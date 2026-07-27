# Briques SaaS — Travaux asynchrones & compteur d'usage — Plan d'implémentation

> **For agentic workers:** REQUIRED SUB-SKILL: superpowers:subagent-driven-development.

**Goal:** Rendre le produit utilisable par quelqu'un d'autre que Baptiste : un run ne doit plus mourir quand l'onglet se ferme, et chaque euro dépensé doit être imputé à un utilisateur.

---

## Les faits mesurés qui motivent ce chunk

- **Un run fiction prend 10 à 15 min** (869 s mesuré sur 3 trios). Le serveur actuel exécute le run dans un thread lié à la connexion SSE : **fermer l'onglet perd le run — et l'argent déjà dépensé**.
- **La latence DataForSEO varie du simple au triple** (SERP mesurées à 85 s, 222 s, 251 s). Aucune interface synchrone ne peut promettre un délai.
- Le coût est déjà mesuré de bout en bout (`CostTracker`), mais **il n'est imputé à personne** : rien ne relie une dépense à un utilisateur.

**Décision — `user_id` dès maintenant, authentification plus tard.** Toutes les tables portent un `user_id` valant `"local"` par défaut. Brancher l'authentification devient un remplissage de colonne, pas une restructuration. Construire l'auth maintenant serait prématuré ; ne pas prévoir la colonne obligerait à tout migrer.

**Décision — le compteur est un garde-fou, pas une grille tarifaire.** L'analyse de coût est sans appel : à 30 analyses/mois la marge est de 88 %, et Stripe coûte plus cher que la donnée. Le seul risque réel est la queue de distribution (un utilisateur à 500 analyses). Le compteur **plafonne**, il ne facture pas à l'acte : un compteur affiché ferait hésiter avant chaque clic, exactement le mauvais réflexe pour un outil d'exploration.

**Tech Stack :** Python 3.13, pytest, FastAPI, SQLite (même pattern que `cache.py` : connexion par appel + WAL, sûr en concurrence).

---

## Task S1 : priorité DataForSEO configurable

**Files:** Modify `01-scripts/search_providers.py` · Test `tests/test_search_providers.py`

- [ ] **Step 1 : Test (échoue)** :
```python
def test_priorite_configurable_par_environnement(monkeypatch):
    """La file « standard » coûte moitié prix (0,0015 $ vs 0,003 $) mais peut mettre ~45 min
    quand priority tourne autour de 1-4 min. C'est un ARBITRAGE, donc un réglage — le défaut
    reste priority pour ne pas dégrader l'usage interactif à l'insu de l'appelant."""
    monkeypatch.setenv("DATAFORSEO_PRIORITY", "1")
    assert DataForSEOProvider(login="l", password="p").priority == 1
    monkeypatch.delenv("DATAFORSEO_PRIORITY")
    assert DataForSEOProvider(login="l", password="p").priority == 2
```

- [ ] **Step 2-3** : lire `DATAFORSEO_PRIORITY` (défaut 2), valider la valeur (1 ou 2, sinon défaut + avertissement).
- [ ] **Step 4-5 : Commit**
```bash
git commit -am "feat(saas): priorité DataForSEO configurable (standard = -50% sur la donnée)"
```

---

## Task S2 : le magasin de travaux

**Files:** Create `01-scripts/jobs.py` · Test `tests/test_jobs.py`

- [ ] **Step 1 : Tests (échouent)** :
```python
def test_un_job_survit_a_la_deconnexion_du_client(tmp_path):
    """LE point du module : aujourd'hui le run vit dans le thread de la connexion SSE.
    Fermer l'onglet tue un run de 15 min ET perd l'argent déjà dépensé."""
    store = JobStore(tmp_path / "j.db")
    jid = store.create("fiction", {"sous_genre": "cosy_mystery"})
    store.start(jid)
    store.append_progress(jid, "SERP 1/3…")
    # le "client" disparaît ici — le job continue de vivre dans le magasin
    store.finish(jid, resultat=[{"niche": "x"}], cout={"usd": 0.15})
    j = store.get(jid)
    assert j.statut == "termine" and j.resultat and j.cout["usd"] == 0.15
    assert "SERP 1/3…" in j.progression


def test_un_job_en_echec_conserve_son_message_et_son_cout():
    """L'argent dépensé avant l'échec doit rester imputé — sinon on facture dans le vide."""
    ...
    store.fail(jid, "TimeoutError: file DataForSEO saturée", cout={"usd": 0.09})
    j = store.get(jid)
    assert j.statut == "echec" and "Timeout" in j.erreur and j.cout["usd"] == 0.09


def test_liste_par_utilisateur_et_par_recence():
    """user_id dès maintenant (défaut 'local') : brancher l'auth deviendra un remplissage
    de colonne, pas une migration."""
    ...
    assert [j.id for j in store.list_jobs(user_id="local", limit=2)] == [j3, j2]


def test_progression_bornee():
    """Un run de 15 min log beaucoup : la progression ne doit pas gonfler la base sans fin."""
    ...
```

