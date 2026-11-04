"""IAG et embedding par une API compatible OpenAI (bibliothèque `openai`, `base_url` configurable)."""

from __future__ import annotations

import asyncio
import json
import time
from collections.abc import Sequence
from copy import deepcopy

import httpx
import openai
from openai import AsyncOpenAI

from demandes.domaine.fiche import CHAMP_ID, SCHEMA_FICHE, formater_mails, schema_lot
from demandes.ports.iag import ErreurIag, ReponseIag

NOM_SCHEMA_LOT = "fiches_demandes"


def consigne_systeme(consigne: str, json_mode: str) -> str:
    """Prompt système complet. En json_object, le schéma est décrit dans le prompt (repli, ADR-0006)."""
    if json_mode == "json_schema":
        return consigne.replace("{consigne_schema}", "").rstrip() + "\n"
    fiche = deepcopy(SCHEMA_FICHE)
    fiche["properties"] = {CHAMP_ID: {"type": "string"}, **fiche["properties"]}
    fiche["required"] = [CHAMP_ID, *fiche["required"]]
    schema = {"type": "object", "required": ["fiches"], "properties": {"fiches": {"type": "array", "items": fiche}}}
    description = (
        "\nRéponds uniquement par un objet JSON qui respecte strictement ce schéma :\n"
        + json.dumps(schema, ensure_ascii=False, indent=1)
    )
    return consigne.replace("{consigne_schema}", description)


class _ClientParBoucle:
    """Un client asynchrone par boucle d'événements (chaque tâche lance sa propre boucle)."""

    def __init__(
        self, base_url: str, api_key: str, timeout_s: float, transport: httpx.AsyncBaseTransport | None = None
    ) -> None:
        self._parametres = {"base_url": base_url, "api_key": api_key, "timeout": timeout_s, "max_retries": 2}
        self._transport = transport  # pour les tests : faux serveur
        self._clients: dict[int, AsyncOpenAI] = {}

    def client(self) -> AsyncOpenAI:
        boucle = id(asyncio.get_running_loop())
        if boucle not in self._clients:
            extra = {"http_client": httpx.AsyncClient(transport=self._transport)} if self._transport else {}
            self._clients[boucle] = AsyncOpenAI(**self._parametres, **extra)
        return self._clients[boucle]


class GenerateurFichesOpenAI:
    def __init__(
        self,
        base_url: str,
        api_key: str,
        modele: str,
        consigne: str,
        temperature: float,
        json_mode: str,
        max_tokens_par_fiche: int,
        timeout_s: float,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self._clients = _ClientParBoucle(base_url, api_key, timeout_s, transport)
        self._modele = modele
        self._systeme = consigne_systeme(consigne, json_mode)
        self._temperature = temperature
        self._json_mode = json_mode
        self._max_tokens_par_fiche = max_tokens_par_fiche

    @property
    def modele(self) -> str:
        return self._modele

    async def generer(self, mails: Sequence[tuple[str, str]]) -> ReponseIag:
        ids = [identifiant for identifiant, _ in mails]
        if self._json_mode == "json_schema":
            format_reponse = {
                "type": "json_schema",
                "json_schema": {"name": NOM_SCHEMA_LOT, "schema": schema_lot(ids), "strict": True},
            }
        else:
            format_reponse = {"type": "json_object"}
        debut = time.perf_counter()
        try:
            reponse = await self._clients.client().chat.completions.create(
                model=self._modele,
                messages=[
                    {"role": "system", "content": self._systeme},
                    {"role": "user", "content": formater_mails(mails)},
                ],
                temperature=self._temperature,
                max_tokens=self._max_tokens_par_fiche * len(mails) + 100,
                response_format=format_reponse,
            )
        except openai.OpenAIError as erreur:
            raise ErreurIag(f"{type(erreur).__name__} : {erreur}") from erreur
        choix = reponse.choices[0]
        usage = reponse.usage
        return ReponseIag(
            contenu=choix.message.content,
            tronquee=choix.finish_reason == "length",
            duree_ms=round((time.perf_counter() - debut) * 1000),
            jetons_entree=usage.prompt_tokens if usage else None,
            jetons_sortie=usage.completion_tokens if usage else None,
        )


class VectoriseurOpenAI:
    def __init__(
        self,
        base_url: str,
        api_key: str,
        modele: str,
        dimension: int,
        timeout_s: float,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self._clients = _ClientParBoucle(base_url, api_key, timeout_s, transport)
        self._modele = modele
        self._dimension = dimension

    @property
    def modele(self) -> str:
        return self._modele

    @property
    def dimension(self) -> int:
        return self._dimension

    async def vectoriser(self, textes: Sequence[str]) -> list[list[float]]:
        try:
            reponse = await self._clients.client().embeddings.create(model=self._modele, input=list(textes))
        except openai.OpenAIError as erreur:
            raise ErreurIag(f"{type(erreur).__name__} : {erreur}") from erreur
        vecteurs = [d.embedding for d in sorted(reponse.data, key=lambda d: d.index)]
        if len(vecteurs) != len(textes):
            raise ErreurIag(f"{len(vecteurs)} vecteurs reçus pour {len(textes)} textes")
        if vecteurs and len(vecteurs[0]) != self._dimension:
            raise ErreurIag(
                f"dimension reçue {len(vecteurs[0])}, attendue {self._dimension} (EMB_DIMENSION)"
            )
        return vecteurs
