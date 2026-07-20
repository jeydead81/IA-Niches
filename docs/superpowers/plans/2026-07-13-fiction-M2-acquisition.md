# Fiction M2 — Acquisition (SERP contrainte + enrichissement ASIN) — Plan d'implémentation

> **For agentic workers:** REQUIRED SUB-SKILL: superpowers:subagent-driven-development.

**Goal:** Reconstituer le « rayon » d'une niche fiction : SERP contrainte au browse node (ou à la requête si le sous-genre n'a pas de rayon), puis enrichissement **batché** des N premiers ASIN en `EnrichedBook`, avec **cache inter-runs** et **coût mesuré**.

**Architecture :** Un parseur **pur** (`parse_enriched_book`) mappe le payload ASIN réel vers `EnrichedBook` — testé sur les **fixtures live** déjà committées. Le provider gagne `product_raw_batch` (le même batch que `product_info_batch`, mais rendant les payloads bruts ; `product_info_batch` en devient un simple consommateur — une seule implémentation de la boucle de poll). `search()` accepte un `search_param` explicite pour porter la contrainte de node. L'orchestrateur `fetch_fiction_shelf` assemble le tout.

**Faits qui pilotent le design (vérifiés live, cf. `docs/spike_fiction_M0.md`) :**
- Contrainte node : `search_param="rh=n:<node>"`. Sous-genre sans node → repli `search_param_for(rayon)` (`i=digital-text` / `i=stripbooks`).
- Clés « Détails » réelles : `Date de publication`, `Éditeur`, `Langue`, `Classement des meilleures ventes d'Amazon`, et la clé **série** `Livre N sur M`.
- Champs item réels : `title`, `author`, `price_from`, `rating.value`, `rating.votes_count`, `description`, `categories`, `data_asin`.
- BSR : passer par `parse_bsr_rank` → (rang, **rayon**, **gratuit**). Un titre gratuit garde son rang mais est marqué — c'est le scoring (M5) qui l'écarte, pas l'acquisition.
- `bought_past_month` / badge KU : **inexistants** → absents du parseur.

**Tech Stack :** Python 3.13, pytest (`pythonpath=01-scripts`, `testpaths=tests`), pydantic v2.

---

## Task M2-1 : `parse_enriched_book` — parseur pur, testé sur payloads réels

**Files:** Create `01-scripts/fiction_books.py` · Test `tests/test_fiction_books.py`

- [ ] **Step 1 : Test (échoue)** — `tests/test_fiction_books.py`, appuyé sur les **fixtures live committées** :
```python
import json
from pathlib import Path

from fiction_books import parse_enriched_book, _series_hint_from_title
from models import EnrichedBook

_FIC = Path(__file__).parent / "fixtures" / "fiction"
_PRINT = json.loads((_FIC / "v2_asin_payloads.json").read_text(encoding="utf-8"))
_KINDLE = json.loads((_FIC / "m1_kindle_nodes.json").read_text(encoding="utf-8"))


def test_parse_livre_papier_reel():
    b = parse_enriched_book(_PRINT["1923235036"], serp_position=8)
    assert isinstance(b, EnrichedBook)
    assert b.asin == "1923235036"
    assert b.title.startswith("Les Racines du Mal")
    assert b.author == "H.Y. Hanna"
    assert b.bsr == 1597 and b.bsr_rayon == "Livres" and b.bsr_gratuit is False
    assert b.serie_tome == 5 and b.serie_total == 6 and b.est_serie is True
    assert b.publisher and b.langue and b.publication_date
    assert b.serp_position == 8


def test_parse_ebook_gratuit_marque_mais_conserve():
    b = parse_enriched_book(_PRINT["B0FF82S9MW"], serp_position=1)
    assert b.bsr == 478 and b.bsr_rayon == "Boutique Kindle"
    assert b.bsr_gratuit is True                  # marqué ici, écarté au scoring (M5)
    assert b.est_payant_dans("Boutique Kindle") is False


def test_parse_sans_bsr_ne_plante_pas():
    b = parse_enriched_book(_PRINT["B0FS7JQNJ6"], serp_position=3)
    assert b is not None and b.bsr is None and b.bsr_rayon is None


def test_series_hint_heuristique():
    assert _series_hint_from_title("Meurtres et cupcakes - tome 15") is True
    assert _series_hint_from_title("Black Sword, T2 : la suite") is True
    assert _series_hint_from_title("Les Enquêtes d'Etsy, Livre 3") is True
    assert _series_hint_from_title("Un meurtre absolument splendide") is False


def test_parse_payload_vide():
    assert parse_enriched_book({}, serp_position=0) is None
```

