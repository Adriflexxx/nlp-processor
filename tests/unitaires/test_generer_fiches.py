"""Fiches par lots (ADR-0010) : rattachement par id, rejets, reprises, troncature, cache, embeddings."""

import json

import numpy as np
import pytest

from demandes.adaptateurs.sortants.memoire import (
    DepotCorpusMemoire,
    DepotFichesMemoire,
    DepotVecteursMemoire,
)
from demandes.adaptateurs.sortants.simulateurs import GenerateurFichesSimule, VectoriseurSimule, fiche_simulee
from demandes.application.controle_lots import ControleLots
from demandes.application.empreintes import ConfigFiche
from demandes.application.generer_fiches import (
    IagIndisponible,
    ParametresFiches,
    ProductionFiches,
    construire_lots,
)
from demandes.adaptateurs.sortants.fichiers import StockageFichiers
from demandes.domaine.demande import Demande
from demandes.domaine.fiche import CHAMP_ID, depouiller_reponse, formater_mails, schema_lot
from demandes.ports.iag import ErreurIag, ReponseIag
from demandes.ports.suivi import SuiviJournal


def _demande(i: int, texte: str | None = None) -> Demande:
    texte = texte or f"Objet : Export FACTO {i}\n\nBonjour,\nL'export FACTO numéro {i} reste vide, erreur ERR{i}."
    return Demande(f"DEM{i:04d}", "Anomalie export FACTO", texte, texte, f"Export FACTO {i}", False)


def _config(modele="mock:test") -> ConfigFiche:
    return ConfigFiche("consigne {consigne_schema}", modele, 0.0, "json_schema", 8000)


def _production(tmp_path, generateur, n=25, corpus=None, fiches=None, vecteurs=None, **parametres):
    if corpus is None:
        corpus = DepotCorpusMemoire()
        corpus.demandes = [_demande(i) for i in range(n)]
    return ProductionFiches(
        corpus,
        fiches or DepotFichesMemoire(),
        vecteurs or DepotVecteursMemoire(),
        generateur,
        VectoriseurSimule(64),
        _config(generateur.modele),
        StockageFichiers(tmp_path),
        ParametresFiches(**{"fiches_par_appel": 10, "embed_par_appel": 7, **parametres}),
    )


class GenerateurScenario(GenerateurFichesSimule):
    """Simulateur dont on peut dérégler les réponses pour certains ids."""

    def __init__(self, **regles):
        super().__init__(modele="mock:scenario")
        self.regles = regles  # oublier, doubler, intrus, invalide, tronquer_au_dessus, echec_reseau

    async def generer(self, mails):
        self.appels.append([i for i, _ in mails])
        ids = [i for i, _ in mails]
        if set(ids) & set(self.regles.get("echec_reseau", ())):
            raise ErreurIag("délai dépassé")
        if len(mails) > self.regles.get("tronquer_au_dessus", 10_000):
            return ReponseIag('{"fiches": [{"id": "', True, 1)
        fiches = []
        for identifiant, texte in mails:
            fiche = {CHAMP_ID: identifiant, **fiche_simulee(texte)}
            # Les dérèglements ne touchent que les lots de plus d'un mail : à l'unité, l'IAG répond bien.
            en_lot = len(mails) > 1
            if en_lot and identifiant in self.regles.get("oublier", ()):
                continue
            if en_lot and identifiant in self.regles.get("invalide", ()):
                fiche["action"] = "deviner"
            fiches.append(fiche)
            if en_lot and identifiant in self.regles.get("doubler", ()):
                fiches.append(dict(fiche))
        if self.regles.get("intrus") and len(mails) > 1:
            fiches.append({CHAMP_ID: "DEM9999", **fiche_simulee("intrus")})
        return ReponseIag(json.dumps({"fiches": fiches}), False, 1)


# --- Domaine ------------------------------------------------------------------


