# CLAUDE.md — IA-Niches (v2, branche `v2-refonte-ideator`)

> Fichier de contexte permanent, lu en priorité à chaque ouverture du dépôt.
> Il s'adresse à l'agent et au développeur, pas à l'utilisateur final.
>
> **La source de vérité est LE CODE** (`01-scripts/` et `web/`), jamais la documentation.
> Quand ce fichier et le code divergent, le code a raison et ce fichier doit être corrigé.
> Les docstrings du dépôt portent les pièges métier mesurés en live : ce sont elles la vraie doc.

---

## 1. CONTEXTE PROJET

**Baptiste** : pharmacien français, auteur sur Amazon KDP fr. Il rédige des livres (pas du
low-content), teste vite plusieurs niches, cible exclusivement Amazon.fr.

**Ce que le produit résout** : trouver des niches de livres réellement demandées et réellement
pénétrables sur Amazon.fr, en remplaçant une recherche manuelle de plusieurs heures par un run
automatisé de quelques minutes.

**Le produit est destiné à être VENDU**, pas seulement à l'usage personnel de Baptiste. Dépôt
GitHub privé. Modèle visé : abonnement unique autour de **19 EUR/mois** pour ~30 analyses en
usage loyal, marge **88-94 %**, seuil de rentabilité **1-2 clients**. **Ces trois chiffres sont
des ESTIMATIONS de cadrage établies en session de travail, pas des mesures du dépôt.** Le seul
chiffre sourçable dans le code est « à 30 analyses/mois la marge est de 88 % »
(`usage.py:4-6`) ; ni « 19 EUR », ni « 94 % », ni le seuil de rentabilité n'apparaissent dans
`01-scripts/` ou `web/`. Ordre de grandeur CALCULÉ (pas mesuré) qui rend ces 88 % cohérents :
30 scouts non-fiction au coût de PRODUCTION (0,084 $, §3) = 2,52 $, soit ~2,32 EUR au taux fixe
`TAUX_USD_EUR=0.92` de `web/index.html` — 12 % de 19 EUR. Corollaire à ne pas inverser : dès
**7 analyses par mois au coût de production**, le coût technique dépasse les frais d'encaissement
d'un abonnement. (0,084 $ × 0,92 = 0,077 EUR par analyse ; les frais d'un encaissement à 19 EUR
tournent autour de 0,50 EUR selon le prestataire — **chiffre hors dépôt, aucun prestataire n'est
intégré**, donc à revérifier au moment de brancher le paiement. Le seuil serait de ~19 analyses
au coût LOCAL, mais §3 interdit de citer ce coût-là comme coût de production.) Une formule
antérieure de ce fichier annonçait l'inverse — que les frais de transaction dominaient — sur la
foi du chiffre local : elle est fausse et ne doit pas revenir.
Conséquence directe sur les décisions techniques : le cache de scraping
est **mutualisé entre tous les utilisateurs** (c'est l'économie principale à l'échelle), alors
que historique, usage et jobs sont **par utilisateur**.

**Posture attendue** : factuelle et tranchée. Aucun compliment gratuit. Chiffrer ce qui peut
l'être. Signaler explicitement les zones d'incertitude et les mesures manquantes.

---

## 2. ARCHITECTURE RÉELLE

Application web **locale**, mono-page : FastAPI (`web/server.py`, 427 lignes, 13 endpoints —
comptage `wc -l`, vérifié le 2026-07-29) + un unique `web/index.html` de 57 319 octets (CSS et
JS inline, zéro dépendance externe, zéro build). Quatre bases SQLite locales dans `99-logs/` :
`df-cache.db`, `jobs.db`, `usage.db`, `history.db`.

Deux moteurs indépendants coexistent : le **scout non-fiction** et le **scout fiction**.

### 2.1 Scout NON-FICTION — `run_scout()` (`01-scripts/scout_master.py`)

Coût : **0,030 $ en local (MESURÉ**, run réel du 2026-07-21, `tutoriel_pdf.py:60`) ;
**0,084 $ avec BSR serveur (CALCULÉ**, jamais mesuré, `tutoriel_pdf.py:61`). La distinction est
portée par la source elle-même (`tutoriel_pdf.py:56-58`) : présenter le second comme mesuré
fausserait la tarification construite dessus. Voir §3.

| Phase | Ce qui se passe | Coût |
|---|---|---|
| 0 | `load_dotenv()` puis ouverture du cache SQLite `99-logs/df-cache.db` (si `use_cache=True`, défaut) | 0 |
| 1 — Ideator | `ideate(seed, signals, n=n_ideas)` → **un seul** appel Anthropic en tool-use **forcé** (`tool_choice` figé sur `proposer_niches`, aucun parsing de texte libre). Sortie : `NicheCandidate[]` avec `niche`, `requete_amazon` COURTE (2-4 mots), `satellite_keywords`, `rationale`, `categorie`, `risques` | LLM |
| 2 — Validation demande | `validate(candidates, pause=0.4, max_queries=3)` — par défaut `niche_validator.validate_niches` (`scout_master.py:17,45,64`) — interroge `completion.amazon.fr` sur la requête courte puis les satellites. `demand_score` = nb de suggestions distinctes ; `validated` = au moins une requête auto-complétée. Tri par `(validated, demand_score)` décroissant (`niche_validator.py:63`) | **gratuit** |
| — **Gate de coût** | `shortlist = validated[:n_search]` (défaut 6 ; l'endpoint SSE envoie 4). **Une niche non validée ne coûte jamais un appel payant.** Shortlist vide → retour `[]` immédiat | — |
| A — Concurrence | Par niche : cache `search` (clé keyword+location+language, TTL 10 j), sinon `provider.search()` sur `merchant/amazon/products` en task_post + poll (8 s d'intervalle, 40 polls max, ~320 s), `search_param=i=stripbooks` si `books_only`. **Un échec est attrapé** (`scout_master.py:89-91`) : avertissement en progress, `sr = None`, le run continue — et la niche ressort marquée `concurrence_mesuree=False` (voir §4.1). On retient les 3 premiers ASIN **organiques** (`n_bsr_per_niche=3`) | DataForSEO |
| B — BSR batché | `resolve_bsrs()` sur l'**union** des ASIN de toutes les niches : dédup, cache par ASIN (TTL 3 j), puis selon `BSR_SOURCE` (voir §3) | gratuit ou payant |
| C — Scoring | `scoring.py`, fonctions pures : `bsr_stats`, `count_targeted`, `score_niche` (3 axes pondérés 0,4 / 0,4 / 0,2). Tri par `global_score` décroissant. Si `search is None`, aucun bonus ni malus de concurrence n'est appliqué et le verdict devient « Concurrence non mesurée — à relancer » | 0 |
| D — Verdict IA | `n_verdict=0` **par défaut** : aucun verdict n'est généré, ni par la CLI ni par les deux endpoints. Gate de coût assumé (3 verdicts pesaient 78 % du coût d'un run). Le verdict se demande à la pièce via `POST /api/verdict` | — |

Le paramètre `signals` (mode « à partir de rien » alimenté par des tendances) traverse `run_scout`
et `niche_ideator` jusqu'au prompt, mais **aucun appelant ne le remplit** : il vaut toujours `None`.

### 2.2 Scout FICTION — `run_fiction_scout()` (`01-scripts/fiction_master.py`)

Coût : **0,153 $ pour 3 trios (MESURÉ)**, **0,409 $ pour 8 trios (EXTRAPOLÉ)** —
`tutoriel_pdf.py:62-63`. Six phases (le docstring du module annonce bien « 6 étapes »,
`fiction_master.py:1`).

- **A — Ideator** (payant, **un seul** appel LLM pour TOUS les trios du sous-genre) :
  `generate_trios` injecte dans le prompt la liste exacte des tropes et décors autorisés, puis
  **vérifie côté code** — tout trio hors taxonomie est écarté (`fiction_ideator.py:112-115`).
  `n` est un plafond réel (`out[:n]`), pas une suggestion.
- **B — N × SERP**, une par niche (payant, rapide, pas de file d'attente) : `fetch_shelf_asins`
  contraint la SERP au browse node du sous-genre (`rh=n:...`) quand il existe, sinon au filtre de
  rayon lu dans la taxonomie (`i=digital-text` kindle, `i=stripbooks` papier). On garde les
  `n_top=12` premiers ASIN organiques dédupliqués par `dict.fromkeys` (préserve l'ordre : une SERP
  qui répète un ASIN ne doit ni le facturer deux fois ni écraser sa position). 12 et non 20 :
  -40 % de coût ASIN. Le docstring (`fiction_serp_provider.py:25-27`) chiffre les positions
  13-20 à « 0,024 $ chacun » — **lire 0,024 $ pour le bloc de 8, pas par position** :
  `COST_PER_CALL_USD[2] = 0,003 $` par ASIN (`search_providers.py:24`), soit 8 × 0,003 = 0,024 $
  par niche. Formulation à corriger dans le docstring.
  **Chaque niche est isolée par try/except** : une niche qui lève est écartée et comptée, les
  rayons déjà payés sont conservés. Aucune survivante → retour `[]`.
- **C — UN SEUL batch ASIN global.** C'est le point du module : union dédupliquée de tous les
  ASIN, passée en un appel `product_raw_batch` (jusqu'à 100 ASIN par task_post). La file
  DataForSEO met ~250 s **quel que soit** le nombre d'ASIN : la payer une fois par run au lieu
  d'une fois par niche fait passer 10 niches de 42 min à 5 min. Bonus : la dédup devient
  inter-niches. Cache livre par ASIN, TTL 7 j. Un payload inexploitable est **absent** du dict
  rendu, jamais une entrée factice.
- **D — Classification des quatrièmes de couverture** (payant, poste LLM dominant). Seuls les
  livres AVEC blurb. Cache de classification (TTL **30 jours**, `CLASSIFICATION_TTL_S`,
  `cache.py:17`) dont la clé porte les cinq choses qui changent le résultat : ASIN + version de
  taxonomie + modèle + SHA1 du prompt système + empreinte des champs de `TropeClassification`
  (`cache.py:144`). Lots de
  `LOT_MAX=20` livres (20 blurbs ~ 9k tokens ; 100 blurbs pour `max_tokens=4000` rendrait la
  troncature nominale). Le module lit `stop_reason=="max_tokens"` et signale la troncature,
  compare ASIN rendus / ASIN envoyés, ignore tout ASIN halluciné hors lot.
- **E — Sonde autocomplete** par niche (gratuit) : `probe_niche` sonde la requête du trio ; si
  elle ne rend rien, elle sonde **seulement alors** la requête canonique du sous-genre, pour
  distinguer « trio trop précis » de « sous-genre fantôme ». Barème 0 / 0,5 / 1. Une query vide
  rend immédiatement `mesure=False`.
- **F — Reconstruction + scoring** : le rayon de chaque niche est reconstruit depuis la table
  globale enrichie et `serp_position` est **ré-affectée selon la position dans CETTE niche** (pas
  celle du batch global, pas celle du cache). Les ASIN non enrichis sont comptés dans
  `FictionShelf.n_echecs` et annoncés. `build_report` applique `livres_scorables`
  (3 exclusions : titre gratuit, non-roman, mauvais rayon) **avant** tout calcul, puis
  `depth_score`, `openness_score`, `saturation_trio`, `demand_matrix` et un verdict textuel qui
  porte explicitement ses réserves.
- **Tri final** : profondeur décroissante, saturation croissante à profondeur égale.

### 2.3 Endpoints (`web/server.py`)

| Méthode | Chemin | Rôle |
|---|---|---|
| GET | `/` | Sert `web/index.html` tel quel (lecture disque à chaque appel) |
| GET | `/api/scout` | Scout non-fiction en **SSE**. `seed` (""), `ideas` (10), `search` (4). Thread + `queue.Queue` qui ne vit que le temps de la requête HTTP. Consigne dans `history.db` via `_consigner_scout`, qui **saute les niches dont `concurrence_mesuree` est `False`** : un point qu'on sait faux produirait au passage suivant un delta spectaculaire et mensonger. **N'enregistre aucun usage et ne vérifie pas le plafond** |
| GET | `/api/fiction/sous-genres` | `[{cle, label}]` triés, lus depuis `data/fiction_taxonomy_fr_v1.json`. Source de vérité unique du sélecteur : jamais de liste dupliquée en dur côté JS |
| GET | `/api/fiction` | Scout fiction en SSE. `sous_genre` (obligatoire), `n_niches` (8), `rayon` ("kindle"). Valide le sous-genre AVANT de lancer quoi que ce soit → 400 explicite au lieu d'une KeyError 500. Ré-injecte `autocomplete_score` à la main (c'est une `@property`, non sérialisée par `model_dump`). **Consigne dans `history.db`** (appel `_consigner_fiction`, `web/server.py:172`) — mais l'UI n'affiche jamais cet historique, cf. §5.25 |
| POST | `/api/jobs` | Crée un job asynchrone, rend **202 + {id} immédiatement**. Body `{type: "scout"\|"fiction", user_id ("local"), + params}`. Type inconnu → 400. **Seul endpoint qui vérifie le plafond** (`UsageMeter.autorise`, 429 si atteint) et **seul qui impute `n_analyses=1`**. **Consigne aussi dans `history.db`** : les deux runners reçoivent `user_id` et appellent `_consigner_scout` / `_consigner_fiction` (`web/server.py:211,230`). Le thread est détaché : fermer l'onglet ne tue pas le run. En cas d'exception, le coût déjà engagé est quand même imputé |
| GET | `/api/jobs/{id}` | État complet : statut, progression (200 derniers messages), résultat, coût, erreur, dates. 404 si inconnu |
| GET | `/api/jobs` | Liste par utilisateur, plus récents d'abord. `user_id` ("local"), `limit` (20) |
| GET | `/api/jobs/{id}/stream` | SSE **reconnectable** branché sur `jobs.db` (poll 0,3 s). Rejoue la progression depuis le début à chaque reconnexion, puis `result` + `cost` + `done` |
| GET | `/api/usage` | Consommation du mois **glissant** (fenêtre 30 j, ni calendaire ni cumulative à vie) : `{n_analyses, cout_usd}` |
| POST | `/api/verdict` | Analyse éditoriale d'UNE niche, à la demande, **sans état** (la `ScoredNiche` entière dans le body ; body invalide → 400). Mesuré à **0,0283 $** pièce. Impute avec `n_analyses=0` |
| GET | `/api/history` | `{niche, passages[], delta}`. Une niche vue une seule fois rend `delta: null` avec un **200** : « pas encore de recul » est une réponse, pas un échec |
| POST | `/api/kdp-keywords` | Les 7 mots-clés backend KDP, sans état, **~0,006 $ (ESTIMÉ** — docstring de `api_kdp_keywords`, `web/server.py:387`, et ligne « estime » de `tutoriel_pdf.COUTS:69` ; aucune mesure datée). Le LLM propose ~22 candidats, le code applique les règles KDP, l'autocomplete confirme **gratuitement** (le coût imputé ne couvre que le LLM). `n_analyses=0` |
| POST | `/api/pdf` | One-pager PDF de positionnement à la volée (fpdf2). Stateless, gratuit, aucune persistance serveur |

### 2.4 Modules

**Orchestration** — `scout_master.py` (non-fiction), `fiction_master.py` (fiction, batch ASIN
unique par run).

**Modèles et scoring** — `models.py` (306 lignes, tous les types pydantic partagés ; porte aussi
de la logique métier subtile : `est_serie`, `est_payant_dans`, extras/echo avec dépouillement des
diacritiques) · `scoring.py` (non-fiction, 100 % pur) · `fiction_scoring.py` (`depth_score`
BSR-first 0,4 meilleur + 0,6 médiane, `openness_score`, `saturation_trio` — le différenciateur,
impossible sans avoir lu les quatrièmes de couverture —, matrice de demande à 6 issues ; tous les
seuils dans un unique dict `SEUILS` calé sur des rayons mesurés en live).

**Accès données** — `search_providers.py` (seam de l'étape payante : `search`,
`product_raw_batch` jusqu'à 100 ASIN, `product_info_batch`, mapping pur et testé, parseurs de BSR)
· `bsr_source.py` · `niche_validator.py` (**phase 2 entière du scout non-fiction** : le gate
gratuit de §2.1, `validate_niches` triant par `(validated, demand_score)`, `niche_validator.py:63`)
· `amazon_autocomplete.py` (deux variantes volontairement distinctes :
`fetch_json_strict` qui lève, `_default_fetch_json` qui avale) · `amazon_product.py` (BSR gratuit
par scraping direct) · `util.py` (`http_get` : headers navigateur + retry, `getter` injectable ;
il **re-lève après ses retries** — c'est ce qui permet à §5.10 de distinguer une panne d'un
signal absent ; utilisé par `amazon_autocomplete.py` et `amazon_product.py`) ·
`fiction_serp_provider.py` (scindé en `fetch_shelf_asins` rapide appelable
N fois et `enrich_asins`, la file lente appelée une fois) · `fiction_books.py` (mappe un payload
ASIN réel vers `EnrichedBook`, gère les formes atypiques observées sans jamais lever) ·
`fiction_autocomplete.py` (sonde à deux barreaux).

**LLM** — `niche_ideator.py` · `niche_verdict.py` · `kdp_keywords.py` · `fiction_ideator.py` ·
`fiction_classifier.py`. Tous en **tool-use forcé**, jamais de parsing de texte libre.

**Infrastructure** — `cache.py` (clé/valeur SQLite partagé cross-user, TTL, connexion par appel +
WAL) · `cost_tracker.py` (coût réel : appels DataForSEO + tokens LLM, grille par modèle) ·
`jobs.py` · `usage.py` · `history.py` (la seule fonction qui répond à « est-ce que ça bouge ? ») ·
`fiction_taxonomy.py` (chargement/validation de la taxonomie, source de vérité unique des filtres
de rayon et des libellés Amazon, rend des copies profondes).

**Sorties** — `positioning_pdf.py` (one-pager, Helvetica core, assainisseur latin-1, dégrade
proprement sans verdict) · `tutoriel_pdf.py` (script autonome, exposé par aucun endpoint ;
`python 01-scripts/tutoriel_pdf.py` régénère les deux PDF à la racine ; constantes
`COUTS` / `ENV_VARS` / `ENDPOINTS` / `GLOSSAIRE` / `PIEGES`). **`COUTS` est la seule source du
dépôt qui étiquette chaque chiffre mesuré / calculé / extrapolé / estimé.** Le retard signalé au
tour précédent est **résorbé** (commit `0c467bb`) : `ENDPOINTS` couvre les 13 routes, `ENV_VARS`
ne cite plus les `REDDIT_*` mais `KDP_KEYWORDS_MODEL`, `COUTS` porte une ligne mots-clés KDP
marquée « estime ». Deux tests le tiennent désormais (`tests/test_tutoriel_pdf.py:100,118`) en
lisant `web/server.py` et les `os.getenv` du code comme source de vérité plutôt qu'en figeant
une liste. **Ce n'est pas pour autant « la doc la plus à jour du projet »** : c'est un générateur
de PDF, tenu par des tests sur deux points précis (routes exposées, variables encore lues) et
sur rien d'autre — les `PIEGES` et le `GLOSSAIRE` ne sont vérifiés par personne. Trou connu :
`ENV_VARS` ignore `HOST` et `PORT` (le test ne vérifie que le sens « documenté ⇒ lu »).

**Outillage dev** — `fiction_validation.py` + `build_validation_set.py` + `validate_classifier.py`
(set de ~50 livres, export xlsx pour correction humaine, mesure de l'accord IA/humain contre la
porte des 80 %) · `demo_free.py` (smoke test CLI des deux canaux gratuits : autocomplete et BSR
scrapé ; couvert par `tests/test_demo_free.py`).

**Entrées CLI à statut non tranché** — `launcher.py`, lancé par `IA-Niches.bat`. **Ce n'est pas
du code v1** : il n'importe que des modules v2 (`amazon_autocomplete`, `amazon_product`, et en
import tardif `niche_ideator` / `niche_validator`, `launcher.py:13-14,63-64`). Son menu est
antérieur à l'UI web et n'expose ni le scout non-fiction complet ni la fiction, **mais son
option 3 appelle l'ideator LLM puis la validation autocomplete** (`launcher.py:26,65-66`,
annoncée « ~0,02 € » dans le menu) : c'est un **chemin de dépense Anthropic actif**, pas un
fichier inerte. Statut à trancher par Baptiste — ne le présenter ni comme supprimé, ni comme
mort. `IA-Niches-Web.bat` lance `python web\server.py` et ouvre `http://127.0.0.1:8000` :
c'est le point d'entrée réel du produit.

### 2.5 Tests

**326 tests** collectés sur 41 fichiers `tests/test_*.py`, aucune erreur de collecte
(`python -m pytest --collect-only`, relancé le 2026-07-29 après les commits `60e405a` et
`0c467bb`).
`python -m pytest` depuis la racine (`pytest.ini` fixe `pythonpath=01-scripts`, `testpaths=tests`).
**Tous hors-ligne** : chaque dépendance lourde (client Anthropic, provider DataForSEO, fetch HTTP,
sonde autocomplete) est injectable par paramètre. Aucun test d'intégration réseau.
Deux fichiers testent l'interface en lisant `web/index.html` comme du texte
(`test_ux_glossaire.py`, `test_ux_kdp_historique.py`) — mais ils vérifient la **présence** des
chaînes, pas leur **atteignabilité** (voir §5).

---

## 3. SOURCES DE DONNÉES ET COÛTS

| Source | Usage | Coût |
|---|---|---|
| **API Anthropic** | Ideator non-fiction, ideator fiction, classifieur de blurbs, verdict éditorial, mots-clés KDP | Payant au token. Grille dans `cost_tracker.py:8-14` — les **quatre clés portent le préfixe `claude-`** : `claude-sonnet-5` (défaut partout) 2 $/10 $ par million in/out en tarif intro **jusqu'au 31/08/2026**, puis 3 $/15 $ ; `claude-opus-4-8` 5 $/25 $ ; `claude-fable-5` 10 $/50 $ ; `claude-haiku-4-5` 1 $/5 $. **Un identifiant absent de la grille est facturé 0,00 $** (`cost_tracker.py:22-24`, `if not p: return 0.0`) : un coût invisible, pas nul. Écrire `opus-4-8` sans le préfixe dans `IDEATOR_MODEL` suffit à faire disparaître la dépense des rapports sans lever la moindre erreur |
| **DataForSEO — Amazon Products** (`/v3/merchant/amazon/products`) | SERP : organiques vs sponsorisés, ASIN, prix, note, avis, badges | 0,003 $/appel en priority 2 (file rapide ~1-4 min, **défaut**), 0,0015 $ en priority 1 (jusqu'à ~45 min). Cache 10 j |
| **DataForSEO — Amazon ASIN** (`/v3/merchant/amazon/asin`) | BSR, rayon, blurb, série, éditeur, date, langue. Batché jusqu'à 100 ASIN | Même tarif par ASIN. **La file met ~250 s quel que soit le lot** → batch unique par run. Cache livre 7 j, cache BSR 3 j |
| **Classification de blurbs** (dérivée, pas une source réseau) | Étiquettes tropes/décor/`est_roman` produites par le LLM et remises en cache | **TTL 30 j** (`CLASSIFICATION_TTL_S`, `cache.py:17`) — le plus long des quatre, parce que la clé porte déjà tout ce qui peut invalider le résultat (§2.2 D) |
| **Amazon autocomplete** (`completion.amazon.fr/api/2017/suggestions`, marketplace `A13V1IB3VIYZZH`) | Validation de la demande non-fiction, sonde fiction, confirmation des mots-clés KDP | **Gratuit.** Endpoint public, aucune clé. Pause 0,4 s entre requêtes |
| **Fiche `amazon.fr/dp/{asin}` scrapée** | BSR, source par défaut en local | **Gratuit — mais IP résidentielle uniquement** (voir piège ci-dessous) |
| `data/fiction_taxonomy_fr_v1.json` | 6 sous-genres, tropes, décors, browse nodes, requêtes canoniques, filtres et libellés de rayon | Gratuit, fichier local versionné |

Codes DataForSEO : `location_code=2250` (France) et `language_code="fr_FR"` — **pas `"fr"`**
(validé en live).

### PIÈGE DE COÛT À TOUJOURS SIGNALER — `BSR_SOURCE`

`BSR_SOURCE=scrape` (défaut) lit les fiches Amazon depuis une **IP résidentielle** : gratuit sur
le PC de Baptiste, **bloqué depuis un datacenter**. En production il faut
`BSR_SOURCE=dataforseo`, ce qui fait passer un scout non-fiction de **0,030 $ (mesuré) à
0,084 $ (calculé, jamais mesuré en conditions serveur)**.
**Ne jamais citer le chiffre local comme coût de production.**

### Variables d'environnement (`.env` uniquement)

**Treize** variables sont lues par `os.getenv` dans `01-scripts/` et `web/` (recensement
exhaustif sur ces deux dossiers, aucun autre `.py` du dépôt n'en lit) ; `.env.example` en
documente **onze** : il lui manque `HOST` et `PORT`, ajoutées après lui par le commit `60e405a`.
Ce tableau porte les treize.

| Variable | Défaut | Obligatoire |
|---|---|---|
| `ANTHROPIC_API_KEY` | aucun (`os.getenv` sans défaut → `None`) | oui |
| `DATAFORSEO_LOGIN` | `""` — un défaut vide ne fait pas échouer la construction du provider, l'échec survient à l'appel HTTP | oui |
| `DATAFORSEO_PASSWORD` | `""` — c'est le **mot de passe d'API** (app.dataforseo.com/api-access), pas celui du compte | oui |
| `BSR_SOURCE` | `"scrape"` (`bsr_source.py:27`). Toute autre valeur que `scrape`/`dataforseo` lève `ValueError`. Ignorée si `fetch_bsr_fn` est injecté | non |
| `DATAFORSEO_PRIORITY` | `2` (`_resolve_priority`, `search_providers.py:27-44` — le repli sur valeur hors plage est en :41-43, après le cas `ValueError`). Valeur non entière ou hors plage → `warnings.warn` + repli sur 2. Un argument explicite prime sur l'env | non |
| `HOST` | `"127.0.0.1"` (`web/server.py:427`). Lue **uniquement** sous `if __name__ == "__main__"` : sans effet si le serveur est lancé par `uvicorn server:app` | non |
| `PORT` | `"8000"` (`web/server.py:424`). Même portée que `HOST`. Valeur non entière → repli silencieux sur 8000 | non |
| `PLAFOND_ANALYSES_MENSUEL` | non défini → `None` = illimité, mais l'usage reste journalisé (`web/server.py:54`). Valeur non entière → retombe silencieusement sur illimité | non |
| `IDEATOR_MODEL` | `claude-sonnet-5` (`niche_ideator.py:20`), choisi après un A/B live du 2026-07-05 : qualité à parité avec `claude-opus-4-8` pour ~2× moins cher | non |
| `VERDICT_MODEL` | `claude-sonnet-5` (`niche_verdict.py:9`) | non |
| `KDP_KEYWORDS_MODEL` | `claude-sonnet-5` (`kdp_keywords.py:19`) | non |
| `FICTION_IDEATOR_MODEL` | `claude-sonnet-5` (`fiction_ideator.py:11`) | non |
| `FICTION_CLASSIFIER_MODEL` | `claude-sonnet-5` (`fiction_classifier.py:15`). **Ne pas rétrograder** : Haiku 4.5 mesuré à 42 % d'accord contre 80 % requis | non |

Les `REDDIT_*` **ne sont plus lues nulle part** : les modules qui les lisaient ont été supprimés
(commit `eaa20b2`), `.env.example` ne les mentionne plus, et `tutoriel_pdf.ENV_VARS` non plus
depuis le commit `0c467bb` (elles y sont remplacées par `KDP_KEYWORDS_MODEL`). Plus aucun résidu
côté `.py`.

---

## 4. CRITÈRES DE DÉCISION — CE QUI EST CODÉ vs CE QUI EST UNE INTENTION

**Règle absolue : ne jamais présenter une intention comme une règle appliquée.**

### 4.1 CODÉ et vérifiable

| Critère | Où | Détail |
|---|---|---|
| BSR 1 — au moins 1 livre du top organique avec BSR < 10 000 | `scoring.py:26` | `crit1 = best < 10_000` |
| BSR 2 — moyenne du top < 50 000 | `scoring.py:27` | `crit2 = top5_avg < 50_000`. **Nuance assumée** (`scoring.py:15-17`) : le scout ne récupère que le **top 3** (`n_bsr_per_niche=3`), donc `bsr_top5_avg` est la moyenne d'au plus 3 BSR. **Le nom du champ ment sur son contenu** |
| BSR 3 — présence d'un BSR > 50 000 (« place à prendre ») | `scoring.py:28` | `crit3 = worst10 > 50_000`. Le seuil « idéalement > 100 000 » n'est **pas** codé ; `worst_top10` est le max des 3 BSR disponibles au plus |
| Conjonction des 3 critères | `scoring.py:31` | `"ok": crit1 and crit2 and crit3`, exposé en `ScoredNiche.criteres_bsr_ok`, affiché comme badge dans l'UI et « OUI — place à prendre » dans le PDF |
| **Séparation organic / sponsored à la source** — et exclusion des sponsorisés de tous les calculs de QUALITÉ | `search_providers.py:67,71-87` + `scoring.py:53-59,109` + `scout_master.py:92` | Détection `sponsored=it.get("type") == "amazon_paid"`, deux listes distinctes dès `map_dataforseo_result`. Les titres, notes, avis et `count_targeted` ne lisent que `search.organic` ; les ASIN envoyés au BSR viennent exclusivement de `sr.organic` (`scout_master.py:92`). **Ne pas lire « exclus de TOUS les calculs »** : `score_niche` lit bien `search.sponsored` (`scoring.py:54`) et leur NOMBRE entre dans le score — voir la ligne « bonus beaucoup de sponsorisés » ci-dessous. `n_sponsored` est exposé (`scoring.py:109`) et affiché |
| Comptage des concurrents réellement ciblés | `scoring.py:38-45` | `count_targeted` extrait les mots de 4 lettres et plus de la requête et compte les titres organiques qui en contiennent au moins la moitié. Exposé en `n_concurrents_cibles` |
| **Garde « concurrence non mesurée »** (commit `60e405a`) | `scoring.py:78-88` + `models.py:103-107` | `mesuree = search is not None`. Quand la SERP a échoué, **aucun** bonus ni malus de concurrence n'est appliqué : sans ce garde, `n_cibles == 0` faute de mesure déclenchait le bonus « moins de 10 concurrents » (+2) et une niche dont rien n'avait été mesuré sortait à 6,88 « Intéressant ». Exposé en `ScoredNiche.concurrence_mesuree`, **défaut pessimiste `False`** (même motif que `AutocompleteSignal.mesure`) |
| Seuils de concurrence 30/50 | `scoring.py:81-86` | **Malus doux, jamais exclusion**, et **seulement si `mesuree`** : plus de 50 → −2 sur la pénétration, plus de 30 → −1, moins de 10 → +2. Une niche à 200 concurrents n'est jamais rejetée : elle perd au maximum 0,8 point de score global |
| Bonus « place à prendre » | `scoring.py:89-90` | `penetration += 1.5` si `crit3`. **Hors du garde `mesuree`** : il repose sur le BSR, pas sur la SERP — une niche non mesurée peut donc encore le toucher |
| Bonus « beaucoup de sponsorisés » | `scoring.py:87-88` | `+= 0.5` si au moins 3 sponsorisés (beaucoup de sponso = concurrence organique plus faible). C'est le **seul** usage de `search.sponsored` dans un calcul de score : +0,5 en pénétration, soit +0,2 sur le score global |
| Pondération 0,4 / 0,4 / 0,2 | `scoring.py:96` | |
| Seuils de verdict 7,5 et 6,0 | `scoring.py:99-101` | **Quatre** libellés, pas trois : « Concurrence non mesurée — à relancer » court-circuite les seuils quand `mesuree` est faux, puis à analyser en priorité / intéressant / faible |
| Règles KDP des 7 mots-clés | `kdp_keywords.py:22,23,28-34,48-88` | **Vérifiées côté code**, pas seulement demandées au prompt : limite dure de 50 caractères, 7 emplacements, `TERMES_INTERDITS` (livre/ebook/kindle/gratuit/meilleur/nouveau/années/amazon/bestseller…), dédup normalisée, chevauchement total avec le titre. **Chaque rejet sort avec son motif** |
| Taxonomie fiction contraignante | `fiction_ideator.py:112-115` / `fiction_classifier.py:148-164` | L'ideator **écarte** tout trio hors taxonomie ; le classifieur range les clés inconnues dans `other` au lieu de les jeter. Asymétrie assumée : l'ideator invente, le classifieur observe |

### 4.2 NON CODÉ — intentions, prompts ou impossibilités

| Sujet | Statut réel |
|---|---|
| Exclusions « saisonnier / religions à expertise pointue / politique contemporaine / borderline TOS / niches d'experts ultra-techniques » | **Non codées.** Elles n'existent que comme texte dans le prompt système de l'ideator (`niche_ideator.py:38-45`). Aucun filtre, aucune liste de mots interdits, aucune vérification a posteriori. **Si le modèle désobéit, rien ne le rattrape** — contrairement aux règles KDP et à la taxonomie fiction, explicitement doublées en code |
| Axe 3 « compatibilité livre » | **Non implémenté.** `scoring.py:94` le fige à la constante `8.0` pour toute niche. L'axe ne discrimine rien : le score global vaut toujours `demande×0,4 + penetration×0,4 + 1,6`, mécaniquement borné entre 2,4 et 9,6 |
| Bonus « expertise pharmacien » (santé/nutrition/bien-être) | **Non codé et délibérément contredit** : `niche_ideator.py:47-50` impose au contraire au modèle de ne privilégier aucun domaine et de ne rien supposer de l'expertise de l'auteur |
| Malus pour risque KDP TOS | **Non codé.** `NicheCandidate.risques` (`models.py:24`) est rempli par le LLM (champ `required` dans le schéma d'outil) mais n'est propagé nulle part : ni `NicheValidation`, ni `ScoredNiche`, ni le scoring, ni l'affichage. **Champ mort** |
| « Nombre de résultats de recherche Amazon inférieur à 10 000 » | **Non codé et non mesurable en l'état** : la donnée n'est pas collectée. `SearchResult.total_items` vaut `len(items)` de la page de SERP (`search_providers.py:86`), pas le total annoncé par Amazon, et n'entre dans aucun calcul |

---

## 5. PIÈGES ÉTABLIS EN LIVE

Section critique. Chacun a coûté un bug réel.

**Scoring et lecture des résultats**

1. **La saturation est le seul score inversé.** Sur `depth_score` et `openness_score`, élevé = bon ;
   sur `saturation_trio`, élevé = **mauvais**. Une jauge colorée uniformément fera recommander
   exactement les pires niches. Encodé dans `history.py:25-26` (`METRIQUES_INVERSEES`) et dans le
   tri de `fiction_master.py:162`.
2. **`non_mesurable` n'est pas « mort ».** Les deux affichent des zéros partout mais disent le
   contraire à l'utilisateur : l'un l'invite à re-mesurer, l'autre à écarter la niche.
   `fiction_scoring.py:158-165` rend explicitement `non_mesurable` quand aucun livre n'est
   scorable, et `_verdict` l'écrit en toutes lettres. Vu en live sur « romance captif huis clos ».
3. **Un rayon amputé n'est pas un rayon désert.** `FictionShelf.n_echecs > 0` signifie que des
   ASIN n'ont pas pu être enrichis (`fiction_master.py:150-151`, `fiction_scoring.py:206-208`).
   Masquer cette mention transforme une donnée manquante en « place à prendre ».
4. **Le piège `label_rayon`.** `FictionNiche.rayon` vaut `"kindle"`/`"papier"` (paramètre interne)
   alors que `EnrichedBook.bsr_rayon` porte le libellé Amazon `"Boutique Kindle"`/`"Livres"`.
   Passer `niche.rayon` tel quel à `est_payant_dans()` rend `False` pour **tous** les livres et
   déclare la niche morte **sans la moindre erreur**. Passer par `fiction_taxonomy.label_rayon()`.
   Documenté trois fois (docstring de `EnrichedBook.est_payant_dans`, `models.py:231-239` ; de
   `fiction_taxonomy.label_rayon`, `:57-67` ; de `fiction_scoring.livres_scorables`, `:43-46`)
   parce que le bug a déjà été commis une fois.
5. **Les BSR Kindle et papier ne se comparent pas** : deux classements distincts, c'est la raison
   d'être du champ `bsr_rayon` (docstring d'`EnrichedBook`, `models.py:202-205` ; champ `:213`).
6. **Les titres gratuits ont leur propre classement** — ~25 % du top Kindle mesuré
   (`SEUILS["part_gratuits_mesuree"]`). Exclus via `bsr_gratuit`, à ne jamais réintroduire dans
   un calcul maison.
7. **Le lookahead sur « en Livres ».** Un ebook affiche « n°478 des titres gratuits dans la
   Boutique Kindle … 5 en Livres électroniques de fiction criminelle ». Sans le `(?!\s+\w)`, le
   parseur renvoyait 5 au lieu de 478 — faux de deux ordres de grandeur, et silencieux.
   `search_providers.py:200-203`, `amazon_product.py:13`.
8. **« Livre 1 sur 1 » n'est pas une série** : Amazon balise un tome unique comme une collection
   d'un seul titre. `EnrichedBook.est_serie` (`models.py:225-229`) exige `serie_total > 1`
   (constaté sur B0GN4G414V).

**Mesure de la demande**

9. **L'autocomplete est préfixe-based.** Sonder une expression longue de longue traîne rend
   systématiquement 0 (« cosy mystery boulangerie bretagne » → rien), ce qui garantissait 0
   confirmation sur 7 en live. `kdp_keywords.py:144-154` sonde donc les **3 premiers mots**
   (amorce) : on vérifie que l'amorce est cherchée, **pas** que la phrase exacte l'est — ce
   qu'aucun outil ne peut établir depuis l'autocomplete.
10. **Une mesure en panne n'est pas un signal absent.** Invariant le plus répété du dépôt, et
    désormais présent dans les deux moteurs : `AutocompleteSignal.mesure` a un défaut
    **pessimiste** `False` (`models.py:190-193`), `FictionNicheReport.autocomplete_score` rend
    `None` et non `0.0` (`models.py:300-306`), `MotsClesKDP.sonde_indisponible` existe pour la
    même raison (`models.py:133-135`), `ScoredNiche.concurrence_mesuree` a été ajouté par
    `60e405a` pour la SERP non-fiction (`models.py:103-107`, §4.1), et `amazon_autocomplete.py`
    maintient deux fonctions (`fetch_json_strict` qui lève, `_default_fetch_json` qui avale)
    précisément pour ne jamais confondre une panne réseau avec « personne ne cherche ça ».
11. **L'autocomplete ne gate jamais seul.** Le spike M0 §V3 est formel et le code le respecte :
    `_matrix_mesuree` (`fiction_scoring.py:168-183`) n'utilise nulle part l'autocomplete pour
    arbitrer `demand_matrix`.
12. **Un point unique n'est pas une tendance.** `history.py:88-94` rend `None` quand il n'y a
    qu'un passage. `SEUIL_SIGNIFICATIF=0.10` (`history.py:30`) filtre le bruit de mesure : en
    deçà, on n'annonce rien plutôt que de faire réagir un auteur sur du vent.

**Coût, cache, infrastructure**

13. **L'empreinte de schéma dans la clé de cache** (`cache.py:20-81`) : les **quatre** clés
    portent un SHA1 des **noms** de champs de leur modèle pydantic — `book:` (`EnrichedBook`,
    `cache.py:121`), `bsr:` (`BsrInfo`, `:113`), `search:` (`SearchResult`, `:117`) et `clf:`
    (`TropeClassification`, `:144`, ajoutée en dernier par le commit `7b79e77`). `clf:` porte
    **en plus** la version de taxonomie, le modèle et un SHA1 du prompt système
    (`_prompt_tag()`) : ce qui change le raisonnement, là où l'empreinte de champs couvre ce
    qui change la forme du résultat. Sans elles, ajouter un champ (le blurb l'a été en M4) sert
    des objets amputés en silence — 7 jours pour `book:`, **30 jours pour `clf:`** — et durcir
    le prompt n'a aucun effet sur les livres déjà vus. **Limite assumée** : l'empreinte suit les
    noms, pas les types ni la sémantique — changer le sens d'un champ sans le renommer exige de
    vider le cache à la main.
14. **Le cache est mutualisé entre tous les utilisateurs, par conception** (`cache.py:1`). Ce n'est
    pas un oubli de cloisonnement : deux clients qui analysent le même rayon ne le paient qu'une
    fois. Quand l'authentification arrivera, introduire `user_id` **uniquement** dans
    `history.py` / `usage.py` / `jobs.py`, **jamais** dans `cache.py`.
15. **La file ASIN se paie une fois par run, pas par niche** (`fiction_master.py:10-13`) : ~250 s
    quel que soit le lot. Revenir à un batch par niche ferait passer 10 niches de 5 à 42 minutes.
16. **Le budget de poll a été doublé après un incident** (`search_providers.py:145-150`) : à
    16 polls (128 s), un simple ralentissement de la file DataForSEO effaçait un run entier —
    3 SERP sur 3 expirées, mesuré en live. C'est désormais 40 polls (~320 s), aligné sur le
    chemin ASIN, et le message d'erreur dit le budget écoulé pour distinguer « file lente » d'une
    vraie erreur de requête.
17. **Pas de `temperature` / `top_p` / `top_k` sur `claude-sonnet-5`** : ces paramètres sont
    supprimés et toute valeur non-défaut renvoie une **400** (`fiction_classifier.py:182-184`).
    La stabilité des étiquettes se joue dans le prompt.
18. **Ne pas rétrograder le classifieur.** Haiku 4.5 mesuré à 42 % d'accord humain/IA contre 80 %
    requis. « Accord » est défini explicitement (`fiction_validation.py:1-8`) :
    Jaccard(tropes) ≥ 0,5 **ET** décor identique **ET** `est_roman` identique. Sous la porte des
    80 %, c'est la **taxonomie** qu'on corrige, pas le classifieur.
19. **Instance par appel, jamais à l'import.** `Cache`, `JobStore`, `UsageMeter` et
    `NicheHistory` ouvrent une connexion SQLite par appel avec WAL ; `web/server.py:40-47` ne
    garde que des constantes `Path`. Construire un magasin à l'import écrirait de vrais fichiers
    dans le dépôt dès qu'un test importe `server.py`, et casserait la sûreté en concurrence (le
    serveur lance un thread par run).
20. **Les défauts de modèle sont lus à l'import, AVANT `load_dotenv()` en CLI.**
    `DEFAULT_MODEL = os.getenv(...)` s'exécute au chargement du module alors que `scout_master.py`
    n'appelle `load_dotenv()` qu'à l'intérieur de `run_scout` (ligne 48), après avoir importé
    `niche_ideator` (ligne 16). Un `IDEATOR_MODEL` défini uniquement dans `.env` est donc
    **ignoré en ligne de commande**. `web/server.py` y échappe parce qu'il appelle `load_dotenv`
    (ligne 24) **avant** ses imports moteur (ligne 25 et suivantes) : un ordre qui a l'air d'un
    détail de style et qui est en fait load-bearing.
21. **`POST /api/jobs` accepte deux jeux de noms de paramètres** (`_run_scout_job`,
    `web/server.py:204-208`) :
    `n_ideas`/`n_search` **et** les noms historiques `ideas`/`search`, parce qu'une divergence a
    été constatée en live — un client reprenant les noms SSE voyait son plafond silencieusement
    ignoré et payait les défauts (6 recherches au lieu des 2 demandées).
22. **Le plafond mensuel ne couvre que les jobs.** `UsageMeter.autorise` n'est appelé que dans
    `POST /api/jobs` (`web/server.py:257-261`). `GET /api/scout` et `GET /api/fiction` dépensent
    **sans vérifier le plafond et sans rien enregistrer** dans `usage.db` — ils consignent bien
    l'historique, mais pas l'usage : les deux magasins sont indépendants. Conséquence directe :
    le bandeau « Ce mois-ci : N analyse(s) » de l'UI reste à 0 quoi que fasse l'utilisateur,
    puisque `/api/verdict` et `/api/kdp-keywords` imputent avec `n_analyses=0` et que l'UI
    n'appelle jamais `/api/jobs`.
23. **`FictionNicheReport` interdit les champs extra** (`model_config extra="forbid"`,
    `models.py:282`) : un champ mal nommé lève à la construction plutôt que d'être avalé en
    silence. C'est ce qui a permis d'attraper l'ancien `autocomplete_score` mal placé.
24. **L'en-tête `Content-Disposition` doit rester encodable en latin-1** (exigence Starlette) :
    `_content_disposition` (`web/server.py:345-352`) émet un nom ASCII de repli et un
    `filename*` RFC 5987 UTF-8, sinon un
    nom de niche accentué fait planter la réponse. Même famille de contrainte pour les PDF :
    fpdf2 en police core Helvetica exige l'assainisseur latin-1 de `positioning_pdf.py:22-26`.

**Interface**

25. **Les boutons « Télécharger le PDF » et « Mots-clés KDP » sont inatteignables dans l'UI
    livrée.** Ils sont générés à l'intérieur de `verdictBlock(r)` (`web/index.html:511-535`,
    boutons `:531-532`), qui fait `if(!v) return ''` (`:513`) quand la niche n'a pas de verdict. Or `/api/scout` appelle `run_scout`
    sans `n_verdict`, donc `n_verdict=0` et `ScoredNiche.verdict` vaut **toujours** `None` ; et
    `index.html` n'appelle jamais `POST /api/verdict` — recensement exhaustif des `api/` du
    fichier : `api/kdp-keywords` (:546), `api/history` (:613), `api/pdf` (:634), `api/scout`
    (:708), `api/fiction/sous-genres` (:747), `api/fiction` (:866), `api/usage` (:954).
    Trois endpoints payants ou utiles —
    `/api/verdict`, `/api/pdf`, `/api/kdp-keywords` — n'ont donc **aucun chemin d'accès depuis
    l'interface**. Ironie : `tests/test_ux_kdp_historique.py` vérifie que les chaînes sont
    présentes dans le HTML, ce qui passe, mais pas qu'elles sont atteignables.
    **Même famille, côté historique fiction** : `/api/fiction` et le job fiction écrivent bien
    dans `history.db`, mais la carte fiction de `web/index.html` ne contient aucun `histslot` ni
    appel à `loadHistorique` — les deux n'existent que dans le rendu non-fiction (`histslot`
    injecté `:672`, chargé à l'ouverture de la ligne `:683`). L'historique fiction est donc
    **écrit et jamais lu**.
    Corollaire pratique : l'UI n'appelle pas non plus `/api/jobs`, donc aucun run lancé depuis
    l'interface ne passe par le seul chemin qui vérifie le plafond (§5.22).

**Invariant transversal**

26. **Un échec n'interrompt jamais un run, mais il est toujours compté — et il ne doit jamais se
    lire comme une mesure.** Search en échec → niche scorée sans concurrence
    (`scout_master.py:89-91`) **et marquée `concurrence_mesuree=False`**, ce qui la prive de tout
    bonus de pénétration, lui donne un verdict explicite et l'exclut de l'historique
    (`60e405a` ; c'était le défaut le plus grave de la revue) ; scrape BSR en échec sur un ASIN →
    `None` pour cet ASIN (`bsr_source.py:33-34`) ; niche fiction en échec → écartée et comptée,
    rayons déjà payés conservés (`fiction_master.py:85-89`) ; livre au payload atypique → `None`
    au lieu d'une `ValidationError` qui tuerait le run (`fiction_books.py:132-135`) ; job en
    échec → le coût déjà engagé reste imputé (`jobs.py:104-105`, `web/server.py:282-285`).

---

## 6. RÈGLES DE FONCTIONNEMENT PERMANENTES

1. **TDD non négociable.** Les tests d'abord, **en rouge**, avant toute ligne d'implémentation.
   On vérifie que le test échoue pour la bonne raison, puis on écrit le minimum qui le fait
   passer. Aucune fonctionnalité ne rentre sans test hors-ligne, dépendance lourde injectée par
   paramètre — c'est ce qui tient les 326 tests sans réseau.
2. **Transparence sur les échecs et les coûts.** Toujours dire quelle source a échoué, combien
   d'ASIN n'ont pas pu être enrichis, combien de sponsorisés ont été écartés, ce qu'a coûté le
   run. Ne jamais masquer un échec partiel ni arrondir un coût vers le bas. Distinguer toujours
   un chiffre mesuré d'un chiffre extrapolé.
3. **Ne jamais présenter une absence de mesure comme un verdict de marché.** `non_mesurable` n'est
   pas « niche morte ». Sonde autocomplete en panne n'est pas « personne ne cherche ça ». Rayon
   amputé n'est pas « place à prendre ». `delta: null` n'est pas une erreur. C'est la faute la
   plus grave que ce produit puisse commettre : elle fait publier un livre sur une niche vide, ou
   renoncer à une bonne.
4. **Ne jamais toucher aux dossiers hors du projet.** Le périmètre est la racine du dépôt
   `IA Niches` et rien d'autre. En particulier, ne jamais approcher les dossiers personnels ou
   comptables de Baptiste.
5. **Secrets dans `.env` uniquement.** Jamais de clé dans un fichier versionné, jamais dans un
   message, jamais dans un log. `.env.example` documente les noms, pas les valeurs.
6. **Pas de devinettes.** Si une donnée manque, le dire ou la demander. Ne jamais écrire un nom de
   fichier, de fonction, d'endpoint ou un chiffre qui n'a pas été vu dans le code.
7. **Le code est la doc.** Avant de modifier un module, lire son docstring : il porte les
   contraintes mesurées en live. Toute décision non évidente se documente **dans le code**, pas
   dans un .md à part. Quand un piège de §5 est corrigé ou aggravé, mettre ce fichier à jour.
8. **Économie de coût.** Le gate de validation autocomplete (gratuit) avant tout appel payant est
   structurel : ne jamais lancer un appel DataForSEO ou LLM « au cas où ». Vérifier le cache
   avant. Grouper les appels ASIN. Un nouvel appel payant se justifie par écrit.
9. **Confirmation avant action lourde** : avant d'écraser un fichier existant, de vider le cache,
   de lancer un run réel qui dépense, ou de modifier une valeur par défaut de modèle.
10. **Sortie utile en cas d'échec** : rapport partiel avec mention explicite des sources tombées,
    jamais un plantage muet. C'est déjà l'invariant du code (§5.26), c'est aussi la règle de
    conduite de l'agent.

---

## 7. CE QUI N'EXISTE PAS

À ne jamais présenter comme disponible, à ne jamais réintroduire par inadvertance.

- **Scrapingdog** : aucun code, aucune clé, aucun appel. **Côté `.py`, le mot ne subsiste que
  dans le docstring de `cost_tracker.py:2`** (les trois scripts v1 qui le mentionnaient ont été
  supprimés par le commit `eaa20b2`). Il subsiste en revanche dans des fichiers non exécutables
  encore versionnés — `README.md`, `ROADMAP.md`, `docs/superpowers/**` — et une variable
  résiduelle traîne dans le `.env` local (non versionné) : la nettoyer ne change rien au
  comportement, mais ne pas la lire comme une intégration vivante.
- **`credits_tracker.py`, `MAX_CREDITS_PER_RUN`, plafond de crédits par run, mode dry-run au
  premier lancement, retry gaté à 1 tentative avec 5 s de délai, compteur « crédits restants sur
  1000 »** : rien de tout cela n'existe, et le résidu `99-logs/credits-log.csv` a été supprimé
  (commit `eaa20b2`). Le seul garde-fou de dépense est
  `PLAFOND_ANALYSES_MENSUEL`, et il n'est vérifié que dans `POST /api/jobs`.
- **Rapport Excel `.xlsx` du scout** (onglets Synthèse / Métadonnées / Sponsorisés, mise en forme
  conditionnelle) : n'existe pas. `openpyxl` est **conservé** dans `requirements.txt` parce qu'il
  est importé par `fiction_validation.py` **et par trois fichiers de tests**
  (`test_build_validation_set.py`, `test_fiction_validation.py`, `test_validate_classifier.py`) :
  outillage de validation **manuelle** du classifieur, pas un livrable. Les
  résultats du scout ne sortent qu'en JSON (SSE ou job) et en PDF one-pager.
- **Google Trends (`pytrends`), Reddit (`praw`), Google News (`feedparser`)** : les modules
  `trends_fr.py`, `reddit_fr.py` et `news_fr.py` ont été **supprimés** (commit `eaa20b2`), avec
  eux le dossier `02-veille-hebdo/`. Les six paquets correspondants sont sortis de
  `requirements.txt` — nuance à respecter : `pytrends`, `praw` et `feedparser` n'étaient pas
  sans import, ils étaient importés par ces trois modules et sont donc morts **en cascade** ;
  seuls `pandas`, `beautifulsoup4` et `lxml` avaient réellement zéro occurrence (le parsing des
  fiches Amazon se fait en expressions régulières pures, cf. `amazon_product.py`).
- **Les dossiers `00-config/`, `02-veille-hebdo/`, `03-niches-validees/` et `04-archives/`** :
  absents du disque, ne pas les recréer, ne pas y renvoyer. **Nuance d'attribution** : le commit
  `eaa20b2` ne supprime que `00-config/` et `02-veille-hebdo/` (avec les trois modules v1, deux
  fichiers de `05-prompts/` et `99-logs/credits-log.csv`). `03-niches-validees/` et `04-archives/`
  étaient **vides et n'ont jamais été versionnés** — git ne suit pas les dossiers vides, donc
  aucun commit ne peut les avoir supprimés (`git log --all -- 03-niches-validees 04-archives` ne
  rend rien). Chercher leur suppression dans `git show eaa20b2` est une perte de temps. De
  `05-prompts/`, seul `prompt-onebooklab-template.md` subsiste — il sert le workflow manuscrit
  personnel de Baptiste, **hors du périmètre de cet outil**. Restent versionnés et à conserver :
  `99-logs/validation-fiction-2026-07-21.xlsx` et
  `99-logs/rapport-validation-classifieur-2026-07-21.json` (étalon-or du classifieur), plus
  `assets/hedgehog.ico`. Leur coût de reproduction : **0,32 $ d'API**, seul chiffre sourçable
  (`tutoriel_pdf.COUTS:68`, marqué « one-shot »), plus une relecture humaine dont la **durée n'est
  pas mesurée** — l'« environ une heure » ne vient que du message du commit `eaa20b2` et de
  `ROADMAP.md`, jamais du code ni du rapport, qui ne porte que `lignes_relues_declarees: 35` sur
  `livres_du_set: 50` et la mention `validation tacite declaree par Baptiste`.
- **TikTok**, sous quelque forme que ce soit : ni automatisé, ni en input manuel.
- **Le mode « à partir de rien » nourri par des tendances** : `signals` existe dans les signatures
  et va jusqu'au prompt, mais aucun appelant ne le remplit. Il se réduit à « graine vide ».
- **Le workflow humain en 5 phases** (validation humaine, analyse sur screenshots, pré-production,
  post-production) : aucune trace en code. Le prompt de `niche_verdict.py` dit même explicitement
  au modèle de ne pas réclamer de screenshots et de raisonner sur les chiffres.
- **Sommaire détaillé en chapitres, prompts OneBookLab, briefs de couverture, quatrième de
  couverture, fiche produit AIDA, liste de 15 mots-clés à vérifier** : rien.
  `MotsClesKDP.a_verifier` n'est pas cette liste : c'est le reliquat des candidats au-delà des
  7 emplacements.
- **Authentification, comptes, mots de passe, sessions, paiement, abonnement, facturation.**
  `user_id` existe en colonne partout et vaut `"local"` par défaut. **Où se trouve exactement le
  codage en dur, parce que c'est là qu'il faudra brancher l'authentification** :
  `_consigner_scout` et `_consigner_fiction` **prennent et lisent** un paramètre `user_id`
  (signatures `web/server.py:72,90`, transmis à `NicheHistory.enregistrer` `:84,93`) ; le
  `"local"` en dur est au **site d'appel** des endpoints SSE, qui les appellent sans second
  argument (`web/server.py:112,172`), pas dans ces fonctions. Le chemin asynchrone, lui, propage
  déjà le vrai `user_id` (`:211,230`). Les deux seuls vrais codages en dur sans paramètre sont
  `/api/verdict` (`web/server.py:367`) et `/api/kdp-keywords` (`:398`), qui écrivent
  `UsageMeter(...).enregistrer("local", …)`. **À implémenter prochainement : création de compte classique
  email + mot de passe.** Rappel §5.14 : `user_id` dans `history.py` / `usage.py` / `jobs.py`
  uniquement, jamais dans `cache.py`.
- **Aucun endpoint ne sert le dossier de passation ni le guide utilisateur.** `tutoriel_pdf.py`
  est un script autonome.
- **Aucune base partagée, aucun Docker, aucun déploiement.** Quatre fichiers SQLite locaux.
- **Aucun test d'intégration réseau.**