- [ ] **Step 2 : Lancer** → FAIL (module absent).

- [ ] **Step 3 : Implémenter `01-scripts/fiction_books.py`** :
```python
"""fiction_books.py — mappe un payload ASIN DataForSEO réel vers EnrichedBook.
Parsing PUR (aucun réseau), testé sur les fixtures live du spike M0/M1.
Les chemins de champs viennent des payloads observés, pas d'une supposition."""
import re

from models import EnrichedBook
from search_providers import parse_bsr_rank

_SERIE_KEY = re.compile(r"^livre\s+(\d+)\s+sur\s+(\d+)$", re.I)
_SERIE_TITLE = re.compile(r"\b(?:tome|livre|vol\.?|t)\s*\d+|#\d+", re.I)
_BSR_KEY = "meilleures ventes"


def _series_hint_from_title(title: str) -> bool:
    """Repli heuristique quand la clé structurée « Livre N sur M » est absente."""
    return bool(_SERIE_TITLE.search(title or ""))


def _details(item: dict) -> dict:
    out: dict = {}
    for sec in (item.get("product_information") or []):
        b = sec.get("body")
        if isinstance(b, dict):
            out.update(b)
    return out


def parse_enriched_book(result: dict, serp_position: int = 0) -> EnrichedBook | None:
    """Payload ASIN (advanced) -> EnrichedBook. None si le payload est inexploitable."""
    items = (result or {}).get("items") or []
    item = next((it for it in items if it.get("type") == "amazon_product_info"),
                items[0] if items else None)
    if not item:
        return None
    asin = (result or {}).get("asin") or item.get("data_asin")
    if not asin:
        return None
    det = _details(item)
    low = {k.lower(): (k, v) for k, v in det.items()}

    def pick(frag: str):
        for kl, (k, v) in low.items():
            if frag in kl:
                return v
        return None

    rang = rayon = None
    gratuit = False
    bsr_raw = pick(_BSR_KEY)
    if isinstance(bsr_raw, str):
        rang, rayon, gratuit = parse_bsr_rank(bsr_raw)

    tome = total = None
    for k in det:
        m = _SERIE_KEY.match(k.strip())
        if m:
            tome, total = int(m.group(1)), int(m.group(2))
            break

    rating = item.get("rating") if isinstance(item.get("rating"), dict) else {}
    title = item.get("title") or ""
    return EnrichedBook(
        asin=asin,
        title=title,
        author=item.get("author"),
        price=item.get("price_from"),
        reviews_count=rating.get("votes_count"),
        rating=rating.get("value"),
        bsr=rang,
        bsr_rayon=rayon,
        bsr_gratuit=gratuit,
        publication_date=pick("date de publication"),
        publisher=pick("diteur"),
        langue=pick("langue"),
        serie_tome=tome,
        serie_total=total,
        series_hint=_series_hint_from_title(title),
        serp_position=serp_position,
    )
```

- [ ] **Step 4 : Lancer** `python -m pytest -q` → vert. **Step 5 : Commit**
```bash
git add 01-scripts/fiction_books.py tests/test_fiction_books.py
git commit -m "feat(fiction): parse_enriched_book — payload ASIN réel -> EnrichedBook (testé sur fixtures live)"
```

---

## Task M2-2 : Provider — `product_raw_batch` + `search_param` explicite

