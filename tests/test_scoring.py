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
