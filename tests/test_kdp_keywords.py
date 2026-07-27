"""test_kdp_keywords.py — les 7 mots-clés backend KDP.

Les contraintes de KDP sont DURES (7 emplacements, 50 caractères, termes proscrits) et un
modèle les oublie sous pression : elles sont donc vérifiées côté code, comme la taxonomie
l'est dans fiction_ideator."""
from kdp_keywords import LIMITE_CARACTERES, TERMES_INTERDITS, nettoyer_candidats


def test_un_emplacement_ne_depasse_jamais_50_caracteres():
    """Contrainte dure de KDP : au-delà, Amazon tronque en SILENCE et l'auteur perd la fin
    de son expression sans jamais le savoir."""
    gardes, rejets = nettoyer_candidats(["a" * 60, "roman policier village breton"], titre="")
    assert all(len(k) <= LIMITE_CARACTERES for k in gardes)
    assert "roman policier village breton" in gardes
    assert any("50" in motif for _, motif in rejets)


def test_les_termes_interdits_par_kdp_sont_ecartes():
    """« livre », « kindle », « gratuit », « meilleur »… sont proscrits par les conditions
    KDP ou déjà indexés par Amazon. Les demander au prompt ne suffit pas."""
    gardes, rejets = nettoyer_candidats(
        ["meilleur livre policier", "kindle gratuit", "enquête village breton"], titre="")
    assert gardes == ["enquête village breton"]
    assert len(rejets) == 2


def test_les_mots_du_titre_ne_sont_pas_regaspilles():
    """Amazon indexe déjà titre et sous-titre : redonner ces mots gâche un emplacement sur
    les sept, qui sont la ressource rare."""
    gardes, _ = nettoyer_candidats(
        ["cosy mystery bretagne", "enquête pâtissière village"],
        titre="Cosy Mystery en Bretagne")
    assert gardes == ["enquête pâtissière village"]


def test_les_doublons_la_casse_et_les_espaces_sont_normalises():
    gardes, _ = nettoyer_candidats(
        ["Enquête Village", "enquête village", "  enquête   village  "], titre="")
    assert len(gardes) == 1


def test_chaque_rejet_porte_son_motif():
    """Un mot-clé écarté sans explication est une décision invisible (CLAUDE.md §10)."""
    _, rejets = nettoyer_candidats(["meilleur livre"], titre="")
    assert rejets and all(isinstance(m, str) and m for _, m in rejets)


def test_les_termes_interdits_sont_documentes_et_non_vides():
    assert "livre" in TERMES_INTERDITS and "kindle" in TERMES_INTERDITS
