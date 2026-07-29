# IA-Niches

Application web locale qui cherche des niches de livres sur **Amazon.fr** pour les auteurs KDP.
Une IA (Claude) propose des niches, l'**autocomplete Amazon** (gratuit) filtre celles que personne
ne cherche, puis **DataForSEO** ne paie la concurrence et les BSR que sur les survivantes. Deux
moteurs indépendants : **non-fiction** (niche + requête + score sur 3 axes) et **fiction**
(trios sous-genre x tropes x décor, avec lecture des quatrièmes de couverture). Sortie : une liste
de niches classées, le coût réel du run en dollars, et des fonctions à la demande (verdict
éditorial, PDF, mots-clés KDP, historique).

> **La source de vérité de ce projet est le code** (`01-scripts/`, `web/`). `CLAUDE.md` et
> `ROADMAP.md` décrivent la v2 et sont tenus à la main : en cas de divergence, le code a raison
> et c'est la doc qu'on corrige. **Ne pas supprimer `CLAUDE.md`** : **18 emplacements du code
> vivant** (12 docstrings, 6 commentaires) citent ses sections comme normatives (`grep -rn CLAUDE 01-scripts web tests`, comptage
> exhaustif sur ces trois dossiers) — 10 dans `01-scripts/` (`niche_verdict.py`, `models.py` ×3,
> `history.py`, `kdp_keywords.py`, `fiction_scoring.py`, `fiction_serp_provider.py`,
> `fiction_validation.py`, `fiction_master.py`), 1 dans `web/server.py`, 2 dans `web/index.html`
> et **5 dans `tests/`** (`test_fiction_scoring.py`, `test_fiction_serp_provider.py`,
> `test_kdp_keywords.py`, `test_server_fiction.py`, `test_ux_kdp_historique.py`). Les dossiers v1
> ont disparu, mais **pas de la même façon** : `00-config/` et `02-veille-hebdo/` ont été
> supprimés par le commit `eaa20b2` ; `03-niches-validees/` et `04-archives/` étaient **vides et
> n'ont jamais été versionnés** — git ne suit pas les dossiers vides, aucun commit ne peut donc
> les avoir supprimés.

---

## 1. Sécurité — à lire avant tout

- Les clés API (**Anthropic**, **DataForSEO**) vivent **uniquement dans `.env`**, exclu de git
  (`.gitignore` ligne 4 ; la ligne 5 exclut aussi `.env.*`, la ligne 6 ré-inclut `.env.example`).
  Ne jamais coller une clé dans un fichier suivi, ni dans un test.
- `.env.example` documente **11** variables, sans secret. C'est le seul `.env*` versionné. Le code
  en lit en réalité **13** : `HOST` et `PORT` (ajoutées en `60e405a`, lues par le `__main__` de
  `web/server.py`) n'y figurent pas.
- Les bases SQLite d'exécution (`99-logs/*.db`) sont ignorées par git (`.gitignore` lignes 47-54) :
  elles contiennent des données d'usage réelles et le cache payant.
