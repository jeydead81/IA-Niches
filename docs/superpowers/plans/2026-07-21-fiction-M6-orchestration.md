# Fiction M6 — Orchestration & UI — Plan d'implémentation

> **For agentic workers:** REQUIRED SUB-SKILL: superpowers:subagent-driven-development.

**Goal:** Rendre la fiction **atteignable par un utilisateur**. Aujourd'hui `grep fiction web/` → 0 occurrence : les 5 modules livrés ne servent à personne.

---

## Le problème de performance, chiffré

`fetch_fiction_shelf` fait **SERP + batch ASIN par niche**. Or la file ASIN de DataForSEO met ~250 s, quel que soit le nombre d'ASIN dans le lot. Enchaîner les niches multiplie donc l'attente :

| Niches | Aujourd'hui (batch par niche) | Avec **un seul** batch global |
|---|---|---|
| 3 | ~750 s | **~265 s** |
| 10 | ~2 500 s (42 min) | **~280 s** |

La file est payée **une fois** au lieu de N. C'est exactement ce que `run_scout` fait déjà côté non-fiction (3 phases), et ce que la mémoire projet signale depuis M2 comme « contrainte de perf pour M6 ».

**Bonus économique :** la déduplication des ASIN devient **inter-niches**. Deux trios du même sous-genre partagent souvent des livres ; aujourd'hui ils sont payés deux fois.

**Tech Stack :** Python 3.13, pytest, FastAPI + SSE (existant), pydantic v2.

---

## Task M6-1 : scinder l'acquisition en deux moitiés (contrat préservé)

**Files:** Modify `01-scripts/fiction_serp_provider.py` · Test `tests/test_fiction_serp_provider.py`

`fetch_fiction_shelf` reste **inchangée pour ses appelants** (tests M2 verts, `build_validation_set` intact) : elle devient la composition de ses deux moitiés.

- [ ] **Step 1 : Tests (échouent)** :
```python
def test_serp_half_rend_les_asins_sans_enrichir():
    """La moitié SERP est rapide et sans file d'attente : c'est elle qu'on veut appeler
    N fois avant de payer UNE seule fois la file ASIN."""
    prov = _Prov()
    sp, asins = fetch_shelf_asins(_niche(), provider=prov, n_top=12, cost=CostTracker())
    assert sp == "rh=n:205566725031"
    assert asins == ["A1", "A2"]
    assert prov.seen.get("asins") is None          # aucun enrichissement déclenché


def test_enrich_half_batche_et_cache():
    prov = _Prov()
    cost = CostTracker()
    out = enrich_asins(["A1", "A2"], provider=prov, cache=None, cost=cost)
    assert set(out) == {"A1", "A2"} and prov.seen["asins"] == ["A1", "A2"]
    assert cost.breakdown()["dataforseo_calls"] == 2


def test_fetch_fiction_shelf_reste_la_composition_des_deux():
    """Contrat M2 inchangé — les appelants existants ne bougent pas."""
    shelf = fetch_fiction_shelf(_niche(), provider=_Prov(), n_top=12, cost=CostTracker())
    assert [b.asin for b in shelf.books] == ["A1", "A2"]
    assert shelf.books[0].serp_position == 1 and shelf.asins_demandes == 2
```

- [ ] **Step 2 : Lancer** → FAIL. **Step 3 : Implémenter** :
  - `fetch_shelf_asins(niche, provider, n_top=12, depth=30, cost=None, version="fr_v1") -> tuple[str, list[str]]` — SERP contrainte, dédup, coût compté, **aucun** appel ASIN.
  - `enrich_asins(asins, provider, cache=None, cost=None, progress=None) -> dict[str, EnrichedBook]` — cache, batch, coût, échecs remontés (la moitié « lente »).
  - `fetch_fiction_shelf(...)` = composition des deux + assemblage du `FictionShelf` (positions SERP réécrites, `n_echecs`). **Ses tests M2 existants doivent rester verts sans modification.**

- [ ] **Step 4 : Lancer** toute la suite → verte. **Step 5 : Commit**
```bash
git commit -am "refactor(fiction): scinde l'acquisition en moitié SERP et moitié enrichissement"
```

---

## Task M6-2 : `run_fiction_scout` — l'orchestrateur en 5 phases

**Files:** Create `01-scripts/fiction_master.py` · Test `tests/test_fiction_master.py`

```
A. ideator            -> N trios                       (1 appel LLM)
B. N x SERP           -> ASIN par niche                (rapide, pas de file)
C. UN batch ASIN      -> tous les livres, dédupliqués  (la file, payée UNE fois)
D. classification     -> par sous-genre, batché         (LLM)
E. sonde autocomplete -> par niche                      (gratuit)
F. scoring            -> rapports triés
```

