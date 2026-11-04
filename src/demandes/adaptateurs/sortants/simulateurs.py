"""Simulation de l'IAG et de l'embedding (MOCK_LLM=true) : toute la chaîne tourne sans serveur.

Déterministe : un même mail donne toujours la même fiche et le même vecteur.
Les fiches sont tirées du mail par des règles simples, et les vecteurs par
hachage des mots : deux mails proches ont des vecteurs proches, ce qui permet
d'entraîner et d'évaluer les modèles de la branche embedding en simulation.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import re
from collections import Counter
from collections.abc import Sequence

import numpy as np

from demandes.apprentissage.nettoyage import extraire_objet
from demandes.domaine.fiche import CHAMP_ID
from demandes.ports.iag import ReponseIag

_ACTIONS = [
    (r"supprim|désactiv|clôtur|départ", "supprimer"),
    (r"retir|révoqu", "retirer_acces"),
    (r"habilit|accès|droits?\b", "donner_acces"),
    (r"erreur|plant|anomal|vide|souci|bloqu", "signaler"),
    (r"cré|nouvel arrivant", "creer"),
    (r"modifi|mise à jour|mettre à jour|réinitialis", "modifier"),
    (r"information|question|chiffres|indicateur", "demander_information"),
]
_MOT = re.compile(r"[a-zà-ÿ]{4,}", re.IGNORECASE)
_SIGLE = re.compile(r"\b[A-Z]{3,}(?: [A-Z]{2,})?\b")
_VIDES = {"bonjour", "cordialement", "merci", "pour", "dans", "avec", "vous", "nous", "objet", "demande", "service"}


def _corps(texte: str) -> str:
    lignes = [ligne for ligne in texte.splitlines() if not re.match(r"^\s*(de|à|objet|cc)\s*:", ligne, re.IGNORECASE)]
    corps = "\n".join(lignes)
    return re.split(r"\n\s*(?:bien )?cordialement", corps, flags=re.IGNORECASE)[0]


def fiche_simulee(texte: str) -> dict:
    corps = _corps(texte)
    objet = extraire_objet(texte) or ""
    sigles = Counter(s for s in _SIGLE.findall(corps + " " + objet) if s not in {"RE", "TR"})
    action = next((a for motif, a in _ACTIONS if re.search(motif, corps + " " + objet, re.IGNORECASE)), "autre")
    mots = [m.lower() for m in _MOT.findall(corps) if m.lower() not in _VIDES]
    frequents = [m for m, _ in Counter(mots).most_common(5)] or ["inconnu"]
    marqueurs = [ligne.split(":")[0].strip() + " :" for ligne in corps.splitlines() if re.match(r"^[^:]{3,40}:\s*\S", ligne)]
    phrases = [p.strip() for p in re.split(r"(?<=[.!?])\s+|\n+", corps) if len(p.strip()) > 15]
    return {
        "objet_origine": objet,
        "template": len(marqueurs) >= 2,
        "marqueurs_template": marqueurs[:5] if len(marqueurs) >= 2 else [],
        "application": sigles.most_common(1)[0][0] if sigles else "inconnu",
        "action": action,
        "objet_action": " ".join(frequents[:2]),
        "elements_discriminants": frequents[:5],
        "resume": " ".join(phrases[:2])[:300] or objet or "Demande sans contenu exploitable.",
    }


class GenerateurFichesSimule:
    def __init__(self, modele: str = "mock:fiche", latence_s: float = 0.0) -> None:
        self._modele = modele
        self.latence_s = latence_s
        self.appels: list[list[str]] = []  # ids de chaque appel, pour les tests

    @property
    def modele(self) -> str:
        return self._modele

    async def generer(self, mails: Sequence[tuple[str, str]]) -> ReponseIag:
        self.appels.append([identifiant for identifiant, _ in mails])
        if self.latence_s:
            await asyncio.sleep(self.latence_s)
        fiches = [{CHAMP_ID: identifiant, **fiche_simulee(texte)} for identifiant, texte in mails]
        return ReponseIag(json.dumps({"fiches": fiches}, ensure_ascii=False), False, round(self.latence_s * 1000))


class VectoriseurSimule:
    def __init__(self, dimension: int = 1024, modele: str = "mock:embedding") -> None:
        self._dimension = dimension
        self._modele = modele
        self.appels: list[int] = []

    @property
    def modele(self) -> str:
        return self._modele

    @property
    def dimension(self) -> int:
        return self._dimension

    def _vecteur(self, texte: str) -> list[float]:
        vecteur = np.zeros(self._dimension, dtype=np.float32)
        mots = [m.lower() for m in _MOT.findall(texte)]
        for jeton in mots + [f"{a}_{b}" for a, b in zip(mots, mots[1:])]:
            h = hashlib.blake2b(jeton.encode(), digest_size=8).digest()
            indice = int.from_bytes(h[:4], "little") % self._dimension
            vecteur[indice] += 1.0 if h[4] & 1 else -1.0
        norme = np.linalg.norm(vecteur)
        return (vecteur / norme if norme else vecteur).tolist()

    async def vectoriser(self, textes: Sequence[str]) -> list[list[float]]:
        self.appels.append(len(textes))
        return [self._vecteur(t) for t in textes]
