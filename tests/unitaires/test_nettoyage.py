from demandes.apprentissage.nettoyage import extraire_objet, nettoyer_mail


def test_retrait_html_et_espaces():
    texte = "<html><body><p>Bonjour,</p><p>Merci de&nbsp;créer   le compte</p><br>Objet : x</body></html>"
    nettoye = nettoyer_mail(texte)
    assert "<" not in nettoye
    assert "Merci de créer le compte" in nettoye


def test_retrait_des_mentions_legales_mais_pas_de_l_en_tete():
    texte = (
        "De : a@b.fr\nObjet : Accès FACTO\n\nBonjour, merci d'ouvrir l'accès.\n\n"
        "Ce message et toutes les pièces jointes sont confidentiels et établis à l'intention exclusive."
    )
    nettoye = nettoyer_mail(texte)
    assert nettoye.startswith("De : a@b.fr\nObjet : Accès FACTO")
    assert "confidentiels" not in nettoye


def test_extraire_objet_sans_prefixes():
    assert extraire_objet("De : x\nObjet : RE: TR: Export FACTO vide\n\nBonjour") == "Export FACTO vide"
    assert extraire_objet("Bonjour, pas d'en-tête") is None
