"""Cas d'usage « fiches » : fiches IAG par lots puis embeddings, avec cache par demande (ADR-0010).

Déroulé :
1. On ne garde que les demandes absentes du cache (ou dont le mail a changé).
2. Les lots (FICHES_PAR_APPEL mails, LOT_MAX_CARACTERES au plus) partent en parallèle,
   LLM_CONCURRENCY appels à la fois. Chaque fiche valide est mise en cache dès réception.
3. Une réponse coupée (limite de jetons) : le lot est coupé en deux et relancé.
4. Les demandes sans fiche valide sont renvoyées une par une, avec 2 reprises, puis
   journalisées en échec : elles sont exclues de la branche embedding (TF-IDF les garde).
5. Les fiches valides sans vecteur sont vectorisées par paquets de EMBED_PAR_APPEL.
"""

from __future__ import annotations

import asyncio
import time
from collections.abc import Sequence
from dataclasses import asdict, dataclass, field
from typing import Any

import numpy as np

from demandes.application.empreintes import ConfigFiche, ConfigVecteur
from demandes.config import Settings
from demandes.domaine.demande import Demande, empreinte_mail
from demandes.domaine.fiche import depouiller_reponse, texte_a_vectoriser
from demandes.ports.artefacts import StockageArtefacts
from demandes.ports.depots import DepotCorpus, DepotFiches, DepotVecteurs, EchecFiche, FicheStockee
from demandes.ports.iag import ErreurIag, GenerateurFiches, ReponseIag, Vectoriseur

#: Au-delà de ce nombre d'erreurs réseau d'affilée, l'IAG est jugée indisponible et la tâche s'arrête.
ERREURS_CONSECUTIVES_MAX = 20


class IagIndisponible(RuntimeError):
    """Trop d'erreurs d'affilée : on arrête plutôt que d'envoyer des milliers d'appels voués à l'échec."""
from demandes.ports.suivi import Suivi

ETAPES = ["fiches", "embeddings"]


@dataclass(frozen=True, slots=True)
class ParametresFiches:
    fiches_par_appel: int = 10
    lot_max_caracteres: int = 40_000
    mail_max_caracteres: int = 8_000
    concurrence: int = 4
    embed_par_appel: int = 100
    reprises: int = 2

    @classmethod
    def depuis(cls, settings: Settings) -> ParametresFiches:
        return cls(
            fiches_par_appel=settings.fiches_par_appel,
            lot_max_caracteres=settings.lot_max_caracteres,
            mail_max_caracteres=settings.mail_max_caracteres,
            concurrence=settings.llm_concurrency,
            embed_par_appel=settings.embed_par_appel,
        )


Mail = tuple[str, str]  # (numéro, texte envoyé)


def texte_envoye(demande: Demande, mail_max_caracteres: int) -> str:
    """Le mail tel qu'envoyé à l'IAG : nettoyé (sans HTML ni mentions légales), tronqué au besoin."""
    texte = demande.mail_nettoye or demande.mail
    return texte if len(texte) <= mail_max_caracteres else texte[:mail_max_caracteres] + "\n[…]"


def construire_lots(mails: Sequence[Mail], par_appel: int, max_caracteres: int) -> list[list[Mail]]:
    """Regroupe les mails dans l'ordre : au plus `par_appel` mails et `max_caracteres` par lot.

    Un mail plus long que le budget part seul.
    """
    lots: list[list[Mail]] = []
    courant: list[Mail] = []
    taille = 0
    for mail in mails:
        longueur = len(mail[1])
        if courant and (len(courant) >= par_appel or taille + longueur > max_caracteres):
            lots.append(courant)
            courant, taille = [], 0
        courant.append(mail)
        taille += longueur
    if courant:
        lots.append(courant)
    return lots


@dataclass(slots=True)
class Compteurs:
    a_produire: int = 0
    en_lot: int = 0
    a_l_unite: int = 0
    echecs: int = 0
    appels: int = 0
    lots_coupes: int = 0
    id_hors_lot: int = 0
    jetons_entree: int = 0
    jetons_sortie: int = 0

    @property
    def traitees(self) -> int:
        return self.en_lot + self.a_l_unite + self.echecs