**Files:** Modify `01-scripts/search_providers.py` · Test `tests/test_search_providers.py`

- [ ] **Step 1 : Tests (échouent)** — ajouter à `tests/test_search_providers.py` :
```python
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
```

- [ ] **Step 2 : Lancer** → FAIL.

- [ ] **Step 3 : Implémenter** dans `01-scripts/search_providers.py` :
  1. `search(...)` : ajouter le paramètre `search_param: str | None = None` (après `books_only`). Dans la construction de `item` : si `search_param` est fourni, `item["search_param"] = search_param` **et** ignorer `books_only` ; sinon comportement actuel (`i=stripbooks` si `books_only`).
  2. Ajouter `product_raw_batch(asins, post_json=None, get_json=None, poll_interval=8, max_polls=40) -> dict` : **exactement la boucle actuelle de `product_info_batch`** mais qui stocke `r["result"][0]` (payload brut) au lieu de `parse_asin_bsr(...)`.
  3. Réécrire `product_info_batch` pour **déléguer** :
```python
    def product_info_batch(self, asins, post_json=None, get_json=None,
                           poll_interval: float = 8, max_polls: int = 40) -> dict:
        """BSR de plusieurs ASIN (batché). Retour : {asin: BsrInfo|None}."""
        raw = self.product_raw_batch(asins, post_json=post_json, get_json=get_json,
                                     poll_interval=poll_interval, max_polls=max_polls)
        return {a: (parse_asin_bsr(r) if r else None) for a, r in raw.items()}
```
  Les tests existants de `product_info_batch` doivent rester verts (le seam HTTP est inchangé).

- [ ] **Step 4 : Lancer** `python -m pytest -q` → vert, **y compris `tests/test_amazon_asin.py`**. **Step 5 : Commit**
```bash
git add 01-scripts/search_providers.py tests/test_search_providers.py
git commit -m "feat(fiction): product_raw_batch + search_param explicite (contrainte node)"
```

---

## Task M2-3 : Cache des livres enrichis (TTL 7 j)

**Files:** Modify `01-scripts/cache.py` · Test `tests/test_cache.py`

- [ ] **Step 1 : Test (échoue)** — ajouter à `tests/test_cache.py` :
```python
def test_book_helpers(tmp_path):
    from models import EnrichedBook
    c = Cache(tmp_path / "c.db")
    b = EnrichedBook(asin="A1", title="T", bsr=20, bsr_rayon="Boutique Kindle", serp_position=3)
    c.set_book("A1", 2250, b, ttl_s=100)
    got = c.get_book("A1", 2250)
    assert got.asin == "A1" and got.bsr == 20 and got.bsr_rayon == "Boutique Kindle"
    assert c.get_book("A2", 2250) is None
```

- [ ] **Step 2 : Lancer** → FAIL. **Step 3 : Implémenter** dans `01-scripts/cache.py` : importer `EnrichedBook`, ajouter `BOOK_TTL_S = 7 * 24 * 3600`, une clé `_book_key(asin, location) -> f"book:{location}:{asin}"`, et les helpers `get_book(asin, location) -> EnrichedBook | None` / `set_book(asin, location, book, ttl_s)` sur le modèle exact de `get_bsr`/`set_bsr` (`model_dump()` / `model_validate`).

- [ ] **Step 4 : Lancer** → vert. **Step 5 : Commit**
```bash
git add 01-scripts/cache.py tests/test_cache.py
git commit -m "feat(fiction): cache des livres enrichis (clé ASIN, TTL 7 j)"
```

---

## Task M2-4 : `fetch_fiction_shelf` — orchestration du rayon

**Files:** Create `01-scripts/fiction_serp_provider.py` · Test `tests/test_fiction_serp_provider.py`

