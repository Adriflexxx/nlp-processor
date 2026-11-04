"""Cas d'usage « predire » : top 3, niveau de confiance et avis de chaque modèle (ADR-0017).

Utilise la configuration de prédiction (`MODE`, `MODELES`), les modèles finaux et le
combinateur sauvegardés du dernier jeu évalué, et les seuils de son évaluation (ou ceux
du `.env`). Pour la branche embedding, la fiche est produite à l'unité (lot de 1, même
consigne qu'à l'ingestion), puis vectorisée. Chaque prédiction est journalisée.
"""

from __future__ import annotations

import asyncio
from dataclasses import asdict, dataclass, field
from typing import Any

import numpy as np

from demandes.application.entrainer import dossier_jeu
from demandes.application.evaluer import chemin_combinateur
from demandes.apprentissage.combinateurs import CombinateurAjuste, desaccord
from demandes.apprentissage.modeles_base import aligner
from demandes.apprentissage.nettoyage import nettoyer_mail
from demandes.domaine.combinaison import MODELES_EMB, Combinaison, Mode
from demandes.domaine.controles import reparer_texte
from demandes.domaine.decision import Seuils, niveau_confiance
from demandes.domaine.fiche import depouiller_reponse, texte_a_vectoriser
from demandes.ports.artefacts import StockageArtefacts
from demandes.ports.depots import DepotEvaluations, DepotPredictions
from demandes.ports.iag import ErreurIag, GenerateurFiches, Vectoriseur


class ConfigurationIndisponible(RuntimeError):
    pass


@dataclass(frozen=True, slots=True)
class ParametresPrediction:
    mode: str
    modeles: tuple[str, ...]
    mail_max_caracteres: int
    seuil_haut: float | None
    seuil_moyen: float | None
    desaccord_bloque: bool


@dataclass(slots=True)
class ResultatPrediction:
    id: int
    top3: list[dict[str, Any]]
    niveau: str
    desaccord: bool
    avis: list[dict[str, Any]]
    configuration: dict[str, Any]
    fiche: dict[str, Any] | None = None
    remarques: list[str] = field(default_factory=list)

    def en_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(slots=True)
class _Charge:
    empreinte_jeu: str
    titres: list[str]
    modeles: dict[str, Any]
    combinateur: CombinateurAjuste
    seuils: Seuils
    nom: str


