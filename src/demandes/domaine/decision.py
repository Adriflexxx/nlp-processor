"""Décision d'assistance : Titre mis en avant, top 3, ou aucune proposition."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum


class Niveau(StrEnum):
    HAUT = "haut"  # un Titre est mis en avant
    MOYEN = "moyen"  # le top 3 est proposé
    AUCUN = "aucun"  # aucune proposition


@dataclass(frozen=True, slots=True)
class Seuils:
    haut: float
    moyen: float
    source: str = "courbe"  # "courbe" (choisis en validation croisée) ou "manuel" (.env)

    def __post_init__(self) -> None:
        if not 0 <= self.moyen <= self.haut <= 1:
            raise ValueError(f"seuils incohérents : moyen {self.moyen}, haut {self.haut}")


def niveau_confiance(probabilite_top1: float, seuils: Seuils, desaccord: bool = False, desaccord_bloque: bool = True) -> Niveau:
    """Seuil haut : un Titre mis en avant ; seuil moyen : top 3 ; en dessous ou en désaccord : aucun."""
    if desaccord and desaccord_bloque:
        return Niveau.AUCUN
    if probabilite_top1 >= seuils.haut:
        return Niveau.HAUT
    if probabilite_top1 >= seuils.moyen:
        return Niveau.MOYEN
    return Niveau.AUCUN
