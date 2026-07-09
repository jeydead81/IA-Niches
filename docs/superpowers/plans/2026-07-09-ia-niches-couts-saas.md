# IA-Niches — Optimisation coûts & préparation SaaS — Plan d'implémentation

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Rendre le BSR fiable côté serveur (DataForSEO ASIN, batché), couper le coût par run (n_bsr 5→3, cache SQLite cross-user, scoping Livres) et instrumenter le coût réel ($ DataForSEO + tokens LLM) exposé dans l'UI — sans casser l'exécution hors-ligne.

**Architecture :** Le BSR passe du scraping `amazon.fr` (bloqué en datacenter) à l'endpoint **DataForSEO Merchant Amazon ASIN**, appelé **en lot** (un `task_post` d'ASIN, collecte via poll) car la file ASIN prend ~3-4 min même en priority. `run_scout` devient 3 phases : searches par niche → résolution BSR globale (dédup + cache) → scoring. Un flag `BSR_SOURCE` (`scrape` défaut local / `dataforseo` serveur) choisit la source. Un cache SQLite partagé (clé par ASIN et par mot-clé, TTL) rend gratuits les ASIN/searches récurrents. Un `CostTracker` additionne les appels DataForSEO et les tokens LLM (usage réel Anthropic) et le coût est streamé en SSE.

**Tech Stack :** Python 3.13, pytest (pythonpath=`01-scripts`), pydantic v2, `sqlite3` (stdlib), `requests`, Anthropic SDK, FastAPI + SSE.

**Forme réelle du BSR (probe live 2026-07-09, ASIN `2080700162`)** — `result.items[0]` (type `amazon_product_info`) → `product_information` est une **liste** → section `type=="product_information_details_item"` → `body` (dict) → clé **`"Classement des meilleures ventes d'Amazon"`** → valeur `"194 en Livres ( Voir les 100 premiers en Livres )  1 en Philosophie…\n 1 en Ouvrages…\n 4 en Biographies historiques (Livres)"`. Fixture brute : `tests/fixtures/asin_fr_raw.json`. `search_param=i=stripbooks` restreint le search au rayon Livres (validé live).

**Décisions verrouillées :** BSR_SOURCE défaut `scrape` (runs perso gratuits) ; BSR en **Priority** (Standard = ~45 min, inutilisable) ; cache **SQLite** ; cache par ASIN (dédup cross-niche/cross-run) — jamais de substitution d'un livre d'une autre niche ; n_bsr plancher **3** ; searches restent séquentiels (progression par niche), seul le BSR est batché globalement.

---

## Task 1 : Parseur `parse_asin_bsr` + fixture figée

**Files:**
- Create: `tests/fixtures/asin_fr.json`
- Modify: `01-scripts/search_providers.py` (ajout parseur + regex + constante `_ASIN_BASE`)
- Test: `tests/test_amazon_asin.py`

- [ ] **Step 1 : Créer la fixture ASIN trimmée**

Écrire `tests/fixtures/asin_fr.json` :

```json
{
  "asin": "2080700162",
  "type": "amazon_product_info",
  "items": [
    {
      "type": "amazon_product_info",
      "data_asin": "2080700162",
      "title": "Pensées pour moi-même, Suivi de Manuel d'Epictète",
      "categories": [{"category": "Livres"}, {"category": "Études supérieures"}],
      "rating": {"value": 4.6, "votes_count": 3028},
      "product_information": [
        {
          "type": "product_information_details_item",
          "section_name": "Détails sur le produit",
          "body": {
            "Éditeur": "FLAMMARION",
            "ISBN-13": "978-2080700162",
            "Classement des meilleures ventes d'Amazon": "194 en Livres ( Voir les 100 premiers en Livres )  1 en Philosophie et épistémologie pour l'université\n 1 en Ouvrages de référence de la philosophie\n 4 en Biographies historiques (Livres)"
          }
        }
      ]
    }
  ]
}
```

- [ ] **Step 2 : Écrire le test (échoue)**

Créer `tests/test_amazon_asin.py` :

```python
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
    # sous-catégories best-effort, "Livres" et le bruit "Voir les 100 premiers" exclus
    cats = [s["category"].lower() for s in info.subcategories]
    assert not any(c == "livres" or "voir les" in c for c in cats)
    assert any("philosophie" in c for c in cats)


def test_parse_asin_bsr_thousands_separator():
    fix = {"items": [{"type": "amazon_product_info", "data_asin": "X",
                      "product_information": [{"type": "product_information_details_item",
                        "body": {"Classement des meilleures ventes d'Amazon": "12 345 en Livres"}}]}]}
    assert parse_asin_bsr(fix).rank_livres == 12345


def test_parse_asin_bsr_non_book_returns_none():
    # un produit sans rang "en Livres" (jeu de cartes) -> None -> exclu des calculs
    fix = {"items": [{"type": "amazon_product_info", "data_asin": "Y",
                      "product_information": [{"type": "product_information_details_item",
                        "body": {"Piles": "3 LR03"}}]}]}
    assert parse_asin_bsr(fix) is None


def test_parse_asin_bsr_empty():
    assert parse_asin_bsr({}) is None
```

- [ ] **Step 3 : Lancer le test (échoue)**

Run : `python -m pytest tests/test_amazon_asin.py -v`
Attendu : FAIL `ImportError: cannot import name 'parse_asin_bsr'`

- [ ] **Step 4 : Implémenter le parseur**

Dans `01-scripts/search_providers.py`, ajouter après la ligne `_BASE = ...` :

```python
_ASIN_BASE = "https://api.dataforseo.com/v3/merchant/amazon/asin"
```

Ajouter en fin de fichier (avant `_PROVIDERS = ...`) :

```python
from models import BsrInfo  # noqa: E402  (déjà importé SearchItem/SearchResult en tête ; regrouper si besoin)

_BSR_KEY_HINTS = ("meilleures ventes", "best sellers rank")
_MAIN_RANK = re.compile(r"([\d][\d\s .]{0,12})\s*en\s+Livres\b", re.I)
_SUB_RANK = re.compile(r"([\d][\d\s .]*?)\s*en\s+([A-Za-zÀ-ÿ][^\n(]{1,60})", re.I)


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
```

