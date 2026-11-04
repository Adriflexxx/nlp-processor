"""Dépôts PostgreSQL (psycopg 3, sans ORM)."""

from __future__ import annotations

import uuid
from typing import Any

from psycopg.rows import dict_row
from psycopg.types.json import Jsonb
from psycopg_pool import ConnectionPool

from demandes.domaine.demande import Demande, LigneEcartee, empreinte_mail
from demandes.domaine.referentiel import EntreeCartographie
from demandes.ports.depots import EntreeJournal, InfoImport, Tache


class DepotCorpusPostgres:
    def __init__(self, pool: ConnectionPool) -> None:
        self.pool = pool

    def remplacer_corpus(self, fichier, empreinte_fichier, nb_lignes, demandes, ecartees, bilan) -> int:
        with self.pool.connection() as cnx:
            import_id = cnx.execute(
                "INSERT INTO imports (fichier, empreinte_fichier, nb_lignes, nb_retenues, nb_ecartees, bilan)"
                " VALUES (%s, %s, %s, %s, %s, %s) RETURNING id",
                (fichier, empreinte_fichier, nb_lignes, len(demandes), len(ecartees), Jsonb(bilan)),
            ).fetchone()[0]
            cnx.execute("DELETE FROM demandes")
            with cnx.cursor() as cur:
                # COPY : quelques dixièmes de seconde pour 10 000 mails.
                with cur.copy(
                    "COPY demandes (numero, date_demande, titre, mail, mail_nettoye, objet, template,"
                    " marqueurs_template, empreinte_mail, import_id) FROM STDIN"
                ) as copie:
                    for d in demandes:
                        copie.write_row(
                            (
                                d.numero, d.date, d.titre, d.mail, d.mail_nettoye, d.objet, d.template,
                                Jsonb(list(d.marqueurs_template)), empreinte_mail(d.mail), import_id,
                            )
                        )
                with cur.copy(
                    "COPY lignes_ecartees (import_id, ligne_source, numero, motif, detail) FROM STDIN"
                ) as copie:
                    for e in ecartees:
                        copie.write_row((import_id, e.ligne_source, e.numero, e.motif.value, e.detail))
            cnx.commit()
        return import_id

    def lister_demandes(self) -> list[Demande]:
        with self.pool.connection() as cnx:
            lignes = cnx.execute(
                "SELECT numero, titre, mail, mail_nettoye, objet, template, marqueurs_template, date_demande"
                " FROM demandes ORDER BY numero"
            ).fetchall()
        return [
            Demande(
                numero=n, titre=t, mail=m, mail_nettoye=mn, objet=o, template=tp,
                marqueurs_template=tuple(mq or ()), date=dt,
            )
            for n, t, m, mn, o, tp, mq, dt in lignes
        ]

    def dernier_import(self) -> InfoImport | None:
        with self.pool.connection() as cnx:
            ligne = cnx.execute(
                "SELECT id, fichier, empreinte_fichier, charge_le, nb_lignes, nb_retenues, nb_ecartees, bilan"
                " FROM imports ORDER BY id DESC LIMIT 1"
            ).fetchone()
        return InfoImport(*ligne) if ligne else None


class DepotReferentielPostgres:
    def __init__(self, pool: ConnectionPool) -> None:
        self.pool = pool

    def lire_reference(self) -> list[EntreeCartographie]:
        with self.pool.connection() as cnx:
            lignes = cnx.execute(
                "SELECT titre, nb_demandes, premiere_date, derniere_date FROM referentiel_titres"
                " ORDER BY nb_demandes DESC, titre"
            ).fetchall()
        return [EntreeCartographie(*ligne) for ligne in lignes]

    def figer_reference(self, entrees: list[EntreeCartographie]) -> None:
        with self.pool.connection() as cnx:
            cnx.execute("DELETE FROM referentiel_titres")
            with cnx.cursor() as cur:
                cur.executemany(
                    "INSERT INTO referentiel_titres (titre, nb_demandes, premiere_date, derniere_date)"
                    " VALUES (%s, %s, %s, %s)",
                    [(e.titre, e.nb_demandes, e.premiere_date, e.derniere_date) for e in entrees],
                )
            cnx.commit()


