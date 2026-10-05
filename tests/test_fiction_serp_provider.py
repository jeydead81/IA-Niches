from fiction_serp_provider import (enrich_asins, fetch_fiction_shelf, fetch_shelf_asins,
                                   search_param_for_niche)
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
    shelf = fetch_fiction_shelf(_niche(), provider=prov, n_top=2, cost=cost, cache=None)
    books = shelf.books
    assert prov.seen["search_param"] == "rh=n:205566725031"
    assert prov.seen["asins"] == ["A1", "A2"]
    assert [b.asin for b in books] == ["A1", "A2"]
    assert all(isinstance(b, EnrichedBook) for b in books)
    assert books[0].serp_position == 1 and books[1].serp_position == 2
    assert shelf.asins_demandes == 2 and shelf.n_echecs == 0 and shelf.complet is True
    b = cost.breakdown()
    assert b["dataforseo_calls"] == 3            # 1 SERP + 2 ASIN


def test_fetch_shelf_deduplique_les_asins_repetes_dans_la_serp():
    # Une SERP qui répète un ASIN (produit sponsorisé + organique, pagination qui se
    # chevauche…) le ferait payer deux fois, rendrait le même livre deux fois, et lui
    # attribuerait la DERNIÈRE position au lieu de la première.
    class _ProvDupliquee(_Prov):
        def search(self, keyword, depth=100, books_only=True, search_param=None):
            self.seen["search_param"] = search_param
            return SearchResult(keyword=keyword, organic=[
                SearchItem(title="A", asin="A1"),
                SearchItem(title="B", asin="A2"),
                SearchItem(title="A bis", asin="A1")], sponsored=[])

    cost = CostTracker()
    prov = _ProvDupliquee()
    shelf = fetch_fiction_shelf(_niche(), provider=prov, n_top=20, cost=cost, cache=None)
    books = shelf.books
    assert prov.seen["asins"] == ["A1", "A2"]              # 2 ASIN postés, pas 3
    assert [b.asin for b in books] == ["A1", "A2"]          # 2 livres rendus
    assert next(b for b in books if b.asin == "A1").serp_position == 1   # 1re occurrence


def test_fetch_shelf_utilise_le_cache(tmp_path):
    from cache import Cache
    c = Cache(tmp_path / "c.db")
    c.set_book("A1", 2250, EnrichedBook(asin="A1", title="EN CACHE", serp_position=9), ttl_s=100)
    cost = CostTracker()
    prov = _Prov()
    shelf = fetch_fiction_shelf(_niche(), provider=prov, n_top=2, cost=cost, cache=c)
    books = shelf.books
    assert prov.seen["asins"] == ["A2"]                  # A1 servi par le cache
    assert {b.asin for b in books} == {"A1", "A2"}
    assert next(b for b in books if b.asin == "A1").title == "EN CACHE"
    assert next(b for b in books if b.asin == "A1").serp_position == 1   # position du run
    assert cost.breakdown()["dataforseo_calls"] == 2     # 1 SERP + 1 ASIN seulement


class _ProvAvecEchec(_Prov):
    """A2 échoue à l'enrichissement (payload absent, ex. task DataForSEO jamais résolue)."""

    def product_raw_batch(self, asins):
        self.seen["asins"] = list(asins)
        out = {}
        for a in asins:
            if a == "A2":
                out[a] = None
            else:
                out[a] = {"asin": a, "items": [{"type": "amazon_product_info", "data_asin": a,
                                                "title": f"Titre {a}"}]}
        return out


def test_fetch_shelf_signale_les_echecs_denrichissement_au_lieu_de_les_droper_en_silence():
    # Un ASIN qui ne s'enrichit pas est aujourd'hui droppé sans trace, après facturation :
    # un rayon amputé (ou vide) se lit en aval comme "niche déserte = place à prendre",
    # faux signal interdit par CLAUDE.md §10. Le rayon doit porter ses compteurs d'échec.
    prov = _ProvAvecEchec()
    msgs = []
    shelf = fetch_fiction_shelf(_niche(), provider=prov, n_top=2, cost=None, cache=None,
                                progress=msgs.append)
    assert shelf.niche.sous_genre == "cosy_mystery"
    assert shelf.search_param == "rh=n:205566725031"
    assert [b.asin for b in shelf.books] == ["A1"]        # A2 absent, mais compté ci-dessous
    assert shelf.asins_demandes == 2
    assert shelf.n_echecs == 1
    assert shelf.complet is False
    assert any("1" in m for m in msgs)                    # avertissement émis via progress()


def test_fetch_shelf_complet_quand_aucun_echec():
    prov = _Prov()
    shelf = fetch_fiction_shelf(_niche(), provider=prov, n_top=2, cost=None, cache=None)
    assert shelf.asins_demandes == 2 and shelf.n_echecs == 0
    assert shelf.complet is True


class _ProvLarge(_Prov):
    """SERP à 20 organiques distincts : sert à vérifier où se coupe le rayon par défaut."""

    def search(self, keyword, depth=100, books_only=True, search_param=None):
        self.seen["search_param"] = search_param
        items = [SearchItem(title=f"T{i}", asin=f"B{i}") for i in range(20)]
        return SearchResult(keyword=keyword, organic=items, sponsored=[])


def test_fetch_shelf_n_top_vaut_10_par_defaut():
    """Le signal concurrentiel est dans les premiers résultats ; les suivants coûtent 0,003 $
    chacun pour peu d'apport. 12 jusqu'au 2026-10-05, 10 sur décision de Baptiste (un run de 5
    niches : 52 fiches, 81 % du coût DataForSEO)."""
    cost = CostTracker()
    shelf = fetch_fiction_shelf(_niche(), provider=_ProvLarge(), cost=cost, cache=None)
    assert shelf.asins_demandes == 10
    assert len(shelf.books) == 10


def test_fetch_shelf_n_top_20_reste_possible():
    """Le compromis (price_band/series_share plus bruités sur 12 livres) doit rester
    contournable niche par niche via n_top=20."""
    cost = CostTracker()
    shelf = fetch_fiction_shelf(_niche(), provider=_ProvLarge(), n_top=20, cost=cost, cache=None)
    assert shelf.asins_demandes == 20
    assert len(shelf.books) == 20


# --- M6-1 : scission SERP / enrichissement (fetch_fiction_shelf = composition des deux) ---

def test_serp_half_rend_les_asins_sans_enrichir():
    """La moitié SERP est rapide et sans file d'attente : c'est elle qu'on veut appeler
    N fois avant de payer UNE seule fois la file ASIN."""
    prov = _Prov()
    sp, asins = fetch_shelf_asins(_niche(), provider=prov, n_top=12, cost=CostTracker())
    assert sp == "rh=n:205566725031"
    assert asins == ["A1", "A2"]
    assert prov.seen.get("asins") is None          # aucun enrichissement déclenché


def test_enrich_half_batche_et_cache():
    prov = _Prov()
    cost = CostTracker()
    out = enrich_asins(["A1", "A2"], provider=prov, cache=None, cost=cost)
    assert set(out) == {"A1", "A2"} and prov.seen["asins"] == ["A1", "A2"]
    assert cost.breakdown()["dataforseo_calls"] == 2


def test_fetch_fiction_shelf_reste_la_composition_des_deux():
    """Contrat M2 inchangé — les appelants existants ne bougent pas."""
    shelf = fetch_fiction_shelf(_niche(), provider=_Prov(), n_top=12, cost=CostTracker())
    assert [b.asin for b in shelf.books] == ["A1", "A2"]
    assert shelf.books[0].serp_position == 1 and shelf.asins_demandes == 2
