# ADR-0016 : Combinaisons, seuils et évaluation

- Date : 2026-11-04
- Statut : Acceptée
- Remplace : —

## Contexte

Le méta-classifieur est une option parmi trois modes de décision. Il faut évaluer 13 combinaisons,
choisir des seuils de confiance sans toucher au test, mesurer chaque combinaison sur trois segments,
et compléter le contrôle lot / unité de l'ADR-0010.

## Décision

**Modes** (`MODE`, `MODELES`) :
- `seul` : les probabilités d'un modèle.
- `moyenne` : moyenne pondérée ; poids positifs de somme 1, par pas de 0,1, chaque modèle gardant un
  poids non nul, choisis pour la meilleure exactitude top 1 hors pli (puis log loss).
- `meta` : régression logistique sur les prédictions hors pli. Pour chaque modèle : son vecteur de
  probabilités et l'écart entre ses deux premières probabilités ; plus un indicateur « tous les
  modèles ont le même top 1 ». C ∈ {0,1 ; 1 ; 10}, choisi en validation croisée sur les mêmes plis ;
  `META_MODELE=gb` remplace la régression par un gradient boosting (HistGradientBoosting, sans grille).
- Les combinateurs ne réentraînent aucun modèle de base : essayer une combinaison coûte quelques
  secondes. Ils sont sauvegardés (`…/combinaisons/<nom>.joblib`) pour `predire`.

**Combinaisons standard (13)** : les 5 seuls ; la branche TF-IDF, la branche embedding
(`svm_emb` + `rl_emb`), le meilleur de chaque branche (meilleure exactitude top 1 hors pli) et les
4 linéaires, chacune en `moyenne` puis en `meta`. Seules les combinaisons dont tous les modèles
sont entraînés sont évaluées. `evaluer --mode … --modeles …` évalue une combinaison choisie à la main.

**Seuils** : choisis sur la courbe couverture / précision des **prédictions hors pli combinées**
(pour `meta`, ses propres prédictions hors pli), jamais sur le test.
- Seuil haut : le plus bas seuil au-dessus duquel la précision top 1 reste ≥ `CIBLE_PRECISION_HAUT`
  (0,95) ; un Titre est mis en avant.
- Seuil moyen : le plus bas seuil au-dessus duquel la précision top 3 reste ≥ `CIBLE_TOP3_MOYEN`
  (0,95), plafonné au seuil haut ; le top 3 est proposé.
- En dessous, ou si les modèles de base n'ont pas le même top 1 (`DESACCORD_BLOQUE=true`) : aucune
  proposition.
- `SEUIL_HAUT` et `SEUIL_MOYEN` renseignés dans le `.env` remplacent les seuils calculés (source
  « manuel ») ; vides, ils sont calculés (les variables vides sont ignorées).

**Mesures** (hors pli et sur le test, chacune pour l'ensemble, les mails issus d'un template et les
mails libres) : exactitude top 1 et top 3, F1 macro, log loss, score de Brier, erreur de calibration
(ECE) ; sur le test aussi : courbe couverture / précision (ensemble et libres), diagramme de
fiabilité, paires de Titres les plus confondues et matrice restreinte, score par Titre, répartition
et justesse des niveaux haut / moyen / aucun. Stockées dans la table `evaluations` (NaN → null) et
en JSON dans `…/evaluations/`.

**Contrôle dans le temps** (`evaluer --temporel`, si les dates sont présentes) : entraînement sur les
demandes antérieures au dernier mois, test sur le dernier mois, avec les paramètres retenus en
validation croisée ; combinaisons `seul` et `moyenne` seulement (le méta demanderait de refaire
toutes les prédictions hors pli sur la période).

**Contrôle lot / unité, volet rl_emb** (complète l'ADR-0010) : `controle-lots` tire son échantillon
en priorité dans le jeu de test ; `evaluer` vectorise les fiches refaites à l'unité et compare
l'exactitude top 1 du `rl_emb` final avec les fiches en lot et à l'unité, sur les demandes de test
de l'échantillon.

**Usage du test** : rien n'est réglé sur le test ; il peut être relu à chaque `evaluer`, mais le
comparatif qui fait foi est celui du rapport.

## Conséquences

- La moyenne est réglée et mesurée hors pli sur les mêmes prédictions (légère optimisation) ; le
  méta est mesuré hors pli par une vraie validation croisée imbriquée.
- Avec `DESACCORD_BLOQUE=true`, une combinaison de 4 modèles propose moins souvent : c'est visible
  dans la répartition des niveaux.
