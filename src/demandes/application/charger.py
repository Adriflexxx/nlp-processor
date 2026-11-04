"""Cas d'usage « charger » : lecture de l'export, contrôles, cartographie, templates.

Étape 1 du pipeline. Aucun appel à l'IAG.
"""

from __future__ import annotations

import hashlib
from collections import Counter
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

from demandes.apprentissage.nettoyage import extraire_objet, nettoyer_mail
from demandes.apprentissage.templates import ParametresTemplates, reperer_templates
from demandes.config import Settings
from demandes.domaine.controles import TexteRepare, ecarter_lignes, reparer_texte
from demandes.domaine.demande import Demande
from demandes.domaine.referentiel import EcartReferentiel, cartographier, comparer, petites_categories
from demandes.parallele import map_par_lots
from demandes.ports.artefacts import StockageArtefacts
from demandes.ports.depots import DepotCorpus, DepotReferentiel
from demandes.ports.source_export import SourceExport
from demandes.ports.suivi import Suivi

DOSSIER = "chargement"
ETAPES = ["lecture", "contrôles", "nettoyage", "templates", "cartographie", "enregistrement"]


@dataclass(frozen=True, slots=True)
class ParametresChargement:
    mapping: dict[str, str]
    feuille: str | None
    min_par_titre: int
    templates: ParametresTemplates
    n_processus: int

    @classmethod
    def depuis(cls, settings: Settings) -> ParametresChargement:
        return cls(
            mapping=settings.mapping_colonnes,
            feuille=settings.feuille_excel or None,
            min_par_titre=settings.min_par_titre,
            templates=ParametresTemplates(
                min_mails=settings.template_min_mails,
                freq_max=settings.template_freq_max,
                min_marqueurs=settings.template_min_marqueurs,
                utiliser_objet=settings.template_objet,
                motifs=tuple(settings.liste_motifs_template),
            ),
            n_processus=settings.n_processus,
        )


@dataclass(slots=True)
class ResultatChargement:
    import_id: int
    fichier: str
    nb_lignes: int
    nb_retenues: int
    nb_ecartees: int
    motifs_ecart: dict[str, int]
    encodages_repares: int
    nul_retires: int
    mails_caracteres_inconnus: int
    dates_absentes: int
    nb_titres: int
    nb_titres_apprentissage: int
    petites_categories: list[str]
    nb_templates: int
    raisons_template: dict[str, int]
    nb_marqueurs: int
    reference_creee: bool
    titres_nouveaux: list[str]
    titres_disparus: list[str]
    fichiers: dict[str, str] = field(default_factory=dict)

    def en_dict(self) -> dict[str, Any]:
        return asdict(self)


def _preparer_mail(mail: str) -> tuple[TexteRepare, str, str | None]:
    """Réparation, nettoyage et objet d'un mail (exécuté dans un processus de travail)."""
    repare = reparer_texte(mail)
    return repare, nettoyer_mail(repare.texte), extraire_objet(repare.texte)


def empreinte_fichier(chemin: Path) -> str:
    sha = hashlib.sha256()
    with chemin.open("rb") as flux:
        for bloc in iter(lambda: flux.read(1 << 20), b""):
            sha.update(bloc)
    return sha.hexdigest()


