# ADR-0009 : Règles de chargement, de contrôle et de repérage des templates

- Date : 2026-11-03
- Statut : Acceptée
- Remplace : —

## Contexte

La spécification demande des contrôles (lignes sans mail ou sans Titre, numéros en double,
encodage des accents), une cartographie des Titres figée comme référence, l'exclusion des petites
catégories et un booléen `template` par mail. Plusieurs points restaient à trancher.

## Décision

**Colonnes** : mapping configurable (`COLONNE_NUMERO`, `COLONNE_TITRE`, `COLONNE_MAIL`,
`COLONNE_DATE`). Valeurs par défaut : `numero`, `titre`, `description`, `date`. La date est
facultative (`COLONNE_DATE` vide) ; sans date, le contrôle dans le temps sera désactivé. Une date
illisible devient vide, sans écarter la ligne.

**Lignes écartées** (fichier `artefacts/chargement/lignes_ecartees.csv` et table `lignes_ecartees`),
dans cet ordre de priorité : `numero_vide`, `mail_vide`, `titre_vide`, `numero_en_double` (la
première occurrence est gardée, les suivantes sont écartées).

**Encodage** : on ne rejette pas un mail pour son encodage. Les caractères NUL sont retirés ; un
texte UTF-8 relu en Latin-1/CP1252 (« Ã© ») est réparé quand la réparation réduit les séquences
fautives ; les caractères illisibles restants (U+FFFD) sont comptés et signalés dans le bilan.

**Référence des Titres** : au premier chargement, la cartographie est figée comme référence (table
`referentiel_titres`). Aux chargements suivants, les Titres absents de la référence et les Titres
disparus sont signalés (journal et `ecarts_referentiel.csv`). `--nouvelle-reference` refige.

**Petites catégories** : calculées à partir de `MIN_PAR_TITRE` au moment du chargement (CSV) et
**recalculées à l'entraînement**, pour qu'un changement de seuil ne demande pas de recharger.

**Templates** (repérage statistique, déterministe) :
1. Lignes candidates prises dans le corps seulement : on saute l'en-tête (`De :`, `Objet :`…) et on
   s'arrête à la formule de politesse finale (« Cordialement »…), pour que les signatures, qui se
   répètent aussi, ne comptent pas. Une ligne « libellé : valeur » est réduite à son libellé si
   ce libellé fait au plus 6 mots ; au-delà, c'est une phrase rédigée, gardée entière.
2. Une candidate est un **marqueur** si elle revient dans au moins `TEMPLATE_MIN_MAILS` mails (5)
   et dans au plus `TEMPLATE_FREQ_MAX` du corpus (30 %).
3. Un mail est un template s'il porte au moins `TEMPLATE_MIN_MARQUEURS` marqueurs distincts (2),
   s'il correspond à un motif de `TEMPLATE_MOTIFS`, ou (si `TEMPLATE_OBJET=true`) si son objet
   revient à l'identique dans au moins `TEMPLATE_MIN_MAILS` mails **et** qu'il porte au moins un
   marqueur. Un objet fixe seul ne suffit pas : sur les données synthétiques, des objets libres
   fréquents (« Demande FACTO ») faisaient passer 100 % des mails pour des templates.
Les marqueurs retenus et le résultat par mail sont écrits dans `marqueurs_template.csv` et
`templates_par_mail.csv`, pour régler les seuils à la main.

**Nettoyage TF-IDF** : retrait du HTML, des mentions légales automatiques (à partir de leur
première phrase reconnue) et des espaces superflus ; l'objet et l'en-tête sont gardés.

## Conséquences

- Les seuils sont à vérifier sur le vrai export, à partir de `marqueurs_template.csv` et
  `templates_par_mail.csv` ; un template sans libellé fixe (texte libre sous un objet imposé) peut
  être rattrapé par `TEMPLATE_MOTIFS`.
- Ces seuils ne font pas partie de la configuration figée du modèle : ils ne servent qu'à découper
  l'évaluation. Les changer demande toutefois un nouvel ADR.
