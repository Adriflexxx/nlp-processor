"""Cas d'usage « controle-lots » : les fiches en lot valent-elles les fiches à l'unité ? (ADR-0010)

Sur un échantillon de demandes dont la fiche a été produite en lot, on refait la
fiche à l'unité (lot de 1, même consigne) et on compare les champs. Les fiches à
l'unité vont dans une table séparée : elles n'écrasent jamais le cache.

La comparaison de l'exactitude top 1 de `rl_emb` (entraîné sur les fiches en lot,
évalué avec les fiches en lot puis à l'unité) s'ajoutera avec les modèles de la
branche embedding.
"""

from __future__ import annotations

import asyncio
import random
import unicodedata
from collections.abc import Callable
from dataclasses import asdict, dataclass, field
from typing import Any

from demandes.application.empreintes import ConfigFiche
from demandes.application.generer_fiches import ParametresFiches, ProducteurFiches, texte_envoye
from demandes.domaine.demande import empreinte_mail
from demandes.ports.artefacts import StockageArtefacts
from demandes.ports.depots import DepotCorpus, DepotFiches, FicheStockee
from demandes.ports.iag import GenerateurFiches
from demandes.ports.suivi import Suivi

CHAMPS_COMPARES = ("action", "application", "template", "objet_action")


def _normaliser(valeur: Any) -> Any:
    if isinstance(valeur, str):
        texte = unicodedata.normalize("NFKD", valeur).encode("ascii", "ignore").decode().casefold()
        return " ".join(texte.split())
    return valeur


@dataclass(slots=True)
class ResultatControle:
    empreinte_fiche: str
    taille_echantillon: int
    fiches_unite_produites: int
    fiches_unite_en_cache: int
    echecs_unite: int
    accords: dict[str, float]  # champ → part d'accord lot / unité
    nb_desaccords: dict[str, int]
    fichiers: dict[str, str] = field(default_factory=dict)

    def en_dict(self) -> dict[str, Any]:
        return asdict(self)


class ControleLots:
    def __init__(
        self,
        corpus: DepotCorpus,
        fiches: DepotFiches,
        generateur: GenerateurFiches,
        config_fiche: ConfigFiche,
        artefacts: StockageArtefacts,
        parametres: ParametresFiches,
        graine: int,
        numeros_test: Callable[[], set[str]] | None = None,
    ) -> None:
        self.corpus = corpus
        self.fiches = fiches
        self.generateur = generateur
        self.config_fiche = config_fiche
        self.artefacts = artefacts
        self.parametres = parametres
        self.graine = graine
        # Demandes du jeu de test : tirées en priorité, pour que le volet rl_emb (évaluer)
        # porte sur des demandes que le modèle n'a pas vues à l'entraînement.
        self.numeros_test = numeros_test

    def executer(self, suivi: Suivi, taille: int = 200) -> ResultatControle:
        suivi.demarrer(["échantillon", "fiches à l'unité", "comparaison"])
        resultat = asyncio.run(self._executer(suivi, taille))
        suivi.terminer(
            "Contrôle lot / unité : accord "
            + ", ".join(f"{champ} {part:.0%}" for champ, part in resultat.accords.items()),
        )
        return resultat

    async def _executer(self, suivi: Suivi, taille: int) -> ResultatControle:
        emp = self.config_fiche.empreinte
        suivi.etape("échantillon")
        demandes = {d.numero: d for d in await asyncio.to_thread(self.corpus.lister_demandes)}
        en_lot = {
            n: f
            for n, f in (await asyncio.to_thread(self.fiches.lire_fiches, emp)).items()
            if f.taille_lot > 1 and n in demandes and f.empreinte_mail == empreinte_mail(demandes[n].mail)
        }
        if not en_lot:
            raise ValueError("aucune fiche produite en lot pour cette configuration : lancer d'abord l'ingestion")
        rng = random.Random(self.graine)
        test = self.numeros_test() if self.numeros_test else set()
        prioritaires = sorted(n for n in en_lot if n in test)
        autres = sorted(n for n in en_lot if n not in test)
        echantillon = rng.sample(prioritaires, min(taille, len(prioritaires)))
        if len(echantillon) < taille:
            echantillon += rng.sample(autres, min(taille - len(echantillon), len(autres)))
        echantillon = sorted(echantillon)
        deja = await asyncio.to_thread(self.fiches.lire_controle, emp)
        deja = {n: f for n, f in deja.items() if n in en_lot and f.empreinte_mail == en_lot[n].empreinte_mail}
        a_faire = [n for n in echantillon if n not in deja]
        suivi.info(
            f"{len(echantillon)} demandes tirées (graine {self.graine}) parmi {len(en_lot)} fiches produites en lot, "
            f"dont {sum(1 for n in echantillon if n in test)} du jeu de test ; "
            f"{len(deja)} fiches à l'unité déjà faites, {len(a_faire)} à produire"
        )

        suivi.etape("fiches à l'unité")
        producteur = ProducteurFiches(self.generateur, self.parametres)
        echecs = 0
        faits = 0

        async def produire(numero: str) -> None:
            nonlocal echecs, faits
            mail = (numero, texte_envoye(demandes[numero], self.parametres.mail_max_caracteres))
            fiche, essais, duree, erreur = await producteur.unite(mail, self.parametres.reprises + 1, "")
            if fiche is None:
                echecs += 1
                suivi.alerte(f"Fiche à l'unité en échec pour {numero} : {erreur}")
            else:
                stockee = FicheStockee(numero, en_lot[numero].empreinte_mail, fiche, 1, essais, duree)
                await asyncio.to_thread(self.fiches.enregistrer_controle, emp, [stockee])
                faits += 1
            suivi.avancer(faits + echecs, len(a_faire), f"{faits} fiches à l'unité, {echecs} échecs")

        await asyncio.gather(*(produire(n) for n in a_faire))

        suivi.etape("comparaison")
        unite = await asyncio.to_thread(self.fiches.lire_controle, emp)
        compares = [n for n in echantillon if n in unite]
        desaccords: list[tuple[str, str, str, str]] = []
        nb: dict[str, int] = {champ: 0 for champ in CHAMPS_COMPARES}
        for n in compares:
            for champ in CHAMPS_COMPARES:
                a, b = en_lot[n].fiche.get(champ), unite[n].fiche.get(champ)
                if _normaliser(a) != _normaliser(b):
                    nb[champ] += 1
                    desaccords.append((n, champ, str(a), str(b)))
        accords = {champ: (1 - nb[champ] / len(compares)) if compares else 0.0 for champ in CHAMPS_COMPARES}
        resultat = ResultatControle(emp, len(echantillon), faits, len(deja), echecs, accords, nb)
        resultat.fichiers["desaccords"] = str(
            self.artefacts.ecrire_csv(
                f"fiches/{emp[:16]}/controle_lots_desaccords.csv", ["numero", "champ", "en_lot", "a_l_unite"], desaccords
            )
        )
        resultat.fichiers["bilan"] = str(
            self.artefacts.ecrire_json(f"fiches/{emp[:16]}/controle_lots.json", resultat.en_dict())
        )
        return resultat