- Les données de runs de la v1 ont été supprimées du dépôt : `eaa20b2` supprime **18** fichiers —
  dont les 10 de `02-veille-hebdo/` et `99-logs/credits-log.csv` — et en **modifie un**
  (`01-scripts/requirements.txt`, réécrit et non supprimé). Le « 19 files changed » du pied de page
  de `git show --stat` additionne les deux : ne pas le lire comme 19 suppressions. Restent **deux**
  fichiers suivis dans `99-logs/` — `validation-fiction-2026-07-21.xlsx` et
  `rapport-validation-classifieur-2026-07-21.json` : c'est l'étalon-or du classifieur fiction
  (0,32 $ d'API et une relecture humaine), **conservé délibérément**, à ne pas confondre avec un
  résidu.
- **Avant toute mise en vente ou passage du dépôt en public** :
  1. **Régénérer la clé Anthropic** (console.anthropic.com) et **le mot de passe d'API DataForSEO**
     (app.dataforseo.com/api-access). Elles ont vécu en local sur un poste de travail.
  2. **Supprimer et révoquer `SCRAPINGDOG_API_KEY`** du `.env` de la racine : le produit
     n'appelle plus ce service depuis la v2, la clé n'y sert plus à rien. Elle n'a jamais fuité
     par le dépôt (`.env` n'a jamais été versionné, `git log --all -- .env` ne rend aucun commit),
     mais une clé tierce qui traîne se révoque.
  3. Envisager une réécriture d'historique (`git filter-repo`) si une clé a transité un jour dans
     un commit. Les fichiers supprimés en `eaa20b2` (`00-config/`, `02-veille-hebdo/`, les trois
     modules v1) restent lisibles dans l'historique git. Rien à purger en revanche pour
     `03-niches-validees/` ni `04-archives/` : ils n'y ont jamais été.
  4. Détail sans risque : les lignes 32-34 de `.gitignore` commentent encore des chemins qui
     n'existent plus (`99-logs/credits-log.csv`, `02-veille-hebdo/…`).
- Aucune authentification n'est branchée aujourd'hui (voir §10). Ne pas exposer le serveur sur
  une IP publique en l'état.

---

## 2. Installation

```bash
pip install -r 01-scripts/requirements.txt
cp .env.example .env       # puis remplir (voir tableau ci-dessous)
```

Python 3.10+ (le code utilise `int | None`). Aucun build front, aucun Docker, aucune base externe :
tout est local — **à une exception près**, l'import de polices Google dans `web/index.html` (§3).

`requirements.txt` ne contient plus que des paquets **réellement importés** : `requests`,
`python-dotenv`, `pydantic`, `anthropic`, `fastapi`, `uvicorn`, `fpdf2`, `openpyxl`, `pytest`.
Six paquets de la v1 ont été retirés en `eaa20b2`, pour deux raisons distinctes qu'il ne faut pas
confondre : `pytrends`, `praw` et `feedparser` étaient bel et bien importés — par
`trends_fr.py` / `reddit_fr.py` / `news_fr.py`, supprimés dans le même commit, donc morts **en
cascade** ; `pandas`, `beautifulsoup4` et `lxml` n'avaient, eux, **aucune occurrence** (le parsing
des fiches Amazon se fait en expressions régulières pures, cf. `amazon_product.py`). `openpyxl`
est **conservé** : importé par `01-scripts/fiction_validation.py` **et** trois fichiers de tests
(`test_build_validation_set.py`, `test_fiction_validation.py`, `test_validate_classifier.py`).

### Variables d'environnement — les 13 lues par le code

Décompte exhaustif : `os.getenv` est le seul mécanisme de lecture (aucun `os.environ` dans
`01-scripts/` ni `web/`), et il rend 13 noms distincts.

**Obligatoires**

| Variable | Défaut | Rôle |
|---|---|---|
| `ANTHROPIC_API_KEY` | aucun (`None`) | Toute la partie IA : les deux ideators, le classifieur de quatrièmes, le verdict, les mots-clés KDP. |
| `DATAFORSEO_LOGIN` | `""` | Compte DataForSEO (SERP Amazon + fiches ASIN). |
| `DATAFORSEO_PASSWORD` | `""` | **Mot de passe d'API** (app.dataforseo.com/api-access), **pas** celui du compte web. |

Les défauts vides ne font pas échouer le démarrage : l'échec survient au premier appel HTTP.

**Optionnelles**

| Variable | Défaut | Rôle |
|---|---|---|
| `BSR_SOURCE` | `scrape` | `scrape` = fiche amazon.fr grattée gratuitement depuis l'IP locale. `dataforseo` = batché, payant, fiable en datacenter. Toute autre valeur lève `ValueError`. |
| `DATAFORSEO_PRIORITY` | `2` | `2` = file rapide (~1-4 min, 0,003 $/appel). `1` = file standard, moitié prix, jusqu'à ~45 min. Valeur invalide -> avertissement + repli sur 2. |
| `PLAFOND_ANALYSES_MENSUEL` | non défini = illimité | Plafond glissant sur 30 jours par utilisateur. Vérifié **uniquement** par `POST /api/jobs`. Valeur non entière -> illimité, silencieusement. |
| `IDEATOR_MODEL` | `claude-sonnet-5` | Ideator non-fiction. |
| `VERDICT_MODEL` | `claude-sonnet-5` | Verdict éditorial. |
| `KDP_KEYWORDS_MODEL` | `claude-sonnet-5` | Mots-clés backend KDP. |
| `FICTION_IDEATOR_MODEL` | `claude-sonnet-5` | Ideator fiction (trios). |
| `FICTION_CLASSIFIER_MODEL` | `claude-sonnet-5` | Classifieur de quatrièmes. **Ne pas rétrograder** : Haiku 4.5 mesuré à 42 % d'accord contre 80 % requis. |
| `HOST` | `127.0.0.1` | Lue par le bloc `__main__` de `web/server.py` uniquement (pas par `uvicorn server:app`). |
| `PORT` | `8000` | Idem. Valeur non entière -> repli silencieux sur 8000. Ajoutée en `60e405a` : un port figé empêchait deux instances et tout hébergement. |

Les 11 premières sont exactement celles que `.env.example` documente depuis `7b79e77` — il n'en
listait que 5, plus trois `REDDIT_*` désormais disparues avec le module qui les lisait. `HOST` et
`PORT` sont lues par le code mais **absentes de `.env.example`** : à y ajouter.

**Piège de facturation** : un identifiant de modèle absent de la grille de `cost_tracker.py` est
facturé **0,00 $** — un coût invisible, pas un coût nul. Les quatre identifiants tarifés portent
le préfixe `claude-` : `claude-sonnet-5` (2 $/10 $ par million de tokens in/out en tarif intro
**jusqu'au 31/08/2026**, puis 3 $/15 $ — la bascule est automatique, dans `llm_cost_usd`),
`claude-opus-4-8` (5 $/25 $), `claude-fable-5` (10 $/50 $), `claude-haiku-4-5` (1 $/5 $).

**Piège de démarrage** : les défauts de modèle sont lus **à l'import**, donc avant le
`load_dotenv()` que `scout_master.py` appelle à l'intérieur de `run_scout()`. Un `IDEATOR_MODEL`
défini uniquement dans `.env` est **ignoré en ligne de commande**. `web/server.py` y échappe parce
qu'il appelle `load_dotenv` (ligne 24) **avant** ses imports moteur — cet ordre est load-bearing,
ne pas le « ranger ».

---

## 3. Lancement

### Interface web (usage normal)

```bash
python web/server.py          # ou double-clic sur IA-Niches-Web.bat
```

Ouvre `http://127.0.0.1:8000` — adresse et port surchargeables par `HOST` / `PORT` (§2), défauts
inchangés. Page unique (`web/index.html`, 57 319 octets, CSS + JS inline, zéro build, aucun
`<script src>` ni `<link>`) : formulaire non-fiction, panneau fiction, progression en direct (SSE),
tableau de niches dépliable, glossaire contextuel.

**Une seule ressource tierce subsiste** : `web/index.html:8` fait un
`@import url('https://fonts.googleapis.com/css2?…')` pour Fira Sans et Fira Code. Chaque ouverture
émet donc une requête vers Google. La page reste fonctionnelle hors ligne (les deux variables CSS
portent un repli : `system-ui,sans-serif` et `ui-monospace,monospace`), mais l'application n'est
pas strictement locale tant que cet import est là.

Endpoints exposés par `web/server.py` (13) : `GET /`, `GET /api/scout`, `GET /api/fiction`,
`GET /api/fiction/sous-genres`, `POST /api/jobs`, `GET /api/jobs`, `GET /api/jobs/{id}`,
`GET /api/jobs/{id}/stream`, `GET /api/usage`, `POST /api/verdict`, `GET /api/history`,
`POST /api/kdp-keywords`, `POST /api/pdf`.

Deux façons de lancer un run, à ne pas confondre :

- `GET /api/scout` et `GET /api/fiction` : SSE **attaché à la requête HTTP**. Fermer l'onglet tue
  le flux et perd le résultat d'un run déjà payé. Ne vérifient pas le plafond, n'enregistrent rien
  dans `usage.db`. Ils consignent en revanche l'historique (`_consigner_scout` /
  `_consigner_fiction`).
- `POST /api/jobs` (+ `GET /api/jobs/{id}/stream`) : job détaché, écrit dans `jobs.db`, **SSE
  reconnectable** qui rejoue la progression depuis le début. **Seul chemin qui vérifie le plafond**
  (429 si atteint) et le seul qui impute une analyse (`n_analyses=1`, imputé même quand le job
  échoue) — `POST /api/verdict` et `POST /api/kdp-keywords` écrivent eux aussi dans `usage.db`, mais avec
  `n_analyses=0` : leur coût compte, pas leur quota. À privilégier pour la fiction (10-15 min).
  Il accepte deux jeux de noms de paramètres (`n_ideas`/`n_search` **et** `ideas`/`search`),
  volontairement, après une divergence constatée en live. Depuis `6c916fd`, ses deux runners
  reçoivent le `user_id` **et** consignent l'historique : recommander ce chemin sans qu'il
  alimente l'historique vidait la fonction de sa substance.

### Ligne de commande

```bash
# Scout non-fiction (défauts : --ideas 12, --search 6)
python 01-scripts/scout_master.py --seed "ésotérisme"
python 01-scripts/scout_master.py                              # mode "graine vide"
python 01-scripts/scout_master.py --seed "sommeil" --ideas 15 --search 8

# Scout fiction (défauts : --n-niches 8, --rayon kindle)
python 01-scripts/fiction_master.py --sous-genre cosy_mystery
python 01-scripts/fiction_master.py --sous-genre dark_romance --n-niches 5 --rayon papier

# Canaux gratuits, smoke test (0 $)
python 01-scripts/demo_free.py --suggest "tarot"
python 01-scripts/demo_free.py --bsr 2266283340

# Régénère les deux PDF à la racine (passation + guide utilisateur)
python 01-scripts/tutoriel_pdf.py

# Outillage dev du classifieur fiction (--sous-genre est REQUIS : sans lui, argparse
# sort en SystemExit 2. Défauts : --n-niches 5, sortie validation-fiction-<date>.xlsx)
python 01-scripts/build_validation_set.py --sous-genre cosy_mystery
python 01-scripts/validate_classifier.py <fichier.xlsx>
```

**Aucune de ces commandes CLI ne consigne l'historique** : `_consigner_scout` /
`_consigner_fiction` vivent dans `web/server.py`, pas dans les orchestrateurs. Un suivi d'évolution
n'existe donc que pour les runs lancés depuis l'interface web ou l'API.

Sous-genres fiction valides (`data/fiction_taxonomy_fr_v1.json`, version `fr_v1`) :
`cosy_mystery`, `thriller_psychologique`, `romantasy`, `romance_contemporaine`, `dark_romance`,
`feel_good`. C'est la source unique : `GET /api/fiction/sous-genres` la sert à l'UI, rien n'est
dupliqué en dur côté JS.

`01-scripts/launcher.py` (lancé par `IA-Niches.bat`) est un menu CLI **antérieur à l'UI web** :
3 entrées (suggestions, BSR, idées de niches), il n'expose ni le scout non-fiction complet ni la
fiction. **Conservé, sort à trancher** — et ce n'est pas un fichier inerte : l'entrée 3 appelle
`niche_ideator.generate_niches` puis `niche_validator.validate_niches`, c'est-à-dire un vrai appel
Anthropic payant, annoncé « ~0,02 € » par le menu lui-même. Supprimer ou moderniser, en le sachant.

---

## 4. Les deux moteurs

### Scout non-fiction — `01-scripts/scout_master.py`

**Produit** : des `ScoredNiche` classées — niche, requête Amazon courte, mots-clés satellites,
score global /10, axes *demande* / *pénétration* / *compatibilité*, critères BSR §4.1 (oui/non),
BSR du top, nombre de concurrents réellement ciblés, nombre de sponsorisés écartés, et le drapeau
`concurrence_mesuree`.

**Chaîne** : ideator LLM (1 appel, tool-use forcé) → validation autocomplete Amazon (gratuit) →
**gate de coût** : seules les `n_search` premières niches validées passent à l'étape payante →
SERP DataForSEO par niche → BSR des 3 premiers ASIN organiques, résolus en **un seul batch
global** → scoring (fonctions pures).

**Ce que « sponsorisés écartés » veut dire exactement** : la séparation organique / `amazon_paid`
se fait à la source (`search_providers.py`), et aucun résultat sponsorisé ne fournit d'ASIN pour
les BSR ni n'entre dans le comptage des concurrents ciblés. Leur **nombre**, lui, est bel et bien
compté : `score_niche` ajoute **+0,5** à l'axe pénétration à partir de 3 sponsorisés (beaucoup de
sponso = concurrence organique plus faible), et `n_sponsored` est exposé et affiché. Lire « jamais
comptés » au pied de la lettre rend un écart de 0,5 point incompréhensible.

