"""Stockage des artefacts dans un dossier (volume monté dans docker compose)."""

from __future__ import annotations

import csv
import json
from collections.abc import Iterable, Sequence
from datetime import date, datetime
from pathlib import Path
from typing import Any

import joblib
import numpy as np


def _par_defaut(valeur: Any) -> Any:
    if isinstance(valeur, (datetime, date)):
        return valeur.isoformat()
    if isinstance(valeur, (set, frozenset, tuple)):
        return list(valeur)
    if hasattr(valeur, "tolist"):  # numpy
        return valeur.tolist()
    if isinstance(valeur, float) and valeur != valeur:
        return None
    raise TypeError(f"non sérialisable en JSON : {type(valeur)}")


class StockageFichiers:
    def __init__(self, racine: Path) -> None:
        self._racine = racine

    @property
    def racine(self) -> Path:
        return self._racine

    def chemin(self, chemin_relatif: str) -> Path:
        return self._chemin(chemin_relatif)

    def existe(self, chemin_relatif: str) -> bool:
        return (self._racine / chemin_relatif).exists()

    def lire_json(self, chemin_relatif: str) -> Any:
        return json.loads((self._racine / chemin_relatif).read_text(encoding="utf-8"))

    def ecrire_texte(self, chemin_relatif: str, texte: str) -> Path:
        chemin = self._chemin(chemin_relatif)
        chemin.write_text(texte, encoding="utf-8")
        return chemin

    def ecrire_matrice(self, chemin_relatif: str, matrice: np.ndarray) -> Path:
        chemin = self._chemin(chemin_relatif)
        np.save(chemin, matrice, allow_pickle=False)
        return chemin

    def lire_matrice(self, chemin_relatif: str) -> np.ndarray:
        return np.load(self._racine / chemin_relatif, allow_pickle=False)

    def ecrire_objet(self, chemin_relatif: str, objet: Any) -> Path:
        chemin = self._chemin(chemin_relatif)
        joblib.dump(objet, chemin, compress=3)
        return chemin

    def lire_objet(self, chemin_relatif: str) -> Any:
        return joblib.load(self._racine / chemin_relatif)

    def _chemin(self, chemin_relatif: str) -> Path:
        chemin = (self._racine / chemin_relatif).resolve()
        if not chemin.is_relative_to(self._racine.resolve()):
            raise ValueError(f"chemin hors du dossier des artefacts : {chemin_relatif}")
        chemin.parent.mkdir(parents=True, exist_ok=True)
        return chemin

    def ecrire_csv(self, chemin_relatif: str, entetes: Sequence[str], lignes: Iterable[Sequence[Any]]) -> Path:
        chemin = self._chemin(chemin_relatif)
        # utf-8-sig : Excel ouvre correctement les accents.
        with chemin.open("w", encoding="utf-8-sig", newline="") as flux:
            ecrivain = csv.writer(flux, delimiter=";")
            ecrivain.writerow(entetes)
            ecrivain.writerows(lignes)
        return chemin

    def ecrire_json(self, chemin_relatif: str, contenu: Any) -> Path:
        chemin = self._chemin(chemin_relatif)
        chemin.write_text(json.dumps(contenu, ensure_ascii=False, indent=2, default=_par_defaut), encoding="utf-8")
        return chemin
