"""Dépôts PostgreSQL des évaluations et du journal des prédictions."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from psycopg.types.json import Jsonb
from psycopg_pool import ConnectionPool

from demandes.ports.depots import PredictionJournal


class DepotEvaluationsPostgres:
    def __init__(self, pool: ConnectionPool) -> None:
        self.pool = pool

    def enregistrer_evaluation(self, empreinte_jeu: str, nom: str, contenu: dict[str, Any]) -> None:
        with self.pool.connection() as cnx:
            cnx.execute(
                "INSERT INTO evaluations (empreinte_jeu, nom, contenu) VALUES (%s, %s, %s)"
                " ON CONFLICT (empreinte_jeu, nom) DO UPDATE SET contenu = EXCLUDED.contenu, cree_le = now()",
                (empreinte_jeu, nom, Jsonb(contenu)),
            )
            cnx.commit()

    def lister_evaluations(self, empreinte_jeu: str | None = None) -> list[dict[str, Any]]:
        with self.pool.connection() as cnx:
            if empreinte_jeu is None:
                ligne = cnx.execute("SELECT empreinte_jeu FROM evaluations ORDER BY cree_le DESC LIMIT 1").fetchone()
                if ligne is None:
                    return []
                empreinte_jeu = ligne[0]
            lignes = cnx.execute(
                "SELECT nom, contenu FROM evaluations WHERE empreinte_jeu = %s ORDER BY cree_le DESC",
                (empreinte_jeu,),
            ).fetchall()
        return [{"empreinte_jeu": empreinte_jeu, "nom": nom, **contenu} for nom, contenu in lignes]


_COLONNES = "id, horodatage, mail, configuration, top3, niveau, avis, titre_retenu, operateur, retenu_le"


class DepotPredictionsPostgres:
    def __init__(self, pool: ConnectionPool) -> None:
        self.pool = pool

    def journaliser(self, mail: str, configuration: dict, top3: list, niveau: str, avis: list) -> int:
        with self.pool.connection() as cnx:
            identifiant = cnx.execute(
                "INSERT INTO predictions (mail, configuration, top3, niveau, avis) VALUES (%s, %s, %s, %s, %s)"
                " RETURNING id",
                (mail, Jsonb(configuration), Jsonb(top3), niveau, Jsonb(avis)),
            ).fetchone()[0]
            cnx.commit()
        return identifiant

    def enregistrer_retour(self, prediction_id: int, titre_retenu: str, operateur: str | None) -> bool:
        with self.pool.connection() as cnx:
            n = cnx.execute(
                "UPDATE predictions SET titre_retenu = %s, operateur = %s, retenu_le = now() WHERE id = %s",
                (titre_retenu, operateur, prediction_id),
            ).rowcount
            cnx.commit()
        return n == 1

    def lire(self, prediction_id: int) -> PredictionJournal | None:
        with self.pool.connection() as cnx:
            ligne = cnx.execute(f"SELECT {_COLONNES} FROM predictions WHERE id = %s", (prediction_id,)).fetchone()
        return PredictionJournal(*ligne) if ligne else None

    def lister(self, depuis: datetime | None = None, avec_retour: bool | None = None) -> list[PredictionJournal]:
        requete, parametres = f"SELECT {_COLONNES} FROM predictions WHERE true", []
        if depuis is not None:
            requete += " AND horodatage >= %s"
            parametres.append(depuis)
        if avec_retour is True:
            requete += " AND titre_retenu IS NOT NULL"
        elif avec_retour is False:
            requete += " AND titre_retenu IS NULL"
        with self.pool.connection() as cnx:
            lignes = cnx.execute(requete + " ORDER BY id", parametres).fetchall()
        return [PredictionJournal(*ligne) for ligne in lignes]