**Quand la SERP tombe** (solde DataForSEO épuisé, file en panne), le run ne s'arrête pas — mais
depuis `60e405a` il ne ment plus. `ScoredNiche.concurrence_mesuree` (défaut pessimiste `False`)
neutralise **tout** bonus et malus de concurrence, le verdict devient
« Concurrence non mesurée — à relancer », l'UI affiche « — / Non mesurée » avec une alerte qui
nomme la cause probable, et la niche n'est **pas** consignée dans l'historique (un point qu'on
sait faux produirait au passage suivant un delta spectaculaire et mensonger). Avant ce correctif,
`n_concurrents_cibles = 0` déclenchait le bonus « moins de 10 concurrents » (+2 en pénétration) :
une niche dont rien n'avait été mesuré ressortait à 6,88 « Intéressant ». **Nuance** : le bonus
« place à prendre » (+1,5) reste appliqué sans SERP — il repose sur le BSR, pas sur la SERP.

**Durée** : 2 à 7 minutes selon la charge de DataForSEO.
**Coût** : 0,030 $ mesuré en local (`BSR_SOURCE=scrape`), 0,084 $ calculé sur serveur.

Le verdict IA n'est **pas** généré pendant le run (`n_verdict=0` par défaut, en CLI comme côté
serveur) : 3 verdicts pré-générés pesaient 78 % du coût pour des textes rarement lus.

