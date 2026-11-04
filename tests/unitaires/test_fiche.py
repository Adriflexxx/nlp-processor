import jsonschema
import pytest

from demandes.domaine.fiche import SCHEMA_FICHE, texte_a_vectoriser

FICHE = {
    "objet_origine": "[Formulaire] PORTAIL RH - donner un accès",
    "template": True,
    "marqueurs_template": ["Type de demande :"],
    "application": "PORTAIL RH",
    "action": "donner_acces",
    "objet_action": "rôle gestionnaire",
    "elements_discriminants": ["habilitation", "rôle gestionnaire"],
    "resume": "Demande d'habilitation au rôle gestionnaire.",
}


def test_le_schema_est_valide_et_strict():
    jsonschema.Draft202012Validator.check_schema(SCHEMA_FICHE)
    jsonschema.validate(FICHE, SCHEMA_FICHE)
    with pytest.raises(jsonschema.ValidationError):
        jsonschema.validate({**FICHE, "titre_itzme": "x"}, SCHEMA_FICHE)  # champ en trop
    with pytest.raises(jsonschema.ValidationError):
        jsonschema.validate({**FICHE, "action": "deviner"}, SCHEMA_FICHE)
    with pytest.raises(jsonschema.ValidationError):
        jsonschema.validate({**FICHE, "elements_discriminants": []}, SCHEMA_FICHE)


def test_texte_a_vectoriser_ordre_fixe():
    texte = texte_a_vectoriser(FICHE)
    libelles = [ligne.split(" : ")[0] for ligne in texte.splitlines()]
    assert libelles == ["Objet", "Application", "Action", "Objet de l'action", "Éléments", "Résumé"]
    assert "template" not in texte.lower() or "Formulaire" in texte
