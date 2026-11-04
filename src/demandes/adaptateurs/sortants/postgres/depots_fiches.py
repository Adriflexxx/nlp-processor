"""Dépôts PostgreSQL des fiches et des vecteurs (pgvector)."""

from __future__ import annotations

from typing import Any

import numpy as np
from pgvector.psycopg import register_vector
from psycopg.types.json import Jsonb
from psycopg_pool import ConnectionPool

from demandes.ports.depots import EchecFiche, FicheStockee


class DepotFichesPostgres:
    def __init__(self, pool: ConnectionPool) -> None:
        self.pool = pool

    def enregistrer_configuration(self, empreinte: str, contenu: dict[str, Any]) -> None:
        with self.pool.connection() as cnx:
            cnx.execute(
                "INSERT INTO configurations (empreinte, nature, contenu) VALUES (%s, %s, %s)"
                " ON CONFLICT (empreinte) DO NOTHING",
                (empreinte, contenu.get("nature", ""), Jsonb(contenu)),
            )
            cnx.commit()

    def etats(self, empreinte_fiche: str) -> dict[str, tuple[str, str]]:
        with self.pool.connection() as cnx:
            echecs = cnx.execute(
                "SELECT numero, empreinte_mail FROM echecs_fiches WHERE empreinte_fiche = %s", (empreinte_fiche,)
            ).fetchall()
            ok = cnx.execute(
                "SELECT numero, empreinte_mail FROM fiches WHERE empreinte_fiche = %s", (empreinte_fiche,)
            ).fetchall()
        etats = {n: ("echec", em) for n, em in echecs}
        etats.update({n: ("ok", em) for n, em in ok})
        return etats

    def enregistrer_fiches(self, empreinte_fiche: str, fiches: list[FicheStockee]) -> None:
        if not fiches:
            return
        with self.pool.connection() as cnx, cnx.cursor() as cur:
            cur.executemany(
                "INSERT INTO fiches (numero, empreinte_fiche, empreinte_mail, fiche, taille_lot, tentatives, duree_ms)"
                " VALUES (%s, %s, %s, %s, %s, %s, %s)"
                " ON CONFLICT (empreinte_fiche, numero) DO UPDATE SET empreinte_mail = EXCLUDED.empreinte_mail,"
                " fiche = EXCLUDED.fiche, taille_lot = EXCLUDED.taille_lot, tentatives = EXCLUDED.tentatives,"
                " duree_ms = EXCLUDED.duree_ms, cree_le = now()",
                [
                    (f.numero, empreinte_fiche, f.empreinte_mail, Jsonb(f.fiche), f.taille_lot, f.tentatives, f.duree_ms)
                    for f in fiches
                ],
            )
            cur.execute(
                "DELETE FROM echecs_fiches WHERE empreinte_fiche = %s AND numero = ANY(%s)",
                (empreinte_fiche, [f.numero for f in fiches]),
            )
            cnx.commit()

    def enregistrer_echecs(self, empreinte_fiche: str, echecs: list[EchecFiche]) -> None:
        if not echecs:
            return
        with self.pool.connection() as cnx, cnx.cursor() as cur:
            cur.executemany(
                "INSERT INTO echecs_fiches (numero, empreinte_fiche, empreinte_mail, tentatives, erreur)"
                " VALUES (%s, %s, %s, %s, %s)"
                " ON CONFLICT (empreinte_fiche, numero) DO UPDATE SET empreinte_mail = EXCLUDED.empreinte_mail,"
                " tentatives = EXCLUDED.tentatives, erreur = EXCLUDED.erreur, cree_le = now()",
                [(e.numero, empreinte_fiche, e.empreinte_mail, e.tentatives, e.erreur) for e in echecs],
            )
            cnx.commit()

    def _lire(self, table: str, empreinte_fiche: str, numeros: list[str] | None) -> dict[str, FicheStockee]:
        colonne_lot = "taille_lot" if table == "fiches" else "1"
        requete = (
            f"SELECT numero, empreinte_mail, fiche, {colonne_lot}, tentatives, duree_ms FROM {table}"
            " WHERE empreinte_fiche = %s"
        )
        parametres: tuple = (empreinte_fiche,)
        if numeros is not None:
            requete += " AND numero = ANY(%s)"
            parametres += (numeros,)
        with self.pool.connection() as cnx:
            lignes = cnx.execute(requete, parametres).fetchall()
        return {ligne[0]: FicheStockee(*ligne) for ligne in lignes}

    def lire_fiches(self, empreinte_fiche: str, numeros: list[str] | None = None) -> dict[str, FicheStockee]:
        return self._lire("fiches", empreinte_fiche, numeros)

    def lire_echecs(self, empreinte_fiche: str) -> list[EchecFiche]:
        with self.pool.connection() as cnx:
            lignes = cnx.execute(
                "SELECT numero, empreinte_mail, tentatives, erreur FROM echecs_fiches"
                " WHERE empreinte_fiche = %s ORDER BY numero",
                (empreinte_fiche,),
            ).fetchall()
        return [EchecFiche(*ligne) for ligne in lignes]

    def enregistrer_controle(self, empreinte_fiche: str, fiches: list[FicheStockee]) -> None:
        if not fiches:
            return
        with self.pool.connection() as cnx, cnx.cursor() as cur:
            cur.executemany(
                "INSERT INTO fiches_controle (numero, empreinte_fiche, empreinte_mail, fiche, tentatives, duree_ms)"
                " VALUES (%s, %s, %s, %s, %s, %s)"
                " ON CONFLICT (empreinte_fiche, numero) DO UPDATE SET empreinte_mail = EXCLUDED.empreinte_mail,"
                " fiche = EXCLUDED.fiche, tentatives = EXCLUDED.tentatives, duree_ms = EXCLUDED.duree_ms,"
                " cree_le = now()",
                [(f.numero, empreinte_fiche, f.empreinte_mail, Jsonb(f.fiche), f.tentatives, f.duree_ms) for f in fiches],
            )
            cnx.commit()

    def lire_controle(self, empreinte_fiche: str) -> dict[str, FicheStockee]:
        return self._lire("fiches_controle", empreinte_fiche, None)


