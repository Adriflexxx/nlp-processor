# ADR-0005 : API FastAPI sans authentification, en environnement de test

- Date : 2026-11-03
- Statut : Acceptée
- Remplace : —

## Contexte

En plus de la ligne de commande, on veut une API pour lancer les étapes, suivre leur avancement et
prédire. Le projet est un banc d'essai : il n'est pas exposé aux opérateurs ni au réseau de
production.

## Décision

- API FastAPI, **sans authentification**, lancée par docker compose (service `api`, port 8000) ou
  par `uv run demandes api`.
- Les cas d'usage sont les mêmes pour la CLI et l'API ; l'API ne contient pas de logique métier.
- Les étapes longues (`charger`, puis `fiches`, `entrainer`, `evaluer`, `rapport`) sont lancées
  comme **tâches de fond** : `POST /taches/<etape>` répond 202 avec l'identifiant de la tâche.
  Le suivi est détaillé dans l'ADR-0008.
- `predire` et le retour opérateur seront synchrones.

## Conséquences

- **Ne pas exposer cette API hors d'un environnement de test.** Une mise en service auprès des
  opérateurs demandera un nouvel ADR (authentification, journalisation des accès, données
  personnelles).
- Les mails contiennent des données personnelles : les exports (`donnees/`) et les artefacts
  (`artefacts/`) sont exclus de git.
