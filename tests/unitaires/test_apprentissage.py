"""Protocole d'apprentissage : pas de fuite, reproductibilité, ordre des classes, modes, cache (ADR-0014, 0015)."""

from dataclasses import replace
from pathlib import Path

import numpy as np
import pytest
from sklearn.base import BaseEstimator, ClassifierMixin

from demandes.adaptateurs.sortants.fichiers import StockageFichiers
from demandes.adaptateurs.sortants.memoire import (
    DepotCorpusMemoire,
    DepotEvaluationsMemoire,
    DepotFichesMemoire,
    DepotPredictionsMemoire,
    DepotReferentielMemoire,
    DepotVecteursMemoire,
)
from demandes.adaptateurs.sortants.simulateurs import GenerateurFichesSimule, VectoriseurSimule
from demandes.application.empreintes import ConfigFiche
from demandes.application.entrainer import Entrainement, ParametresEntrainement
from demandes.application.evaluer import Evaluation, ModelesNonEntraines, ParametresEvaluation
from demandes.application.generer_fiches import ParametresFiches, ProductionFiches
from demandes.application.jeu import construire_jeu
from demandes.apprentissage import modeles_base
from demandes.apprentissage.combinateurs import desaccord, regler_poids
from demandes.apprentissage.modeles_base import TFIDF, DefinitionModele, aligner
from demandes.apprentissage.seuils import choisir_seuils
from demandes.apprentissage.validation import plis, rechercher_grilles
from demandes.domaine.combinaison import Combinaison, Mode, combinaisons_standard
from demandes.domaine.decision import Niveau, Seuils, niveau_confiance
from demandes.ports.suivi import SuiviJournal
from tests.conftest import fabriquer_chargeur


def _monter(tmp_path: Path, export: Path, dimension=32, acp=(8, 32)):
    corpus = DepotCorpusMemoire()
    fabriquer_chargeur(tmp_path, corpus=corpus, referentiel=DepotReferentielMemoire()).executer(export, SuiviJournal())
    fiches, vecteurs = DepotFichesMemoire(), DepotVecteursMemoire()
    art = StockageFichiers(tmp_path / "artefacts")
    production = ProductionFiches(
        corpus, fiches, vecteurs, GenerateurFichesSimule(), VectoriseurSimule(dimension),
        ConfigFiche("c", "mock", 0.0, "json_schema", 8000), art, ParametresFiches(),
    )
    production.executer(SuiviJournal())
    entrainement = Entrainement(
        corpus, vecteurs, art, ParametresEntrainement(10, 0.2, 3, 42, 1, False, list(acp)),
        production.config_vecteur.empreinte,
    )
    evaluation = Evaluation(
        entrainement, DepotEvaluationsMemoire(), art,
        ParametresEvaluation("rl", 0.95, 0.95, True, None, None, 42, 1),
        fiches, production.vectoriseur, production.config_fiche.empreinte,
    )
    return corpus, entrainement, evaluation, art


@pytest.fixture(scope="module")
def monte(tmp_path_factory, export_synthetique):
    tmp = tmp_path_factory.mktemp("monte")
    corpus, entrainement, evaluation, art = _monter(tmp, export_synthetique)
    resultat = entrainement.executer(SuiviJournal())
    return corpus, entrainement, evaluation, art, resultat


# --- Pas de fuite ---------------------------------------------------------------


class Espion(ClassifierMixin, BaseEstimator):
    """Enregistre les textes vus à l'ajustement ; prédit la distribution a priori."""

    vus: list = []

    def __init__(self, C=1.0):
        self.C = C

    def fit(self, X, y):
        Espion.vus.append(set(X))
        self.classes_, n = np.unique(y, return_counts=True)
        self.p_ = n / n.sum()
        return self

    def predict_proba(self, X):
        return np.tile(self.p_, (len(X), 1))


