"""Port de stockage des artefacts sur fichiers (CSV, JSON, matrices, modèles, graphiques)."""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from pathlib import Path
from typing import Any, Protocol

import numpy as np


class StockageArtefacts(Protocol):
    @property
    def racine(self) -> Path: ...

    def chemin(self, chemin_relatif: str) -> Path:
        """Chemin absolu d'un artefact (dossier parent créé)."""
        ...

    def existe(self, chemin_relatif: str) -> bool: ...

    def ecrire_csv(self, chemin_relatif: str, entetes: Sequence[str], lignes: Iterable[Sequence[Any]]) -> Path: ...

    def ecrire_json(self, chemin_relatif: str, contenu: Any) -> Path: ...

    def lire_json(self, chemin_relatif: str) -> Any: ...

    def ecrire_texte(self, chemin_relatif: str, texte: str) -> Path: ...

    def ecrire_matrice(self, chemin_relatif: str, matrice: np.ndarray) -> Path: ...

    def lire_matrice(self, chemin_relatif: str) -> np.ndarray: ...

    def ecrire_objet(self, chemin_relatif: str, objet: Any) -> Path:
        """Objet Python (modèle ajusté…) sérialisé avec joblib."""
        ...

    def lire_objet(self, chemin_relatif: str) -> Any: ...


class Graphiques(Protocol):
    def courbes_couverture(self, series: dict[str, list[dict]], chemin: Path) -> Path:
        """Courbes couverture / précision top 1, une par combinaison."""
        ...

    def fiabilite(self, series: dict[str, dict], chemin: Path) -> Path:
        """Diagrammes de fiabilité (confiance / exactitude par tranche)."""
        ...

    def confusion(self, matrice: list[list[int]], titres: list[str], chemin: Path) -> Path:
        """Matrice de confusion restreinte aux Titres les plus confondus."""
        ...
