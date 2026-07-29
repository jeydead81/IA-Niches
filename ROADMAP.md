# ROADMAP — IA-Niches

Mise à jour : 2026-07-29 · branche `v2-refonte-ideator`.

**La source de vérité de ce fichier est le code** (`01-scripts/` et `web/`), pas la
documentation. `README.md` et `CLAUDE.md` sont tenus à la main : en cas de divergence avec le
code, c'est la doc qu'on corrige. `00-config/` a été supprimé au commit `eaa20b2`. Rien de ce qui
suit n'est écrit d'après ces fichiers.

Objectif produit : application vendue en abonnement, pas seulement un outil personnel. Le prix
de **~19 EUR/mois pour ~30 analyses** est une **estimation de cadrage établie en session de
travail** : il n'est écrit dans aucun fichier du dépôt. Le seul chiffre sourçable est
« à 30 analyses/mois la marge est de 88 % » (`01-scripts/usage.py:5`), et c'est lui-même une
projection de plan, pas une mesure. Tout ce document est classé par rapport à cet objectif.

---

## 1. État actuel

### 1.1 Ce qui est livré

Une application web locale mono-page : FastAPI (`web/server.py`, 427 lignes, 13 endpoints
`@app.` comptés dans le fichier) plus un unique `web/index.html` de 57 319 octets (CSS et JS
inline, zéro build). Depuis le commit `60e405a`, l'hôte et le port se règlent par `HOST` / `PORT`
(défauts inchangés : `127.0.0.1:8000`) ; un port figé empêchait deux instances et tout
hébergement.

**Une seule dépendance réseau tierce, à corriger avant vente** : `index.html:8` importe deux
polices depuis Google Fonts (`@import url('https://fonts.googleapis.com/css2?family=Fira+Code…')`).
Hors ligne, derrière un pare-feu ou sur un serveur sans sortie Internet, `--mono` / `--sans`
retombent sur les fallbacks système ; et chaque visite déclenche une requête vers un tiers.
Vérifié : le fichier ne contient que **deux** `https://`, celui-ci et le lien `amazon.fr/dp/` des
ASIN. Embarquer les polices en base64, ou assumer les polices système, est un correctif de
quelques minutes.

Deux moteurs indépendants :

| Moteur | Entrée | Sortie | Coût mesuré |
|---|---|---|---|
| Scout **non-fiction** (`scout_master.run_scout`) | une graine libre, ou rien | niches classées, 3 axes pondérés 0,4 / 0,4 / 0,2 | **0,030 $** en local (`BSR_SOURCE=scrape`) |
| Scout **fiction** (`fiction_master.run_fiction_scout`) | un sous-genre de la taxonomie | trios sous-genre × tropes × décor, avec saturation | **0,153 $** pour 3 trios |

Sources réelles, et elles seules : API Anthropic (`claude-sonnet-5` par défaut partout, en
tool-use forcé, jamais de parsing de texte libre), DataForSEO (Amazon Products SERP + Amazon
ASIN), l'autocomplete public `completion.amazon.fr` (gratuit) et le scraping direct de
`amazon.fr/dp/{asin}` (gratuit, IP résidentielle uniquement).

Le cœur économique est un **cache SQLite mutualisé entre tous les utilisateurs**
(`99-logs/df-cache.db`), dont les clés portent une empreinte SHA1 automatique du schéma pydantic
— ajouter un champ invalide le cache tout seul. Les **quatre** familles de clés que construit
`cache.py` sont désormais toutes couvertes : `book:`, `bsr:`, `search:`, et `clf:` depuis le
commit `7b79e77` (`_clf_schema_tag`), qui porte en plus un SHA1 du prompt système
du classifieur — durcir ce prompt n'avait aucun effet sur les livres déjà vus. Limite assumée :
l'empreinte suit les **noms** de champs, pas les types ni la sémantique ; changer le sens d'un
champ sans le renommer exige de vider le cache à la main. Trois autres bases SQLite locales :
`jobs.db`, `usage.db`, `history.db`.

**326 tests collectés exactement**, sur 41 fichiers `tests/test_*.py`
(`python -m pytest --collect-only`), aucune erreur de collecte. **Tous hors-ligne** : chaque
dépendance lourde (client Anthropic, provider DataForSEO, fetch HTTP, sonde autocomplete) est
injectable par paramètre. Il n'existe **aucun test d'intégration réseau**.

