"""Jeu d'apprentissage : demandes retenues, Titres encodés, découpage, représentations, empreintes."""

from __future__ import annotations

import hashlib
import json
import math
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

import numpy as np

from demandes.apprentissage.validation import decouper, plis
from demandes.domaine.demande import Demande, empreinte_mail
from demandes.domaine.referentiel import cartographier, petites_categories


def hacher(contenu: Any) -> str:
    texte = json.dumps(contenu, sort_keys=True, ensure_ascii=False, separators=(",", ":"), default=str)
    return hashlib.sha256(texte.encode("utf-8")).hexdigest()


def sans_nan(valeur: Any) -> Any:
    """NaN → None, récursivement (PostgreSQL refuse NaN dans du JSON)."""
    if isinstance(valeur, float) and math.isnan(valeur):
        return None
    if isinstance(valeur, dict):
        return {k: sans_nan(v) for k, v in valeur.items()}
    if isinstance(valeur, (list, tuple)):
        return [sans_nan(v) for v in valeur]
    if isinstance(valeur, (np.floating,)):
        return sans_nan(float(valeur))
    if isinstance(valeur, (np.integer,)):
        return int(valeur)
    return valeur


@dataclass(slots=True)
class Jeu:
    numeros: np.ndarray  # (n,) str
    titres: list[str]  # classes, dans l'ordre commun (trié)
    y: np.ndarray  # (n,) int, indices dans `titres`
    textes: np.ndarray  # (n,) object : mail nettoyé (branche TF-IDF)
    template: np.ndarray  # (n,) bool
    dates: list[datetime | None]
    exclus: list[str]  # Titres sous MIN_PAR_TITRE
    entrainement: np.ndarray  # indices
    test: np.ndarray  # indices
    plis: list[tuple[np.ndarray, np.ndarray]]  # relatifs à l'entraînement
    empreinte: str
    parametres: dict[str, Any] = field(default_factory=dict)
    vecteurs: np.ndarray | None = None  # (n, d) float32, NaN si pas de vecteur
    empreinte_vecteur: str | None = None
    n_avec_vecteur: int = 0

    @property
    def n_classes(self) -> int:
        return len(self.titres)

    def entrees(self, indices: np.ndarray) -> dict[str, Any]:
        sortie: dict[str, Any] = {"tfidf": self.textes[indices]}
        if self.vecteurs is not None:
            sortie["emb"] = self.vecteurs[indices]
        return sortie

    def resume(self) -> dict[str, Any]:
        return {
            "empreinte": self.empreinte,
            "n_demandes": int(len(self.y)),
            "n_titres": self.n_classes,
            "n_entrainement": int(len(self.entrainement)),
            "n_test": int(len(self.test)),
            "part_template": float(self.template.mean()) if len(self.template) else 0.0,
            "titres_exclus": self.exclus,
            "empreinte_vecteur": self.empreinte_vecteur,
            "n_avec_vecteur": self.n_avec_vecteur,
            **self.parametres,
        }


def construire_jeu(
    demandes: list[Demande], min_par_titre: int, taille_test: float, n_plis: int, graine: int
) -> Jeu:
    """Retire les petites catégories, encode les Titres, découpe 80/20 et prépare les plis."""
    exclus = sorted(e.titre for e in petites_categories(cartographier(demandes), min_par_titre))
    retenues = sorted((d for d in demandes if d.titre not in set(exclus)), key=lambda d: d.numero)
    if not retenues:
        raise ValueError("aucune demande retenue pour l'apprentissage (corpus vide ou MIN_PAR_TITRE trop haut)")
    titres = sorted({d.titre for d in retenues})
    if len(titres) < 2:
        raise ValueError("il faut au moins deux Titres pour apprendre")
    index = {t: i for i, t in enumerate(titres)}
    y = np.array([index[d.titre] for d in retenues], dtype=np.int64)
    parametres = {"min_par_titre": min_par_titre, "taille_test": taille_test, "n_plis": n_plis, "seed": graine}
    empreinte = hacher(
        {"demandes": [(d.numero, d.titre, empreinte_mail(d.mail)) for d in retenues], **parametres, "version": 1}
    )
    entrainement, test = decouper(y, taille_test, graine)
    return Jeu(
        numeros=np.array([d.numero for d in retenues]),
        titres=titres,
        y=y,
        textes=np.array([d.mail_nettoye or d.mail for d in retenues], dtype=object),
        template=np.array([d.template for d in retenues], dtype=bool),
        dates=[d.date for d in retenues],
        exclus=exclus,
        entrainement=entrainement,
        test=test,
        plis=plis(y[entrainement], n_plis, graine),
        empreinte=empreinte,
        parametres=parametres,
    )


def attacher_vecteurs(jeu: Jeu, numeros: list[str], matrice: np.ndarray, empreinte_vecteur: str) -> None:
    """Aligne les vecteurs sur le jeu ; une demande sans vecteur reçoit une ligne de NaN."""
    if len(numeros) == 0:
        return
    position = {n: i for i, n in enumerate(numeros)}
    sortie = np.full((len(jeu.numeros), matrice.shape[1]), np.nan, dtype=np.float32)
    for i, numero in enumerate(jeu.numeros):
        j = position.get(numero)
        if j is not None:
            sortie[i] = matrice[j]
    jeu.vecteurs = sortie
    jeu.empreinte_vecteur = empreinte_vecteur
    jeu.n_avec_vecteur = int((~np.isnan(sortie).any(axis=1)).sum())
