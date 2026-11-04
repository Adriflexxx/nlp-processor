"""Ports vers l'IAG (fiches) et le modèle d'embedding. Appels asynchrones (ADR-0004)."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from typing import Protocol


@dataclass(frozen=True, slots=True)
class ReponseIag:
    contenu: str | None  # texte JSON renvoyé
    tronquee: bool  # finish_reason == "length" : la sortie a été coupée
    duree_ms: int
    jetons_entree: int | None = None
    jetons_sortie: int | None = None


class ErreurIag(RuntimeError):
    """Échec de l'appel après les reprises réseau du client (délai, 5xx, connexion)."""


class GenerateurFiches(Protocol):
    @property
    def modele(self) -> str:
        """Nom du modèle, tel qu'il entre dans l'empreinte (« mock:… » en simulation)."""
        ...

    async def generer(self, mails: Sequence[tuple[str, str]]) -> ReponseIag:
        """Envoie un lot de mails (id, texte) et renvoie la réponse brute. Lève ErreurIag."""
        ...


class Vectoriseur(Protocol):
    @property
    def modele(self) -> str: ...

    @property
    def dimension(self) -> int: ...

    async def vectoriser(self, textes: Sequence[str]) -> list[list[float]]:
        """Un vecteur par texte, dans l'ordre. Lève ErreurIag."""
        ...