class ProducteurFiches:
    """Appels à l'IAG, contrôle des réponses, reprises. Partagé par l'ingestion et le contrôle lot / unité."""

    def __init__(self, generateur: GenerateurFiches, parametres: ParametresFiches) -> None:
        self.generateur = generateur
        self.parametres = parametres
        self.compteurs = Compteurs()
        self._semaphore: asyncio.Semaphore | None = None
        self._erreurs_consecutives = 0

    def _sem(self) -> asyncio.Semaphore:
        if self._semaphore is None:
            self._semaphore = asyncio.Semaphore(self.parametres.concurrence)
        return self._semaphore

    async def appeler(self, lot: Sequence[Mail]) -> tuple[ReponseIag | None, str | None]:
        async with self._sem():
            self.compteurs.appels += 1
            if self._erreurs_consecutives >= ERREURS_CONSECUTIVES_MAX:
                raise IagIndisponible(
                    f"{self._erreurs_consecutives} erreurs d'affilée de l'IAG, arrêt. Les fiches déjà produites "
                    "sont en cache : relancer la commande reprendra là où elle s'est arrêtée."
                )
            try:
                reponse = await self.generateur.generer(lot)
            except ErreurIag as erreur:
                self._erreurs_consecutives += 1
                return None, str(erreur)
        self._erreurs_consecutives = 0
        self.compteurs.jetons_entree += reponse.jetons_entree or 0
        self.compteurs.jetons_sortie += reponse.jetons_sortie or 0
        return reponse, None

    async def lot(self, lot: list[Mail]) -> tuple[dict[str, tuple[dict, int, int]], dict[str, str]]:
        """Traite un lot. Renvoie (fiches valides : id → (fiche, taille_lot, durée), rejets : id → motif)."""
        reponse, erreur = await self.appeler(lot)
        ids = [i for i, _ in lot]
        if erreur:
            return {}, {i: erreur for i in ids}
        if reponse.tronquee and len(lot) > 1:
            self.compteurs.lots_coupes += 1
            milieu = len(lot) // 2
            (v1, r1), (v2, r2) = await asyncio.gather(self.lot(lot[:milieu]), self.lot(lot[milieu:]))
            return {**v1, **v2}, {**r1, **r2}
        if reponse.tronquee:
            return {}, {ids[0]: "réponse tronquée (limite de jetons)"}
        depouillement = depouiller_reponse(reponse.contenu, ids)
        self.compteurs.id_hors_lot += len(depouillement.hors_lot)
        valides = {i: (f, len(lot), reponse.duree_ms) for i, f in depouillement.valides.items()}
        return valides, depouillement.rejets

    async def unite(self, mail: Mail, essais: int, erreur_initiale: str) -> tuple[dict | None, int, int, str]:
        """Renvoie un mail seul, `essais` fois au plus. → (fiche ou None, essais faits, durée, dernière erreur)."""
        derniere = erreur_initiale
        for essai in range(1, essais + 1):
            reponse, erreur = await self.appeler([mail])
            if erreur:
                derniere = erreur
                continue
            if reponse.tronquee:
                derniere = "réponse tronquée (limite de jetons)"
                continue
            depouillement = depouiller_reponse(reponse.contenu, [mail[0]])
            if mail[0] in depouillement.valides:
                return depouillement.valides[mail[0]], essai, reponse.duree_ms, ""
            derniere = depouillement.rejets.get(mail[0], "fiche absente")
        return None, essais, 0, derniere


@dataclass(slots=True)
class ResultatFiches:
    empreinte_fiche: str
    empreinte_vecteur: str
    modele_iag: str
    modele_embedding: str
    nb_demandes: int
    fiches_en_cache: int
    fiches_a_produire: int
    fiches_en_lot: int
    fiches_a_l_unite: int
    echecs_nouveaux: int
    echecs_total: int
    appels_iag: int
    lots_coupes: int
    id_hors_lot: int
    jetons_entree: int
    jetons_sortie: int
    duree_fiches_s: float
    debit_fiches_par_minute: float
    vecteurs_en_cache: int
    vecteurs_calcules: int
    echecs_embedding: int
    exclus_branche_embedding: int
    fichiers: dict[str, str] = field(default_factory=dict)

    def en_dict(self) -> dict[str, Any]:
        return asdict(self)


