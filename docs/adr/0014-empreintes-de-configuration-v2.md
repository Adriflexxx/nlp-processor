# ADR-0014 : Empreintes de configuration (v2) : fiche, vecteur, jeu, modèle

- Date : 2026-11-04
- Statut : Acceptée
- Remplace : ADR-0007

## Contexte

L'ADR-0007 prévoyait une seule « empreinte de run » couvrant vecteurs, TF-IDF, grilles et
protocole. À l'implémentation de l'entraînement, une empreinte unique obligerait à tout recalculer
dès qu'un seul élément change : ajouter les vecteurs après un premier score TF-IDF relancerait la
validation croisée du TF-IDF. L'ADR-0010 a déjà précisé l'empreinte de fiche. Cet ADR remplace
l'ADR-0007 et rassemble les quatre empreintes réellement utilisées.

## Décision

Toutes les empreintes sont des SHA-256 d'un JSON canonique (clés triées). Elles sont tronquées à
16 caractères dans les noms de dossiers, complètes ailleurs.

1. **Fiche** (`ConfigFiche`) : consigne (prompt), `SCHEMA_FICHE`, modèle LLM, température,
   `JSON_MODE`, `MAIL_MAX_CARACTERES`. **Pas** `FICHES_PAR_APPEL` (ADR-0010). Clé du cache des
   fiches, avec l'empreinte du mail.
2. **Vecteur** (`ConfigVecteur`) : empreinte de fiche, modèle d'embedding, dimension, version du
   texte vectorisé. Clé du cache des vecteurs, avec l'empreinte du mail.
3. **Jeu** (`construire_jeu`) : liste des (numéro, Titre, empreinte du mail) retenus, `MIN_PAR_TITRE`,
   `TAILLE_TEST`, `N_PLIS`, `SEED`, version. Elle fixe le découpage 80/20 et les plis ; dossier
   `artefacts/entrainement/<jeu>/` (découpage, classes, évaluations, combinateurs).
4. **Modèle** (une par modèle de base) : empreinte du jeu, clé du modèle, grille complète (dont les
   dimensions d'ACP testées), version des définitions de modèles ; plus `TFIDF_CARACTERES` pour la
   branche TF-IDF ; plus l'empreinte de vecteur et l'empreinte de la liste des demandes qui ont un
   vecteur pour la branche embedding. Dossier `…/modeles/<cle>-<empreinte>/` : prédictions hors
   pli, prédictions de test, modèle final, grille.

En mode `MOCK_LLM`, les noms de modèles sont préfixés par `mock:` : les fiches, vecteurs et
modèles simulés ne se mélangent jamais aux vrais.

Chaque empreinte de fiche et de vecteur est enregistrée avec son contenu dans la table
`configurations`.

## Conséquences

- Changer de modèle d'embedding ne recalcule que les vecteurs puis les trois modèles embedding ;
  le TF-IDF reste en cache.
- Changer une grille ne recalcule que le modèle concerné.
- Un nouvel export (Titres ou mails différents) change l'empreinte du jeu : tout l'entraînement est
  refait, ce qui est voulu, puisque le découpage change.
