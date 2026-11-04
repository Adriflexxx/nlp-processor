"""Port de suivi de l'avancement : étapes, progression, journal.

Les cas d'usage décrivent leurs étapes et signalent leur avancement ; un
adaptateur décide où l'écrire (console pour la ligne de commande, table
`journal_taches` pour l'API). Voir l'ADR-0008.
"""

from __future__ import annotations

import logging
import time
from abc import ABC, abstractmethod
from typing import Any

journal = logging.getLogger("demandes")


class Suivi(ABC):
    """Base commune : calcule la progression globale et limite le débit des messages."""

    #: intervalle minimal entre deux messages de progression d'une même étape
    INTERVALLE_S = 1.0

    def __init__(self) -> None:
        self._etapes: list[str] = []
        self._index = -1
        self._dernier_envoi = 0.0
        self._derniere_part = -1.0

    # --- API utilisée par les cas d'usage ---------------------------------

    def demarrer(self, etapes: list[str]) -> None:
        self._etapes = list(etapes)
        self._index = -1
        self._emettre("INFO", f"Démarrage : {len(etapes)} étapes ({', '.join(etapes)})", 0.0, None, {})

    def etape(self, nom: str) -> None:
        if nom in self._etapes:
            self._index = self._etapes.index(nom)
        else:
            self._etapes.append(nom)
            self._index = len(self._etapes) - 1
        self._derniere_part = -1.0
        self._emettre("INFO", f"Étape {self._index + 1}/{len(self._etapes)} : {nom}", self.progression(0.0), nom, {})

    def avancer(self, fait: int, total: int, message: str = "") -> None:
        part = fait / total if total else 1.0
        maintenant = time.monotonic()
        fin = fait >= total
        if not fin and (maintenant - self._dernier_envoi < self.INTERVALLE_S or part - self._derniere_part < 0.01):
            return
        self._dernier_envoi, self._derniere_part = maintenant, part
        texte = f"{fait}/{total}" + (f" — {message}" if message else "")
        self._emettre("INFO", texte, self.progression(part), self.etape_courante, {"fait": fait, "total": total})

    def info(self, message: str, **donnees: Any) -> None:
        self._emettre("INFO", message, self.progression(self._derniere_part_valide()), self.etape_courante, donnees)

    def alerte(self, message: str, **donnees: Any) -> None:
        self._emettre("WARNING", message, self.progression(self._derniere_part_valide()), self.etape_courante, donnees)

    def terminer(self, message: str = "Terminé", **donnees: Any) -> None:
        self._emettre("INFO", message, 1.0, self.etape_courante, donnees)

    # --- Calculs -----------------------------------------------------------

    @property
    def etape_courante(self) -> str | None:
        return self._etapes[self._index] if 0 <= self._index < len(self._etapes) else None

    def progression(self, part_etape: float) -> float:
        if not self._etapes or self._index < 0:
            return 0.0
        return min(1.0, (self._index + max(0.0, min(1.0, part_etape))) / len(self._etapes))

    def _derniere_part_valide(self) -> float:
        return max(0.0, self._derniere_part)

    @abstractmethod
    def _emettre(self, niveau: str, message: str, progression: float, etape: str | None, donnees: dict[str, Any]) -> None:
        """Écrit un message de suivi."""


class SuiviJournal(Suivi):
    """Suivi vers le module logging (console de la ligne de commande, tests)."""

    def __init__(self) -> None:
        super().__init__()
        self.messages: list[tuple[str, str, float]] = []

    def _emettre(self, niveau: str, message: str, progression: float, etape: str | None, donnees: dict[str, Any]) -> None:
        self.messages.append((niveau, message, progression))
        journal.log(logging.getLevelName(niveau), "[%3d%%] %s", round(progression * 100), message)