- [ ] **Step 1 : Test (échoue)** — `tests/test_fiction_serp_provider.py` :
```python
from fiction_serp_provider import fetch_fiction_shelf, search_param_for_niche
from models import FictionNiche, SearchResult, SearchItem, EnrichedBook
from cost_tracker import CostTracker


def _niche(sg="cosy_mystery", rayon="kindle"):
    return FictionNiche(sous_genre=sg, tropes=["animal_compagnon"], decor="ile",
                        rayon=rayon, query="cosy mystery chat ile")


def test_search_param_node_sinon_repli_rayon():
    assert search_param_for_niche(_niche()) == "rh=n:205566725031"          # node dispo
    assert search_param_for_niche(_niche("feel_good")) == "i=digital-text"  # pas de node -> rayon
    assert search_param_for_niche(_niche("feel_good", "papier")) == "i=stripbooks"


class _Prov:
    priority = 2
    location_code = 2250
    language_code = "fr_FR"

    def __init__(self):
        self.seen = {}

    def search(self, keyword, depth=100, books_only=True, search_param=None):
        self.seen["search_param"] = search_param
        return SearchResult(keyword=keyword, organic=[
            SearchItem(title="A", asin="A1"), SearchItem(title="B", asin="A2")], sponsored=[])

    def product_raw_batch(self, asins):
        self.seen["asins"] = list(asins)
        return {a: {"asin": a, "items": [{"type": "amazon_product_info", "data_asin": a,
                                          "title": f"Titre {a}"}]} for a in asins}


def test_fetch_shelf_contraint_enrichit_et_compte_le_cout():
    cost = CostTracker()
    prov = _Prov()
    books = fetch_fiction_shelf(_niche(), provider=prov, n_top=2, cost=cost, cache=None)
    assert prov.seen["search_param"] == "rh=n:205566725031"
    assert prov.seen["asins"] == ["A1", "A2"]
    assert [b.asin for b in books] == ["A1", "A2"]
    assert all(isinstance(b, EnrichedBook) for b in books)
    assert books[0].serp_position == 1 and books[1].serp_position == 2
    b = cost.breakdown()
    assert b["dataforseo_calls"] == 3            # 1 SERP + 2 ASIN


def test_fetch_shelf_utilise_le_cache(tmp_path):
    from cache import Cache
    c = Cache(tmp_path / "c.db")
    c.set_book("A1", 2250, EnrichedBook(asin="A1", title="EN CACHE", serp_position=9), ttl_s=100)
    cost = CostTracker()
    prov = _Prov()
    books = fetch_fiction_shelf(_niche(), provider=prov, n_top=2, cost=cost, cache=c)
    assert prov.seen["asins"] == ["A2"]                  # A1 servi par le cache
    assert {b.asin for b in books} == {"A1", "A2"}
    assert next(b for b in books if b.asin == "A1").title == "EN CACHE"
    assert next(b for b in books if b.asin == "A1").serp_position == 1   # position du run
    assert cost.breakdown()["dataforseo_calls"] == 2     # 1 SERP + 1 ASIN seulement
```