class DepotVecteursPostgres:
    def __init__(self, pool: ConnectionPool) -> None:
        self.pool = pool

    def numeros_vectorises(self, empreinte_vecteur: str) -> dict[str, str]:
        with self.pool.connection() as cnx:
            lignes = cnx.execute(
                "SELECT numero, empreinte_mail FROM vecteurs WHERE empreinte_vecteur = %s", (empreinte_vecteur,)
            ).fetchall()
        return dict(lignes)

    def enregistrer_vecteurs(
        self,
        empreinte_vecteur: str,
        empreinte_fiche: str,
        numeros: list[str],
        empreintes_mail: list[str],
        matrice: np.ndarray,
    ) -> None:
        with self.pool.connection() as cnx:
            register_vector(cnx)
            with cnx.cursor() as cur:
                cur.executemany(
                    "INSERT INTO vecteurs (numero, empreinte_vecteur, empreinte_fiche, empreinte_mail, vecteur)"
                    " VALUES (%s, %s, %s, %s, %s)"
                    " ON CONFLICT (empreinte_vecteur, numero) DO UPDATE SET empreinte_fiche = EXCLUDED.empreinte_fiche,"
                    " empreinte_mail = EXCLUDED.empreinte_mail, vecteur = EXCLUDED.vecteur, cree_le = now()",
                    [
                        (n, empreinte_vecteur, empreinte_fiche, em, np.asarray(v, dtype=np.float32))
                        for n, em, v in zip(numeros, empreintes_mail, matrice, strict=True)
                    ],
                )
            cnx.commit()

    def lire_vecteurs(self, empreinte_vecteur: str, numeros: list[str] | None = None) -> tuple[list[str], np.ndarray]:
        requete = "SELECT numero, vecteur FROM vecteurs WHERE empreinte_vecteur = %s"
        parametres: tuple = (empreinte_vecteur,)
        if numeros is not None:
            requete += " AND numero = ANY(%s)"
            parametres += (numeros,)
        with self.pool.connection() as cnx:
            register_vector(cnx)
            lignes = cnx.execute(requete + " ORDER BY numero", parametres).fetchall()
        if not lignes:
            return [], np.zeros((0, 0), dtype=np.float32)
        return [n for n, _ in lignes], np.vstack([_en_numpy(v) for _, v in lignes])


def _en_numpy(valeur) -> np.ndarray:
    """pgvector renvoie un objet Vector (versions récentes) ou un tableau numpy (anciennes)."""
    if hasattr(valeur, "to_numpy"):
        valeur = valeur.to_numpy()
    return np.asarray(valeur, dtype=np.float32)
