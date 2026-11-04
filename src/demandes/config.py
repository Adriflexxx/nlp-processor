"""Configuration du banc d'essai, lue depuis l'environnement et le fichier .env.

Toute la configuration passe par la classe `Settings`. Les éléments qui
« figent » une configuration (prompt, modèles, hyperparamètres) entrent dans
des empreintes calculées ailleurs (voir ADR-0007).
"""

from __future__ import annotations

import os
from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

MODELES_CONNUS = ("svm_tfidf", "rl_tfidf", "svm_emb", "rl_emb", "knn_emb")


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    # Base de données
    database_url: str = "postgresql://demandes:demandes@localhost:5433/demandes"

    # Mapping des colonnes de l'export
    colonne_numero: str = "numero"
    colonne_titre: str = "titre"
    colonne_mail: str = "description"
    colonne_date: str = "date"
    feuille_excel: str = ""

    # IAG
    iag_base_url: str = "http://localhost:8080/v1"
    iag_api_key: str = "inutile"
    iag_modele: str = "modele-interne"
    iag_temperature: float = 0.0
    iag_timeout_s: float = 120.0
    json_mode: Literal["json_schema", "json_object"] = "json_schema"
    prompt_fiche: str = "prompts/fiche_v1.md"
    # Fiches par lots (ADR-0010)
    fiches_par_appel: int = Field(10, ge=1)
    lot_max_caracteres: int = Field(40_000, ge=1_000)
    mail_max_caracteres: int = Field(8_000, ge=500)
    iag_max_tokens_par_fiche: int = Field(400, ge=50)
    fiches_a_l_ingestion: bool = True

    # Embedding
    emb_base_url: str = "http://localhost:8081/v1"
    emb_api_key: str = "inutile"
    emb_modele: str = "bge-m3"
    emb_dimension: int = 1024
    embed_par_appel: int = Field(100, ge=1)

    mock_llm: bool = False

    # Apprentissage et évaluation
    seed: int = 42
    min_par_titre: int = Field(10, ge=2)
    taille_test: float = Field(0.2, gt=0, lt=1)
    n_plis: int = Field(5, ge=2)
    llm_concurrency: int = Field(4, ge=1)
    n_jobs: int = -1

    # Mode de décision
    mode: Literal["seul", "moyenne", "meta"] = "seul"
    modeles: str = "svm_tfidf"

    # Seuils
    seuil_haut: float = 0.80
    seuil_moyen: float = 0.40

    # Repérage des templates
    template_min_mails: int = Field(5, ge=2)
    template_freq_max: float = Field(0.30, gt=0, le=1)
    template_min_marqueurs: int = Field(2, ge=1)
    template_objet: bool = True
    template_motifs: str = ""

    # Divers
    dossier_artefacts: str = "artefacts"
    dossier_donnees: str = "donnees"
    niveau_log: str = "INFO"

    @field_validator("modeles")
    @classmethod
    def _verifier_modeles(cls, valeur: str) -> str:
        inconnus = [m for m in _decouper(valeur, ",") if m not in MODELES_CONNUS]
        if inconnus:
            raise ValueError(f"modèles inconnus : {inconnus} (connus : {MODELES_CONNUS})")
        return valeur

    # --- Valeurs dérivées -------------------------------------------------

    @property
    def liste_modeles(self) -> list[str]:
        return _decouper(self.modeles, ",")

    @property
    def liste_motifs_template(self) -> list[str]:
        return _decouper(self.template_motifs, ";;")

    @property
    def mapping_colonnes(self) -> dict[str, str]:
        """Nom de colonne dans l'Excel → nom interne. La date est facultative."""
        mapping = {
            self.colonne_numero: "numero",
            self.colonne_titre: "titre",
            self.colonne_mail: "mail",
        }
        if self.colonne_date.strip():
            mapping[self.colonne_date] = "date"
        return mapping

    @property
    def n_processus(self) -> int:
        """Nombre de processus réellement utilisés pour le calcul."""
        if self.n_jobs is None or self.n_jobs == 0:
            return 1
        if self.n_jobs < 0:
            return max(1, (os.cpu_count() or 1) + 1 + self.n_jobs)
        return self.n_jobs

    @property
    def chemin_artefacts(self) -> Path:
        return Path(self.dossier_artefacts)


def _decouper(valeur: str, separateur: str) -> list[str]:
    return [morceau.strip() for morceau in valeur.split(separateur) if morceau.strip()]


@lru_cache
def obtenir_settings() -> Settings:
    return Settings()
