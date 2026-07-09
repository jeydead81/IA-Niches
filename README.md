# IA-Niches — Chercheur de niches pour auteurs Amazon KDP

> Système de veille et d'analyse de niches **Amazon.fr KDP**, piloté en langage naturel.
> Il automatise la détection d'opportunités éditoriales (livres rédigés, non low-content)
> et réduit la recherche de niche de **2–5 h/semaine à moins d'1 h**.

---

## ⚠️ Sécurité — à lire en premier

- Les clés API (Anthropic, DataForSEO) vivent **uniquement dans `.env`**, qui est **exclu de git**
  (`.gitignore`). Ne jamais committer ce fichier, ni coller une clé dans un fichier suivi.
- Un modèle `.env.example` documente les variables attendues, sans secret.
- **Avant toute mise en vente ou passage du dépôt en public** : régénérer les clés Anthropic et
  DataForSEO, retirer les données de runs (`02-veille-hebdo/`, `99-logs/df-cache.db`) et envisager
  de réécrire l'historique git (`git filter-repo`) — ces données révèlent la stratégie de seeds.

---

## Le concept

Une IA (**ideator**, modèle Claude) propose des niches de livre — à partir d'une graine
(« ésotérisme ») ou « à partir de rien ». Chaque niche est ensuite **validée** en deux temps :
la **demande** via l'**autocomplete Amazon.fr** (gratuit — les vraies requêtes tapées par les
acheteurs), puis la **concurrence et le BSR** via **DataForSEO**, scopés au rayon Livres. Les
niches sont **scorées sur 3 axes** : *Demande*, *Facilité de pénétration*, *Compatibilité livre*
(critères BSR §4.1 du `CLAUDE.md`). Le résultat : une liste de niches classées, avec verdict et
coût réel du run affiché en fin d'exécution.

**Cible** : auteurs / éditeurs KDP francophones cherchant des niches *evergreen* (hors saisonnier) à
fort potentiel et faible concurrence.

---

## Workflow en 5 phases

```
PHASE 1 — SCOUT AUTO  ─────────────────────────────────────────────┐
  Ideator IA (Claude) : niches livre, à partir d'une graine ou      │  (coût LLM)
  "à partir de rien"                                                │
  → Validation de la demande : autocomplete Amazon.fr               │  (gratuit)
  → Concurrence : recherche Amazon.fr via DataForSEO (rayon Livres) │  (~0,003 $/niche)
  → BSR : scraping fiche produit (gratuit) ou DataForSEO ASIN batché│  (gratuit / payant)
  → Scoring 3 axes (§4.1) → niches classées + coût réel du run     │
                                                                     │
PHASE 2 — VALIDATION HUMAINE                                         │
  L'auteur choisit 2–3 niches, navigue sur Amazon.fr, capture       │
  des screenshots → 03-niches-validees/                             │
                                                                     │
PHASE 3 — ANALYSE ÉDITORIALE                                         │
  Lecture des screenshots + prompt "Directeur éditorial" +          │
  critique stratégique → analyse-editoriale.md (verdict Go/No-Go)   │
                                                                     │
PHASE 4 — PRÉ-PRODUCTION (niches Go)                                 │
  Sommaire détaillé + prompts de rédaction → pre-production.md       │
                                                                     │
PHASE 5 — POST-PRODUCTION                                            │
  Couvertures + 4e de couverture + fiche produit SEO + mots-clés    │
  KDP → post-production.md                                           │
└────────────────────────────────────────────────────────────────────┘
```

Seule la **Phase 1** est entièrement automatisée (scripts Python + CLI/UI web). Les phases 3–5
sont assistées en langage naturel (prompts de `05-prompts/`), pilotées via `CLAUDE.md`.

---

## Stack & sources de données