**Un module livré sans aucun chemin d'accès** : `01-scripts/tutoriel_pdf.py` (546 lignes,
16 tests dans `tests/test_tutoriel_pdf.py`) n'est importé par aucun module de `01-scripts/` ni de
`web/` — `server.py` n'importe que `positioning_pdf`. C'est un script autonome
(`python 01-scripts/tutoriel_pdf.py` régénère les deux PDF à la racine), et c'est le plus gros
orphelin du dépôt. Détail qui compte : ce sont ses constantes `COUTS` (10 lignes) et `ENV_VARS`
(8 lignes) qui portent les chiffres de coût et les 42 % de Haiku cités en 1.2 et 1.3. Le résidu
`REDDIT_*` de `ENV_VARS` a été **corrigé** au commit `0c467bb`, en même temps que `ENDPOINTS`,
passé de 11 à 13 entrées : deux tests de `test_tutoriel_pdf.py` lisent maintenant `web/server.py`
comme source de vérité, ce qui rend l'écart détectable au lieu d'être découvert à la relecture.
Ce n'est pas pour autant « la doc la plus à jour du projet » : c'est un générateur de PDF, tenu à
jour par ces tests, pas un miroir automatique du code.

### 1.2 Validé EN LIVE (argent réel, réseau réel)

Ces points ne reposent pas sur des mocks. Plusieurs ont été découverts précisément parce qu'un run
réel contredisait les tests.

- Coût d'un scout non-fiction : **0,030 $** en local. Coût d'un scout fiction : **0,153 $** pour
  3 trios.
- Coût d'un verdict éditorial à la pièce : **0,0283 $**. C'est cette mesure qui a fait passer
  `n_verdict` à 0 par défaut — 3 verdicts pesaient 78 % du coût d'un run, pour des analyses non
  lues.
- Coût des 7 mots-clés KDP : **~0,006 $**, mais c'est une **estimation**, sans run daté à
  l'appui. Elle est portée par le docstring de l'endpoint `mots_cles_kdp` dans `web/server.py`,
  et depuis `0c467bb` par une ligne de `tutoriel_pdf.COUTS` explicitement marquée `estime` —
  `01-scripts/kdp_keywords.py` ne contient aucun chiffre de coût. Ce que couvre le chiffre est en
  revanche exact : le LLM seul, la confirmation par autocomplete étant gratuite.
- Statut des dix lignes de `tutoriel_pdf.COUTS` : chacune porte sa mention, et **trois seulement**
  disent `mesuré` — scout non-fiction local, scout fiction 3 trios, analyse éditoriale. Les sept
  autres disent `calculé`, `extrapolé`, `estime`, `gratuit`, `local`, `lecture`, `one-shot`. Ne
  jamais promouvoir l'une de ces mentions en « mesuré ».
- Le code langue DataForSEO est `fr_FR` et non `fr` ; `location_code = 2250`.
- Parsing BSR : sans le lookahead `(?!\s+\w)`, « n°478 des titres gratuits … 5 en Livres » était
  lu **5** au lieu de **478**. Faux de deux ordres de grandeur, et silencieux.
- L'autocomplete est **préfixe-based** : sonder une expression de longue traîne donnait 0
  confirmation sur 7. D'où la sonde sur les 3 premiers mots (`kdp_keywords.amorce`).
- Budget de poll DataForSEO : à 16 polls (128 s), un ralentissement de la file a effacé un run
  entier — **3 SERP sur 3 expirées**. Porté à 40 polls (~320 s).
- Classifieur de quatrièmes de couverture : Haiku 4.5 mesuré à **42 % d'accord** humain/IA contre
  **80 % requis**. Ne pas rétrograder `FICTION_CLASSIFIER_MODEL`.
- Cas `non_mesurable` observé en réel sur « romance captif huis clos ». Balise « Livre 1 sur 1 »
  qui n'est pas une série, observée sur l'ASIN B0GN4G414V.

### 1.3 Validé en test unitaire SEULEMENT

À traiter comme non éprouvé tant qu'un run réel n'est pas passé dessus.

