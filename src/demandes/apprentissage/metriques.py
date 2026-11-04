"""Mesures d'une matrice de probabilités (n × K) face aux Titres vrais (indices 0..K-1)."""

from __future__ import annotations

from collections import Counter
from typing import Any

import numpy as np
from sklearn.metrics import f1_score, precision_recall_fscore_support

SEUILS_COURBE = np.round(np.linspace(0.0, 1.0, 101), 2)


def exactitude_topk(probas: np.ndarray, y: np.ndarray, k: int) -> float:
    if len(y) == 0:
        return float("nan")
    k = min(k, probas.shape[1])
    topk = np.argpartition(-probas, kth=k - 1, axis=1)[:, :k]
    return float(np.mean([y[i] in topk[i] for i in range(len(y))]))


def log_loss_securise(probas: np.ndarray, y: np.ndarray) -> float:
    if len(y) == 0:
        return float("nan")
    p = np.clip(probas[np.arange(len(y)), y], 1e-15, 1.0)
    return float(-np.mean(np.log(p)))


def brier(probas: np.ndarray, y: np.ndarray) -> float:
    if len(y) == 0:
        return float("nan")
    cible = np.zeros_like(probas)
    cible[np.arange(len(y)), y] = 1.0
    return float(np.mean(np.sum((probas - cible) ** 2, axis=1)))


def courbe_couverture(probas: np.ndarray, y: np.ndarray, seuils: np.ndarray = SEUILS_COURBE) -> list[dict[str, float]]:
    """Pour chaque seuil : part des demandes couvertes (p top 1 >= seuil), exactitude top 1 et top 3 sur elles."""
    if len(y) == 0:
        return []
    confiance = probas.max(axis=1)
    juste_top1 = probas.argmax(axis=1) == y
    top3 = np.argsort(-probas, axis=1)[:, :3]
    juste_top3 = np.array([y[i] in top3[i] for i in range(len(y))])
    points = []
    for s in seuils:
        couvert = confiance >= s
        n = int(couvert.sum())
        points.append(
            {
                "seuil": float(s),
                "couverture": n / len(y),
                "precision_top1": float(juste_top1[couvert].mean()) if n else float("nan"),
                "precision_top3": float(juste_top3[couvert].mean()) if n else float("nan"),
            }
        )
    return points


def fiabilite(probas: np.ndarray, y: np.ndarray, n_classes_bins: int = 10) -> dict[str, Any]:
    """Diagramme de fiabilité (confiance moyenne / exactitude par tranche) et erreur de calibration (ECE)."""
    if len(y) == 0:
        return {"tranches": [], "ece": float("nan")}
    confiance = probas.max(axis=1)
    juste = probas.argmax(axis=1) == y
    bornes = np.linspace(0, 1, n_classes_bins + 1)
    tranches, ece = [], 0.0
    for a, b in zip(bornes[:-1], bornes[1:]):
        dedans = (confiance > a) & (confiance <= b) if a > 0 else (confiance >= a) & (confiance <= b)
        n = int(dedans.sum())
        if n:
            conf, exact = float(confiance[dedans].mean()), float(juste[dedans].mean())
            ece += n / len(y) * abs(conf - exact)
            tranches.append({"de": float(a), "a": float(b), "n": n, "confiance": conf, "exactitude": exact})
    return {"tranches": tranches, "ece": float(ece)}


def paires_confondues(probas: np.ndarray, y: np.ndarray, titres: list[str], n: int = 15) -> list[dict[str, Any]]:
    """Paires (vrai → prédit) les plus fréquentes parmi les erreurs top 1."""
    predits = probas.argmax(axis=1)
    erreurs = Counter((int(v), int(p)) for v, p in zip(y, predits) if v != p)
    return [
        {"vrai": titres[v], "predit": titres[p], "nombre": c} for (v, p), c in erreurs.most_common(n)
    ]


def matrice_confusion(probas: np.ndarray, y: np.ndarray, classes: list[int]) -> list[list[int]]:
    """Matrice de confusion restreinte aux classes données (lignes : vrai, colonnes : prédit)."""
    predits = probas.argmax(axis=1)
    index = {c: i for i, c in enumerate(classes)}
    matrice = np.zeros((len(classes), len(classes)), dtype=int)
    for v, p in zip(y, predits):
        if v in index and p in index:
            matrice[index[v], index[p]] += 1
    return matrice.tolist()


def scores_par_titre(probas: np.ndarray, y: np.ndarray, titres: list[str]) -> list[dict[str, Any]]:
    labels = list(range(len(titres)))
    precision, rappel, f1, support = precision_recall_fscore_support(
        y, probas.argmax(axis=1), labels=labels, zero_division=0
    )
    return [
        {"titre": titres[i], "precision": float(precision[i]), "rappel": float(rappel[i]), "f1": float(f1[i]), "support": int(support[i])}
        for i in labels
        if support[i] > 0
    ]


def mesures(probas: np.ndarray, y: np.ndarray, n_classes: int) -> dict[str, float]:
    """Mesures de synthèse d'un segment."""
    if len(y) == 0:
        return {"n": 0}
    return {
        "n": int(len(y)),
        "top1": exactitude_topk(probas, y, 1),
        "top3": exactitude_topk(probas, y, 3),
        "f1_macro": float(f1_score(y, probas.argmax(axis=1), average="macro", labels=list(range(n_classes)), zero_division=0)),
        "logloss": log_loss_securise(probas, y),
        "brier": brier(probas, y),
        "ece": fiabilite(probas, y)["ece"],
    }


def mesures_par_segment(probas: np.ndarray, y: np.ndarray, template: np.ndarray, n_classes: int) -> dict[str, dict]:
    """Chaque mesure trois fois : ensemble, mails issus d'un template, mails libres."""
    template = np.asarray(template, dtype=bool)
    return {
        "ensemble": mesures(probas, y, n_classes),
        "template": mesures(probas[template], y[template], n_classes),
        "libre": mesures(probas[~template], y[~template], n_classes),
    }