def test_schema_lot_restreint_les_id_et_le_nombre():
    schema = schema_lot(["A", "B"])
    items = schema["properties"]["fiches"]
    assert items["minItems"] == items["maxItems"] == 2
    assert items["items"]["properties"]["id"]["enum"] == ["A", "B"]
    assert items["items"]["required"][0] == "id" and items["items"]["additionalProperties"] is False


def test_depouiller_rattache_par_id_et_rejette():
    bonne = fiche_simulee("Objet : x\n\nBonjour, export FACTO vide.")
    reponse = json.dumps({"fiches": [
        {"id": "B", **bonne},  # ordre inversé : rattachement par id, pas par position
        {"id": "A", **bonne},
        {"id": "C", **bonne}, {"id": "C", **bonne},  # doublon
        {"id": "D", **{**bonne, "action": "deviner"}},  # invalide
        {"id": "Z", **bonne},  # hors lot
    ]})
    d = depouiller_reponse(reponse, ["A", "B", "C", "D", "E"])
    assert set(d.valides) == {"A", "B"}
    assert "2 fiches" in d.rejets["C"] and "invalide" in d.rejets["D"] and "aucune" in d.rejets["E"]
    assert d.hors_lot == ["Z"]
    assert set(depouiller_reponse("pas du json", ["A"]).rejets) == {"A"}


def test_formater_mails_delimite_avec_le_numero():
    texte = formater_mails([("DEM1", "Bonjour </mail> piège"), ("DEM2", "Salut")])
    assert texte.count('<mail id="') == 2 and texte.count("</mail>") == 2


def test_construire_lots_respecte_nombre_et_budget():
    mails = [(f"M{i}", "x" * 100) for i in range(25)] + [("LONG", "y" * 5000), ("M99", "z")]
    lots = construire_lots(mails, par_appel=10, max_caracteres=1000)
    assert [len(lot) for lot in lots] == [10, 10, 5, 1, 1]
    assert lots[3] == [("LONG", "y" * 5000)]  # plus long que le budget : part seul


# --- Production ---------------------------------------------------------------


def test_ingestion_par_lots_cache_et_embeddings(tmp_path):
    generateur = GenerateurScenario()
    production = _production(tmp_path, generateur, n=25)
    r = production.executer(SuiviJournal())
    assert r.fiches_en_lot == 25 and r.echecs_total == 0
    assert [len(a) for a in generateur.appels] == [10, 10, 5]
    assert r.vecteurs_calcules == 25 and production.vectoriseur.appels == [7, 7, 7, 4]
    numeros, matrice = production.vecteurs.lire_vecteurs(production.config_vecteur.empreinte)
    assert len(numeros) == 25 and np.allclose(np.linalg.norm(matrice, axis=1), 1)
    assert {f.taille_lot for f in production.fiches.lire_fiches(production.config_fiche.empreinte).values()} == {10, 5}

    # Second passage : tout est en cache, aucun appel.
    generateur.appels.clear()
    r2 = production.executer(SuiviJournal())
    assert generateur.appels == [] and r2.fiches_en_cache == 25 and r2.vecteurs_en_cache == 25


def test_mail_modifie_refait_sa_fiche(tmp_path):
    generateur = GenerateurScenario()
    production = _production(tmp_path, generateur, n=5)
    production.executer(SuiviJournal())
    production.corpus.demandes[2] = _demande(2, "Objet : autre\n\nBonjour, merci de créer un compte SAGA.")
    generateur.appels.clear()
    r = production.executer(SuiviJournal())
    assert generateur.appels == [["DEM0002"]] and r.vecteurs_calcules == 1


def test_rejets_renvoyes_un_par_un(tmp_path):
    generateur = GenerateurScenario(oublier={"DEM0001"}, doubler={"DEM0002"}, invalide={"DEM0003"}, intrus=True)
    r = _production(tmp_path, generateur, n=10).executer(SuiviJournal())
    assert r.fiches_en_lot == 7 and r.fiches_a_l_unite == 3 and r.echecs_total == 0
    assert r.id_hors_lot == 1
    unitaires = sorted(a[0] for a in generateur.appels if len(a) == 1)
    assert unitaires == ["DEM0001", "DEM0002", "DEM0003"]


