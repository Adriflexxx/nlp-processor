"""Outillage des ADR immuables (ADR-0001). Bibliothèque standard uniquement : le hook git l'appelle sans dépendances.

- `sceller` enregistre l'empreinte des nouveaux ADR, sans jamais toucher aux empreintes existantes ;
- `verifier` signale tout ADR modifié, supprimé ou pas encore scellé ;
- `corriger` accepte une correction de forme d'un ADR existant et la trace dans errata.md ;
- `generer_index` écrit docs/adr/README.md avec les statuts calculés (remplacements).
"""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass
from datetime import date
from pathlib import Path

DOSSIER_ADR = Path("docs/adr")
FICHIER_EMPREINTES = "empreintes.sha256"
FICHIER_ERRATA = "errata.md"
_NOM_ADR = re.compile(r"^(\d{4})-[\w-]+\.md$")
_TITRE = re.compile(r"^#\s*ADR-(\d{4})\s*:\s*(.+)$", re.MULTILINE)
_CHAMP = re.compile(r"^-\s*(Date|Statut|Remplace)\s*:\s*(.+)$", re.MULTILINE | re.IGNORECASE)


@dataclass(frozen=True, slots=True)
class Adr:
    numero: str
    fichier: str
    titre: str
    date: str
    statut: str
    remplace: tuple[str, ...]


def _empreinte(chemin: Path) -> str:
    # Normalisation des fins de ligne : un passage Windows/Linux n'est pas une modification.
    return hashlib.sha256(chemin.read_bytes().replace(b"\r\n", b"\n")).hexdigest()


def fichiers_adr(dossier: Path = DOSSIER_ADR) -> list[Path]:
    return sorted(p for p in dossier.glob("*.md") if _NOM_ADR.match(p.name))


def lire_empreintes(dossier: Path = DOSSIER_ADR) -> dict[str, str]:
    chemin = dossier / FICHIER_EMPREINTES
    if not chemin.exists():
        return {}
    empreintes = {}
    for ligne in chemin.read_text(encoding="utf-8").splitlines():
        if ligne.strip() and not ligne.startswith("#"):
            valeur, nom = ligne.split(maxsplit=1)
            empreintes[nom.strip()] = valeur
    return empreintes


def _ecrire_empreintes(empreintes: dict[str, str], dossier: Path) -> None:
    lignes = ["# Empreintes SHA-256 des ADR. Ne pas éditer à la main : demandes adr sceller / corriger."]
    lignes += [f"{empreintes[nom]}  {nom}" for nom in sorted(empreintes)]
    (dossier / FICHIER_EMPREINTES).write_text("\n".join(lignes) + "\n", encoding="utf-8")


def verifier(dossier: Path = DOSSIER_ADR) -> tuple[list[str], list[str]]:
    """Renvoie (erreurs, non_scelles). Une erreur = un ADR scellé modifié ou supprimé."""
    empreintes = lire_empreintes(dossier)
    presents = {p.name: p for p in fichiers_adr(dossier)}
    erreurs, non_scelles = [], []
    for nom, chemin in presents.items():
        if nom not in empreintes:
            non_scelles.append(nom)
        elif _empreinte(chemin) != empreintes[nom]:
            erreurs.append(
                f"{nom} a été modifié. Un ADR est immuable : écrivez un nouvel ADR qui le remplace, "
                f"ou, pour une simple correction de forme : demandes adr corriger {nom[:4]} --motif \"…\""
            )
    for nom in empreintes:
        if nom not in presents:
            erreurs.append(f"{nom} a été supprimé ; un ADR ne se supprime pas, il se remplace.")
    return erreurs, non_scelles


def sceller(dossier: Path = DOSSIER_ADR) -> list[str]:
    """Scelle les ADR qui n'ont pas encore d'empreinte ; renvoie leurs noms."""
    empreintes = lire_empreintes(dossier)
    nouveaux = [p for p in fichiers_adr(dossier) if p.name not in empreintes]
    for chemin in nouveaux:
        empreintes[chemin.name] = _empreinte(chemin)
    if nouveaux:
        _ecrire_empreintes(empreintes, dossier)
    return [p.name for p in nouveaux]


