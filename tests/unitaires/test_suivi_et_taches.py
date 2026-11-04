import pytest

from demandes.adaptateurs.sortants.memoire import DepotTachesMemoire
from demandes.adaptateurs.sortants.suivi_taches import SuiviTache
from demandes.application.taches import ExecuteurTaches, TypeTacheInconnu
from demandes.ports.suivi import SuiviJournal


def test_progression_globale():
    s = SuiviJournal()
    s.INTERVALLE_S = 0
    s.demarrer(["a", "b"])
    s.etape("a")
    s.avancer(5, 10)
    assert s.messages[-1][2] == pytest.approx(0.25)
    s.etape("b")
    s.avancer(10, 10)
    assert s.messages[-1][2] == pytest.approx(1.0)


def test_les_messages_de_progression_sont_limites():
    s = SuiviJournal()
    s.demarrer(["a"])
    s.etape("a")
    for i in range(1, 1001):
        s.avancer(i, 1000)
    # un premier message, puis plus rien pendant 1 s, sauf le dernier (fin d'étape)
    assert len([m for m in s.messages if "/1000" in m[1]]) <= 3


def _executeur(depot, actions):
    return ExecuteurTaches(depot, lambda tache_id: SuiviTache(depot, tache_id), actions)


def test_tache_reussie_et_journal():
    depot = DepotTachesMemoire()

    def action(parametres, suivi):
        suivi.demarrer(["calcul"])
        suivi.etape("calcul")
        suivi.info("en cours", x=1)
        return {"double": parametres["n"] * 2}

    tache, futur = _executeur(depot, {"calcul": action}).soumettre("calcul", {"n": 21})
    futur.result(timeout=5)
    lue = depot.lire(tache.id)
    assert lue.statut == "terminee" and lue.resultat == {"double": 42} and lue.progression == 1.0
    journal = depot.lire_journal(tache.id)
    assert [e.message for e in journal][-1] == "en cours"
    assert depot.lire_journal(tache.id, apres_id=journal[-1].id) == []


def test_tache_en_echec():
    depot = DepotTachesMemoire()

    def action(parametres, suivi):
        raise RuntimeError("panne")

    executeur = _executeur(depot, {"x": action})
    tache, futur = executeur.soumettre("x", {})
    futur.result(timeout=5)
    lue = depot.lire(tache.id)
    assert lue.statut == "echec" and "panne" in lue.erreur
    with pytest.raises(RuntimeError):
        executeur.executer_maintenant("x", {})
    with pytest.raises(TypeTacheInconnu):
        executeur.soumettre("inconnu", {})