### Scout fiction — `01-scripts/fiction_master.py`

**Produit** : des `FictionNicheReport` — un trio sous-genre x tropes x décor, avec `depth_score`
(profondeur du rayon), `openness_score` (ouverture), `saturation_trio` (couverture du trio par les
concurrents, calculée en **lisant les quatrièmes de couverture**), une matrice de demande à
6 issues et un verdict textuel qui porte ses réserves.

**Chaîne** (6 étapes A-F, conformément au docstring d'en-tête de `fiction_master.py`) : ideator contraint à
la taxonomie (tout trio hors taxonomie est écarté côté code) → une SERP par niche → **un seul batch ASIN pour tout le run** → classification des
blurbs par lots de 20 → sonde autocomplete à deux barreaux → reconstruction des rayons + scoring.

Le batch ASIN unique est la raison d'être du module : la file DataForSEO met ~250 s **quel que
soit** le nombre d'ASIN. La payer une fois par run au lieu d'une fois par niche fait passer
10 niches de 42 min à 5 min.

**Durée** : 10 à 15 minutes (869 s mesurés sur 3 trios, chiffre repris de
`docs/superpowers/plans/2026-07-21-saas-jobs-et-compteur.md` et du guide utilisateur).
**Coût** : 0,153 $ mesuré pour 3 trios, 0,409 $ extrapolé pour 8 trios.

**Piège de lecture** : `saturation_trio` est le **seul score inversé** — élevé = mauvais. Une jauge
colorée comme les autres ferait recommander exactement les pires niches.

---

## 5. Fonctions à la demande

| Fonction | Endpoint | Coût | État |
|---|---|---|---|
| Verdict éditorial d'une niche (Go / Go prudent / No-Go, confiance /10, facteur décisif, 2-3 angles d'attaque, critique stratégique) | `POST /api/verdict` | 0,028 $ | Sans état : la niche entière est passée dans le body. **Aucun appelant dans l'UI livrée.** |
| PDF de positionnement (one-pager) | `POST /api/pdf` | 0 $ | Rendu à la volée, aucune persistance serveur. Bouton présent mais inatteignable (§10). |
| 7 mots-clés backend KDP | `POST /api/kdp-keywords` | ~0,006 $ (estimé) | ~22 candidats proposés par le LLM, règles KDP vérifiées **côté code** (50 caractères, termes proscrits, chevauchement avec le titre, doublons, motif de rejet lisible), puis confirmation **gratuite** par l'autocomplete Amazon. Bouton inatteignable (§10). |
| Historique et évolution d'une niche | `GET /api/history` | 0 $ | Enregistré automatiquement par les deux endpoints SSE **et** par `POST /api/jobs` — mais **jamais par les deux CLI**, et **jamais pour une niche non-fiction dont la SERP a échoué** (`concurrence_mesuree=False`, §4). Une seule mesure -> `delta: null` avec un **200** : « pas encore de recul » est une réponse, pas une erreur. Seuil de significativité 0,10. Seule des trois fonctions ci-dessus à être réellement atteignable dans l'UI (le bloc `.histslot` est rendu hors de `verdictBlock`, au dépliage de la ligne). |
| Consommation du mois glissant | `GET /api/usage` | 0 $ | Fenêtre de 30 jours, ni calendaire ni cumulative à vie. |

