"""Intégration PostgreSQL : nécessite `docker compose up -d postgres`. Lancer : uv run pytest -m postgres"""

import os

import pytest

from demandes.adaptateurs.sortants.postgres.connexion import creer_pool, migrer
from demandes.adaptateurs.sortants.postgres.depots import (
    DepotCorpusPostgres,
    DepotReferentielPostgres,
    DepotTachesPostgres,
)
from demandes.adaptateurs.sortants.suivi_taches import SuiviTache
from tests.conftest import fabriquer_chargeur

pytestmark = pytest.mark.postgres

URL = os.environ.get("DATABASE_URL_TEST", "postgresql://demandes:demandes@localhost:5433/demandes_test")


@pytest.fixture(scope="module")
def pool():
    import psycopg

    admin = URL.rsplit("/", 1)[0] + "/demandes"
    nom = URL.rsplit("/", 1)[1]
    with psycopg.connect(admin, autocommit=True) as cnx:
        cnx.execute(f'DROP DATABASE IF EXISTS "{nom}" WITH (FORCE)')
        cnx.execute(f'CREATE DATABASE "{nom}"')
    p = creer_pool(URL)
    assert migrer(p)  # première application
    assert migrer(p) == []  # idempotent
    yield p
    p.close()


def test_chargement_en_base(tmp_path, export_synthetique, pool):
    corpus, referentiel, taches = DepotCorpusPostgres(pool), DepotReferentielPostgres(pool), DepotTachesPostgres(pool)
    tache = taches.creer("charger", {"fichier": str(export_synthetique)})
    taches.demarrer(tache.id)
    chargeur = fabriquer_chargeur(tmp_path, corpus=corpus, referentiel=referentiel)
    resultat = chargeur.executer(export_synthetique, SuiviTache(taches, tache.id))
    taches.terminer(tache.id, resultat.en_dict())

    demandes = corpus.lister_demandes()
    assert len(demandes) == resultat.nb_retenues == 404
    assert corpus.dernier_import().nb_ecartees == 3
    assert len(referentiel.lire_reference()) == 9
    assert all("\x00" not in d.mail for d in demandes)
    assert any(d.template for d in demandes) and any(d.marqueurs_template for d in demandes)

    lue = taches.lire(tache.id)
    assert lue.statut == "terminee" and lue.progression == 1.0
    assert len(taches.lire_journal(tache.id)) >= 6

    # Second chargement : le corpus est remplacé, pas cumulé.
    chargeur.executer(export_synthetique, SuiviTache(taches, tache.id))
    assert len(corpus.lister_demandes()) == 404


def test_fiches_et_vecteurs_en_base(tmp_path, export_synthetique, pool):
    from demandes.adaptateurs.sortants.fichiers import StockageFichiers
    from demandes.adaptateurs.sortants.postgres.depots_fiches import DepotFichesPostgres, DepotVecteursPostgres
    from demandes.adaptateurs.sortants.simulateurs import GenerateurFichesSimule, VectoriseurSimule
    from demandes.application.controle_lots import ControleLots
    from demandes.application.empreintes import ConfigFiche
    from demandes.application.generer_fiches import ParametresFiches, ProductionFiches
    from demandes.ports.suivi import SuiviJournal

    corpus = DepotCorpusPostgres(pool)
    fabriquer_chargeur(tmp_path, corpus=corpus, referentiel=DepotReferentielPostgres(pool)).executer(
        export_synthetique, SuiviJournal()
    )
    generateur = GenerateurFichesSimule()
    fiches, vecteurs = DepotFichesPostgres(pool), DepotVecteursPostgres(pool)
    config = ConfigFiche("consigne", generateur.modele, 0.0, "json_schema", 8000)
    production = ProductionFiches(
        corpus, fiches, vecteurs, generateur, VectoriseurSimule(1024), config, StockageFichiers(tmp_path),
        ParametresFiches(fiches_par_appel=10, embed_par_appel=100),
    )
    r = production.executer(SuiviJournal())
    assert r.fiches_en_lot == 404 and r.vecteurs_calcules == 404 and r.echecs_total == 0

    numeros, matrice = vecteurs.lire_vecteurs(production.config_vecteur.empreinte)
    assert len(numeros) == 404 and matrice.shape == (404, 1024) and str(matrice.dtype) == "float32"
    assert fiches.lire_fiches(config.empreinte, ["DEM100000"])["DEM100000"].taille_lot == 10

    generateur.appels.clear()
    r2 = production.executer(SuiviJournal())
    assert generateur.appels == [] and r2.fiches_en_cache == 404 and r2.vecteurs_en_cache == 404

    controle = ControleLots(corpus, fiches, generateur, config, StockageFichiers(tmp_path), ParametresFiches(), 42)
    rc = controle.executer(SuiviJournal(), taille=15)
    assert rc.fiches_unite_produites == 15 and rc.accords["action"] == 1.0
    assert len(fiches.lire_controle(config.empreinte)) == 15
    with pool.connection() as cnx:
        assert cnx.execute("SELECT count(*) FROM configurations").fetchone()[0] == 2


def test_evaluations_et_predictions_en_base(pool):
    from demandes.adaptateurs.sortants.postgres.depots_evaluation import DepotEvaluationsPostgres, DepotPredictionsPostgres

    evals = DepotEvaluationsPostgres(pool)
    evals.enregistrer_evaluation("jeu1", "seul__svm_tfidf", {"test": {"ensemble": {"top1": 0.9}}})
    evals.enregistrer_evaluation("jeu1", "seul__svm_tfidf", {"test": {"ensemble": {"top1": 0.91}}})  # remplace
    evals.enregistrer_evaluation("jeu2", "temporel", {"n_test": 10})
    assert [e["nom"] for e in evals.lister_evaluations()] == ["temporel"]  # dernier jeu évalué
    assert evals.lister_evaluations("jeu1")[0]["test"]["ensemble"]["top1"] == 0.91

    preds = DepotPredictionsPostgres(pool)
    i = preds.journaliser("mail", {"nom": "x"}, [{"titre": "T", "probabilite": 0.9}], "haut", [])
    assert preds.lister(avec_retour=True) == [] and preds.enregistrer_retour(i, "T", "op")
    assert not preds.enregistrer_retour(10**9, "T", None)
    lue = preds.lire(i)
    assert lue.titre_retenu == "T" and lue.operateur == "op" and lue.retenu_le is not None
    assert [p.id for p in preds.lister(avec_retour=True)] == [i]
