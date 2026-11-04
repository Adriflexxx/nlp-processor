"""Port de lecture d'un export de demandes."""

from __future__ import annotations

from pathlib import Path
from typing import Protocol

from demandes.domaine.demande import LigneBrute


class ColonnesManquantes(ValueError):
    """Les colonnes attendues par le mapping ne sont pas dans l'export."""


class SourceExport(Protocol):
    def lire(self, chemin: Path, mapping: dict[str, str], feuille: str | None = None) -> list[LigneBrute]:
        """Lit l'export et renvoie une ligne brute par ligne de données.

        `mapping` associe le nom de colonne du fichier au nom interne
        (`numero`, `titre`, `mail`, `date`). Lève `ColonnesManquantes`.
        """
        ...
