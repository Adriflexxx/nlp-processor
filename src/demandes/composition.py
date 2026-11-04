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
from demandes.adaptateurs.sortants.graphiques import GraphiquesMatplotlib
from demandes.adaptateurs.sortants.postgres.depots_evaluation import DepotEvaluationsPostgres, DepotPredictionsPostgres
from demandes.adaptateurs.sortants.postgres.depots_fiches import DepotFichesPostgres, DepotVecteursPostgres
from demandes.adaptateurs.sortants.simulateurs import GenerateurFichesSimule, VectoriseurSimule
from demandes.adaptateurs.sortants.suivi_taches import SuiviTache
from demandes.application.charger import Chargeur, ParametresChargement
from demandes.application.controle_lots import ControleLots
from demandes.application.empreintes import ConfigFiche
from demandes.application.generer_fiches import ETAPES as ETAPES_FICHES
from demandes.application.generer_fiches import ParametresFiches, ProductionFiches
from demandes.application.entrainer import Entrainement, ParametresEntrainement
from demandes.application.evaluer import Evaluation, ParametresEvaluation
from demandes.application.jeu import construire_jeu
from demandes.application.predire import ParametresPrediction, Prediction
from demandes.application.rapporter import ParametresRapport, Rapport
from demandes.application.retours import ColonnesExport, Retours
from demandes.application.taches import ExecuteurTaches
from demandes.domaine.combinaison import lire_combinaison
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
    def depot_evaluations(self) -> DepotEvaluationsPostgres:
        return DepotEvaluationsPostgres(self.pool)

    @cached_property
    def depot_predictions(self) -> DepotPredictionsPostgres:
        return DepotPredictionsPostgres(self.pool)

    @cached_property
    def graphiques(self) -> GraphiquesMatplotlib:
        return GraphiquesMatplotlib()

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

    def _numeros_test(self) -> set[str]:
        s = self.settings
        try:
            jeu = construire_jeu(self.depot_corpus.lister_demandes(), s.min_par_titre, s.taille_test, s.n_plis, s.seed)
        except ValueError:
            return set()
        return set(jeu.numeros[jeu.test].tolist())

    @cached_property
    def controle_lots(self) -> ControleLots:
        return ControleLots(
            self.depot_corpus, self.depot_fiches, self.generateur_fiches, self.config_fiche, self.artefacts,
            ParametresFiches.depuis(self.settings), self.settings.seed, self._numeros_test,
        )

    @cached_property
    def entrainement(self) -> Entrainement:
        s = self.settings
        return Entrainement(
            self.depot_corpus, self.depot_vecteurs, self.artefacts,
            ParametresEntrainement(
                s.min_par_titre, s.taille_test, s.n_plis, s.seed, s.n_processus, s.tfidf_caracteres,
                s.liste_acp_dimensions,
            ),
            self.production_fiches.config_vecteur.empreinte,
        )

    @cached_property
    def evaluation(self) -> Evaluation:
        s = self.settings
        return Evaluation(
            self.entrainement, self.depot_evaluations, self.artefacts,
            ParametresEvaluation(
                s.meta_modele, s.cible_precision_haut, s.cible_top3_moyen, s.desaccord_bloque,
                s.seuil_haut, s.seuil_moyen, s.seed, s.n_processus,
            ),
            self.depot_fiches, self.vectoriseur, self.config_fiche.empreinte,
        )

    @cached_property
    def rapport(self) -> Rapport:
        s = self.settings
        return Rapport(
            self.entrainement, self.depot_evaluations, self.artefacts, self.graphiques,
            ParametresRapport(s.reference, s.gain_min, self.generateur_fiches.modele, self.vectoriseur.modele),
        )

    @cached_property
    def prediction(self) -> Prediction:
        s = self.settings
        return Prediction(
            self.depot_evaluations, self.depot_predictions, self.artefacts, self.generateur_fiches, self.vectoriseur,
            ParametresPrediction(
                s.mode, tuple(s.liste_modeles), s.mail_max_caracteres, s.seuil_haut, s.seuil_moyen, s.desaccord_bloque
            ),
        )

    @cached_property
    def retours(self) -> Retours:
        s = self.settings
        return Retours(self.depot_predictions, ColonnesExport(s.colonne_numero, s.colonne_titre, s.colonne_mail, s.colonne_date))

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

    def _action_entrainer(self, parametres: dict[str, Any], suivi: Suivi) -> dict[str, Any]:
        return self.entrainement.executer(suivi, parametres.get("modeles") or None).en_dict()

    def _action_evaluer(self, parametres: dict[str, Any], suivi: Suivi) -> dict[str, Any]:
        combinaisons = None
        if parametres.get("mode") and parametres.get("modeles"):
            combinaisons = [lire_combinaison(parametres["mode"], parametres["modeles"])]
        return self.evaluation.executer(suivi, combinaisons, bool(parametres.get("temporel", False)))

    def _action_rapport(self, parametres: dict[str, Any], suivi: Suivi) -> dict[str, Any]:
        return self.rapport.executer(suivi)

    @cached_property
    def executeur(self) -> ExecuteurTaches:
        return ExecuteurTaches(
            self.depot_taches,
            lambda tache_id: SuiviTache(self.depot_taches, tache_id),
            {
                "charger": self._action_charger,
                "fiches": self._action_fiches,
                "controle_lots": self._action_controle_lots,
                "entrainer": self._action_entrainer,
                "evaluer": self._action_evaluer,
                "rapport": self._action_rapport,
            },
        )

    def fermer(self) -> None:
        if "executeur" in self.__dict__:
            self.executeur.arreter()
        if "pool" in self.__dict__:
            self.pool.close()
