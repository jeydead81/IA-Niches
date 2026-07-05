# IA-Niches v2 — Plan 1 : Fondations d'acquisition (canaux gratuits)

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Construire et tester les deux canaux d'acquisition Amazon *gratuits et validés en live* — l'autocomplete direct (« la niche est-elle cherchée ? ») et le parsing du BSR depuis les fiches produit (« quel est le vrai classement des ventes ? ») — avec un socle de tests réutilisable.

**Architecture:** Modules Python autonomes dans `01-scripts/`, importables et testés unitairement. Toute I/O réseau est injectable (on teste le *parsing* et la *logique* contre des fixtures issues des vraies réponses observées le 2026-07-05, jamais le réseau live). Les types partagés sont des modèles Pydantic dans `models.py`.

**Tech Stack:** Python 3.13, `requests` (déjà présent), `pydantic` v2 (nouveau), `pytest` (nouveau, dev). Pas de clé API dans ce plan (les deux canaux sont gratuits).

**Réfs :** spec `docs/superpowers/specs/2026-07-05-ia-niches-v2-design.md` (§2 faits F3/F4, §4 composants). Le Plan 2 (ideator, search DataForSEO, scoring, orchestrateur) sera écrit après exécution de ce plan.

---

### Task 1 : Socle de test + dépendances

**Files:**
- Create: `pytest.ini`
- Modify: `01-scripts/requirements.txt`
- Create: `tests/__init__.py`
- Create: `tests/test_sanity.py`

- [ ] **Step 1 : Ajouter les dépendances**

Modifier `01-scripts/requirements.txt` — ajouter à la fin :

```
# v2
pydantic>=2,<3
pytest>=8
```

- [ ] **Step 2 : Installer**

Run: `python -m pip install pydantic pytest`
Expected: installation OK (pydantic 2.x, pytest 8.x).

- [ ] **Step 3 : Configurer pytest** — créer `pytest.ini` à la racine :

```ini
[pytest]
pythonpath = 01-scripts
testpaths = tests
python_files = test_*.py
addopts = -q
```

- [ ] **Step 4 : Test sanity** — créer `tests/__init__.py` (vide) et `tests/test_sanity.py` :

```python
def test_python_and_pytest_work():
    assert 2 + 2 == 4
```

- [ ] **Step 5 : Vérifier que le socle tourne**

Run: `python -m pytest tests/test_sanity.py -v`
Expected: PASS (1 passed).

- [ ] **Step 6 : Commit**

```bash
git add pytest.ini tests/__init__.py tests/test_sanity.py "01-scripts/requirements.txt"
git commit -m "test: socle pytest + deps v2 (pydantic, pytest)"
```

---

### Task 2 : `util.py` — HTTP navigateur + retry

**Files:**
- Create: `01-scripts/util.py`
- Test: `tests/test_util.py`

- [ ] **Step 1 : Écrire le test qui échoue**

Créer `tests/test_util.py` :

```python
from util import http_get, BROWSER_HEADERS


class FakeResp:
    def __init__(self, status, text):
        self.status_code = status
        self.text = text


def test_headers_have_browser_ua():
    assert "Mozilla" in BROWSER_HEADERS["User-Agent"]
    assert BROWSER_HEADERS["Accept-Language"].startswith("fr-FR")


def test_http_get_retries_then_succeeds():
    calls = {"n": 0}

    def fake_get(url, headers=None, timeout=None):
        calls["n"] += 1
        if calls["n"] == 1:
            raise TimeoutError("boom")
        return FakeResp(200, "OK")

    r = http_get("https://example.test", getter=fake_get, retries=1, delay=0)
    assert r.status_code == 200
    assert calls["n"] == 2
```

- [ ] **Step 2 : Lancer, vérifier l'échec**

Run: `python -m pytest tests/test_util.py -v`
Expected: FAIL (`ModuleNotFoundError: No module named 'util'`).

- [ ] **Step 3 : Implémenter `01-scripts/util.py`**

