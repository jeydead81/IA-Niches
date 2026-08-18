"""Catégories Amazon suggérées — la donnée était déjà payée, personne ne la lisait.

Choisir ses deux catégories KDP est une décision de publication à part entière, et l'auteur
la prend aujourd'hui à l'aveugle. Or chaque `BsrInfo` du top porte déjà ses sous-catégories
de classement : les livres qui marchent dans un rayon DISENT dans quelles catégories ils
sont rangés. Agréger ces lignes coûte 0 $ et n'appelle aucun LLM.

Ce que la fonction NE fait pas, volontairement : recommander. Elle constate une fréquence
et un meilleur rang. « 3 livres du top sont rangés ici » est une observation ; « publie
ici » serait un conseil que rien dans la donnée ne soutient — les catégories du top sont
celles de livres DÉJÀ installés, pas forcément celles où une place est libre.
"""
from categories import suggerer_categories
from models import BsrInfo


def _bsr(asin, subs):
    return BsrInfo(rank_livres=1000, asin=asin,
                   subcategories=[{"category": c, "rank": r} for c, r in subs])


def test_la_frequence_prime_puis_le_meilleur_rang():
    """Une catégorie où 3 livres du top sont rangés pèse plus qu'une où un seul l'est,
    même très bien classé : la fréquence dit que le rayon y VIT."""
    bsrs = [
        _bsr("A1", [("Diabète", 12), ("Carnets et journaux", 300)]),
        _bsr("A2", [("Diabète", 40)]),
        _bsr("A3", [("Diabète", 8), ("Nutrition", 2)]),
    ]
    out = suggerer_categories(bsrs, n=3)
    assert out[0]["category"] == "Diabète"
    assert out[0]["n_livres"] == 3
    assert out[0]["meilleur_rang"] == 8


def test_a_frequence_egale_le_meilleur_rang_departage():
    bsrs = [_bsr("A1", [("Nutrition", 2), ("Carnets", 300)])]
    out = suggerer_categories(bsrs, n=3)
    assert [c["category"] for c in out] == ["Nutrition", "Carnets"]


def test_la_categorie_racine_et_le_lien_de_navigation_sont_ecartes():
    """« Livres » est la racine (aucune décision à y prendre) et « Voir les 100 premiers »
    est un lien de navigation qu'Amazon glisse dans le même bloc — pas une catégorie."""
    bsrs = [_bsr("A1", [("Livres", 194), ("Voir les 100 premiers en Livres", 1),
                        ("Diabète", 12)])]
    out = suggerer_categories(bsrs, n=5)
    assert [c["category"] for c in out] == ["Diabète"]


def test_la_liste_est_bornee_par_n():
    bsrs = [_bsr("A1", [(f"Cat{i}", i + 1) for i in range(10)])]
    assert len(suggerer_categories(bsrs, n=3)) == 3


def test_aucun_bsr_ne_conclut_rien():
    """Zéro suggestion n'est pas « aucune catégorie pertinente » : c'est une absence de
    mesure. La liste vide doit se lire comme telle en aval (§5.10)."""
    assert suggerer_categories([], n=3) == []
    assert suggerer_categories([_bsr("A1", [])], n=3) == []


def test_un_None_dans_la_liste_ne_fait_pas_tomber_le_calcul():
    """`resolve_bsrs` rend {asin: BsrInfo|None} : le None est le cas NORMAL d'un ASIN dont
    le classement n'a pas pu être lu, pas une anomalie."""
    assert suggerer_categories([None, _bsr("A1", [("Diabète", 12)])], n=3)[0]["n_livres"] == 1


def test_la_casse_et_les_espaces_ne_creent_pas_deux_categories():
    """Amazon n'est pas régulier sur la casse d'un même libellé ; deux entrées pour la
    même catégorie diviseraient la fréquence par deux et la feraient passer derrière."""
    bsrs = [_bsr("A1", [("Diabète", 12)]), _bsr("A2", [("diabète ", 40)])]
    out = suggerer_categories(bsrs, n=3)
    assert len(out) == 1 and out[0]["n_livres"] == 2
