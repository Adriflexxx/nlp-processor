"""Dépôt des exports, consultation du corpus chargé et de la référence des Titres."""

from __future__ import annotations

import re
import shutil
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, UploadFile

from demandes.adaptateurs.entrants.api.dependances import conteneur
from demandes.composition import Conteneur

routeur = APIRouter(tags=["corpus"])


@routeur.post("/fichiers", status_code=201)
def deposer(fichier: UploadFile, c: Conteneur = Depends(conteneur)) -> dict[str, str]:
    """Dépose un export Excel dans le dossier des données ; renvoie le chemin à passer à /taches/charger."""
    nom = re.sub(r"[^\w.\-]", "_", Path(fichier.filename or "export.xlsx").name)
    if not nom.lower().endswith((".xlsx", ".xlsm")):
        raise HTTPException(422, "un fichier .xlsx est attendu")
    dossier = Path(c.settings.dossier_donnees)
    dossier.mkdir(parents=True, exist_ok=True)
    cible = dossier / nom
    with cible.open("wb") as sortie:
        shutil.copyfileobj(fichier.file, sortie)
    return {"fichier": str(cible)}


@routeur.get("/fichiers")
def lister_fichiers(c: Conteneur = Depends(conteneur)) -> list[str]:
    dossier = Path(c.settings.dossier_donnees)
    return sorted(str(p) for p in dossier.glob("*.xls*")) if dossier.exists() else []


@routeur.get("/corpus")
def dernier_import(c: Conteneur = Depends(conteneur)) -> dict[str, Any]:
    """Bilan du dernier chargement."""
    info = c.depot_corpus.dernier_import()
    if info is None:
        raise HTTPException(404, "aucun export chargé")
    return {
        "import_id": info.id,
        "fichier": info.fichier,
        "charge_le": info.charge_le,
        "nb_lignes": info.nb_lignes,
        "nb_retenues": info.nb_retenues,
        "nb_ecartees": info.nb_ecartees,
        "bilan": info.bilan,
    }


@routeur.get("/referentiel")
def referentiel(c: Conteneur = Depends(conteneur)) -> list[dict[str, Any]]:
    """Référence figée des Titres."""
    return [
        {"titre": e.titre, "nb_demandes": e.nb_demandes, "premiere_date": e.premiere_date, "derniere_date": e.derniere_date}
        for e in c.depot_referentiel.lire_reference()
    ]
