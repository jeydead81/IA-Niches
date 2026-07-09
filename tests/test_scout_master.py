from scout_master import run_scout
from cost_tracker import CostTracker
from models import NicheCandidate, NicheValidation, SearchResult, SearchItem, BsrInfo


def _fake_ideate(seed, signals, n, model, on_usage=None):
    if on_usage:
        on_usage(1000, 1200, model or "claude-sonnet-5")
    return [
        NicheCandidate(niche="tarot", requete_amazon="tarot", rationale="r", categorie="éso"),
        NicheCandidate(niche="mort", requete_amazon="zzzz", rationale="r", categorie="x"),
    ]


def _fake_validate(cands, **kw):
    return [
        NicheValidation(niche="tarot", requete_amazon="tarot", categorie="éso",
                        demand_score=6, validated=True),
        NicheValidation(niche="mort", requete_amazon="zzzz", categorie="x",
                        demand_score=0, validated=False),
    ]


class _FakeProvider:
    priority = 2
    location_code = 2250
    language_code = "fr_FR"

    def search(self, q, books_only=True):
        return SearchResult(keyword=q, sponsored=[], organic=[
            SearchItem(title="Tarot débutant", asin="A1", rating=4.5, reviews_count=6000),
            SearchItem(title="Tarot de marseille", asin="A2", rating=4.3, reviews_count=200),
        ])


def _fake_bsr(asin):
    return {"A1": BsrInfo(rank_livres=3000, asin="A1"),
            "A2": BsrInfo(rank_livres=60000, asin="A2")}.get(asin)


def test_run_scout_end_to_end_mocked():
    cost = CostTracker()
    res = run_scout(seed="ésotérisme", n_search=3, bsr_pause=0, use_cache=False, cost=cost,
                    ideate=_fake_ideate, validate=_fake_validate,
                    provider=_FakeProvider(), fetch_bsr_fn=_fake_bsr)
    assert len(res) == 1
    s = res[0]
    assert s.niche == "tarot" and s.n_organic == 2 and s.top_asins == ["A1", "A2"]
    assert s.bsr_best == 3000 and s.criteres_bsr_ok is True
    assert 1.0 <= s.global_score <= 10.0
    assert cost.breakdown()["llm_tokens_in"] == 1000


def test_run_scout_no_validated_returns_empty():
    def validate_none(cands, **kw):
        return [NicheValidation(niche="x", requete_amazon="x", categorie="c",
                                demand_score=0, validated=False)]
    res = run_scout(seed="x", ideate=_fake_ideate, validate=validate_none,
                    provider=_FakeProvider(), fetch_bsr_fn=_fake_bsr, bsr_pause=0, use_cache=False)
    assert res == []
