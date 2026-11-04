"""Cartographie des Titres et comparaison avec la référence figée."""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import datetime

from demandes.domaine.demande import Demande


@dataclass(frozen=True, slots=True)
class EntreeCartographie:
    titre: str
    nb_demandes: int
    premiere_date: datetime | None
    derniere_date: datetime | None


@dataclass(frozen=True, slots=True)
class EcartReferentiel:
    """Écart entre un export et la référence figée."""

    nouveaux: tuple[str, ...]  # présents dans l'export, absents de la référence
    disparus: tuple[str, ...]  # présents dans la référence, absents de l'export

    @property
    def vide(self) -> bool:
        return not self.nouveaux and not self.disparus


def cartographier(demandes: Iterable[Demande]) -> list[EntreeCartographie]:
    """Titre, nombre de demandes, première et dernière date ; tri par effectif décroissant."""
    effectifs: dict[str, int] = defaultdict(int)
    premieres: dict[str, datetime] = {}
    dernieres: dict[str, datetime] = {}
    for demande in demandes:
        effectifs[demande.titre] += 1
        if demande.date is not None:
            if demande.titre not in premieres or demande.date < premieres[demande.titre]:
                premieres[demande.titre] = demande.date
            if demande.titre not in dernieres or demande.date > dernieres[demande.titre]:
                dernieres[demande.titre] = demande.date
    entrees = [
        EntreeCartographie(titre, n, premieres.get(titre), dernieres.get(titre))
        for titre, n in effectifs.items()
    ]
    return sorted(entrees, key=lambda e: (-e.nb_demandes, e.titre))


def comparer(reference: Iterable[str], actuels: Iterable[str]) -> EcartReferentiel:
    ref, act = set(reference), set(actuels)
    return EcartReferentiel(nouveaux=tuple(sorted(act - ref)), disparus=tuple(sorted(ref - act)))


def petites_categories(cartographie: Iterable[EntreeCartographie], minimum: int) -> list[EntreeCartographie]:
    """Titres trop rares pour l'apprentissage (moins de `minimum` demandes)."""
    return [e for e in cartographie if e.nb_demandes < minimum]
