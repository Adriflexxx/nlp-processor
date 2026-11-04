from __future__ import annotations

from pathlib import Path

import pytest

from demandes.adaptateurs.sortants.excel import SourceExcel
from demandes.adaptateurs.sortants.fichiers import StockageFichiers
from demandes.adaptateurs.sortants.memoire import DepotCorpusMemoire, DepotReferentielMemoire
from demandes.application.charger import Chargeur, ParametresChargement
from demandes.apprentissage.templates import ParametresTemplates
from demandes.synthetique import ecrire_excel, generer_demandes

MAPPING = {"numero": "numero", "titre": "titre", "description": "mail", "date": "date"}


@pytest.fixture(scope="session")
def export_synthetique(tmp_path_factory) -> Path:
    return ecrire_excel(generer_demandes(400, 42), tmp_path_factory.mktemp("donnees") / "synthetique.xlsx")


def fabriquer_chargeur(tmp_path: Path, n_processus: int = 1, **surcharges) -> Chargeur:
    parametres = ParametresChargement(
        mapping=surcharges.pop("mapping", MAPPING),
        feuille=None,
        min_par_titre=surcharges.pop("min_par_titre", 10),
        templates=surcharges.pop("templates", ParametresTemplates()),
        n_processus=n_processus,
    )
    return Chargeur(
        SourceExcel(),
        surcharges.pop("corpus", DepotCorpusMemoire()),
        surcharges.pop("referentiel", DepotReferentielMemoire()),
        StockageFichiers(tmp_path / "artefacts"),
        parametres,
    )
