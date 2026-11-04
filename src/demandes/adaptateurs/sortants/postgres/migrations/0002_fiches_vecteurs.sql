-- Fiches IAG, échecs, contrôle lot / unité, vecteurs et configurations (ADR-0010).

-- Ce que recouvre chaque empreinte (prompt, schéma, modèles…), pour la traçabilité.
CREATE TABLE configurations (
    empreinte  text PRIMARY KEY,
    nature     text        NOT NULL,
    contenu    jsonb       NOT NULL,
    cree_le    timestamptz NOT NULL DEFAULT now()
);

-- Cache des fiches : une par demande et par configuration de fiche.
CREATE TABLE fiches (
    numero           text        NOT NULL,
    empreinte_fiche  text        NOT NULL,
    empreinte_mail   text        NOT NULL,
    fiche            jsonb       NOT NULL,
    taille_lot       integer     NOT NULL,  -- mails dans l'appel qui l'a produite (1 = à l'unité)
    tentatives       integer     NOT NULL,
    duree_ms         integer     NOT NULL,
    cree_le          timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (empreinte_fiche, numero)
);

-- Journal des échecs : demandes sans fiche valide après les reprises (exclues de la branche embedding).
CREATE TABLE echecs_fiches (
    numero           text        NOT NULL,
    empreinte_fiche  text        NOT NULL,
    empreinte_mail   text        NOT NULL,
    tentatives       integer     NOT NULL,
    erreur           text        NOT NULL,
    cree_le          timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (empreinte_fiche, numero)
);

-- Fiches produites à l'unité pour le contrôle qualité lot / unité (n'écrasent jamais le cache).
CREATE TABLE fiches_controle (
    numero           text        NOT NULL,
    empreinte_fiche  text        NOT NULL,
    empreinte_mail   text        NOT NULL,
    fiche            jsonb       NOT NULL,
    tentatives       integer     NOT NULL,
    duree_ms         integer     NOT NULL,
    cree_le          timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (empreinte_fiche, numero)
);

-- Vecteurs normalisés. Colonne « vector » sans dimension fixe : la dimension dépend du modèle
-- d'embedding, qui fait partie de l'empreinte du vecteur.
CREATE TABLE vecteurs (
    numero             text        NOT NULL,
    empreinte_vecteur  text        NOT NULL,
    empreinte_fiche    text        NOT NULL,
    empreinte_mail     text        NOT NULL,
    vecteur            vector      NOT NULL,
    cree_le            timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (empreinte_vecteur, numero)
);
