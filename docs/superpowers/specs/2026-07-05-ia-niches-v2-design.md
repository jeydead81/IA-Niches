# IA-Niches v2 — Spec de refonte (design validé)

> **Statut** : design validé avec Baptiste le 2026-07-05, ancré sur une recherche de
> faisabilité + un test live sur amazon.fr. Prochaine étape : plan d'implémentation.
> **Portée** : refonte du cœur du scout (Phase 1) autour d'un ideator LLM, avec une
> acquisition de données Amazon réaliste. Phases 3-5 (analyse/prod) inchangées.

---

## 1. Objectifs

Deux modes de recherche de niche, toujours **pour des livres** (evergreen, grand public) :

1. **« À partir de rien »** — l'utilisateur ne fournit rien ; l'outil récupère l'air du
   temps (Trends/Reddit/News) et en fait émerger de bonnes idées de niches livre.
2. **« À partir d'une graine »** — l'utilisateur donne un mot-clé (ex. « Ésotérisme »),
   l'outil trouve les concepts liés (tarot, anges, numérologie, cartomancie…) et valide
   lesquels sont des niches livre exploitables sur Amazon.fr.

Contraintes : coût maîtrisé, fiabilité, utilisable en perso maintenant **et** revendable
ensuite (architecture « bring-your-own-key », pas de UI dans cette phase).

---

## 2. Faits établis (recherche + test live du 2026-07-05)

Ces faits **remplacent** les hypothèses du CLAUDE.md v3 là où ils divergent.

| # | Fait | Statut | Impact design |
|---|------|--------|---------------|
| F1 | Le **modèle de coût du CLAUDE.md est faux ×5** : un appel amazon.fr coûte ~5 crédits Scrapingdog, pas 1 (déclencheur = param `country=fr`). | Vérifié | Plafond crédits + estimations à refaire. |
| F2 | Le **BSR n'est PAS sur la page de résultats** — uniquement sur la fiche produit `/dp/ASIN`. | Vérifié (aide KDP Amazon) | Récupérer le BSR = passer par les fiches produit. |
| F3 | **L'autocomplete amazon.fr est accessible en direct, gratuitement** (`completion.amazon.fr/api/2017/suggestions`, JSON). Testé : HTTP 200, suggestions réelles. | **Testé live** ✅ | On supprime Scrapingdog de l'autocomplete. |
| F4 | **Les fiches produit `/dp/ASIN` se chargent en direct depuis l'IP de Baptiste** (HTTP 200, ~1 Mo) et contiennent le **bloc BSR complet** (rang Livres + sous-catégories). Testé sur 3 ASIN. | **Testé live** ✅ | **Le BSR devient automatique et GRATUIT.** |
| F5 | La **page de résultats `/s` est verrouillée** depuis l'IP de Baptiste — HTTP 202/interstitiel — même en session chaude **et** avec imitation TLS Chrome (`curl_cffi`). | **Testé live** ❌ | L'étape *search* a besoin d'un provider payant. |
| F6 | Scrapingdog `/amazon/search` et `/amazon/product` renvoient **403 « Account Limit reached »**. Endpoints Amazon payants inutilisables tant que le compte n'est pas débloqué. | **Testé live** | Ne pas dépendre de Scrapingdog ; provider search = DataForSEO. |
| F7 | Scrapingdog **ne documente pas de champ BSR** dans ses endpoints structurés. | Vérifié (docs) | Non bloquant vu F4 (BSR gratuit ailleurs). |

**Conséquence structurante :** l'acquisition Amazon se répartit en 3 surfaces au profil
anti-bot très différent → **3 canaux distincts** :

- **Autocomplete** → direct, gratuit (F3).
- **Fiche produit / BSR** → direct depuis l'IP utilisateur, gratuit (F4).
- **Search (liste organique + sponsorisés + ASIN)** → provider payant, DataForSEO (F5).

---

## 3. Architecture cible

```
   Mode graine (--seed "ésotérisme")        Mode "à partir de rien"
            │                          Trends + Reddit + News (best-effort)
            └───────────────┬────────────────────────┘
                            ▼
   ① niche_ideator.py — LLM (Anthropic opus-4-8, "auteur KDP à succès")
       seed → concepts liés │ ou synthèse de l'air du temps
       → 20-30 CANDIDATS de niches LIVRE (sortie structurée Pydantic)
                            ▼
   ② amazon_autocomplete.py — DIRECT, GRATUIT
       "la niche est-elle vraiment cherchée ?" + satellites + proxy volume
       → filtre/priorise → ~8 candidats retenus
                            ▼
   ③ amazon_search.py — provider payant (DataForSEO), GATÉ (~8 appels/run)
       organique vs sponsorisé, concurrence, avis, badges, ASIN, catégorie Livres
                            ▼
   ④ tri sur proxy (avis + badge N°1) → 3-5 FINALISTES
                            ▼
   ⑤ amazon_product.py — DIRECT depuis l'IP, GRATUIT
       fiches produit des top livres des finalistes → BSR réel (§4.1)
                            ▼
   ⑥ scoring.py — 3 axes (avec vrai BSR) → report_builder.py → Excel
```