---

## 6. Coûts

Les lignes marquées **mesuré** viennent de runs réels du 2026-07-21 et sont reprises telles quelles
de la table `COUTS` de `01-scripts/tutoriel_pdf.py`. Les autres sont **calculées**, **extrapolées**
ou **estimées** — la colonne « Origine » est la seule chose qui distingue un chiffre relevé d'un
chiffre déduit, ne pas la lire c'est se tromper de tarification. Colonne « standard » =
`DATAFORSEO_PRIORITY=1` : moitié prix sur la donnée, mais jusqu'à ~45 min d'attente.

| Demande | priority (défaut) | standard | Origine |
|---|---|---|---|
| Scout non-fiction, BSR local (`scrape`) | 0,030 $ | 0,021 $ | mesuré |
| Scout non-fiction, BSR serveur (`dataforseo`) | **0,084 $** | 0,048 $ | calculé |
| Scout fiction, 3 trios | 0,153 $ | 0,113 $ | mesuré |
| Scout fiction, 8 trios | 0,409 $ | 0,299 $ | extrapolé |
| Verdict éditorial (1 niche) | 0,028 $ | 0,028 $ | mesuré |
| Mots-clés KDP (1 niche) | ~0,006 $ | ~0,006 $ | **estimé** — ordre de grandeur repris du docstring de `api_kdp_keywords` ; présent dans `COUTS` depuis `0c467bb`, mais explicitement marqué « estime » : aucune mesure datée |
| Sonde autocomplete | 0 $ | 0 $ | endpoint public |
| PDF, historique, consultation d'un job | 0 $ | 0 $ | local |
| Set de validation du classifieur (50 livres) | 0,32 $ | — | one-shot |

**PIÈGE `BSR_SOURCE` — ne jamais citer le chiffre local comme coût de production.** Le défaut
`scrape` lit les fiches `amazon.fr/dp/{asin}` depuis une **IP résidentielle**. Depuis un datacenter,
Amazon bloque : il faut `BSR_SOURCE=dataforseo`, et le scout non-fiction passe de 0,030 $ à
**0,084 $**, soit ×2,8.

