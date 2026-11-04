"""Rapport, recommandation, prédiction d'un nouveau mail et boucle de retour (ADR-0016, 0017)."""

import json

import pandas as pd
import pytest

from demandes.adaptateurs.sortants.graphiques import GraphiquesMatplotlib
from demandes.adaptateurs.sortants.memoire import DepotPredictionsMemoire
from demandes.adaptateurs.sortants.simulateurs import GenerateurFichesSimule
from demandes.application.predire import ConfigurationIndisponible, ParametresPrediction, Prediction
from demandes.application.rapporter import ParametresRapport, Rapport, choisir_configuration
from demandes.application.retours import ColonnesExport, PredictionInconnue, Retours
from demandes.ports.iag import ErreurIag
from demandes.ports.suivi import SuiviJournal
from tests.unitaires.test_apprentissage import _monter

MAIL = "De : a@b.fr\nObjet : export FACTO\n\nBonjour,\nL'export FACTO est vide, message d'erreur au lancement.\n\nCordialement"


@pytest.fixture(scope="module")
def evalue(tmp_path_factory, export_synthetique):
    tmp = tmp_path_factory.mktemp("evalue")
    corpus, entrainement, evaluation, art = _monter(tmp, export_synthetique)
    entrainement.executer(SuiviJournal())
    evaluation.executer(SuiviJournal())
    return corpus, entrainement, evaluation, art


def _eval(nom, cout, top1, libre):
    return {"nom": nom, "libelle": nom, "cout": cout, "test": {"ensemble": {"top1": top1}, "libre": {"top1": libre}}}


def test_choisir_la_plus_legere_sauf_gain_net():
    simple, lourde = _eval("simple", 1, 0.90, 0.85), _eval("lourde", 5, 0.905, 0.855)
    assert choisir_configuration([simple, lourde], 0.01)[0]["nom"] == "simple"
    lourde_libres = _eval("lourde", 5, 0.905, 0.90)  # gain net sur les mails libres
    assert choisir_configuration([simple, lourde_libres], 0.01)[0]["nom"] == "lourde"
    nette = _eval("nette", 5, 0.95, 0.85)
    assert choisir_configuration([simple, nette], 0.01)[0]["nom"] == "nette"


def test_rapport_complet(evalue):
    _, entrainement, evaluation, art = evalue
    rapport = Rapport(entrainement, evaluation.evaluations, art, GraphiquesMatplotlib(), ParametresRapport("svm_tfidf", 0.01, "mock", "mock"))
    r = rapport.executer(SuiviJournal())
    texte = open(r["rapport"], encoding="utf-8").read()
    assert "## Recommandation" in texte and "## Classement des combinaisons" in texte
    assert texte.count("| ") > 13 and "✅" in texte
    for cle in ("couverture", "fiabilite"):
        assert open(r["fichiers"][cle], "rb").read(4) == b"\x89PNG"
    reco = r["recommandation"]
    assert reco["mode"] in ("seul", "moyenne", "meta") and reco["modeles"]


LINEAIRES = ("svm_tfidf", "rl_tfidf", "svm_emb", "rl_emb")  # toujours parmi les 13 combinaisons


def _prediction(evaluation, art, mode="moyenne", modeles=LINEAIRES, generateur=None, **seuils):
    return Prediction(
        evaluation.evaluations, DepotPredictionsMemoire(), art, generateur or GenerateurFichesSimule(),
        evaluation.vectoriseur,
        ParametresPrediction(mode, modeles, 8000, seuils.get("haut"), seuils.get("moyen"), True),
    )


def test_predire_top3_niveau_et_avis(evalue):
    _, _, evaluation, art = evalue
    prediction = _prediction(evaluation, art)
    r = prediction.predire(MAIL)
    assert r.id == 1 and len(r.top3) == 3
    assert r.top3[0]["titre"] == "Anomalie export FACTO"
    assert r.top3[0]["probabilite"] >= r.top3[1]["probabilite"] >= r.top3[2]["probabilite"]
    assert r.niveau in ("haut", "moyen", "aucun")
    assert [a["modele"] for a in r.avis] == list(LINEAIRES)
    assert r.fiche is not None and r.configuration["nom"] == "moyenne__svm_tfidf+rl_tfidf+svm_emb+rl_emb"
    journal = prediction.predictions.lire(r.id)
    assert journal.mail == MAIL and journal.niveau == r.niveau


def test_predire_seuils_manuels_et_desaccord(evalue):
    _, _, evaluation, art = evalue
    r = _prediction(evaluation, art, mode="seul", modeles=("svm_tfidf",), haut=1.0, moyen=0.0).predire(MAIL)
    assert r.niveau == "moyen" and r.configuration["seuils"]["source"] == "manuel" and r.fiche is None


def test_predire_fiche_en_echec_repli_a_priori(evalue):
    _, _, evaluation, art = evalue

    class EnPanne(GenerateurFichesSimule):
        async def generer(self, mails):
            raise ErreurIag("indisponible")

    r = _prediction(evaluation, art, generateur=EnPanne()).predire(MAIL)
    assert r.remarques and "a priori" in r.remarques[0]
    assert r.top3[0]["titre"] == "Anomalie export FACTO"  # la branche TF-IDF porte la décision


def test_predire_configuration_non_evaluee(evalue):
    _, _, evaluation, art = evalue
    with pytest.raises(ConfigurationIndisponible, match="evaluer --mode meta"):
        _prediction(evaluation, art, mode="meta", modeles=("rl_tfidf", "knn_emb")).predire(MAIL)


def test_retours_et_export(evalue, tmp_path):
    _, _, evaluation, art = evalue
    prediction = _prediction(evaluation, art)
    ids = [prediction.predire(MAIL).id for _ in range(3)]
    retours = Retours(prediction.predictions, ColonnesExport("numero", "titre", "description", "date"))
    assert retours.enregistrer(ids[0], "Anomalie export FACTO", "op1")["rang_dans_le_top3"] == 1
    assert retours.enregistrer(ids[1], "Titre nouveau")["rang_dans_le_top3"] is None
    with pytest.raises(PredictionInconnue):
        retours.enregistrer(999, "X")
    with pytest.raises(ValueError):
        retours.enregistrer(ids[2], "  ")
    r = retours.exporter(tmp_path / "retours.xlsx", mois=12)
    assert r["n"] == 2 and r["exactitude_top1_en_production"] == 0.5
    df = pd.read_excel(tmp_path / "retours.xlsx")
    assert list(df.columns) == ["numero", "date", "titre", "description"]
    assert set(df["numero"]) == {f"PRED{ids[0]}", f"PRED{ids[1]}"}