> Note : `re` est déjà importé en tête de `search_providers.py`. Si `from models import BsrInfo` fait doublon avec l'import existant `from models import SearchItem, SearchResult`, fusionner en `from models import BsrInfo, SearchItem, SearchResult`.

- [ ] **Step 5 : Lancer le test (passe)**

Run : `python -m pytest tests/test_amazon_asin.py -v`
Attendu : PASS (4 tests)

- [ ] **Step 6 : Commit**

```bash
git add tests/fixtures/asin_fr.json tests/test_amazon_asin.py 01-scripts/search_providers.py
git commit -m "feat(bsr): parseur parse_asin_bsr (DataForSEO ASIN, rang Livres) + fixture live"
```

---

## Task 2 : Scoping Livres sur le search (`books_only`)

**Files:**
- Modify: `01-scripts/search_providers.py` (`DataForSEOProvider.search`)
- Test: `tests/test_search_providers.py`

- [ ] **Step 1 : Écrire le test (échoue)**

Ajouter dans `tests/test_search_providers.py` :

```python
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
```

- [ ] **Step 2 : Lancer (échoue)**

Run : `python -m pytest tests/test_search_providers.py -k books -v`
Attendu : FAIL (`search()` ne prend pas `books_only`)

- [ ] **Step 3 : Implémenter**

Dans `DataForSEOProvider.search`, modifier la signature et le corps `body` :

```python
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
        # ... (reste inchangé)
```

- [ ] **Step 4 : Lancer (passe)**

Run : `python -m pytest tests/test_search_providers.py -v`
Attendu : PASS (tous, y compris les anciens — le body inclut désormais `search_param` par défaut ; vérifier que `test_provider_search_posts_correct_body_and_maps` n'assertait pas l'absence de clés).

- [ ] **Step 5 : Commit**

```bash
git add 01-scripts/search_providers.py tests/test_search_providers.py
git commit -m "feat(search): scoping rayon Livres (search_param=i=stripbooks) par défaut"
```

---

## Task 3 : Lookup BSR batché (`product_info_batch`)

**Files:**
- Modify: `01-scripts/search_providers.py` (`DataForSEOProvider.product_info_batch`)
- Test: `tests/test_amazon_asin.py`

- [ ] **Step 1 : Écrire le test (échoue)**

Ajouter dans `tests/test_amazon_asin.py` :

```python
from search_providers import DataForSEOProvider


def test_product_info_batch_maps_asin_to_bsr():
    captured = {}

    def fake_post(url, body):
        captured["url"] = url
        captured["body"] = body
        return {"tasks": [{"status_code": 20100, "id": "TID1"},
                          {"status_code": 20100, "id": "TID2"}]}

    def fake_get(url):
        # les deux ASIN renvoient la même fixture (rang 194) pour le test
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
```

- [ ] **Step 2 : Lancer (échoue)**

