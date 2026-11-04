"""Cas d'usage « evaluer » : combinaisons, seuils et mesures (ADR-0015).

Pour chaque combinaison (les 13 standard, ou une combinaison choisie) :
- le combinateur (moyenne ou méta) est réglé sur les prédictions hors pli en cache :
  quelques secondes, aucun modèle de base n'est réentraîné ;
- les seuils sont choisis sur la courbe couverture / précision hors pli (jamais sur le test) ;
- les mesures sont calculées hors pli (entraînement) et sur le test, chacune pour
  l'ensemble, les mails issus d'un template et les mails libres.
Options : contrôle dans le temps (11 premiers mois / dernier mois) et volet `rl_emb` du
contrôle lot / unité.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from datetime import datetime
from typing import Any

import numpy as np
from joblib import Parallel, delayed

from demandes.application.entrainer import Entrainement, dossier_jeu
from demandes.application.jeu import Jeu, sans_nan
from demandes.apprentissage.combinateurs import CombinateurAjuste, desaccord, moyenne, regler_combinateur
from demandes.apprentissage.metriques import (
    courbe_couverture,
    fiabilite,
    matrice_confusion,
    mesures_par_segment,
    paires_confondues,
    scores_par_titre,
)
from demandes.apprentissage.modeles_base import aligner
from demandes.apprentissage.seuils import bilan_decisions, choisir_seuils
from demandes.apprentissage.validation import ajuster
from demandes.domaine.combinaison import MODELES_EMB, MODELES_TFIDF, Combinaison, Mode, combinaisons_standard
from demandes.domaine.decision import Seuils
from demandes.domaine.fiche import texte_a_vectoriser
from demandes.ports.artefacts import StockageArtefacts
from demandes.ports.depots import DepotEvaluations, DepotFiches
from demandes.ports.iag import Vectoriseur
from demandes.ports.suivi import Suivi


class ModelesNonEntraines(RuntimeError):
    pass


@dataclass(frozen=True, slots=True)
class ParametresEvaluation:
    type_meta: str
    cible_haut: float
    cible_top3_moyen: float
    desaccord_bloque: bool
    seuil_haut: float | None
    seuil_moyen: float | None
    graine: int
    n_processus: int


@dataclass(slots=True)
class Predictions:
    """Probabilités en cache d'un modèle de base."""

    hors_pli: np.ndarray
    test: np.ndarray
    info: dict[str, Any]


def chemin_combinateur(empreinte_jeu: str, nom: str) -> str:
    return f"{dossier_jeu(empreinte_jeu)}/combinaisons/{nom}.joblib"


def chemin_evaluation(empreinte_jeu: str, nom: str) -> str:
    return f"{dossier_jeu(empreinte_jeu)}/evaluations/{nom}.json"


