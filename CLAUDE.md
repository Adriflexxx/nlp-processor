## Projet

Banc d'essai de classification supervisée : prédire le Titre d'une demande ITZME à partir du mail. Sans lien avec RITA : ne pas réutiliser son code. Le code, les identifiants, les commentaires, les messages et les rapports sont en français.

- Architecture hexagonale (docs/adr/0002) : `domaine/` en Python pur ; `apprentissage/` avec numpy/sklearn mais sans I/O ; `ports/` ; `application/` (1 commande = 1 endpoint = 1 classe) ; `adaptateurs/` ; câblage dans `composition.py`. Le cœur n'importe jamais un adaptateur concret.
- Chaque décision notable donne lieu à un **nouvel ADR** (`uv run demandes adr nouveau "…"`, à rédiger, puis `uv run demandes adr sceller`). Ne jamais modifier un ADR scellé : le remplacer par un nouveau ADR (`--remplace NNNN`). Seules les corrections de forme passent par `demandes adr corriger NNNN --motif "…"`.
- Parallélisme (docs/adr/0004) : processus via `demandes.parallele.map_par_lots` pour le calcul ; asyncio + sémaphore pour l'IAG et l'embedding. Pas de parallélisme imbriqué.
- Suivi : un cas d'usage ne fait jamais de `print`, il passe par le port `Suivi` (docs/adr/0008).
- Schéma de la base : nouvelle migration `adaptateurs/sortants/postgres/migrations/NNNN_*.sql`, jamais de modification d'une migration déjà appliquée.
- Tests : `uv run pytest` (en mémoire, sans Docker) ; `uv run pytest -m postgres` (avec `docker compose up -d postgres`, port 5433).

## graphify

This project has a knowledge graph at graphify-out/ with god nodes, community structure, and cross-file relationships.

Rules:
- For codebase questions, first run `graphify query "<question>"` when graphify-out/graph.json exists. Use `graphify path "<A>" "<B>"` for relationships and `graphify explain "<concept>"` for focused concepts. These return a scoped subgraph, usually much smaller than GRAPH_REPORT.md or raw grep output.
- If graphify-out/wiki/index.md exists, use it for broad navigation instead of raw source browsing.
- Read graphify-out/GRAPH_REPORT.md only for broad architecture review or when query/path/explain do not surface enough context.
- After modifying code, run `graphify update .` to keep the graph current (AST-only, no API cost).
