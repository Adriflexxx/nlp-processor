# ADR-0010 : Fiches produites par lots à l'ingestion

- Date : 2026-11-04
- Statut : Acceptée
- Remplace : ADR-0006

## Contexte

L'IAG interne sait traiter plusieurs mails dans un même appel et renvoyer la liste des fiches,
chacune rattachée à son numéro. Pour 10 000 mails, cela divise le nombre d'appels par la taille
du lot. Mais regrouper des mails dans un même prompt comporte des risques : contamination entre
mails, numéros intervertis, fiche qui dépend de ses voisins, écart avec la production où
`predire` traite un mail seul. Les comparaisons de l'utilisateur supposent en outre que toutes
les données (fiches et vecteurs compris) soient produites dès l'ingestion.

Cet ADR remplace l'ADR-0006 : le schéma des champs de la fiche est inchangé, mais le format
d'appel et de réponse change. Il précise aussi l'ADR-0007 (empreintes).

## Décision

**Ingestion** : `charger` enchaîne lecture, contrôles, cartographie, templates, puis fiches et
embeddings des demandes absentes du cache, dans une même tâche suivie. Réglage
`FICHES_A_L_INGESTION=true` ; `charger --sans-fiches` (API : `"avec_fiches": false`) ne fait aucun
appel à l'IAG. La commande `fiches` reste disponible seule. La branche TF-IDF n'en dépend pas.

**Schéma de la fiche** (`SCHEMA_FICHE`, défini une seule fois dans `domaine/fiche.py`, tous les
champs obligatoires, `additionalProperties: false`) : `objet_origine` (chaîne), `template`
(booléen), `marqueurs_template` (liste de chaînes, `[]` si aucune), `application` (chaîne,
`"inconnu"` si absent), `action` (énumération : `creer`, `modifier`, `supprimer`, `donner_acces`,
`retirer_acces`, `signaler`, `demander_information`, `autre`), `objet_action` (chaîne),
`elements_discriminants` (1 à 5 chaînes), `resume` (2 phrases au plus).

**Lots** :
- `FICHES_PAR_APPEL` mails par appel (10 par défaut ; 1 = un mail par appel), avec un budget
  `LOT_MAX_CARACTERES` (40 000) ; un mail plus long que le budget part seul. Les mails sont envoyés
  nettoyés (sans HTML ni mentions légales) et tronqués à `MAIL_MAX_CARACTERES` (8 000).
- Les lots partent en parallèle, `LLM_CONCURRENCY` appels à la fois (asyncio, ADR-0004).
- **Un mail seul est un lot de 1** : même consigne, même format. Les reprises à l'unité, le
  contrôle qualité et `predire` utilisent donc exactement le même prompt que les lots.

**Prompt** (`prompts/fiche_v1.md`, message système fixe, placé en tête pour le cache de préfixe) :
chaque mail est délimité par `<mail id="NUMERO"> … </mail>` dans le message utilisateur ; chaque
mail est traité indépendamment des autres ; n'utiliser que le contenu du mail ; ignorer signature
et formules de politesse ; ne jamais deviner la catégorie ITZME.

**Réponse imposée** (décodage guidé, `strict: true`) : `{"fiches": [{"id": …, …champs de
SCHEMA_FICHE}]}`. Le schéma est construit pour chaque lot à partir de `SCHEMA_FICHE` : `id` est
restreint par une énumération aux numéros du lot (l'IAG ne peut pas en inventer) et le nombre de
fiches est fixé à la taille du lot. `JSON_MODE=json_object` reste le repli (le schéma est alors
décrit dans le prompt système).

**Contrôles** (`depouiller_reponse`) : une fiche est rattachée à sa demande par son id, jamais par
sa position ; un id inconnu du lot est rejeté ; un id présent plusieurs fois est rejeté en entier ;
chaque fiche est validée contre `SCHEMA_FICHE` (jsonschema, autorisé dans le domaine : calcul pur,
sans I/O).

**Reprises** : une réponse tronquée (limite de jetons, `max_tokens` = `IAG_MAX_TOKENS_PAR_FICHE` ×
taille du lot + 100) fait couper le lot en deux, relancé. Les demandes sans fiche valide sont
renvoyées une par une, avec 2 reprises (3 envois à l'unité ; 2 si le lot était déjà d'un seul
mail), puis journalisées en échec (`echecs_fiches`, `artefacts/fiches/<empreinte>/echecs.csv`) et
exclues de la branche embedding ; la branche TF-IDF les garde. `fiches --reprendre-echecs` les
retente. Après 20 erreurs réseau d'affilée, la tâche s'arrête (IAG jugée indisponible) ; les
fiches déjà produites restent en cache et une relance reprend là où elle s'est arrêtée.

**Cache** : par demande, clé (empreinte de fiche, numéro), avec l'empreinte du mail ; un lot ne
contient que des demandes absentes du cache ou dont le mail a changé ; chaque fiche valide est
enregistrée dès la réception de la réponse de son lot. Chaque fiche garde la taille du lot qui l'a
produite (`taille_lot`).

**Empreintes (précise l'ADR-0007)** : l'empreinte de fiche couvre la consigne, le schéma, le
modèle, la température, `JSON_MODE` et `MAIL_MAX_CARACTERES`, mais **pas** `FICHES_PAR_APPEL` :
changer la taille des lots ne vide pas le cache, et la traçabilité passe par `taille_lot`.
Chaque empreinte est enregistrée avec son contenu dans la table `configurations`.

**Embeddings** : par paquets de `EMBED_PAR_APPEL` (100), en parallèle selon `LLM_CONCURRENCY`,
vecteurs normalisés, stockés dans `vecteurs` (colonne pgvector sans dimension fixe).

**Contrôle qualité** (`controle-lots`, 200 mails par défaut) : sur un échantillon tiré avec `SEED`
parmi les fiches produites en lot, la fiche est refaite à l'unité (table `fiches_controle`, qui
n'écrase jamais le cache) et l'on mesure l'accord sur `action`, `application`, `template` et
`objet_action`. L'exactitude top 1 de `rl_emb` (entraîné sur les fiches en lot, évalué avec les
fiches en lot puis à l'unité) s'y ajoutera avec les modèles de la branche embedding : c'est elle
qui mesure l'écart entre l'ingestion (lots) et la production (`predire`, un mail). Si le lot
dégrade les résultats, on réduit `FICHES_PAR_APPEL`.

## Conséquences

- Le nombre d'appels à l'IAG est divisé par la taille des lots ; le gain de temps réel dépend du
  serveur (un appel de 10 fiches est plus long qu'un appel d'une fiche) et se lit dans le débit
  affiché par la tâche.
- Les fiches d'apprentissage et la fiche de production ne sont pas produites dans les mêmes
  conditions ; le contrôle qualité est obligatoire avant de retenir une configuration en lot.
- Le prompt de fiche passe au format « un ou plusieurs mails » : l'empreinte de fiche change par
  rapport à l'ADR-0006 (aucune fiche n'avait encore été produite).
