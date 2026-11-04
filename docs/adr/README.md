# Registre des décisions d'architecture (ADR)

Fichier généré par `demandes adr index` : ne pas éditer à la main.

Un ADR est **immuable** une fois scellé. Pour revenir sur une décision, on écrit un nouvel ADR
avec `- Remplace : ADR-NNNN` ; le statut ci-dessous est calculé à partir de ces remplacements.
Les corrections de forme sont tracées dans [errata.md](errata.md).

| N° | Titre | Date | Statut |
|---|---|---|---|
| 0001 | [Tracer chaque décision dans un ADR immuable](0001-adr-immuables.md) | 2026-11-03 | Acceptée |
| 0002 | [Architecture hexagonale, calcul autorisé dans le cœur](0002-architecture-hexagonale.md) | 2026-11-03 | Acceptée |
| 0003 | [PostgreSQL + pgvector pour le corpus, le cache et le suivi ; fichiers pour les gros artefacts](0003-postgresql-pgvector.md) | 2026-11-03 | Acceptée |
| 0004 | [Parallélisme : processus pour le calcul, asyncio pour les appels réseau](0004-parallelisme.md) | 2026-11-03 | Acceptée |
| 0005 | [API FastAPI sans authentification, en environnement de test](0005-api-fastapi-sans-authentification.md) | 2026-11-03 | Acceptée |
| 0006 | [Schéma de la fiche v1 et décodage guidé](0006-schema-fiche-v1.md) | 2026-11-03 | Remplacée par ADR-0010 |
| 0007 | [Empreintes de configuration à deux niveaux](0007-empreintes-configuration.md) | 2026-11-03 | Acceptée |
| 0008 | [Tâches de fond et journal d'avancement détaillé](0008-taches-et-suivi-avancement.md) | 2026-11-03 | Acceptée |
| 0009 | [Règles de chargement, de contrôle et de repérage des templates](0009-regles-de-chargement.md) | 2026-11-03 | Acceptée |
| 0010 | [Fiches produites par lots à l'ingestion](0010-fiches-par-lots-a-l-ingestion.md) | 2026-11-04 | Acceptée |