- [ ] **Step 2 : Lancer** → FAIL. **Step 3 : Implémenter `01-scripts/fiction_serp_provider.py`** :
```python
"""fiction_serp_provider.py — reconstitue le « rayon » d'une niche fiction.
SERP contrainte au browse node (ou à la requête si le sous-genre n'a pas de rayon),
puis enrichissement BATCHÉ des n_top premiers ASIN, avec cache inter-runs et coût mesuré."""
from fiction_books import parse_enriched_book
from fiction_taxonomy import node_for, search_param_for
from models import EnrichedBook, FictionNiche

BOOK_TTL_S = 7 * 24 * 3600


def search_param_for_niche(niche: FictionNiche, version: str = "fr_v1") -> str:
    """Contrainte de rayon : le browse node si le sous-genre en a un, sinon le filtre
    de rayon (mode « rayon requête »)."""
    node = node_for(niche.sous_genre, niche.rayon, version)
    return f"rh=n:{node}" if node else search_param_for(niche.rayon, version)


def fetch_fiction_shelf(niche: FictionNiche, provider, n_top: int = 20, depth: int = 30,
                        cache=None, cost=None, version: str = "fr_v1") -> list[EnrichedBook]:
    """SERP contrainte -> n_top premiers ASIN -> EnrichedBook (cache + coût)."""
    sp = search_param_for_niche(niche, version)
    sr = provider.search(niche.query, depth=depth, search_param=sp)
    if cost is not None:
        cost.add_dataforseo(1, getattr(provider, "priority", 2))
    asins = [o.asin for o in sr.organic if o.asin][:n_top]
    loc = getattr(provider, "location_code", 2250)

    books: dict = {}
    misses: list[str] = []
    for a in asins:
        cached = cache.get_book(a, loc) if cache else None
        if cached is not None:
            books[a] = cached
        else:
            misses.append(a)

    if misses:
        raw = provider.product_raw_batch(misses)
        if cost is not None:
            cost.add_dataforseo(len(misses), getattr(provider, "priority", 2))
        for a in misses:
            b = parse_enriched_book(raw.get(a) or {})
            if b is not None:
                books[a] = b
                if cache:
                    cache.set_book(a, loc, b, BOOK_TTL_S)

    out: list[EnrichedBook] = []
    for i, a in enumerate(asins, 1):
        b = books.get(a)
        if b is not None:
            b.serp_position = i          # la position dépend du run, pas du cache
            out.append(b)
    return out
```

- [ ] **Step 4 : Lancer** `python -m pytest -q` → vert. **Step 5 : Commit**
```bash
git add 01-scripts/fiction_serp_provider.py tests/test_fiction_serp_provider.py
git commit -m "feat(fiction): fetch_fiction_shelf — SERP contrainte + enrichissement batché + cache + coût"
```

---

## Self-Review
- Contrainte node avec repli requête : M2-4 (`search_param_for_niche`), rayon **commutable** (papier passe par le même chemin). ✓
- Enrichissement **batché** (une attente de file), cache inter-runs, coût compté **uniquement sur les vrais appels**. ✓
- `serp_position` réécrite à chaque run (elle dépend de la requête, pas du livre) — piège de cache évité. ✓
- Titre gratuit : **conservé et marqué** à l'acquisition, écarté au scoring (M5). Séparation des responsabilités. ✓
- Parseur pur testé sur **payloads réels** committés, pas sur des mocks inventés. ✓
- `product_info_batch` délègue à `product_raw_batch` : une seule boucle de poll. ✓

## Suite
M3 sonde autocomplete · M4 classifieur de blurb (+ validation 50 livres) · M5 scoring (matrice de demande) · M6 orchestration/UI · puis le compteur de crédits.

---

## Correctifs post-revue

Passe de correctifs TDD sur ce chunk après revue de code, un commit par correctif.

1. `_SERIE_TITLE` reconnaît désormais « t. 1 » (point) sans faux positif sur « vol » sans point — `37cab7d`
2. `est_serie` exige `serie_total > 1` (« Livre 1 sur 1 » = tome unique, pas une série) — `b3cb139`
3. `parse_enriched_book` ne lève plus jamais (price FR, champ texte atypique, `product_information` en dict) : `None` si inexploitable, comme promis — `7873086`
4. Dédup des ASIN de la SERP (`dict.fromkeys`, ordre préservé) avant facturation/enrichissement — `d9b16b3`
5. `product_raw_batch` apparie les payloads par ASIN rendu (écho `task["data"]["asin"]`), plus par position — `b743f0d`
6. `fetch_fiction_shelf` rend un `FictionShelf` (compteurs `asins_demandes`/`n_echecs`/`complet`) au lieu de dropper les échecs d'enrichissement en silence — `f73ab39`
7. `label_rayon()` — pont explicite entre `FictionNiche.rayon` ("kindle"/"papier") et `EnrichedBook.bsr_rayon` (libellé Amazon), piège désamorcé pour M5 — `8898b74`
8. `bsr_subcats` rempli (sous-catégories BSR extraites après le rang principal, qualificatif "(Livres)" conservé) — `44d128b`
