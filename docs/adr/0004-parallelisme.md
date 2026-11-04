# ADR-0004 : Parallélisme : processus pour le calcul, asyncio pour les appels réseau

- Date : 2026-11-03
- Statut : Acceptée
- Remplace : —

## Contexte

On veut accélérer chaque étape par du multiprocessus quand c'est possible. Or les étapes n'ont
pas le même profil : les appels à l'IAG et à l'embedding attendent le réseau, tandis que la
validation croisée, le TF-IDF et le prétraitement occupent le processeur.

## Décision

- **Calcul** (prétraitement par lots, grilles × plis × modèles, combinaisons) : processus via
  joblib (backend loky), helper `demandes.parallele.map_par_lots`, nombre de processus réglé par
  `N_JOBS` (-1 = tous les cœurs). En dessous de 2 000 éléments, on reste dans un seul processus :
  lancer des processus coûterait plus que le gain.
- Un seul thread BLAS par processus (`OMP_NUM_THREADS=1`…), fixé au démarrage, pour ne pas
  surcharger les cœurs.
- **Pas de parallélisme imbriqué** : si une boucle externe est parallèle, les estimateurs internes
  (`CalibratedClassifierCV`, recherche de grille) tournent avec `n_jobs=1`.
- **Appels réseau** (fiches, embeddings) : `asyncio` + `AsyncOpenAI`, avec un sémaphore
  `LLM_CONCURRENCY` (4 par défaut) ; embeddings envoyés par lots de `EMB_TAILLE_LOT`. Des processus
  n'apporteraient rien à une attente réseau.
- **Tâches de l'API** : une seule tâche longue à la fois, dans un fil dédié ; elle utilise
  elle-même les processus de calcul ou la concurrence réseau.
- Toute fonction envoyée à un processus est définie au niveau d'un module (sérialisable), et le
  résultat garde l'ordre des entrées : le parallélisme ne change pas les résultats.

## Conséquences

- Reproductibilité : les graines sont passées explicitement à chaque tâche parallèle, jamais
  tirées dans un processus de travail.
- Sur une petite machine, `N_JOBS` doit être réduit pour garder de la mémoire (chaque processus
  reçoit une copie des matrices).