def test_aucun_objet_ajuste_ne_voit_le_test(tmp_path, export_synthetique, monkeypatch):
    corpus, entrainement, _, _ = _monter(tmp_path, export_synthetique)
    espion = DefinitionModele("svm_tfidf", TFIDF, ({"C": 1.0}, {"C": 2.0}), lambda params, graine, options: Espion(params["C"]))
    monkeypatch.setattr(entrainement, "definitions", lambda jeu: {**modeles_base.definitions(), "svm_tfidf": espion})
    Espion.vus = []
    entrainement.executer(SuiviJournal(), ["svm_tfidf"])
    jeu = entrainement.preparer_jeu()
    textes_test = set(jeu.textes[jeu.test])
    entr = jeu.textes[jeu.entrainement]
    validations = [set(entr[val]) for _, val in jeu.plis]
    assert len(Espion.vus) == 2 * 3 + 1  # 2 paramètres × 3 plis + le modèle final
    for vus in Espion.vus:
        assert not vus & textes_test  # aucun ajustement ne voit le test
    # Chaque ajustement de pli ne voit pas son pli de validation.
    for i, vus in enumerate(Espion.vus[:6]):
        assert not vus & validations[i % 3]


def test_le_vocabulaire_tfidf_ignore_les_mots_du_test(tmp_path, export_synthetique):
    corpus, entrainement, _, art = _monter(tmp_path, export_synthetique)
    jeu = construire_jeu(corpus.demandes, 10, 0.2, 3, 42)
    test = set(jeu.numeros[jeu.test][:3])
    # Un mot présent dans 3 mails du test seulement : min_df=2 le retiendrait s'il y avait fuite.
    corpus.demandes = [
        replace(d, mail_nettoye=d.mail_nettoye + " motdefuite") if d.numero in test else d for d in corpus.demandes
    ]
    r = entrainement.executer(SuiviJournal(), ["svm_tfidf", "rl_tfidf"])
    for cle in ("svm_tfidf", "rl_tfidf"):
        modele = art.lire_objet(f"{r.modeles[cle]['dossier']}/modele.joblib")
        vocabulaire = modele.named_steps["tfidf"].vocabulary_
        assert not any("motdefuite" in mot for mot in vocabulaire)


# --- Reproductibilité ---------------------------------------------------------


def test_reproductible_avec_la_graine(tmp_path, export_synthetique):
    sorties = []
    for nom in ("a", "b"):
        _, entrainement, _, art = _monter(tmp_path / nom, export_synthetique)
        r = entrainement.executer(SuiviJournal(), ["svm_tfidf", "rl_emb"])
        sorties.append({c: (art.lire_matrice(f"{m['dossier']}/hors_pli.npy"), art.lire_matrice(f"{m['dossier']}/test.npy")) for c, m in r.modeles.items()})
        sorties[-1]["decoupage"] = art.lire_json(f"entrainement/{r.jeu['empreinte'][:16]}/decoupage.json")
    assert sorties[0]["decoupage"] == sorties[1]["decoupage"]
    for cle in ("svm_tfidf", "rl_emb"):
        assert np.array_equal(sorties[0][cle][0], sorties[1][cle][0])
        assert np.array_equal(sorties[0][cle][1], sorties[1][cle][1])


def test_parallele_identique_au_sequentiel(export_synthetique, tmp_path):
    corpus, entrainement, _, _ = _monter(tmp_path, export_synthetique)
    jeu = entrainement.preparer_jeu()
    defs = {"rl_tfidf": modeles_base.definitions()["rl_tfidf"]}
    y = jeu.y[jeu.entrainement]
    args = (defs, jeu.entrees(jeu.entrainement), y, jeu.plis, jeu.n_classes, 42, {})
    seq = rechercher_grilles(*args, n_processus=1)["rl_tfidf"]
    par = rechercher_grilles(*args, n_processus=2)["rl_tfidf"]
    assert np.allclose(seq.hors_pli, par.hors_pli) and seq.meilleur == par.meilleur


# --- Ordre des classes -------------------------------------------------------------


