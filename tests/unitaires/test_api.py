"""API de bout en bout, avec des dépôts en mémoire (sans Docker)."""

import time
from functools import cached_property

import pytest
from fastapi.testclient import TestClient

from demandes.adaptateurs.entrants.api.app import creer_app
from demandes.adaptateurs.sortants.memoire import (
    DepotCorpusMemoire,
    DepotEvaluationsMemoire,
    DepotFichesMemoire,
    DepotPredictionsMemoire,
    DepotReferentielMemoire,
    DepotTachesMemoire,
    DepotVecteursMemoire,
)
from demandes.composition import Conteneur
from demandes.config import Settings


class ConteneurMemoire(Conteneur):
    def migrer(self):
        return []

    @property
    def pool(self):
        raise AssertionError("un test unitaire ne doit pas toucher PostgreSQL")

    @cached_property
    def depot_fiches(self):
        return DepotFichesMemoire()

    @cached_property
    def depot_evaluations(self):
        return DepotEvaluationsMemoire()

    @cached_property
    def depot_predictions(self):
        return DepotPredictionsMemoire()

    @cached_property
    def depot_vecteurs(self):
        return DepotVecteursMemoire()

    @cached_property
    def depot_corpus(self):
        return DepotCorpusMemoire()

    @cached_property
    def depot_referentiel(self):
        return DepotReferentielMemoire()

    @cached_property
    def depot_taches(self):
        return DepotTachesMemoire()


@pytest.fixture
def client(tmp_path):
    settings = Settings(
        _env_file=None,
        dossier_artefacts=str(tmp_path / "artefacts"),
        dossier_donnees=str(tmp_path / "donnees"),
        colonne_mail="description",
        colonne_date="date",
        mock_llm=True,
        emb_dimension=64,
        n_plis=3,
        n_jobs=1,
        acp_dimensions="16,64",
        mode="moyenne",
        modeles="svm_emb,rl_emb",
    )
    with TestClient(creer_app(ConteneurMemoire(settings))) as client:
        yield client


def _attendre(client, tache_id, delai=30):
    fin = time.monotonic() + delai
    while time.monotonic() < fin:
        tache = client.get(f"/taches/{tache_id}").json()
        if tache["statut"] in ("terminee", "echec"):
            return tache
        time.sleep(0.1)
    raise TimeoutError


def test_depot_chargement_suivi(client, export_synthetique):
    with export_synthetique.open("rb") as flux:
        reponse = client.post("/fichiers", files={"fichier": ("mon export.xlsx", flux)})
    assert reponse.status_code == 201
    chemin = reponse.json()["fichier"]
    assert chemin.endswith("mon_export.xlsx")
    assert client.get("/fichiers").json() == [chemin]

    reponse = client.post("/taches/charger", json={"fichier": chemin})
    assert reponse.status_code == 202
    tache = _attendre(client, reponse.json()["id"])
    assert tache["statut"] == "terminee", tache["erreur"]
    assert tache["resultat"]["chargement"]["nb_retenues"] == 404
    fiches = tache["resultat"]["fiches"]
    assert fiches["fiches_en_lot"] == 404 and fiches["vecteurs_calcules"] == 404
    assert fiches["modele_iag"].startswith("mock:")

    journal = client.get(f"/taches/{tache['id']}/journal").json()
    etapes = {e["etape"] for e in journal}
    assert {"lecture", "contrôles", "nettoyage", "templates", "cartographie", "enregistrement", "fiches", "embeddings"} <= etapes
    progressions = [e["progression"] for e in journal]
    assert progressions == sorted(progressions) and progressions[-1] == 1.0
    suite = client.get(f"/taches/{tache['id']}/journal", params={"apres": journal[-1]["id"]}).json()
    assert suite == []

    flux = client.get(f"/taches/{tache['id']}/flux").text
    assert "event: fin" in flux and "Ingestion terminée" in flux

    # Contrôle lot / unité, puis chargement sans fiches : aucun appel à l'IAG.
    controle = _attendre(client, client.post("/taches/controle-lots", json={"taille": 20}).json()["id"])
    assert controle["statut"] == "terminee" and controle["resultat"]["taille_echantillon"] == 20
    sans = _attendre(client, client.post("/taches/charger", json={"fichier": chemin, "avec_fiches": False}).json()["id"])
    assert sans["statut"] == "terminee" and "fiches" not in sans["resultat"]

    assert client.get("/corpus").json()["nb_retenues"] == 404
    assert len(client.get("/referentiel").json()) == 9


def test_chargement_en_echec_visible(client):
    tache = client.post("/taches/charger", json={"fichier": "introuvable.xlsx"}).json()
    tache = _attendre(client, tache["id"])
    assert tache["statut"] == "echec"
    assert "introuvable" in tache["erreur"]
    assert client.get("/taches/inconnue").status_code == 404


def test_parcours_complet_entrainer_evaluer_rapport_predire(client, export_synthetique):
    with export_synthetique.open("rb") as flux:
        chemin = client.post("/fichiers", files={"fichier": ("export.xlsx", flux)}).json()["fichier"]
    assert _attendre(client, client.post("/taches/charger", json={"fichier": chemin}).json()["id"])["statut"] == "terminee"
    assert client.post("/predire", json={"mail": "x"}).status_code == 409  # rien d'évalué encore

    entr = _attendre(client, client.post("/taches/entrainer", json={}).json()["id"], delai=120)
    assert entr["statut"] == "terminee", entr["erreur"]
    assert len(entr["resultat"]["modeles"]) == 5
    ev = _attendre(client, client.post("/taches/evaluer", json={}).json()["id"], delai=120)
    assert ev["statut"] == "terminee", ev["erreur"] and len(ev["resultat"]["classement"]) == 13
    assert len([e for e in client.get("/evaluations").json() if "test" in e]) == 13
    rap = _attendre(client, client.post("/taches/rapport").json()["id"], delai=60)
    assert rap["statut"] == "terminee", rap["erreur"]
    assert "## Recommandation" in client.get("/rapport").text

    p = client.post("/predire", json={"mail": "Objet : export FACTO\n\nL'export FACTO est vide, erreur."}).json()
    assert len(p["top3"]) == 3 and p["niveau"] in ("haut", "moyen", "aucun") and len(p["avis"]) == 2
    r = client.post(f"/predictions/{p['id']}/retour", json={"titre_retenu": p["top3"][0]["titre"], "operateur": "op"})
    assert r.status_code == 200 and r.json()["rang_dans_le_top3"] == 1
    assert client.get(f"/predictions/{p['id']}").json()["titre_retenu"] == p["top3"][0]["titre"]
    assert client.post("/predictions/999/retour", json={"titre_retenu": "X"}).status_code == 404