Le coût réel (appels DataForSEO + tokens LLM) est affiché en fin de run, en CLI comme dans l'UI.
Le **cache SQLite mutualisé** (`99-logs/df-cache.db`, TTL : BSR 3 j, livre 7 j, SERP 10 j,
classification 30 j) est l'économie principale à l'échelle : deux utilisateurs qui analysent le
même rayon ne le paient qu'une fois. Ce partage est **délibéré**, pas un oubli de cloisonnement.
Les **quatre** familles de clés portent une empreinte SHA1 du schéma pydantic — `book:`, `bsr:`,
`search:` et, depuis `7b79e77`, `clf:`, qui cumule empreinte de schéma **et** empreinte du prompt
système du classifieur (`Cache._clf_key`). Ajouter un champ invalide automatiquement les entrées ;
sans cela, `clf:` servait pendant **30 jours** des objets amputés. Limite assumée :
l'empreinte suit les **noms** de champs, pas leur sémantique — changer le sens d'un champ sans le
renommer exige de vider le cache à la main.

---

## 7. Structure du dépôt

Les dossiers v1 ont disparu : `00-config/` et `02-veille-hebdo/` **supprimés** par le commit
`eaa20b2`, `03-niches-validees/` et `04-archives/` simplement effacés du disque — ils étaient
vides et n'ont jamais été versionnés. `05-prompts/` subsiste avec **un seul** fichier,
`prompt-onebooklab-template.md` : il sert le workflow manuscrit de Baptiste, hors de cet outil, et
n'est importé par aucun module.

L'arbre ci-dessous liste **les 32 modules de `01-scripts/`** sans exception, y compris ceux qui ne
sont pas dans le chemin nominal.

```
├── 01-scripts/                # Le moteur
│   ├── scout_master.py            # Orchestrateur non-fiction
│   ├── fiction_master.py          # Orchestrateur fiction (6 étapes, batch ASIN unique)
│   ├── models.py                  # Tous les types pydantic + la logique métier subtile
│   ├── scoring.py / fiction_scoring.py   # Scoring, 100 % de fonctions pures
│   ├── niche_ideator.py / fiction_ideator.py   # Génération LLM (tool-use forcé)
│   ├── niche_validator.py / amazon_autocomplete.py / fiction_autocomplete.py  # Demande, gratuit
│   ├── search_providers.py        # DataForSEO (SERP + ASIN batché) + parseurs BSR
│   ├── bsr_source.py / amazon_product.py  # BSR : scrape gratuit ou DataForSEO payant
│   ├── fiction_serp_provider.py / fiction_books.py / fiction_classifier.py / fiction_taxonomy.py
│   ├── niche_verdict.py / kdp_keywords.py / positioning_pdf.py   # Fonctions à la demande
│   ├── cache.py / cost_tracker.py / jobs.py / usage.py / history.py   # Infrastructure
│   ├── util.py                    # HTTP avec en-têtes navigateur
│   ├── tutoriel_pdf.py            # Générateur des 2 PDF racine (13 endpoints depuis 0c467bb)
│   ├── demo_free.py               # Smoke test des canaux gratuits (0 $)
│   ├── launcher.py                # Menu CLI antérieur à l'UI web — l'entrée 3 dépense (§3)
│   ├── requirements.txt
│   └── fiction_validation.py, build_validation_set.py, validate_classifier.py  # Outillage dev
├── web/
│   ├── server.py                  # FastAPI, 13 routes @app, 427 lignes
│   └── index.html                 # UI complète en un fichier (57 319 octets)
├── data/fiction_taxonomy_fr_v1.json   # 6 sous-genres : source de vérité unique
├── tests/                         # 326 tests sur 41 fichiers, tous hors-ligne
├── docs/
│   ├── spike_fiction_M0.md            # Spike de conception du moteur fiction
│   └── superpowers/plans/ (12) · specs/ (1)   # Plans TDD ; cités depuis le code et les tests
│                                              # (ex. docstring de tests/test_ux_glossaire.py)
├── 05-prompts/prompt-onebooklab-template.md   # Workflow manuscrit, hors outil
├── 99-logs/                       # 4 bases SQLite locales, git-ignorées (+ .db-wal/.db-shm)
│   ├── df-cache.db · jobs.db · usage.db · history.db
│   ├── validation-fiction-2026-07-21.xlsx           # SUIVI par git : étalon-or du classifieur
│   └── rapport-validation-classifieur-2026-07-21.json   # SUIVI par git
├── assets/hedgehog.ico            # Icône du raccourci Windows
├── .env / .env.example
├── pytest.ini · .gitattributes · .gitignore · LICENSE
├── CLAUDE.md · ROADMAP.md · README.md
├── IA-Niches-Web.bat              # Lance le serveur + ouvre le navigateur
├── IA-Niches.bat                  # Lance launcher.py (menu CLI antérieur à l'UI web)
├── IA-Niches - Dossier de passation.pdf   # Généré par tutoriel_pdf.py
└── IA-Niches - Guide utilisateur.pdf      # idem
```

