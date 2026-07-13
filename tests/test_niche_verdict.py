from niche_verdict import generate_verdict, build_user_prompt
from models import ScoredNiche, SearchResult, SearchItem, NicheVerdict


def _sample_scored():
    return ScoredNiche(niche="stoïcisme pratique", requete_amazon="stoïcisme",
                       categorie="philosophie", global_score=8.0, demande=9.0,
                       penetration=6.0, compatibilite=8.0, verdict=None,
                       n_organic=16, n_concurrents_cibles=12, n_sponsored=4,
                       avg_rating=4.4, total_reviews=8000, bsr_best=2279,
                       bsr_top5_avg=21445, bsr_worst_top10=120000, criteres_bsr_ok=True,
                       top_asins=["A1", "A2"])


def test_build_user_prompt_contains_key_data():
    sr = SearchResult(keyword="stoïcisme", organic=[
        SearchItem(title="Petit manuel de stoïcisme", asin="A1"),
        SearchItem(title="Pensées de Marc Aurèle", asin="A2")])
    p = build_user_prompt(_sample_scored(), sr)
    assert "stoïcisme" in p and "2279" in p
    assert "Petit manuel de stoïcisme" in p
    assert "4" in p


def test_generate_verdict_forced_tool_use_and_usage():
    class _Usage:
        input_tokens = 900
        output_tokens = 1100

    class _Block:
        type = "tool_use"
        input = {"verdict": "Go", "confiance": 8, "facteur_decisif": "couverture pro",
                 "angles": [{"angle": "stoïcisme pour débutants", "pourquoi": "demande forte",
                             "risque": "niche connue", "titre": "Stoïcisme facile",
                             "sous_titre": "le guide du quotidien", "direction_couverture": "sobre",
                             "prix_suggere": "14,90 €", "requete_principale": "stoïcisme",
                             "requetes_secondaires": ["marc aurèle"]}],
                 "saturation": "moyenne", "faux_concurrent": "aucun",
                 "differenciation": "exécution"}

    class _Resp:
        content = [_Block()]
        usage = _Usage()

    class _Client:
        class messages:
            @staticmethod
            def create(**kw):
                assert kw["tool_choice"]["type"] == "tool"
                assert kw["tools"][0]["name"]
                return _Resp()

    seen = {}
    v = generate_verdict(_sample_scored(), search=None, client=_Client(),
                         model="claude-sonnet-5", on_usage=lambda i, o, m: seen.update(i=i, o=o))
    assert isinstance(v, NicheVerdict)
    assert v.verdict == "Go" and v.confiance == 8 and v.angles[0].titre == "Stoïcisme facile"
    assert seen == {"i": 900, "o": 1100}
