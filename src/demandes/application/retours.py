"""Boucle de retour : Titre retenu par l'opérateur, export pour le réentraînement (ADR-0017)."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import pandas as pd

from demandes.ports.depots import DepotPredictions


@dataclass(frozen=True, slots=True)
class ColonnesExport:
    numero: str
    titre: str
    mail: str
    date: str  # vide : pas de colonne date


class PredictionInconnue(KeyError):
    pass


class Retours:
    def __init__(self, predictions: DepotPredictions, colonnes: ColonnesExport) -> None:
        self.predictions = predictions
        self.colonnes = colonnes

    def enregistrer(self, prediction_id: int, titre_retenu: str, operateur: str | None = None) -> dict[str, Any]:
        titre = titre_retenu.strip()
        if not titre:
            raise ValueError("le Titre retenu est vide")
        if not self.predictions.enregistrer_retour(prediction_id, titre, operateur):
            raise PredictionInconnue(f"prédiction {prediction_id} inconnue")
        p = self.predictions.lire(prediction_id)
        propose = [t["titre"] for t in p.top3]
        return {
            "id": prediction_id,
            "titre_retenu": titre,
            "rang_dans_le_top3": propose.index(titre) + 1 if titre in propose else None,
            "niveau": p.niveau,
        }

    def exporter(self, chemin: Path, mois: int = 12) -> dict[str, Any]:
        """Prédictions avec retour sur les `mois` derniers mois, au format de l'export ITZME (rechargeable par `charger`)."""
        depuis = datetime.now(UTC) - timedelta(days=round(mois * 30.44))
        lignes = self.predictions.lister(depuis=depuis, avec_retour=True)
        c = self.colonnes
        donnees = []
        for p in lignes:
            ligne = {c.numero: f"PRED{p.id}", c.titre: p.titre_retenu, c.mail: p.mail}
            if c.date:
                ligne[c.date] = p.horodatage.replace(tzinfo=None)
            donnees.append(ligne)
        colonnes = [c.numero] + ([c.date] if c.date else []) + [c.titre, c.mail]
        chemin.parent.mkdir(parents=True, exist_ok=True)
        pd.DataFrame(donnees, columns=colonnes).to_excel(chemin, index=False)
        justes = sum(1 for p in lignes if p.top3 and p.top3[0]["titre"] == p.titre_retenu)
        return {
            "fichier": str(chemin),
            "n": len(lignes),
            "depuis": depuis.date().isoformat(),
            "exactitude_top1_en_production": justes / len(lignes) if lignes else None,
        }