def test_aligner_remet_les_colonnes_dans_l_ordre_commun():
    probas = np.array([[0.7, 0.3]])
    sortie = aligner(probas, np.array([1, 3]), np.arange(4))
    assert sortie.tolist() == [[0.0, 0.7, 0.0, 0.3]]
    with pytest.raises(ValueError):
        aligner(probas, np.array([1, 9]), np.arange(4))


def test_ordre_des_classes_coherent_entre_modeles(monte):
    _, entrainement, _, art, resultat = monte
    jeu = entrainement.preparer_jeu()
    assert set(resultat.modeles) == {"svm_tfidf", "rl_tfidf", "svm_emb", "rl_emb", "knn_emb"}
    classes = art.lire_json(f"entrainement/{jeu.empreinte[:16]}/classes.json")
    assert classes == jeu.titres
    for cle, info in resultat.modeles.items():
        modele = art.lire_objet(f"{info['dossier']}/modele.joblib")
        test = art.lire_matrice(f"{info['dossier']}/test.npy")
        assert test.shape == (len(jeu.test), len(classes))
        assert np.allclose(test.sum(axis=1), 1, atol=1e-4)
        assert list(modele.classes_) == list(range(len(classes)))
        entree = jeu.entrees(jeu.test)["tfidf" if cle.endswith("tfidf") else "emb"]
        # La colonne de plus forte probabilité correspond à la classe prédite par le modèle.
        assert np.array_equal(test.argmax(axis=1), modele.predict(entree))


# --- Modes et combinaisons --------------------------------------------------------


def test_les_13_combinaisons_et_chaque_mode_tournent(monte):
    _, entrainement, evaluation, art, _ = monte
    r = evaluation.executer(SuiviJournal())
    assert len(r["classement"]) == 13
    for e in r["classement"]:
        assert 0 <= e["top1_test"] <= 1 and e["seuils"]["moyen"] <= e["seuils"]["haut"]
    manuelles = [
        Combinaison(Mode.SEUL, ("knn_emb",)),
        Combinaison(Mode.MOYENNE, ("rl_tfidf", "knn_emb", "svm_emb")),
        Combinaison(Mode.META, ("svm_tfidf", "knn_emb")),
    ]
    r2 = evaluation.executer(SuiviJournal(), manuelles)
    assert {e["nom"] for e in r2["classement"]} == {c.nom for c in manuelles}
    evaluation_gb = Evaluation(
        entrainement, DepotEvaluationsMemoire(), art, replace(evaluation.parametres, type_meta="gb")
    )
    r3 = evaluation_gb.executer(SuiviJournal(), [Combinaison(Mode.META, ("svm_tfidf", "rl_emb"))])
    assert r3["classement"][0]["top1_test"] > 0.5


def test_combinaison_sans_modele_entraine(tmp_path, export_synthetique):
    _, entrainement, evaluation, _ = _monter(tmp_path, export_synthetique)
    with pytest.raises(ModelesNonEntraines):
        evaluation.executer(SuiviJournal())
    entrainement.executer(SuiviJournal(), ["svm_tfidf"])
    with pytest.raises(ModelesNonEntraines):
        evaluation.executer(SuiviJournal(), [Combinaison(Mode.MOYENNE, ("svm_tfidf", "rl_tfidf"))])
    r = evaluation.executer(SuiviJournal())  # seules les combinaisons évaluables
    assert [e["nom"] for e in r["classement"]] == ["seul__svm_tfidf"]


def test_combinaisons_standard_et_validation():
    combis = combinaisons_standard("rl_tfidf", "knn_emb")
    assert len(combis) == 13 and len({c.nom for c in combis}) == 13
    assert sum(c.mode is Mode.SEUL for c in combis) == 5
    assert Combinaison(Mode.MOYENNE, ("rl_tfidf", "knn_emb")) in combis
    with pytest.raises(ValueError):
        Combinaison(Mode.SEUL, ("svm_tfidf", "rl_tfidf"))
    with pytest.raises(ValueError):
        Combinaison(Mode.META, ("svm_tfidf",))
    assert not Combinaison(Mode.SEUL, ("svm_tfidf",)).fait_appel_au_llm
    assert Combinaison(Mode.SEUL, ("rl_emb",)).fait_appel_au_llm


