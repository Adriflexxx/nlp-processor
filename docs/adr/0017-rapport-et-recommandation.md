# ADR-0017 : Rapport et règle de recommandation

- Date : 2026-11-04
- Statut : Acceptée
- Remplace : —

## Contexte

Le rapport doit classer les 13 combinaisons, donner le gain par rapport à la combinaison la plus
simple, dire si chacune fait appel au LLM en production, et recommander une configuration et ses
seuils. Une combinaison plus lourde ne doit être retenue que si elle apporte un gain net, en
particulier sur les mails libres.

## Décision

- **Format** : Markdown, `artefacts/rapports/<jeu>/rapport.md`, avec trois graphiques PNG
  (matplotlib) dans le même dossier : courbes couverture / précision (les 5 meilleures, la
  référence et la retenue), fiabilité (retenue et référence), matrice des Titres les plus
  confondus (retenue). `recommandation.json` reprend la recommandation. `GET /rapport` renvoie le
  dernier rapport.
- **Classement** : par exactitude top 1 sur le test, puis top 3.
- **Référence** (« la plus simple ») : `REFERENCE` (`svm_tfidf`) seul ; les gains (top 1 sur
  l'ensemble et sur les mails libres) sont donnés en points par rapport à elle.
- **Lourdeur** d'une combinaison : nombre de modèles, + 2 si elle fait appel au LLM en production
  (une fiche IAG et un embedding par mail), + 1 en mode méta.
- **Règle de recommandation** : la plus légère des combinaisons qu'aucune plus lourde ne bat de plus
  de `GAIN_MIN` (1 point) d'exactitude top 1, ni sur l'ensemble, ni sur les mails libres. À lourdeur
  égale, la meilleure en top 1.
- La recommandation donne `MODE`, `MODELES` et les seuils, ainsi que l'effet attendu sur le test
  (part et précision des niveaux haut / moyen / aucun). Le contrôle dans le temps et le volet
  `rl_emb` du contrôle lot / unité y figurent s'ils ont été calculés.

## Conséquences

- La règle favorise la simplicité : sur des données faciles, une combinaison TF-IDF sans LLM sera
  retenue tant que l'embedding n'apporte pas plus d'un point.
- `GAIN_MIN` et `REFERENCE` se règlent dans le `.env`.
