from models import BsrInfo


def test_bsrinfo_minimal():
    b = BsrInfo(rank_livres=23372)
    assert b.rank_livres == 23372
    assert b.asin is None
    assert b.subcategories == []


def test_bsrinfo_with_subcats():
    b = BsrInfo(
        asin="2266283340",
        rank_livres=23372,
        subcategories=[{"category": "Sciences infirmières", "rank": 13}],
    )
    assert b.subcategories[0]["rank"] == 13


def test_niche_verdict_and_scored_niche_field():
    from models import AngleAttaque, NicheVerdict, ScoredNiche
    a = AngleAttaque(angle="a", pourquoi="p", risque="r", titre="T", sous_titre="ST")
    v = NicheVerdict(verdict="Go", confiance=8, facteur_decisif="f", angles=[a],
                     saturation="non", faux_concurrent="aucun", differenciation="exécution")
    sc = ScoredNiche(niche="x", verdict=v)
    assert sc.verdict.verdict == "Go" and sc.verdict.angles[0].titre == "T"
    assert ScoredNiche(niche="y").verdict is None
    d = sc.model_dump()
    assert ScoredNiche.model_validate(d).verdict.confiance == 8
