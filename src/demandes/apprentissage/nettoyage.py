"""Nettoyage du mail pour la branche TF-IDF.

On retire le HTML éventuel, les mentions légales automatiques et les espaces
superflus. On garde l'objet et l'en-tête : ils portent souvent le signal.
Fonctions pures, appelables en parallèle par lots.
"""

from __future__ import annotations

import html
import re

_BALISES_BLOC = re.compile(r"<\s*(br|/p|/div|/tr|/li|/h[1-6])\b[^>]*>", re.IGNORECASE)
_BALISES = re.compile(r"<[^>]+>")
_STYLE_SCRIPT = re.compile(r"<(style|script)\b.*?</\1\s*>", re.IGNORECASE | re.DOTALL)
_COMMENTAIRES = re.compile(r"<!--.*?-->", re.DOTALL)
_SEMBLE_HTML = re.compile(r"<\s*(html|body|div|p|br|table|span|td)\b", re.IGNORECASE)

# Début d'un paragraphe de mentions légales : tout ce qui suit est retiré.
_MENTIONS_LEGALES = re.compile(
    r"^\s*(?:"
    r"ce (?:message|courriel|mail|e-mail)(?: et (?:toutes? )?(?:les |ses )?pi[eè]ces? jointes?)? "
    r"(?:est|sont|peut|contient|et)"
    r"|this (?:e-?mail|message)(?: and any attachments?)? (?:is|are|may|contains)"
    r"|confidentialit[ée]\s*:"
    r"|avertissement\s*:"
    r"|disclaimer\s*:"
    r"|pensez [àa] l'environnement"
    r"|p\s*(?:avant|before) d'imprimer"
    r"|merci de penser [àa] l'environnement"
    r")",
    re.IGNORECASE | re.MULTILINE,
)
_ESPACES = re.compile(r"[ \t  -​ ]+")
_LIGNES_VIDES = re.compile(r"\n\s*\n+")
_OBJET = re.compile(r"^\s*(?:objet|subject|sujet)\s*:\s*(.*?)\s*$", re.IGNORECASE | re.MULTILINE)
_PREFIXES_OBJET = re.compile(r"^(?:\s*(?:re|tr|fw|fwd)\s*:\s*)+", re.IGNORECASE)


def retirer_html(texte: str) -> str:
    if not _SEMBLE_HTML.search(texte):
        return html.unescape(texte) if "&" in texte else texte
    texte = _COMMENTAIRES.sub(" ", texte)
    texte = _STYLE_SCRIPT.sub(" ", texte)
    texte = _BALISES_BLOC.sub("\n", texte)
    texte = _BALISES.sub(" ", texte)
    return html.unescape(texte)


def retirer_mentions_legales(texte: str) -> str:
    correspondance = _MENTIONS_LEGALES.search(texte)
    return texte[: correspondance.start()] if correspondance else texte


def normaliser_espaces(texte: str) -> str:
    texte = texte.replace("\r\n", "\n").replace("\r", "\n")
    lignes = [_ESPACES.sub(" ", ligne).strip() for ligne in texte.split("\n")]
    return _LIGNES_VIDES.sub("\n\n", "\n".join(lignes)).strip()


def nettoyer_mail(texte: str) -> str:
    """Texte prêt pour TF-IDF : sans HTML, sans mentions légales, espaces normalisés."""
    return normaliser_espaces(retirer_mentions_legales(retirer_html(texte)))


def extraire_objet(texte: str) -> str | None:
    """Objet du mail (première ligne « Objet : … » de l'en-tête), sans préfixes RE/TR."""
    correspondance = _OBJET.search(texte)
    if not correspondance:
        return None
    objet = _PREFIXES_OBJET.sub("", correspondance.group(1)).strip()
    return objet or None
