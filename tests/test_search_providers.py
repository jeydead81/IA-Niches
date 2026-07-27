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


def test_product_raw_batch_apparie_par_asin_rendu_pas_par_position():
    # task_post peut échoer les tâches dans un ordre différent de la requête postée ; la
    # réponse fait écho à l'ASIN dans task["data"]["asin"]. zip(tasks, asins) suppose que
    # l'ordre posté == l'ordre rendu -> mauvais payload sous le mauvais ASIN si inversé.
    def fake_post(url, body):
        tasks = [{"status_code": 20100, "id": f"T-{item['asin']}", "data": {"asin": item["asin"]}}
                 for item in reversed(body)]           # ordre INVERSÉ vs la requête postée
        return {"tasks": tasks}

    def fake_get(url):
        tid = url.rsplit("/", 1)[-1]
        asin = tid.split("T-", 1)[1]
        return {"tasks": [{"status_code": 20000, "result": [{"asin": asin, "items": []}]}]}

    prov = DataForSEOProvider(login="l", password="p")
    out = prov.product_raw_batch(["A1", "A2"], post_json=fake_post, get_json=fake_get,
                                 poll_interval=0)
    assert out["A1"]["asin"] == "A1"
    assert out["A2"]["asin"] == "A2"


def test_product_raw_batch_rend_les_payloads_bruts():
    def fake_post(url, body):
        return {"tasks": [{"status_code": 20100, "id": "T1"}]}

    def fake_get(url):
        return {"tasks": [{"status_code": 20000, "result": [{"asin": "A1", "items": []}]}]}

    prov = DataForSEOProvider(login="l", password="p")
    out = prov.product_raw_batch(["A1"], post_json=fake_post, get_json=fake_get, poll_interval=0)
    assert out["A1"]["asin"] == "A1"          # payload brut, pas un BsrInfo


def test_echo_asin_hors_lot_retombe_sur_la_position():
    """Un écho qui ne fait pas partie du lot posté classerait le payload sous une clé
    fantôme et le perdrait pour l'ASIN demandé — on ne fait confiance à l'écho que s'il
    appartient au lot."""
    def fake_post(url, body):
        return {"tasks": [{"status_code": 20100, "id": "T1",
                           "data": {"asin": "XX-INCONNU"}}]}

    def fake_get(url):
        return {"tasks": [{"status_code": 20000, "result": [{"asin": "A1", "items": []}]}]}

    prov = DataForSEOProvider(login="l", password="p")
    out = prov.product_raw_batch(["A1"], post_json=fake_post, get_json=fake_get,
                                 poll_interval=0)
    assert out["A1"] is not None
    assert "XX-INCONNU" not in out


def test_le_budget_de_poll_serp_vaut_celui_du_chemin_asin():
    """Le SERP n'a aucune raison d'avoir un budget d'attente PLUS COURT que le batch ASIN.
    Mesuré en live : la file DataForSEO a dépassé 128 s (16 polls) et les 3 SERP d'un run
    ont expiré, alors que le chemin ASIN (40 polls) tenait. Un ralentissement passager de
    DataForSEO effaçait donc un run entier — côté fiction ET côté non-fiction."""
    import inspect

    budget_serp = inspect.signature(DataForSEOProvider.search).parameters["max_polls"].default
    budget_asin = (inspect.signature(DataForSEOProvider.product_raw_batch)
                   .parameters["max_polls"].default)
    assert budget_serp >= budget_asin


def test_priorite_configurable_par_environnement(monkeypatch):
    """La file « standard » coûte moitié prix (0,0015 $ vs 0,003 $) mais peut mettre ~45 min
    quand priority tourne autour de 1-4 min. C'est un ARBITRAGE, donc un réglage — le défaut
    reste priority pour ne pas dégrader l'usage interactif à l'insu de l'appelant."""
    monkeypatch.setenv("DATAFORSEO_PRIORITY", "1")
    assert DataForSEOProvider(login="l", password="p").priority == 1
    monkeypatch.delenv("DATAFORSEO_PRIORITY")
    assert DataForSEOProvider(login="l", password="p").priority == 2
