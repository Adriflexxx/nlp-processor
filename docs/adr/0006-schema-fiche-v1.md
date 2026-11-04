# ADR-0006 : Schéma de la fiche v1 et décodage guidé

- Date : 2026-11-03
- Statut : Acceptée
- Remplace : —

## Contexte

La branche « sens » transforme chaque mail en une fiche JSON produite par l'IAG, puis vectorise
cette fiche. L'IAG interne accepte les sorties structurées imposées (décodage guidé par schéma JSON).

## Décision

**Schéma** (`SCHEMA_FICHE`, défini une seule fois dans `domaine/fiche.py`, tous les champs
obligatoires, `additionalProperties: false`) :

| Champ | Type | Contenu |
|---|---|---|
| `objet_origine` | chaîne | objet du mail tel quel |
| `template` | booléen | le mail suit-il un template de la société |
| `marqueurs_template` | liste de chaînes | formulations fixes repérées, `[]` si aucune |
| `application` | chaîne | application ou périmètre concerné, `"inconnu"` si absent |
| `action` | énumération | `creer`, `modifier`, `supprimer`, `donner_acces`, `retirer_acces`, `signaler`, `demander_information`, `autre` |
| `objet_action` | chaîne | sur quoi porte l'action |
| `elements_discriminants` | liste de 1 à 5 chaînes | ce qui distingue cette demande |
| `resume` | chaîne | 2 phrases maximum |

**Appel** : bibliothèque `openai`, `response_format={"type": "json_schema", "json_schema":
{"name": "fiche_demande", "schema": SCHEMA_FICHE, "strict": True}}`. Paramètre `JSON_MODE` :
`json_schema` par défaut, `json_object` en repli (le schéma est alors décrit dans le prompt).

**Validation** : chaque réponse est validée contre `SCHEMA_FICHE` (jsonschema). En cas d'échec :
2 reprises, puis la demande est journalisée en échec et **exclue de la branche embedding** ; la
branche TF-IDF la garde.

**Règles du prompt** (`prompts/fiche_v1.md`) : n'utiliser que le contenu du mail reçu, jamais les
données ajoutées par l'opérateur ; ignorer la signature et les formules de politesse ; ne jamais
deviner la catégorie ITZME.

**Texte vectorisé** : concaténation des champs dans cet ordre fixe : `objet_origine`,
`application`, `action`, `objet_action`, `elements_discriminants`, `resume`.

## Conséquences

- Le booléen `template` qui découpe l'évaluation (mails template / mails libres) reste celui du
  **repérage statistique** de l'étape 1 (ADR-0009), déterministe. Celui de la fiche n'est qu'une
  caractéristique ; on mesurera la concordance des deux.
- Tout changement du schéma, du prompt ou de l'ordre de concaténation change l'empreinte de la
  fiche (ADR-0007) et exige un nouvel ADR.
