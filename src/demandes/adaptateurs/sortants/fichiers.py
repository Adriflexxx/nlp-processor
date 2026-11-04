"""Stockage des artefacts dans un dossier (volume monté dans docker compose)."""

from __future__ import annotations

import csv
import json
from collections.abc import Iterable, Sequence
from datetime import date, datetime
from pathlib import Path
from typing import Any


def _par_defaut(valeur: Any) -> Any:
    if isinstance(valeur, (datetime, date)):
        return valeur.isoformat()
    if isinstance(valeur, (set, frozenset, tuple)):
        return list(valeur)
    if hasattr(valeur, "tolist"):  # numpy
        return valeur.tolist()
    raise TypeError(f"non sérialisable en JSON : {type(valeur)}")


class StockageFichiers:
    def __init__(self, racine: Path) -> None:
        self._racine = racine

    @property
    def racine(self) -> Path:
        return self._racine

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
