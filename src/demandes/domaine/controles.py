"""Contrôles d'une ligne brute : champs obligatoires, encodage, caractères interdits.

Fonctions pures, sans I/O. Les règles sont décrites dans l'ADR-0009.
"""

from __future__ import annotations

import re
from collections.abc import Iterable
from dataclasses import dataclass

from demandes.domaine.demande import LigneBrute, LigneEcartee, MotifEcart

# Séquences typiques d'un texte UTF-8 relu en Latin-1 / CP1252 (« Ã© » pour « é », « â€™ » pour « ’ »).
# Les octets de suite UTF-8 (0x80-0xBF) vus en Latin-1 ou en CP1252 :
_SUITE = "\u0080-¿ŒœŠšŸŽžƒˆ˜–-›€™"
# Têtes retenues : Ã, Â, Å (2 octets) et â (3 octets). On exclut volontairement les autres
# majuscules accentuées (É, È, Ê…) : « RÉSUMÉ : » avec espace insécable n'est pas un défaut.
_SEQUENCE = re.compile(f"[ÃÂÅ][{_SUITE}]|â[{_SUITE}]{{2}}")
# « à » = C3 A0 : relu « Ã » + espace insécable ; si l'insécable est devenue une espace ordinaire,
# la séquence « Ã » + espace représente « à » à elle seule (l'espace qui suit le mot reste).
_A_GRAVE_PERDU = re.compile("Ã ")


def _decoder(correspondance: re.Match[str]) -> str:
    sequence = correspondance.group()
    for codec in ("cp1252", "latin-1"):
        try:
            return sequence.encode(codec).decode("utf-8")
        except (UnicodeEncodeError, UnicodeDecodeError):
            continue
    return sequence


@dataclass(frozen=True, slots=True)
class TexteRepare:
    texte: str
    encodage_repare: bool
    nul_retires: int
    caracteres_inconnus: int  # U+FFFD restants : perte d'information non réparable


def reparer_texte(texte: str) -> TexteRepare:
    """Retire les NUL (refusés par PostgreSQL) et répare le double encodage UTF-8/Latin-1.

    La réparation se fait séquence par séquence : un mail en partie seulement
    cassé (une réponse collée sous un mail correct) est réparé sans toucher au reste.
    """
    nul = texte.count("\x00")
    if nul:
        texte = texte.replace("\x00", "")
    repare = _SEQUENCE.sub(_decoder, texte)
    if repare != texte:
        # Le texte est avéré cassé : on traite aussi le « à » dont l'insécable s'est perdue.
        repare = _A_GRAVE_PERDU.sub("à", repare)
    return TexteRepare(repare, repare != texte, nul, repare.count("�"))


def normaliser_champ(valeur: object) -> str | None:
    """Convertit une cellule en texte ; None si vide."""
    if valeur is None:
        return None
    if isinstance(valeur, float):
        if valeur != valeur:  # NaN
            return None
        if valeur.is_integer():
            valeur = int(valeur)  # un numéro lu « 12345.0 » redevient « 12345 »
    texte = str(valeur).strip()
    return texte or None


def ecarter_lignes(lignes: Iterable[LigneBrute]) -> tuple[list[LigneBrute], list[LigneEcartee]]:
    """Sépare les lignes exploitables des lignes écartées (avec motif).

    Pour un numéro en double, la première occurrence est gardée, les suivantes
    sont écartées.
    """
    gardees: list[LigneBrute] = []
    ecartees: list[LigneEcartee] = []
    vus: dict[str, int] = {}
    for ligne in lignes:
        if not ligne.numero:
            ecartees.append(LigneEcartee(ligne.ligne_source, None, MotifEcart.NUMERO_VIDE))
        elif not ligne.mail:
            ecartees.append(LigneEcartee(ligne.ligne_source, ligne.numero, MotifEcart.MAIL_VIDE))
        elif not ligne.titre:
            ecartees.append(LigneEcartee(ligne.ligne_source, ligne.numero, MotifEcart.TITRE_VIDE))
        elif ligne.numero in vus:
            ecartees.append(
                LigneEcartee(
                    ligne.ligne_source,
                    ligne.numero,
                    MotifEcart.NUMERO_EN_DOUBLE,
                    f"déjà vu ligne {vus[ligne.numero]}",
                )
            )
        else:
            vus[ligne.numero] = ligne.ligne_source
            gardees.append(ligne)
    return gardees, ecartees
