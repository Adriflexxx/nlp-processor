# ADR-0008 : Tâches de fond et journal d'avancement détaillé

- Date : 2026-11-03
- Statut : Acceptée
- Remplace : —

## Contexte

Les étapes longues (fiches pour 10 000 mails, validation croisée de 13 combinaisons) prennent de
quelques minutes à plusieurs heures. Depuis l'API comme depuis la ligne de commande, on veut savoir
où en est le traitement, avec le détail de chaque étape.

## Décision

- Chaque exécution d'un cas d'usage est une **tâche** (table `taches`) : type, paramètres, statut
  (`en_attente`, `en_cours`, `terminee`, `echec`), progression (0 à 1), étape courante, dernier
  message, résultat JSON ou erreur. La CLI crée aussi une tâche : l'historique est commun.
- Le **port `Suivi`** est le seul moyen pour un cas d'usage de signaler son avancement :
  `demarrer(etapes)`, `etape(nom)`, `avancer(fait, total)`, `info`, `alerte`, `terminer`.
  La progression globale est calculée à partir du rang de l'étape et de l'avancement dans l'étape.
- Chaque message est écrit dans `journal_taches` (horodatage, niveau, message, progression, étape,
  données structurées) et dans les logs. Les messages de progression sont limités à un par seconde
  et par point de pourcentage, pour ne pas inonder la base.
- API : `GET /taches/{id}` (état), `GET /taches/{id}/journal?apres=N` (nouvelles lignes),
  `GET /taches/{id}/flux` (Server-Sent Events, en direct).
- Au démarrage de l'API, les tâches restées `en_cours` sont passées en `echec` (interrompues).

## Conséquences

- Un cas d'usage ne doit jamais faire de `print` : tout passe par le `Suivi`.
- La tâche ne peut pas être annulée en cours de route pour l'instant (évolution possible).
