from fiction_serp_provider import fetch_fiction_shelf, search_param_for_niche
from models import FictionNiche, SearchResult, SearchItem, EnrichedBook
from cost_tracker import CostTracker


def _niche(sg="cosy_mystery", rayon="kindle"):
    return FictionNiche(sous_genre=sg, tropes=["animal_compagnon"], decor="ile",
                        rayon=rayon, query="cosy mystery chat ile")


def test_search_param_node_sinon_repli_rayon():
    assert search_param_for_niche(_niche()) == "rh=n:205566725031"          # node dispo
    assert search_param_for_niche(_niche("feel_good")) == "i=digital-text"  # pas de node -> rayon
    assert search_param_for_niche(_niche("feel_good", "papier")) == "i=stripbooks"


class _Prov:
    priority = 2
    location_code = 2250
    language_code = "fr_FR"

    def __init__(self):
        self.seen = {}

    def search(self, keyword, depth=100, books_only=True, search_param=None):
        self.seen["search_param"] = search_param
        return SearchResult(keyword=keyword, organic=[
            SearchItem(title="A", asin="A1"), SearchItem(title="B", asin="A2")], sponsored=[])

    def product_raw_batch(self, asins):
        self.seen["asins"] = list(asins)
        return {a: {"asin": a, "items": [{"type": "amazon_product_info", "data_asin": a,
                                          "title": f"Titre {a}"}]} for a in asins}


def test_fetch_shelf_contraint_enrichit_et_compte_le_cout():
    cost = CostTracker()
    prov = _Prov()
    books = fetch_fiction_shelf(_niche(), provider=prov, n_top=2, cost=cost, cache=None)
    assert prov.seen["search_param"] == "rh=n:205566725031"
    assert prov.seen["asins"] == ["A1", "A2"]
    assert [b.asin for b in books] == ["A1", "A2"]
    assert all(isinstance(b, EnrichedBook) for b in books)
    assert books[0].serp_position == 1 and books[1].serp_position == 2
    b = cost.breakdown()
    assert b["dataforseo_calls"] == 3            # 1 SERP + 2 ASIN


def test_fetch_shelf_utilise_le_cache(tmp_path):
    from cache import Cache
    c = Cache(tmp_path / "c.db")
    c.set_book("A1", 2250, EnrichedBook(asin="A1", title="EN CACHE", serp_position=9), ttl_s=100)
    cost = CostTracker()
    prov = _Prov()
    books = fetch_fiction_shelf(_niche(), provider=prov, n_top=2, cost=cost, cache=c)
    assert prov.seen["asins"] == ["A2"]                  # A1 servi par le cache
    assert {b.asin for b in books} == {"A1", "A2"}
    assert next(b for b in books if b.asin == "A1").title == "EN CACHE"
    assert next(b for b in books if b.asin == "A1").serp_position == 1   # position du run
    assert cost.breakdown()["dataforseo_calls"] == 2     # 1 SERP + 1 ASIN seulement
