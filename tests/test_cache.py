from cache import Cache


def test_set_get_roundtrip(tmp_path):
    c = Cache(tmp_path / "c.db")
    c.set("k", {"n": 1}, ttl_s=100)
    assert c.get("k") == {"n": 1}


def test_miss_returns_none(tmp_path):
    assert Cache(tmp_path / "c.db").get("absent") is None


def test_ttl_expiry(tmp_path):
    clock = {"t": 1000.0}
    c = Cache(tmp_path / "c.db", now=lambda: clock["t"])
    c.set("k", {"v": 1}, ttl_s=10)
    clock["t"] = 1005.0
    assert c.get("k") == {"v": 1}          # encore valide
    clock["t"] = 1020.0
    assert c.get("k") is None              # expiré


def test_bsr_helpers(tmp_path):
    from models import BsrInfo
    c = Cache(tmp_path / "c.db")
    c.set_bsr("A1", 2250, BsrInfo(rank_livres=194, asin="A1"), ttl_s=100)
    got = c.get_bsr("A1", 2250)
    assert got.rank_livres == 194 and got.asin == "A1"
    assert c.get_bsr("A2", 2250) is None


def test_search_helpers(tmp_path):
    from models import SearchResult, SearchItem
    c = Cache(tmp_path / "c.db")
    sr = SearchResult(keyword="tarot", organic=[SearchItem(title="x", asin="A1")])
    c.set_search("Tarot ", 2250, "fr_FR", sr, ttl_s=100)   # clé normalisée (lower+strip)
    got = c.get_search("tarot", 2250, "fr_FR")
    assert got.keyword == "tarot" and got.organic[0].asin == "A1"
