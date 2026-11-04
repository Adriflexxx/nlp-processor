from demandes.domaine.controles import ecarter_lignes, normaliser_champ, reparer_texte
from demandes.domaine.demande import LigneBrute, MotifEcart


def test_reparation_du_double_encodage():
    r = reparer_texte("CrÃ©ation du compte, rÃ¨gle Ã  appliquer")
    assert r.texte == "Création du compte, règle à appliquer"
    assert r.encodage_repare


def test_un_texte_correct_n_est_pas_touche():
    r = reparer_texte("Création d'un accès à l'écran « Gestion »")
    assert r.texte == "Création d'un accès à l'écran « Gestion »"
    assert not r.encodage_repare


def test_retrait_des_nul_et_comptage_des_caracteres_illisibles():
    r = reparer_texte("Bon\x00jour �")
    assert r.texte == "Bonjour �"
    assert r.nul_retires == 1
    assert r.caracteres_inconnus == 1


def test_normaliser_champ():
    assert normaliser_champ(12345.0) == "12345"
    assert normaliser_champ(float("nan")) is None
    assert normaliser_champ("  ") is None
    assert normaliser_champ(" DEM1 ") == "DEM1"


def test_ecarter_lignes_motifs_et_doublons():
    lignes = [
        LigneBrute(2, "A", "T1", "mail"),
        LigneBrute(3, None, "T1", "mail"),
        LigneBrute(4, "B", "T1", None),
        LigneBrute(5, "C", None, "mail"),
        LigneBrute(6, "A", "T2", "autre mail"),
    ]
    gardees, ecartees = ecarter_lignes(lignes)
    assert [g.numero for g in gardees] == ["A"]
    assert [(e.ligne_source, e.motif) for e in ecartees] == [
        (3, MotifEcart.NUMERO_VIDE),
        (4, MotifEcart.MAIL_VIDE),
        (5, MotifEcart.TITRE_VIDE),
        (6, MotifEcart.NUMERO_EN_DOUBLE),
    ]
    assert "ligne 2" in ecartees[-1].detail
