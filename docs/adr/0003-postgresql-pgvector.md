# ADR-0003 : PostgreSQL + pgvector pour le corpus, le cache et le suivi ; fichiers pour les gros artefacts

- Date : 2026-11-03
- Statut : Acceptée
- Remplace : —

## Contexte

La spécification initiale prévoit un cache sur disque pour les fiches et les vecteurs. Le projet
ajoute PostgreSQL avec pgvector, lancé par docker compose. Il faut répartir ce qui va en base et ce
qui reste en fichiers.

## Décision

- **En base** (image `pgvector/pgvector:pg17`, port hôte 5433) : le corpus courant (`demandes`),
  l'historique des chargements (`imports`, `lignes_ecartees`), la référence figée des Titres
  (`referentiel_titres`), les tâches et leur journal (`taches`, `journal_taches`) ; puis, dans des
  migrations suivantes, les fiches (`jsonb`), les vecteurs (`vector`), les configurations, les
  exécutions et le journal des prédictions.
- La base **remplace le cache sur disque** des fiches et vecteurs. Clé du cache : numéro de la
  demande + empreinte de configuration (ADR-0007), avec contrôle de l'empreinte du mail
  (`demandes.empreinte_mail`) : une fiche n'est réutilisée que si le mail n'a pas changé.
- **En fichiers** (dossier `artefacts/`, volume monté) : modèles `joblib`, prédictions hors pli
  (`.npy`), CSV de contrôle, rapports et graphiques. Ce sont de gros objets binaires lus d'un bloc.
- Accès par psycopg 3 sans ORM ; schéma géré par des migrations SQL numérotées
  (`adaptateurs/sortants/postgres/migrations/NNNN_*.sql`), appliquées par `demandes migrer` ou au
  démarrage de l'API.
- pgvector sert au stockage des vecteurs et au plus proche voisin **au moment de la prédiction**.
  Pendant la validation croisée, le KNN tourne en mémoire : interroger la base imposerait de
  filtrer par pli à chaque requête, avec un risque de fuite.
- Le corpus courant est **remplacé** à chaque chargement ; les fiches et vecteurs restent en cache.

## Conséquences

- Docker est nécessaire pour la chaîne complète ; les tests unitaires s'en passent (ADR-0002).
- Les caractères NUL sont refusés par PostgreSQL : ils sont retirés au chargement (ADR-0009).
- Un changement de dimension d'embedding passera par une migration et un ADR.
