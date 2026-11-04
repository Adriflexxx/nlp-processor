"""Les cinq modèles de base, leurs grilles et leurs représentations.

Chaque modèle est un estimateur scikit-learn complet (Pipeline) : la représentation
(TF-IDF, ACP) est ajustée dans `fit`, donc uniquement sur les données d'entraînement
qu'on lui passe. Rien n'est ajusté en dehors (pas de fuite).

Entrées :
- branche TF-IDF : tableau de textes (mail nettoyé) ;
- branche embedding : matrice n × d (vecteurs normalisés), une ligne de NaN pour une
  demande sans vecteur (fiche en échec) : le modèle lui attribue la distribution a
  priori des Titres de l'entraînement.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable

import numpy as np
from sklearn.base import BaseEstimator, ClassifierMixin, clone
from sklearn.calibration import CalibratedClassifierCV
from sklearn.decomposition import PCA
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.linear_model import LogisticRegression
from sklearn.neighbors import KNeighborsClassifier
from sklearn.pipeline import FeatureUnion, Pipeline
from sklearn.svm import LinearSVC

TFIDF = "tfidf"
EMB = "emb"

#: Version des définitions ci-dessous : entre dans l'empreinte des modèles.
VERSION_MODELES = 1


# --- Briques -------------------------------------------------------------------


def poids_similarite(distances: np.ndarray) -> np.ndarray:
    """Vote du KNN pondéré par la similarité cosinus (1 - distance)."""
    return np.clip(1.0 - distances, 1e-9, None)


class SVMCalibre(ClassifierMixin, BaseEstimator):
    """LinearSVC + CalibratedClassifierCV (sigmoïde).

    Le nombre de plis de calibration s'adapte à la plus petite classe de l'entraînement
    (3 au plus, 2 au moins), pour rester valable avec de petits Titres.
    """

    def __init__(self, C: float = 1.0, random_state: int = 0) -> None:
        self.C = C
        self.random_state = random_state

    def fit(self, X, y):
        _, effectifs = np.unique(y, return_counts=True)
        plis = int(max(2, min(3, effectifs.min())))
        svm = LinearSVC(C=self.C, class_weight="balanced", random_state=self.random_state, max_iter=5000)
        self.modele_ = CalibratedClassifierCV(svm, method="sigmoid", cv=plis)
        self.modele_.fit(X, y)
        self.classes_ = self.modele_.classes_
        return self

    def predict_proba(self, X):
        return self.modele_.predict_proba(X)

    def predict(self, X):
        return self.classes_[np.argmax(self.predict_proba(X), axis=1)]


class AvecRepli(ClassifierMixin, BaseEstimator):
    """Entraîne sur les lignes sans NaN ; une ligne de NaN reçoit la distribution a priori."""

    def __init__(self, estimateur: Any = None) -> None:
        self.estimateur = estimateur

    def fit(self, X, y):
        X = np.asarray(X, dtype=np.float32)
        y = np.asarray(y)
        valides = ~np.isnan(X).any(axis=1)
        self.classes_, effectifs = np.unique(y, return_counts=True)
        self.a_priori_ = effectifs / effectifs.sum()
        self.estimateur_ = clone(self.estimateur).fit(X[valides], y[valides])
        return self

    def predict_proba(self, X):
        X = np.asarray(X, dtype=np.float32)
        valides = ~np.isnan(X).any(axis=1)
        sortie = np.tile(self.a_priori_, (len(X), 1))
        if valides.any():
            partielles = self.estimateur_.predict_proba(X[valides])
            colonnes = np.searchsorted(self.classes_, self.estimateur_.classes_)
            bloc = np.zeros((int(valides.sum()), len(self.classes_)))
            bloc[:, colonnes] = partielles
            sortie[valides] = bloc
        return sortie

    def predict(self, X):
        return self.classes_[np.argmax(self.predict_proba(X), axis=1)]


def _tfidf(caracteres: bool):
    mots = TfidfVectorizer(ngram_range=(1, 2), min_df=2, sublinear_tf=True, strip_accents=None, lowercase=True)
    if not caracteres:
        return mots
    lettres = TfidfVectorizer(analyzer="char_wb", ngram_range=(3, 5), min_df=2, sublinear_tf=True)
    return FeatureUnion([("mots", mots), ("caracteres", lettres)])


def _acp(dimension: int | None, graine: int):
    return "passthrough" if dimension is None else PCA(n_components=dimension, random_state=graine)


# --- Définitions ---------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class DefinitionModele:
    cle: str
    representation: str  # TFIDF ou EMB
    grille: tuple[dict[str, Any], ...]
    fabrique: Callable[..., Any]  # (params, graine, options) -> estimateur non ajusté


def _svm_tfidf(params, graine, options):
    return Pipeline([("tfidf", _tfidf(options.get("tfidf_caracteres", False))), ("clf", SVMCalibre(params["C"], graine))])


def _rl_tfidf(params, graine, options):
    clf = LogisticRegression(C=params["C"], class_weight="balanced", max_iter=3000)
    return Pipeline([("tfidf", _tfidf(options.get("tfidf_caracteres", False))), ("clf", clf)])


def _svm_emb(params, graine, options):
    return AvecRepli(Pipeline([("acp", _acp(params.get("dimension"), graine)), ("clf", SVMCalibre(params["C"], graine))]))


def _rl_emb(params, graine, options):
    clf = LogisticRegression(C=params["C"], class_weight="balanced", max_iter=3000)
    return AvecRepli(Pipeline([("acp", _acp(params.get("dimension"), graine)), ("clf", clf)]))


def _knn_emb(params, graine, options):
    clf = KNeighborsClassifier(n_neighbors=params["K"], metric="cosine", weights=poids_similarite, algorithm="brute")
    return AvecRepli(Pipeline([("acp", _acp(params.get("dimension"), graine)), ("clf", clf)]))


C_SVM = (0.01, 0.1, 1.0, 10.0)
C_RL = (0.1, 1.0, 10.0, 100.0)
K_KNN = (5, 10, 20)


def definitions(dimensions_acp: list[int | None] | None = None) -> dict[str, DefinitionModele]:
    """Les cinq modèles. `dimensions_acp` : dimensions testées (None = sans réduction)."""
    dims = dimensions_acp or [None]
    return {
        "svm_tfidf": DefinitionModele("svm_tfidf", TFIDF, tuple({"C": c} for c in C_SVM), _svm_tfidf),
        "rl_tfidf": DefinitionModele("rl_tfidf", TFIDF, tuple({"C": c} for c in C_RL), _rl_tfidf),
        "svm_emb": DefinitionModele(
            "svm_emb", EMB, tuple({"C": c, "dimension": d} for d in dims for c in C_SVM), _svm_emb
        ),
        "rl_emb": DefinitionModele("rl_emb", EMB, tuple({"C": c, "dimension": d} for d in dims for c in C_RL), _rl_emb),
        "knn_emb": DefinitionModele(
            "knn_emb", EMB, tuple({"K": k, "dimension": d} for d in dims for k in K_KNN), _knn_emb
        ),
    }


def dimensions_effectives(demandees: list[int], dimension_vecteurs: int, n_entrainement: int) -> list[int | None]:
    """Dimensions d'ACP réellement testées : une valeur >= dimension (ou > effectif) = pas de réduction (None)."""
    plafond = min(dimension_vecteurs, n_entrainement)
    sortie: list[int | None] = []
    for d in sorted(demandees):
        valeur = None if d >= plafond else d
        if valeur not in sortie:
            sortie.append(valeur)
    return sortie or [None]


def aligner(probas: np.ndarray, classes_modele: np.ndarray, classes: np.ndarray) -> np.ndarray:
    """Remet les colonnes de probabilités dans l'ordre de classes commun (0 pour une classe absente)."""
    sortie = np.zeros((probas.shape[0], len(classes)), dtype=np.float64)
    if not np.isin(classes_modele, classes).all():
        raise ValueError("le modèle connaît des classes absentes de l'ordre commun")
    positions = np.searchsorted(classes, classes_modele)
    sortie[:, positions] = probas
    return sortie