**Principe** : sources gratuites = *inspiration* du LLM ; Amazon = *juge de paix*. La
fiabilité vient de l'architecture (canaux séparés, best-effort + fallback), pas de la
perfection d'un scraper unique.

---

## 4. Composants

### Nouveaux

**`niche_ideator.py`** — le cerveau.
- Dépend de `anthropic` (SDK officiel). Modèle **configurable** (variable `.env`/config),
  défaut `claude-opus-4-8` — **A/B tôt** avec `claude-sonnet-5` (voire `claude-fable-5`) sur
  2-3 graines réelles : c'est la qualité des niches sorties qui tranche, pas le palier. Coût
  non déterminant (1 appel/run). `thinking={"type":"adaptive"}`, sortie structurée via
  `client.messages.parse()` + schéma Pydantic (JSON garanti, pas de parsing).
- Interface : `generate_niches(seed: str | None, signals: dict, n: int = 25) -> list[NicheCandidate]`.
- `NicheCandidate` = `{niche, satellite_keywords[], rationale, categorie, pharma_flag, risk_flags[]}`.
- System prompt « directeur éditorial / auteur KDP à succès » : expansion latérale
  (ésotérisme→tarot/anges), evergreen only, applique les exclusions §4.4, conscience de
  l'avantage pharmacien §4.3, ne propose que du **livre-compatible**.
- Coût : ~1 appel/run, quelques centimes.

**`amazon_product.py`** — BSR gratuit.
- `fetch_bsr(asin: str) -> BsrInfo | None` : GET direct `https://www.amazon.fr/dp/{asin}`
  (UA navigateur), parse « Classement des meilleures ventes d'Amazon : N°X en Livres » +
  sous-catégories + date de publication si dispo.
- Pacing 3-5 req/min, retry max 1 (5 s), et **fallback** : si l'IP se fait soft-bloquer,
  marquer le BSR « à valider manuellement (Phase 2) » plutôt que planter (transparence §10).

### Réécrits

**`amazon_autocomplete.py`** — direct, gratuit (supprime tout Scrapingdog).
- `fetch_suggestions(prefix: str) -> list[str]` via `completion.amazon.fr/api/2017/suggestions`
  (`mid=A13V1IB3VIYZZH`, `alias=aps`, `prefix`, `limit=11`). Pacing + retry.
