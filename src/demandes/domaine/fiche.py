"""Fiche d'une demande produite par l'IAG à partir du mail reçu (ADR-0006).

`SCHEMA_FICHE` est défini une seule fois ici : il sert au décodage guidé
(`response_format`) et à la validation de chaque réponse.
"""

from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from copy import deepcopy
from dataclasses import dataclass
from typing import Any

from jsonschema import Draft202012Validator

ACTIONS = (
    "creer",
    "modifier",
    "supprimer",
    "donner_acces",
    "retirer_acces",
    "signaler",
    "demander_information",
    "autre",
)

SCHEMA_FICHE: dict[str, Any] = {
    "type": "object",
    "additionalProperties": False,
    "required": [
        "objet_origine",
        "template",
        "marqueurs_template",
        "application",
        "action",
        "objet_action",
        "elements_discriminants",
        "resume",
    ],
    "properties": {
        "objet_origine": {"type": "string", "description": "Objet du mail tel quel."},
        "template": {"type": "boolean", "description": "Le mail suit-il un template de la société."},
        "marqueurs_template": {
            "type": "array",
            "items": {"type": "string"},
            "description": "Formulations fixes repérées, [] si aucune.",
        },
        "application": {
            "type": "string",
            "description": "Application ou périmètre concerné, \"inconnu\" si absent.",
        },
        "action": {"type": "string", "enum": list(ACTIONS)},
        "objet_action": {"type": "string", "description": "Sur quoi porte l'action."},
        "elements_discriminants": {
            "type": "array",
            "items": {"type": "string"},
            "minItems": 1,
            "maxItems": 5,
            "description": "1 à 5 éléments qui distinguent cette demande.",
        },
        "resume": {"type": "string", "description": "2 phrases maximum."},
    },
}

NOM_SCHEMA = "fiche_demande"

#: Version de la concaténation : entre dans l'empreinte des vecteurs (ADR-0007).
VERSION_TEXTE = 1


CHAMP_ID = "id"


def schema_lot(ids: Sequence[str]) -> dict[str, Any]:
    """Schéma de réponse d'un appel : {"fiches": [{"id", ...SCHEMA_FICHE}]} (ADR-0010).

    Construit pour chaque lot à partir de SCHEMA_FICHE : l'id est restreint aux
    numéros du lot (le décodage guidé ne peut pas en inventer) et le nombre de
    fiches est fixé à la taille du lot.
    """
    fiche = deepcopy(SCHEMA_FICHE)
    fiche["properties"] = {CHAMP_ID: {"type": "string", "enum": list(ids)}, **fiche["properties"]}
    fiche["required"] = [CHAMP_ID, *fiche["required"]]
    return {
        "type": "object",
        "additionalProperties": False,
        "required": ["fiches"],
        "properties": {
            "fiches": {"type": "array", "items": fiche, "minItems": len(ids), "maxItems": len(ids)},
        },
    }


_VALIDATEUR = Draft202012Validator(SCHEMA_FICHE)


def erreurs_fiche(fiche: Any) -> list[str]:
    """Écarts d'une fiche (sans son id) au SCHEMA_FICHE ; liste vide si elle est valide."""
    return [f"{'/'.join(map(str, e.path)) or 'racine'} : {e.message}" for e in _VALIDATEUR.iter_errors(fiche)]


@dataclass(frozen=True, slots=True)
class DepouillementLot:
    """Résultat du contrôle d'une réponse : fiches valides rattachées par id, rejets motivés."""

    valides: dict[str, dict[str, Any]]
    rejets: dict[str, str]  # id du lot → motif (fiche absente, invalide, en double)
    hors_lot: list[str]  # id renvoyés qui n'appartiennent pas au lot


def depouiller_reponse(contenu: str | None, ids: Sequence[str]) -> DepouillementLot:
    """Contrôle une réponse de l'IAG. Une fiche est rattachée par son id, jamais par sa position."""
    attendus = list(ids)
    try:
        donnees = json.loads(contenu or "")
    except json.JSONDecodeError as erreur:
        return DepouillementLot({}, {i: f"JSON illisible : {erreur.msg}" for i in attendus}, [])
    fiches = donnees.get("fiches") if isinstance(donnees, dict) else None
    if not isinstance(fiches, list):
        return DepouillementLot({}, {i: "réponse sans liste « fiches »" for i in attendus}, [])

    par_id: dict[str, list[Any]] = {}
    hors_lot: list[str] = []
    for element in fiches:
        identifiant = element.get(CHAMP_ID) if isinstance(element, dict) else None
        if identifiant in attendus:
            par_id.setdefault(identifiant, []).append(element)
        else:
            hors_lot.append(str(identifiant))

    valides: dict[str, dict[str, Any]] = {}
    rejets: dict[str, str] = {}
    for identifiant in attendus:
        candidats = par_id.get(identifiant, [])
        if not candidats:
            rejets[identifiant] = "aucune fiche pour cet id"
        elif len(candidats) > 1:
            rejets[identifiant] = f"{len(candidats)} fiches pour le même id"
        else:
            fiche = {k: v for k, v in candidats[0].items() if k != CHAMP_ID}
            erreurs = erreurs_fiche(fiche)
            if erreurs:
                rejets[identifiant] = "fiche invalide : " + " ; ".join(erreurs[:3])
            else:
                valides[identifiant] = fiche
    return DepouillementLot(valides, rejets, hors_lot)


def formater_mails(mails: Sequence[tuple[str, str]]) -> str:
    """Message utilisateur d'un appel : chaque mail délimité avec son numéro."""
    blocs = []
    for identifiant, texte in mails:
        # Un « </mail> » dans le texte fermerait la balise trop tôt.
        texte = texte.replace("</mail>", "</ mail>")
        blocs.append(f'<mail id="{identifiant}">\n{texte}\n</mail>')
    return "\n\n".join(blocs)


def texte_a_vectoriser(fiche: Mapping[str, Any]) -> str:
    """Concaténation des champs utiles, toujours dans le même ordre (ADR-0006)."""
    elements = fiche.get("elements_discriminants") or []
    morceaux = [
        ("Objet", fiche.get("objet_origine", "")),
        ("Application", fiche.get("application", "")),
        ("Action", fiche.get("action", "")),
        ("Objet de l'action", fiche.get("objet_action", "")),
        ("Éléments", " ; ".join(str(e) for e in elements)),
        ("Résumé", fiche.get("resume", "")),
    ]
    return "\n".join(f"{libelle} : {str(valeur).strip()}" for libelle, valeur in morceaux if str(valeur).strip())