| Source                     | Rôle                                          | Coût                | Lib / API              |
|-----------------------------|------------------------------------------------|----------------------|-------------------------|
| **Ideator LLM**             | Génère les niches livre candidates             | Tokens Claude        | API Anthropic (`claude-sonnet-5` par défaut) |
| **Amazon.fr Autocomplete**  | Validation de la demande (vraies requêtes acheteurs) | Gratuit         | Endpoint public `completion.amazon.fr` |
| **Amazon.fr Search**        | Concurrence, sponsorisés, ASIN (rayon Livres)  | ~0,003 $/requête    | DataForSEO (Amazon Products) |
| **BSR (classement Livres)** | Preuve de demande §4.1                         | Gratuit ou payant    | Scraping fiche produit (`BSR_SOURCE=scrape`) ou DataForSEO ASIN batché (`BSR_SOURCE=dataforseo`) |
| Google Trends / Reddit / Google News FR | Scripts de collecte de signaux gratuits, exploitables en entrée de l'ideator (`signals`) mais non branchés par défaut sur la CLI/UI | Gratuit | `pytrends` / `feedparser` / `praw` |
| TikTok Creative Center      | Hashtags émergents                             | Manuel               | (saisie humaine, non automatisé) |

- **Python 3**, tout en local (pas de Docker/serveur) ; UI web optionnelle (FastAPI, en local aussi).
- Un **cache SQLite** (`99-logs/df-cache.db`) évite de repayer une requête DataForSEO ou un BSR déjà
  vus récemment (clé par ASIN et par mot-clé, avec TTL).
- Pas d'automatisation TikTok (anti-bot trop agressif) → saisie manuelle optionnelle.

---

## Installation

```bash
pip install -r 01-scripts/requirements.txt
cp .env.example .env        # puis renseigner les clés (voir ci-dessous)
```

### Configuration `.env`

| Variable              | Obligatoire | Rôle                                                          |
|------------------------|:-----------:|------------------------------------------------------------------|
| `ANTHROPIC_API_KEY`    | ✅          | Clé API Claude, utilisée par l'ideator pour proposer les niches. |
| `DATAFORSEO_LOGIN`     | ✅          | Login du compte DataForSEO (recherche Amazon + BSR batché).      |
| `DATAFORSEO_PASSWORD`  | ✅          | **Mot de passe d'API** DataForSEO (dans l'espace *API Dashboard*, **pas** le mot de passe du compte web). |
| `IDEATOR_MODEL`        | Non         | Modèle utilisé par l'ideator. Défaut : `claude-sonnet-5`.         |
| `BSR_SOURCE`           | Non         | `scrape` (défaut) = scraping local gratuit, IP résidentielle. `dataforseo` = BSR batché serveur, fiable, payant. |
| `REDDIT_CLIENT_ID` / `REDDIT_CLIENT_SECRET` | Non | Reddit API (sinon mode RSS dégradé automatique). |

## Coût