def corriger(numero: str, motif: str, dossier: Path = DOSSIER_ADR) -> str:
    """Accepte une correction de forme sur un ADR scellé, et la trace dans errata.md."""
    if not motif.strip():
        raise ValueError("le motif de la correction est obligatoire")
    candidats = [p for p in fichiers_adr(dossier) if p.name.startswith(f"{int(numero):04d}-")]
    if not candidats:
        raise FileNotFoundError(f"aucun ADR numéro {numero}")
    chemin = candidats[0]
    empreintes = lire_empreintes(dossier)
    ancienne, nouvelle = empreintes.get(chemin.name, "—"), _empreinte(chemin)
    if ancienne == nouvelle:
        raise ValueError(f"{chemin.name} n'a pas changé")
    empreintes[chemin.name] = nouvelle
    _ecrire_empreintes(empreintes, dossier)
    errata = dossier / FICHIER_ERRATA
    if not errata.exists():
        errata.write_text(
            "# Errata des ADR\n\nCorrections de forme acceptées sur des ADR scellés (le fond ne change pas).\n\n"
            "| Date | ADR | Motif | Empreinte avant | Empreinte après |\n|---|---|---|---|---|\n",
            encoding="utf-8",
        )
    with errata.open("a", encoding="utf-8") as flux:
        flux.write(f"| {date.today().isoformat()} | {chemin.name} | {motif.strip()} | `{ancienne[:12]}` | `{nouvelle[:12]}` |\n")
    return chemin.name


def lire_adr(chemin: Path) -> Adr:
    texte = chemin.read_text(encoding="utf-8")
    titre = _TITRE.search(texte)
    champs = {cle.lower(): valeur.strip() for cle, valeur in _CHAMP.findall(texte)}
    remplace = tuple(re.findall(r"ADR-(\d{4})", champs.get("remplace", "")))
    return Adr(
        numero=chemin.name[:4],
        fichier=chemin.name,
        titre=titre.group(2).strip() if titre else chemin.stem,
        date=champs.get("date", ""),
        statut=champs.get("statut", "Acceptée"),
        remplace=remplace,
    )


def generer_index(dossier: Path = DOSSIER_ADR) -> Path:
    adrs = [lire_adr(p) for p in fichiers_adr(dossier)]
    remplacee_par: dict[str, list[str]] = {}
    for adr in adrs:
        for ancien in adr.remplace:
            remplacee_par.setdefault(ancien, []).append(adr.numero)
    lignes = [
        "# Registre des décisions d'architecture (ADR)",
        "",
        "Fichier généré par `demandes adr index` : ne pas éditer à la main.",
        "",
        "Un ADR est **immuable** une fois scellé. Pour revenir sur une décision, on écrit un nouvel ADR",
        "avec `- Remplace : ADR-NNNN` ; le statut ci-dessous est calculé à partir de ces remplacements.",
        "Les corrections de forme sont tracées dans [errata.md](errata.md).",
        "",
        "| N° | Titre | Date | Statut |",
        "|---|---|---|---|",
    ]
    for adr in adrs:
        statut = adr.statut
        if adr.numero in remplacee_par:
            statut = "Remplacée par " + ", ".join(f"ADR-{n}" for n in remplacee_par[adr.numero])
        lignes.append(f"| {adr.numero} | [{adr.titre}]({adr.fichier}) | {adr.date} | {statut} |")
    chemin = dossier / "README.md"
    chemin.write_text("\n".join(lignes) + "\n", encoding="utf-8")
    return chemin


def prochain_numero(dossier: Path = DOSSIER_ADR) -> str:
    numeros = [int(p.name[:4]) for p in fichiers_adr(dossier)]
    return f"{max(numeros, default=0) + 1:04d}"