_COLONNES_TACHE = (
    "id::text AS id, type, statut, parametres, progression, etape, message, resultat, erreur,"
    " cree_le, demarre_le, termine_le"
)


class DepotTachesPostgres:
    def __init__(self, pool: ConnectionPool) -> None:
        self.pool = pool

    def _executer(self, requete: str, parametres: tuple) -> None:
        with self.pool.connection() as cnx:
            cnx.execute(requete, parametres)
            cnx.commit()

    def creer(self, type_tache: str, parametres: dict[str, Any]) -> Tache:
        tache_id = str(uuid.uuid4())
        with self.pool.connection() as cnx, cnx.cursor(row_factory=dict_row) as cur:
            ligne = cur.execute(
                f"INSERT INTO taches (id, type, statut, parametres) VALUES (%s, %s, 'en_attente', %s)"
                f" RETURNING {_COLONNES_TACHE}",
                (tache_id, type_tache, Jsonb(parametres)),
            ).fetchone()
            cnx.commit()
        return Tache(**ligne)

    def demarrer(self, tache_id: str) -> None:
        self._executer("UPDATE taches SET statut = 'en_cours', demarre_le = now() WHERE id = %s", (tache_id,))

    def terminer(self, tache_id: str, resultat: dict[str, Any]) -> None:
        self._executer(
            "UPDATE taches SET statut = 'terminee', progression = 1, resultat = %s, termine_le = now() WHERE id = %s",
            (Jsonb(resultat), tache_id),
        )

    def echouer(self, tache_id: str, erreur: str) -> None:
        self._executer(
            "UPDATE taches SET statut = 'echec', erreur = %s, termine_le = now() WHERE id = %s", (erreur, tache_id)
        )

    def journaliser(self, tache_id, niveau, message, progression, etape, donnees) -> None:
        with self.pool.connection() as cnx:
            cnx.execute(
                "INSERT INTO journal_taches (tache_id, niveau, message, progression, etape, donnees)"
                " VALUES (%s, %s, %s, %s, %s, %s)",
                (tache_id, niveau, message, progression, etape, Jsonb(donnees)),
            )
            cnx.execute(
                "UPDATE taches SET progression = %s, etape = %s, message = %s WHERE id = %s",
                (progression, etape, message, tache_id),
            )
            cnx.commit()

    def lire(self, tache_id: str) -> Tache | None:
        with self.pool.connection() as cnx, cnx.cursor(row_factory=dict_row) as cur:
            ligne = cur.execute(f"SELECT {_COLONNES_TACHE} FROM taches WHERE id = %s", (tache_id,)).fetchone()
        return Tache(**ligne) if ligne else None

    def lister(self, limite: int = 50) -> list[Tache]:
        with self.pool.connection() as cnx, cnx.cursor(row_factory=dict_row) as cur:
            lignes = cur.execute(
                f"SELECT {_COLONNES_TACHE} FROM taches ORDER BY cree_le DESC LIMIT %s", (limite,)
            ).fetchall()
        return [Tache(**ligne) for ligne in lignes]

    def lire_journal(self, tache_id: str, apres_id: int = 0, limite: int = 500) -> list[EntreeJournal]:
        with self.pool.connection() as cnx:
            lignes = cnx.execute(
                "SELECT id, tache_id::text, horodatage, niveau, message, progression, etape, donnees"
                " FROM journal_taches WHERE tache_id = %s AND id > %s ORDER BY id LIMIT %s",
                (tache_id, apres_id, limite),
            ).fetchall()
        return [EntreeJournal(*ligne) for ligne in lignes]

    def marquer_interrompues(self) -> int:
        with self.pool.connection() as cnx:
            n = cnx.execute(
                "UPDATE taches SET statut = 'echec', erreur = 'interrompue par un redémarrage', termine_le = now()"
                " WHERE statut IN ('en_cours', 'en_attente')"
            ).rowcount
            cnx.commit()
        return n
