"""Cas d'usage « rapport » : classement des combinaisons, graphiques et recommandation (ADR-0016)."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any

from demandes.application.entrainer import Entrainement
from demandes.ports.artefacts import Graphiques, StockageArtefacts
from demandes.ports.depots import DepotEvaluations
from demandes.ports.suivi import Suivi

NOMS_SPECIAUX = {"temporel", "controle_lots"}


@dataclass(frozen=True, slots=True)
class ParametresRapport:
    reference: str  # clé du modèle seul de référence
    gain_min: float
    modele_iag: str
    modele_embedding: str


def _v(valeur: Any, format_: str = ".3f") -> str:
    return "—" if valeur is None else format(valeur, format_)


def _gain(valeur: float | None) -> str:
    return "—" if valeur is None else f"{valeur * 100:+.1f} pt"


def _top1(e: dict, segment: str = "ensemble") -> float | None:
    return e["test"].get(segment, {}).get("top1")


def choisir_configuration(evaluations: list[dict], gain_min: float) -> tuple[dict, str]:
    """La plus légère des combinaisons qu'aucune plus lourde ne bat de plus de `gain_min`
    en exactitude top 1, ni sur l'ensemble, ni sur les mails libres."""
    ordonnees = sorted(evaluations, key=lambda e: (e["cout"], -(_top1(e) or 0)))
    for candidate in ordonnees:
        meilleures = []
        for autre in evaluations:
            if autre["cout"] <= candidate["cout"]:
                continue
            gain = (_top1(autre) or 0) - (_top1(candidate) or 0)
            gain_libre = (_top1(autre, "libre") or 0) - (_top1(candidate, "libre") or 0)
            if gain > gain_min or (_top1(candidate, "libre") is not None and gain_libre > gain_min):
                meilleures.append(autre["libelle"])
        if not meilleures:
            raison = (
                f"aucune combinaison plus lourde ne gagne plus de {gain_min * 100:.1f} point d'exactitude top 1, "
                "ni sur l'ensemble ni sur les mails libres"
            )
            return candidate, raison
    return ordonnees[-1], "toutes les combinaisons plus légères sont battues"


