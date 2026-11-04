"""Les ADR du dépôt sont scellés et intacts (ADR-0001), et l'outillage se comporte comme prévu."""

import shutil
from pathlib import Path

import pytest

from demandes import adr

RACINE = Path(__file__).resolve().parents[2]


def test_les_adr_du_depot_sont_scelles_et_intacts():
    erreurs, non_scelles = adr.verifier(RACINE / "docs/adr")
    assert not erreurs, erreurs
    assert not non_scelles, f"ADR à sceller : {non_scelles} (uv run demandes adr sceller)"


@pytest.fixture
def dossier(tmp_path):
    d = tmp_path / "adr"
    d.mkdir()
    (d / "0001-premiere.md").write_text("# ADR-0001 : Première\n\n- Date : 2026-01-01\n- Statut : Acceptée\n- Remplace : —\n")
    adr.sceller(d)
    return d


def test_modification_et_suppression_detectees(dossier):
    assert adr.verifier(dossier) == ([], [])
    (dossier / "0001-premiere.md").write_text("# ADR-0001 : Première, réécrite\n")
    erreurs, _ = adr.verifier(dossier)
    assert erreurs and "modifié" in erreurs[0]
    (dossier / "0001-premiere.md").unlink()
    erreurs, _ = adr.verifier(dossier)
    assert erreurs and "supprimé" in erreurs[0]


def test_sceller_ne_reecrit_pas_une_empreinte_existante(dossier):
    avant = adr.lire_empreintes(dossier)["0001-premiere.md"]
    (dossier / "0001-premiere.md").write_text("autre contenu")
    (dossier / "0002-seconde.md").write_text("# ADR-0002 : Seconde\n\n- Remplace : ADR-0001\n")
    assert adr.sceller(dossier) == ["0002-seconde.md"]
    assert adr.lire_empreintes(dossier)["0001-premiere.md"] == avant
    assert adr.verifier(dossier)[0]  # la modification de 0001 reste une erreur


def test_correction_de_forme_tracee(dossier):
    chemin = dossier / "0001-premiere.md"
    chemin.write_text(chemin.read_text().replace("Première", "Premiere"))
    with pytest.raises(ValueError):
        adr.corriger("1", "", dossier)
    adr.corriger("1", "coquille", dossier)
    assert adr.verifier(dossier) == ([], [])
    assert "coquille" in (dossier / "errata.md").read_text()


def test_index_calcule_les_remplacements(dossier):
    (dossier / "0002-seconde.md").write_text("# ADR-0002 : Seconde\n\n- Date : 2026-02-01\n- Remplace : ADR-0001\n")
    index = adr.generer_index(dossier).read_text()
    assert "| 0001 | [Première](0001-premiere.md) | 2026-01-01 | Remplacée par ADR-0002 |" in index
    assert "| 0002 | [Seconde](0002-seconde.md) | 2026-02-01 | Acceptée |" in index
