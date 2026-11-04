"""Câblage : choisit les adaptateurs et assemble les cas d'usage à partir de Settings.

C'est le seul endroit qui connaît à la fois le cœur et les adaptateurs concrets.
"""

from __future__ import annotations

import logging
from functools import cached_property
from pathlib import Path
from typing import Any

from demandes.adaptateurs.sortants.excel import SourceExcel
from demandes.adaptateurs.sortants.fichiers import StockageFichiers
from demandes.adaptateurs.sortants.iag_openai import GenerateurFichesOpenAI, VectoriseurOpenAI
from demandes.adaptateurs.sortants.postgres.connexion import creer_pool, migrer
from demandes.adaptateurs.sortants.postgres.depots import (
    DepotCorpusPostgres,
    DepotReferentielPostgres,
    DepotTachesPostgres,
)
from demandes.adaptateurs.sortants.postgres.depots_fiches import DepotFichesPostgres, DepotVecteursPostgres
from demandes.adaptateurs.sortants.simulateurs import GenerateurFichesSimule, VectoriseurSimule
from demandes.adaptateurs.sortants.suivi_taches import SuiviTache
from demandes.application.charger import Chargeur, ParametresChargement
from demandes.application.controle_lots import ControleLots
from demandes.application.empreintes import ConfigFiche
from demandes.application.generer_fiches import ETAPES as ETAPES_FICHES
from demandes.application.generer_fiches import ParametresFiches, ProductionFiches
from demandes.application.taches import ExecuteurTaches
from demandes.config import Settings, obtenir_settings
from demandes.parallele import limiter_threads_blas
from demandes.ports.suivi import Suivi


def configurer_journal(niveau: str = "INFO") -> None:
    logging.basicConfig(
        level=niveau.upper(),
        format="%(asctime)s %(levelname)-7s %(name)s : %(message)s",
        datefmt="%H:%M:%S",
    )
    logging.getLogger("httpx").setLevel(logging.WARNING)


class Conteneur:
    def __init__(self, settings: Settings | None = None) -> None:
        self.settings = settings or obtenir_settings()
        limiter_threads_blas()

    # --- Adaptateurs sortants ----------------------------------------------

    @cached_property
    def pool(self):
        return creer_pool(self.settings.database_url)

    def migrer(self) -> list[str]:
        return migrer(self.pool)

    @cached_property
    def depot_corpus(self) -> DepotCorpusPostgres:
        return DepotCorpusPostgres(self.pool)

    @cached_property
    def depot_referentiel(self) -> DepotReferentielPostgres:
        return DepotReferentielPostgres(self.pool)

    @cached_property
    def depot_taches(self) -> DepotTachesPostgres:
        return DepotTachesPostgres(self.pool)

    @cached_property
    def depot_fiches(self) -> DepotFichesPostgres:
        return DepotFichesPostgres(self.pool)

    @cached_property
    def depot_vecteurs(self) -> DepotVecteursPostgres:
        return DepotVecteursPostgres(self.pool)

    @cached_property
    def artefacts(self) -> StockageFichiers:
        return StockageFichiers(self.settings.chemin_artefacts)

    @cached_property
    def consigne_fiche(self) -> str:
        return Path(self.settings.prompt_fiche).read_text(encoding="utf-8")

    @cached_property
    def generateur_fiches(self):
        s = self.settings
        if s.mock_llm:
            return GenerateurFichesSimule(modele=f"mock:{s.iag_modele}")
        return GenerateurFichesOpenAI(
            s.iag_base_url, s.iag_api_key, s.iag_modele, self.consigne_fiche, s.iag_temperature,
            s.json_mode, s.iag_max_tokens_par_fiche, s.iag_timeout_s,
        )

    @cached_property
    def vectoriseur(self):
        s = self.settings
        if s.mock_llm:
            return VectoriseurSimule(s.emb_dimension, modele=f"mock:{s.emb_modele}")
        return VectoriseurOpenAI(s.emb_base_url, s.emb_api_key, s.emb_modele, s.emb_dimension, s.iag_timeout_s)

    @cached_property
    def config_fiche(self) -> ConfigFiche:
        s = self.settings
        return ConfigFiche(
            consigne=self.consigne_fiche,
            modele=self.generateur_fiches.modele,
            temperature=s.iag_temperature,
            json_mode=s.json_mode,
            mail_max_caracteres=s.mail_max_caracteres,
        )

    # --- Cas d'usage --------------------------------------------------------

    @cached_property
    def chargeur(self) -> Chargeur:
        return Chargeur(
            SourceExcel(),
            self.depot_corpus,
            self.depot_referentiel,
            self.artefacts,
            ParametresChargement.depuis(self.settings),
        )

    @cached_property
    def production_fiches(self) -> ProductionFiches:
        return ProductionFiches(
            self.depot_corpus, self.depot_fiches, self.depot_vecteurs, self.generateur_fiches, self.vectoriseur,
            self.config_fiche, self.artefacts, ParametresFiches.depuis(self.settings),
        )

    @cached_property
    def controle_lots(self) -> ControleLots:
        return ControleLots(
            self.depot_corpus, self.depot_fiches, self.generateur_fiches, self.config_fiche, self.artefacts,
            ParametresFiches.depuis(self.settings), self.settings.seed,
        )

    def _action_charger(self, parametres: dict[str, Any], suivi: Suivi) -> dict[str, Any]:
        avec_fiches = parametres.get("avec_fiches")
        if avec_fiches is None:
            avec_fiches = self.settings.fiches_a_l_ingestion
        chargement = self.chargeur.executer(
            Path(parametres["fichier"]), suivi, bool(parametres.get("nouvelle_reference", False)),
            etapes_suivantes=ETAPES_FICHES if avec_fiches else None,
        )
        resultat: dict[str, Any] = {"chargement": chargement.en_dict()}
        if avec_fiches:
            fiches = self.production_fiches.executer(suivi, deja_demarre=True)
            resultat["fiches"] = fiches.en_dict()
            suivi.terminer(
                f"Ingestion terminée : {chargement.nb_retenues} demandes, "
                f"{fiches.fiches_en_cache + fiches.fiches_en_lot + fiches.fiches_a_l_unite} fiches, "
                f"{fiches.echecs_total} en échec, {fiches.vecteurs_en_cache + fiches.vecteurs_calcules} vecteurs"
            )
        return resultat

    def _action_fiches(self, parametres: dict[str, Any], suivi: Suivi) -> dict[str, Any]:
        return self.production_fiches.executer(suivi, bool(parametres.get("reprendre_echecs", False))).en_dict()

    def _action_controle_lots(self, parametres: dict[str, Any], suivi: Suivi) -> dict[str, Any]:
        return self.controle_lots.executer(suivi, int(parametres.get("taille", 200))).en_dict()

    @cached_property
    def executeur(self) -> ExecuteurTaches:
        return ExecuteurTaches(
            self.depot_taches,
            lambda tache_id: SuiviTache(self.depot_taches, tache_id),
            {
                "charger": self._action_charger,
                "fiches": self._action_fiches,
                "controle_lots": self._action_controle_lots,
            },
        )

    def fermer(self) -> None:
        if "executeur" in self.__dict__:
            self.executeur.arreter()
        if "pool" in self.__dict__:
            self.pool.close()
