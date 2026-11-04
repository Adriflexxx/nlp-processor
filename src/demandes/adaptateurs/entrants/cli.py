"""Ligne de commande : une commande par étape du pipeline.

    uv run demandes --help
"""

from __future__ import annotations

import json
import re
import sys
import unicodedata
from datetime import date
from pathlib import Path

import typer

from demandes import adr as outils_adr

app = typer.Typer(help="Classification supervisée des demandes ITZME.", no_args_is_help=True, add_completion=False)
app_adr = typer.Typer(help="Décisions d'architecture immuables (docs/adr).", no_args_is_help=True)
app.add_typer(app_adr, name="adr")


def _conteneur():
    # Import tardif : les commandes ADR et synthetique n'ont besoin ni de la base ni de sklearn.
    from demandes.composition import Conteneur, configurer_journal

    conteneur = Conteneur()
    configurer_journal(conteneur.settings.niveau_log)
    return conteneur


@app.command()
def migrer() -> None:
    """Crée ou met à jour le schéma de la base."""
    c = _conteneur()
    try:
        appliquees = c.migrer()
        typer.echo(f"Migrations appliquées : {appliquees}" if appliquees else "Schéma déjà à jour.")
    finally:
        c.fermer()


@app.command()
def charger(
    fichier: Path = typer.Argument(..., exists=True, dir_okay=False, help="Export Excel des demandes"),
    nouvelle_reference: bool = typer.Option(False, help="Fige la cartographie de cet export comme nouvelle référence"),
    fiches: bool | None = typer.Option(
        None, "--fiches/--sans-fiches", help="Enchaîner sur les fiches et embeddings (défaut : FICHES_A_L_INGESTION)"
    ),
) -> None:
    """Ingestion : lecture, contrôles, cartographie, templates, puis fiches IAG par lots et embeddings."""
    c = _conteneur()
    try:
        c.migrer()
        tache, resultat = c.executeur.executer_maintenant(
            "charger", {"fichier": str(fichier), "nouvelle_reference": nouvelle_reference, "avec_fiches": fiches}
        )
        typer.echo(f"\nTâche {tache.id}")
        _afficher(resultat)
    finally:
        c.fermer()


def _afficher(resultat: dict) -> None:
    """Affiche un résultat de tâche : les valeurs, puis les fichiers produits."""
    fichiers: dict[str, str] = {}

    def sans_fichiers(valeur):
        if isinstance(valeur, dict):
            fichiers.update(valeur.get("fichiers", {}))
            return {k: sans_fichiers(v) for k, v in valeur.items() if k != "fichiers"}
        return valeur

    typer.echo(json.dumps(sans_fichiers(resultat), ensure_ascii=False, indent=2))
    if fichiers:
        typer.echo("Fichiers produits :")
        for nom, chemin in fichiers.items():
            typer.echo(f"  {nom:22} {chemin}")


@app.command("fiches")
def fiches_(
    reprendre_echecs: bool = typer.Option(False, help="Retenter aussi les demandes déjà journalisées en échec"),
) -> None:
    """Fiches IAG par lots et embeddings pour les demandes absentes du cache."""
    c = _conteneur()
    try:
        c.migrer()
        tache, resultat = c.executeur.executer_maintenant("fiches", {"reprendre_echecs": reprendre_echecs})
        typer.echo(f"\nTâche {tache.id}")
        _afficher(resultat)
    finally:
        c.fermer()


@app.command("controle-lots")
def controle_lots(taille: int = typer.Option(200, help="Nombre de demandes de l'échantillon")) -> None:
    """Contrôle qualité : fiches en lot comparées aux fiches à l'unité sur un échantillon."""
    c = _conteneur()
    try:
        c.migrer()
        tache, resultat = c.executeur.executer_maintenant("controle_lots", {"taille": taille})
        typer.echo(f"\nTâche {tache.id}")
        _afficher(resultat)
    finally:
        c.fermer()