| Élément | État réel |
|---|---|
| `POST /api/jobs` et `/api/jobs/{id}/stream` (12 tests) | **aucun appelant dans `web/index.html`** (vérifié : zéro occurrence de `/api/jobs` dans le fichier). Le mécanisme asynchrone n'a jamais servi un utilisateur. Décompte exact : 9 des 14 tests de `tests/test_server_jobs.py` portent sur ces endpoints — les 5 autres testent `/api/usage`, `/api/verdict` (×2) et `/api/kdp-keywords` (×2) — plus 3 dans `tests/test_history.py`. Les 6 tests de `tests/test_jobs.py` couvrent le magasin `JobStore`, pas les endpoints. |
| Plafond `PLAFOND_ANALYSES_MENSUEL` | vérifié uniquement dans `POST /api/jobs` → jamais déclenché en pratique. |
| Compteur d'usage (`usage.db`) | `/api/scout` et `/api/fiction` dépensent **sans rien enregistrer**. Le bandeau « Ce mois-ci : N analyse(s) » reste donc **à 0 quoi que fasse l'utilisateur**. |
| `POST /api/verdict` | aucun appelant dans l'UI. |
| `POST /api/pdf` et `POST /api/kdp-keywords` | appelés par le JS, mais depuis les deux boutons générés à la fin de `verdictBlock(r)` (`web/index.html`), qui fait `if(!v) return ''`. Or `n_verdict=0` par défaut → `verdict` vaut toujours `None` → **boutons jamais rendus**. |
| `BSR_SOURCE=dataforseo` en conditions serveur | le chiffre de **0,084 $** par scout non-fiction est **calculé, pas mesuré en production**. |
| Scout fiction à 8 trios (0,409 $) | **extrapolé** depuis les 3 trios réellement mesurés. |
| `ScoredNiche.concurrence_mesuree` (commit `60e405a`) | garde-fou neuf, couvert par `tests/test_scoring.py` et `tests/test_history.py`, **jamais éprouvé sur un vrai solde épuisé**. Il coupe tout bonus et tout malus de concurrence quand la SERP n'a pas répondu, écrit « Concurrence non mesurée — à relancer » au lieu d'un verdict, affiche « — / Non mesurée » dans l'UI et exclut la niche de l'historique. Le bonus « place à prendre » (+1,5) reste appliqué : il repose sur le BSR, pas sur la SERP. |
| Delta d'historique | l'écriture est automatique sur **les deux chemins** depuis le commit `6c916fd` — les deux endpoints SSE et les deux runners de job appellent tous `_consigner_scout` / `_consigner_fiction` ; auparavant seul le SSE consignait, alors que le job est le chemin recommandé. Le bloc de lecture est atteignable côté non-fiction. Mais un delta suppose deux passages espacés sur la même niche : non observé en conditions réelles à ce jour. |

Deux fichiers de tests lisent `web/index.html` comme du texte (`test_ux_glossaire.py`,
`test_ux_kdp_historique.py`). Ils vérifient la **présence** des chaînes, pas leur
**atteignabilité** — c'est exactement ce qui a laissé passer les boutons morts ci-dessus.

---

## 2. Ce qui reste avant commercialisation

Classé par ordre de blocage. Rien en dessous du point 2.1 ne peut être facturé.

### 2.1 Comptes utilisateurs + authentification — BLOQUANT

Aucune authentification n'est branchée. Mais le cloisonnement n'est pas uniformément absent : il
faut distinguer trois états, sinon on sous-estime le chantier d'un côté et on le surestime de
l'autre.

Les repères ci-dessous citent des **noms** de fonctions et d'endpoints, pas des numéros de ligne :
`web/server.py` bouge à chaque commit et les références chiffrées y périment en silence.

| Appelant | État réel de `user_id` |
|---|---|
| `POST /api/jobs` | `body.get("user_id") or "local"` — **déjà pilotable par le client**, et propagé au runner (`_run_scout_job` / `_run_fiction_job`) puis à `_consigner_scout` / `_consigner_fiction` et à `UsageMeter.enregistrer` |
| `GET /api/usage`, `GET /api/history`, `GET /api/jobs` | paramètre de requête surchargeable, défaut `"local"` — `GET /api/usage?user_id=X` fonctionne aujourd'hui |
| `POST /api/verdict`, `POST /api/kdp-keywords` | littéral `"local"` en dur dans l'appel à `UsageMeter.enregistrer` — **vrai codage en dur** |
| `GET /api/scout`, `GET /api/fiction` | **aucun paramètre `user_id` dans la signature**, et `_consigner_scout(results)` / `_consigner_fiction(rapports)` appelés sans argument |

Conséquence : deux clients partageraient l'historique et le compteur d'analyses dès qu'ils
passent par l'UI, puisque l'UI n'emprunte que les deux endpoints SSE de la dernière ligne. La
file de jobs, elle, est déjà cloisonnable — mais aucun client ne l'utilise (voir 1.3).

Décision produit prise : **création de compte classique (email + mot de passe)**.

**Estimation d'effort, corrigée.** La colonne `user_id` existe bien dans les trois bases, et le
chemin asynchrone est déjà instrumenté de bout en bout depuis le commit `6c916fd`. En revanche,
le seul chemin que l'UI emprunte réellement — `/api/scout` et `/api/fiction` — exige de
**modifier deux signatures d'endpoint et deux appels**, pas de remplir une colonne existante.
Petit chantier, mais du code, pas de la configuration.

