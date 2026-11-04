# ADR-0019 : Données synthétiques avec des confusions réalistes

- Date : 2026-11-04
- Statut : Acceptée
- Remplace : —

## Contexte

Avec le générateur initial, tous les modèles atteignaient 100 % d'exactitude : le verbe d'action et
le vocabulaire propres à chaque Titre apparaissaient dans tous les mails libres. Les seuils, les
combinaisons et le rapport ne pouvaient pas être éprouvés.

## Décision

Le générateur (`demandes synthetique`, `src/demandes/synthetique.py`) :
- associe à chaque Titre un **Titre voisin** (création / suppression de compte, habilitation /
  retrait, anomalie d'export / modification de référentiel…) ; un mail libre sur deux emprunte un
  mot au voisin, et 10 % des mails libres sont **trompeurs** (surtout du vocabulaire du voisin) ;
- emploie des **formulations génériques** sans verbe d'action (« pouvez-vous regarder »…) ;
- garde les mails issus d'un template faciles (libellés fixes), comme dans la réalité ;
- reste déterministe (graine) et conserve les anomalies volontaires du chargement.

## Conséquences

- Les scores synthétiques ne sont plus parfaits (KNN vers 0,90, embedding vers 0,97), mais restent
  élevés pour le TF-IDF ; ils ne préjugent en rien des scores sur le vrai export.
- Les tests ne s'appuient pas sur des scores précis, seulement sur des propriétés (ordre, bornes,
  cohérence).