@app.command()
def taches(limite: int = typer.Option(20, help="Nombre de tâches à afficher")) -> None:
    """Liste les dernières tâches (lancées par la CLI ou par l'API)."""
    c = _conteneur()
    try:
        for t in c.depot_taches.lister(limite):
            typer.echo(f"{t.id}  {t.type:10} {t.statut:10} {t.progression:5.0%}  {t.cree_le.astimezone():%Y-%m-%d %H:%M}  {t.message or ''}")
    finally:
        c.fermer()


@app.command()
def synthetique(
    sortie: Path = typer.Option(Path("donnees/synthetique.xlsx"), help="Fichier Excel à écrire"),
    nb: int = typer.Option(400, help="Nombre de demandes (hors anomalies et Titre rare)"),
    graine: int = typer.Option(42, help="Graine du générateur"),
) -> None:
    """Génère un export synthétique (quelques Titres, templates, anomalies) pour essayer la chaîne."""
    from demandes.synthetique import ecrire_excel, generer_demandes

    chemin = ecrire_excel(generer_demandes(nb, graine), sortie)
    typer.echo(f"Export synthétique écrit : {chemin}")


@app.command()
def api(port: int = 8000, reload: bool = False) -> None:
    """Lance l'API FastAPI (sans authentification : environnement de test)."""
    import uvicorn

    uvicorn.run("demandes.adaptateurs.entrants.api.app:app", host="0.0.0.0", port=port, reload=reload)


# --- ADR ---------------------------------------------------------------------


def _slug(titre: str) -> str:
    texte = unicodedata.normalize("NFKD", titre).encode("ascii", "ignore").decode().lower()
    return re.sub(r"[^a-z0-9]+", "-", texte).strip("-")[:60]


@app_adr.command("nouveau")
def adr_nouveau(
    titre: str,
    remplace: str = typer.Option("", help="Numéro(s) d'ADR remplacé(s), ex. 0003"),
) -> None:
    """Crée un ADR à partir du modèle (à rédiger, puis : demandes adr sceller)."""
    numero = outils_adr.prochain_numero()
    modele = (outils_adr.DOSSIER_ADR / "modele.md").read_text(encoding="utf-8")
    remplaces = ", ".join(f"ADR-{int(n):04d}" for n in re.findall(r"\d+", remplace)) or "—"
    contenu = (
        modele.replace("NNNN", numero).replace("{titre}", titre)
        .replace("{date}", date.today().isoformat()).replace("{remplace}", remplaces)
    )
    chemin = outils_adr.DOSSIER_ADR / f"{numero}-{_slug(titre)}.md"
    chemin.write_text(contenu, encoding="utf-8")
    typer.echo(f"ADR créé : {chemin}")


@app_adr.command("sceller")
def adr_sceller() -> None:
    """Scelle les nouveaux ADR et régénère l'index."""
    nouveaux = outils_adr.sceller()
    outils_adr.generer_index()
    typer.echo(f"ADR scellés : {nouveaux}" if nouveaux else "Aucun nouvel ADR à sceller.")


@app_adr.command("verifier")
def adr_verifier() -> None:
    """Échoue si un ADR scellé a été modifié ou supprimé (utilisé par le hook pre-commit)."""
    erreurs, non_scelles = outils_adr.verifier()
    for nom in non_scelles:
        typer.echo(f"À sceller : {nom} (demandes adr sceller)", err=True)
    for erreur in erreurs:
        typer.echo(f"ERREUR : {erreur}", err=True)
    if erreurs or non_scelles:
        raise typer.Exit(1)
    typer.echo("ADR : tout est scellé et intact.")


@app_adr.command("corriger")
def adr_corriger(numero: str, motif: str = typer.Option(..., help="Nature de la correction de forme")) -> None:
    """Accepte une correction de forme sur un ADR scellé (tracée dans errata.md)."""
    nom = outils_adr.corriger(numero, motif)
    outils_adr.generer_index()
    typer.echo(f"Correction de forme enregistrée pour {nom}")


@app_adr.command("index")
def adr_index() -> None:
    """Régénère docs/adr/README.md."""
    typer.echo(f"Index écrit : {outils_adr.generer_index()}")


if __name__ == "__main__":
    sys.exit(app())
