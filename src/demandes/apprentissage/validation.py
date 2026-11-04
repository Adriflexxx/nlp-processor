"""Protocole : découpage 80/20 stratifié, plis, prédictions hors pli et recherche de grille.

- Le jeu de test n'est vu par aucun objet ajusté pendant les réglages.
- Les mêmes plis servent à la recherche de grille et aux prédictions hors pli.
- Toutes les tâches (modèle × paramètre × pli) sont indépendantes et tournent en
  parallèle sur plusieurs processus ; chacune reçoit sa graine explicitement (ADR-0004).
"""

from __future__ import annotations

import warnings
from dataclasses import dataclass
from typing import Any

import numpy as np
from joblib import Parallel, delayed
from sklearn.model_selection import StratifiedKFold, train_test_split

from demandes.apprentissage.metriques import exactitude_topk, log_loss_securise
from demandes.apprentissage.modeles_base import DefinitionModele, aligner


def decouper(y: np.ndarray, taille_test: float, graine: int) -> tuple[np.ndarray, np.ndarray]:
    """Indices (entraînement, test), stratifiés par Titre, triés."""
    indices = np.arange(len(y))
    entrainement, test = train_test_split(indices, test_size=taille_test, stratify=y, random_state=graine)
    return np.sort(entrainement), np.sort(test)


def plis(y: np.ndarray, n_plis: int, graine: int) -> list[tuple[np.ndarray, np.ndarray]]:
    """Plis stratifiés (indices relatifs au tableau `y` reçu)."""
    return list(StratifiedKFold(n_splits=n_plis, shuffle=True, random_state=graine).split(np.zeros(len(y)), y))


def ajuster_predire(
    definition: DefinitionModele,
    params: dict[str, Any],
    graine: int,
    options: dict[str, Any],
    X_fit,
    y_fit: np.ndarray,
    X_pred,
    n_classes: int,
) -> np.ndarray:
    """Ajuste un modèle sur (X_fit, y_fit) et renvoie ses probabilités sur X_pred, dans l'ordre commun."""
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")  # non-convergence, classes rares dans un pli de calibration
        modele = definition.fabrique(params, graine, options).fit(X_fit, y_fit)
        probas = modele.predict_proba(X_pred)
    return aligner(probas, np.asarray(modele.classes_), np.arange(n_classes))


def ajuster(definition: DefinitionModele, params: dict[str, Any], graine: int, options: dict[str, Any], X, y):
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        return definition.fabrique(params, graine, options).fit(X, y)


def _tache_pli(definition, params, graine, options, X, y, entr, val, n_classes):
    return ajuster_predire(definition, params, graine, options, X[entr], y[entr], X[val], n_classes)


@dataclass(slots=True)
class ResultatGrille:
    cle: str
    params: list[dict[str, Any]]
    scores: list[dict[str, float]]  # par paramètre : top1, logloss hors pli
    meilleur: int
    hors_pli: np.ndarray  # probabilités hors pli du meilleur paramètre (n_entrainement × K)

    @property
    def meilleurs_params(self) -> dict[str, Any]:
        return self.params[self.meilleur]


def rechercher_grilles(
    definitions: dict[str, DefinitionModele],
    entrees: dict[str, Any],
    y: np.ndarray,
    les_plis: list[tuple[np.ndarray, np.ndarray]],
    n_classes: int,
    graine: int,
    options: dict[str, Any],
    n_processus: int,
    rappel=None,
) -> dict[str, ResultatGrille]:
    """Validation croisée de chaque modèle sur sa grille, toutes tâches en parallèle.

    `entrees` : représentation → X d'entraînement (textes ou matrice). Le meilleur
    paramètre est celui de la meilleure exactitude top 1 hors pli (puis log loss).
    `rappel(fait, total)` est appelé au fil de l'eau.
    """
    taches = [
        (cle, i, p)
        for cle, definition in definitions.items()
        for i in range(len(definition.grille))
        for p in range(len(les_plis))
    ]
    resultats: dict[tuple[str, int, int], np.ndarray] = {}
    parallele = Parallel(n_jobs=max(1, n_processus), backend="loky", return_as="generator")
    generateur = parallele(
        delayed(_tache_pli)(
            definitions[cle], definitions[cle].grille[i], graine, options,
            entrees[definitions[cle].representation], y, les_plis[p][0], les_plis[p][1], n_classes,
        )
        for cle, i, p in taches
    )
    for numero, (tache, probas) in enumerate(zip(taches, generateur), start=1):
        resultats[tache] = probas
        if rappel:
            rappel(numero, len(taches))

    sortie: dict[str, ResultatGrille] = {}
    for cle, definition in definitions.items():
        hors_pli_par_param, scores = [], []
        for i in range(len(definition.grille)):
            matrice = np.zeros((len(y), n_classes))
            for p, (_, val) in enumerate(les_plis):
                matrice[val] = resultats[(cle, i, p)]
            hors_pli_par_param.append(matrice)
            scores.append({"top1": exactitude_topk(matrice, y, 1), "logloss": log_loss_securise(matrice, y)})
        meilleur = max(range(len(scores)), key=lambda i: (scores[i]["top1"], -scores[i]["logloss"]))
        sortie[cle] = ResultatGrille(cle, list(definition.grille), scores, meilleur, hors_pli_par_param[meilleur])
    return sortie
