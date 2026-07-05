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