Le code est **massivement auto-documenté** : les docstrings contiennent les pièges métier mesurés
en live (BSR Kindle vs papier non comparables, titres gratuits exclus, lookahead « en Livres »,
`label_rayon`, autocomplete préfixé…). C'est la vraie documentation du projet.

`tutoriel_pdf.py` n'en fait pas partie : c'est un **générateur de PDF**, pas une source de vérité.
Il documentait 11 endpoints sur 13 et citait encore les `REDDIT_*` ; corrigé en `0c467bb`, il
couvre les 13 endpoints, cite `KDP_KEYWORDS_MODEL` et porte une ligne mots-clés KDP marquée
« estime ». Il est désormais **tenu à jour par deux tests** qui lisent le code au lieu de figer une
liste : `test_le_dossier_de_passation_couvre_TOUS_les_endpoints_reels` (lit `web/server.py`) et
`test_le_dossier_de_passation_ne_cite_que_des_variables_encore_lues` (balaie `01-scripts/*.py` et
`web/server.py`). Les deux PDF de la racine ont été régénérés.

---

## 8. Tests

```bash
python -m pytest                    # depuis la racine — 326 passed en 4,08 s (mesuré)
python -m pytest --collect-only     # 326 tests collected, 41 fichiers, 0 erreur de collecte
```

`pytest.ini` fixe `pythonpath=01-scripts`, `testpaths=tests`, `python_files=test_*.py`,
`addopts=-q`. **Les 326 tests sont tous hors-ligne** : chaque dépendance lourde (client Anthropic,
provider DataForSEO, fetch HTTP, sonde autocomplete) est injectable par paramètre. Aucune clé API
n'est nécessaire pour les faire passer. Deux fichiers (`test_ux_glossaire.py`,
`test_ux_kdp_historique.py`) testent l'interface en lisant `web/index.html` comme du texte — ils
vérifient la **présence** des chaînes, jamais leur atteignabilité (§10).

---

## 9. Invariants à ne pas casser

