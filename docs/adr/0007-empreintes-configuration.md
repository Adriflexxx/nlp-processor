# ADR-0007 : Empreintes de configuration à deux niveaux

- Date : 2026-11-03
- Statut : Acceptée
- Remplace : —

## Contexte

La configuration est figée : prompt, modèle LLM, modèle d'embedding et hyperparamètres sont
versionnés ensemble, et changer l'un d'eux crée une nouvelle configuration. Le cache des fiches et
des vecteurs doit être indexé par cette configuration, pour que chaque appel ne soit fait qu'une
fois. Mais changer de modèle d'embedding ne doit pas obliger à refaire les fiches.

## Décision

- `empreinte_fiche` = SHA-256 de : texte du prompt, `SCHEMA_FICHE`, modèle LLM, température,
  `JSON_MODE`.
- `empreinte_vecteur` = SHA-256 de : `empreinte_fiche`, modèle d'embedding, dimension, version de
  la fonction de concaténation.
- `empreinte_run` = SHA-256 de : `empreinte_vecteur`, paramètres TF-IDF, grilles, `SEED`,
  `N_PLIS`, `TAILLE_TEST`, `MIN_PAR_TITRE` ; elle indexe les prédictions hors pli, les modèles
  et les rapports.
- En mode `MOCK_LLM`, le nom des modèles est préfixé par `mock:` : les vecteurs simulés ne se
  mélangent jamais aux vrais.
- Les empreintes sont tronquées à 16 caractères dans les noms de dossiers, complètes en base.

## Conséquences

- Changer le modèle d'embedding réutilise les fiches et recalcule seulement les vecteurs.
- Changer le prompt recalcule les fiches et les vecteurs.
- Changer une grille ou la graine relance l'entraînement, sans aucun appel LLM.
