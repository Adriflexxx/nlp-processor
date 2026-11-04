"""Port de stockage des artefacts sur fichiers (CSV, JSON, modèles, graphiques)."""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from pathlib import Path
from typing import Any, Protocol


class StockageArtefacts(Protocol):
    @property
    def racine(self) -> Path: ...

    def ecrire_csv(self, chemin_relatif: str, entetes: Sequence[str], lignes: Iterable[Sequence[Any]]) -> Path: ...

    def ecrire_json(self, chemin_relatif: str, contenu: Any) -> Path: ...