| Base | Cloisonnement |
|---|---|
| `history.db` (`history.py`) | **par utilisateur** |
| `usage.db` (`usage.py`) | **par utilisateur** |
| `jobs.db` (`jobs.py`) | **par utilisateur** |
| `df-cache.db` (`cache.py`) | **PARTAGÉ entre tous les comptes, définitivement** |

Le cache est mutualisé **par conception** (`cache.py:1`), pas par oubli : c'est ce qui évite de
repayer la même donnée quand deux clients cherchent le même rayon, et c'est l'économie principale
à l'échelle. **Consigne : ne jamais introduire `user_id` dans `cache.py`.** Le partage se fait en
coulisses, invisible pour l'utilisateur, et doit le rester.

Corollaire à traiter dans le même chantier : le compteur d'usage n'est alimenté que par
`/api/jobs`. Tant que l'UI passe par `/api/scout` et `/api/fiction` en SSE, facturer à l'analyse
est impossible — on ne compte rien.

### 2.2 L'interface n'expose pas ce que le backend sait déjà faire

Trois endpoints livrés, testés et utiles n'ont **aucun chemin d'accès** depuis l'interface :
`/api/verdict`, `/api/pdf`, `/api/kdp-keywords` (mécanisme détaillé en 1.3). C'est du travail déjà
payé qui ne rapporte rien. Sortir les deux boutons du bloc de verdict et donner un appelant à
`/api/verdict` est un chantier court à fort rendement.

**Symétrie fiction.** Le backend consigne les runs fiction dans l'historique par les deux chemins
(`_consigner_fiction`, appelé par l'endpoint SSE `GET /api/fiction` et par `_run_fiction_job`) :
la donnée est écrite, personne ne la lit. Côté non-fiction, l'historique est bien affiché
(`histslot` et `loadHistorique` dans `web/index.html`, en dehors du bloc de verdict). Côté
fiction, `renderFic` n'a **ni bloc d'historique, ni bouton « Mots-clés KDP »**.

Pour les mots-clés, le coût d'adaptation est **plus faible qu'annoncé jusqu'ici**.
`generer_mots_cles` (`kdp_keywords.py`) type son entrée en `ScoredNiche`, mais `build_user_prompt`
ne lit que **quatre champs** : `niche`, `requete_amazon`, `categorie`, `satellite_keywords` —
plus le paramètre `titre`. Aucun BSR, aucun `n_concurrents_cibles` : le fichier entier n'en
contient pas une occurrence (vérifié par recherche sur `bsr` et `n_concurrents`, zéro résultat).
Un `FictionNiche` fournit déjà requête, sous-genre et tropes ; il ne manque **aucune métrique de
concurrence**.
Deux options, non tranchées : projeter le trio vers un `ScoredNiche` partiel (quatre champs à
remplir), ou extraire un contrat d'entrée minimal commun aux deux moteurs.

### 2.3 Paiement (Stripe)

Non commencé. Aucune ligne de facturation, d'abonnement ou de webhook dans le dépôt : recherche
insensible à la casse de `stripe|webhook|billing|subscription` sur `01-scripts/` et `web/` — zéro
occurrence.

**Statut des chiffres de cette section : ESTIMATIONS DE CADRAGE, pas des mesures.** Aucune
transaction n'a jamais eu lieu, donc rien ici n'est mesurable par construction. Les valeurs
~0,52 EUR de frais Stripe par abonnement mensuel (1,4 % + 0,25 EUR sur 19 EUR), marge 88-94 % et
seuil de rentabilité à 1-2 clients viennent d'une analyse de session, **elles ne sont écrites dans
aucun fichier du dépôt**. Le seul chiffre sourçable dans le code est « à 30 analyses/mois la marge
est de 88 % » (`01-scripts/usage.py:5`), lui-même une projection de plan.

**Correction d'une affirmation fausse qui a circulé ici : « Stripe coûte plus cher que DataForSEO
+ Claude réunis » ne tient pas.** L'arithmétique, au coût de production (`BSR_SOURCE=dataforseo`,
0,084 $ le scout non-fiction) : 30 analyses = 2,52 $, soit ~2,30 EUR — **plus de quatre fois** les
~0,52 EUR de frais Stripe. Même en local (0,030 $), 30 analyses font 0,90 $ ≈ 0,82 EUR, déjà
au-dessus. En fiction (0,409 $ pour 8 trios, extrapolé), 30 analyses feraient 12,27 $. L'ancienne
formulation ne tenait qu'à très faible usage — de l'ordre de 10 analyses en local — et elle
s'appuyait sur le chiffre local, celui-là même que le « piège de coût » ci-dessous interdit
d'employer comme coût de production. Cohérence de contrôle : 88 % de marge à 30 analyses sur
19 EUR implique ~2,28 EUR de coût technique, ce qui recoupe le calcul de production. Tous ces
montants sont **calculés**, aucun ne sort d'une facture.

