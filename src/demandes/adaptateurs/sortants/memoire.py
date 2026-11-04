"""Dépôts en mémoire : pour les tests et pour essayer la chaîne sans base de données."""

from __future__ import annotations

import threading
import uuid
from datetime import UTC, datetime
from typing import Any

import numpy as np

from demandes.domaine.demande import Demande, LigneEcartee
from demandes.domaine.referentiel import EntreeCartographie
from demandes.ports.depots import EchecFiche, EntreeJournal, FicheStockee, InfoImport, PredictionJournal, Tache


class DepotCorpusMemoire:
    def __init__(self) -> None:
        self.demandes: list[Demande] = []
        self.ecartees: list[LigneEcartee] = []
        self.imports: list[InfoImport] = []

    def remplacer_corpus(self, fichier, empreinte_fichier, nb_lignes, demandes, ecartees, bilan) -> int:
        self.demandes, self.ecartees = list(demandes), list(ecartees)
        info = InfoImport(
            len(self.imports) + 1, fichier, empreinte_fichier, datetime.now(UTC), nb_lignes,
            len(demandes), len(ecartees), dict(bilan),
        )
        self.imports.append(info)
        return info.id

    def lister_demandes(self) -> list[Demande]:
        return list(self.demandes)

    def dernier_import(self) -> InfoImport | None:
        return self.imports[-1] if self.imports else None


class DepotReferentielMemoire:
    def __init__(self) -> None:
        self.reference: list[EntreeCartographie] = []

    def lire_reference(self) -> list[EntreeCartographie]:
        return list(self.reference)

    def figer_reference(self, entrees: list[EntreeCartographie]) -> None:
        self.reference = list(entrees)


class DepotTachesMemoire:
    def __init__(self) -> None:
        self._taches: dict[str, Tache] = {}
        self._journal: list[EntreeJournal] = []
        self._verrou = threading.Lock()

    def creer(self, type_tache: str, parametres: dict[str, Any]) -> Tache:
        tache = Tache(str(uuid.uuid4()), type_tache, "en_attente", dict(parametres), cree_le=datetime.now(UTC))
        self._taches[tache.id] = tache
        return tache

    def demarrer(self, tache_id: str) -> None:
        t = self._taches[tache_id]
        t.statut, t.demarre_le = "en_cours", datetime.now(UTC)

    def terminer(self, tache_id: str, resultat: dict[str, Any]) -> None:
        t = self._taches[tache_id]
        t.statut, t.resultat, t.progression, t.termine_le = "terminee", resultat, 1.0, datetime.now(UTC)

    def echouer(self, tache_id: str, erreur: str) -> None:
        t = self._taches[tache_id]
        t.statut, t.erreur, t.termine_le = "echec", erreur, datetime.now(UTC)

    def journaliser(self, tache_id, niveau, message, progression, etape, donnees) -> None:
        with self._verrou:
            self._journal.append(
                EntreeJournal(len(self._journal) + 1, tache_id, datetime.now(UTC), niveau, message, progression, etape, donnees)
            )
            t = self._taches[tache_id]
            t.progression, t.etape, t.message = progression, etape, message

    def lire(self, tache_id: str) -> Tache | None:
        return self._taches.get(tache_id)

    def lister(self, limite: int = 50) -> list[Tache]:
        return sorted(self._taches.values(), key=lambda t: t.cree_le, reverse=True)[:limite]

    def lire_journal(self, tache_id: str, apres_id: int = 0, limite: int = 500) -> list[EntreeJournal]:
        return [e for e in self._journal if e.tache_id == tache_id and e.id > apres_id][:limite]

    def marquer_interrompues(self) -> int:
        n = 0
        for t in self._taches.values():
            if t.statut in ("en_cours", "en_attente"):
                self.echouer(t.id, "interrompue par un redémarrage")
                n += 1
        return n


