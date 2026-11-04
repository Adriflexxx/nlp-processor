"""Modes de décision : seul, moyenne pondérée, méta-classifieur (stacking).

Tout se règle sur les prédictions hors pli des modèles de base (entraînement seul) :
les poids de la moyenne, le méta-classifieur et son hyperparamètre. Les probabilités
de test ne servent qu'à l'évaluation finale.
"""

from __future__ import annotations

import itertools
import warnings
from dataclasses import dataclass, field
from typing import Any

import numpy as np
from sklearn.ensemble import HistGradientBoostingClassifier
from joblib import Parallel, delayed
from sklearn.linear_model import LogisticRegression

from demandes.apprentissage.metriques import exactitude_topk, log_loss_securise
from demandes.apprentissage.modeles_base import aligner

C_META = (0.1, 1.0, 10.0)
PAS_POIDS = 0.1


def desaccord(probas: list[np.ndarray]) -> np.ndarray:
    """Vrai si les modèles n'ont pas tous le même top 1."""
    if len(probas) < 2:
        return np.zeros(len(probas[0]), dtype=bool)
    tops = np.stack([p.argmax(axis=1) for p in probas])
    return (tops != tops[0]).any(axis=0)


def moyenne(probas: list[np.ndarray], poids: tuple[float, ...]) -> np.ndarray:
    total = sum(w * p for w, p in zip(poids, probas))
    somme = total.sum(axis=1, keepdims=True)
    return total / np.where(somme == 0, 1, somme)


def _critere(probas: np.ndarray, y: np.ndarray) -> tuple[float, float]:
    return exactitude_topk(probas, y, 1), -log_loss_securise(probas, y)


def regler_poids(hors_pli: list[np.ndarray], y: np.ndarray, pas: float = PAS_POIDS) -> tuple[float, ...]:
    """Poids (positifs, de somme 1, par pas de 0,1) qui maximisent l'exactitude top 1 hors pli, puis la log loss."""
    n = len(hors_pli)
    graduations = int(round(1 / pas))
    meilleurs, meilleur_score = None, None
    for combinaison in itertools.product(range(graduations + 1), repeat=n):
        if sum(combinaison) != graduations or 0 in combinaison:
            continue  # chaque modèle de la combinaison garde un poids non nul
        poids = tuple(c / graduations for c in combinaison)
        score = _critere(moyenne(hors_pli, poids), y)
        if meilleur_score is None or score > meilleur_score:
            meilleurs, meilleur_score = poids, score
    return meilleurs or tuple(1 / n for _ in range(n))


def caracteristiques_meta(probas: list[np.ndarray]) -> np.ndarray:
    """Pour chaque modèle : ses probabilités et l'écart entre ses deux premières ; plus l'accord des modèles."""
    blocs = []
    for p in probas:
        deux = -np.sort(-p, axis=1)[:, :2]
        blocs += [p, (deux[:, 0] - deux[:, 1])[:, None]]
    blocs.append((~desaccord(probas)).astype(float)[:, None])
    return np.hstack(blocs)


def _fabriquer_meta(type_meta: str, C: float, graine: int):
    if type_meta == "gb":
        return HistGradientBoostingClassifier(max_iter=100, learning_rate=0.1, random_state=graine)
    return LogisticRegression(C=C, max_iter=3000)


def _ajuster_predire_meta(type_meta, C, graine, X_fit, y_fit, X_pred, n_classes) -> np.ndarray:
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        modele = _fabriquer_meta(type_meta, C, graine).fit(X_fit, y_fit)
        return aligner(modele.predict_proba(X_pred), modele.classes_, np.arange(n_classes))


def meta_hors_pli(
    caracteristiques: np.ndarray,
    y: np.ndarray,
    les_plis,
    n_classes: int,
    type_meta: str,
    graine: int,
    n_processus: int = 1,
) -> tuple[np.ndarray, dict[str, Any]]:
    """Prédictions hors pli du méta-classifieur (mêmes plis) et hyperparamètre retenu.

    Les ajustements (hyperparamètre × pli) tournent en parallèle sur plusieurs processus.
    """
    candidats = C_META if type_meta == "rl" else (None,)
    taches = [(C, p) for C in candidats for p in range(len(les_plis))]
    sorties = Parallel(n_jobs=max(1, min(n_processus, len(taches))), backend="loky")(
        delayed(_ajuster_predire_meta)(
            type_meta, C, graine, caracteristiques[les_plis[p][0]], y[les_plis[p][0]],
            caracteristiques[les_plis[p][1]], n_classes,
        )
        for C, p in taches
    )
    par_c: dict[Any, np.ndarray] = {C: np.zeros((len(y), n_classes)) for C in candidats}
    for (C, p), probas in zip(taches, sorties):
        par_c[C][les_plis[p][1]] = probas
    meilleur_c = max(candidats, key=lambda C: _critere(par_c[C], y))
    return par_c[meilleur_c], {"type": type_meta, "C": meilleur_c}


@dataclass
class CombinateurAjuste:
    """Combinateur prêt à servir : il reçoit les probabilités des modèles de base, dans l'ordre de `modeles`."""

    mode: str
    modeles: tuple[str, ...]
    n_classes: int
    poids: tuple[float, ...] | None = None
    meta: Any = None
    params: dict[str, Any] = field(default_factory=dict)

    def combiner(self, probas: list[np.ndarray]) -> np.ndarray:
        if self.mode == "seul":
            return probas[0]
        if self.mode == "moyenne":
            return moyenne(probas, self.poids)
        X = caracteristiques_meta(probas)
        return aligner(self.meta.predict_proba(X), self.meta.classes_, np.arange(self.n_classes))


def regler_combinateur(
    mode: str,
    modeles: tuple[str, ...],
    hors_pli: list[np.ndarray],
    y: np.ndarray,
    les_plis,
    n_classes: int,
    type_meta: str,
    graine: int,
    n_processus: int = 1,
) -> tuple[CombinateurAjuste, np.ndarray]:
    """Règle le combinateur sur les prédictions hors pli. Renvoie (combinateur, prédictions combinées hors pli)."""
    if mode == "seul":
        return CombinateurAjuste(mode, modeles, n_classes), hors_pli[0]
    if mode == "moyenne":
        poids = regler_poids(hors_pli, y)
        return CombinateurAjuste(mode, modeles, n_classes, poids=poids, params={"poids": list(poids)}), moyenne(hors_pli, poids)
    X = caracteristiques_meta(hors_pli)
    meta_oof, params = meta_hors_pli(X, y, les_plis, n_classes, type_meta, graine, n_processus)
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        meta = _fabriquer_meta(type_meta, params["C"], graine).fit(X, y)
    return CombinateurAjuste(mode, modeles, n_classes, meta=meta, params=params), meta_oof