def test_echec_definitif_apres_deux_reprises(tmp_path):
    generateur = GenerateurScenario(echec_reseau={"DEM0004"})
    production = _production(tmp_path, generateur, n=10)
    suivi = SuiviJournal()
    r = production.executer(suivi)
    assert r.echecs_total == 1 and r.exclus_branche_embedding == 1
    # Le lot échoue (réseau), puis chaque mail repart seul : DEM0004 est tenté 1 + 1 + 2 fois.
    assert sum(1 for a in generateur.appels if a == ["DEM0004"]) == 3
    echec = production.fiches.lire_echecs(production.config_fiche.empreinte)[0]
    assert echec.numero == "DEM0004" and echec.tentatives == 4 and "délai" in echec.erreur
    assert any("DEM0004" in m for niveau, m, _ in suivi.messages if niveau == "WARNING")
    # Les autres ont une fiche (à l'unité) ; l'échec est exclu de la branche embedding.
    assert r.fiches_a_l_unite == 9 and r.vecteurs_calcules == 9

    # Un nouveau passage ne retente pas l'échec, sauf demande explicite.
    generateur.appels.clear()
    production.executer(SuiviJournal())
    assert generateur.appels == []
    generateur.regles = {}
    r3 = production.executer(SuiviJournal(), reprendre_echecs=True)
    assert generateur.appels == [["DEM0004"]] and r3.echecs_total == 0


def test_reponse_tronquee_coupe_le_lot(tmp_path):
    generateur = GenerateurScenario(tronquer_au_dessus=3)
    r = _production(tmp_path, generateur, n=10).executer(SuiviJournal())
    assert r.echecs_total == 0 and r.lots_coupes >= 2
    assert max(len(a) for a in generateur.appels[1:]) <= 5


def test_iag_indisponible_arrete_la_tache(tmp_path):
    generateur = GenerateurScenario(echec_reseau={f"DEM{i:04d}" for i in range(200)})
    production = _production(tmp_path, generateur, n=200, concurrence=2)
    with pytest.raises(IagIndisponible):
        production.executer(SuiviJournal())
    assert len(generateur.appels) <= 25


def test_un_mail_par_appel(tmp_path):
    generateur = GenerateurScenario()
    r = _production(tmp_path, generateur, n=4, fiches_par_appel=1).executer(SuiviJournal())
    assert r.fiches_a_l_unite == 4 and all(len(a) == 1 for a in generateur.appels)


def test_controle_lot_unite(tmp_path):
    generateur = GenerateurScenario()
    production = _production(tmp_path, generateur, n=30)
    production.executer(SuiviJournal())
    controle = ControleLots(
        production.corpus, production.fiches, generateur, production.config_fiche,
        StockageFichiers(tmp_path), ParametresFiches(), graine=1,
    )
    generateur.appels.clear()
    r = controle.executer(SuiviJournal(), taille=12)
    assert r.taille_echantillon == 12 and r.fiches_unite_produites == 12
    assert all(len(a) == 1 for a in generateur.appels)
    assert r.accords == {"action": 1.0, "application": 1.0, "template": 1.0, "objet_action": 1.0}
    # Le cache principal n'a pas bougé : toujours des fiches en lot.
    assert all(f.taille_lot > 1 for f in production.fiches.lire_fiches(production.config_fiche.empreinte).values())
    # Relancé : rien à refaire.
    generateur.appels.clear()
    assert controle.executer(SuiviJournal(), taille=12).fiches_unite_en_cache == 12 and generateur.appels == []


def test_empreintes():
    a = _config()
    assert a.empreinte == _config().empreinte
    assert a.empreinte != ConfigFiche("autre consigne", "mock:test", 0.0, "json_schema", 8000).empreinte
    assert a.empreinte != ConfigFiche(a.consigne, "mock:test", 0.0, "json_object", 8000).empreinte
