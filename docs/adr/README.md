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
| 0007 | [Empreintes de configuration à deux niveaux](0007-empreintes-configuration.md) | 2026-11-03 | Remplacée par ADR-0014 |
| 0008 | [Tâches de fond et journal d'avancement détaillé](0008-taches-et-suivi-avancement.md) | 2026-11-03 | Acceptée |
| 0009 | [Règles de chargement, de contrôle et de repérage des templates](0009-regles-de-chargement.md) | 2026-11-03 | Remplacée par ADR-0011 |
| 0010 | [Fiches produites par lots à l'ingestion](0010-fiches-par-lots-a-l-ingestion.md) | 2026-11-04 | Acceptée |
| 0011 | [Règles de chargement, de contrôle et de repérage des templates (v2)](0011-regles-de-chargement-v2.md) | 2026-11-04 | Acceptée |
| 0012 | [Exploitation du service dans Docker](0012-exploitation-docker.md) | 2026-11-04 | Acceptée |
| 0013 | [Stratégie de tests](0013-strategie-de-tests.md) | 2026-11-04 | Acceptée |
| 0014 | [Empreintes de configuration (v2) : fiche, vecteur, jeu, modèle](0014-empreintes-de-configuration-v2.md) | 2026-11-04 | Acceptée |
| 0015 | [Protocole d'apprentissage et modèles de base](0015-protocole-et-modeles-de-base.md) | 2026-11-04 | Acceptée |
| 0016 | [Combinaisons, seuils et évaluation](0016-combinaisons-seuils-et-evaluation.md) | 2026-11-04 | Acceptée |
| 0017 | [Rapport et règle de recommandation](0017-rapport-et-recommandation.md) | 2026-11-04 | Acceptée |
| 0018 | [Prédiction d'un nouveau mail et boucle de retour](0018-prediction-et-boucle-de-retour.md) | 2026-11-04 | Acceptée |
| 0019 | [Données synthétiques avec des confusions réalistes](0019-donnees-synthetiques-ambigues.md) | 2026-11-04 | Acceptée |
