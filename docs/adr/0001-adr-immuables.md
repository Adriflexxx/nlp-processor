# ADR-0001 : Tracer chaque décision dans un ADR immuable

- Date : 2026-11-03
- Statut : Acceptée
- Remplace : —

## Contexte

Le projet est un banc d'essai où la « configuration figée » (prompt de fiche, modèle LLM, modèle
d'embedding, hyperparamètres) compte : comparer deux configurations n'a de sens que si l'on sait
exactement ce qui a changé et pourquoi. Il faut un historique fiable des décisions, qu'on ne puisse
pas réécrire après coup.

## Décision

- Chaque décision notable (architecture, stockage, schéma, protocole, changement de configuration)
  fait l'objet d'un ADR dans `docs/adr/NNNN-titre.md`, rédigé en français à partir de `modele.md`.
- Un ADR est **immuable** une fois scellé : son empreinte SHA-256 est enregistrée dans
  `docs/adr/empreintes.sha256` (`demandes adr sceller`).
- Revenir sur une décision se fait par un **nouvel ADR** qui porte `- Remplace : ADR-NNNN`.
  L'ancien n'est pas modifié ; son statut « Remplacée par » est **calculé** dans l'index
  `docs/adr/README.md`, généré par `demandes adr index`.
- Seules les **corrections de forme** (coquille, lien cassé) sont tolérées sur un ADR scellé :
  `demandes adr corriger NNNN --motif "…"` met à jour l'empreinte et trace la correction dans
  `docs/adr/errata.md`. Le fond d'une décision ne se corrige jamais ainsi.
- Contrôles : un test pytest (`tests/unitaires/test_adr_immuables.py`) et un hook git pre-commit
  (`outils/hooks/pre-commit`, activé par `git config core.hooksPath outils/hooks`) échouent si un
  ADR scellé est modifié ou supprimé, ou si un ADR n'est pas scellé.

## Conséquences

- L'historique des décisions est lisible dans l'ordre et vérifiable.
- Un changement de configuration coûte un ADR : c'est voulu, cela force à documenter ce qui change.
- Le hook demande Python 3 sur le poste (le module `demandes.adr` n'utilise que la bibliothèque standard).
