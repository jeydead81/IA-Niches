# ROADMAP — IA-Niches

Améliorations priorisées, classées par objectif. Chaque item indique l'**impact**, l'**effort**
estimé et le **pourquoi**. Établie après audit du code (juin 2026), mise à jour après la refonte
DataForSEO + ideator (2026-07-09).

Légende effort : 🟢 faible · 🟡 moyen · 🔴 élevé

---

## FAIT — refonte v2 (2026-07-09)

L'architecture v1 (provider Amazon Search tiers défaillant, BSR non fiable, scoring nourri à vide)
a été **remplacée**, pas réparée : ideator LLM (Anthropic) pour générer les niches, autocomplete
Amazon.fr en direct (gratuit) pour valider la demande, **DataForSEO** pour la concurrence et le
BSR. Les trois priorités qui bloquaient l'outil sont réglées :

- **P0 — BSR fiable côté serveur.** `bsr_source.py` résout le BSR par ASIN via DataForSEO ASIN
  batché (`BSR_SOURCE=dataforseo`), fiable et adapté à un usage multi-utilisateurs, avec repli
  scraping local gratuit (`BSR_SOURCE=scrape`) pour l'usage perso. Le scoring (`scoring.py`)
  consomme désormais du BSR réel et applique les critères §4.1 (au lieu de tourner à vide).
- **P1 — Économies.** Trois leviers en place : **`n_bsr_per_niche=3`** (top-3 organique
  suffisant pour discriminer les critères §4.1, au lieu du top-10), un **cache SQLite**
  (`99-logs/df-cache.db`, clé par ASIN et par mot-clé, avec TTL) qui évite de repayer une requête
  DataForSEO déjà vue, et le **scoping rayon Livres** (`search_param=i=stripbooks`) qui réduit le
  bruit et le volume de résultats à traiter par requête.
- **P2 — Instrumentation coût.** `cost_tracker.py` mesure le coût réel d'un run (appels
  DataForSEO en $ + tokens LLM de l'ideator) et l'affiche en fin de run, en CLI et dans l'UI web
  (streamé en SSE).

Le vieux code du provider tiers v1 (`amazon_search.py`, `credits_tracker.py`) a été retiré du
dépôt. L'ancien P3 #13/#14 de ce fichier (artefacts de debug, doublons) est en grande partie
caduc — voir la section *Qualité de code* mise à jour plus bas pour ce qu'il en reste.

---

## P0 — Verdict IA par niche

### 1. Brancher le "directeur éditorial" sur le top-3 du scout 🔴
Aujourd'hui le scout produit un **classement** (score, axes, BSR) mais pas de **verdict** :
c'est Baptiste qui doit encore lire les screenshots et appliquer manuellement le prompt
"Directeur éditorial" (`CLAUDE.md` §7) + la critique stratégique (§8). L'objectif : brancher ce
prompt en **tool-use** sur le pipeline, **gaté sur le top-3** du run (pas toutes les niches — trop
coûteux, et le prompt n'a de sens que sur des niches déjà qualifiées par le scoring).

**Sortie attendue par niche** : verdict Go/No-Go tranché, score de confiance /10, facteur
décisif, **titre + sous-titre de travail**, angle d'attaque prioritaire, requête principale +
requêtes secondaires. Réutilise les données déjà collectées par le scout (search DataForSEO :
titres organiques, prix, badges, sponsorisés déjà écartés) — pas besoin de nouveaux
screenshots pour ce premier passage automatisé ; les screenshots humains (Phase 2 du `CLAUDE.md`)
restent la validation finale avant production.

**Pourquoi c'est la priorité** : c'est l'écart le plus net entre ce que l'outil fait
aujourd'hui (classer) et ce que Baptiste veut au final (savoir sur quelle niche foncer, avec
quel angle). Sans ce point, le scout reste un filtre — pas un conseiller.

---

## P1 — Comptes et monétisation

### 2. Comptes utilisateurs + crédits métrés + Stripe 🔴
Pré-requis direct à la vente (le produit est destiné à être vendu, pas seulement à usage perso) :
- **Comptes utilisateurs** (SQLite pour démarrer — le pattern cache SQLite de `cache.py` s'y
  prête déjà) : identité, clés API propres ou crédits partagés selon le modèle choisi.
- **Crédits métrés** : `cost_tracker.py` calcule déjà le coût réel en $ par run (DataForSEO + LLM)
  — il reste à le relier à un solde de crédits par utilisateur, décrémenté à chaque run.
- **Stripe** : vente de **packs de crédits prépayés** (1 crédit = 1 run, ou barème selon le coût
  réel mesuré), pas d'abonnement complexe à ce stade — cohérent avec le coût marginal mesuré
  (~0,01–0,06 $/run) et la logique usage-based déjà en place.

### 3. Dé-hardcoder la configuration utilisateur 🟡
Le système reste câblé pour **un** profil (Baptiste, pharmacien, Amazon.fr) : critères,
exclusions et bonus expertise vivent dans `CLAUDE.md`/`00-config/`, pas dans un fichier de config
par utilisateur. À traiter avant d'ouvrir à d'autres auteurs KDP, en parallèle de #2.

---

## P2 — Marketplace et produit

### 4. Marketplace anglophone (EN) 🟡
`search_providers.py` a déjà `location_code`/`language_code` en constantes (`DEFAULT_LOCATION`,
`DEFAULT_LANGUAGE`, actuellement France/`fr_FR`) — les externaliser en paramètres exposés
(CLI/UI/config utilisateur) ouvre `amazon.com`/`.co.uk`/`.de` sans réécrire le provider. Marché
EN largement plus profond que FR : fort argument de vente une fois #2/#3 en place.

### 5. Analyse comparative inter-runs 🟢
Comparer les scouts successifs pour détecter les niches en accélération (delta de score, de BSR,
de nombre de concurrents d'un run à l'autre). Différenciateur produit, faible effort une fois le
cache/l'historique de runs structuré (déjà partiellement le cas via `99-logs/df-cache.db`).

---

## Qualité de code / hygiène

### 6. Nettoyer les artefacts du provider v1 restants 🟢
La suppression de `amazon_search.py`/`credits_tracker.py` n'a pas tout emporté. Encore présents
dans `01-scripts/`, tous **complètement morts** (l'ancien provider tiers n'existe plus dans le
pipeline) :
- `amazon_autocomplete 2.py` (doublon obsolète)
- `debug_autocomplete.py` + `99-logs/debug_autocomplete_response.txt`
- `test_autocomplete.py` et l'autre script de test manuel de l'ancienne API tierce (nom de
  fichier explicitement lié au provider mort) — la vraie suite de tests vit maintenant dans
  `tests/`, avec fixtures et mocks hors-ligne

### 7. Centraliser les constantes de chemins 🟢
`trends_fr.py`, `reddit_fr.py` et `news_fr.py` redéfinissent chacun `BASE_DIR`/`RAW_DIR` en tête
de fichier au lieu de les importer d'un module commun (`util.py` existe déjà pour d'autres
helpers). Petit nettoyage, à faire en même temps que #6.

---

## Ordre d'attaque conseillé

1. **#1 (verdict IA)** — la valeur produit la plus directe, débloque une vraie recommandation
   au lieu d'un simple classement.
2. **#6 (nettoyage artefacts)** — trivial, à faire avant tout passage du dépôt en public/vente.
3. **#2 + #3 (comptes, crédits, Stripe, config par utilisateur)** — passage au produit vendable.
4. **#4 + #5 (marketplace EN, delta inter-runs)** — extension une fois le socle SaaS posé.