Run : `python -m pytest tests/test_amazon_asin.py -k batch -v`
Attendu : FAIL (`product_info_batch` n'existe pas)

- [ ] **Step 3 : Implémenter**

Ajouter la méthode dans `class DataForSEOProvider` (après `search`) :

```python
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
```

- [ ] **Step 4 : Lancer (passe)**

Run : `python -m pytest tests/test_amazon_asin.py -v`
Attendu : PASS

- [ ] **Step 5 : Commit**

```bash
git add 01-scripts/search_providers.py tests/test_amazon_asin.py
git commit -m "feat(bsr): product_info_batch — lookups ASIN batchés (amortit la file ~4 min)"
```

---

## Task 4 : Cache SQLite partagé (TTL)

**Files:**
- Create: `01-scripts/cache.py`
- Test: `tests/test_cache.py`

- [ ] **Step 1 : Écrire le test (échoue)**

Créer `tests/test_cache.py` :

```python
from cache import Cache


def test_set_get_roundtrip(tmp_path):
    c = Cache(tmp_path / "c.db")
    c.set("k", {"n": 1}, ttl_s=100)
    assert c.get("k") == {"n": 1}


def test_miss_returns_none(tmp_path):
    assert Cache(tmp_path / "c.db").get("absent") is None


def test_ttl_expiry(tmp_path):
    clock = {"t": 1000.0}
    c = Cache(tmp_path / "c.db", now=lambda: clock["t"])
    c.set("k", {"v": 1}, ttl_s=10)
    clock["t"] = 1005.0
    assert c.get("k") == {"v": 1}          # encore valide
    clock["t"] = 1020.0
    assert c.get("k") is None              # expiré


def test_bsr_helpers(tmp_path):
    from models import BsrInfo
    c = Cache(tmp_path / "c.db")
    c.set_bsr("A1", 2250, BsrInfo(rank_livres=194, asin="A1"), ttl_s=100)
    got = c.get_bsr("A1", 2250)
    assert got.rank_livres == 194 and got.asin == "A1"
    assert c.get_bsr("A2", 2250) is None


def test_search_helpers(tmp_path):
    from models import SearchResult, SearchItem
    c = Cache(tmp_path / "c.db")
    sr = SearchResult(keyword="tarot", organic=[SearchItem(title="x", asin="A1")])
    c.set_search("Tarot ", 2250, "fr_FR", sr, ttl_s=100)   # clé normalisée (lower+strip)
    got = c.get_search("tarot", 2250, "fr_FR")
    assert got.keyword == "tarot" and got.organic[0].asin == "A1"
```

- [ ] **Step 2 : Lancer (échoue)**

Run : `python -m pytest tests/test_cache.py -v`
Attendu : FAIL `ModuleNotFoundError: No module named 'cache'`

- [ ] **Step 3 : Implémenter**

Créer `01-scripts/cache.py` :

```python
"""cache.py — cache clé/valeur SQLite partagé (cross-user), avec TTL.
Sûr en concurrence (le serveur lance des scouts en threads) : connexion par appel + WAL.
Valeurs JSON-sérialisables. Helpers dédiés BSR (par ASIN) et search (par mot-clé normalisé)."""
import json
import sqlite3
import time
from pathlib import Path

from models import BsrInfo, SearchResult


class Cache:
    def __init__(self, path, now=None):
        self.path = str(path)
        self.now = now or time.time
        Path(self.path).parent.mkdir(parents=True, exist_ok=True)
        with self._conn() as cx:
            cx.execute("CREATE TABLE IF NOT EXISTS kv "
                       "(key TEXT PRIMARY KEY, value TEXT NOT NULL, expires REAL NOT NULL)")

    def _conn(self):
        cx = sqlite3.connect(self.path, timeout=10, check_same_thread=False)
        cx.execute("PRAGMA journal_mode=WAL")
        return cx

    def get(self, key: str):
        with self._conn() as cx:
            row = cx.execute("SELECT value, expires FROM kv WHERE key=?", (key,)).fetchone()
        if not row or row[1] < self.now():
            return None
        return json.loads(row[0])

    def set(self, key: str, value, ttl_s: float) -> None:
        with self._conn() as cx:
            cx.execute("INSERT OR REPLACE INTO kv (key, value, expires) VALUES (?, ?, ?)",
                       (key, json.dumps(value, ensure_ascii=False), self.now() + ttl_s))

    # ── helpers métier ──
    @staticmethod
    def _bsr_key(asin: str, location: int) -> str:
        return f"bsr:{location}:{asin}"

    @staticmethod
    def _search_key(keyword: str, location: int, language: str) -> str:
        return f"search:{location}:{language}:{(keyword or '').lower().strip()}"

    def get_bsr(self, asin: str, location: int) -> BsrInfo | None:
        d = self.get(self._bsr_key(asin, location))
        return BsrInfo.model_validate(d) if d else None

    def set_bsr(self, asin: str, location: int, info: BsrInfo, ttl_s: float) -> None:
        self.set(self._bsr_key(asin, location), info.model_dump(), ttl_s)

    def get_search(self, keyword: str, location: int, language: str) -> SearchResult | None:
        d = self.get(self._search_key(keyword, location, language))
        return SearchResult.model_validate(d) if d else None

    def set_search(self, keyword: str, location: int, language: str,
                   result: SearchResult, ttl_s: float) -> None:
        self.set(self._search_key(keyword, location, language), result.model_dump(), ttl_s)
```

- [ ] **Step 4 : Lancer (passe)**

Run : `python -m pytest tests/test_cache.py -v`
Attendu : PASS (5 tests)

- [ ] **Step 5 : Commit**

```bash
git add 01-scripts/cache.py tests/test_cache.py
git commit -m "feat(cache): cache SQLite partagé TTL (BSR par ASIN + search par mot-clé)"
```

---

## Task 5 : Compteur de coût réel (`cost_tracker`)

**Files:**
- Create: `01-scripts/cost_tracker.py`
- Test: `tests/test_cost_tracker.py`

- [ ] **Step 1 : Écrire le test (échoue)**

Créer `tests/test_cost_tracker.py` :

```python
from datetime import date

from cost_tracker import CostTracker, llm_cost_usd, dataforseo_cost_usd


def test_dataforseo_cost():
    assert dataforseo_cost_usd(6, priority=2) == 6 * 0.003
    assert dataforseo_cost_usd(18, priority=1) == 18 * 0.0015


def test_llm_cost_sonnet_intro_vs_standard():
    # 1M in / 1M out
    intro = llm_cost_usd("claude-sonnet-5", 1_000_000, 1_000_000, today=date(2026, 7, 9))
    std = llm_cost_usd("claude-sonnet-5", 1_000_000, 1_000_000, today=date(2026, 9, 1))
    assert intro == 2.0 + 10.0            # tarif intro
    assert std == 3.0 + 15.0              # tarif standard après 2026-08-31


def test_tracker_aggregates():
    t = CostTracker(today=date(2026, 7, 9))
    t.add_dataforseo(2, priority=2)       # 2 searches priority
    t.add_dataforseo(3, priority=1)       # 3 BSR standard... (ici priority=1 = 0.0015)
    t.add_llm("claude-sonnet-5", 1200, 1500)
    b = t.breakdown()
    assert b["dataforseo_calls"] == 5
    assert round(t.total_usd(), 6) == round(b["usd"], 6)
    assert b["usd"] > 0
```

- [ ] **Step 2 : Lancer (échoue)**

Run : `python -m pytest tests/test_cost_tracker.py -v`
Attendu : FAIL `ModuleNotFoundError: No module named 'cost_tracker'`

- [ ] **Step 3 : Implémenter**

Créer `01-scripts/cost_tracker.py` :

```python
"""cost_tracker.py — coût réel d'un run : appels DataForSEO ($) + tokens LLM (usage Anthropic).
Remplace l'ancien credits_tracker (Scrapingdog, mort). Brique de facturation en crédits."""
from datetime import date

from search_providers import COST_PER_CALL_USD

# $/million de tokens (input, output). Sonnet 5 : tarif intro jusqu'au 31/08/2026, puis standard.
_LLM_PRICES = {
    "claude-sonnet-5": {"in": 2.0, "out": 10.0, "in_std": 3.0, "out_std": 15.0,
                        "intro_until": date(2026, 8, 31)},
    "claude-opus-4-8": {"in": 5.0, "out": 25.0},
    "claude-fable-5": {"in": 10.0, "out": 50.0},
    "claude-haiku-4-5": {"in": 1.0, "out": 5.0},
}


def dataforseo_cost_usd(n_calls: int, priority: int) -> float:
    return n_calls * COST_PER_CALL_USD.get(priority, 0.003)


def llm_cost_usd(model: str, in_tok: int, out_tok: int, today: date | None = None) -> float:
    p = _LLM_PRICES.get(model)
    if not p:
        return 0.0
    today = today or date.today()
    if "intro_until" in p and today > p["intro_until"]:
        p_in, p_out = p["in_std"], p["out_std"]
    else:
        p_in, p_out = p["in"], p["out"]
    return (in_tok * p_in + out_tok * p_out) / 1_000_000


class CostTracker:
    def __init__(self, today: date | None = None):
        self.today = today
        self._df: list[tuple[int, int]] = []      # (n_calls, priority)
        self._llm: list[tuple[str, int, int]] = []  # (model, in, out)

    def add_dataforseo(self, n_calls: int, priority: int) -> None:
        if n_calls:
            self._df.append((n_calls, priority))

    def add_llm(self, model: str, in_tok: int, out_tok: int) -> None:
        self._llm.append((model, in_tok or 0, out_tok or 0))

    def total_usd(self) -> float:
        df = sum(dataforseo_cost_usd(n, p) for n, p in self._df)
        llm = sum(llm_cost_usd(m, i, o, self.today) for m, i, o in self._llm)
        return df + llm

    def breakdown(self) -> dict:
        df = sum(dataforseo_cost_usd(n, p) for n, p in self._df)
        llm = sum(llm_cost_usd(m, i, o, self.today) for m, i, o in self._llm)
        return {
            "usd": round(df + llm, 4),
            "dataforseo_usd": round(df, 4),
            "llm_usd": round(llm, 4),
            "dataforseo_calls": sum(n for n, _ in self._df),
            "llm_tokens_in": sum(i for _, i, _ in self._llm),
            "llm_tokens_out": sum(o for _, _, o in self._llm),
        }
```

- [ ] **Step 4 : Lancer (passe)**

Run : `python -m pytest tests/test_cost_tracker.py -v`
Attendu : PASS (3 tests)

- [ ] **Step 5 : Commit**

```bash
git add 01-scripts/cost_tracker.py tests/test_cost_tracker.py
git commit -m "feat(cost): CostTracker — coût réel DataForSEO + tokens LLM (tarifs 2026)"
```

---

## Task 6 : Résolution BSR (`resolve_bsrs`) — source + cache + dédup + coût

**Files:**
- Create: `01-scripts/bsr_source.py`
- Test: `tests/test_bsr_source.py`

- [ ] **Step 1 : Écrire le test (échoue)**

Créer `tests/test_bsr_source.py` :

```python
from bsr_source import resolve_bsrs
from cost_tracker import CostTracker
from cache import Cache
from models import BsrInfo


def test_resolve_dedups_and_uses_fetch_fn():
    calls = []

    def fetch_fn(asin):
        calls.append(asin)
        return {"A1": BsrInfo(rank_livres=3000, asin="A1"),
                "A2": BsrInfo(rank_livres=60000, asin="A2")}.get(asin)

    out = resolve_bsrs(["A1", "A2", "A1"], fetch_bsr_fn=fetch_fn, bsr_pause=0)
    assert out["A1"].rank_livres == 3000 and out["A2"].rank_livres == 60000
    assert sorted(calls) == ["A1", "A2"]           # dédup : A1 une seule fois


def test_resolve_dataforseo_batch_counts_cost():
    class FakeProvider:
        priority = 2
        location_code = 2250
        def product_info_batch(self, asins):
            return {a: BsrInfo(rank_livres=100, asin=a) for a in asins}

    cost = CostTracker()
    out = resolve_bsrs(["A1", "A2"], source="dataforseo", provider=FakeProvider(),
                       cost=cost, bsr_priority=2)
    assert out["A1"].rank_livres == 100
    assert cost.breakdown()["dataforseo_calls"] == 2   # 2 lookups payés


def test_resolve_cache_hit_no_network(tmp_path):
    c = Cache(tmp_path / "c.db")
    c.set_bsr("A1", 2250, BsrInfo(rank_livres=5, asin="A1"), ttl_s=100)

    def boom(asin):
        raise AssertionError("ne doit pas être appelé (cache hit)")

    out = resolve_bsrs(["A1"], fetch_bsr_fn=boom, cache=c, location=2250, bsr_pause=0)
    assert out["A1"].rank_livres == 5
```

- [ ] **Step 2 : Lancer (échoue)**

Run : `python -m pytest tests/test_bsr_source.py -v`
Attendu : FAIL `ModuleNotFoundError: No module named 'bsr_source'`

- [ ] **Step 3 : Implémenter**

Créer `01-scripts/bsr_source.py` :

```python
"""bsr_source.py — résout le BSR d'une liste d'ASIN, avec dédup + cache + choix de source.
Source (env BSR_SOURCE) : 'scrape' (gratuit, IP résidentielle, défaut local) ou 'dataforseo'
(batché, fiable, serveur). fetch_bsr_fn injectable (tests hors-ligne + fallback scrape par ASIN)."""
import os
import time

from amazon_product import fetch_bsr as _scrape_bsr

BSR_TTL_S = 3 * 24 * 3600      # 3 jours : le classement bouge, mais réutilisable court terme


def resolve_bsrs(asins, *, source=None, provider=None, fetch_bsr_fn=None, cache=None,
                 location: int = 2250, bsr_priority: int = 2, cost=None,
                 bsr_pause: float = 0.4) -> dict:
    """Retour : {asin: BsrInfo|None}. Dédup, cache (par ASIN), et comptage coût pour DataForSEO."""
    uniq = list(dict.fromkeys(a for a in asins if a))
    out: dict = {}
    misses: list[str] = []
    for a in uniq:
        c = cache.get_bsr(a, location) if cache else None
        if c is not None:
            out[a] = c
        else:
            misses.append(a)

    if misses:
        source = source or os.getenv("BSR_SOURCE", "scrape")
        if fetch_bsr_fn is not None or source == "scrape":
            fn = fetch_bsr_fn or _scrape_bsr
            for a in misses:
                out[a] = fn(a)
                if bsr_pause and fetch_bsr_fn is None:
                    time.sleep(bsr_pause)
        elif source == "dataforseo":
            if provider is None:
                raise ValueError("source=dataforseo requiert un provider")
            batch = provider.product_info_batch(misses)
            out.update(batch)
            if cost is not None:
                cost.add_dataforseo(len(misses), getattr(provider, "priority", bsr_priority))
        else:
            raise ValueError(f"BSR_SOURCE inconnu : {source}")

        if cache:
            for a in misses:
                if out.get(a) is not None:
                    cache.set_bsr(a, location, out[a], BSR_TTL_S)
    return out
```

- [ ] **Step 4 : Lancer (passe)**

Run : `python -m pytest tests/test_bsr_source.py -v`
Attendu : PASS (3 tests)

- [ ] **Step 5 : Commit**

```bash
git add 01-scripts/bsr_source.py tests/test_bsr_source.py
git commit -m "feat(bsr): resolve_bsrs — dédup + cache + source (scrape/dataforseo) + coût"
```

---

## Task 7 : `bsr_stats` — recalibrage top-3 (docstring + test témoin)

**Files:**
- Modify: `01-scripts/scoring.py` (docstring de `bsr_stats`)
- Test: `tests/test_scoring.py`

> `bsr_stats` utilise déjà `vals[:5]` / `vals[:10]` : avec 3 BSR, `top5` = 3 valeurs et `worst_top10` = max des 3. La fonction reste correcte ; on documente le changement de sémantique et on ajoute un test témoin.

- [ ] **Step 1 : Écrire le test (échoue)**

Ajouter dans `tests/test_scoring.py` :

```python
def test_bsr_stats_top3_place_a_prendre():
    # n_bsr=3 : ≥1 <10k, moyenne <50k, ≥1 >50k  -> §4.1 rempli sur 3 points
    s = bsr_stats([2279, 8000, 60000])
    assert s["best"] == 2279 and s["crit1"] and s["crit2"] and s["crit3"] and s["ok"]


def test_bsr_stats_top3_no_place():
    s = bsr_stats([2279, 4000, 9000])          # aucun >50k
    assert s["crit1"] and s["crit2"] and not s["crit3"] and not s["ok"]
```

- [ ] **Step 2 : Lancer (passe déjà, mais on veut la protection de non-régression)**

Run : `python -m pytest tests/test_scoring.py -k top3 -v`
Attendu : PASS (la logique existante gère déjà 3 points)

- [ ] **Step 3 : Documenter le changement**

Dans `01-scripts/scoring.py`, remplacer la docstring de `bsr_stats` par :

```python
    """Statistiques BSR + critères §4.1 sur les BSR du top organique.
    §4.1 : (1) ≥1 BSR < 10 000, (2) moyenne du top < 50 000, (3) ≥1 BSR > 50 000.
    NB : le scout ne récupère que le top-3 (n_bsr_per_niche=3) pour maîtriser le coût ;
    'top5_avg' est donc la moyenne des ≤3 BSR disponibles et 'worst_top10' leur max.
    Les 3 critères restent discriminants sur 3 points."""
```

- [ ] **Step 4 : Lancer (passe)**

Run : `python -m pytest tests/test_scoring.py -v`
Attendu : PASS

- [ ] **Step 5 : Commit**

```bash
git add 01-scripts/scoring.py tests/test_scoring.py
git commit -m "docs(scoring): §4.1 recalibré top-3 + tests témoins"
```

---

## Task 8 : Usage tokens de l'ideator (`on_usage`)

**Files:**
- Modify: `01-scripts/niche_ideator.py` (`generate_niches`)
- Test: `tests/test_niche_ideator.py`

- [ ] **Step 1 : Écrire le test (échoue)**

Ajouter dans `tests/test_niche_ideator.py` (adapter le nom du client factice au style existant du fichier) :

```python
def test_generate_niches_reports_usage():
    class _Usage:
        input_tokens = 1200
        output_tokens = 1500

    class _Block:
        type = "tool_use"
        input = {"niches": [{"niche": "tarot", "requete_amazon": "tarot",
                             "satellite_keywords": [], "rationale": "r",
                             "categorie": "éso", "risques": []}]}

    class _Resp:
        content = [_Block()]
        usage = _Usage()

    class _Client:
        class messages:
            @staticmethod
            def create(**kw):
                return _Resp()

    seen = {}
    from niche_ideator import generate_niches
    generate_niches(seed="ésotérisme", client=_Client(), model="claude-sonnet-5",
                    on_usage=lambda i, o, m: seen.update(i=i, o=o, m=m))
    assert seen == {"i": 1200, "o": 1500, "m": "claude-sonnet-5"}
```

- [ ] **Step 2 : Lancer (échoue)**

Run : `python -m pytest tests/test_niche_ideator.py -k usage -v`
Attendu : FAIL (`generate_niches` ne prend pas `on_usage`)

- [ ] **Step 3 : Implémenter**

Dans `01-scripts/niche_ideator.py`, modifier `generate_niches` :

```python
def generate_niches(seed: str | None = None, signals: dict | None = None,
                    n: int = 20, model: str | None = None, client=None,
                    on_usage=None) -> list[NicheCandidate]:
    """Génère des niches livre candidates. `client` (Anthropic) injectable pour les tests.
    `on_usage(input_tokens, output_tokens, model)` optionnel : coût LLM réel."""
    client = client or _default_client()
    model = model or DEFAULT_MODEL
    user = build_user_prompt(seed, signals, n)
    resp = client.messages.create(
        model=model,
        max_tokens=8000,
        system=SYSTEM_PROMPT,
        tools=[{
            "name": "proposer_niches",
            "description": "Renvoie la liste des niches livre candidates.",
            "input_schema": NICHE_INPUT_SCHEMA,
        }],
        tool_choice={"type": "tool", "name": "proposer_niches"},
        messages=[{"role": "user", "content": user}],
    )
    if on_usage is not None and getattr(resp, "usage", None) is not None:
        on_usage(getattr(resp.usage, "input_tokens", 0),
                 getattr(resp.usage, "output_tokens", 0), model)
    for block in resp.content:
        if getattr(block, "type", None) == "tool_use":
            return NicheList.model_validate(block.input).niches
    return []
```

- [ ] **Step 4 : Lancer (passe)**

Run : `python -m pytest tests/test_niche_ideator.py -v`
Attendu : PASS

- [ ] **Step 5 : Commit**

```bash
git add 01-scripts/niche_ideator.py tests/test_niche_ideator.py
git commit -m "feat(ideator): callback on_usage (tokens réels) pour l'instrumentation coût"
```

---

## Task 9 : Réécriture `run_scout` (3 phases, n_bsr=3, cache, coût, BSR_SOURCE)

**Files:**
- Modify: `01-scripts/scout_master.py`
- Test: `tests/test_scout_master.py`

- [ ] **Step 1 : Mettre à jour les fakes + tests (échouent)**

Remplacer `tests/test_scout_master.py` par :

```python
from scout_master import run_scout
from cost_tracker import CostTracker
from models import NicheCandidate, NicheValidation, SearchResult, SearchItem, BsrInfo


def _fake_ideate(seed, signals, n, model, on_usage=None):
    if on_usage:
        on_usage(1000, 1200, model or "claude-sonnet-5")
    return [
        NicheCandidate(niche="tarot", requete_amazon="tarot", rationale="r", categorie="éso"),
        NicheCandidate(niche="mort", requete_amazon="zzzz", rationale="r", categorie="x"),
    ]


def _fake_validate(cands, **kw):
    return [
        NicheValidation(niche="tarot", requete_amazon="tarot", categorie="éso",
                        demand_score=6, validated=True),
        NicheValidation(niche="mort", requete_amazon="zzzz", categorie="x",
                        demand_score=0, validated=False),
    ]


class _FakeProvider:
    priority = 2
    location_code = 2250
    language_code = "fr_FR"

    def search(self, q, books_only=True):
        return SearchResult(keyword=q, sponsored=[], organic=[
            SearchItem(title="Tarot débutant", asin="A1", rating=4.5, reviews_count=6000),
            SearchItem(title="Tarot de marseille", asin="A2", rating=4.3, reviews_count=200),
        ])


def _fake_bsr(asin):
    return {"A1": BsrInfo(rank_livres=3000, asin="A1"),
            "A2": BsrInfo(rank_livres=60000, asin="A2")}.get(asin)


def test_run_scout_end_to_end_mocked():
    cost = CostTracker()
    res = run_scout(seed="ésotérisme", n_search=3, bsr_pause=0, use_cache=False, cost=cost,
                    ideate=_fake_ideate, validate=_fake_validate,
                    provider=_FakeProvider(), fetch_bsr_fn=_fake_bsr)
    assert len(res) == 1
    s = res[0]
    assert s.niche == "tarot" and s.n_organic == 2 and s.top_asins == ["A1", "A2"]
    assert s.bsr_best == 3000 and s.criteres_bsr_ok is True
    assert 1.0 <= s.global_score <= 10.0
    assert cost.breakdown()["llm_tokens_in"] == 1000     # coût ideator capté


def test_run_scout_no_validated_returns_empty():
    def validate_none(cands, **kw):
        return [NicheValidation(niche="x", requete_amazon="x", categorie="c",
                                demand_score=0, validated=False)]
    res = run_scout(seed="x", ideate=_fake_ideate, validate=validate_none,
                    provider=_FakeProvider(), fetch_bsr_fn=_fake_bsr, bsr_pause=0, use_cache=False)
    assert res == []
```

- [ ] **Step 2 : Lancer (échoue)**

Run : `python -m pytest tests/test_scout_master.py -v`
Attendu : FAIL (`run_scout` ne prend pas `use_cache`/`cost` et n'appelle pas `on_usage`)

- [ ] **Step 3 : Réécrire `run_scout`**

Remplacer le corps de `run_scout` (imports + fonction) dans `01-scripts/scout_master.py`. En tête, ajouter les imports :

```python
from bsr_source import resolve_bsrs
from cache import Cache
from cost_tracker import CostTracker
```

Remplacer la fonction `run_scout` par :

```python
_SEARCH_TTL_S = 10 * 24 * 3600     # 10 jours


def run_scout(seed: str | None = None, signals: dict | None = None,
              n_ideas: int = 12, n_search: int = 6, n_bsr_per_niche: int = 3,
              model: str | None = None, provider=None, progress=None,
              bsr_pause: float = 0.4, books_only: bool = True,
              use_cache: bool = True, cache_path: str | None = None,
              bsr_source: str | None = None, bsr_priority: int = 2, cost=None,
              ideate=None, validate=None, fetch_bsr_fn=None) -> list[ScoredNiche]:
    """Scout complet, 3 phases : ideator → validation demande → [search par niche] →
    [BSR batché global : dédup + cache] → scoring §4.1. Renvoie les niches triées.

    Coût mesurable via `cost` (CostTracker fourni par l'appelant). BSR gratuit en local
    (BSR_SOURCE=scrape), payant/fiable en serveur (BSR_SOURCE=dataforseo)."""
    progress = progress or _noop
    ideate = ideate or _generate_niches
    validate = validate or _validate_niches
    cost = cost if cost is not None else CostTracker()
    load_dotenv()

    from pathlib import Path
    _root = Path(__file__).resolve().parent.parent
    cache = None
    if use_cache:
        cache = Cache(cache_path or (_root / "99-logs" / "df-cache.db"))

    # 1) Ideator (coût LLM réel via on_usage)
    progress(f"Génération de niches par l'IA (graine : {seed or 'aucune'})…")
    candidates = ideate(seed=seed, signals=signals, n=n_ideas, model=model,
                        on_usage=lambda i, o, m: cost.add_llm(m, i, o))
    progress(f"{len(candidates)} niches proposées par l'IA.")

    # 2) Validation demande (gratuit, autocomplete)
    progress("Validation de la demande sur Amazon (autocomplete, gratuit)…")
    validations = validate(candidates, pause=0.4, max_queries=3)
    validated = [v for v in validations if v.validated]
    progress(f"{len(validated)}/{len(validations)} niches avec demande confirmée.")

    shortlist = validated[:n_search]
    if not shortlist:
        progress("Scout terminé.")
        return []
    provider = provider or get_provider("dataforseo")
    loc = getattr(provider, "location_code", 2250)
    lang = getattr(provider, "language_code", "fr_FR")

    # Phase A — concurrence Amazon par niche (search, caché par mot-clé)
    per_niche = []          # (validation, SearchResult|None, [asins top-n])
    all_asins: list[str] = []
    for i, v in enumerate(shortlist, 1):
        q = v.requete_amazon or v.niche
        progress(f"[{i}/{len(shortlist)}] Concurrence Amazon « {q} »…")
        sr = cache.get_search(q, loc, lang) if cache else None
        if sr is None:
            try:
                sr = provider.search(q, books_only=books_only)
                cost.add_dataforseo(1, getattr(provider, "priority", 2))
                if cache:
                    cache.set_search(q, loc, lang, sr, _SEARCH_TTL_S)
            except Exception as e:  # noqa: BLE001 — on n'interrompt jamais le run
                progress(f"  ⚠ search échec ({e}) — niche scorée sans concurrence.")
                sr = None
        asins = [o.asin for o in (sr.organic if sr else []) if o.asin][:n_bsr_per_niche]
        per_niche.append((v, sr, asins))
        all_asins.extend(asins)

    # Phase B — BSR global (batché, dédup + cache)
    progress(f"Récupération des BSR ({len(set(all_asins))} livres uniques)…")
    bsr_map = resolve_bsrs(all_asins, source=bsr_source, provider=provider,
                           fetch_bsr_fn=fetch_bsr_fn, cache=cache, location=loc,
                           bsr_priority=bsr_priority, cost=cost, bsr_pause=bsr_pause)

    # Phase C — scoring
    scored: list[ScoredNiche] = []
    for v, sr, asins in per_niche:
        bsrs = [bsr_map[a].rank_livres for a in asins
                if bsr_map.get(a) and bsr_map[a].rank_livres]
        scored.append(score_niche(v, sr, bsrs))

    scored.sort(key=lambda s: s.global_score, reverse=True)
    b = cost.breakdown()
    progress(f"Scout terminé. Coût ~{b['usd']:.4f} $ "
             f"({b['dataforseo_calls']} appels DataForSEO + LLM).")
    return scored
```

Retirer l'import désormais inutile `from amazon_product import fetch_bsr as _fetch_bsr` (le fallback scrape vit maintenant dans `bsr_source`) et l'import `time` s'il n'est plus utilisé ailleurs dans le fichier.

- [ ] **Step 4 : Ajouter l'affichage coût au CLI `main()`**

Dans `main()`, après `results = run_scout(...)`, passer un tracker et l'afficher :

```python
    cost = CostTracker()
    results = run_scout(seed=args.seed, n_ideas=args.ideas, n_search=args.search,
                        progress=print, cost=cost)
    print("\n=== NICHES CLASSÉES ===")
    for s in results:
        _print_row(s)
    b = cost.breakdown()
    print(f"\nCoût du run : ~{b['usd']:.4f} $  "
          f"(DataForSEO {b['dataforseo_usd']:.4f} $ / LLM {b['llm_usd']:.4f} $)")
```

- [ ] **Step 5 : Lancer toute la suite (passe)**

Run : `python -m pytest -q`
Attendu : PASS (toute la suite, y compris les nouveaux modules)

- [ ] **Step 6 : Commit**

```bash
git add 01-scripts/scout_master.py tests/test_scout_master.py
git commit -m "feat(scout): run_scout 3 phases — BSR batché+caché, n_bsr=3, source flag, coût mesuré"
```

---

## Task 10 : Coût dans l'UI (SSE + affichage)

**Files:**
- Modify: `web/server.py`
- Modify: `web/index.html`

- [ ] **Step 1 : Émettre l'événement `cost` en SSE**

Dans `web/server.py`, importer et instrumenter le worker :

```python
from cost_tracker import CostTracker  # noqa: E402  (après l'ajout de 01-scripts au sys.path)
```

Dans `scout()`, modifier `worker()` :

```python
    def worker() -> None:
        cost = CostTracker()
        try:
            results = run_scout(seed=(seed or None), n_ideas=ideas, n_search=search,
                                progress=progress, cost=cost)
            q.put(("result", [r.model_dump() for r in results]))
            q.put(("cost", cost.breakdown()))
        except Exception as e:  # noqa: BLE001
            q.put(("error", f"{type(e).__name__}: {e}"))
        finally:
            q.put(("done", None))
```

Le `stream()` relaie déjà tout `kind` non-`done` via `_sse(kind, payload)` — l'événement `cost` passe donc sans changement.

- [ ] **Step 2 : Afficher le coût dans `web/index.html`**

Ajouter (near le bloc résultats) un conteneur discret :

```html
<div id="cost" class="cost" hidden></div>
```

Dans le script EventSource, ajouter un handler :

```javascript
es.addEventListener('cost', (e) => {
  const c = JSON.parse(e.data);
  const el = document.getElementById('cost');
  el.hidden = false;
  el.textContent = `Coût de ce run : ~$${c.usd.toFixed(4)} `
    + `(DataForSEO $${c.dataforseo_usd.toFixed(4)} · LLM $${c.llm_usd.toFixed(4)} · `
    + `${c.dataforseo_calls} appels)`;
});
```

Ajouter un style minimal cohérent avec le dashboard (Fira Code, gris atténué, aligné à droite sous la table) :

```css
.cost { margin-top: 12px; font-family: 'Fira Code', monospace; font-size: 12px;
        color: var(--muted, #64748B); text-align: right; }
```

> Utiliser les variables CSS/tokens déjà définis dans `index.html` (couleur atténuée, monospace). Ne pas introduire de nouvelle palette.

- [ ] **Step 3 : Vérifier en live (preview)**

Lancer le serveur web (preview_start `IA-Niches (Web)` / launch.json), lancer un scout court (seed « stoïcisme », ideas=6, search=2), confirmer via `preview_snapshot` que la ligne coût s'affiche après les résultats, et via `preview_logs` un seul appel `/api/scout`.

- [ ] **Step 4 : Commit**

```bash
git add web/server.py web/index.html
git commit -m "feat(ui): coût réel du run streamé en SSE + affiché sous les résultats"
```

---

## Task 11 : Nettoyage du code v1 mort (Scrapingdog)

**Files:**
- Delete: `01-scripts/credits_tracker.py`, `01-scripts/amazon_search.py`
- Delete (si présents): `01-scripts/amazon_autocomplete 2.py`, scripts de debug v1 (`01-scripts/demo_free.py` si non testé — vérifier)

- [ ] **Step 1 : Confirmer que ces modules ne sont plus importés par le pipeline v2**

Run : `python -m pytest -q && rg -n "credits_tracker|amazon_search" 01-scripts web tests`
Attendu : seuls `amazon_search.py`/`credits_tracker.py` se référencent mutuellement (v1) ; aucun import depuis `scout_master`, `bsr_source`, `search_providers`, `web/`. Si `demo_free.py` est couvert par `tests/test_demo_free.py`, **le garder** ; sinon évaluer sa suppression.

- [ ] **Step 2 : Supprimer**

```bash
git rm "01-scripts/credits_tracker.py" "01-scripts/amazon_search.py"
git ls-files "01-scripts/amazon_autocomplete 2.py" && git rm "01-scripts/amazon_autocomplete 2.py" || true
```

- [ ] **Step 3 : Vérifier la suite**

Run : `python -m pytest -q`
Attendu : PASS (aucun test ne dépendait des fichiers supprimés)

- [ ] **Step 4 : Commit**

```bash
git commit -m "chore: retire le code v1 mort (Scrapingdog : credits_tracker, amazon_search)"
```

---

## Task 12 : Rafraîchir README.md + ROADMAP.md

**Files:**
- Modify: `README.md`
- Modify: `ROADMAP.md`

- [ ] **Step 1 : README — supprimer Scrapingdog, documenter l'architecture réelle**

Réécrire les sections concernées pour refléter :
- **Canaux** : autocomplete Amazon (gratuit, validation demande), search **DataForSEO** rayon Livres (payant, ~0,003 $/niche), BSR via **DataForSEO ASIN** batché (serveur) ou scraping fiche (local, gratuit) selon `BSR_SOURCE`.
- **Config** : `.env` = `ANTHROPIC_API_KEY`, `DATAFORSEO_LOGIN`, `DATAFORSEO_PASSWORD` (password d'API), `IDEATOR_MODEL` (défaut `claude-sonnet-5`), `BSR_SOURCE` (`scrape` défaut / `dataforseo`). Plus aucune mention de `SCRAPINGDOG_API_KEY`.
- **Coût** : ~0,01–0,06 $/run selon cache et `n_search` ; cache SQLite `99-logs/df-cache.db` (graines récurrentes ~0 $).
- **Lancer** : hérisson CLI (`IA-Niches.bat`) et UI web (`IA-Niches (Web)`), + `python -m pytest`.

- [ ] **Step 2 : ROADMAP — acter le fait + la suite**

Mettre à jour : P0 (BSR fiable) / P1 (économies) / P2 (instrumentation coût) **faits** ; **suite** = verdict IA par niche (directeur éditorial §7-8 branché en tool-use, gaté top-3) puis comptes utilisateurs + crédits métrés (SQLite) + Stripe. Marketplace EN plus tard.

- [ ] **Step 3 : Commit**

```bash
git add README.md ROADMAP.md
git commit -m "docs: README/ROADMAP à jour (DataForSEO + cache + coût, fin de Scrapingdog)"
```

---

## Self-Review (relecture à froid vs le brief)

**1. Couverture du brief :**
- P0 BSR fiable serveur → T1 (parseur) + T3 (batch) + T6 (source flag + fallback scrape) + T9 (branchement, `sans aucune requête amazon.fr` en mode dataforseo). ✅
- P1 n_bsr 5→3 → T9 (défaut 3) + T7 (recalibrage §4.1). ✅
- P1 cache inter-runs → T4 (SQLite) + T6/T9 (câblage BSR + search, cross-user, TTL). ✅
- P1 files Priority/Standard → décision : BSR en Priority (correction du §3c, Standard=~45 min) ; `bsr_priority` exposé. ✅
- P1 scoping Livres → T2 (`search_param=i=stripbooks`) ; les non-livres n'ont pas de rang Livres → exclus (T1). ✅
- P2 compteur coût → T5 (`CostTracker`, tarifs Sonnet 5 intro/std + DataForSEO) + T9 (agrégation) + T10 (SSE/UI). ✅
- Nettoyage credits_tracker → T11. ✅ | README/ROADMAP périmés → T12. ✅
- Garde-fou "aucun réseau en unit-test" : tout est injectable (post_json/get_json, fetch_bsr_fn, cache tmp_path, client Anthropic factice). ✅

**2. Placeholders :** aucun « TBD » ; chaque étape porte du code ou une commande exacte.

**3. Cohérence des types :** `parse_asin_bsr → BsrInfo` (T1) ; `product_info_batch → {asin: BsrInfo|None}` (T3) ; `resolve_bsrs` consomme `fetch_bsr_fn(asin)->BsrInfo|None` **et** `provider.product_info_batch` (T6) ; `run_scout` lit `bsr_map[a].rank_livres` (T9) — aligné. `Cache.get_bsr/get_search` reconstruisent via `model_validate` (T4). `CostTracker.add_llm/add_dataforseo/breakdown` cohérents entre T5, T9, T10. `on_usage(i,o,m)` identique T8/T9.

**4. Hors périmètre (confirmé) :** verdict IA par niche (5a) et comptes/crédits/Stripe (5b) — chantiers suivants, non inclus.

---

## Handoff

À l'exécution : `python -m pytest -q` doit rester vert à chaque tâche. Le mode par défaut reste `BSR_SOURCE=scrape` (runs perso gratuits) ; le chemin `dataforseo` est testé hors-ligne (fixtures) et prêt pour le déploiement serveur.
