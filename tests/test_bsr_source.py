from bsr_source import resolve_bsrs
from cost_tracker import CostTracker
from cache import Cache
from models import BsrInfo


def test_resolve_dedups_and_uses_fetch_fn():
    calls = []

    def fetch_fn(asin):
        calls.append(asin)
        return {"A1": BsrInfo(rank_livres=3000, asin="A1"),
                "A2": BsrInfo(rank_livres=60000, asin="A2")}.get(asin)

    out = resolve_bsrs(["A1", "A2", "A1"], fetch_bsr_fn=fetch_fn, bsr_pause=0)
    assert out["A1"].rank_livres == 3000 and out["A2"].rank_livres == 60000
    assert sorted(calls) == ["A1", "A2"]           # dédup : A1 une seule fois


def test_resolve_dataforseo_batch_counts_cost():
    class FakeProvider:
        priority = 2
        location_code = 2250
        def product_info_batch(self, asins):
            return {a: BsrInfo(rank_livres=100, asin=a) for a in asins}

    cost = CostTracker()
    out = resolve_bsrs(["A1", "A2"], source="dataforseo", provider=FakeProvider(),
                       cost=cost, bsr_priority=2)
    assert out["A1"].rank_livres == 100
    assert cost.breakdown()["dataforseo_calls"] == 2   # 2 lookups payés


def test_resolve_scrape_error_does_not_crash():
    def flaky(asin):
        if asin == "A2":
            raise RuntimeError("réseau indisponible")   # util.http_get relève après retries
        return BsrInfo(rank_livres=3000, asin=asin)

    out = resolve_bsrs(["A1", "A2"], fetch_bsr_fn=flaky, bsr_pause=0)
    assert out["A1"].rank_livres == 3000
    assert out["A2"] is None          # l'échec sur A2 -> None, le run continue (§11.11)


def test_resolve_cache_hit_no_network(tmp_path):
    c = Cache(tmp_path / "c.db")
    c.set_bsr("A1", 2250, BsrInfo(rank_livres=5, asin="A1"), ttl_s=100)

    def boom(asin):
        raise AssertionError("ne doit pas être appelé (cache hit)")

    out = resolve_bsrs(["A1"], fetch_bsr_fn=boom, cache=c, location=2250, bsr_pause=0)
    assert out["A1"].rank_livres == 5
