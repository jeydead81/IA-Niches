"""search_providers.py — étape SEARCH (payante) derrière un seam interchangeable.

Récupère, pour une requête, les résultats Amazon.fr : organiques vs sponsorisés + ASIN
+ prix + note + avis + badges. Les ASIN alimentent ensuite le BSR gratuit. Provider par
défaut : DataForSEO (Amazon Products, task-based, ~0,003 $/requête en priority).

Le mapping (DataForSEO -> modèles normalisés) est PUR et testé contre la vraie forme de
réponse observée en live. Les appels HTTP sont injectables (aucun réseau en unit-test).
"""
import os
import time

import requests
from dotenv import load_dotenv

from models import SearchItem, SearchResult

_BASE = "https://api.dataforseo.com/v3/merchant/amazon/products"
DEFAULT_LOCATION = 2250       # France (location_code)
DEFAULT_LANGUAGE = "fr_FR"    # "French (France)" — code validé en live (pas "fr")
COST_PER_CALL_USD = {1: 0.0015, 2: 0.003}  # standard (~45 min) / priority (~1 min)


def _to_float(x) -> float | None:
    try:
        return float(x) if x is not None else None
    except (TypeError, ValueError):
        return None


def _map_item(it: dict) -> SearchItem:
    rating = it.get("rating") if isinstance(it.get("rating"), dict) else {}
    return SearchItem(
        rank=it.get("rank_absolute"),
        asin=it.get("data_asin"),
        title=it.get("title") or "",
        url=it.get("url"),
        price=_to_float(it.get("price_from")),
        currency=it.get("currency"),
        rating=_to_float(rating.get("value")),
        reviews_count=rating.get("votes_count"),
        is_best_seller=bool(it.get("is_best_seller")),
        is_amazon_choice=bool(it.get("is_amazon_choice")),
        sponsored=it.get("type") == "amazon_paid",
    )


def map_dataforseo_result(result: dict) -> SearchResult:
    """Convertit un 'result' DataForSEO (merchant/amazon/products) en SearchResult
    normalisé : organiques (amazon_serp) vs sponsorisés (amazon_paid)."""
    items = (result or {}).get("items") or []
    organic, sponsored = [], []
    for it in items:
        t = it.get("type")
        if t == "amazon_serp":
            organic.append(_map_item(it))
        elif t == "amazon_paid":
            sponsored.append(_map_item(it))
    return SearchResult(
        keyword=(result or {}).get("keyword") or "",
        organic=organic,
        sponsored=sponsored,
        total_items=len(items),
    )


class DataForSEOProvider:
    """Provider search via DataForSEO Amazon Products (task-based)."""
    name = "dataforseo"

    def __init__(self, login: str | None = None, password: str | None = None,
                 priority: int = 2, location_code: int = DEFAULT_LOCATION,
                 language_code: str = DEFAULT_LANGUAGE):
        load_dotenv()
        self.auth = (login or os.getenv("DATAFORSEO_LOGIN", ""),
                     password or os.getenv("DATAFORSEO_PASSWORD", ""))
        self.priority = priority
        self.location_code = location_code
        self.language_code = language_code

    def _post(self, url: str, body):
        return requests.post(url, auth=self.auth, json=body, timeout=30).json()

    def _get(self, url: str):
        return requests.get(url, auth=self.auth, timeout=30).json()

    @property
    def cost_per_call(self) -> float:
        return COST_PER_CALL_USD.get(self.priority, 0.003)

    def search(self, keyword: str, depth: int = 100, post_json=None, get_json=None,
               poll_interval: float = 8, max_polls: int = 16) -> SearchResult:
        """Poste une tâche puis attend le résultat (poll). HTTP injectable pour les tests."""
        post_json = post_json or self._post
        get_json = get_json or self._get
        body = [{
            "keyword": keyword,
            "location_code": self.location_code,
            "language_code": self.language_code,
            "depth": depth,
            "priority": self.priority,
        }]
        d = post_json(_BASE + "/task_post", body)
        task = (d.get("tasks") or [{}])[0]
        if task.get("status_code") not in (20000, 20100):
            raise RuntimeError(f"task_post refusé : {task.get('status_code')} {task.get('status_message')}")
        tid = task.get("id")
        for _ in range(max_polls):
            time.sleep(poll_interval)
            t = (get_json(f"{_BASE}/task_get/advanced/{tid}").get("tasks") or [{}])[0]
            if t.get("status_code") == 20000 and t.get("result"):
                return map_dataforseo_result(t["result"][0])
        raise TimeoutError(f"résultat DataForSEO non prêt (id={tid})")


_PROVIDERS = {"dataforseo": DataForSEOProvider}


def get_provider(name: str = "dataforseo", **kwargs):
    """Renvoie une instance de provider search (seam). Défaut : dataforseo."""
    cls = _PROVIDERS.get(name)
    if cls is None:
        raise ValueError(f"provider search inconnu : {name} (dispo : {list(_PROVIDERS)})")
    return cls(**kwargs)