- [ ] **Step 2-3 : Implémenter `01-scripts/jobs.py`** : `Job` (pydantic : `id`, `user_id`, `type`, `params`, `statut` ∈ `en_attente|en_cours|termine|echec`, `progression: list[str]`, `resultat`, `cout`, `erreur`, `cree_le`, `fini_le`) et `JobStore(path)` avec `create/start/append_progress/finish/fail/get/list_jobs`. SQLite, connexion par appel, WAL. Progression plafonnée (garder les N derniers messages).

- [ ] **Step 4-5 : Commit**
```bash
git add 01-scripts/jobs.py tests/test_jobs.py
git commit -m "feat(saas): magasin de travaux — un run survit à la fermeture de l'onglet"
```

---

## Task S3 : compteur d'usage & plafond

**Files:** Create `01-scripts/usage.py` · Test `tests/test_usage.py`

- [ ] **Step 1 : Tests (échouent)** :
```python
def test_chaque_run_est_impute_a_un_utilisateur(tmp_path):
    m = UsageMeter(tmp_path / "u.db")
    m.enregistrer("local", "fiction", cout_usd=0.153, n_analyses=3)
    r = m.resume("local")
    assert r.n_analyses == 3 and abs(r.cout_usd - 0.153) < 1e-9


def test_le_plafond_protege_de_la_queue_de_distribution(tmp_path):
    """La marge est de 88 % à 30 analyses/mois : le coût unitaire n'est PAS le risque.
    Le risque est l'utilisateur à 500 analyses. Le plafond existe pour lui, pas pour
    facturer à l'acte."""
    m = UsageMeter(tmp_path / "u.db", plafond_analyses=30)
    m.enregistrer("local", "fiction", cout_usd=1.0, n_analyses=30)
    assert m.autorise("local", n_analyses=1) is False
    assert m.autorise("autre", n_analyses=1) is True     # plafond PAR utilisateur


def test_le_plafond_est_mensuel_et_glissant(tmp_path):
    """Un plafond cumulatif à vie bloquerait un client fidèle au bout de quelques mois."""
    ...


def test_aucun_plafond_configure_nautorise_pas_tout_a_linfini():
    """Défaut prudent : pas de plafond -> illimité, mais l'usage reste journalisé."""
    ...
```

- [ ] **Step 2-3 : Implémenter `01-scripts/usage.py`** : `UsageMeter(path, plafond_analyses=None)` avec `enregistrer(user_id, type, cout_usd, n_analyses)`, `resume(user_id, depuis=None)`, `autorise(user_id, n_analyses)`. Fenêtre **mensuelle glissante**. SQLite même pattern.

- [ ] **Step 4-5 : Commit**
```bash
git add 01-scripts/usage.py tests/test_usage.py
git commit -m "feat(saas): compteur d'usage par utilisateur + plafond mensuel glissant"
```

---

## Task S4 : endpoints asynchrones

**Files:** Modify `web/server.py` · Test `tests/test_server_jobs.py`

- [ ] **Step 1 : Tests (échouent)** :
```python
def test_post_job_rend_un_id_immediatement():
    """Le client ne doit PAS attendre 15 min sur une requête HTTP."""
    r = client.post("/api/jobs", json={"type": "fiction", "sous_genre": "cosy_mystery"})
    assert r.status_code == 202 and r.json()["id"]


def test_get_job_rend_la_progression_puis_le_resultat():
    ...


def test_job_refuse_quand_le_plafond_est_atteint():
    """429 explicite avec le motif, pas un échec silencieux."""
    assert r.status_code == 429 and "plafond" in r.json()["detail"].lower()


def test_type_de_job_inconnu_rend_400():
    ...
```

- [ ] **Step 2-3 : Implémenter** : `POST /api/jobs` (202 + id, run lancé dans un thread **détaché du client**), `GET /api/jobs/{id}`, `GET /api/jobs` (liste), `GET /api/jobs/{id}/stream` (SSE branché sur la progression du magasin — reconnectable). Le plafond est vérifié **avant** de dépenser. Les endpoints SSE existants restent en place (usage interactif).

- [ ] **Step 4-5 : Commit**
```bash
git add web/server.py tests/test_server_jobs.py
git commit -m "feat(saas): endpoints de travaux asynchrones — le run survit au client"
```

---

## Self-Review
- Un run de 15 min ne meurt plus avec l'onglet, et l'argent déjà dépensé reste imputé même en cas d'échec. ✓
- `user_id` partout dès maintenant : l'authentification deviendra un remplissage, pas une migration. ✓
- Le plafond protège de la queue de distribution sans transformer le produit en compteur à l'acte. ✓
- La priorité DataForSEO est un **réglage** assumé (−50 % sur la donnée contre une latence pouvant aller à ~45 min), pas un défaut imposé. ✓
- Aucun réseau en test : magasin, compteur et endpoints sont testés sur SQLite temporaire et dépendances injectées. ✓

## Suite
Revue UX (lisibilité pour un utilisateur non technique : expliquer les menus et les chiffres) puis tutoriel PDF.
