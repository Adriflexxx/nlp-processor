-- Évaluations des combinaisons et journal des prédictions (boucle de retour opérateur).

CREATE TABLE evaluations (
    empreinte_jeu  text        NOT NULL,
    nom            text        NOT NULL,  -- combinaison (mode__modeles) ou « temporel »
    contenu        jsonb       NOT NULL,
    cree_le        timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (empreinte_jeu, nom)
);
CREATE INDEX evaluations_cree_le_idx ON evaluations (cree_le DESC);

CREATE TABLE predictions (
    id             bigserial PRIMARY KEY,
    horodatage     timestamptz NOT NULL DEFAULT now(),
    mail           text        NOT NULL,
    configuration  jsonb       NOT NULL,  -- mode, modèles, empreintes, seuils
    top3           jsonb       NOT NULL,
    niveau         text        NOT NULL,
    avis           jsonb       NOT NULL,  -- avis de chaque modèle de base
    titre_retenu   text,                  -- complété par l'opérateur
    operateur      text,
    retenu_le      timestamptz
);
CREATE INDEX predictions_horodatage_idx ON predictions (horodatage);