class Prediction:
    def __init__(
        self,
        evaluations: DepotEvaluations,
        predictions: DepotPredictions,
        artefacts: StockageArtefacts,
        generateur: GenerateurFiches,
        vectoriseur: Vectoriseur,
        parametres: ParametresPrediction,
    ) -> None:
        self.evaluations = evaluations
        self.predictions = predictions
        self.artefacts = artefacts
        self.generateur = generateur
        self.vectoriseur = vectoriseur
        self.parametres = parametres
        self.combinaison = Combinaison(Mode(parametres.mode), tuple(parametres.modeles))
        self._charge: _Charge | None = None

    def charger(self, forcer: bool = False) -> _Charge:
        """Modèles et combinateur du dernier jeu évalué, gardés en mémoire entre deux prédictions."""
        evaluations = self.evaluations.lister_evaluations()
        evaluation = next((e for e in evaluations if e["nom"] == self.combinaison.nom), None)
        if evaluation is None:
            raise ConfigurationIndisponible(
                f"la combinaison {self.combinaison.nom} (MODE / MODELES) n'a pas été évaluée sur le dernier jeu : "
                f"lancer « evaluer --mode {self.parametres.mode} --modeles {','.join(self.parametres.modeles)} »"
            )
        empreinte = evaluation["empreinte_jeu"]
        if self._charge is not None and not forcer and self._charge.empreinte_jeu == empreinte:
            return self._charge
        base = dossier_jeu(empreinte)
        index = self.artefacts.lire_json(f"{base}/modeles.json")
        modeles = {m: self.artefacts.lire_objet(f"{index[m]['dossier']}/modele.joblib") for m in self.combinaison.modeles}
        p = self.parametres
        if p.seuil_haut is not None and p.seuil_moyen is not None:
            seuils = Seuils(p.seuil_haut, p.seuil_moyen, "manuel")
        else:
            seuils = Seuils(evaluation["seuils"]["haut"], evaluation["seuils"]["moyen"], evaluation["seuils"]["source"])
        self._charge = _Charge(
            empreinte, self.artefacts.lire_json(f"{base}/classes.json"), modeles,
            self.artefacts.lire_objet(chemin_combinateur(empreinte, self.combinaison.nom)), seuils, self.combinaison.nom,
        )
        return self._charge

    async def _vecteur(self, numero: str, texte: str) -> tuple[np.ndarray, dict | None, str | None]:
        """Fiche à l'unité (lot de 1) puis embedding. En échec : ligne de NaN (a priori des Titres)."""
        nan = np.full((1, self.vectoriseur.dimension), np.nan, dtype=np.float32)
        try:
            reponse = await self.generateur.generer([(numero, texte)])
        except ErreurIag as erreur:
            return nan, None, f"fiche IAG en échec : {erreur}"
        fiche = depouiller_reponse(reponse.contenu, [numero]).valides.get(numero)
        if fiche is None:
            return nan, None, "fiche IAG invalide"
        try:
            vecteur = np.asarray(await self.vectoriseur.vectoriser([texte_a_vectoriser(fiche)]), dtype=np.float32)
        except ErreurIag as erreur:
            return nan, fiche, f"embedding en échec : {erreur}"
        norme = np.linalg.norm(vecteur, axis=1, keepdims=True)
        return vecteur / np.where(norme == 0, 1, norme), fiche, None

    def predire(self, mail: str) -> ResultatPrediction:
        charge = self.charger()
        texte = nettoyer_mail(reparer_texte(mail).texte)
        envoye = texte if len(texte) <= self.parametres.mail_max_caracteres else texte[: self.parametres.mail_max_caracteres] + "\n[…]"
        remarques: list[str] = []
        fiche = None
        vecteur = None
        if any(m in MODELES_EMB for m in self.combinaison.modeles):
            vecteur, fiche, probleme = asyncio.run(self._vecteur("NOUVEAU", envoye))
            if probleme:
                remarques.append(f"{probleme} : les modèles embedding donnent la distribution a priori")

        classes = np.arange(len(charge.titres))
        probas = []
        for cle in self.combinaison.modeles:
            modele = charge.modeles[cle]
            entree = vecteur if cle in MODELES_EMB else np.array([texte], dtype=object)
            probas.append(aligner(modele.predict_proba(entree), np.asarray(modele.classes_), classes))
        p = charge.combinateur.combiner(probas)[0]
        en_desaccord = bool(desaccord(probas)[0])
        ordre = np.argsort(-p)[:3]
        top3 = [{"titre": charge.titres[i], "probabilite": round(float(p[i]), 4)} for i in ordre]
        niveau = niveau_confiance(float(p[ordre[0]]), charge.seuils, en_desaccord, self.parametres.desaccord_bloque)
        avis = []
        for cle, pr in zip(self.combinaison.modeles, probas):
            i = int(pr[0].argmax())
            avis.append({"modele": cle, "titre": charge.titres[i], "probabilite": round(float(pr[0][i]), 4)})
        configuration = {
            "nom": charge.nom, "mode": self.combinaison.mode.value, "modeles": list(self.combinaison.modeles),
            "empreinte_jeu": charge.empreinte_jeu,
            "seuils": {"haut": charge.seuils.haut, "moyen": charge.seuils.moyen, "source": charge.seuils.source},
        }
        identifiant = self.predictions.journaliser(mail, configuration, top3, niveau.value, avis)
        return ResultatPrediction(identifiant, top3, niveau.value, en_desaccord, avis, configuration, fiche, remarques)
