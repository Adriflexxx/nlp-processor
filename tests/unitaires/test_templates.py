from demandes.apprentissage.templates import ParametresTemplates, lignes_candidates, reperer_templates
from demandes.parallele import map_par_lots

GABARIT = "De : {p}\nObjet : demande {i}\n\nBonjour,\n\nType de demande : accès\nApplication concernée : SAGA {i}\nNom du bénéficiaire : X{i}\n\nCordialement,\n{p}\nService achats\nTél : 01 02"
LIBRE = "De : {p}\nObjet : souci {i}\n\nBonjour,\n\nPourriez-vous regarder l'export numéro {i} qui reste vide depuis hier ?\n\nCordialement,\n{p}\nService achats\nTél : 01 02"


def _corpus():
    textes, objets = [], []
    for i in range(20):
        p = "Claire Martin"  # même signature partout : elle ne doit pas faire un template
        gabarit = GABARIT if i % 2 == 0 else LIBRE
        textes.append(gabarit.format(p=p, i=i))
        objets.append(f"objet unique {i}")
    return textes, objets


def test_les_signatures_et_l_en_tete_ne_sont_pas_candidates():
    candidates = lignes_candidates(GABARIT.format(p="Claire Martin", i=1))
    assert "type de demande :" in candidates
    assert not any("claire" in c or "achats" in c or c.startswith("tél") for c in candidates)
    assert "objet :" not in candidates and "de :" not in candidates


def test_reperage_des_templates():
    textes, objets = _corpus()
    reperage = reperer_templates(textes, objets, ParametresTemplates(min_mails=5, freq_max=0.6, min_marqueurs=2))
    assert [r.template for r in reperage.resultats] == [i % 2 == 0 for i in range(20)]
    assert {"type de demande :", "application concernée :", "nom du bénéficiaire :"} <= set(reperage.marqueurs)


def test_formule_trop_frequente_ignoree():
    textes, objets = _corpus()
    # freq_max 30 % : les libellés présents dans 50 % des mails sont jugés banals.
    reperage = reperer_templates(textes, objets, ParametresTemplates(min_mails=5, freq_max=0.3, min_marqueurs=2))
    assert not any(r.template for r in reperage.resultats)


def test_objet_fixe_corrobore_par_un_marqueur_et_motif():
    textes, _ = _corpus()
    objets = ["[Formulaire] SAGA"] * 6 + [f"objet {i}" for i in range(14)]
    parametres = ParametresTemplates(min_mails=5, freq_max=0.6, min_marqueurs=99, motifs=(r"export numéro 13\b",))
    reperage = reperer_templates(textes, objets, parametres)
    raisons = [r.raison for r in reperage.resultats]
    # Objet fixe : template seulement pour les mails pairs, qui portent aussi des lignes fixes.
    assert raisons[:6] == ["objet", "", "objet", "", "objet", ""]
    assert raisons[13] == "motif"


def test_phrase_terminee_par_deux_points_n_est_pas_un_libelle():
    texte = "Bonjour,\nPourriez-vous traiter la demande suivante concernant FACTO : export vide\nType de demande : accès"
    candidates = lignes_candidates(texte)
    assert "type de demande :" in candidates
    assert not any(c.endswith(":") and c.startswith("pourriez") for c in candidates)


def test_parallele_identique_au_sequentiel():
    textes, _ = _corpus()
    textes = textes * 10
    assert map_par_lots(lignes_candidates, textes, 2, seuil=0) == [lignes_candidates(t) for t in textes]