- [ ] **Step 1 : Tests (échouent)** — tout injecté, **aucun réseau** :
```python
def test_un_seul_batch_asin_pour_toutes_les_niches():
    """LE point du module : la file ASIN (~250 s) est payée UNE fois, pas N fois."""
    appels = {"serp": 0, "enrich": 0}

    def faux_serp(niche, **kw):
        appels["serp"] += 1
        return "rh=n:1", [f"A{appels['serp']}", "PARTAGE"]

    def faux_enrich(asins, **kw):
        appels["enrich"] += 1
        return {a: EnrichedBook(asin=a, title="T", blurb="b", bsr=3000,
                                bsr_rayon="Boutique Kindle") for a in asins}

    rapports = run_fiction_scout("cosy_mystery", n_niches=3, ideate=_faux_ideate,
                                 serp_fn=faux_serp, enrich_fn=faux_enrich,
                                 classify=_faux_classify, probe=_faux_probe)
    assert appels["serp"] == 3
    assert appels["enrich"] == 1               # <- UN SEUL batch, quel que soit N


def test_asins_dedupliques_entre_niches():
    """Deux trios du même sous-genre partagent des livres : les payer deux fois est du gaspillage."""
    vus = {}

    def faux_enrich(asins, **kw):
        vus["asins"] = list(asins)
        return {a: EnrichedBook(asin=a, title="T", blurb="b") for a in asins}

    run_fiction_scout("cosy_mystery", n_niches=3, ideate=_faux_ideate, serp_fn=_faux_serp,
                      enrich_fn=faux_enrich, classify=_faux_classify, probe=_faux_probe)
    assert len(vus["asins"]) == len(set(vus["asins"]))     # aucun doublon payé


def test_rapports_tries_par_interet():
    rapports = run_fiction_scout(...)
    scores = [(r.depth_score, -r.saturation_trio) for r in rapports]
    assert scores == sorted(scores, reverse=True)


def test_une_niche_en_echec_ne_coule_pas_le_run():
    """Un rayon qui lève ne doit pas faire perdre les rayons DÉJÀ PAYÉS (§10.11)."""
    def serp_capricieux(niche, **kw):
        if "boum" in niche.query:
            raise RuntimeError("SERP HS")
        return "rh=n:1", ["A1"]

    rapports = run_fiction_scout(..., serp_fn=serp_capricieux, progress=msgs.append)
    assert len(rapports) == 2                              # les 2 autres sont conservés
    assert any("échec" in m.lower() for m in msgs)


def test_progress_et_cout_remontent():
    cost = CostTracker()
    run_fiction_scout(..., cost=cost, progress=msgs.append)
    assert msgs and cost is not None
```

- [ ] **Step 2 : Lancer** → FAIL. **Step 3 : Implémenter `01-scripts/fiction_master.py`** — mêmes conventions que `scout_master.run_scout` (dépendances injectables `ideate`/`serp_fn`/`enrich_fn`/`classify`/`probe`, callback `progress(str)`, `CostTracker` optionnel, CLI `main()`), avec :
  - phase C sur l'**union dédupliquée** des ASIN de toutes les niches ;
  - reconstruction des `FictionShelf` par niche depuis la table globale (positions SERP propres à chaque niche, `n_echecs` = ASIN demandés et non enrichis) ;
  - une niche en échec est **isolée** et signalée, les autres sont conservées ;
  - tri des rapports par intérêt (profondeur décroissante, saturation croissante) ;
  - `progress()` à chaque phase, avec le nombre d'ASIN uniques économisés par la dédup.

- [ ] **Step 4 : Lancer** → verte. **Step 5 : Commit**
```bash
git add 01-scripts/fiction_master.py tests/test_fiction_master.py
git commit -m "feat(fiction): run_fiction_scout — un seul batch ASIN global (42 min -> 5 min sur 10 niches)"
```

---

## Task M6-3 : l'UI — la fiction devient atteignable

**Files:** Modify `web/server.py`, `web/index.html` · Test `tests/test_server_fiction.py`

- [ ] **Step 1 : Tests (échouent)** :
```python
def test_endpoint_fiction_stream_sse():
    """Même contrat SSE que /api/scout : progress -> result -> cost -> done."""
    ...


def test_endpoint_fiction_refuse_un_sous_genre_inconnu():
    """400 explicite plutôt qu'une KeyError 500 venue de la taxonomie."""
    r = client.get("/api/fiction?sous_genre=inexistant")
    assert r.status_code == 400
```

- [ ] **Step 2 : Lancer** → FAIL. **Step 3 : Implémenter** :
  - `GET /api/fiction` : mêmes événements SSE que `/api/scout` (`progress` / `result` / `cost` / `error` / `done`), paramètres `sous_genre`, `n_niches`, `rayon` ;
  - validation du sous-genre **avant** de lancer quoi que ce soit (400 propre, pas une 500) ;
  - UI : un onglet ou sélecteur **Non-fiction / Fiction** réutilisant **le design system existant** de `web/index.html` (bleu/ambre, Fira) — ne pas inventer une seconde charte ;
  - carte de résultat fiction affichant : trio, `demand_matrix` en badge, `depth`/`openness`, **`saturation_trio` mise en avant** (c'est le différenciateur), `series_share`, `price_band`, et le verdict ;
  - afficher explicitement les **avertissements** portés par le verdict (rayon incomplet, sous-genre fantôme, livres non classés) — un utilisateur qui ne voit pas ces réserves surinterprète le score.

- [ ] **Step 4 : Lancer** → verte. **Step 5 : Commit**
```bash
git add web/ tests/test_server_fiction.py
git commit -m "feat(fiction): endpoint SSE /api/fiction + onglet UI — la fiction devient atteignable"
```

---

## Self-Review
- La file ASIN est payée **une fois par run**, pas une fois par niche — le seul vrai levier de latence. ✓
- Dédup **inter-niches** : les livres partagés entre trios ne sont plus payés deux fois. ✓
- Contrat de `fetch_fiction_shelf` préservé : les tests M2 et `build_validation_set` ne bougent pas. ✓
- Une niche en échec n'emporte pas les rayons déjà payés (§10.11). ✓
- Les réserves (rayon incomplet, sous-genre fantôme) sont **visibles dans l'UI**, pas seulement dans les données. ✓
- Aucun réseau en test : ideator, SERP, enrichissement, classifieur et sonde sont tous injectés. ✓

## Suite
Briques SaaS : file DataForSEO « standard » + livraison asynchrone (−25 % de coût, latence déjà présente), journal d'usage brancheable sur Stripe.
