import pytest

from search_providers import (map_dataforseo_result, DataForSEOProvider, get_provider)
from models import SearchResult

# Forme RÉELLE observée en live (merchant/amazon/products/task_get/advanced)
_RESULT = {
    "keyword": "tarot",
    "items": [
        {"type": "amazon_serp", "rank_absolute": 1, "data_asin": "B0DR231CVV",
         "title": "78 jeu tarot divinatoire", "url": "https://amazon.fr/dp/B0DR231CVV",
         "price_from": 11.99, "currency": "EUR",
         "rating": {"value": 4.1, "votes_count": 110}, "is_best_seller": False,
         "is_amazon_choice": True},
        {"type": "amazon_serp", "rank_absolute": 2, "data_asin": "B00XYZ0000",
         "title": "Le tarot pour débutants", "price_from": 9.5, "currency": "EUR",
         "rating": {"value": 4.6, "votes_count": 320}, "is_best_seller": True},
        {"type": "amazon_paid", "rank_absolute": 3, "data_asin": "B0BMN2P9PN",
         "title": "La magie du pendule", "price_from": 13.64, "currency": "EUR",
         "rating": {"value": 4.4, "votes_count": 172}},
        {"type": "related_searches", "items": ["tarot de marseille"]},
    ],
}


def test_map_splits_organic_and_sponsored():
    res = map_dataforseo_result(_RESULT)
    assert isinstance(res, SearchResult)
    assert res.keyword == "tarot"
    assert len(res.organic) == 2
    assert len(res.sponsored) == 1
    assert res.total_items == 4                      # inclut le related_searches ignoré
    o0 = res.organic[0]
    assert o0.asin == "B0DR231CVV"
    assert o0.rating == 4.1 and o0.reviews_count == 110
    assert o0.is_amazon_choice is True and o0.sponsored is False
    assert res.sponsored[0].sponsored is True
    assert res.sponsored[0].asin == "B0BMN2P9PN"


def test_map_handles_missing_rating():
    r = map_dataforseo_result({"keyword": "x", "items": [
        {"type": "amazon_serp", "data_asin": "A1", "title": "sans note"}]})
    assert r.organic[0].rating is None
    assert r.organic[0].reviews_count is None


def test_map_empty():
    r = map_dataforseo_result({})
    assert r.organic == [] and r.sponsored == [] and r.total_items == 0


def test_provider_search_posts_correct_body_and_maps():
    captured = {}

    def fake_post(url, body):
        captured["url"] = url
        captured["body"] = body
        return {"tasks": [{"status_code": 20100, "status_message": "Task Created", "id": "TID"}]}

    def fake_get(url):
        return {"tasks": [{"status_code": 20000, "result": [_RESULT]}]}

    prov = DataForSEOProvider(login="l", password="p", priority=2)
    res = prov.search("tarot", post_json=fake_post, get_json=fake_get, poll_interval=0)

    assert len(res.organic) == 2 and len(res.sponsored) == 1
    body = captured["body"][0]
    assert body["location_code"] == 2250
    assert body["language_code"] == "fr_FR"
    assert body["priority"] == 2
    assert body["keyword"] == "tarot"
    assert captured["url"].endswith("/task_post")


def test_provider_raises_on_rejected_task():
    def fake_post(url, body):
        return {"tasks": [{"status_code": 40501, "status_message": "Invalid Field"}]}
    prov = DataForSEOProvider(login="l", password="p")
    with pytest.raises(RuntimeError):
        prov.search("tarot", post_json=fake_post, get_json=lambda u: {}, poll_interval=0)


def test_get_provider_unknown_raises():
    with pytest.raises(ValueError):
        get_provider("bidon")


def test_get_provider_default_is_dataforseo():
    prov = get_provider(login="l", password="p")
    assert prov.name == "dataforseo"
    assert prov.cost_per_call == 0.003


def test_provider_search_scopes_to_books_by_default():
    captured = {}

    def fake_post(url, body):
        captured["body"] = body
        return {"tasks": [{"status_code": 20100, "id": "T"}]}

    def fake_get(url):
        return {"tasks": [{"status_code": 20000, "result": [_RESULT]}]}

    prov = DataForSEOProvider(login="l", password="p")
    prov.search("tarot", post_json=fake_post, get_json=fake_get, poll_interval=0)
    assert captured["body"][0]["search_param"] == "i=stripbooks"


def test_provider_search_books_only_false_omits_param():
    captured = {}

    def fake_post(url, body):
        captured["body"] = body
        return {"tasks": [{"status_code": 20100, "id": "T"}]}

    prov = DataForSEOProvider(login="l", password="p")
    prov.search("tarot", books_only=False, post_json=fake_post,
                get_json=lambda u: {"tasks": [{"status_code": 20000, "result": [_RESULT]}]},
                poll_interval=0)
    assert "search_param" not in captured["body"][0]


def test_search_param_explicite_prime_sur_books_only():
    captured = {}

    def fake_post(url, body):
        captured["body"] = body
        return {"tasks": [{"status_code": 20100, "id": "T"}]}

    prov = DataForSEOProvider(login="l", password="p")
    prov.search("cosy mystery", search_param="rh=n:205566725031",
                post_json=fake_post,
                get_json=lambda u: {"tasks": [{"status_code": 20000, "result": [_RESULT]}]},
                poll_interval=0)
    assert captured["body"][0]["search_param"] == "rh=n:205566725031"


def test_product_raw_batch_rend_les_payloads_bruts():
    def fake_post(url, body):
        return {"tasks": [{"status_code": 20100, "id": "T1"}]}

    def fake_get(url):
        return {"tasks": [{"status_code": 20000, "result": [{"asin": "A1", "items": []}]}]}

    prov = DataForSEOProvider(login="l", password="p")
    out = prov.product_raw_batch(["A1"], post_json=fake_post, get_json=fake_get, poll_interval=0)
    assert out["A1"]["asin"] == "A1"          # payload brut, pas un BsrInfo
