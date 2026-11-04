"""Génération d'un petit export synthétique pour les tests et les essais sans données réelles.

Quelques Titres, des mails issus de deux templates et des mails libres, des
signatures qui se répètent, et quelques anomalies volontaires (mail vide,
Titre vide, numéro en double, encodage cassé, HTML, mentions légales, NUL).
"""

from __future__ import annotations

import random
from datetime import datetime, timedelta
from pathlib import Path

import pandas as pd

# Titre → (application, action, mots propres au Titre)
TITRES: dict[str, tuple[str, str, list[str]]] = {
    "Création de compte SAGA": ("SAGA", "créer", ["nouvel arrivant", "création du compte", "identifiant", "profil"]),
    "Suppression de compte SAGA": ("SAGA", "supprimer", ["départ", "désactiver le compte", "fin de contrat", "clôture"]),
    "Habilitation PORTAIL RH": ("PORTAIL RH", "donner un accès", ["droits", "habilitation", "rôle gestionnaire", "accès"]),
    "Retrait d'habilitation PORTAIL RH": ("PORTAIL RH", "retirer un accès", ["retirer", "révoquer", "changement de poste", "plus besoin"]),
    "Anomalie export FACTO": ("FACTO", "signaler", ["export", "fichier vide", "erreur", "plantage", "message d'erreur"]),
    "Modification référentiel FACTO": ("FACTO", "modifier", ["référentiel", "code fournisseur", "mise à jour", "libellé"]),
    "Réinitialisation mot de passe SAGA": ("SAGA", "réinitialiser", ["mot de passe", "bloqué", "réinitialiser", "verrouillé"]),
    "Demande d'information INFOCENTRE": ("INFOCENTRE", "demander", ["indicateur", "tableau de bord", "requête", "chiffres"]),
}
# Titre rare : doit finir dans les petites catégories.
TITRE_RARE = "Purge historique ARCHIVE"

# Titres servis par un template de la société.
TEMPLATE_HABILITATION = (
    "Formulaire de demande d'habilitation applicative\n"
    "Type de demande : {action}\n"
    "Application concernée : {application}\n"
    "Nom du bénéficiaire : {personne}\n"
    "Service du bénéficiaire : {service}\n"
    "Date souhaitée : {date}\n"
    "Justification : {mots}\n"
)
TEMPLATE_COMPTE = (
    "Merci de compléter tous les champs de ce modèle avant envoi\n"
    "Opération sur compte : {action}\n"
    "Logiciel : {application}\n"
    "Matricule de l'agent : {matricule}\n"
    "Motif de la demande : {mots}\n"
)
AVEC_TEMPLATE = {
    "Habilitation PORTAIL RH": TEMPLATE_HABILITATION,
    "Retrait d'habilitation PORTAIL RH": TEMPLATE_HABILITATION,
    "Création de compte SAGA": TEMPLATE_COMPTE,
    "Suppression de compte SAGA": TEMPLATE_COMPTE,
}

PERSONNES = ["Claire Martin", "Hugo Bernard", "Inès Petit", "Lucas Moreau", "Sarah Lefèvre", "Nadia Roux"]
SERVICES = ["Direction financière", "Ressources humaines", "Achats", "Comptabilité fournisseurs"]
# Mails libres : composés de morceaux tirés au hasard, pour qu'aucune phrase entière
# ne revienne à l'identique dans beaucoup de mails (sinon ce serait un template).
OUVERTURES = [
    "Je me permets de vous solliciter", "Pourriez-vous m'aider", "J'aurais besoin de votre aide",
    "Je reviens vers vous", "Une petite demande de ma part", "Je vous écris", "Suite à notre échange téléphonique",
    "Comme convenu avec mon responsable", "Désolé de vous déranger", "Je vous sollicite en urgence",
]
LIAISONS = ["au sujet de", "concernant", "pour", "à propos de", "sur"]
DEMANDES = [
    "il faudrait {action} ce qui suit", "merci de {action} rapidement", "est-il possible de {action}",
    "je souhaite {action}", "pouvez-vous {action} dès que possible", "nous avons besoin de {action}",
]
PRECISIONS = [
    "C'est pour {personne} du service {service}.", "Le besoin date de {date}.", "Merci de me tenir au courant.",
    "Je reste disponible si besoin.", "C'est assez urgent pour l'équipe.", "", "", "",
]
MENTION_LEGALE = (
    "Ce message et toutes les pièces jointes sont confidentiels et établis à l'intention exclusive de ses destinataires."
)


