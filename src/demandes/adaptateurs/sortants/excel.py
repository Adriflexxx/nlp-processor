"""Lecture de l'export Excel (pandas + openpyxl)."""

from __future__ import annotations

from datetime import datetime
from pathlib import Path

import pandas as pd

from demandes.domaine.controles import normaliser_champ
from demandes.domaine.demande import LigneBrute
from demandes.ports.source_export import ColonnesManquantes


class SourceExcel:
    def lire(self, chemin: Path, mapping: dict[str, str], feuille: str | None = None) -> list[LigneBrute]:
        if not chemin.exists():
            raise FileNotFoundError(f"export introuvable : {chemin}")
        # Tout en texte (dtype=object) : un numéro ne doit pas devenir un flottant.
        df = pd.read_excel(chemin, sheet_name=feuille or 0, dtype=object, engine="openpyxl")
        colonnes = {str(c).strip(): c for c in df.columns}
        manquantes = [nom for nom in mapping if nom not in colonnes]
        if manquantes:
            raise ColonnesManquantes(
                f"colonnes absentes de l'export : {manquantes} ; colonnes présentes : {list(colonnes)}"
                " (réglez COLONNE_NUMERO, COLONNE_TITRE, COLONNE_MAIL, COLONNE_DATE dans le .env)"
            )
        interne = {mapping[nom]: colonnes[nom] for nom in mapping}

        dates: list[datetime | None]
        if "date" in interne:
            serie = pd.to_datetime(df[interne["date"]], errors="coerce", dayfirst=True)
            dates = [None if pd.isna(v) else v.to_pydatetime() for v in serie]
        else:
            dates = [None] * len(df)

        lignes: list[LigneBrute] = []
        for position, (_, rangee) in enumerate(df.iterrows()):
            mail = rangee[interne["mail"]]
            lignes.append(
                LigneBrute(
                    ligne_source=position + 2,  # ligne 1 = en-tête
                    numero=normaliser_champ(rangee[interne["numero"]]),
                    titre=normaliser_champ(rangee[interne["titre"]]),
                    # Le mail garde ses retours à la ligne : on ne retire que les blancs aux bords.
                    mail=None if normaliser_champ(mail) is None else str(mail).strip(),
                    date=dates[position],
                )
            )
        return lignes
