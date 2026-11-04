"""Empreintes de configuration (ADR-0007, précisé par l'ADR-0010).

- empreinte_fiche : consigne (prompt), schéma, modèle LLM, température, JSON_MODE,
  troncature des mails. La taille des lots n'y entre pas : un mail seul est un lot de 1,
  traité avec la même consigne ; chaque fiche garde la taille du lot qui l'a produite.
- empreinte_vecteur : empreinte_fiche, modèle d'embedding, dimension, version du texte vectorisé.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass
from typing import Any

from demandes.domaine.fiche import SCHEMA_FICHE, VERSION_TEXTE


def _hacher(contenu: dict[str, Any]) -> str:
    texte = json.dumps(contenu, sort_keys=True, ensure_ascii=False, separators=(",", ":"))
    return hashlib.sha256(texte.encode("utf-8")).hexdigest()


@dataclass(frozen=True, slots=True)
class ConfigFiche:
    consigne: str
    modele: str  # préfixé par « mock: » en mode simulé
    temperature: float
    json_mode: str
    mail_max_caracteres: int

    @property
    def contenu(self) -> dict[str, Any]:
        return {"nature": "fiche", **asdict(self), "schema": SCHEMA_FICHE}

    @property
    def empreinte(self) -> str:
        return _hacher(self.contenu)


@dataclass(frozen=True, slots=True)
class ConfigVecteur:
    empreinte_fiche: str
    modele: str
    dimension: int
    version_texte: int = VERSION_TEXTE

    @property
    def contenu(self) -> dict[str, Any]:
        return {"nature": "vecteur", **asdict(self)}

    @property
    def empreinte(self) -> str:
        return _hacher(self.contenu)
