"""Lancement et suivi des tâches longues, avec journal d'avancement détaillé."""

from __future__ import annotations

import asyncio
import json
from datetime import datetime
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from demandes.adaptateurs.entrants.api.dependances import conteneur
from demandes.composition import Conteneur

routeur = APIRouter(prefix="/taches", tags=["tâches"])


class TacheSortie(BaseModel):
    id: str
    type: str
    statut: str
    parametres: dict[str, Any]
    progression: float
    etape: str | None
    message: str | None
    resultat: dict[str, Any] | None
    erreur: str | None
    cree_le: datetime | None
    demarre_le: datetime | None
    termine_le: datetime | None


class EntreeJournalSortie(BaseModel):
    id: int
    horodatage: datetime
    niveau: str
    message: str
    progression: float
    etape: str | None
    donnees: dict[str, Any]


class ParametresCharger(BaseModel):
    fichier: str
    nouvelle_reference: bool = False
    # None : suit FICHES_A_L_INGESTION ; false : chargement seul, sans appel à l'IAG.
    avec_fiches: bool | None = None


class ParametresFiches(BaseModel):
    reprendre_echecs: bool = False


class ParametresControle(BaseModel):
    taille: int = 200


class ParametresEntrainer(BaseModel):
    modeles: list[str] | None = None


class ParametresEvaluer(BaseModel):
    mode: str | None = None
    modeles: list[str] | None = None
    temporel: bool = False


def _sortie(tache) -> TacheSortie:
    return TacheSortie(**{champ: getattr(tache, champ) for champ in TacheSortie.model_fields})


def _journal(entree) -> EntreeJournalSortie:
    return EntreeJournalSortie(**{champ: getattr(entree, champ) for champ in EntreeJournalSortie.model_fields})


@routeur.post("/charger", response_model=TacheSortie, status_code=202)
def lancer_chargement(parametres: ParametresCharger, c: Conteneur = Depends(conteneur)) -> TacheSortie:
    """Ingestion d'un export Excel (chemin vu par le service, ex. donnees/export.xlsx), fiches comprises."""
    tache, _ = c.executeur.soumettre("charger", parametres.model_dump())
    return _sortie(tache)


@routeur.post("/fiches", response_model=TacheSortie, status_code=202)
def lancer_fiches(parametres: ParametresFiches, c: Conteneur = Depends(conteneur)) -> TacheSortie:
    """Fiches IAG par lots et embeddings pour les demandes absentes du cache."""
    tache, _ = c.executeur.soumettre("fiches", parametres.model_dump())
    return _sortie(tache)


@routeur.post("/controle-lots", response_model=TacheSortie, status_code=202)
def lancer_controle_lots(parametres: ParametresControle, c: Conteneur = Depends(conteneur)) -> TacheSortie:
    """Contrôle qualité : fiches en lot comparées aux fiches à l'unité sur un échantillon."""
    tache, _ = c.executeur.soumettre("controle_lots", parametres.model_dump())
    return _sortie(tache)


@routeur.post("/entrainer", response_model=TacheSortie, status_code=202)
def lancer_entrainement(parametres: ParametresEntrainer, c: Conteneur = Depends(conteneur)) -> TacheSortie:
    """Validation croisée, prédictions hors pli et modèles finaux (cache par modèle)."""
    tache, _ = c.executeur.soumettre("entrainer", parametres.model_dump())
    return _sortie(tache)


@routeur.post("/evaluer", response_model=TacheSortie, status_code=202)
def lancer_evaluation(parametres: ParametresEvaluer, c: Conteneur = Depends(conteneur)) -> TacheSortie:
    """Les 13 combinaisons, ou une combinaison précise (mode + modeles) ; option temporel."""
    tache, _ = c.executeur.soumettre("evaluer", parametres.model_dump())
    return _sortie(tache)


@routeur.post("/rapport", response_model=TacheSortie, status_code=202)
def lancer_rapport(c: Conteneur = Depends(conteneur)) -> TacheSortie:
    """Rapport Markdown, graphiques et recommandation."""
    tache, _ = c.executeur.soumettre("rapport", {})
    return _sortie(tache)


@routeur.get("", response_model=list[TacheSortie])
def lister(limite: int = Query(50, le=500), c: Conteneur = Depends(conteneur)) -> list[TacheSortie]:
    return [_sortie(t) for t in c.depot_taches.lister(limite)]


@routeur.get("/{tache_id}", response_model=TacheSortie)
def lire(tache_id: str, c: Conteneur = Depends(conteneur)) -> TacheSortie:
    tache = c.depot_taches.lire(tache_id)
    if tache is None:
        raise HTTPException(404, "tâche inconnue")
    return _sortie(tache)


@routeur.get("/{tache_id}/journal", response_model=list[EntreeJournalSortie])
def journal(
    tache_id: str, apres: int = Query(0, description="id de la dernière ligne déjà reçue"), c: Conteneur = Depends(conteneur)
) -> list[EntreeJournalSortie]:
    """Journal d'avancement ; passer `apres` pour ne recevoir que les nouvelles lignes."""
    return [_journal(e) for e in c.depot_taches.lire_journal(tache_id, apres)]


@routeur.get("/{tache_id}/flux")
async def flux(tache_id: str, c: Conteneur = Depends(conteneur)) -> StreamingResponse:
    """Journal en direct (Server-Sent Events) : `curl -N http://localhost:8000/taches/<id>/flux`."""
    if c.depot_taches.lire(tache_id) is None:
        raise HTTPException(404, "tâche inconnue")

    async def evenements():
        dernier = 0
        while True:
            entrees = await asyncio.to_thread(c.depot_taches.lire_journal, tache_id, dernier)
            for e in entrees:
                dernier = e.id
                yield f"id: {e.id}\ndata: {_journal(e).model_dump_json()}\n\n"
            tache = await asyncio.to_thread(c.depot_taches.lire, tache_id)
            if tache.statut in ("terminee", "echec") and not entrees:
                fin = {"statut": tache.statut, "erreur": tache.erreur}
                yield f"event: fin\ndata: {json.dumps(fin, ensure_ascii=False)}\n\n"
                return
            await asyncio.sleep(0.5)

    return StreamingResponse(evenements(), media_type="text/event-stream")
