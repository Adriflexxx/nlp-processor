"""Adaptateur openai réel, branché sur un faux serveur compatible OpenAI (transport httpx)."""

import asyncio
import json

import httpx
import pytest

from demandes.adaptateurs.sortants.iag_openai import GenerateurFichesOpenAI, VectoriseurOpenAI, consigne_systeme
from demandes.adaptateurs.sortants.simulateurs import fiche_simulee
from demandes.domaine.fiche import depouiller_reponse
from demandes.ports.iag import ErreurIag


class FauxServeur:
    def __init__(self, tronquer=False, statut=200, dimension=8):
        self.requetes = []
        self.tronquer, self.statut, self.dimension = tronquer, statut, dimension

    def __call__(self, requete: httpx.Request) -> httpx.Response:
        corps = json.loads(requete.content)
        self.requetes.append((requete.url.path, corps))
        if self.statut != 200:
            return httpx.Response(self.statut, json={"error": {"message": "refus"}})
        if requete.url.path.endswith("/embeddings"):
            donnees = [{"object": "embedding", "index": i, "embedding": [0.5] * self.dimension} for i in range(len(corps["input"]))]
            return httpx.Response(200, json={"object": "list", "data": donnees[::-1], "model": corps["model"]})
        ids = corps["response_format"]["json_schema"]["schema"]["properties"]["fiches"]["items"]["properties"]["id"]["enum"] \
            if corps["response_format"]["type"] == "json_schema" else ["A", "B"]
        contenu = json.dumps({"fiches": [{"id": i, **fiche_simulee("Objet : x\n\nExport FACTO vide.")} for i in ids]})
        return httpx.Response(200, json={
            "id": "x", "object": "chat.completion", "created": 0, "model": corps["model"],
            "choices": [{"index": 0, "finish_reason": "length" if self.tronquer else "stop",
                         "message": {"role": "assistant", "content": contenu}}],
            "usage": {"prompt_tokens": 120, "completion_tokens": 80, "total_tokens": 200},
        })


def _generateur(serveur, json_mode="json_schema"):
    return GenerateurFichesOpenAI(
        "http://iag.test/v1", "cle", "modele-x", "Consigne.\n{consigne_schema}", 0.0, json_mode, 400, 5,
        transport=httpx.MockTransport(serveur),
    )


def test_appel_json_schema_strict_par_lot():
    serveur = FauxServeur()
    reponse = asyncio.run(_generateur(serveur).generer([("A", "mail a"), ("B", "mail b")]))
    chemin, corps = serveur.requetes[0]
    assert chemin == "/v1/chat/completions"
    format_ = corps["response_format"]
    assert format_["type"] == "json_schema" and format_["json_schema"]["strict"] is True
    assert format_["json_schema"]["schema"]["properties"]["fiches"]["items"]["properties"]["id"]["enum"] == ["A", "B"]
    assert corps["max_tokens"] == 2 * 400 + 100 and corps["temperature"] == 0.0
    assert corps["messages"][0]["role"] == "system" and "{consigne_schema}" not in corps["messages"][0]["content"]
    assert '<mail id="A">' in corps["messages"][1]["content"]
    assert not reponse.tronquee and reponse.jetons_entree == 120
    assert set(depouiller_reponse(reponse.contenu, ["A", "B"]).valides) == {"A", "B"}


def test_repli_json_object_decrit_le_schema_dans_le_prompt():
    serveur = FauxServeur()
    asyncio.run(_generateur(serveur, "json_object").generer([("A", "a"), ("B", "b")]))
    corps = serveur.requetes[0][1]
    assert corps["response_format"] == {"type": "json_object"}
    assert '"fiches"' in corps["messages"][0]["content"]
    assert "elements_discriminants" in consigne_systeme("x {consigne_schema}", "json_object")


def test_troncature_et_erreur():
    assert asyncio.run(_generateur(FauxServeur(tronquer=True)).generer([("A", "a")])).tronquee
    with pytest.raises(ErreurIag):
        asyncio.run(_generateur(FauxServeur(statut=400)).generer([("A", "a")]))


def test_embeddings_par_lot_dans_l_ordre_et_dimension_controlee():
    serveur = FauxServeur(dimension=8)
    v = VectoriseurOpenAI("http://emb.test/v1", "cle", "bge-m3", 8, 5, transport=httpx.MockTransport(serveur))
    vecteurs = asyncio.run(v.vectoriser(["a", "b", "c"]))
    assert len(vecteurs) == 3 and serveur.requetes[0][1]["input"] == ["a", "b", "c"]
    mauvais = VectoriseurOpenAI("http://emb.test/v1", "cle", "bge-m3", 1024, 5, transport=httpx.MockTransport(serveur))
    with pytest.raises(ErreurIag, match="dimension"):
        asyncio.run(mauvais.vectoriser(["a"]))
