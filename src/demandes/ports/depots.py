"""Ports de persistance (implémentés en PostgreSQL et en mémoire)."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Protocol

import numpy as np

from demandes.domaine.demande import Demande, LigneEcartee
from demandes.domaine.referentiel import EntreeCartographie


@dataclass(frozen=True, slots=True)
class InfoImport:
    id: int
    fichier: str
    empreinte_fichier: str
    charge_le: datetime
    nb_lignes: int
    nb_retenues: int
    nb_ecartees: int
    bilan: dict[str, Any] = field(default_factory=dict)


class DepotCorpus(Protocol):
    def remplacer_corpus(
        self,
        fichier: str,
        empreinte_fichier: str,
        nb_lignes: int,
        demandes: list[Demande],
        ecartees: list[LigneEcartee],
        bilan: dict[str, Any],
    ) -> int:
        """Remplace le corpus courant de façon atomique ; renvoie l'id de l'import.

        Les fiches et vecteurs déjà calculés ne sont pas touchés : ils sont
        indexés par numéro et empreinte, et resservent d'un import à l'autre.
        """
        ...

    def lister_demandes(self) -> list[Demande]: ...

    def dernier_import(self) -> InfoImport | None: ...


class DepotReferentiel(Protocol):
    def lire_reference(self) -> list[EntreeCartographie]:
        """Référence figée des Titres ; liste vide s'il n'y en a pas encore."""
        ...

    def figer_reference(self, entrees: list[EntreeCartographie]) -> None:
        """Remplace la référence par la cartographie donnée."""
        ...


@dataclass(frozen=True, slots=True)
class FicheStockee:
    numero: str
    empreinte_mail: str
    fiche: dict[str, Any]
    taille_lot: int  # nombre de mails de l'appel qui l'a produite (1 = à l'unité)
    tentatives: int
    duree_ms: int


@dataclass(frozen=True, slots=True)
class EchecFiche:
    numero: str
    empreinte_mail: str
    tentatives: int
    erreur: str


class DepotFiches(Protocol):
    def enregistrer_configuration(self, empreinte: str, contenu: dict[str, Any]) -> None:
        """Mémorise ce que recouvre une empreinte (prompt, modèles…), pour la traçabilité."""
        ...

    def etats(self, empreinte_fiche: str) -> dict[str, tuple[str, str]]:
        """numéro → (statut « ok » ou « echec », empreinte du mail) pour cette configuration."""
        ...

    def enregistrer_fiches(self, empreinte_fiche: str, fiches: list[FicheStockee]) -> None:
        """Enregistre des fiches valides (remplace un éventuel échec antérieur)."""
        ...

    def enregistrer_echecs(self, empreinte_fiche: str, echecs: list[EchecFiche]) -> None: ...

    def lire_fiches(self, empreinte_fiche: str, numeros: list[str] | None = None) -> dict[str, FicheStockee]: ...

    def lire_echecs(self, empreinte_fiche: str) -> list[EchecFiche]: ...

    def enregistrer_controle(self, empreinte_fiche: str, fiches: list[FicheStockee]) -> None:
        """Fiches produites à l'unité pour le contrôle qualité lot / unité (table séparée)."""
        ...

    def lire_controle(self, empreinte_fiche: str) -> dict[str, FicheStockee]: ...


class DepotVecteurs(Protocol):
    def numeros_vectorises(self, empreinte_vecteur: str) -> dict[str, str]:
        """numéro → empreinte du mail dont le vecteur est issu."""
        ...

    def enregistrer_vecteurs(
        self,
        empreinte_vecteur: str,
        empreinte_fiche: str,
        numeros: list[str],
        empreintes_mail: list[str],
        matrice: np.ndarray,
    ) -> None:
        """Une ligne de `matrice` (float32, normalisée) par numéro ; remplace un vecteur existant."""
        ...

    def lire_vecteurs(self, empreinte_vecteur: str, numeros: list[str] | None = None) -> tuple[list[str], np.ndarray]:
        """(numéros triés, matrice n × dimension en float32)."""
        ...


StatutTache = str  # "en_attente" | "en_cours" | "terminee" | "echec"


@dataclass(slots=True)
class Tache:
    id: str
    type: str
    statut: StatutTache
    parametres: dict[str, Any]
    progression: float = 0.0
    etape: str | None = None
    message: str | None = None
    resultat: dict[str, Any] | None = None
    erreur: str | None = None
    cree_le: datetime | None = None
    demarre_le: datetime | None = None
    termine_le: datetime | None = None


@dataclass(frozen=True, slots=True)
class EntreeJournal:
    id: int
    tache_id: str
    horodatage: datetime
    niveau: str
    message: str
    progression: float
    etape: str | None
    donnees: dict[str, Any]


class DepotTaches(Protocol):
    def creer(self, type_tache: str, parametres: dict[str, Any]) -> Tache: ...

    def demarrer(self, tache_id: str) -> None: ...

    def terminer(self, tache_id: str, resultat: dict[str, Any]) -> None: ...

    def echouer(self, tache_id: str, erreur: str) -> None: ...

    def journaliser(
        self, tache_id: str, niveau: str, message: str, progression: float, etape: str | None, donnees: dict[str, Any]
    ) -> None:
        """Ajoute une ligne au journal et met à jour progression / étape / message de la tâche."""
        ...

    def lire(self, tache_id: str) -> Tache | None: ...

    def lister(self, limite: int = 50) -> list[Tache]: ...

    def lire_journal(self, tache_id: str, apres_id: int = 0, limite: int = 500) -> list[EntreeJournal]: ...

    def marquer_interrompues(self) -> int:
        """Passe en échec les tâches restées « en_cours » (redémarrage du service)."""
        ...