class DepotFichesMemoire:
    def __init__(self) -> None:
        self.configurations: dict[str, dict] = {}
        self.fiches: dict[tuple[str, str], FicheStockee] = {}
        self.echecs: dict[tuple[str, str], EchecFiche] = {}
        self.controle: dict[tuple[str, str], FicheStockee] = {}

    def enregistrer_configuration(self, empreinte, contenu) -> None:
        self.configurations[empreinte] = dict(contenu)

    def etats(self, empreinte_fiche):
        etats = {n: ("echec", e.empreinte_mail) for (emp, n), e in self.echecs.items() if emp == empreinte_fiche}
        etats.update({n: ("ok", f.empreinte_mail) for (emp, n), f in self.fiches.items() if emp == empreinte_fiche})
        return etats

    def enregistrer_fiches(self, empreinte_fiche, fiches) -> None:
        for f in fiches:
            self.fiches[(empreinte_fiche, f.numero)] = f
            self.echecs.pop((empreinte_fiche, f.numero), None)

    def enregistrer_echecs(self, empreinte_fiche, echecs) -> None:
        for e in echecs:
            self.echecs[(empreinte_fiche, e.numero)] = e

    def lire_fiches(self, empreinte_fiche, numeros=None):
        voulus = set(numeros) if numeros is not None else None
        return {
            n: f for (emp, n), f in self.fiches.items() if emp == empreinte_fiche and (voulus is None or n in voulus)
        }

    def lire_echecs(self, empreinte_fiche):
        return [e for (emp, _), e in sorted(self.echecs.items()) if emp == empreinte_fiche]

    def enregistrer_controle(self, empreinte_fiche, fiches) -> None:
        for f in fiches:
            self.controle[(empreinte_fiche, f.numero)] = f

    def lire_controle(self, empreinte_fiche):
        return {n: f for (emp, n), f in self.controle.items() if emp == empreinte_fiche}


class DepotVecteursMemoire:
    def __init__(self) -> None:
        self.vecteurs: dict[tuple[str, str], tuple[str, np.ndarray]] = {}

    def numeros_vectorises(self, empreinte_vecteur):
        return {n: em for (emp, n), (em, _) in self.vecteurs.items() if emp == empreinte_vecteur}

    def enregistrer_vecteurs(self, empreinte_vecteur, empreinte_fiche, numeros, empreintes_mail, matrice) -> None:
        for n, em, ligne in zip(numeros, empreintes_mail, matrice, strict=True):
            self.vecteurs[(empreinte_vecteur, n)] = (em, np.asarray(ligne, dtype=np.float32))

    def lire_vecteurs(self, empreinte_vecteur, numeros=None):
        voulus = set(numeros) if numeros is not None else None
        retenus = sorted(
            (n, v) for (emp, n), (_, v) in self.vecteurs.items()
            if emp == empreinte_vecteur and (voulus is None or n in voulus)
        )
        if not retenus:
            return [], np.zeros((0, 0), dtype=np.float32)
        return [n for n, _ in retenus], np.vstack([v for _, v in retenus])


class DepotEvaluationsMemoire:
    def __init__(self) -> None:
        self.evaluations: dict[tuple[str, str], dict] = {}
        self._ordre: list[tuple[str, str]] = []

    def enregistrer_evaluation(self, empreinte_jeu, nom, contenu) -> None:
        cle = (empreinte_jeu, nom)
        self.evaluations[cle] = {"empreinte_jeu": empreinte_jeu, "nom": nom, **contenu}
        if cle in self._ordre:
            self._ordre.remove(cle)
        self._ordre.append(cle)

    def lister_evaluations(self, empreinte_jeu=None):
        if empreinte_jeu is None and self._ordre:
            empreinte_jeu = self._ordre[-1][0]
        return [self.evaluations[c] for c in reversed(self._ordre) if c[0] == empreinte_jeu]


class DepotPredictionsMemoire:
    def __init__(self) -> None:
        self.predictions: dict[int, PredictionJournal] = {}

    def journaliser(self, mail, configuration, top3, niveau, avis) -> int:
        identifiant = len(self.predictions) + 1
        self.predictions[identifiant] = PredictionJournal(
            identifiant, datetime.now(UTC), mail, configuration, top3, niveau, avis
        )
        return identifiant

    def enregistrer_retour(self, prediction_id, titre_retenu, operateur) -> bool:
        p = self.predictions.get(prediction_id)
        if p is None:
            return False
        p.titre_retenu, p.operateur, p.retenu_le = titre_retenu, operateur, datetime.now(UTC)
        return True

    def lire(self, prediction_id):
        return self.predictions.get(prediction_id)

    def lister(self, depuis=None, avec_retour=None):
        sortie = [p for p in self.predictions.values() if depuis is None or p.horodatage >= depuis]
        if avec_retour is not None:
            sortie = [p for p in sortie if (p.titre_retenu is not None) == avec_retour]
        return sorted(sortie, key=lambda p: p.id)