```python
"""util.py — helpers HTTP communs (headers navigateur, GET avec retry).
Le réseau est injectable (paramètre `getter`) pour permettre les tests hors-ligne."""
import time
import requests

BROWSER_HEADERS = {
    "User-Agent": ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                   "(KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36"),
    "Accept": ("text/html,application/xhtml+xml,application/xml;q=0.9,"
               "image/avif,image/webp,*/*;q=0.8"),
    "Accept-Language": "fr-FR,fr;q=0.9,en;q=0.8",
    "Accept-Encoding": "gzip, deflate, br",
    "Upgrade-Insecure-Requests": "1",
}


def http_get(url, headers=None, timeout=20, retries=1, delay=5, getter=None):
    """GET avec headers navigateur + retry (garde-fou : max `retries` tentatives sup.).
    `getter` par défaut = requests.get ; injectable pour les tests."""
    getter = getter or requests.get
    h = dict(BROWSER_HEADERS)
    if headers:
        h.update(headers)
    last_exc = None
    for attempt in range(retries + 1):
        try:
            return getter(url, headers=h, timeout=timeout)
        except Exception as e:  # réseau/timeout
            last_exc = e
            if attempt < retries:
                time.sleep(delay)
    raise last_exc
```

- [ ] **Step 4 : Lancer, vérifier le succès**

Run: `python -m pytest tests/test_util.py -v`
Expected: PASS (2 passed).

- [ ] **Step 5 : Commit**

```bash
git add 01-scripts/util.py tests/test_util.py
git commit -m "feat(util): GET navigateur avec retry injectable"
```

---

### Task 3 : `models.py` — modèle `BsrInfo`

**Files:**
- Create: `01-scripts/models.py`
- Test: `tests/test_models.py`

- [ ] **Step 1 : Écrire le test qui échoue**

Créer `tests/test_models.py` :

```python
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
```

- [ ] **Step 2 : Lancer, vérifier l'échec**

Run: `python -m pytest tests/test_models.py -v`
Expected: FAIL (`No module named 'models'`).

- [ ] **Step 3 : Implémenter `01-scripts/models.py`**

```python
"""models.py — types partagés du scout v2 (Pydantic).
Le Plan 2 y ajoutera NicheCandidate, SearchResult, ScoredNiche."""
from pydantic import BaseModel, Field


class BsrInfo(BaseModel):
    """Classement des ventes d'une fiche produit amazon.fr (bloc 'Classement
    des meilleures ventes')."""
    asin: str | None = None
    rank_livres: int                       # rang dans la catégorie racine "Livres"
    subcategories: list[dict] = Field(default_factory=list)  # [{"category": str, "rank": int}]
    raw: str | None = None                 # extrait texte pour debug/transparence
```

- [ ] **Step 4 : Lancer, vérifier le succès**

Run: `python -m pytest tests/test_models.py -v`
Expected: PASS (2 passed).

- [ ] **Step 5 : Commit**

```bash
git add 01-scripts/models.py tests/test_models.py
git commit -m "feat(models): BsrInfo (Pydantic)"
```

---

### Task 4 : `amazon_product.py` — parsing BSR (le cœur gratuit)

> Le parseur est calibré sur les vraies fiches amazon.fr observées le 2026-07-05
> (ex. « Classement des meilleures ventes d'Amazon : 1 346 172 en Livres ( Voir les
> 100 premiers en Livres ) 35 876 en Livres d'activités pour enfants »). Les nombres
> utilisent l'espace fine insécable ` ` comme séparateur de milliers.

**Files:**
- Create: `01-scripts/amazon_product.py`
- Test: `tests/test_amazon_product.py`

- [ ] **Step 1 : Écrire le test qui échoue**

Créer `tests/test_amazon_product.py` :

```python
from amazon_product import parse_bsr, fetch_bsr, _to_int

# Fragment réaliste (HTML + espaces fines insécables   comme sur amazon.fr)
FIXTURE = (
    "<div id='detailBullets'>"
    "<span>Classement des meilleures ventes d'Amazon :</span> "
    "<span>23 372 en <a href='/gp/bestsellers/books'>Livres</a> "
    "(<a href='/gp/bestsellers/books'>Voir les 100 premiers en Livres</a>)</span>"
    "<ul><li><span>13 en <a href='/x'>Sciences infirmières</a></span></li>"
    "<li><span>180 en <a href='/y'>Manuels de médecine</a></span></li></ul>"
    "</div>"
)


def test_to_int_handles_thin_spaces():
    assert _to_int("23 372") == 23372
    assert _to_int("1 346 172") == 1346172
    assert _to_int("") is None


def test_parse_bsr_extracts_main_rank():
    info = parse_bsr(FIXTURE)
    assert info is not None
    assert info.rank_livres == 23372


def test_parse_bsr_extracts_subcategories():
    info = parse_bsr(FIXTURE)
    cats = {s["category"]: s["rank"] for s in info.subcategories}
    assert cats.get("Sciences infirmières") == 13
    # la catégorie racine "Livres" et le bruit "Voir les 100..." ne sont PAS des sous-catégories
    assert "Livres" not in cats


def test_parse_bsr_none_when_absent():
    assert parse_bsr("<div>aucun classement ici</div>") is None


def test_fetch_bsr_sets_asin_and_uses_injected_html():
    info = fetch_bsr("2266283340", fetch_html=lambda asin: FIXTURE)
    assert info.asin == "2266283340"
    assert info.rank_livres == 23372
```

