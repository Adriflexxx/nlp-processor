"""Entités du corpus : une ligne brute de l'export, une demande retenue, une ligne écartée."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from datetime import datetime
from enum import StrEnum


@dataclass(frozen=True, slots=True)
class LigneBrute:
    """Une ligne de l'export telle que lue, avant tout contrôle.

    `ligne_source` est le numéro de ligne dans le fichier (en-tête = ligne 1),
    pour que l'opérateur retrouve facilement une ligne écartée.
    """

    ligne_source: int
    numero: str | None
    titre: str | None
    mail: str | None
    date: datetime | None = None


@dataclass(frozen=True, slots=True)
class Demande:
    """Une demande retenue après contrôle, prête pour l'apprentissage."""

    numero: str
    titre: str
    mail: str  # texte brut (après réparation de l'encodage et retrait des NUL)
    mail_nettoye: str  # texte pour la branche TF-IDF
    objet: str | None
    template: bool
    marqueurs_template: tuple[str, ...] = field(default_factory=tuple)
    date: datetime | None = None


class MotifEcart(StrEnum):
    MAIL_VIDE = "mail_vide"
    TITRE_VIDE = "titre_vide"
    NUMERO_VIDE = "numero_vide"
    NUMERO_EN_DOUBLE = "numero_en_double"


@dataclass(frozen=True, slots=True)
class LigneEcartee:
    ligne_source: int
    numero: str | None
    motif: MotifEcart
    detail: str = ""


def empreinte_mail(texte: str) -> str:
    """Empreinte d'un mail : une fiche en cache n'est réutilisée que si le mail n'a pas changé."""
    return hashlib.sha256(texte.encode("utf-8")).hexdigest()