class Rapport:
    def __init__(
        self,
        entrainement: Entrainement,
        evaluations: DepotEvaluations,
        artefacts: StockageArtefacts,
        graphiques: Graphiques,
        parametres: ParametresRapport,
    ) -> None:
        self.entrainement = entrainement
        self.evaluations = evaluations
        self.artefacts = artefacts
        self.graphiques = graphiques
        self.parametres = parametres

    def executer(self, suivi: Suivi) -> dict[str, Any]:
        p = self.parametres
        suivi.demarrer(["lecture", "recommandation", "graphiques", "rédaction"])
        suivi.etape("lecture")
        jeu = self.entrainement.preparer_jeu()
        toutes = self.evaluations.lister_evaluations(jeu.empreinte)
        combis = [e for e in toutes if e["nom"] not in NOMS_SPECIAUX]
        if not combis:
            raise RuntimeError("aucune évaluation pour le jeu courant : lancer d'abord « evaluer »")
        temporel = next((e for e in toutes if e["nom"] == "temporel"), None)
        lot_unite = next((e for e in toutes if e["nom"] == "controle_lots"), None)
        classement = sorted(combis, key=lambda e: (-(_top1(e) or 0), -(e["test"]["ensemble"].get("top3") or 0)))
        suivi.info(f"{len(combis)} combinaisons évaluées pour le jeu {jeu.empreinte[:16]}")

        suivi.etape("recommandation")
        reference = next((e for e in combis if e["nom"] == f"seul__{p.reference}"), None) or min(
            combis, key=lambda e: (e["cout"], -(_top1(e) or 0))
        )
        retenue, raison = choisir_configuration(combis, p.gain_min)
        suivi.info(f"Configuration retenue : {retenue['libelle']} ({raison})")

        suivi.etape("graphiques")
        dossier = f"rapports/{jeu.empreinte[:16]}"
        courbes = {e["libelle"]: e["courbe_test"] for e in classement[:5]}
        for e in (reference, retenue):
            courbes.setdefault(e["libelle"], e["courbe_test"])
        g_courbes = self.graphiques.courbes_couverture(courbes, self.artefacts.chemin(f"{dossier}/couverture_precision.png"))
        g_fiab = self.graphiques.fiabilite(
            {e["libelle"]: e["fiabilite_test"] for e in {id(x): x for x in (retenue, reference)}.values()},
            self.artefacts.chemin(f"{dossier}/fiabilite.png"),
        )
        g_conf = None
        if retenue["confusion"]["titres"]:
            g_conf = self.graphiques.confusion(
                retenue["confusion"]["matrice"], retenue["confusion"]["titres"],
                self.artefacts.chemin(f"{dossier}/confusion.png"),
            )

        suivi.etape("rédaction")
        texte = self._rediger(jeu.resume(), classement, reference, retenue, raison, temporel, lot_unite, g_conf is not None)
        chemin = self.artefacts.ecrire_texte(f"{dossier}/rapport.md", texte)
        recommandation = {
            "nom": retenue["nom"], "libelle": retenue["libelle"], "mode": retenue["mode"], "modeles": retenue["modeles"],
            "seuils": retenue["seuils"], "raison": raison, "fait_appel_au_llm": retenue["fait_appel_au_llm"],
            "empreinte_jeu": jeu.empreinte,
        }
        self.artefacts.ecrire_json(f"{dossier}/recommandation.json", recommandation)
        suivi.terminer(f"Rapport écrit : {chemin}")
        return {
            "rapport": str(chemin),
            "recommandation": recommandation,
            "fichiers": {"rapport": str(chemin), "couverture": str(g_courbes), "fiabilite": str(g_fiab),
                         **({"confusion": str(g_conf)} if g_conf else {})},
        }

    # --- Rédaction -------------------------------------------------------------

    def _rediger(self, jeu, classement, reference, retenue, raison, temporel, lot_unite, avec_confusion) -> str:
        p = self.parametres
        L: list[str] = []
        L += [
            "# Rapport : classification du Titre des demandes ITZME",
            "",
            f"Généré le {datetime.now():%d/%m/%Y à %H:%M}. Jeu `{jeu['empreinte'][:16]}` : {jeu['n_demandes']} demandes, "
            f"{jeu['n_titres']} Titres, {jeu['n_entrainement']} pour l'entraînement et {jeu['n_test']} pour le test "
            f"(découpage {int((1 - jeu['taille_test']) * 100)}/{int(jeu['taille_test'] * 100)} stratifié, graine {jeu['seed']}). "
            f"Mails issus d'un template : {jeu['part_template']:.0%}.",
            "",
            f"Titres exclus de l'apprentissage (moins de {jeu['min_par_titre']} demandes) : "
            + (", ".join(jeu["titres_exclus"]) if jeu["titres_exclus"] else "aucun") + ".",
            "",
            f"Modèle IAG : `{p.modele_iag}` ; modèle d'embedding : `{p.modele_embedding}` ; "
            f"demandes avec vecteur : {jeu['n_avec_vecteur']}/{jeu['n_demandes']}.",
            "",
            "Toutes les mesures ci-dessous sont calculées sur le **jeu de test**, qui n'a servi à aucun réglage. "
            "Les seuils sont choisis en validation croisée sur l'entraînement.",
            "",
            "## Recommandation",
            "",
            f"**Configuration retenue : {retenue['libelle']}** (`MODE={retenue['mode']}`, "
            f"`MODELES={','.join(retenue['modeles'])}`). Raison : {raison}.",
            "",
            f"- Exactitude top 1 : {_v(_top1(retenue))} (mails libres : {_v(_top1(retenue, 'libre'))}, "
            f"templates : {_v(_top1(retenue, 'template'))}) ; top 3 : {_v(retenue['test']['ensemble'].get('top3'))}.",
            f"- Fait appel au LLM en production : {'oui (une fiche IAG et un embedding par mail)' if retenue['fait_appel_au_llm'] else 'non'}.",
            f"- Seuils ({'choisis sur la courbe couverture / précision' if retenue['seuils']['source'] == 'courbe' else 'fixés à la main'}) : "
            f"haut **{retenue['seuils']['haut']:.2f}** (un Titre mis en avant), moyen **{retenue['seuils']['moyen']:.2f}** (top 3).",
            "",
            "Effet attendu sur le test :",
            "",
            "| Niveau | Part des demandes | Précision top 1 | Précision top 3 |",
            "|---|---|---|---|",
        ]
        for niveau, libelle in (("haut", "Haut : Titre mis en avant"), ("moyen", "Moyen : top 3"), ("aucun", "Aucune proposition")):
            d = retenue["decisions_test"][niveau]
            L.append(f"| {libelle} | {d['part']:.0%} | {_v(d['precision_top1'])} | {_v(d['precision_top3'])} |")
        L += [
            "",
            f"À reporter dans le `.env` pour `predire` : `MODE={retenue['mode']}`, `MODELES={','.join(retenue['modeles'])}`"
            + (f", `SEUIL_HAUT={retenue['seuils']['haut']:.2f}`, `SEUIL_MOYEN={retenue['seuils']['moyen']:.2f}`" if retenue["seuils"]["source"] == "manuel" else "")
            + ".",
            "",
            "## Classement des combinaisons",
            "",
            f"Gains mesurés par rapport à la référence : **{reference['libelle']}**.",
            "",
            "| Rang | Combinaison | LLM en prod. | Top 1 | Top 3 | F1 macro | Log loss | Top 1 libres | Top 1 templates | Gain top 1 | Gain libres |",
            "|---|---|---|---|---|---|---|---|---|---|---|",
        ]
        for rang, e in enumerate(classement, start=1):
            t = e["test"]
            gain = None if _top1(e) is None else _top1(e) - (_top1(reference) or 0)
            gain_libre = None if _top1(e, "libre") is None or _top1(reference, "libre") is None else _top1(e, "libre") - _top1(reference, "libre")
            marque = " ✅" if e["nom"] == retenue["nom"] else ""
            L.append(
                f"| {rang} | {e['libelle']}{marque} | {'oui' if e['fait_appel_au_llm'] else 'non'} | {_v(t['ensemble'].get('top1'))} | "
                f"{_v(t['ensemble'].get('top3'))} | {_v(t['ensemble'].get('f1_macro'))} | {_v(t['ensemble'].get('logloss'))} | "
                f"{_v(t['libre'].get('top1'))} | {_v(t['template'].get('top1'))} | {_gain(gain)} | {_gain(gain_libre)} |"
            )
        L += [
            "",
            "## Graphiques",
            "",
            "![Couverture / précision](couverture_precision.png)",
            "",
            "![Fiabilité](fiabilite.png)",
            "",
        ]
        if avec_confusion:
            L += ["![Titres les plus confondus](confusion.png)", ""]
        L += ["## Paires de Titres les plus confondues (configuration retenue)", ""]
        if retenue["paires_confondues"]:
            L += ["| Titre vrai | Titre prédit | Nombre |", "|---|---|---|"]
            L += [f"| {x['vrai']} | {x['predit']} | {x['nombre']} |" for x in retenue["paires_confondues"]]
        else:
            L.append("Aucune erreur top 1 sur le test.")
        L += ["", "## Détail par combinaison", ""]
        for e in classement:
            L += [
                f"### {e['libelle']}",
                "",
                f"`{e['nom']}` ; paramètres : `{e['parametres']}` ; seuils haut {e['seuils']['haut']:.2f}, moyen {e['seuils']['moyen']:.2f} ; "
                f"désaccord des modèles sur le test : {e['part_desaccord_test']:.0%}.",
                "",
                "| Segment | n | Top 1 | Top 3 | F1 macro | Log loss | Brier | ECE |",
                "|---|---|---|---|---|---|---|---|",
            ]
            for seg, lib in (("ensemble", "Ensemble"), ("template", "Templates"), ("libre", "Libres")):
                m = e["test"][seg]
                L.append(
                    f"| {lib} | {m.get('n', 0)} | {_v(m.get('top1'))} | {_v(m.get('top3'))} | {_v(m.get('f1_macro'))} | "
                    f"{_v(m.get('logloss'))} | {_v(m.get('brier'))} | {_v(m.get('ece'))} |"
                )
            L.append("")
        if temporel:
            L += [
                "## Contrôle dans le temps",
                "",
                f"Entraînement sur les {temporel['n_entrainement']} demandes antérieures à {temporel['periode_test']}, "
                f"test sur les {temporel['n_test']} demandes de {temporel['periode_test']}, avec les paramètres retenus en "
                "validation croisée (les combinaisons en mode méta ne sont pas refaites).",
                "",
                "| Combinaison | Top 1 | Top 3 | Top 1 libres |",
                "|---|---|---|---|",
            ]
            L += [
                f"| {c['libelle']} | {_v(c['test']['ensemble'].get('top1'))} | {_v(c['test']['ensemble'].get('top3'))} | {_v(c['test']['libre'].get('top1'))} |"
                for c in temporel["combinaisons"]
            ]
            if temporel["titres_absents_avant"]:
                L += ["", "Titres du dernier mois absents des mois précédents : " + ", ".join(temporel["titres_absents_avant"]) + "."]
            L.append("")
        if lot_unite:
            L += [
                "## Contrôle lot / unité (rl_emb)",
                "",
                f"Sur {lot_unite['n']} demandes de test, `rl_emb` (entraîné sur des fiches produites en lot) obtient "
                f"{lot_unite['top1_fiches_en_lot']:.3f} d'exactitude top 1 avec les fiches en lot et "
                f"{lot_unite['top1_fiches_a_l_unite']:.3f} avec les fiches refaites à l'unité, comme en production "
                f"(écart {_gain(lot_unite['ecart'])}, accord des top 1 {lot_unite['accord_top1']:.0%}). "
                "Si l'écart est nettement négatif, réduire `FICHES_PAR_APPEL`.",
                "",
            ]
        return "\n".join(L)