- [ ] **Step 2 : Lancer, vérifier l'échec**

Run: `python -m pytest tests/test_amazon_product.py -v`
Expected: FAIL (`No module named 'amazon_product'`).

- [ ] **Step 3 : Implémenter `01-scripts/amazon_product.py`**

```python
"""amazon_product.py — récupère le BSR (classement des ventes) d'une fiche produit
amazon.fr en la scrappant DIRECTEMENT (gratuit, validé live depuis l'IP utilisateur).
Le parsing est pur et testé ; l'I/O réseau est injectable."""
import re

import util
from models import BsrInfo

# Bloc "Classement des meilleures ventes" (on borne à 1500 car pour rester local)
_BLOCK = re.compile(r"Classement des meilleures ventes.{0,1500}", re.I | re.S)
# rang principal : "N en Livres" (catégorie racine)
_MAIN = re.compile(r"([\d][\d\s.  ]{0,14}?)\s*en\s+Livres\b", re.I)
# sous-catégories : "N en <NomCatégorie>"
_SUB = re.compile(
    r"([\d][\d\s.  ]{0,14}?)\s*en\s+([A-Za-zÀ-ÿ][^\d(]{2,50}?)(?=\s{2,}|\s+\d|$)",
    re.I,
)


def _strip_tags(html: str) -> str:
    return re.sub(r"<[^>]+>", " ", html)


def _to_int(s: str) -> int | None:
    digits = re.sub(r"[^\d]", "", s or "")
    return int(digits) if digits else None


def parse_bsr(html: str) -> BsrInfo | None:
    """Extrait le rang Livres + sous-catégories du bloc BSR. None si absent."""
    m = _BLOCK.search(html)
    if not m:
        return None
    text = re.sub(r"\s+", " ", _strip_tags(m.group(0)))
    main = _MAIN.search(text)
    rank_livres = _to_int(main.group(1)) if main else None
    if rank_livres is None:
        return None
    subs: list[dict] = []
    for sm in _SUB.finditer(text):
        cat = sm.group(2).strip(" .:,")
        if cat.lower() == "livres" or "voir les" in cat.lower():
            continue  # catégorie racine ou lien "Voir les 100 premiers"
        rank = _to_int(sm.group(1))
        if rank and cat:
            subs.append({"category": cat, "rank": rank})
    return BsrInfo(rank_livres=rank_livres, subcategories=subs[:5], raw=text[:300])


def _default_fetch_html(asin: str) -> str | None:
    r = util.http_get(f"https://www.amazon.fr/dp/{asin}")
    return r.text if getattr(r, "status_code", None) == 200 else None


def fetch_bsr(asin: str, fetch_html=None) -> BsrInfo | None:
    """Récupère et parse le BSR d'un ASIN. `fetch_html(asin)->str|None` injectable."""
    fetch_html = fetch_html or _default_fetch_html
    html = fetch_html(asin)
    if not html:
        return None
    info = parse_bsr(html)
    if info:
        info.asin = asin
    return info
```

- [ ] **Step 4 : Lancer, vérifier le succès**

Run: `python -m pytest tests/test_amazon_product.py -v`
Expected: PASS (5 passed).

- [ ] **Step 5 : Commit**

```bash
git add 01-scripts/amazon_product.py tests/test_amazon_product.py
git commit -m "feat(amazon_product): parsing BSR gratuit depuis les fiches produit"
```

---

### Task 5 : `amazon_autocomplete.py` — autocomplete direct (réécriture)

