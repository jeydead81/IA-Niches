import json
from pathlib import Path

from search_providers import parse_asin_bsr, DataForSEOProvider
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


def test_product_info_batch_maps_asin_to_bsr():
    captured = {}

    def fake_post(url, body):
        captured["url"] = url
        captured["body"] = body
        return {"tasks": [{"status_code": 20100, "id": "TID1"},
                          {"status_code": 20100, "id": "TID2"}]}

    def fake_get(url):
        return {"tasks": [{"status_code": 20000, "result": [_FIX]}]}

    prov = DataForSEOProvider(login="l", password="p")
    out = prov.product_info_batch(["A1", "A2"], post_json=fake_post,
                                  get_json=fake_get, poll_interval=0)
    assert captured["url"].endswith("/asin/task_post")
    assert len(captured["body"]) == 2
    assert captured["body"][0]["location_code"] == 2250
    assert out["A1"].rank_livres == 194 and out["A2"].rank_livres == 194


def test_product_info_batch_empty():
    prov = DataForSEOProvider(login="l", password="p")
    assert prov.product_info_batch([], post_json=lambda u, b: {}, get_json=lambda u: {}) == {}