- **Un échec n'interrompt jamais un run, mais il est toujours compté.** SERP en échec -> niche
  scorée sans concurrence **et marquée `concurrence_mesuree=False`** (aucun bonus/malus de
  concurrence, verdict « non mesurée », pas de consignation dans l'historique) ; ASIN non enrichi ->
  `n_echecs` incrémenté et annoncé ; niche fiction en échec -> écartée, rayons déjà payés
  conservés ; job en échec -> le coût engagé reste imputé.
- **Une sonde en panne n'est pas un signal absent.** `AutocompleteSignal.mesure` a un défaut
  pessimiste `False`, `autocomplete_score` rend `None` et non `0.0`. Confondre les deux fait
  déclarer morte une niche qu'on n'a simplement pas mesurée.
- **`non_mesurable` n'est pas « mort »**, et **un rayon amputé n'est pas un rayon désert**.
- **Pas de `temperature` / `top_p` / `top_k`** sur `claude-sonnet-5` : toute valeur non-défaut
  renvoie une 400.
- **Instance par appel, jamais à l'import** pour Cache / JobStore / UsageMeter / NicheHistory :
  sinon importer `server.py` en test écrit de vrais fichiers dans le dépôt.
- Code langue DataForSEO : `fr_FR` (pas `fr`), `location_code=2250`.

---

## 10. Limites connues / ce qui n'existe pas encore

**Bloquants pour une mise en vente**

- **Aucune authentification — et le `user_id` est déclaratif.** La colonne existe partout
  (`jobs.db`, `usage.db`, `history.db`), mais quatre endpoints acceptent une valeur **fournie par
  le client**, avec `"local"` pour simple défaut : `POST /api/jobs` (champ du body), `GET
  /api/jobs`, `GET /api/usage` et `GET /api/history` (paramètre de requête). Conséquence concrète,
  pas cosmétique : n'importe quel client peut se déclarer sous un autre `user_id` et **repartir
  d'un plafond mensuel vierge** — le garde-fou de dépense ne tient que tant que personne n'essaie.
  Le `"local"` est en dur dans `POST /api/verdict`, `POST /api/kdp-keywords` et les consignations
  d'historique des deux endpoints SSE. Pas de comptes, pas de sessions, pas de paiement, pas de
  facturation. Quand l'auth arrivera : introduire `user_id` **uniquement** dans `history.py` / `usage.py` / `jobs.py`,
  **jamais** dans `cache.py` (le cache reste partagé, c'est le modèle économique).
- **Trois fonctions payantes ou utiles sont inatteignables depuis l'UI livrée.** Les boutons
  « Télécharger le PDF » (`.btn-pdf`) et « Mots-clés KDP » (`.btn-kdp`) sont générés à l'intérieur
  de `verdictBlock(r)` dans `web/index.html`, qui sort sur `if(!v) return ''` dès sa deuxième ligne
  quand la niche n'a pas de verdict — or `n_verdict=0` partout, donc `ScoredNiche.verdict` vaut
  **toujours** `None`. Et `index.html`
  n'appelle jamais `POST /api/verdict`. Les écouteurs de clic existent bien mais sont posés sous
  `if(pdfBtn)` / `if(kdpBtn)`, sur des éléments qui n'ont jamais été rendus. Les tests UX vérifient
  la **présence** des chaînes dans le HTML, pas leur **atteignabilité**. **L'historique, lui, est
  atteignable** : son bloc `.histslot` est rendu **hors** de `verdictBlock` et `loadHistorique()`
  est déclenché au dépliage d'une ligne — ne pas le ranger avec les trois autres.
- **Le compteur d'usage de l'UI reste à zéro.** `UsageMeter.autorise` n'est appelé que par
  `POST /api/jobs`, que l'UI n'utilise jamais — les **sept** URL `/api/…` littérales présentes dans
  `web/index.html` sont `/api/scout`, `/api/fiction`, `/api/fiction/sous-genres`, `/api/usage`,
  `/api/history`, `/api/kdp-keywords` et `/api/pdf` (aucune n'est construite dynamiquement) ;
  `/api/scout` et `/api/fiction` dépensent sans rien enregistrer dans `usage.db` ; `/api/verdict`
  et `/api/kdp-keywords` imputent leur coût mais avec `n_analyses=0`. Le bandeau alimenté par
  `/api/usage` affichera donc **0 analyse** quoi que fasse l'utilisateur.
- **`BSR_SOURCE=scrape` ne survit pas au déploiement** (voir §6).
- Aucun déploiement, aucun Docker, aucune base partagée : quatre fichiers SQLite locaux.

**Limites de mesure**

- **L'axe 3 « compatibilité livre » n'est pas implémenté** : figé à la constante `8.0` pour toute
  niche. Le score global vaut donc toujours `demande×0,4 + pénétration×0,4 + 1,6`, mécaniquement
  borné entre 2,4 et 9,6.
- **`bsr_top5_avg` ment sur son contenu** : le scout ne récupère que le top 3 (`n_bsr_per_niche=3`).
  Même remarque pour `worst_top10`.
- **Le critère « ≤ 10 000 résultats Amazon » n'est ni codé ni mesurable** : la donnée n'est pas
  collectée (`SearchResult.total_items` = nombre d'items de la page, jamais utilisé dans un calcul).
- **Les exclusions métier (saisonnier, religions à expertise pointue, politique contemporaine,
  risque TOS) n'existent que dans le prompt** de l'ideator. Aucun filtre Python ne rattrape un
  modèle qui désobéit — contrairement aux règles KDP et à la taxonomie fiction, doublées en code.
- **Le champ `NicheCandidate.risques` est mort** : rempli par le LLM, propagé nulle part. Le malus
  -2 pour risque TOS n'est pas codé.
- **Aucun bonus « expertise pharmacien »**, et c'est délibéré : le prompt de l'ideator impose au
  contraire une clause d'impartialité explicite qui interdit de privilégier un domaine.
- **Le paramètre `signals`** (mode « à partir de rien » nourri par des tendances) traverse les
  signatures jusqu'au prompt, mais aucun appelant ne le remplit : il vaut toujours `None`. Le mode
  « à partir de rien » se réduit à « graine vide ».
- **Aucun test d'intégration réseau** : rien ne détecte une rupture de contrat côté DataForSEO ou
  Amazon avant un run réel.

**Ce qui n'existe plus du tout** : Scrapingdog (**côté `.py`**, le mot ne survit que dans le
docstring d'en-tête de `cost_tracker.py` ; il subsiste en revanche dans trois fichiers d'archives
de décision toujours suivis par git — deux plans et une spec de `docs/superpowers/` — ainsi que
dans ce README, `CLAUDE.md` et `ROADMAP.md`, qui en parlent pour dire qu'il est abandonné), le compteur de crédits et ses garde-fous, le mode dry-run, les
rapports Excel du scout (`openpyxl` ne sert qu'à la validation **manuelle** du classifieur), Google Trends, Reddit,
Google News, TikTok, le workflow humain en 5 phases, la pré-production (sommaires, prompts de
rédaction, briefs de couverture) et la post-production (4e de couverture, fiche produit AIDA).
Depuis `eaa20b2`, les trois modules de veille et les dossiers v1 sont supprimés, pas seulement
inutilisés : il n'y a plus de code à réactiver par erreur.

---

## Licence

Projet **propriétaire** — © 2026 Baptiste. Tous droits réservés. Voir [`LICENSE`](LICENSE).
Non destiné à la redistribution ou à l'usage commercial par des tiers sans autorisation.
