# Demandes ITZME : classification supervisée du Titre

Banc d'essai qui apprend à prédire la catégorie (le **Titre**, ~160 valeurs) d'une demande ITZME à
partir du mail qui l'a créée. Usage visé : **assistance**. Le modèle propose un Titre ou un top 3,
et l'opérateur valide toujours.

Ce projet est indépendant de RITA (le pipeline de clustering).

## État d'avancement

| Étape | Commande | État |
|---|---|---|
| 1. Chargement, contrôles, cartographie, templates | `charger` | ✅ |
| 3a. Fiches IAG par lots, embeddings, cache, contrôle lot / unité | `charger`, `fiches`, `controle-lots` | ✅ |
| 2. Branche TF-IDF, `svm_tfidf`, `rl_tfidf` : premier score sans LLM | `entrainer`, `evaluer` | à venir |
| 3b. Modèles `svm_emb`, `rl_emb`, `knn_emb` | `entrainer`, `evaluer` | à venir |
| 4. Prédictions hors pli, modes `moyenne` et `meta`, 13 combinaisons | `evaluer` | à venir |
| 5. Rapport, seuils, prédiction d'un nouveau mail | `rapport`, `predire` | à venir |

## Installation

Prérequis : Docker (avec compose) et [uv](https://docs.astral.sh/uv/).

```bash
cp .env.exemple .env              # puis adapter le mapping des colonnes et l'IAG
uv sync                           # dépendances (Python 3.12 installé par uv si besoin)
docker compose up -d postgres     # PostgreSQL + pgvector sur le port 5433
uv run demandes migrer            # schéma de la base
git config core.hooksPath outils/hooks   # contrôle des ADR avant chaque commit
```

Pour tout lancer dans Docker, API comprise : `docker compose up -d --build`. L'API est alors
disponible sur http://localhost:8000/docs.

## Configuration

Tout se règle dans `.env`, lu par la classe `Settings` ([config.py](src/demandes/config.py)).
Les valeurs commentées sont dans [.env.exemple](.env.exemple). Les principales :

- **Colonnes de l'export** : `COLONNE_NUMERO`, `COLONNE_TITRE`, `COLONNE_MAIL`, `COLONNE_DATE`
  (laisser vide s'il n'y a pas de date) ;
- **IAG et embedding** (API compatibles OpenAI) : `IAG_BASE_URL`, `IAG_MODELE`, `JSON_MODE`,
  `EMB_BASE_URL`, `EMB_MODELE` (bge-m3 par défaut) ; `MOCK_LLM=true` pour tout simuler ;
- **Fiches par lots** ([ADR-0010](docs/adr/0010-fiches-par-lots-a-l-ingestion.md)) :
  `FICHES_PAR_APPEL` (10 ; 1 = un mail par appel), `LOT_MAX_CARACTERES`, `MAIL_MAX_CARACTERES`,
  `IAG_MAX_TOKENS_PAR_FICHE`, `EMBED_PAR_APPEL` (100), `FICHES_A_L_INGESTION` ;
- **Apprentissage** : `SEED`, `MIN_PAR_TITRE`, `N_PLIS`, `TAILLE_TEST`, `N_JOBS`, `LLM_CONCURRENCY` ;
- **Décision** : `MODE` (`seul`, `moyenne`, `meta`), `MODELES`, `SEUIL_HAUT`, `SEUIL_MOYEN` ;
- **Templates** : `TEMPLATE_MIN_MAILS`, `TEMPLATE_FREQ_MAX`, `TEMPLATE_MIN_MARQUEURS`,
  `TEMPLATE_OBJET`, `TEMPLATE_MOTIFS`.

## Enchaînement des commandes

```bash
uv run demandes synthetique                      # export d'essai : donnees/synthetique.xlsx
uv run demandes charger donnees/export.xlsx      # ingestion : contrôles, puis fiches et embeddings
uv run demandes charger donnees/export.xlsx --sans-fiches   # contrôles seuls, aucun appel à l'IAG
uv run demandes fiches [--reprendre-echecs]      # fiches et embeddings manquants (après --sans-fiches)
uv run demandes controle-lots --taille 200       # qualité : fiches en lot comparées à l'unité
uv run demandes taches                           # historique des tâches (CLI et API)
```

Pour tout essayer sans serveur IAG : `MOCK_LLM=true uv run demandes charger donnees/synthetique.xlsx`.

### Fiches par lots

Chaque appel à l'IAG reçoit `FICHES_PAR_APPEL` mails, délimités par `<mail id="NUMERO">`, et
renvoie `{"fiches": [...]}`. Le schéma imposé n'autorise que les numéros du lot. Une fiche est
rattachée par son id, jamais par sa position. Les fiches manquantes, invalides ou en double sont
redemandées une par une (2 reprises), puis journalisées en échec dans
`artefacts/fiches/<empreinte>/echecs.csv`. Le cache est par demande : relancer ne refait que ce
qui manque. Après 20 erreurs réseau d'affilée, la tâche s'arrête ; il suffit de la relancer.

`controle-lots` refait à l'unité les fiches d'un échantillon produit en lot et mesure l'accord
sur `action`, `application`, `template`, `objet_action` (`controle_lots.json`,
`controle_lots_desaccords.csv`). Si le lot dégrade les résultats, réduire `FICHES_PAR_APPEL`.

`charger` produit dans `artefacts/chargement/` :

| Fichier | Contenu |
|---|---|
| `lignes_ecartees.csv` | lignes écartées et leur motif |
| `cartographie_titres.csv` | Titre, nombre de demandes, première et dernière date |
| `petites_categories.csv` | Titres sous `MIN_PAR_TITRE`, exclus de l'apprentissage |
| `ecarts_referentiel.csv` | Titres absents de la référence figée, ou disparus |
| `marqueurs_template.csv` | lignes et objets fixes retenus comme marqueurs de template |
| `templates_par_mail.csv` | booléen `template`, raison et marqueurs, par mail |
| `bilan_chargement.json` | bilan complet |

Au premier chargement, la cartographie devient la **référence figée** des Titres. Pour la
remplacer : `uv run demandes charger <fichier> --nouvelle-reference`.

## API

Pas d'authentification : environnement de test uniquement ([ADR-0005](docs/adr/0005-api-fastapi-sans-authentification.md)).

```bash
uv run demandes api        # ou : docker compose up -d api
# Déposer un export, puis lancer le chargement en tâche de fond
curl -F fichier=@export.xlsx http://localhost:8000/fichiers
curl -X POST http://localhost:8000/taches/charger -H 'Content-Type: application/json' \
     -d '{"fichier": "donnees/export.xlsx"}'
# Suivre l'avancement en direct
curl -N http://localhost:8000/taches/<id>/flux
```

| Route | Rôle |
|---|---|
| `POST /fichiers`, `GET /fichiers` | dépôt et liste des exports |
| `POST /taches/charger` | ingestion en tâche de fond (202) ; `"avec_fiches": false` pour sauter les fiches |
| `POST /taches/fiches` | fiches et embeddings manquants (`"reprendre_echecs": true` pour retenter les échecs) |
| `POST /taches/controle-lots` | contrôle qualité lot / unité (`"taille": 200`) |
| `GET /taches`, `GET /taches/{id}` | état des tâches (progression, étape, résultat) |
| `GET /taches/{id}/journal?apres=N` | journal d'avancement détaillé (lignes nouvelles) |
| `GET /taches/{id}/flux` | journal en direct (Server-Sent Events) |
| `GET /corpus`, `GET /referentiel` | bilan du dernier chargement, référence des Titres |

## Architecture

Hexagonale ([ADR-0002](docs/adr/0002-architecture-hexagonale.md)) :

```
src/demandes/
├── domaine/          entités et règles métier, Python pur
├── apprentissage/    prétraitement, modèles, validation (numpy, sklearn ; pas d'I/O)
├── ports/            interfaces vers l'extérieur
├── application/      cas d'usage (1 commande = 1 endpoint = 1 classe)
├── adaptateurs/
│   ├── entrants/     cli.py (Typer), api/ (FastAPI)
│   └── sortants/     excel, postgres/, fichiers, mémoire, suivi des tâches
└── composition.py    câblage selon Settings
```

Le parallélisme est décrit dans l'[ADR-0004](docs/adr/0004-parallelisme.md) : des processus
pour le calcul (`N_JOBS`), asyncio pour les appels à l'IAG (`LLM_CONCURRENCY`).

## Décisions (ADR)

Chaque décision est tracée dans [docs/adr/](docs/adr/README.md). Un ADR est **immuable** une fois
scellé ([ADR-0001](docs/adr/0001-adr-immuables.md)) :

```bash
uv run demandes adr nouveau "Titre de la décision" [--remplace 0003]
# ... rédiger le fichier, puis :
uv run demandes adr sceller        # enregistre l'empreinte et régénère l'index
uv run demandes adr verifier       # aussi lancé par le hook pre-commit et par pytest
uv run demandes adr corriger 0004 --motif "coquille"   # correction de forme uniquement
```

## Tests

```bash
uv run pytest                      # tests unitaires, sans Docker
uv run pytest -m postgres          # tests d'intégration (docker compose up -d postgres)
```
