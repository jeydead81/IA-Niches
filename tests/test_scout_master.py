from scout_master import run_scout
from cost_tracker import CostTracker
from models import NicheCandidate, NicheValidation, SearchResult, SearchItem, BsrInfo, NicheVerdict


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


def _fake_verdict(scored, search=None, model=None, on_usage=None):
    if on_usage:
        on_usage(500, 400, model or "claude-sonnet-5")
    return NicheVerdict(verdict="Go", confiance=8, facteur_decisif="exécution",
                        angles=[], saturation="non", faux_concurrent="aucun",
                        differenciation="exécution")


def test_run_scout_end_to_end_mocked():
    cost = CostTracker()
    res = run_scout(seed="ésotérisme", n_search=3, bsr_pause=0, use_cache=False, cost=cost,
                    ideate=_fake_ideate, validate=_fake_validate, provider=_FakeProvider(),
                    fetch_bsr_fn=_fake_bsr, verdict_fn=_fake_verdict, n_verdict=1)
    assert len(res) == 1
    s = res[0]
    assert s.niche == "tarot" and s.bsr_best == 3000 and s.criteres_bsr_ok is True
    assert s.verdict is not None and s.verdict.verdict == "Go"
    assert cost.breakdown()["llm_tokens_in"] == 1000 + 500


def test_run_scout_verdict_off_when_n_verdict_zero():
    res = run_scout(seed="x", n_search=3, bsr_pause=0, use_cache=False, n_verdict=0,
                    ideate=_fake_ideate, validate=_fake_validate, provider=_FakeProvider(),
                    fetch_bsr_fn=_fake_bsr, verdict_fn=_fake_verdict)
    assert res and res[0].verdict is None


def test_run_scout_no_validated_returns_empty():
    def validate_none(cands, **kw):
        return [NicheValidation(niche="x", requete_amazon="x", categorie="c",
                                demand_score=0, validated=False)]
    res = run_scout(seed="x", ideate=_fake_ideate, validate=validate_none,
                    provider=_FakeProvider(), fetch_bsr_fn=_fake_bsr, bsr_pause=0, use_cache=False)
    assert res == []


def test_aucun_verdict_genere_par_defaut():
    """Mesuré : un verdict coûte 0,0283 $ et 3 verdicts font 78 % du coût d'un run — payés
    pour les 3 premières niches alors que l'utilisateur n'en lit qu'une. Le défaut est
    donc 0 : le verdict se demande sur la niche choisie.

    `assert res` d'ABORD : sans lui, ce test passerait à vide si le scout ne rendait
    aucune niche — il ne prouverait alors rien du tout (piège vérifié en conditions
    réelles : une première version de ce test validait un code jamais modifié)."""
    appels = []
    res = run_scout(seed="ésotérisme", n_search=3, bsr_pause=0, use_cache=False,
                    ideate=_fake_ideate, validate=_fake_validate, provider=_FakeProvider(),
                    fetch_bsr_fn=_fake_bsr,
                    verdict_fn=lambda *a, **k: appels.append(1))
    assert res, "le scout n'a rendu aucune niche : le test ne prouverait rien"
    assert appels == []                      # aucun verdict payé sans qu'on l'ait demandé
    assert all(r.verdict is None for r in res)
