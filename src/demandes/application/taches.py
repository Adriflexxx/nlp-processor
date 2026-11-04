"""Exécution des cas d'usage comme tâches suivies (en arrière-plan pour l'API, au premier plan pour la CLI)."""

from __future__ import annotations

import logging
import traceback
from collections.abc import Callable
from concurrent.futures import Future, ThreadPoolExecutor
from typing import Any

from demandes.ports.depots import DepotTaches, Tache
from demandes.ports.suivi import Suivi

journal = logging.getLogger("demandes")

# Une action reçoit les paramètres de la tâche et un suivi, et renvoie un résultat sérialisable en JSON.
Action = Callable[[dict[str, Any], Suivi], dict[str, Any]]
FabriqueSuivi = Callable[[str], Suivi]


class TypeTacheInconnu(KeyError):
    pass


class ExecuteurTaches:
    """Lance les tâches une par une dans un fil dédié.

    Une seule tâche tourne à la fois : chacune utilise déjà tous les cœurs
    (processus de calcul) ou la concurrence permise par l'IAG.
    """

    def __init__(self, depot: DepotTaches, fabrique_suivi: FabriqueSuivi, actions: dict[str, Action]) -> None:
        self.depot = depot
        self.fabrique_suivi = fabrique_suivi
        self.actions = actions
        self._pool = ThreadPoolExecutor(max_workers=1, thread_name_prefix="tache")

    def _verifier(self, type_tache: str) -> Action:
        if type_tache not in self.actions:
            raise TypeTacheInconnu(f"type de tâche inconnu : {type_tache} (connus : {sorted(self.actions)})")
        return self.actions[type_tache]

    def soumettre(self, type_tache: str, parametres: dict[str, Any]) -> tuple[Tache, Future]:
        """Crée la tâche et la met en file ; renvoie aussitôt."""
        self._verifier(type_tache)
        tache = self.depot.creer(type_tache, parametres)
        return tache, self._pool.submit(self._executer, tache.id, type_tache, parametres)

    def executer_maintenant(self, type_tache: str, parametres: dict[str, Any]) -> tuple[Tache, dict[str, Any]]:
        """Crée la tâche et l'exécute dans le fil courant (ligne de commande)."""
        self._verifier(type_tache)
        tache = self.depot.creer(type_tache, parametres)
        return tache, self._executer(tache.id, type_tache, parametres, relancer=True)

    def _executer(self, tache_id: str, type_tache: str, parametres: dict[str, Any], relancer: bool = False) -> dict[str, Any]:
        action = self.actions[type_tache]
        self.depot.demarrer(tache_id)
        suivi = self.fabrique_suivi(tache_id)
        try:
            resultat = action(parametres, suivi)
        except Exception as erreur:  # noqa: BLE001 - toute erreur doit être tracée dans la tâche
            message = f"{type(erreur).__name__} : {erreur}"
            journal.error("Tâche %s en échec : %s\n%s", tache_id, message, traceback.format_exc())
            try:
                suivi.alerte(f"Échec : {message}")
            finally:
                self.depot.echouer(tache_id, message)
            if relancer:
                raise
            return {}
        self.depot.terminer(tache_id, resultat)
        return resultat

    def arreter(self) -> None:
        self._pool.shutdown(wait=False, cancel_futures=True)
