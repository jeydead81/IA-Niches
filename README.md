# IA-Niches — Chercheur de niches pour auteurs Amazon KDP

> Système de veille et d'analyse de niches **Amazon.fr KDP**, piloté en langage naturel.
> Il automatise la détection d'opportunités éditoriales (livres rédigés, non low-content)
> et réduit la recherche de niche de **2–5 h/semaine à moins d'1 h**.

---

## ⚠️ Sécurité — à lire en premier

- La clé API (Scrapingdog) vit **uniquement dans `.env`**, qui est **exclu de git** (`.gitignore`).
  Ne jamais committer ce fichier, ni coller la clé dans un fichier suivi.
- Un modèle `.env.example` documente les variables attendues, sans secret.
- **Avant toute mise en vente ou passage du dépôt en public** : régénérer la clé Scrapingdog,
  retirer les données de runs (`02-veille-hebdo/`, `99-logs/credits-log.csv`) et envisager de
  réécrire l'historique git (`git filter-repo`) — ces données révèlent la stratégie de seeds.

---

## Le concept

L'outil croise plusieurs sources gratuites (Google Trends, Reddit, Google News) avec l'**autocomplete
Amazon.fr** (les vraies requêtes tapées par les acheteurs) pour faire émerger des niches, puis les
**score sur 3 axes** : *Demande*, *Facilité de pénétration*, *Compatibilité livre*. Le résultat est un
**rapport Excel** classé et coloré, prêt à l'arbitrage humain.

**Cible** : auteurs / éditeurs KDP francophones cherchant des niches *evergreen* (hors saisonnier) à
fort potentiel et faible concurrence.

---

## Workflow en 5 phases

```
PHASE 1 — SCOUT AUTO  ─────────────────────────────────────────────┐
  Sources gratuites : Google Trends FR + Reddit FR + Google News FR │  (0 crédit)
  + TikTok manuel (hashtags optionnels)                             │
  + Amazon Autocomplete via Scrapingdog                             │  (1 crédit / requête)
  → Scoring 3 axes → Rapport Excel : 02-veille-hebdo/rapports/      │
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

Seule la **Phase 1** est entièrement automatisée (scripts Python). Les phases 3–5 sont assistées
en langage naturel (prompts de `05-prompts/`).

---

## Stack & sources de données

| Source              | Rôle                                   | Coût           | Lib / API        |
|---------------------|----------------------------------------|----------------|------------------|
| Google Trends FR    | Signal de tendance (30 j / 12 mois)    | Gratuit        | `pytrends`       |
| Reddit FR           | Signal communautaire                   | Gratuit (RSS)  | `feedparser`/`praw` |
| Google News FR      | Signal d'actualité                     | Gratuit (RSS)  | `feedparser`     |
| Amazon.fr Autocomplete | Vraies requêtes acheteurs (expansion) | 1 crédit/req | Scrapingdog      |
| Amazon.fr Search    | BSR / concurrence / sponsorisés        | 1 crédit/req   | Scrapingdog *(voir Limitations)* |
| TikTok Creative Center | Hashtags émergents                  | Manuel         | (saisie humaine) |

- **Python 3**, tout en local (pas de Docker/serveur).
- Pas d'automatisation TikTok (anti-bot trop agressif) → saisie manuelle optionnelle.

---

## Installation

```bash
pip install -r 01-scripts/requirements.txt
cp .env.example .env        # puis renseigner SCRAPINGDOG_API_KEY
```

## Utilisation

### En ligne de commande

```bash
# Test de la clé API (1 crédit)
python 01-scripts/scout_master.py --dry-run

# Scout complet
python 01-scripts/scout_master.py

# Avec hashtags TikTok repérés manuellement
python 01-scripts/scout_master.py --tiktok "ikigai,burnout,neurodivergent"

# Focus sur un domaine (expansion sémantique ciblée)
python 01-scripts/scout_master.py --focus "nutrition sportive,sport santé"
```

Le rapport Excel atterrit dans `02-veille-hebdo/rapports/scout-AAAA-MM-JJ.xlsx` (3 onglets :
*Synthèse* colorée, *Métadonnées* du run, *Sponsorisés écartés*).

### En langage naturel (Cowork / Claude)

> « Lance le scout » · « Lance la phase 3 sur la niche X » · « Lance la phase 4 sur X »

Le détail du comportement attendu est dans [`CLAUDE.md`](CLAUDE.md) (contexte permanent de l'agent).

---

## Garde-fous crédits (Scrapingdog)

Configurables dans [`00-config/credits-config.md`](00-config/credits-config.md) :

| Paramètre              | Défaut | Rôle                                            |
|------------------------|--------|-------------------------------------------------|
| `MAX_CREDITS_PER_RUN`  | 400    | Plafond strict par scout → arrêt + rapport partiel |
| `MAX_RETRIES_PER_REQUEST` | 1   | Pas de retry agressif                           |
| `RETRY_DELAY_SECONDS`  | 5      | Délai entre tentatives                          |
| `DRY_RUN_FIRST_LAUNCH` | False  | 1 requête test au 1er lancement                 |

Chaque requête payante est **loggée** dans `99-logs/credits-log.csv` (date, endpoint, mot-clé,
crédits, succès, cumul, reste estimé).

---

## Structure du dépôt

```
├── CLAUDE.md              # Contexte permanent de l'agent (méthodologie complète)
├── 00-config/            # Critères, exclusions, config crédits
├── 01-scripts/           # Scripts Python (le cœur)
│   ├── scout_master.py       # Orchestrateur
│   ├── trends_fr.py / reddit_fr.py / news_fr.py
│   ├── amazon_autocomplete.py / amazon_search.py
│   ├── credits_tracker.py    # Garde-fous + log crédits
│   └── report_builder.py     # Génération Excel
├── 02-veille-hebdo/      # Données brutes + rapports des scouts
├── 03-niches-validees/   # Une niche validée = un dossier (screenshots + analyses)
├── 05-prompts/           # Prompts (directeur éditorial, critique, OneBookLab)
└── 99-logs/              # Log CSV des crédits
```

---

## Limitations connues (transparence)

- **Amazon Search (BSR) non opérationnel** : l'endpoint Scrapingdog `/amazon` échoue sur le plan
  actuel. Le scout **contourne** le search et délègue la validation BSR à la Phase 2 manuelle.
  → Le scoring repose donc surtout sur le volume d'autocomplete (signal plus faible). Chantier
  prioritaire — voir [`ROADMAP.md`](ROADMAP.md).
- **Google Trends** (`pytrends`, API non officielle) : sujet aux *rate limits* (HTTP 429), parfois
  vide. Traité en *best-effort* (n'interrompt pas le scout).
- **Reddit** : mode RSS dégradé par défaut (pas de score/commentaires). Mode API complet si
  identifiants fournis dans `.env`.
- **TikTok** : pas d'automatisation fiable → saisie manuelle.

---

## Roadmap

Optimisations coût/fiabilité et pistes de produit (UI, multi-marketplace, pricing) :
voir **[`ROADMAP.md`](ROADMAP.md)**.

---

## Licence

Projet **propriétaire** — © 2026 Baptiste. Tous droits réservés. Voir [`LICENSE`](LICENSE).
Non destiné à la redistribution ou à l'usage commercial par des tiers sans autorisation.
