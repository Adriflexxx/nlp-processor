import csv

import pandas as pd
import pytest

from demandes.adaptateurs.sortants.memoire import DepotCorpusMemoire, DepotReferentielMemoire
from demandes.ports.source_export import ColonnesManquantes
from demandes.ports.suivi import SuiviJournal
from demandes.synthetique import TITRE_RARE, TITRES, ecrire_excel, generer_demandes
from tests.conftest import fabriquer_chargeur


def _lire_csv(chemin):
    with open(chemin, encoding="utf-8-sig") as flux:
        return list(csv.DictReader(flux, delimiter=";"))


def test_chargement_complet(tmp_path, export_synthetique):
    corpus = DepotCorpusMemoire()
    suivi = SuiviJournal()
    resultat = fabriquer_chargeur(tmp_path, corpus=corpus).executer(export_synthetique, suivi)

    assert resultat.nb_lignes == 400 + 4 + 3
    assert resultat.motifs_ecart == {"mail_vide": 1, "titre_vide": 1, "numero_en_double": 1}
    assert resultat.nb_retenues == len(corpus.demandes) == 404
    assert resultat.nb_titres == len(TITRES) + 1
    assert resultat.petites_categories == [TITRE_RARE]
    assert resultat.nb_titres_apprentissage == len(TITRES)
    assert resultat.encodages_repares >= 1
    assert resultat.reference_creee
    assert resultat.nb_templates > 0
    # Les mails libres existent aussi, y compris pour les Titres servis par un template.
    assert resultat.nb_templates < resultat.nb_retenues

    # Le mail à l'encodage cassé est réparé, le mail HTML nettoyé.
    par_numero = {d.numero: d for d in corpus.demandes}
    assert "Ã" not in par_numero["DEM100001"].mail
    assert "<" not in par_numero["DEM100002"].mail_nettoye
    assert "confidentiels" not in par_numero["DEM100003"].mail_nettoye

    ecartees = _lire_csv(resultat.fichiers["lignes_ecartees"])
    assert {e["motif"] for e in ecartees} == {"mail_vide", "titre_vide", "numero_en_double"}
    carto = _lire_csv(resultat.fichiers["cartographie"])
    assert sum(int(e["nb_demandes"]) for e in carto) == 404
    assert all(e["premiere_date"] <= e["derniere_date"] for e in carto)

    # Suivi : toutes les étapes, progression croissante jusqu'à 100 %.
    progressions = [p for _, _, p in suivi.messages]
    assert progressions == sorted(progressions) and progressions[-1] == 1.0


def test_templates_alignes_sur_le_generateur(tmp_path, export_synthetique):
    corpus = DepotCorpusMemoire()
    fabriquer_chargeur(tmp_path, corpus=corpus).executer(export_synthetique, SuiviJournal())
    for d in corpus.demandes:
        issu_du_formulaire = "Formulaire de demande d'habilitation" in d.mail or "Merci de compléter tous les champs" in d.mail
        if issu_du_formulaire:
            assert d.template, d.numero


def test_ecarts_avec_la_reference(tmp_path, export_synthetique):
    referentiel = DepotReferentielMemoire()
    fabriquer_chargeur(tmp_path, referentiel=referentiel).executer(export_synthetique, SuiviJournal())

    df = generer_demandes(400, 7)
    df.loc[df["titre"] == "Anomalie export FACTO", "titre"] = "Nouveau Titre"
    second = ecrire_excel(df, tmp_path / "second.xlsx")
    suivi = SuiviJournal()
    resultat = fabriquer_chargeur(tmp_path, referentiel=referentiel).executer(second, suivi)

    assert not resultat.reference_creee
    assert resultat.titres_nouveaux == ["Nouveau Titre"]
    assert resultat.titres_disparus == ["Anomalie export FACTO"]
    assert any(niveau == "WARNING" and "absents de la référence" in m for niveau, m, _ in suivi.messages)
    # La référence n'a pas bougé.
    assert "Anomalie export FACTO" in {e.titre for e in referentiel.reference}


def test_colonnes_manquantes(tmp_path, export_synthetique):
    chargeur = fabriquer_chargeur(tmp_path, mapping={"num": "numero", "titre": "titre", "description": "mail"})
    with pytest.raises(ColonnesManquantes, match="num"):
        chargeur.executer(export_synthetique, SuiviJournal())


def test_export_sans_date(tmp_path):
    df = generer_demandes(60, 1).drop(columns=["date"])
    chemin = ecrire_excel(df, tmp_path / "sans_date.xlsx")
    mapping = {"numero": "numero", "titre": "titre", "description": "mail"}
    resultat = fabriquer_chargeur(tmp_path, mapping=mapping).executer(chemin, SuiviJournal())
    assert resultat.dates_absentes == resultat.nb_retenues


def test_numero_numerique_lu_sans_decimale(tmp_path):
    df = pd.DataFrame({"numero": [123456, 123457], "titre": ["T", "T"], "description": ["a", "b"]})
    chemin = tmp_path / "num.xlsx"
    df.to_excel(chemin, index=False)
    corpus = DepotCorpusMemoire()
    mapping = {"numero": "numero", "titre": "titre", "description": "mail"}
    fabriquer_chargeur(tmp_path, corpus=corpus, mapping=mapping).executer(chemin, SuiviJournal())
    assert [d.numero for d in corpus.demandes] == ["123456", "123457"]


def test_parallele_meme_resultat(tmp_path, export_synthetique, monkeypatch):
    import demandes.parallele as parallele

    monkeypatch.setattr(parallele, "SEUIL_PARALLELE", 0)
    sequentiel, parallele_ = DepotCorpusMemoire(), DepotCorpusMemoire()
    fabriquer_chargeur(tmp_path / "a", corpus=sequentiel).executer(export_synthetique, SuiviJournal())
    fabriquer_chargeur(tmp_path / "b", n_processus=2, corpus=parallele_).executer(export_synthetique, SuiviJournal())
    assert sequentiel.demandes == parallele_.demandes