Formulation juste : **le coût technique domine les frais de transaction dès 7 analyses par mois
au coût de production** (0,52 / 0,077 = 6,8 ; le seuil serait de ~19 analyses au coût local, mais
c'est justement le chiffre qu'on s'interdit d'employer pour la production). Les frais Stripe ne
sont déterminants qu'à très faible usage. `CLAUDE.md` §1 porte le même seuil : s'ils divergent,
c'est qu'un des deux n'a pas été recalculé. Le levier de
marge reste double, et il faut les hiérarchiser par palier d'usage — conversion et réduction du
nombre de transactions (annuel plutôt que mensuel) d'un côté, coût technique par analyse de
l'autre. Ce dernier n'est pas « déjà réglé » : le cache mutualisé et les gates de coût le
contiennent, ils ne le suppriment pas.

**Piège de coût à ne jamais oublier en communication commerciale** : les 0,030 $ par scout
non-fiction supposent `BSR_SOURCE=scrape`, qui ne fonctionne que depuis une **IP résidentielle**
(le PC de Baptiste). En production sur serveur, Amazon bloque : il faut `BSR_SOURCE=dataforseo`,
soit **0,084 $ — chiffre CALCULÉ, jamais mesuré en production** (ligne « Scout non-fiction (BSR
serveur, payant) » de `tutoriel_pdf.COUTS`, marquée « calculé » à côté des lignes marquées
« mesuré »). Ne jamais citer le chiffre local comme coût de production, ni le chiffre serveur
comme une mesure.

### 2.4 Actions hors code, en attente

Aucun développement, mais elles bloquent tout run réel.

1. **Régénérer la clé API Anthropic** (`ANTHROPIC_API_KEY`) — exposée en clair dans un chat.
2. **Régénérer les identifiants DataForSEO** (`DATAFORSEO_LOGIN` / `DATAFORSEO_PASSWORD`) —
   exposés de la même façon. Rappel : `DATAFORSEO_PASSWORD` est le **mot de passe d'API**
   (app.dataforseo.com/api-access), pas celui du compte.
3. **Recharger le solde DataForSEO.** Sans solde : aucune SERP, aucun BSR serveur. Attention à ne
   pas en déduire que les scouts s'arrêtent — c'est faux pour le non-fiction, et l'invariant 6
   dit pourquoi. Chaque `provider.search()` lève, l'exception est **attrapée** dans
   `scout_master.run_scout`, la niche reste dans la liste avec `search=None`, la phase BSR devient
   un no-op faute d'ASIN, et `score_niche` tourne quand même sur toute la shortlist : le run rend
   une liste complète. Depuis `60e405a`, ces niches sortent avec `concurrence_mesuree=False`,
   sans bonus ni malus de concurrence, verdict « Concurrence non mesurée — à relancer », et ne
   sont pas consignées dans l'historique. Avant ce commit, `n_cibles == 0` déclenchait le bonus
   « moins de 10 concurrents » (+2) et la même situation sortait un « Intéressant » — 6,88 sur un
   `demand_score` de 7, chiffre **calculé depuis `score_niche`**, pas relevé sur un run. Seul le
   scout fiction s'arrête réellement (`return []` quand aucune niche ne survit).
4. **Supprimer et révoquer `SCRAPINGDOG_API_KEY`.** Le `.env` de la racine porte encore cette
   entrée alors que le provider est abandonné depuis la v2 (section 5). C'est la seule des quatre
   clés du fichier qui ne sert plus à rien : elle se retire sans rien casser. `.env.example` ne la
   mentionne déjà plus.

Note : `DATAFORSEO_LOGIN` et `DATAFORSEO_PASSWORD` ont pour défaut la chaîne vide
(`DataForSEOProvider.__init__`, `search_providers.py`). La construction du provider **ne casse
pas** ; l'échec ne survient qu'à l'appel HTTP. Un oubli de configuration ne se voit donc pas au
démarrage.

`.env.example` documente **onze** variables (commit `7b79e77`) — il en manquait six. Écart rouvert
depuis : `web/server.py` lit maintenant `HOST` et `PORT` (commit `60e405a`), qui n'y figurent pas.
Compte exact au disque : **treize** variables distinctes lues par `os.getenv` dans `01-scripts/`
et `web/`, onze documentées. Piège écrit noir sur blanc dans le fichier et qu'il faut répéter ici :
les identifiants de modèle valides portent le préfixe `claude-` (`claude-sonnet-5`,
`claude-opus-4-8`, `claude-fable-5`, `claude-haiku-4-5`), et **un identifiant absent de la grille
de `cost_tracker.py` est facturé 0,00 $** — le coût disparaît des rapports sans qu'aucune erreur
ne soit levée. Un coût invisible, pas un coût nul.

