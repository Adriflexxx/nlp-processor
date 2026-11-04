from __future__ import annotations

from fastapi import Request

from demandes.composition import Conteneur


def conteneur(request: Request) -> Conteneur:
    return request.app.state.conteneur
