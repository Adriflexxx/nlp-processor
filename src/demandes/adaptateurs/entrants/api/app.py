"""API FastAPI, sans authentification (environnement de test uniquement, ADR-0005).

Lancement : uv run uvicorn demandes.adaptateurs.entrants.api.app:app --reload
"""

from __future__ import annotations

from contextlib import asynccontextmanager

from fastapi import FastAPI

from demandes.adaptateurs.entrants.api.routes import corpus, prediction, taches
from demandes.composition import Conteneur, configurer_journal


def creer_app(conteneur: Conteneur | None = None) -> FastAPI:
    @asynccontextmanager
    async def cycle_de_vie(app: FastAPI):
        c = conteneur or Conteneur()
        configurer_journal(c.settings.niveau_log)
        c.migrer()
        c.depot_taches.marquer_interrompues()
        app.state.conteneur = c
        yield
        c.fermer()

    app = FastAPI(
        title="Demandes ITZME : classification du Titre",
        description="Banc d'essai. Pas d'authentification : ne pas exposer hors d'un environnement de test.",
        version="0.1.0",
        lifespan=cycle_de_vie,
    )

    @app.get("/sante", tags=["service"])
    def sante() -> dict[str, str]:
        return {"statut": "ok"}

    app.include_router(taches.routeur)
    app.include_router(corpus.routeur)
    app.include_router(prediction.routeur)
    return app


app = creer_app()