# --- Cache ------------------------------------------------------------------------


def test_entrainer_deux_fois_ne_recalcule_rien(tmp_path, export_synthetique, monkeypatch):
    _, entrainement, _, _ = _monter(tmp_path, export_synthetique)
    entrainement.executer(SuiviJournal(), ["svm_tfidf", "rl_emb"])
    import demandes.application.entrainer as module

    def interdit(*a, **k):
        raise AssertionError("aucun ajustement ne doit être relancé")

    monkeypatch.setattr(module, "rechercher_grilles", interdit)
    r = entrainement.executer(SuiviJournal(), ["svm_tfidf", "rl_emb"])
    assert all(m["en_cache"] for m in r.modeles.values())


def test_sans_vecteurs_la_branche_tfidf_tourne_seule(tmp_path, export_synthetique):
    corpus = DepotCorpusMemoire()
    fabriquer_chargeur(tmp_path, corpus=corpus).executer(export_synthetique, SuiviJournal())
    entrainement = Entrainement(
        corpus, DepotVecteursMemoire(), StockageFichiers(tmp_path / "a"),
        ParametresEntrainement(10, 0.2, 3, 42, 1, False, [256]), "aucune",
    )
    r = entrainement.executer(SuiviJournal())
    assert set(r.modeles) == {"svm_tfidf", "rl_tfidf"} and set(r.ignores) == {"svm_emb", "rl_emb", "knn_emb"}


# --- Briques ------------------------------------------------------------------------


def test_poids_de_la_moyenne_et_desaccord():
    y = np.array([0, 1, 0, 1])
    bon = np.array([[0.9, 0.1], [0.1, 0.9], [0.8, 0.2], [0.3, 0.7]])
    mauvais = np.array([[0.2, 0.8], [0.8, 0.2], [0.4, 0.6], [0.6, 0.4]])
    poids = regler_poids([bon, mauvais], y)
    assert poids[0] > poids[1] and abs(sum(poids) - 1) < 1e-9
    assert desaccord([bon, mauvais]).tolist() == [True, True, True, True]
    assert desaccord([bon]).tolist() == [False] * 4


def test_seuils_et_niveaux():
    rng = np.random.default_rng(0)
    y = rng.integers(0, 5, 2000)
    confiance = rng.uniform(0.2, 1.0, 2000)
    probas = np.full((2000, 5), 0.0)
    juste = rng.uniform(size=2000) < confiance  # plus la confiance est haute, plus c'est juste
    for i in range(2000):
        k = y[i] if juste[i] else (y[i] + 1) % 5
        probas[i] = (1 - confiance[i]) / 4
        probas[i, k] = confiance[i]
    seuils = choisir_seuils(probas, y, 0.9, 0.95)
    assert 0.8 <= seuils.haut <= 1.0 and seuils.moyen <= seuils.haut
    s = Seuils(0.8, 0.4)
    assert niveau_confiance(0.85, s) is Niveau.HAUT
    assert niveau_confiance(0.5, s) is Niveau.MOYEN
    assert niveau_confiance(0.3, s) is Niveau.AUCUN
    assert niveau_confiance(0.99, s, desaccord=True) is Niveau.AUCUN
    assert niveau_confiance(0.99, s, desaccord=True, desaccord_bloque=False) is Niveau.HAUT
    with pytest.raises(ValueError):
        Seuils(0.3, 0.6)


def test_plis_stratifies():
    y = np.repeat(np.arange(4), 10)
    for entr, val in plis(y, 5, 1):
        assert set(np.unique(y[val])) == {0, 1, 2, 3}
