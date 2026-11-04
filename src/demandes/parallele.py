"""Exécution parallèle par lots, sur plusieurs processus (joblib / loky).

Voir l'ADR-0004 : les processus servent au calcul. Les appels réseau
(IAG, embedding) passent par asyncio, pas par ce module.
"""

from __future__ import annotations

import os
from collections.abc import Callable, Sequence
from typing import TypeVar

from joblib import Parallel, delayed

E = TypeVar("E")
R = TypeVar("R")

# En dessous de ce nombre d'éléments, lancer des processus coûte plus que ça ne rapporte.
SEUIL_PARALLELE = 2000


def limiter_threads_blas() -> None:
    """Un seul thread BLAS par processus, pour ne pas surcharger les cœurs."""
    for variable in ("OMP_NUM_THREADS", "OPENBLAS_NUM_THREADS", "MKL_NUM_THREADS"):
        os.environ.setdefault(variable, "1")


def _appliquer_lot(fonction: Callable[[E], R], lot: Sequence[E]) -> list[R]:
    return [fonction(element) for element in lot]


def map_par_lots(
    fonction: Callable[[E], R],
    elements: Sequence[E],
    n_processus: int,
    taille_lot: int | None = None,
    seuil: int = SEUIL_PARALLELE,
) -> list[R]:
    """Applique `fonction` à chaque élément, en conservant l'ordre.

    `fonction` doit être définie au niveau d'un module (sérialisable).
    """
    if n_processus <= 1 or len(elements) < seuil:
        return [fonction(element) for element in elements]
    if taille_lot is None:
        taille_lot = max(1, -(-len(elements) // (n_processus * 4)))
    lots = [elements[i : i + taille_lot] for i in range(0, len(elements), taille_lot)]
    resultats = Parallel(n_jobs=n_processus, backend="loky")(
        delayed(_appliquer_lot)(fonction, lot) for lot in lots
    )
    return [r for lot in resultats for r in lot]
