"""Suivi d'avancement écrit dans le journal d'une tâche (et dans les logs)."""

from __future__ import annotations

import logging
from typing import Any

from demandes.ports.depots import DepotTaches
from demandes.ports.suivi import Suivi

journal = logging.getLogger("demandes")


class SuiviTache(Suivi):
    def __init__(self, depot: DepotTaches, tache_id: str) -> None:
        super().__init__()
        self.depot = depot
        self.tache_id = tache_id

    def _emettre(self, niveau: str, message: str, progression: float, etape: str | None, donnees: dict[str, Any]) -> None:
        journal.log(logging.getLevelName(niveau), "[tâche %s %3d%%] %s", self.tache_id[:8], round(progression * 100), message)
        self.depot.journaliser(self.tache_id, niveau, message, progression, etape, donnees)