class Evaluation:
    def __init__(
        self,
        entrainement: Entrainement,
        evaluations: DepotEvaluations,
        artefacts: StockageArtefacts,
        parametres: ParametresEvaluation,
        fiches: DepotFiches | None = None,
        vectoriseur: Vectoriseur | None = None,
        empreinte_fiche: str | None = None,
    ) -> None:
        self.entrainement = entrainement
        self.evaluations = evaluations
        self.artefacts = artefacts
        self.parametres = parametres
        self.fiches = fiches
        self.vectoriseur = vectoriseur
        self.empreinte_fiche = empreinte_fiche

    # --- Chargement -------------------------------------------------------------

    def charger_predictions(self, jeu: Jeu) -> dict[str, Predictions]:
        """Prédictions en cache des modèles dont l'empreinte correspond au jeu et à la configuration courante."""
        index = self.entrainement.index_modeles(jeu)
        definitions = self.entrainement.definitions(jeu)
        sortie: dict[str, Predictions] = {}
        for cle, info in index.items():
            if cle not in definitions or info["empreinte"] != self.entrainement.empreinte_modele(jeu, definitions[cle]):
                continue  # périmé : grille, vecteurs ou options ont changé
            dossier = info["dossier"]
            if not self.artefacts.existe(f"{dossier}/hors_pli.npy"):
                continue
            sortie[cle] = Predictions(
                self.artefacts.lire_matrice(f"{dossier}/hors_pli.npy").astype(np.float64),
                self.artefacts.lire_matrice(f"{dossier}/test.npy").astype(np.float64),
                info,
            )
        return sortie

    def seuils(self, hors_pli: np.ndarray, y: np.ndarray) -> Seuils:
        p = self.parametres
        if p.seuil_haut is not None and p.seuil_moyen is not None:
            return Seuils(p.seuil_haut, p.seuil_moyen, "manuel")
        return choisir_seuils(hors_pli, y, p.cible_haut, p.cible_top3_moyen)

    # --- Une combinaison --------------------------------------------------------

    def evaluer_combinaison(self, jeu: Jeu, combi: Combinaison, preds: dict[str, Predictions]) -> dict[str, Any]:
        p = self.parametres
        manquants = [m for m in combi.modeles if m not in preds]
        if manquants:
            raise ModelesNonEntraines(f"{combi.nom} : modèles non entraînés {manquants} (lancer « entrainer »)")
        y_entr, y_test = jeu.y[jeu.entrainement], jeu.y[jeu.test]
        tpl_entr, tpl_test = jeu.template[jeu.entrainement], jeu.template[jeu.test]
        hors_pli = [preds[m].hors_pli for m in combi.modeles]
        test = [preds[m].test for m in combi.modeles]
        combinateur, hp_comb = regler_combinateur(
            combi.mode.value, combi.modeles, hors_pli, y_entr, jeu.plis, jeu.n_classes, p.type_meta, p.graine,
            p.n_processus,
        )
        test_comb = combinateur.combiner(test)
        des_entr, des_test = desaccord(hors_pli), desaccord(test)
        seuils = self.seuils(hp_comb, y_entr)

        paires = paires_confondues(test_comb, y_test, jeu.titres, 15)
        confondus = []
        for paire in paires:
            for t in (paire["vrai"], paire["predit"]):
                if t not in confondus:
                    confondus.append(t)
        confondus = confondus[:15]
        indices_confondus = [jeu.titres.index(t) for t in confondus]

        self.artefacts.ecrire_objet(chemin_combinateur(jeu.empreinte, combi.nom), combinateur)
        return sans_nan(
            {
                "nom": combi.nom,
                "libelle": combi.libelle or combi.nom,
                "mode": combi.mode.value,
                "modeles": list(combi.modeles),
                "fait_appel_au_llm": combi.fait_appel_au_llm,
                "cout": combi.cout,
                "parametres": combinateur.params,
                "seuils": {"haut": seuils.haut, "moyen": seuils.moyen, "source": seuils.source},
                "cv": mesures_par_segment(hp_comb, y_entr, tpl_entr, jeu.n_classes),
                "test": mesures_par_segment(test_comb, y_test, tpl_test, jeu.n_classes),
                "decisions_cv": bilan_decisions(hp_comb, y_entr, des_entr, seuils, p.desaccord_bloque),
                "decisions_test": bilan_decisions(test_comb, y_test, des_test, seuils, p.desaccord_bloque),
                "part_desaccord_test": float(des_test.mean()),
                "courbe_test": courbe_couverture(test_comb, y_test),
                "courbe_test_libre": courbe_couverture(test_comb[~tpl_test], y_test[~tpl_test]),
                "fiabilite_test": fiabilite(test_comb, y_test),
                "paires_confondues": paires,
                "confusion": {"titres": confondus, "matrice": matrice_confusion(test_comb, y_test, indices_confondus)},
                "par_titre": scores_par_titre(test_comb, y_test, jeu.titres),
                "evalue_le": datetime.now().isoformat(timespec="seconds"),
            }
        )

    # --- Exécution ----------------------------------------------------------------

    def executer(
        self, suivi: Suivi, combinaisons: list[Combinaison] | None = None, temporel: bool = False
    ) -> dict[str, Any]:
        etapes = ["prédictions en cache", "combinaisons"] + (["contrôle dans le temps"] if temporel else []) + [
            "contrôle lot / unité"
        ]
        suivi.demarrer(etapes)
        suivi.etape("prédictions en cache")
        jeu = self.entrainement.preparer_jeu()
        preds = self.charger_predictions(jeu)
        if not preds:
            raise ModelesNonEntraines("aucun modèle entraîné pour ce jeu : lancer d'abord « entrainer »")
        suivi.info(f"Jeu {jeu.empreinte[:16]} ; modèles disponibles : {', '.join(preds)}")

        if combinaisons is None:
            meilleur = lambda groupe: max(  # noqa: E731
                (m for m in groupe if m in preds), key=lambda m: preds[m].info["score_cv_top1"], default=None
            )
            m_tfidf, m_emb = meilleur(MODELES_TFIDF), meilleur(MODELES_EMB)
            standard = combinaisons_standard(m_tfidf or "svm_tfidf", m_emb or "rl_emb")
            combinaisons = [c for c in standard if all(m in preds for m in c.modeles)]
            ecartees = [c.libelle for c in standard if c not in combinaisons]
            if ecartees:
                suivi.alerte(f"{len(ecartees)} combinaisons non évaluables (modèles non entraînés) : {', '.join(ecartees)}")

        suivi.etape("combinaisons")
        resultats: list[dict[str, Any]] = []
        for i, combi in enumerate(combinaisons, start=1):
            evaluation = self.evaluer_combinaison(jeu, combi, preds)
            self.artefacts.ecrire_json(chemin_evaluation(jeu.empreinte, combi.nom), evaluation)
            self.evaluations.enregistrer_evaluation(jeu.empreinte, combi.nom, evaluation)
            resultats.append(evaluation)
            t = evaluation["test"]
            suivi.avancer(i, len(combinaisons), f"{combi.libelle or combi.nom} : top 1 test {t['ensemble']['top1']:.3f}")

        temporel_res = None
        if temporel:
            suivi.etape("contrôle dans le temps")
            temporel_res = self.controle_temporel(jeu, preds, resultats, suivi)
            if temporel_res:
                self.artefacts.ecrire_json(chemin_evaluation(jeu.empreinte, "temporel"), temporel_res)
                self.evaluations.enregistrer_evaluation(jeu.empreinte, "temporel", temporel_res)

        suivi.etape("contrôle lot / unité")
        lot_unite = self.controle_lot_unite(jeu, preds, suivi)
        if lot_unite:
            self.artefacts.ecrire_json(chemin_evaluation(jeu.empreinte, "controle_lots"), lot_unite)
            self.evaluations.enregistrer_evaluation(jeu.empreinte, "controle_lots", lot_unite)

        classement = sorted(resultats, key=lambda e: -e["test"]["ensemble"]["top1"])
        suivi.terminer(
            f"{len(resultats)} combinaisons évaluées ; meilleure en top 1 test : "
            f"{classement[0]['libelle']} ({classement[0]['test']['ensemble']['top1']:.3f})"
        )
        return {
            "jeu": jeu.resume(),
            "classement": [
                {
                    "nom": e["nom"], "libelle": e["libelle"], "top1_test": e["test"]["ensemble"]["top1"],
                    "top3_test": e["test"]["ensemble"]["top3"], "top1_libre": e["test"]["libre"].get("top1"),
                    "seuils": e["seuils"],
                }
                for e in classement
            ],
            "temporel": temporel_res is not None,
            "controle_lots": lot_unite is not None,
        }

    # --- Contrôle dans le temps -----------------------------------------------------

    def controle_temporel(self, jeu: Jeu, preds: dict[str, Predictions], resultats: list[dict], suivi: Suivi):
        dates = [d for d in jeu.dates if d is not None]
        if len(dates) < len(jeu.dates) * 0.9:
            suivi.alerte("Contrôle dans le temps impossible : dates absentes (COLONNE_DATE)")
            return None
        derniere = max(dates)
        debut_mois = datetime(derniere.year, derniere.month, 1, tzinfo=derniere.tzinfo)
        avant = np.array([d is not None and d < debut_mois for d in jeu.dates])
        dernier_mois = np.array([d is not None and d >= debut_mois for d in jeu.dates])
        if avant.sum() < 50 or dernier_mois.sum() < 20:
            suivi.alerte("Contrôle dans le temps impossible : pas assez de demandes avant ou pendant le dernier mois")
            return None
        entr, test = np.where(avant)[0], np.where(dernier_mois)[0]
        suivi.info(f"Entraînement sur {len(entr)} demandes avant {debut_mois:%Y-%m}, test sur {len(test)} du dernier mois")
        definitions = self.entrainement.definitions(jeu)
        cles = list(preds)
        options = self.entrainement.options()
        X_entr, X_test = jeu.entrees(entr), jeu.entrees(test)

        probas = dict(zip(cles, Parallel(n_jobs=max(1, min(self.parametres.n_processus, len(cles))), backend="loky")(
            delayed(_refaire_et_predire)(
                definitions[c], preds[c].info["meilleurs_params"], self.parametres.graine, options,
                X_entr[definitions[c].representation], jeu.y[entr], X_test[definitions[c].representation], jeu.n_classes,
            )
            for c in cles
        )))
        y_t, tpl_t = jeu.y[test], jeu.template[test]
        sortie = []
        for e in resultats:
            if e["mode"] == Mode.META.value:
                continue  # le méta demanderait de refaire toutes les prédictions hors pli sur cette période
            liste = [probas[m] for m in e["modeles"]]
            comb = liste[0] if e["mode"] == "seul" else moyenne(liste, tuple(e["parametres"]["poids"]))
            sortie.append({"nom": e["nom"], "libelle": e["libelle"], "test": mesures_par_segment(comb, y_t, tpl_t, jeu.n_classes)})
        titres_nouveaux = sorted({jeu.titres[i] for i in set(y_t) - set(jeu.y[entr])})
        return sans_nan({
            "periode_test": f"{debut_mois:%Y-%m}",
            "n_entrainement": int(len(entr)),
            "n_test": int(len(test)),
            "titres_absents_avant": titres_nouveaux,
            "combinaisons": sortie,
        })

    # --- Contrôle lot / unité : rl_emb -----------------------------------------------

    def controle_lot_unite(self, jeu: Jeu, preds: dict[str, Predictions], suivi: Suivi):
        if not (self.fiches and self.vectoriseur and self.empreinte_fiche) or "rl_emb" not in preds:
            suivi.info("Volet rl_emb du contrôle lot / unité : sans objet (rl_emb non entraîné)")
            return None
        unite = self.fiches.lire_controle(self.empreinte_fiche)
        position_test = {n: i for i, n in enumerate(jeu.numeros[jeu.test])}
        communs = sorted(n for n in unite if n in position_test)
        if not communs:
            suivi.info("Volet rl_emb du contrôle lot / unité : aucune fiche à l'unité sur le jeu de test (lancer controle-lots)")
            return None
        textes = [texte_a_vectoriser(unite[n].fiche) for n in communs]
        vecteurs = np.asarray(asyncio.run(self.vectoriseur.vectoriser(textes)), dtype=np.float32)
        vecteurs /= np.where(np.linalg.norm(vecteurs, axis=1, keepdims=True) == 0, 1, np.linalg.norm(vecteurs, axis=1, keepdims=True))
        modele = self.artefacts.lire_objet(f"{preds['rl_emb'].info['dossier']}/modele.joblib")
        p_unite = aligner(modele.predict_proba(vecteurs), np.asarray(modele.classes_), np.arange(jeu.n_classes))
        lignes = [position_test[n] for n in communs]
        p_lot = preds["rl_emb"].test[lignes]
        y = jeu.y[jeu.test][lignes]
        resultat = {
            "n": len(communs),
            "top1_fiches_en_lot": float((p_lot.argmax(axis=1) == y).mean()),
            "top1_fiches_a_l_unite": float((p_unite.argmax(axis=1) == y).mean()),
            "accord_top1": float((p_lot.argmax(axis=1) == p_unite.argmax(axis=1)).mean()),
        }
        resultat["ecart"] = resultat["top1_fiches_a_l_unite"] - resultat["top1_fiches_en_lot"]
        suivi.info(
            f"rl_emb sur {len(communs)} demandes de test : top 1 {resultat['top1_fiches_en_lot']:.3f} (fiches en lot) "
            f"contre {resultat['top1_fiches_a_l_unite']:.3f} (fiches à l'unité)",
            **resultat,
        )
        return resultat


def _refaire_et_predire(definition, params, graine, options, X_entr, y_entr, X_test, n_classes) -> np.ndarray:
    """Réentraîne un modèle avec ses paramètres retenus et prédit (exécuté dans un processus de travail)."""
    modele = ajuster(definition, params, graine, options, X_entr, y_entr)
    return aligner(modele.predict_proba(X_test), np.asarray(modele.classes_), np.arange(n_classes))


def charger_combinateur(artefacts: StockageArtefacts, empreinte_jeu: str, nom: str) -> CombinateurAjuste:
    return artefacts.lire_objet(chemin_combinateur(empreinte_jeu, nom))
