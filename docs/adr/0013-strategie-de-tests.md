# ADR-0013 : Stratégie de tests

- Date : 2026-11-04
- Statut : Acceptée
- Remplace : —

## Contexte

L'ADR-0002 prévoit des tests unitaires en mémoire, sans Docker. En ajoutant les fiches, le test de
l'API a utilisé sans le dire la base de développement, parce que son conteneur de test ne
remplaçait pas les nouveaux dépôts. Par ailleurs, l'adaptateur `openai` réel n'était couvert par
aucun test : seul le simulateur l'était.

## Décision

- **Tests unitaires** (`uv run pytest`, par défaut) : dépôts en mémoire, IAG et embedding simulés.
  Ils ne doivent **jamais** toucher PostgreSQL : le conteneur de test de l'API remplace le pool par
  une propriété qui lève une erreur, et chaque nouveau dépôt doit y recevoir son équivalent en mémoire.
- **Tests d'intégration** (`uv run pytest -m postgres`) : base dédiée `demandes_test`, supprimée et
  recréée au début de la session de test, jamais la base de développement. Ils vérifient les
  migrations (dont leur idempotence), les dépôts, pgvector et le cache.
- **Adaptateur openai réel** : testé contre un faux serveur compatible OpenAI, branché par un
  transport `httpx.MockTransport` injectable dans les adaptateurs (paramètre `transport`). On
  vérifie le format exact des requêtes (`response_format` json_schema strict avec les id du lot,
  `max_tokens`, repli `json_object`, lots d'embeddings, contrôle de la dimension).
- `httpx` devient une **dépendance directe** du projet (il était seulement tiré par `openai` et par
  le groupe de dev) : le code l'importe pour ce transport.
- **Simulateurs** (`MOCK_LLM=true`) : déterministes ; la fiche est tirée du mail par des règles
  simples et le vecteur par hachage des mots, pour que deux mails proches aient des vecteurs
  proches et que la branche embedding soit évaluable en simulation.
- Les tests obligatoires de la spécification (pas de fuite, reproductibilité, ordre des classes,
  modes et combinaisons, cache sans appel en double) s'ajoutent avec les étapes concernées.

## Conséquences

- Un test unitaire qui tenterait d'ouvrir une connexion échoue immédiatement, au lieu d'écrire
  dans la base de développement.
- Les tests d'intégration demandent `docker compose up -d postgres`.
