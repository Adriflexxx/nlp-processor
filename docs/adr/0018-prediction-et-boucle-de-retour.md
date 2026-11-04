# ADR-0018 : Prédiction d'un nouveau mail et boucle de retour

- Date : 2026-11-04
- Statut : Acceptée
- Remplace : —

## Contexte

`predire(mail)` doit renvoyer le top 3, le niveau de confiance et l'avis de chaque modèle de base,
à partir de la configuration et des modèles sauvegardés. Un journal des prédictions, complété par
le Titre retenu par l'opérateur, doit servir de boucle de retour et de base au réentraînement sur
une fenêtre glissante de 12 mois.

## Décision

- **Configuration** : `MODE` et `MODELES` du `.env` (le rapport indique les valeurs recommandées).
  La combinaison doit avoir été évaluée sur le **dernier jeu évalué** ; sinon, erreur explicite
  (API : 409) avec la commande `evaluer` à lancer.
- **Modèles** : modèles finaux (entraînés sur les 80 % d'entraînement, ADR-0015) et combinateur
  sauvegardés, gardés en mémoire entre deux prédictions.
- **Seuils** : ceux de l'évaluation de la combinaison, ou `SEUIL_HAUT` / `SEUIL_MOYEN` s'ils sont
  renseignés.
- **Traitement du mail** : réparation de l'encodage et nettoyage comme à l'ingestion ; pour la
  branche embedding, fiche produite **à l'unité** (lot de 1, même consigne, ADR-0010), puis
  embedding normalisé. Si la fiche ou l'embedding échoue, les modèles embedding donnent la
  distribution a priori (comme à l'entraînement) et une remarque l'indique.
- **Réponse** : top 3 (Titre, probabilité), niveau (haut, moyen, aucun), indicateur de désaccord,
  avis de chaque modèle (Titre top 1, probabilité), configuration utilisée, fiche, remarques.
- **Journal** : chaque prédiction est enregistrée (table `predictions` : mail, configuration,
  top 3, niveau, avis) ; `POST /predictions/{id}/retour` ou `demandes retour ID "Titre"` complète
  le Titre retenu et l'opérateur. Un Titre hors du référentiel est accepté (nouveau Titre possible).
- **Réentraînement** : `demandes exporter-retours --mois 12` écrit les prédictions validées de la
  fenêtre glissante au format de l'export (mapping des colonnes, numéro `PRED<id>`), rechargeable
  par `charger` ; il donne aussi l'exactitude top 1 constatée en production. Le réentraînement
  n'est pas automatique : il suit l'enchaînement charger → entrainer → evaluer → rapport.

## Conséquences

- Une prédiction avec la branche embedding coûte un appel IAG et un appel d'embedding (quelques
  secondes) ; sans elle, quelques millisecondes.
- Les mails du journal contiennent des données personnelles : la table `predictions` suit les mêmes
  précautions que le corpus (ADR-0005).