> Réécriture : supprime la dépendance Scrapingdog. Endpoint direct
> `completion.amazon.fr/api/2017/suggestions` (validé live : HTTP 200, suggestions
> réelles pour « tarot »). Format de réponse : `{"suggestions": [{"value": "..."}]}`.

**Files:**
- Create/Overwrite: `01-scripts/amazon_autocomplete.py`
- Test: `tests/test_amazon_autocomplete.py`

- [ ] **Step 1 : Écrire le test qui échoue**

Créer `tests/test_amazon_autocomplete.py` :

```python
from amazon_autocomplete import parse_suggestions, fetch_suggestions

# Format réel observé le 2026-07-05
FIXTURE = {"suggestions": [
    {"value": "tarot"},
    {"value": "tarot divinatoire"},
    {"value": "tarot de marseille"},
    {"value": ""},          # vide → ignoré
]}


def test_parse_suggestions_filters_empty():
    out = parse_suggestions(FIXTURE)
    assert out == ["tarot", "tarot divinatoire", "tarot de marseille"]


def test_parse_suggestions_bad_payload():
    assert parse_suggestions({}) == []
    assert parse_suggestions({"suggestions": None}) == []


def test_fetch_suggestions_uses_injected_json():
    out = fetch_suggestions("tarot", fetch_json=lambda prefix: FIXTURE)
    assert "tarot divinatoire" in out
```

- [ ] **Step 2 : Lancer, vérifier l'échec**

