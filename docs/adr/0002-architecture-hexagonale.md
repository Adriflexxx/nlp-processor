# ADR-0002 : Architecture hexagonale, calcul autorisé dans le cœur

- Date : 2026-11-03
- Statut : Acceptée
- Remplace : —

## Contexte

On veut pouvoir intervenir facilement dans le code : changer de source de données, de base, de
fournisseur d'IAG, ou tester un cas d'usage sans infrastructure. Une architecture hexagonale (ports
et adaptateurs) répond à ce besoin. Mais le cœur du projet est un travail d'apprentissage
automatique : cacher scikit-learn et numpy derrière des interfaces rendrait ce cœur pénible à
modifier, sans rien y gagner.

## Décision

Paquet `src/demandes/`, organisé en couches :

| Couche | Rôle | Dépendances permises |
|---|---|---|
| `domaine/` | entités, règles métier (contrôles, référentiel, décision, combinaisons) | Python pur |
| `apprentissage/` | prétraitement, représentations, modèles, validation, métriques | numpy, scikit-learn, pas d'I/O |
| `ports/` | interfaces (`typing.Protocol`, classes abstraites) vers l'extérieur | domaine |
| `application/` | cas d'usage : une commande = un endpoint = une classe | domaine, apprentissage, ports |
| `adaptateurs/entrants/` | ligne de commande (Typer), API (FastAPI) | application, composition |
| `adaptateurs/sortants/` | Excel, PostgreSQL, IAG, embedding, fichiers, mémoire, simulateurs | ports, bibliothèques externes |
| `composition.py` | câblage des adaptateurs selon `Settings` | tout |

- Seules les **entrées/sorties** passent par des ports : lecture de l'export, persistance,
  IAG, embedding, artefacts, suivi d'avancement.
- Le cœur (`domaine`, `apprentissage`, `application`) n'importe jamais un adaptateur concret.
- Chaque port a une implémentation **en mémoire** pour les tests unitaires, qui tournent sans Docker.

## Conséquences

- Changer de base ou de fournisseur d'IAG ne touche qu'un adaptateur et la composition.
- Les tests obligatoires (fuite, graine, ordre des classes, modes, cache) tournent en mémoire.
- La règle « pas d'I/O dans `apprentissage` » doit être tenue à la relecture : les artefacts
  (modèles, prédictions hors pli) sont écrits par l'application via le port `StockageArtefacts`.
