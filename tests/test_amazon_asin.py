import json
from pathlib import Path

from search_providers import parse_asin_bsr
from models import BsrInfo

_FIX = json.loads((Path(__file__).parent / "fixtures" / "asin_fr.json").read_text(encoding="utf-8"))


def test_parse_asin_bsr_rank_livres():
    info = parse_asin_bsr(_FIX)
    assert isinstance(info, BsrInfo)
    assert info.rank_livres == 194
    assert info.asin == "2080700162"
    cats = [s["category"].lower() for s in info.subcategories]
    assert not any(c == "livres" or "voir les" in c for c in cats)
    assert any("philosophie" in c for c in cats)


def test_parse_asin_bsr_thousands_separator():
    fix = {"items": [{"type": "amazon_product_info", "data_asin": "X",
                      "product_information": [{"type": "product_information_details_item",
                        "body": {"Classement des meilleures ventes d'Amazon": "12 345 en Livres"}}]}]}
    assert parse_asin_bsr(fix).rank_livres == 12345


def test_parse_asin_bsr_non_book_returns_none():
    fix = {"items": [{"type": "amazon_product_info", "data_asin": "Y",
                      "product_information": [{"type": "product_information_details_item",
                        "body": {"Piles": "3 LR03"}}]}]}
    assert parse_asin_bsr(fix) is None


def test_parse_asin_bsr_empty():
    assert parse_asin_bsr({}) is None
