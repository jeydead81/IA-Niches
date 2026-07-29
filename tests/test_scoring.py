from scoring import bsr_stats, count_targeted, score_niche
from models import NicheValidation, SearchResult, SearchItem


def test_bsr_stats_criteria_ok():
    s = bsr_stats([3000, 8000, 20000, 45000, 120000])
    assert s["best"] == 3000
    assert s["crit1"] and s["crit2"] and s["crit3"] and s["ok"] is True


def test_bsr_stats_no_place_a_prendre():
    s = bsr_stats([3000, 4000, 5000])          # tous bas, aucun > 50k
    assert s["crit1"] and s["crit2"]
    assert s["crit3"] is False and s["ok"] is False


def test_bsr_stats_empty():
    s = bsr_stats([])
    assert s["best"] is None and s["ok"] is False


def test_count_targeted():
    items = [SearchItem(title="Le Tarot de Marseille pour débutants"),
             SearchItem(title="Cuisine végétarienne facile"),
             SearchItem(title="Tarot divinatoire complet")]
    assert count_targeted("tarot", items) == 2


def test_score_niche_priority_when_criteria_ok():
    val = NicheValidation(niche="tarot", requete_amazon="tarot", categorie="ésotérisme",
                          demand_score=8, validated=True)
    organic = [SearchItem(title="Tarot débutant", asin="A1", rating=4.5, reviews_count=6000),
               SearchItem(title="Tarot de marseille", asin="A2", rating=4.2, reviews_count=300)]
    search = SearchResult(keyword="tarot", organic=organic, sponsored=[])
    sc = score_niche(val, search, bsrs=[3000, 9000, 60000])
    assert sc.criteres_bsr_ok is True
    assert sc.bsr_best == 3000
    assert sc.demande >= 7
    assert sc.top_asins == ["A1", "A2"]
    assert sc.global_score >= 7.5           # devrait ressortir prioritaire


def test_score_niche_without_search_data_stays_in_range():
    val = NicheValidation(niche="x", requete_amazon="x", categorie="c", demand_score=0)
    sc = score_niche(val, None, bsrs=[])
    assert sc.n_organic == 0 and sc.criteres_bsr_ok is False
    assert 1.0 <= sc.global_score <= 10.0


def test_bsr_stats_top3_place_a_prendre():
    # n_bsr=3 : ≥1 <10k, moyenne <50k, ≥1 >50k  -> §4.1 rempli sur 3 points
    s = bsr_stats([2279, 8000, 60000])
    assert s["best"] == 2279 and s["crit1"] and s["crit2"] and s["crit3"] and s["ok"]


def test_bsr_stats_top3_no_place():
    s = bsr_stats([2279, 4000, 9000])          # aucun >50k
    assert s["crit1"] and s["crit2"] and not s["crit3"] and not s["ok"]


# ── Absence de mesure ≠ verdict de marché (le pire défaut possible du produit) ──────

def test_une_niche_sans_concurrence_mesuree_ne_passe_pas_pour_penetrable():
    """DÉFAUT TROUVÉ EN REVUE. Quand la SERP échoue (solde DataForSEO épuisé, file en
    panne), `search` vaut None : zéro concurrent est alors compté, ce qui déclenchait le
    bonus « moins de 10 concurrents » (+2 en pénétration). Une niche dont RIEN n'a été
    mesuré ressortait à 6,88 « Intéressant » — le zéro de mesure lu comme « la place est
    libre ». C'est la faute cardinale du produit : présenter une absence de mesure comme
    un verdict de marché. Le moteur fiction a `non_mesurable` depuis M6 ; le non-fiction
    n'avait rien."""
    v = NicheValidation(niche="stoicisme applique", requete_amazon="stoicisme",
                        categorie="dev perso", demand_score=7, validated=True)
    r = score_niche(v, None, [])
    assert r.concurrence_mesuree is False
    assert "mesur" in r.priorite.lower(), (
        "le verdict doit DIRE que la concurrence n'a pas été mesurée")
    # Le bonus « peu de concurrents » ne doit pas naître d'une absence de données.
    mesuree_vide = score_niche(v, SearchResult(keyword="stoicisme"), [])
    assert r.penetration < mesuree_vide.penetration, (
        "un rayon non mesuré ne doit jamais mieux scorer qu'un rayon mesuré vide")


def test_un_rayon_mesure_et_reellement_vide_reste_une_bonne_nouvelle():
    """L'inverse du piège : une SERP qui répond et ne montre aucun concurrent ciblé est
    une VRAIE place à prendre. Il ne faut pas punir la mesure sous prétexte de corriger
    l'absence de mesure."""
    v = NicheValidation(niche="niche rare", requete_amazon="niche rare",
                        categorie="dev perso", demand_score=6, validated=True)
    r = score_niche(v, SearchResult(keyword="niche rare"), [])
    assert r.concurrence_mesuree is True
    assert "mesur" not in r.priorite.lower()
