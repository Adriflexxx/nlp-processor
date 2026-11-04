"""Choix des seuils sur la courbe couverture / précision (prédictions de validation croisée).

- Seuil haut : le plus bas seuil dont la précision top 1 des demandes couvertes atteint
  la cible ; au-dessus, un Titre est mis en avant.
- Seuil moyen : le plus bas seuil dont la précision top 3 atteint la cible ; au-dessus,
  le top 3 est proposé. En dessous, ou en cas de désaccord des modèles : aucune proposition.

Les seuils sont choisis sur l'entraînement (hors pli), jamais sur le test.
"""

from __future__ import annotations

import math
from collections import Counter

import numpy as np

from demandes.apprentissage.metriques import courbe_couverture
from demandes.domaine.decision import Niveau, Seuils, niveau_confiance


def _plus_bas_seuil(points: list[dict], cle: str, cible: float) -> float:
    for point in points:  # seuils croissants
        valeur = point[cle]
        if not math.isnan(valeur) and point["couverture"] > 0 and valeur >= cible:
            # La précision doit rester au-dessus de la cible pour tous les seuils plus hauts.
            plus_hauts = [p[cle] for p in points if p["seuil"] >= point["seuil"] and not math.isnan(p[cle])]
            if min(plus_hauts) >= cible:
                return point["seuil"]
    return 1.0


def choisir_seuils(probas: np.ndarray, y: np.ndarray, cible_haut: float, cible_top3_moyen: float) -> Seuils:
    points = courbe_couverture(probas, y)
    haut = _plus_bas_seuil(points, "precision_top1", cible_haut)
    moyen = min(_plus_bas_seuil(points, "precision_top3", cible_top3_moyen), haut)
    return Seuils(haut=haut, moyen=moyen, source="courbe")


def bilan_decisions(
    probas: np.ndarray, y: np.ndarray, desaccord: np.ndarray, seuils: Seuils, desaccord_bloque: bool
) -> dict[str, dict[str, float]]:
    """Répartition des niveaux et justesse de chacun (top 1 pour « haut », top 3 pour « moyen »)."""
    confiance = probas.max(axis=1)
    niveaux = [niveau_confiance(float(c), seuils, bool(d), desaccord_bloque) for c, d in zip(confiance, desaccord)]
    top1 = probas.argmax(axis=1) == y
    top3 = np.array([y[i] in np.argsort(-probas[i])[:3] for i in range(len(y))])
    comptes = Counter(niveaux)
    sortie = {}
    for niveau in Niveau:
        masque = np.array([n is niveau for n in niveaux])
        n = int(masque.sum())
        sortie[niveau.value] = {
            "part": n / len(y) if len(y) else 0.0,
            "n": n,
            "precision_top1": float(top1[masque].mean()) if n else float("nan"),
            "precision_top3": float(top3[masque].mean()) if n else float("nan"),
        }
    assert sum(comptes.values()) == len(y)
    return sortie
