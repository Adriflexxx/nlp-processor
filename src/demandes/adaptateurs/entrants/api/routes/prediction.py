"""Prédiction d'un nouveau mail, retour de l'opérateur, évaluations et rapport."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import PlainTextResponse
from pydantic import BaseModel

from demandes.adaptateurs.entrants.api.dependances import conteneur
from demandes.application.predire import ConfigurationIndisponible
from demandes.application.retours import PredictionInconnue
from demandes.composition import Conteneur

routeur = APIRouter(tags=["prédiction"])


class Mail(BaseModel):
    mail: str


class Retour(BaseModel):
    titre_retenu: str
    operateur: str | None = None


@routeur.post("/predire")
def predire(entree: Mail, c: Conteneur = Depends(conteneur)) -> dict[str, Any]:
    """Top 3 (Titre, probabilité), niveau de confiance (haut, moyen, aucun) et avis de chaque modèle de base."""
    if not entree.mail.strip():
        raise HTTPException(422, "mail vide")
    try:
        return c.prediction.predire(entree.mail).en_dict()
    except ConfigurationIndisponible as erreur:
        raise HTTPException(409, str(erreur)) from erreur


@routeur.post("/predictions/{prediction_id}/retour")
def retour(prediction_id: int, entree: Retour, c: Conteneur = Depends(conteneur)) -> dict[str, Any]:
    """Titre retenu par l'opérateur (boucle de retour)."""
    try:
        return c.retours.enregistrer(prediction_id, entree.titre_retenu, entree.operateur)
    except PredictionInconnue as erreur:
        raise HTTPException(404, str(erreur)) from erreur
    except ValueError as erreur:
        raise HTTPException(422, str(erreur)) from erreur


@routeur.get("/predictions/{prediction_id}")
def lire_prediction(prediction_id: int, c: Conteneur = Depends(conteneur)) -> dict[str, Any]:
    p = c.depot_predictions.lire(prediction_id)
    if p is None:
        raise HTTPException(404, "prédiction inconnue")
    return {k: getattr(p, k) for k in p.__dataclass_fields__}


@routeur.get("/evaluations", tags=["évaluation"])
def evaluations(c: Conteneur = Depends(conteneur)) -> list[dict[str, Any]]:
    """Synthèse des évaluations du dernier jeu évalué."""
    sortie = []
    for e in c.depot_evaluations.lister_evaluations():
        if "test" not in e:
            sortie.append({"nom": e["nom"], **{k: v for k, v in e.items() if k not in ("nom",)}})
            continue
        sortie.append({
            "nom": e["nom"], "libelle": e["libelle"], "mode": e["mode"], "modeles": e["modeles"],
            "fait_appel_au_llm": e["fait_appel_au_llm"], "seuils": e["seuils"], "test": e["test"],
            "decisions_test": e["decisions_test"], "empreinte_jeu": e["empreinte_jeu"],
        })
    return sortie


@routeur.get("/rapport", tags=["évaluation"], response_class=PlainTextResponse)
def rapport(c: Conteneur = Depends(conteneur)) -> str:
    """Dernier rapport Markdown produit (les graphiques sont dans le même dossier d'artefacts)."""
    rapports = sorted(c.artefacts.racine.glob("rapports/*/rapport.md"), key=lambda p: p.stat().st_mtime)
    if not rapports:
        raise HTTPException(404, "aucun rapport : lancer POST /taches/rapport")
    return rapports[-1].read_text(encoding="utf-8")