class ProductionFiches:
    def __init__(
        self,
        corpus: DepotCorpus,
        fiches: DepotFiches,
        vecteurs: DepotVecteurs,
        generateur: GenerateurFiches,
        vectoriseur: Vectoriseur,
        config_fiche: ConfigFiche,
        artefacts: StockageArtefacts,
        parametres: ParametresFiches,
    ) -> None:
        self.corpus = corpus
        self.fiches = fiches
        self.vecteurs = vecteurs
        self.generateur = generateur
        self.vectoriseur = vectoriseur
        self.config_fiche = config_fiche
        self.config_vecteur = ConfigVecteur(config_fiche.empreinte, vectoriseur.modele, vectoriseur.dimension)
        self.artefacts = artefacts
        self.parametres = parametres

    def executer(self, suivi: Suivi, reprendre_echecs: bool = False, deja_demarre: bool = False) -> ResultatFiches:
        if not deja_demarre:
            suivi.demarrer(ETAPES)
        resultat = asyncio.run(self._executer(suivi, reprendre_echecs))
        if not deja_demarre:
            suivi.terminer(
                f"Fiches : {resultat.fiches_en_cache + resultat.fiches_en_lot + resultat.fiches_a_l_unite} valides, "
                f"{resultat.echecs_total} en échec ; vecteurs : {resultat.vecteurs_en_cache + resultat.vecteurs_calcules}"
            )
        return resultat

    # --- Fiches ---------------------------------------------------------------

    async def _executer(self, suivi: Suivi, reprendre_echecs: bool) -> ResultatFiches:
        p = self.parametres
        emp_fiche, emp_vecteur = self.config_fiche.empreinte, self.config_vecteur.empreinte
        suivi.etape("fiches")
        await asyncio.to_thread(self.fiches.enregistrer_configuration, emp_fiche, self.config_fiche.contenu)
        await asyncio.to_thread(self.fiches.enregistrer_configuration, emp_vecteur, self.config_vecteur.contenu)

        demandes = await asyncio.to_thread(self.corpus.lister_demandes)
        etats = await asyncio.to_thread(self.fiches.etats, emp_fiche)
        empreintes = {d.numero: empreinte_mail(d.mail) for d in demandes}
        a_faire = []
        for d in demandes:
            etat = etats.get(d.numero)
            a_jour = etat is not None and etat[1] == empreintes[d.numero]
            if a_jour and (etat[0] == "ok" or not reprendre_echecs):
                continue
            a_faire.append(d)
        en_cache = sum(1 for d in demandes if etats.get(d.numero, ("", ""))[0] == "ok" and etats[d.numero][1] == empreintes[d.numero])

        mails = [(d.numero, texte_envoye(d, p.mail_max_caracteres)) for d in sorted(a_faire, key=lambda d: d.numero)]
        lots = construire_lots(mails, p.fiches_par_appel, p.lot_max_caracteres)
        suivi.info(
            f"Configuration de fiche {emp_fiche[:16]} (modèle {self.generateur.modele}) : "
            f"{en_cache} fiches déjà en cache, {len(mails)} à produire en {len(lots)} appels "
            f"de {p.fiches_par_appel} mails au plus, {p.concurrence} appels en parallèle",
            empreinte_fiche=emp_fiche,
        )

        producteur = ProducteurFiches(self.generateur, p)
        c = producteur.compteurs
        c.a_produire = len(mails)
        debut = time.monotonic()

        def signaler() -> None:
            ecoule = max(time.monotonic() - debut, 1e-6)
            suivi.avancer(
                c.traitees, c.a_produire,
                f"{c.en_lot} en lot, {c.a_l_unite} à l'unité, {c.echecs} échecs — "
                f"{(c.en_lot + c.a_l_unite) / ecoule * 60:.0f} fiches/min, {c.appels} appels",
            )

        async def enregistrer(valides: dict[str, tuple[dict, int, int]], tentatives: int) -> None:
            if not valides:
                return
            stockees = [
                FicheStockee(numero, empreintes[numero], fiche, taille, tentatives, duree)
                for numero, (fiche, taille, duree) in valides.items()
            ]
            await asyncio.to_thread(self.fiches.enregistrer_fiches, emp_fiche, stockees)

        textes = dict(mails)

        async def traiter(lot: list[Mail]) -> None:
            valides, rejets = await producteur.lot(lot)
            await enregistrer(valides, 1)
            for numero, (_, taille, _) in valides.items():
                if taille > 1:
                    c.en_lot += 1
                else:
                    c.a_l_unite += 1
            signaler()
            # Renvoi un par un : 1 envoi + 2 reprises ; un lot de 1 a déjà compté pour un envoi.
            essais = p.reprises if len(lot) == 1 else p.reprises + 1
            await asyncio.gather(*(reprendre(numero, motif, essais) for numero, motif in rejets.items()))

        async def reprendre(numero: str, motif: str, essais: int) -> None:
            fiche, faits, duree, derniere = await producteur.unite((numero, textes[numero]), essais, motif)
            if fiche is not None:
                await enregistrer({numero: (fiche, 1, duree)}, faits + 1)
                c.a_l_unite += 1
            else:
                echec = EchecFiche(numero, empreintes[numero], faits + 1, derniere)
                await asyncio.to_thread(self.fiches.enregistrer_echecs, emp_fiche, [echec])
                c.echecs += 1
                suivi.alerte(f"Fiche en échec pour {numero} après {faits + 1} envois : {derniere}", numero=numero)
            signaler()

        await asyncio.gather(*(traiter(lot) for lot in lots))
        duree_fiches = time.monotonic() - debut
        if c.id_hors_lot:
            suivi.alerte(f"{c.id_hors_lot} fiches rejetées : id inconnu du lot")
        if c.lots_coupes:
            suivi.alerte(f"{c.lots_coupes} lots coupés en deux (réponse tronquée) : réduire FICHES_PAR_APPEL ?")

        echecs = await asyncio.to_thread(self.fiches.lire_echecs, emp_fiche)
        echecs_courants = [e for e in echecs if empreintes.get(e.numero) == e.empreinte_mail]
        fichier_echecs = self.artefacts.ecrire_csv(
            f"fiches/{emp_fiche[:16]}/echecs.csv",
            ["numero", "tentatives", "erreur"],
            ((e.numero, e.tentatives, e.erreur) for e in echecs_courants),
        )

        # --- Embeddings ---------------------------------------------------------
        vect_en_cache, vect_calcules, echecs_emb = await self._embeddings(suivi, empreintes)

        resultat = ResultatFiches(
            empreinte_fiche=emp_fiche,
            empreinte_vecteur=emp_vecteur,
            modele_iag=self.generateur.modele,
            modele_embedding=self.vectoriseur.modele,
            nb_demandes=len(demandes),
            fiches_en_cache=en_cache,
            fiches_a_produire=c.a_produire,
            fiches_en_lot=c.en_lot,
            fiches_a_l_unite=c.a_l_unite,
            echecs_nouveaux=c.echecs,
            echecs_total=len(echecs_courants),
            appels_iag=c.appels,
            lots_coupes=c.lots_coupes,
            id_hors_lot=c.id_hors_lot,
            jetons_entree=c.jetons_entree,
            jetons_sortie=c.jetons_sortie,
            duree_fiches_s=round(duree_fiches, 1),
            debit_fiches_par_minute=round((c.en_lot + c.a_l_unite) / max(duree_fiches, 1e-6) * 60, 1),
            vecteurs_en_cache=vect_en_cache,
            vecteurs_calcules=vect_calcules,
            echecs_embedding=echecs_emb,
            exclus_branche_embedding=len(demandes) - vect_en_cache - vect_calcules,
            fichiers={"echecs": str(fichier_echecs)},
        )
        resultat.fichiers["bilan"] = str(
            self.artefacts.ecrire_json(f"fiches/{emp_fiche[:16]}/bilan_fiches.json", resultat.en_dict())
        )
        return resultat

    async def _embeddings(self, suivi: Suivi, empreintes: dict[str, str]) -> tuple[int, int, int]:
        p = self.parametres
        emp_fiche, emp_vecteur = self.config_fiche.empreinte, self.config_vecteur.empreinte
        suivi.etape("embeddings")
        fiches = await asyncio.to_thread(self.fiches.lire_fiches, emp_fiche, sorted(empreintes))
        fiches = {n: f for n, f in fiches.items() if f.empreinte_mail == empreintes.get(n)}
        deja = await asyncio.to_thread(self.vecteurs.numeros_vectorises, emp_vecteur)
        en_cache = sum(1 for n in fiches if deja.get(n) == empreintes[n])
        a_faire = sorted(n for n in fiches if deja.get(n) != empreintes[n])
        paquets = [a_faire[i : i + p.embed_par_appel] for i in range(0, len(a_faire), p.embed_par_appel)]
        suivi.info(
            f"Configuration de vecteur {emp_vecteur[:16]} (modèle {self.vectoriseur.modele}, "
            f"{self.vectoriseur.dimension} dimensions) : {en_cache} en cache, {len(a_faire)} à calculer "
            f"en {len(paquets)} appels de {p.embed_par_appel}",
            empreinte_vecteur=emp_vecteur,
        )
        semaphore = asyncio.Semaphore(p.concurrence)
        faits, echecs = 0, 0

        async def traiter(paquet: list[str]) -> None:
            nonlocal faits, echecs
            textes = [texte_a_vectoriser(fiches[n].fiche) for n in paquet]
            derniere = ""
            for _ in range(p.reprises + 1):
                async with semaphore:
                    try:
                        vecteurs = await self.vectoriseur.vectoriser(textes)
                        break
                    except ErreurIag as erreur:
                        derniere = str(erreur)
            else:
                echecs += len(paquet)
                suivi.alerte(f"Embedding en échec pour {len(paquet)} demandes : {derniere}")
                return
            matrice = np.asarray(vecteurs, dtype=np.float32)
            normes = np.linalg.norm(matrice, axis=1, keepdims=True)
            matrice = matrice / np.where(normes == 0, 1, normes)
            await asyncio.to_thread(
                self.vecteurs.enregistrer_vecteurs, emp_vecteur, emp_fiche, paquet, [empreintes[n] for n in paquet], matrice
            )
            faits += len(paquet)
            suivi.avancer(faits + echecs, len(a_faire), f"{faits} vecteurs calculés, {echecs} échecs")

        await asyncio.gather(*(traiter(paquet) for paquet in paquets))
        return en_cache, faits, echecs