Run: `python -m pytest tests/test_amazon_autocomplete.py -v`
Expected: FAIL (`No module named 'amazon_autocomplete'` OU l'ancien module sans `parse_suggestions`).

- [ ] **Step 3 : Réécrire `01-scripts/amazon_autocomplete.py`** (remplace intégralement l'ancien contenu Scrapingdog)

```python
"""amazon_autocomplete.py — suggestions amazon.fr en DIRECT (gratuit, 0 crédit).
Endpoint public completion.amazon.fr. Sert à valider qu'une niche est réellement
cherchée, découvrir des satellites, et fournir un proxy de volume (nb de suggestions).
I/O réseau injectable pour les tests."""
from urllib.parse import urlencode

import util

_BASE = "https://completion.amazon.fr/api/2017/suggestions"
_MID_FR = "A13V1IB3VIYZZH"  # marketplace ID amazon.fr


def _build_url(prefix: str) -> str:
    q = urlencode({"mid": _MID_FR, "alias": "aps", "prefix": prefix, "limit": 11})
    return f"{_BASE}?{q}"


def parse_suggestions(payload: dict) -> list[str]:
    """Extrait la liste des chaînes de suggestion depuis le JSON amazon."""
    if not isinstance(payload, dict):
        return []
    items = payload.get("suggestions") or []
    out = []
    for s in items:
        v = (s.get("value") or "").strip() if isinstance(s, dict) else ""
        if v:
            out.append(v)
    return out


def _default_fetch_json(prefix: str) -> dict:
    import json
    r = util.http_get(_build_url(prefix), timeout=15)
    if getattr(r, "status_code", None) != 200:
        return {}
    try:
        return json.loads(r.text)
    except Exception:
        return {}


def fetch_suggestions(prefix: str, fetch_json=None) -> list[str]:
    """Retourne les suggestions amazon.fr pour `prefix`. `fetch_json(prefix)->dict`
    injectable ; par défaut appelle l'endpoint direct."""
    fetch_json = fetch_json or _default_fetch_json
    return parse_suggestions(fetch_json(prefix))
```

- [ ] **Step 4 : Lancer, vérifier le succès**

Run: `python -m pytest tests/test_amazon_autocomplete.py -v`
Expected: PASS (3 passed).

- [ ] **Step 5 : Vérifier la non-régression globale**

Run: `python -m pytest -v`
Expected: PASS (tous les tests des Tasks 1-5).

- [ ] **Step 6 : Commit**

```bash
git add 01-scripts/amazon_autocomplete.py tests/test_amazon_autocomplete.py
git commit -m "feat(autocomplete): endpoint direct gratuit (supprime Scrapingdog)"
```

---

### Task 6 : `demo_free.py` — glue + smoke manuel des canaux gratuits

> Petit CLI pour vérifier les deux canaux gratuits en réel (nécessite le réseau ;
> hors boucle TDD). Sert de preuve de bout-en-bout des Tasks 4-5.

**Files:**
- Create: `01-scripts/demo_free.py`
- Test: `tests/test_demo_free.py`

- [ ] **Step 1 : Écrire le test qui échoue** (on teste la fonction pure de formatage, pas le réseau)

Créer `tests/test_demo_free.py` :

```python
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
```

- [ ] **Step 2 : Lancer, vérifier l'échec**

Run: `python -m pytest tests/test_demo_free.py -v`
Expected: FAIL (`No module named 'demo_free'`).

- [ ] **Step 3 : Implémenter `01-scripts/demo_free.py`**

```python
"""demo_free.py — smoke test des canaux GRATUITS (autocomplete + BSR).
Usage :
  python 01-scripts/demo_free.py --suggest "tarot"
  python 01-scripts/demo_free.py --bsr 2266283340
"""
import argparse

from amazon_autocomplete import fetch_suggestions
from amazon_product import fetch_bsr
from models import BsrInfo


def format_report(prefix=None, suggestions=None, bsr: BsrInfo | None = None) -> str:
    lines = []
    if prefix is not None:
        lines.append(f"Suggestions pour « {prefix} » ({len(suggestions or [])}) :")
        for s in (suggestions or []):
            lines.append(f"  - {s}")
    if bsr is not None:
        lines.append(f"BSR {bsr.asin} : N°{bsr.rank_livres} en Livres")
        for sub in bsr.subcategories:
            lines.append(f"    N°{sub['rank']} en {sub['category']}")
    return "\n".join(lines)


def main():
    p = argparse.ArgumentParser(description="Smoke test canaux gratuits IA-Niches v2")
    p.add_argument("--suggest", help="mot-clé pour l'autocomplete")
    p.add_argument("--bsr", help="ASIN pour le classement des ventes")
    args = p.parse_args()

    if args.suggest:
        sugg = fetch_suggestions(args.suggest)
        print(format_report(prefix=args.suggest, suggestions=sugg))
    if args.bsr:
        info = fetch_bsr(args.bsr)
        if info:
            print(format_report(bsr=info))
        else:
            print(f"BSR {args.bsr} : introuvable (fiche bloquée ou sans classement)")
    if not args.suggest and not args.bsr:
        p.print_help()


if __name__ == "__main__":
    main()
```

- [ ] **Step 4 : Lancer, vérifier le succès**

Run: `python -m pytest tests/test_demo_free.py -v`
Expected: PASS (1 passed).

- [ ] **Step 5 : Smoke test réel (manuel, réseau requis)**

Run: `python 01-scripts/demo_free.py --suggest "tarot"`
Expected: liste de suggestions réelles (tarot divinatoire, tarot de marseille…).

Run: `python 01-scripts/demo_free.py --bsr 2266283340`
Expected: `BSR 2266283340 : N°XXXXX en Livres` + sous-catégories. (Si « introuvable » de façon répétée → l'IP est soft-bloquée : espacer les appels ; ce sera géré par le pacing du Plan 2.)

- [ ] **Step 6 : Commit**

```bash
git add 01-scripts/demo_free.py tests/test_demo_free.py
git commit -m "feat(demo): smoke CLI des canaux gratuits (autocomplete + BSR)"
```

---

## Self-review (fait)

- **Couverture spec** : ce plan couvre F3 (autocomplete direct — Task 5) et F4 (BSR gratuit — Task 4) de la spec, plus le socle de test transverse. Les autres composants (ideator, search, scoring, orchestrateur, nettoyage) sont explicitement dans le **Plan 2**.
- **Placeholders** : aucun — chaque step contient le code/commande réel.
- **Cohérence des types** : `BsrInfo` défini en Task 3, utilisé identique en Tasks 4 et 6. `fetch_html(asin)->str|None`, `fetch_json(prefix)->dict`, `getter(url,...)` — signatures cohérentes entre modules et tests.

## Suite

Après exécution + revue de ce Plan 1, on écrit le **Plan 2** : `niche_ideator.py` (LLM, modèle configurable), `search_providers.py` (DataForSEO derrière un seam), `filters.py`, `scoring.py`, maj `report_builder.py`, refonte `scout_master.py` (2 modes), et le nettoyage (suppression Scrapingdog résiduel, doublon, scripts debug ; maj `.env.example`/`00-config`).
