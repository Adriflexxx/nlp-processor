"""Pool de connexions PostgreSQL et application des migrations SQL."""

from __future__ import annotations

import logging
from pathlib import Path

from psycopg_pool import ConnectionPool

journal = logging.getLogger("demandes.postgres")
DOSSIER_MIGRATIONS = Path(__file__).parent / "migrations"


def creer_pool(database_url: str, taille_max: int = 10) -> ConnectionPool:
    pool = ConnectionPool(database_url, min_size=1, max_size=taille_max, open=False, kwargs={"autocommit": False})
    pool.open(wait=True, timeout=30)
    return pool


def migrer(pool: ConnectionPool, dossier: Path = DOSSIER_MIGRATIONS) -> list[str]:
    """Applique, dans l'ordre, les fichiers NNNN_*.sql pas encore appliqués. Renvoie leur liste."""
    appliquees: list[str] = []
    with pool.connection() as cnx:
        cnx.execute(
            "CREATE TABLE IF NOT EXISTS schema_migrations ("
            " version text PRIMARY KEY, applique_le timestamptz NOT NULL DEFAULT now())"
        )
        # Verrou consultatif : deux processus qui démarrent ensemble ne migrent pas deux fois.
        cnx.execute("SELECT pg_advisory_xact_lock(724413)")
        deja = {ligne[0] for ligne in cnx.execute("SELECT version FROM schema_migrations")}
        for fichier in sorted(dossier.glob("[0-9][0-9][0-9][0-9]_*.sql")):
            if fichier.stem in deja:
                continue
            journal.info("Migration %s", fichier.name)
            cnx.execute(fichier.read_text(encoding="utf-8"))
            cnx.execute("INSERT INTO schema_migrations (version) VALUES (%s)", (fichier.stem,))
            appliquees.append(fichier.stem)
        cnx.commit()
    return appliquees
