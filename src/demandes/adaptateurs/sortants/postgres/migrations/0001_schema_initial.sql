-- Schéma initial : corpus, référence des Titres, tâches de fond et journal d'avancement.
-- Les tables des fiches, vecteurs, runs et prédictions viendront dans des migrations suivantes.

CREATE EXTENSION IF NOT EXISTS vector;

CREATE TABLE imports (
    id                 bigserial PRIMARY KEY,
    fichier            text        NOT NULL,
    empreinte_fichier  text        NOT NULL,
    charge_le          timestamptz NOT NULL DEFAULT now(),
    nb_lignes          integer     NOT NULL,
    nb_retenues        integer     NOT NULL,
    nb_ecartees        integer     NOT NULL,
    bilan              jsonb       NOT NULL DEFAULT '{}'::jsonb
);

-- Corpus courant : remplacé entièrement à chaque chargement.
CREATE TABLE demandes (
    numero              text PRIMARY KEY,
    date_demande        timestamptz,
    titre               text    NOT NULL,
    mail                text    NOT NULL,
    mail_nettoye        text    NOT NULL,
    objet               text,
    template            boolean NOT NULL,
    marqueurs_template  jsonb   NOT NULL DEFAULT '[]'::jsonb,
    -- Empreinte du mail brut : une fiche en cache n'est réutilisée que si le mail n'a pas changé.
    empreinte_mail      text    NOT NULL,
    import_id           bigint  NOT NULL REFERENCES imports (id)
);
CREATE INDEX demandes_titre_idx ON demandes (titre);

CREATE TABLE lignes_ecartees (
    id            bigserial PRIMARY KEY,
    import_id     bigint  NOT NULL REFERENCES imports (id) ON DELETE CASCADE,
    ligne_source  integer NOT NULL,
    numero        text,
    motif         text    NOT NULL,
    detail        text    NOT NULL DEFAULT ''
);

-- Référence figée des Titres (cartographie d'un export choisi comme référence).
CREATE TABLE referentiel_titres (
    titre          text PRIMARY KEY,
    nb_demandes    integer     NOT NULL,
    premiere_date  timestamptz,
    derniere_date  timestamptz,
    fige_le        timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE taches (
    id           uuid PRIMARY KEY,
    type         text        NOT NULL,
    statut       text        NOT NULL CHECK (statut IN ('en_attente', 'en_cours', 'terminee', 'echec')),
    parametres   jsonb       NOT NULL DEFAULT '{}'::jsonb,
    progression  real        NOT NULL DEFAULT 0,
    etape        text,
    message      text,
    resultat     jsonb,
    erreur       text,
    cree_le      timestamptz NOT NULL DEFAULT now(),
    demarre_le   timestamptz,
    termine_le   timestamptz
);
CREATE INDEX taches_cree_le_idx ON taches (cree_le DESC);

CREATE TABLE journal_taches (
    id           bigserial PRIMARY KEY,
    tache_id     uuid        NOT NULL REFERENCES taches (id) ON DELETE CASCADE,
    horodatage   timestamptz NOT NULL DEFAULT now(),
    niveau       text        NOT NULL,
    message      text        NOT NULL,
    progression  real        NOT NULL,
    etape        text,
    donnees      jsonb       NOT NULL DEFAULT '{}'::jsonb
);
CREATE INDEX journal_taches_tache_idx ON journal_taches (tache_id, id);
