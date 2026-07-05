from demo_free import format_report
from models import BsrInfo


def test_format_report():
    txt = format_report(
        prefix="tarot",
        suggestions=["tarot", "tarot divinatoire"],
        bsr=BsrInfo(asin="X", rank_livres=23372,
                    subcategories=[{"category": "Sciences infirmières", "rank": 13}]),
    )
    assert "tarot divinatoire" in txt
    assert "23372" in txt or "23 372" in txt
    assert "Sciences infirmières" in txt
