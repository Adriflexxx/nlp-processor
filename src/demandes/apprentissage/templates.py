"""Repérage des mails issus d'un template de la société.

Principe (ADR-0009) : un template laisse des formulations fixes qui
reviennent à l'identique d'un mail à l'autre (« Nom du demandeur : »,
« Type de demande : », phrase d'introduction du formulaire…).

1. Pour chaque mail, on extrait des lignes candidates, prises dans le corps
   seulement : on saute l'en-tête et on s'arrête à la formule de politesse
   finale, pour que les signatures (qui se répètent aussi) ne comptent pas.
   Une ligne « libellé : valeur » est réduite à son libellé.
2. Une candidate devient un marqueur si elle revient dans au moins
   `min_mails` mails et dans au plus `freq_max` du corpus.
3. Un mail est un template s'il porte au moins `min_marqueurs` marqueurs
   distincts, s'il correspond à un motif configuré, ou (option) si son objet
   revient à l'identique dans au moins `min_mails` mails ET qu'il porte au
   moins un marqueur : un objet libre fréquent (« Demande FACTO ») ne suffit pas.
"""

from __future__ import annotations

import re
import unicodedata
from collections import Counter
from collections.abc import Sequence
from dataclasses import dataclass

from demandes.parallele import map_par_lots

_ENTETE = re.compile(
    r"^(?:de|à|a|cc|cci|objet|sujet|envoy[ée]|date|from|to|sent|subject|importance|exp[ée]diteur|destinataire)\s*:",
    re.IGNORECASE,
)
_FORMULE_FINALE = re.compile(
    r"^(?:bien |tr[eè]s )?cordialement|^bien [àa] (?:vous|toi)|^salutations|^sinc[eè]res salutations"
    r"|^(?:best )?regards|^bonne (?:journ[ée]e|soir[ée]e)|^merci (?:d'avance|par avance)\s*[.,!]?\s*$",
    re.IGNORECASE,
)
_LIBELLES_BANALS = {
    "tel", "tél", "téléphone", "telephone", "mobile", "portable", "fax", "email", "e-mail", "mail",
    "adresse", "site", "web", "bonjour", "bonsoir", "hello", "merci", "nb", "ps", "pj", "rappel",
}
MOTS_MAX_LIBELLE = 6
_LIGNES_BANALES = re.compile(r"^(?:bonjour|bonsoir|hello|madame|monsieur|merci|cordialement)\b", re.IGNORECASE)


@dataclass(frozen=True, slots=True)
class ParametresTemplates:
    min_mails: int = 5
    freq_max: float = 0.30
    min_marqueurs: int = 2
    utiliser_objet: bool = True
    motifs: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class ResultatTemplate:
    template: bool
    marqueurs: tuple[str, ...]
    raison: str  # "marqueurs", "objet", "motif" ou ""


def _normaliser(ligne: str) -> str:
    ligne = unicodedata.normalize("NFC", ligne).lower()
    ligne = re.sub(r"\s+", " ", ligne).strip()
    return ligne.strip(" .;,-_*•>")


def _normaliser_objet(objet: str | None) -> str | None:
    if not objet:
        return None
    objet = _normaliser(objet)
    return objet if len(objet) >= 4 else None


def lignes_candidates(texte: str) -> frozenset[str]:
    """Lignes du corps susceptibles d'appartenir à un template (normalisées)."""
    candidates: set[str] = set()
    lignes = texte.split("\n")
    i = 0
    # Saut de l'en-tête : lignes « De : », « Objet : »… et lignes vides au début.
    while i < len(lignes) and (not lignes[i].strip() or _ENTETE.match(lignes[i].strip())):
        i += 1
    for brute in lignes[i:]:
        ligne = brute.strip()
        if not ligne:
            continue
        if _FORMULE_FINALE.match(ligne):
            break
        if _ENTETE.match(ligne):
            # En-tête d'un mail transféré : on ne le prend pas.
            continue
        if ":" in ligne:
            libelle = _normaliser(ligne.split(":", 1)[0])
            # Un libellé de formulaire est court : au-delà de 6 mots, c'est une phrase rédigée.
            if (
                2 <= len(libelle) <= 60
                and len(libelle.split()) <= MOTS_MAX_LIBELLE
                and re.search(r"[a-zà-ÿ]", libelle)
                and libelle not in _LIBELLES_BANALS
            ):
                candidates.add(libelle + " :")
                continue
        normalisee = _normaliser(ligne)
        if 12 <= len(normalisee) <= 160 and not _LIGNES_BANALES.match(normalisee):
            if sum(c.isalpha() for c in normalisee) >= len(normalisee) * 0.5:
                candidates.add(normalisee)
    return frozenset(candidates)


@dataclass(frozen=True, slots=True)
class ReperageTemplates:
    resultats: list[ResultatTemplate]  # un par mail, dans l'ordre du corpus
    marqueurs: dict[str, int]  # marqueur → nombre de mails qui le portent
    objets_fixes: dict[str, int]  # objet normalisé → nombre de mails


def reperer_templates(
    textes: Sequence[str],
    objets: Sequence[str | None],
    parametres: ParametresTemplates,
    n_processus: int = 1,
) -> ReperageTemplates:
    """Calcule le booléen `template` et les marqueurs de chaque mail du corpus."""
    if len(textes) != len(objets):
        raise ValueError("textes et objets doivent avoir la même longueur")
    total = len(textes)
    if total == 0:
        return ReperageTemplates([], {}, {})

    candidates = map_par_lots(lignes_candidates, list(textes), n_processus)

    frequences = Counter(c for ensemble in candidates for c in ensemble)
    plafond = max(parametres.min_mails, int(parametres.freq_max * total))
    marqueurs = {c for c, n in frequences.items() if parametres.min_mails <= n <= plafond}

    objets_normalises = [_normaliser_objet(o) for o in objets]
    frequences_objets = Counter(o for o in objets_normalises if o)
    objets_fixes = {o for o, n in frequences_objets.items() if parametres.min_mails <= n <= plafond}

    motifs = [re.compile(m, re.IGNORECASE | re.MULTILINE) for m in parametres.motifs]

    resultats: list[ResultatTemplate] = []
    for texte, ensemble, objet in zip(textes, candidates, objets_normalises, strict=True):
        trouves = tuple(sorted(ensemble & marqueurs))
        if len(trouves) >= parametres.min_marqueurs:
            raison = "marqueurs"
        elif any(m.search(texte) for m in motifs):
            raison = "motif"
        elif parametres.utiliser_objet and objet in objets_fixes and trouves:
            raison = "objet"
        else:
            raison = ""
        resultats.append(ResultatTemplate(bool(raison), trouves[:10], raison))
    return ReperageTemplates(
        resultats,
        {m: frequences[m] for m in sorted(marqueurs, key=lambda m: -frequences[m])},
        {o: frequences_objets[o] for o in sorted(objets_fixes, key=lambda o: -frequences_objets[o])},
    )