Un run type coûte environ **0,01 à 0,06 $**, selon le nombre de niches passées au search
(`n_search`, coût DataForSEO ~0,003 $/niche) et le taux de cache. Le **cache SQLite**
(`99-logs/df-cache.db`) mémorise les résultats DataForSEO et les BSR par ASIN / mot-clé (avec TTL) :
relancer un scout sur une **graine déjà vue récemment** coûte donc **quasiment 0 $** (seuls les
tokens de l'ideator sont repayés). Le **BSR est gratuit** en local (`BSR_SOURCE=scrape`) ; il devient
payant mais fiable en mode serveur (`BSR_SOURCE=dataforseo`, adapté à l'UI web multi-utilisateurs).
Le coût réel (DataForSEO + tokens LLM) est **affiché en fin de run**, en CLI comme dans l'UI web.

## Utilisation

### En ligne de commande

```bash
# Lanceur interactif (raccourci bureau IA-Niches.bat) — menu : suggestions / BSR / idées de niches
python 01-scripts/launcher.py

# Scout complet, orchestrateur v2
python 01-scripts/scout_master.py --seed "ésotérisme"

# Mode "à partir de rien" (pas de graine)
python 01-scripts/scout_master.py

# Réglage du volume (idées générées / niches passées au search payant)
python 01-scripts/scout_master.py --seed "sommeil" --ideas 15 --search 8
```

Chaque run affiche la liste des niches classées (score global, axes, critères §4.1, BSR, coût) et
le coût réel en dollars en fin d'exécution.

### Interface web

```bash
# Raccourci bureau « IA-Niches (Web) », ou :
python web/server.py
```

Ouvre `http://127.0.0.1:8000` : formulaire de saisie (graine, volume), lancement du scout en
tâche de fond avec progression **en direct (SSE)**, tableau des niches classées, coût du run affiché
en fin d'exécution.

### Tests

```bash
python -m pytest
```

### En langage naturel (Cowork / Claude)

> « Lance le scout » · « Lance la phase 3 sur la niche X » · « Lance la phase 4 sur X »

Le détail du comportement attendu est dans [`CLAUDE.md`](CLAUDE.md) (contexte permanent de l'agent).

---

## Structure du dépôt

```
├── CLAUDE.md              # Contexte permanent de l'agent (méthodologie complète)
├── 00-config/            # Critères, exclusions
├── 01-scripts/           # Scripts Python (le cœur)
│   ├── scout_master.py       # Orchestrateur v2 : ideator → validation → search → BSR → scoring
│   ├── niche_ideator.py      # Génération de niches par LLM (Anthropic, tool-use)
│   ├── niche_validator.py    # Validation demande via autocomplete
│   ├── amazon_autocomplete.py / amazon_product.py   # Autocomplete + fiche produit (BSR), gratuits
│   ├── search_providers.py   # Recherche Amazon.fr payante (DataForSEO, rayon Livres)
│   ├── bsr_source.py         # Résolution BSR : scrape (gratuit) ou DataForSEO (serveur)
│   ├── cache.py              # Cache SQLite (99-logs/df-cache.db), clé ASIN / mot-clé, TTL
│   ├── cost_tracker.py       # Coût réel du run (DataForSEO $ + tokens LLM)
│   ├── scoring.py            # Scoring 3 axes + critères BSR §4.1
│   ├── launcher.py           # Menu interactif (raccourci bureau IA-Niches.bat)
│   └── trends_fr.py / reddit_fr.py / news_fr.py   # Signaux gratuits optionnels
├── web/                  # UI web (FastAPI + SSE) — server.py, index.html
├── tests/                # Suite pytest (unitaires, providers mockés hors-ligne)
├── 02-veille-hebdo/      # Données brutes + rapports des scouts
├── 03-niches-validees/   # Une niche validée = un dossier (screenshots + analyses)
├── 05-prompts/           # Prompts (directeur éditorial, critique, OneBookLab)
└── 99-logs/              # Cache SQLite (df-cache.db)
```

---

## Limitations connues (transparence)

- **Google Trends** (`pytrends`, API non officielle) : sujet aux *rate limits* (HTTP 429), parfois
  vide. Traité en *best-effort*, signal optionnel (n'interrompt pas le scout).
- **Reddit** : mode RSS dégradé par défaut (pas de score/commentaires). Mode API complet si
  identifiants fournis dans `.env`.
- **BSR en mode `scrape`** : dépend d'une IP résidentielle et de la stabilité de la page produit
  Amazon — gratuit mais moins fiable que le mode `dataforseo` (batché, payant).
- **TikTok** : pas d'automatisation fiable → saisie manuelle.

---

## Roadmap

Optimisations coût/fiabilité et pistes de produit (UI, multi-marketplace, pricing) :
voir **[`ROADMAP.md`](ROADMAP.md)**.

---

## Licence

Projet **propriétaire** — © 2026 Baptiste. Tous droits réservés. Voir [`LICENSE`](LICENSE).
Non destiné à la redistribution ou à l'usage commercial par des tiers sans autorisation.
