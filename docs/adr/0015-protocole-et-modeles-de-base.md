# ADR-0015 : Protocole d'apprentissage et modèles de base

- Date : 2026-11-04
- Statut : Acceptée
- Remplace : —

## Contexte

La spécification fixe cinq modèles de base, leurs grilles, un découpage 80/20 stratifié, une
validation croisée en 5 plis et l'interdiction de tout ajustement sur le test. Plusieurs points
restaient à trancher : critère de sélection, traitement des demandes sans vecteur, calibration avec
de petits Titres, sur quoi le modèle final est entraîné.

## Décision

**Jeu** : les Titres sous `MIN_PAR_TITRE` sont retirés (recalculé à chaque entraînement) ; les
Titres sont encodés dans un **ordre de classes commun** (tri alphabétique) ; découpage 80/20
stratifié par Titre (`SEED`) ; `N_PLIS` plis stratifiés mélangés (`SEED`) sur l'entraînement seul.

**Modèles** (chacun est un estimateur scikit-learn complet : représentation et ACP sont ajustées
dans `fit`, donc jamais sur le test ni sur le pli de validation) :

| Clé | Modèle | Représentation | Grille |
|---|---|---|---|
| `svm_tfidf` | LinearSVC + CalibratedClassifierCV (sigmoïde) | TF-IDF | C ∈ {0,01 ; 0,1 ; 1 ; 10} |
| `rl_tfidf` | LogisticRegression | TF-IDF | C ∈ {0,1 ; 1 ; 10 ; 100} |
| `svm_emb` | LinearSVC + CalibratedClassifierCV (sigmoïde) | embedding (+ ACP) | C × dimensions |
| `rl_emb` | LogisticRegression | embedding (+ ACP) | C × dimensions |
| `knn_emb` | KNN cosinus, vote pondéré par la similarité (1 − distance) | embedding (+ ACP) | K ∈ {5 ; 10 ; 20} × dimensions |

- TF-IDF : mots et bigrammes, `min_df=2`, `sublinear_tf=True` ; variante `TFIDF_CARACTERES=true`
  qui ajoute `char_wb` 3 à 5.
- `class_weight="balanced"` pour les modèles linéaires.
- Calibration du SVM : nombre de plis = min(3, effectif de la plus petite classe), au moins 2.
- Dimensions d'ACP testées : `ACP_DIMENSIONS` (256, 512, 1024) ; une valeur au moins égale à la
  dimension des vecteurs, ou à l'effectif du plus petit pli, signifie « sans réduction ».
- **Demandes sans vecteur** (fiche en échec) : gardées dans tous les jeux ; les modèles embedding
  leur attribuent la distribution a priori des Titres de l'entraînement (enveloppe `AvecRepli`).
  Toutes les combinaisons sont ainsi évaluées sur les mêmes demandes, et la branche TF-IDF les garde.
- Sans aucun vecteur pour la configuration courante, seule la branche TF-IDF est entraînée : premier
  score **sans aucun appel au LLM**.

**Sélection** : pour chaque modèle, le paramètre retenu est celui de la meilleure **exactitude top 1
hors pli**, puis de la plus faible log loss. Ses prédictions hors pli (mêmes plis) sont mises en
cache : elles servent aux combinaisons (ADR-0016).

**Modèle final** : réentraîné avec le paramètre retenu sur **tout le jeu d'entraînement** (80 %) ;
ses probabilités sur le test sont mises en cache ; c'est lui qui sert à `predire`.

**Sorties** : chaque modèle sort un vecteur de probabilités sur tous les Titres, dans l'ordre
commun (`aligner` ; une classe inconnue de l'ordre commun est une erreur).

**Parallélisme** (ADR-0004) : toutes les tâches modèle × paramètre × pli tournent en parallèle
(joblib, `N_JOBS`), puis les modèles finaux ; résultats identiques au calcul séquentiel (testé).

## Conséquences

- Le choix du paramètre et le réglage des combinaisons utilisent les mêmes prédictions hors pli :
  légère optimisation sur l'entraînement, sans effet sur le test, qui reste intact.
- Les modèles finaux ne voient pas les 20 % du test ; un réentraînement sur 100 % pour la
  production demanderait un nouvel ADR.
