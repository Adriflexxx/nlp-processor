# ADR-0011 : Règles de chargement, de contrôle et de repérage des templates (v2)

- Date : 2026-11-04
- Statut : Acceptée
- Remplace : ADR-0009

## Contexte

L'ADR-0009 décrit la réparation de l'encodage comme une réparation globale du texte (« réparé
quand la réparation réduit les séquences fautives »). Le code livré répare séquence par séquence :
une réparation globale échoue dès qu'une seule séquence n'est pas réparable, ce qui arrive avec un
mail en partie seulement cassé (réponse collée sous un mail correct) ou quand l'espace insécable
d'un « à » cassé est devenue une espace ordinaire. Cet ADR remplace l'ADR-0009 pour décrire le
comportement réel ; les autres règles sont reprises sans changement.

## Décision

**Colonnes** : mapping configurable (`COLONNE_NUMERO`, `COLONNE_TITRE`, `COLONNE_MAIL`,
`COLONNE_DATE`). Valeurs par défaut : `numero`, `titre`, `description`, `date`. La date est
facultative (`COLONNE_DATE` vide) ; sans date, le contrôle dans le temps sera désactivé. Une date
illisible devient vide, sans écarter la ligne. Un numéro lu comme nombre (« 123456.0 ») redevient
« 123456 ».

**Lignes écartées** (`artefacts/chargement/lignes_ecartees.csv` et table `lignes_ecartees`), dans
cet ordre de priorité : `numero_vide`, `mail_vide`, `titre_vide`, `numero_en_double` (la première
occurrence est gardée, les suivantes sont écartées).

**Encodage** (`domaine/controles.py`, `reparer_texte`) : on ne rejette jamais un mail pour son
encodage.
1. Les caractères NUL sont retirés (PostgreSQL les refuse).
2. Réparation **séquence par séquence** du texte UTF-8 relu en Latin-1 / CP1252 : chaque séquence
   formée d'une tête `Ã`, `Â` ou `Å` suivie d'un octet de suite, ou d'une tête `â` suivie de deux
   octets de suite (octets 0x80-0xBF vus en Latin-1 ou en CP1252), est réencodée puis redécodée en
   UTF-8 ; une séquence qui ne se redécode pas est laissée telle quelle. Le reste du texte n'est
   pas touché.
3. Les autres majuscules accentuées (`É`, `È`, `Ê`…) ne sont **pas** des têtes : « RÉSUMÉ » suivi
   d'une espace insécable est un texte correct, qu'il ne faut pas « réparer ».
4. Si au moins une séquence a été réparée (texte avéré cassé), « Ã » suivi d'une espace ordinaire
   est remplacé par « à » : c'est un « à » dont l'insécable s'est perdue.
5. Les caractères illisibles restants (U+FFFD) sont comptés et signalés dans le bilan.

**Référence des Titres** : au premier chargement, la cartographie est figée comme référence (table
`referentiel_titres`). Aux chargements suivants, les Titres absents de la référence et les Titres
disparus sont signalés (journal et `ecarts_referentiel.csv`). `--nouvelle-reference` refige.

**Petites catégories** : calculées à partir de `MIN_PAR_TITRE` au moment du chargement (CSV) et
recalculées à l'entraînement, pour qu'un changement de seuil ne demande pas de recharger.

**Templates** (repérage statistique, déterministe) :
1. Lignes candidates prises dans le corps seulement : on saute l'en-tête (`De :`, `Objet :`…) et on
   s'arrête à la formule de politesse finale (« Cordialement »…), pour que les signatures, qui se
   répètent aussi, ne comptent pas. Une ligne « libellé : valeur » est réduite à son libellé si ce
   libellé fait au plus 6 mots ; au-delà, c'est une phrase rédigée, gardée entière.
2. Une candidate est un **marqueur** si elle revient dans au moins `TEMPLATE_MIN_MAILS` mails (5)
   et dans au plus `TEMPLATE_FREQ_MAX` du corpus (30 %).
3. Un mail est un template s'il porte au moins `TEMPLATE_MIN_MARQUEURS` marqueurs distincts (2),
   s'il correspond à un motif de `TEMPLATE_MOTIFS`, ou (si `TEMPLATE_OBJET=true`) si son objet
   revient à l'identique dans au moins `TEMPLATE_MIN_MAILS` mails **et** qu'il porte au moins un
   marqueur. Un objet fixe seul ne suffit pas (des objets libres fréquents comme « Demande FACTO »
   faisaient passer 100 % des mails synthétiques pour des templates).
Les marqueurs retenus et le résultat par mail sont écrits dans `marqueurs_template.csv` et
`templates_par_mail.csv`, pour régler les seuils à la main.

**Nettoyage TF-IDF** : retrait du HTML, des mentions légales automatiques (à partir de leur
première phrase reconnue) et des espaces superflus ; l'objet et l'en-tête sont gardés.

**Parallélisme** : la réparation et le nettoyage tournent par lots sur plusieurs processus à
partir de 2 000 mails (ADR-0004) ; le résultat est identique au traitement séquentiel (testé).

## Conséquences

- Un mail en partie cassé est réparé sans dégrader sa partie correcte.
- Les seuils des templates sont à vérifier sur le vrai export à partir des deux CSV ; un template
  sans libellé fixe (texte libre sous un objet imposé) peut être rattrapé par `TEMPLATE_MOTIFS`.
- Ces seuils ne font pas partie de la configuration figée du modèle : ils ne servent qu'à découper
  l'évaluation. Les changer demande toutefois un nouvel ADR.