def _signature(personne: str, service: str) -> str:
    return f"Cordialement,\n{personne}\n{service}\nTél : 01 23 45 67 {sum(map(ord, personne)) % 90 + 10}"


def _mail(rng: random.Random, titre: str, application: str, action: str, mots: list[str], date: datetime) -> str:
    personne, service = rng.choice(PERSONNES), rng.choice(SERVICES)
    choisis = ", ".join(rng.sample(mots, k=min(len(mots), rng.randint(2, 3))))
    valeurs = {
        "application": application, "action": action, "mots": choisis, "personne": rng.choice(PERSONNES),
        "service": rng.choice(SERVICES), "date": (date + timedelta(days=7)).strftime("%d/%m/%Y"),
        "matricule": f"A{rng.randint(10000, 99999)}",
    }
    gabarit = AVEC_TEMPLATE.get(titre)
    if gabarit and rng.random() < 0.8:
        objet = f"[Formulaire] {application} - {action}"
        corps = gabarit.format(**valeurs)
    else:
        objet = rng.choice(
            [f"{application} {rng.choice(mots)} {rng.randint(1, 999)}", f"{rng.choice(mots)} - {valeurs['personne']}",
             f"RE: {rng.choice(mots)} {valeurs['date']}", f"Question {application} ({rng.choice(mots)})"]
        )
        corps = (
            f"{rng.choice(OUVERTURES)} {rng.choice(LIAISONS)} {application}, "
            f"{rng.choice(DEMANDES).format(**valeurs)} ({choisis}). {rng.choice(PRECISIONS).format(**valeurs)}"
        ).strip()
    entete = f"De : {personne} <{personne.lower().replace(' ', '.')}@societe.fr>\nÀ : support@societe.fr\nObjet : {objet}\n"
    return f"{entete}\nBonjour,\n\n{corps}\n\n{_signature(personne, service)}"


def generer_demandes(nb: int = 400, graine: int = 42) -> pd.DataFrame:
    """DataFrame au format de l'export : numero, date, titre, description."""
    rng = random.Random(graine)
    debut = datetime(2025, 11, 1)
    titres = list(TITRES)
    lignes = []
    for i in range(nb):
        titre = titres[i % len(titres)]
        application, action, mots = TITRES[titre]
        date = debut + timedelta(days=rng.randint(0, 364), hours=rng.randint(8, 18))
        lignes.append(
            {"numero": f"DEM{100000 + i}", "date": date, "titre": titre,
             "description": _mail(rng, titre, application, action, mots, date)}
        )
    for j in range(4):  # Titre rare
        date = debut + timedelta(days=rng.randint(0, 364))
        lignes.append(
            {"numero": f"DEM{900000 + j}", "date": date, "titre": TITRE_RARE,
             "description": _mail(rng, TITRE_RARE, "ARCHIVE", "purger", ["purge", "historique", "volumétrie"], date)}
        )

    # Anomalies volontaires
    lignes[1]["description"] = lignes[1]["description"].replace("é", "Ã©").replace("è", "Ã¨")  # encodage cassé
    lignes[2]["description"] = (
        "<html><body><p>" + lignes[2]["description"].replace("\n", "<br>") + "</p></body></html>"
    )
    lignes[3]["description"] += "\n\n" + MENTION_LEGALE
    lignes[4]["description"] = lignes[4]["description"].replace("Bonjour", "Bon\x00jour")
    lignes.append({"numero": "DEM999990", "date": debut, "titre": titres[0], "description": "   "})
    lignes.append({"numero": "DEM999991", "date": debut, "titre": None, "description": "Bonjour, une demande sans titre."})
    lignes.append({"numero": lignes[0]["numero"], "date": debut, "titre": titres[1], "description": "Doublon de numéro."})
    return pd.DataFrame(lignes, columns=["numero", "date", "titre", "description"])


def ecrire_excel(df: pd.DataFrame, chemin: Path) -> Path:
    chemin.parent.mkdir(parents=True, exist_ok=True)
    # openpyxl refuse le caractère NUL dans une cellule : il est retiré à l'écriture.
    # Le cas NUL est testé directement sur le domaine et sur le cas d'usage.
    df = df.copy()
    df["description"] = df["description"].map(lambda v: v.replace("\x00", "") if isinstance(v, str) else v)
    df.to_excel(chemin, index=False, engine="openpyxl")
    return chemin
