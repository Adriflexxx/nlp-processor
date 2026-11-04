"""Cas d'usage « entrainer » : validation croisée, prédictions hors pli et modèles finaux (ADR-0014).

Pour chaque modèle de base :
1. recherche de grille en validation croisée (5 plis stratifiés, entraînement seul) ;
2. prédictions hors pli du meilleur paramètre, calculées une seule fois et mises en cache ;
3. modèle final réentraîné sur tout le jeu d'entraînement, et ses probabilités sur le test.

Le cache est indexé par l'empreinte du modèle (jeu, grille, représentation) : relancer
ne recalcule que ce qui a changé. La branche TF-IDF ne demande aucun appel au LLM.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any

import numpy as np
from joblib import Parallel, delayed

from demandes.application.jeu import Jeu, attacher_vecteurs, construire_jeu, hacher
from demandes.apprentissage.modeles_base import (
    EMB,
    TFIDF,
    VERSION_MODELES,
    DefinitionModele,
    aligner,
    definitions,
    dimensions_effectives,
)
from demandes.apprentissage.validation import ajuster, rechercher_grilles
from demandes.domaine.combinaison import TOUS_LES_MODELES
from demandes.ports.artefacts import StockageArtefacts
from demandes.ports.depots import DepotCorpus, DepotVecteurs
from demandes.ports.suivi import Suivi

ETAPES = ["jeu", "validation croisée", "modèles finaux"]


@dataclass(frozen=True, slots=True)
class ParametresEntrainement:
    min_par_titre: int
    taille_test: float
    n_plis: int
    graine: int
    n_processus: int
    tfidf_caracteres: bool
    acp_dimensions: list[int]


def dossier_jeu(empreinte_jeu: str) -> str:
    return f"entrainement/{empreinte_jeu[:16]}"


@dataclass(slots=True)
class ModeleEntraine:
    cle: str
    empreinte: str
    dossier: str
    meilleurs_params: dict[str, Any]
    score_cv_top1: float
    logloss_cv: float
    en_cache: bool

    def en_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(slots=True)
class ResultatEntrainement:
    jeu: dict[str, Any]
    modeles: dict[str, dict[str, Any]]
    ignores: dict[str, str] = field(default_factory=dict)

    def en_dict(self) -> dict[str, Any]:
        return asdict(self)


def _final(definition: DefinitionModele, params, graine, options, X_entr, y_entr, X_test, n_classes):
    modele = ajuster(definition, params, graine, options, X_entr, y_entr)
    probas = aligner(modele.predict_proba(X_test), np.asarray(modele.classes_), np.arange(n_classes))
    return modele, probas


class Entrainement:
    def __init__(
        self,
        corpus: DepotCorpus,
        vecteurs: DepotVecteurs,
        artefacts: StockageArtefacts,
        parametres: ParametresEntrainement,
        empreinte_vecteur: str,
    ) -> None:
        self.corpus = corpus
        self.vecteurs = vecteurs
        self.artefacts = artefacts
        self.parametres = parametres
        self.empreinte_vecteur = empreinte_vecteur

    # --- Jeu -----------------------------------------------------------------

    def preparer_jeu(self) -> Jeu:
        p = self.parametres
        jeu = construire_jeu(self.corpus.lister_demandes(), p.min_par_titre, p.taille_test, p.n_plis, p.graine)
        numeros, matrice = self.vecteurs.lire_vecteurs(self.empreinte_vecteur, list(jeu.numeros))
        attacher_vecteurs(jeu, numeros, matrice, self.empreinte_vecteur)
        return jeu

    def definitions(self, jeu: Jeu) -> dict[str, DefinitionModele]:
        if jeu.vecteurs is None:
            return definitions([None])
        plus_petit_pli = min(len(entr) for entr, _ in jeu.plis)
        return definitions(dimensions_effectives(self.parametres.acp_dimensions, jeu.vecteurs.shape[1], plus_petit_pli))

    def options(self) -> dict[str, Any]:
        return {"tfidf_caracteres": self.parametres.tfidf_caracteres}

    def empreinte_modele(self, jeu: Jeu, definition: DefinitionModele) -> str:
        contenu: dict[str, Any] = {
            "jeu": jeu.empreinte, "cle": definition.cle, "grille": list(definition.grille), "version": VERSION_MODELES,
        }
        if definition.representation == TFIDF:
            contenu["tfidf_caracteres"] = self.parametres.tfidf_caracteres
        else:
            avec = [] if jeu.vecteurs is None else list(jeu.numeros[~np.isnan(jeu.vecteurs).any(axis=1)])
            contenu["vecteurs"] = {"empreinte": jeu.empreinte_vecteur, "numeros": hacher(avec)}
        return hacher(contenu)

    def dossier_modele(self, jeu: Jeu, cle: str, empreinte: str) -> str:
        return f"{dossier_jeu(jeu.empreinte)}/modeles/{cle}-{empreinte[:16]}"

    def _en_cache(self, dossier: str) -> bool:
        return all(
            self.artefacts.existe(f"{dossier}/{f}") for f in ("hors_pli.npy", "test.npy", "modele.joblib", "grille.json")
        )

    def index_modeles(self, jeu: Jeu) -> dict[str, dict[str, Any]]:
        chemin = f"{dossier_jeu(jeu.empreinte)}/modeles.json"
        return self.artefacts.lire_json(chemin) if self.artefacts.existe(chemin) else {}

    # --- Exécution -------------------------------------------------------------

    def executer(self, suivi: Suivi, modeles: list[str] | None = None) -> ResultatEntrainement:
        p = self.parametres
        suivi.demarrer(ETAPES)
        suivi.etape("jeu")
        jeu = self.preparer_jeu()
        suivi.info(
            f"Jeu {jeu.empreinte[:16]} : {len(jeu.y)} demandes, {jeu.n_classes} Titres "
            f"({len(jeu.exclus)} exclus sous {p.min_par_titre}), entraînement {len(jeu.entrainement)}, "
            f"test {len(jeu.test)}, {p.n_plis} plis ; vecteurs : {jeu.n_avec_vecteur}/{len(jeu.y)}",
            jeu=jeu.resume(),
        )
        base = dossier_jeu(jeu.empreinte)
        self.artefacts.ecrire_json(f"{base}/jeu.json", jeu.resume())
        self.artefacts.ecrire_json(f"{base}/classes.json", jeu.titres)
        self.artefacts.ecrire_json(
            f"{base}/decoupage.json",
            {"entrainement": jeu.numeros[jeu.entrainement].tolist(), "test": jeu.numeros[jeu.test].tolist()},
        )

        demandes = list(modeles or TOUS_LES_MODELES)
        toutes = self.definitions(jeu)
        ignores: dict[str, str] = {}
        if jeu.vecteurs is None:
            for cle in demandes:
                if toutes[cle].representation == EMB:
                    ignores[cle] = "aucun vecteur pour la configuration courante : lancer d'abord les fiches"
            if ignores:
                suivi.alerte(f"Modèles embedding ignorés ({', '.join(ignores)}) : aucun vecteur en base")
        retenus = {cle: toutes[cle] for cle in demandes if cle not in ignores}

        index = self.index_modeles(jeu)
        a_calculer: dict[str, DefinitionModele] = {}
        resultats: dict[str, ModeleEntraine] = {}
        for cle, definition in retenus.items():
            empreinte = self.empreinte_modele(jeu, definition)
            dossier = self.dossier_modele(jeu, cle, empreinte)
            if self._en_cache(dossier):
                grille = self.artefacts.lire_json(f"{dossier}/grille.json")
                resultats[cle] = ModeleEntraine(
                    cle, empreinte, dossier, grille["meilleurs_params"], grille["score_cv_top1"], grille["logloss_cv"], True
                )
            else:
                a_calculer[cle] = definition
        if resultats:
            suivi.info(f"En cache : {', '.join(resultats)} (aucun recalcul)")

        suivi.etape("validation croisée")
        if a_calculer:
            y_entr = jeu.y[jeu.entrainement]
            entrees = jeu.entrees(jeu.entrainement)
            n_taches = sum(len(d.grille) for d in a_calculer.values()) * len(jeu.plis)
            suivi.info(
                f"Validation croisée de {', '.join(a_calculer)} : {n_taches} ajustements sur {p.n_processus} processus"
            )
            grilles = rechercher_grilles(
                a_calculer, entrees, y_entr, jeu.plis, jeu.n_classes, p.graine, self.options(), p.n_processus,
                rappel=lambda fait, total: suivi.avancer(fait, total, "ajustements (modèle × paramètre × pli)"),
            )
            for cle, g in grilles.items():
                suivi.info(
                    f"{cle} : meilleur {g.meilleurs_params}, top 1 hors pli {g.scores[g.meilleur]['top1']:.3f}",
                    scores=[{**prm, **sc} for prm, sc in zip(g.params, g.scores)],
                )

            suivi.etape("modèles finaux")
            entrees_test = jeu.entrees(jeu.test)
            finals = Parallel(n_jobs=max(1, min(p.n_processus, len(a_calculer))), backend="loky")(
                delayed(_final)(
                    a_calculer[cle], grilles[cle].meilleurs_params, p.graine, self.options(),
                    entrees[a_calculer[cle].representation], y_entr,
                    entrees_test[a_calculer[cle].representation], jeu.n_classes,
                )
                for cle in a_calculer
            )
            for cle, (modele, probas_test) in zip(a_calculer, finals):
                g = grilles[cle]
                empreinte = self.empreinte_modele(jeu, a_calculer[cle])
                dossier = self.dossier_modele(jeu, cle, empreinte)
                self.artefacts.ecrire_matrice(f"{dossier}/hors_pli.npy", g.hors_pli.astype(np.float32))
                self.artefacts.ecrire_matrice(f"{dossier}/test.npy", probas_test.astype(np.float32))
                self.artefacts.ecrire_objet(f"{dossier}/modele.joblib", modele)
                grille_json = {
                    "cle": cle, "empreinte": empreinte, "meilleurs_params": g.meilleurs_params,
                    "score_cv_top1": g.scores[g.meilleur]["top1"], "logloss_cv": g.scores[g.meilleur]["logloss"],
                    "grille": [{**prm, **sc} for prm, sc in zip(g.params, g.scores)],
                }
                self.artefacts.ecrire_json(f"{dossier}/grille.json", grille_json)
                resultats[cle] = ModeleEntraine(
                    cle, empreinte, dossier, g.meilleurs_params, grille_json["score_cv_top1"], grille_json["logloss_cv"], False
                )
        else:
            suivi.etape("modèles finaux")

        for cle, r in resultats.items():
            index[cle] = r.en_dict()
        self.artefacts.ecrire_json(f"{base}/modeles.json", index)
        resultat = ResultatEntrainement(jeu.resume(), {c: r.en_dict() for c, r in resultats.items()}, ignores)
        suivi.terminer(
            "Entraînement terminé : "
            + ", ".join(f"{c} {r.score_cv_top1:.3f}" for c, r in sorted(resultats.items(), key=lambda x: -x[1].score_cv_top1))
            + " (top 1 hors pli)"
        )
        return resultat
