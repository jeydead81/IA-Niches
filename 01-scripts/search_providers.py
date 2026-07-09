"""search_providers.py — étape SEARCH (payante) derrière un seam interchangeable.

Récupère, pour une requête, les résultats Amazon.fr : organiques vs sponsorisés + ASIN
+ prix + note + avis + badges. Les ASIN alimentent ensuite le BSR gratuit. Provider par
défaut : DataForSEO (Amazon Products, task-based, ~0,003 $/requête en priority).

Le mapping (DataForSEO -> modèles normalisés) est PUR et testé contre la vraie forme de
réponse observée en live. Les appels HTTP sont injectables (aucun réseau en unit-test).
"""
import os
import re
import time

import requests
from dotenv import load_dotenv

from models import BsrInfo, SearchItem, SearchResult

_BASE = "https://api.dataforseo.com/v3/merchant/amazon/products"
_ASIN_BASE = "https://api.dataforseo.com/v3/merchant/amazon/asin"
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

    def search(self, keyword: str, depth: int = 100, books_only: bool = True,
               post_json=None, get_json=None, poll_interval: float = 8,
               max_polls: int = 16) -> SearchResult:
        """Poste une tâche puis attend le résultat (poll). HTTP injectable pour les tests.
        books_only=True restreint au rayon Livres (search_param=i=stripbooks)."""
        post_json = post_json or self._post
        get_json = get_json or self._get
        item = {
            "keyword": keyword,
            "location_code": self.location_code,
            "language_code": self.language_code,
            "depth": depth,
            "priority": self.priority,
        }
        if books_only:
            item["search_param"] = "i=stripbooks"
        body = [item]
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

    def product_info_batch(self, asins, post_json=None, get_json=None,
                           poll_interval: float = 8, max_polls: int = 40) -> dict:
        """BSR de plusieurs ASIN en un seul task_post (jusqu'à 100), collecte par poll.
        Retour : {asin: BsrInfo|None}. HTTP injectable."""
        asins = [a for a in asins if a]
        if not asins:
            return {}
        post_json = post_json or self._post
        get_json = get_json or self._get
        body = [{"asin": a, "location_code": self.location_code,
                 "language_code": self.language_code, "priority": self.priority} for a in asins]
        d = post_json(_ASIN_BASE + "/task_post", body)
        tasks = d.get("tasks") or []
        pending: dict[str, str] = {}          # task_id -> asin (ordre de requête)
        for t, a in zip(tasks, asins):
            if t.get("status_code") in (20000, 20100) and t.get("id"):
                pending[t["id"]] = a
        out: dict = {a: None for a in asins}
        for _ in range(max_polls):
            if not pending:
                break
            time.sleep(poll_interval)
            for tid in list(pending):
                r = (get_json(f"{_ASIN_BASE}/task_get/advanced/{tid}").get("tasks") or [{}])[0]
                if r.get("status_code") == 20000 and r.get("result"):
                    out[pending.pop(tid)] = parse_asin_bsr(r["result"][0])
        return out


_BSR_KEY_HINTS = ("meilleures ventes", "best sellers rank")
_MAIN_RANK = re.compile(r"([\d][\d\s .]{0,12})\s*en\s+Livres\b", re.I)
_SUB_RANK = re.compile(r"([\d][\d\s .]*?)\s*en\s+([A-Za-zÀ-ÿ][^\n(]{1,60})", re.I)


def _bsr_to_int(s: str) -> int | None:
    digits = re.sub(r"[^\d]", "", s or "")
    return int(digits) if digits else None


def parse_asin_bsr(result: dict) -> BsrInfo | None:
    """Extrait le rang Livres d'une réponse DataForSEO ASIN (advanced). None si pas de rang Livres."""
    items = (result or {}).get("items") or []
    item = next((it for it in items if it.get("type") == "amazon_product_info"),
                items[0] if items else None)
    if not item:
        return None
    body: dict = {}
    for sec in (item.get("product_information") or []):
        b = sec.get("body")
        if isinstance(b, dict):
            body.update(b)
    bsr_val = next((v for k, v in body.items()
                    if isinstance(v, str) and any(h in k.lower() for h in _BSR_KEY_HINTS)), None)
    if not bsr_val:
        return None
    m = _MAIN_RANK.search(bsr_val)
    rank = _bsr_to_int(m.group(1)) if m else None
    if rank is None:
        return None
    subs: list[dict] = []
    for sm in _SUB_RANK.finditer(bsr_val):
        cat = sm.group(2).strip(" .,;:()")
        if cat.lower().startswith("livres") or "voir les" in cat.lower():
            continue
        r = _bsr_to_int(sm.group(1))
        if r and cat:
            subs.append({"category": cat[:60], "rank": r})
    return BsrInfo(rank_livres=rank, asin=(result.get("asin") or item.get("data_asin")),
                   subcategories=subs[:5], raw=bsr_val[:300])


_PROVIDERS = {"dataforseo": DataForSEOProvider}


def get_provider(name: str = "dataforseo", **kwargs):
    """Renvoie une instance de provider search (seam). Défaut : dataforseo."""
    cls = _PROVIDERS.get(name)
    if cls is None:
        raise ValueError(f"provider search inconnu : {name} (dispo : {list(_PROVIDERS)})")
    return cls(**kwargs)