---

## 3. Pistes ensuite — NON DÉCIDÉES

Aucune de ces pistes n'est arbitrée. Elles sont listées pour qu'un repreneur ne les redécouvre
pas, pas pour qu'il les implémente.

- **Déploiement.** Aucun Docker, aucun serveur, aucune base partagée : les quatre SQLite sont des
  fichiers locaux dans `99-logs/`. Héberger impose au minimum `BSR_SOURCE=dataforseo` et une
  décision sur le stockage.
- **Marketplace anglophone.** `search_providers.py` porte déjà `DEFAULT_LOCATION = 2250` et
  `DEFAULT_LANGUAGE = "fr_FR"` en constantes, et `location_code` / `language_code` sont des
  paramètres du provider. Les exposer ouvrirait `amazon.com` / `.co.uk` / `.de` sans réécrire le
  provider — mais la taxonomie fiction, les prompts et le glossaire sont en français.
- **Le paramètre `signals`** de `run_scout` et de `ideate` traverse les signatures jusqu'au prompt,
  mais **aucun appelant ne le remplit** : il vaut toujours `None`. Le mode « à partir de rien » se
  réduit donc à « graine vide ». Le brancher rouvrirait le sujet abandonné en 5.
- **Le champ `NicheCandidate.risques`** est rempli par le LLM (`required` dans le schéma d'outil)
  et propagé nulle part : ni dans `NicheValidation`, ni dans `ScoredNiche`, ni dans le scoring, ni
  dans l'affichage. Champ mort : soit on l'affiche, soit on le retire.
- **L'axe 3 « compatibilité livre »** est figé à la constante `8.0` pour toute niche
  (`compatibilite = 8.0` dans `score_niche`, `scoring.py`). Il ne discrimine rien : le score
  global vaut toujours
  `demande*0,4 + penetration*0,4 + 1,6`, mécaniquement borné entre 2,4 et 9,6. Soit on
  l'implémente, soit on assume publiquement un score sur 2 axes.
- **Le critère « nombre de résultats Amazon ≤ 10 000 »** n'est pas seulement non codé, il est **non
  mesurable en l'état** : `SearchResult.total_items` vaut `len(items)` de la page de SERP, pas le
  total annoncé par Amazon.
- **Les exclusions métier** (saisonnier, religions à expertise pointue, politique contemporaine,
  borderline TOS, niches d'experts ultra-techniques) n'existent **que comme texte dans le prompt
  système** de l'ideator (bloc « CONTRAINTES NON-NÉGOCIABLES » de `niche_ideator.py`).
  Contrairement aux règles KDP et à la taxonomie fiction, elles ne sont **pas doublées côté code** :
  si le modèle désobéit, rien ne le rattrape.
- **Élargir la taxonomie fiction** au-delà des 6 sous-genres de
  `data/fiction_taxonomy_fr_v1.json`. Règle de gouvernance : sous la porte des 80 % d'accord, c'est
  la **taxonomie** qu'on corrige, pas le classifieur.
- **Nettoyage du dépôt — FAIT** (commit `eaa20b2`), plus une piste. Supprimés : `00-config/`,
  `02-veille-hebdo/` (10 fichiers suivis par git), `05-prompts/prompt-directeur-editorial.md` et
  `prompt-critique-strategique.md`, `99-logs/credits-log.csv`, `01-scripts/trends_fr.py`,
  `reddit_fr.py`, `news_fr.py`, et six paquets de `01-scripts/requirements.txt`.
  `03-niches-validees/` et `04-archives/` ont disparu aussi, mais ils étaient **vides et non
  suivis par git** : il n'y avait rien à nettoyer côté dépôt.
  **Nuance sur les six paquets, à ne pas retourner en consigne fausse** : `pytrends`, `praw` et
  `feedparser` étaient bel et bien importés — par `trends_fr.py`, `reddit_fr.py` et `news_fr.py`.
  Ils étaient morts **en cascade**, parce que ces trois modules étaient orphelins, pas parce que
  personne ne les importait. Seuls `pandas`, `beautifulsoup4` et `lxml` avaient réellement zéro
  occurrence. `openpyxl` est **conservé** : `fiction_validation.py` l'importe, et trois fichiers
  de tests aussi (voir section 5).
  Conservés volontairement, à ne pas confondre avec des oublis :
  `99-logs/validation-fiction-2026-07-21.xlsx` et `rapport-validation-classifieur-2026-07-21.json`
  (étalon-or du classifieur, ~0,32 $ et une heure de relecture humaine, toujours suivis par git),
  `05-prompts/prompt-onebooklab-template.md` (workflow manuscrit de Baptiste, hors de cet outil),
  `assets/hedgehog.ico`, et `launcher.py` + `IA-Niches.bat` (voir section 4).
  Le résidu `REDDIT_CLIENT_ID / _SECRET / _USER_AGENT` de `tutoriel_pdf.ENV_VARS` a été **retiré**
  au commit `0c467bb` et remplacé par `KDP_KEYWORDS_MODEL`. Aucun `os.getenv("REDDIT_*")` ne
  subsiste dans `01-scripts/` ni `web/` ; le préfixe `REDDIT_` ne survit plus que dans de la
  documentation (`README.md`, `CLAUDE.md`, ce fichier, une spec de `docs/superpowers/`) et dans le
  test qui interdit sa réapparition.

---

## 4. En sursis — décision non prise

`01-scripts/launcher.py` et `IA-Niches.bat`. Le `.bat` lance bien `python 01-scripts\launcher.py`,
donc **ce n'est pas du code mort** au sens strict. Son contenu est périmé : son docstring parle
encore d'un « orchestrateur complet (Plan 2) » à venir, et son menu à 3 entrées est antérieur à
l'UI web — il n'expose **ni le scout non-fiction complet, ni la fiction**.

**Le vrai risque n'est pas cosmétique, il est financier.** L'entrée 3 du menu s'annonce
« Idées de niches par l'IA (clé Anthropic, ~0,02€) » et `_do_niches()` appelle
`generate_niches(seed=seed, n=10)` puis `validate_niches(...)` (`01-scripts/launcher.py` ;
`niche_ideator.generate_niches` et `niche_validator.validate_niches` existent toujours tous les
deux, l'appel n'est donc pas mort à l'import).
C'est la première moitié du scout non-fiction : **un chemin de dépense Anthropic actif, atteignable
par un double-clic sur le raccourci bureau**, sans plafond, sans imputation d'usage, sans trace
dans `usage.db`. Les entrées 1 et 2 (autocomplete, BSR) sont bien gratuites.

Trois options, aucune retenue : le mettre à jour, le supprimer avec son `.bat`, ou faire pointer
`IA-Niches.bat` sur `IA-Niches-Web.bat`. **À trancher par Baptiste** — mais tant qu'il vit, c'est
une porte de dépense hors du garde-fou.

`assets/hedgehog.ico` : **aucun code ni aucun script du dépôt ne le charge.** Ni `IA-Niches.bat`
(7 lignes) ni `IA-Niches-Web.bat` (11 lignes) ne mentionnent d'icône, et il n'existe aucun `.lnk`
versionné. Les seules mentions sont documentaires : l'arborescence de `README.md`
(« Icône du raccourci Windows ») et la liste des fichiers conservés de `CLAUDE.md`. Le raccourci
Windows, s'il existe, vit sur le bureau de Baptiste, hors dépôt et hors vérification. Ne pas le
supprimer sans lui demander.

---

## 5. Abandonné explicitement — ce sont des choix, pas des oublis

Un repreneur qui lit les plans et specs historiques de `docs/superpowers/` croira que ces briques
existent ou restent à faire : ces fichiers datent de la conception et n'ont jamais été révisés.
`README.md`, lui, les liste correctement sous « Ce qui n'existe plus du tout » — il ne fait pas
partie du problème. Toutes ont été **retirées volontairement**.

| Abandonné | Pourquoi |
|---|---|
| **Scrapingdog** (provider Amazon tiers) et tout son appareil : `credits_tracker.py`, `MAX_CREDITS_PER_RUN`, plafond de crédits par run, mode dry-run au premier lancement, retry gate à 1 tentative / 5 s, compteur « crédits restants sur 1000 » | BSR non fiable et données de concurrence incomplètes. Remplacé par DataForSEO. **Aucun appel** : hors du docstring de `cost_tracker.py:2`, le mot n'apparaît nulle part dans `01-scripts/` ni `web/`. **Mais la clé n'est pas partie** : `SCRAPINGDOG_API_KEY` figure encore dans le `.env` de la racine — à supprimer et révoquer (§2.4, point 4). Le nom survit aussi dans trois fichiers de `docs/superpowers/` (deux plans, une spec), à lire comme des archives de décision, jamais comme l'état du produit ; ce dossier compte 13 fichiers suivis par git, les dix autres ne le mentionnent pas. Le seul garde-fou de dépense aujourd'hui est `PLAFOND_ANALYSES_MENSUEL`, et il n'est vérifié que dans `POST /api/jobs`. |
| **Rapports Excel `.xlsx`** du scout (onglets Synthèse / Métadonnées / Sponsorisés, mise en forme conditionnelle openpyxl) | Le livrable est une interface web, pas un fichier à ouvrir. Les résultats sortent en JSON (SSE ou job) et en PDF one-pager. **`openpyxl` reste une dépendance obligatoire** : `fiction_validation.py` l'importe (outil de développement, pas livrable) **et trois fichiers de tests aussi** — `test_fiction_validation.py:1`, `test_validate_classifier.py:1`, `test_build_validation_set.py:98`. Le retirer de `requirements.txt` casserait la collecte de 3 des 41 fichiers de tests. |
| **Google Trends** (`pytrends`), **Reddit** (`praw`), **Google News** (`feedparser`) | Signaux bruyants et mal corrélés à la demande sur Amazon, pour un coût de maintenance élevé. Remplacés par l'ideator LLM + la validation autocomplete gratuite. `trends_fr.py`, `reddit_fr.py` et `news_fr.py` ont été **supprimés** au commit `eaa20b2`, avec les trois paquets qu'ils étaient seuls à importer. Ne pas les recréer : le mode « à partir de rien » se traite par `signals` (section 3), pas par ces trois sources. |
| **TikTok**, sous toute forme — automatisé comme en saisie manuelle | Creative Center n'est pas scrapable de façon fiable, et une saisie manuelle avant chaque run contredit la promesse du produit : un bouton, un résultat. |
| **Le workflow humain en 5 phases** (validation humaine sur screenshots, analyse éditoriale, pré-production, post-production) | Remplacé par deux scouts automatiques et un verdict à la demande. Le prompt de `niche_verdict.py` interdit explicitement au modèle de réclamer des screenshots : il raisonne sur les métriques du scout. Rien de la phase 4 (sommaire, prompts OneBookLab, briefs de couverture) ni de la phase 5 (quatrième de couverture, fiche AIDA, 15 mots-clés à vérifier) n'existe en code. |
| **Le bonus « +1 zone d'expertise pharmacien »** | Non seulement non codé, mais **délibérément contredit** : le bloc « IMPARTIALITÉ » du prompt système de `niche_ideator.py` impose au modèle de ne privilégier aucun domaine et de ne rien supposer de l'expertise de l'auteur. Cohérent avec un produit vendu à d'autres auteurs qu'un pharmacien. |
| **Le malus « -2 risque KDP TOS »** | Non codé. Le champ `risques` existe mais n'est lu nulle part (voir section 3). |

---

## 6. Invariants à ne pas casser

Rappels courts : le détail vit dans les docstrings du code, qui sont la vraie documentation du
projet.

1. **La saturation est le seul score inversé** (haut = mauvais). Une jauge colorée uniformément
   ferait recommander exactement les pires niches.
2. **`non_mesurable` n'est pas `mort`.** Les deux affichent des zéros et disent le contraire à
   l'utilisateur : l'un invite à re-mesurer, l'autre à écarter la niche.
3. **Un rayon amputé n'est pas un rayon désert** : `FictionShelf.n_echecs > 0` doit rester visible,
   sinon une donnée manquante se lit « place à prendre ».
4. **Une sonde en panne n'est pas un signal absent** : les défauts sont pessimistes
   (`mesure=False`, `autocomplete_score=None`, `concurrence_mesuree=False`), jamais 0. Corollaire
   ajouté au commit `60e405a` : **un compteur à zéro faute de mesure ne doit jamais nourrir un
   bonus.** `n_concurrents_cibles == 0` sur une SERP qui n'a pas répondu déclenchait le bonus
   « moins de 10 concurrents » — l'absence de mesure lue comme « place à prendre ».
5. **Ne jamais passer `niche.rayon` à `est_payant_dans()`** : passer par
   `fiction_taxonomy.label_rayon()`. Le bug a déjà été commis, et il déclare une niche morte sans
   la moindre erreur.
6. **Un échec n'interrompt jamais un run, mais il est toujours compté.**
7. **Instance par appel, jamais à l'import**, pour Cache / JobStore / UsageMeter / NicheHistory.
8. **`load_dotenv()` avant les imports moteur** dans `web/server.py` : les défauts de modèle sont
   lus à l'import. Cet ordre a l'air d'un détail de style, il est load-bearing.
9. **Pas de `temperature` / `top_p` / `top_k`** sur `claude-sonnet-5` : toute valeur non-défaut
   renvoie une 400.