- Sert : validation « est-ce cherché », découverte de satellites, proxy de volume
  (nb de suggestions = signal d'intention).

**`amazon_search.py`** — provider payant derrière un seam.
- Interface `SearchProvider.search(query) -> SearchResult`.
  `SearchResult = {organic[], sponsored[], total_results}`, item =
  `{title, asin, price, rating, reviews_count, sponsored, badges[]}`.
- `DataForSEOProvider` (défaut) ; `ScrapingdogProvider` optionnel (si compte débloqué).
  Provider choisi via `.env` / config.
- **Gaté** aux ~8 meilleurs candidats post-autocomplete (pas toutes les niches).

### Conservés / retouchés

- `trends_fr.py`, `reddit_fr.py`, `news_fr.py` — inchangés dans le principe, deviennent des
  fournisseurs de *signaux best-effort* passés à l'ideator (plus la source primaire des mots-clés).
- `report_builder.py` — ajout des colonnes **BSR réel** (rang Livres, sous-catégorie) désormais
  disponibles ; l'onglet « Sponsorisés écartés » reste (alimenté par le search).
- `credits_tracker.py` → **`cost_tracker.py`** : ne compte plus que les appels payants (search) ;
  autocomplete + BSR = 0. Modèle de coût par provider corrigé. Garde-fous conservés (§10).
- `scout_master.py` — refonte de l'orchestration + 2 modes (`--seed` / from-scratch).

### Supprimés

- Code Scrapingdog d'autocomplete (obsolète, remplacé par F3).
- Ancien `amazon_search.py` cassé (endpoint/params faux — remplacé).
- `01-scripts/amazon_autocomplete 2.py` (doublon obsolète, déjà gitignored).
- Scripts de debug/test Scrapingdog (`test_scrapingdog.py`, `debug_autocomplete*`) →
  supprimés ou remplacés par des tests des nouveaux modules.

---

## 5. Modèle de coût révisé (par run)

| Poste | Appels | Coût |
|-------|--------|------|
| Ideator LLM | 1 | ~quelques centimes (opus-4-8) |
| Autocomplete | ~25-30 | **0** (direct) |
| Search (DataForSEO) | ~8 (gaté) | ~0,02 $ (ou ~40 cr si Scrapingdog) |
| BSR fiches produit | ~15-25 | **0** (direct, IP utilisateur) |

→ **~0,02-0,05 $/run** + LLM. On divise par ~3-4 la cible « ~175 cr » de la recherche,
et surtout le **BSR (cœur des critères §4.1) devient automatique et gratuit**. Bien dans le
budget « quelques centaines €/mois max ».

---

## 6. Configuration & secrets (`.env`)

- `ANTHROPIC_API_KEY` — **nouveau**, obligatoire (ideator).
- `DATAFORSEO_LOGIN` / `DATAFORSEO_PASSWORD` — **nouveau**, obligatoire (search).
- `SCRAPINGDOG_API_KEY` — **optionnel** (provider search alternatif seulement).
- `REDDIT_*` — inchangé (optionnel, mode dégradé RSS sinon).
- Mise à jour de `.env.example` en conséquence.

`00-config/` : le fichier crédits devient un fichier **coût/provider** (provider search actif,
plafond d'appels payants/run, pacing).

---

## 7. Scoring (avec vrai BSR)

- **AXE 1 Demande** : volume autocomplete + **BSR réel** des finalistes (critères §4.1 enfin
  appliqués : ≥1 top BSR < 10 000, moyenne top-5 < 50 000, présence d'un > 50-100k = « place à
  prendre ») + proxy avis/badge sur les non-finalistes + boost Trends/Reddit/News.
- **AXE 2 Pénétration** : nb résultats + concurrents organiques ciblés (search, **hors
  sponsorisés**) + distribution BSR + ratio sponsorisés.
- **AXE 3 Compatibilité livre** : garantie en amont par l'ideator + garde-fou heuristique.
- Bonus pharmacien (+1) et malus TOS (-2) conservés.

---

## 8. Ce qui reste à valider en implémentation

Repris des « open questions » de la recherche, à confirmer au 1er appel réel :
1. Format exact de la réponse DataForSEO (champs organique/sponsorisé/ASIN pour amazon.fr) +
   coût réel/appel (chiffrage recherche non re-vérifié en contradictoire).
2. Robustesse du parsing BSR sur la variété des fiches livres (broché/poche/Kindle : **fixer un
   format cible** pour des BSR comparables entre niches).
3. Seuil de pacing produit avant soft-block de l'IP (tester la fréquence tolérée).

---

## 9. Risques & mitigations

- **IP soft-bloquée sur les fiches produit à volume** → pacing strict + fallback « BSR manuel »
  + option proxy résidentiel plus tard. Non bloquant (F4 validé à faible volume).
- **DataForSEO : chiffrage non re-vérifié** (l'agent de vérif a planté) → confirmer au 1er appel,
  seam provider pour pivoter si besoin (Scrapingdog/Rainforest).
- **ToS Amazon / revente** → vendre l'**analyse/les rapports**, jamais des datasets Amazon bruts.
- **Endpoint autocomplete gratuit pourrait durcir** (maj anti-crawler 2026) → garder un fallback.

---

## 10. Garde-fous non-négociables (conservés du CLAUDE.md)

- Plafond d'appels **payants** par run (le nouveau `cost_tracker`), retry max 1 / délai 5 s.
- **Transparence absolue** : sources OK/KO, sponsorisés écartés, BSR non résolus, coût consommé
  affichés dans le rapport (onglet Métadonnées) et le résumé chat.
- Confirmation avant tout run payant ; sortie utile (rapport partiel) en cas d'échec.

---

## 11. Hors périmètre (cette phase)

- UI (décision : pas maintenant).
- Multi-marketplace (on reste amazon.fr).
- Phases 3-5 (analyse éditoriale, pré/post-production) — inchangées.
- Mise à jour du CLAUDE.md v3 pour refléter cette v2 (cost model, BSR auto, Scrapingdog retiré) :
  **recommandée en fin d'implémentation**, à faire dans un commit dédié.