class Chargeur:
    def __init__(
        self,
        source: SourceExport,
        corpus: DepotCorpus,
        referentiel: DepotReferentiel,
        artefacts: StockageArtefacts,
        parametres: ParametresChargement,
    ) -> None:
        self.source = source
        self.corpus = corpus
        self.referentiel = referentiel
        self.artefacts = artefacts
        self.parametres = parametres

    def executer(
        self,
        chemin: Path,
        suivi: Suivi,
        nouvelle_reference: bool = False,
        etapes_suivantes: list[str] | None = None,
    ) -> ResultatChargement:
        """`etapes_suivantes` : étapes qu'un autre cas d'usage enchaînera dans la même tâche (fiches…)."""
        p = self.parametres
        suivi.demarrer(ETAPES + list(etapes_suivantes or []))

        # 1. Lecture
        suivi.etape("lecture")
        suivi.info(f"Lecture de {chemin} (colonnes : {p.mapping})")
        lignes = self.source.lire(chemin, p.mapping, p.feuille)
        suivi.info(f"{len(lignes)} lignes lues")

        # 2. Contrôles
        suivi.etape("contrôles")
        gardees, ecartees = ecarter_lignes(lignes)
        motifs = Counter(e.motif.value for e in ecartees)
        suivi.info(f"{len(gardees)} lignes gardées, {len(ecartees)} écartées", motifs=dict(motifs))

        # 3. Nettoyage (en parallèle sur plusieurs processus)
        suivi.etape("nettoyage")
        suivi.info(f"Réparation de l'encodage et nettoyage de {len(gardees)} mails sur {p.n_processus} processus")
        prepares = map_par_lots(_preparer_mail, [ligne.mail or "" for ligne in gardees], p.n_processus)
        encodages = sum(r.encodage_repare for r, _, _ in prepares)
        nul = sum(r.nul_retires for r, _, _ in prepares)
        inconnus = sum(r.caracteres_inconnus > 0 for r, _, _ in prepares)
        if encodages:
            suivi.alerte(f"Encodage réparé dans {encodages} mails (UTF-8 relu en Latin-1)")
        if inconnus:
            suivi.alerte(f"{inconnus} mails contiennent des caractères illisibles (U+FFFD) non réparables")
        if nul:
            suivi.info(f"{nul} caractères NUL retirés")

        # 4. Templates
        suivi.etape("templates")
        reperage = reperer_templates(
            [nettoye for _, nettoye, _ in prepares],
            [objet for _, _, objet in prepares],
            p.templates,
            p.n_processus,
        )
        demandes = [
            Demande(
                numero=ligne.numero or "",
                titre=ligne.titre or "",
                mail=repare.texte,
                mail_nettoye=nettoye,
                objet=objet,
                template=tpl.template,
                marqueurs_template=tpl.marqueurs,
                date=ligne.date,
            )
            for ligne, (repare, nettoye, objet), tpl in zip(gardees, prepares, reperage.resultats, strict=True)
        ]
        raisons = Counter(r.raison for r in reperage.resultats if r.template)
        nb_templates = sum(raisons.values())
        part = nb_templates / len(demandes) if demandes else 0.0
        suivi.info(
            f"{nb_templates} mails issus d'un template ({part:.0%}), {len(reperage.marqueurs)} marqueurs fixes",
            raisons=dict(raisons),
        )

        # 5. Cartographie et référence figée
        suivi.etape("cartographie")
        carto = cartographier(demandes)
        petites = petites_categories(carto, p.min_par_titre)
        reference = self.referentiel.lire_reference()
        reference_creee = False
        if not reference or nouvelle_reference:
            self.referentiel.figer_reference(carto)
            reference_creee = True
            ecart = EcartReferentiel((), ())
            suivi.info(f"Référence des Titres figée sur cet export ({len(carto)} Titres)")
        else:
            ecart = comparer((e.titre for e in reference), (e.titre for e in carto))
            if ecart.nouveaux:
                suivi.alerte(f"{len(ecart.nouveaux)} Titres absents de la référence", titres=list(ecart.nouveaux))
            if ecart.disparus:
                suivi.alerte(f"{len(ecart.disparus)} Titres de la référence ont disparu", titres=list(ecart.disparus))
        if petites:
            suivi.info(
                f"{len(petites)} Titres ont moins de {p.min_par_titre} demandes : exclus de l'apprentissage",
                titres=[e.titre for e in petites],
            )

        fichiers = self._ecrire_artefacts(ecartees, carto, petites, ecart, demandes, reperage, reperage.resultats)

        # 6. Enregistrement en base
        suivi.etape("enregistrement")
        dates_absentes = sum(d.date is None for d in demandes)
        resultat = ResultatChargement(
            import_id=0,
            fichier=str(chemin),
            nb_lignes=len(lignes),
            nb_retenues=len(demandes),
            nb_ecartees=len(ecartees),
            motifs_ecart=dict(motifs),
            encodages_repares=encodages,
            nul_retires=nul,
            mails_caracteres_inconnus=inconnus,
            dates_absentes=dates_absentes,
            nb_titres=len(carto),
            nb_titres_apprentissage=len(carto) - len(petites),
            petites_categories=[e.titre for e in petites],
            nb_templates=nb_templates,
            raisons_template=dict(raisons),
            nb_marqueurs=len(reperage.marqueurs),
            reference_creee=reference_creee,
            titres_nouveaux=list(ecart.nouveaux),
            titres_disparus=list(ecart.disparus),
            fichiers=fichiers,
        )
        resultat.import_id = self.corpus.remplacer_corpus(
            str(chemin), empreinte_fichier(chemin), len(lignes), demandes, ecartees, resultat.en_dict()
        )
        self.artefacts.ecrire_json(f"{DOSSIER}/bilan_chargement.json", resultat.en_dict())
        message = (
            f"Chargement terminé : {resultat.nb_retenues} demandes, {resultat.nb_titres} Titres "
            f"({resultat.nb_titres_apprentissage} pour l'apprentissage)"
        )
        if etapes_suivantes:
            suivi.info(message, import_id=resultat.import_id)
        else:
            suivi.terminer(message, import_id=resultat.import_id)
        return resultat

    def _ecrire_artefacts(self, ecartees, carto, petites, ecart, demandes, reperage, resultats) -> dict[str, str]:
        a = self.artefacts
        f: dict[str, str] = {}
        f["lignes_ecartees"] = str(
            a.ecrire_csv(
                f"{DOSSIER}/lignes_ecartees.csv",
                ["ligne_source", "numero", "motif", "detail"],
                ((e.ligne_source, e.numero or "", e.motif.value, e.detail) for e in ecartees),
            )
        )
        lignes_carto = [
            (e.titre, e.nb_demandes, _date(e.premiere_date), _date(e.derniere_date)) for e in carto
        ]
        entetes_carto = ["titre", "nb_demandes", "premiere_date", "derniere_date"]
        f["cartographie"] = str(a.ecrire_csv(f"{DOSSIER}/cartographie_titres.csv", entetes_carto, lignes_carto))
        f["petites_categories"] = str(
            a.ecrire_csv(
                f"{DOSSIER}/petites_categories.csv",
                entetes_carto,
                ((e.titre, e.nb_demandes, _date(e.premiere_date), _date(e.derniere_date)) for e in petites),
            )
        )
        f["ecarts_referentiel"] = str(
            a.ecrire_csv(
                f"{DOSSIER}/ecarts_referentiel.csv",
                ["titre", "ecart"],
                [(t, "absent_de_la_reference") for t in ecart.nouveaux]
                + [(t, "disparu_de_l_export") for t in ecart.disparus],
            )
        )
        f["marqueurs_template"] = str(
            a.ecrire_csv(
                f"{DOSSIER}/marqueurs_template.csv",
                ["nature", "texte", "nb_mails"],
                [("ligne", m, n) for m, n in reperage.marqueurs.items()]
                + [("objet", o, n) for o, n in reperage.objets_fixes.items()],
            )
        )
        f["templates_par_mail"] = str(
            a.ecrire_csv(
                f"{DOSSIER}/templates_par_mail.csv",
                ["numero", "titre", "template", "raison", "marqueurs"],
                (
                    (d.numero, d.titre, int(r.template), r.raison, " | ".join(r.marqueurs))
                    for d, r in zip(demandes, resultats, strict=True)
                ),
            )
        )
        return f


def _date(valeur) -> str:
    return valeur.date().isoformat() if valeur is not None else ""
