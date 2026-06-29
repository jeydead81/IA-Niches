# ROADMAP — IA-Niches

Améliorations priorisées, classées par objectif. Chaque item indique l'**impact**, l'**effort**
estimé et le **pourquoi**. Établie après audit du code (juin 2026).

Légende effort : 🟢 faible · 🟡 moyen · 🔴 élevé

---

## P0 — Fiabilité (à régler en premier)

### 1. Réparer la collecte BSR / concurrence Amazon 🔴
**Le problème central.** L'endpoint Scrapingdog `/amazon` (`amazon_search.py`) échoue
systématiquement (cf. 20 échecs consécutifs dans `99-logs/credits-log.csv`, 03/05). Le scout a été
recâblé pour **sauter le search** : les axes *Demande* et *Pénétration* tournent donc presque à vide
(BSR absent, `total_results`/concurrents organiques = 0, score de pénétration bloqué à la base 5.0).

**Conséquence** : les critères BSR de la méthodologie (§4.1 du `CLAUDE.md` — le cœur de la validation
de niche) ne sont **pas automatisés**. Le classement final repose surtout sur le *nombre* de
suggestions autocomplete, un proxy faible qui discrimine mal les niches.

**Pistes** (par ordre de préférence) :
- **Réutiliser l'approche proxy qui marche déjà** pour l'autocomplete : scraper le HTML de la page
  de résultats `amazon.fr/s?k=...` via l'endpoint générique `/scrape` (déjà utilisé, fiable) +
  `BeautifulSoup` (déjà en dépendance). Extraire titres, badges « Sponsorisé », prix, et le BSR via
  la mention « #N en Livres » des fiches. Coût identique (1 crédit/req).
- Sinon : tester si l'endpoint `/amazon` nécessite un plan payant Scrapingdog, ou comparer une API
  concurrente (Rainforest API, Bright Data) sur fiabilité/prix.
- Garder la validation manuelle Phase 2 en *fallback* documenté, pas en mode par défaut.

> Sans ce point, l'outil détecte des *thèmes populaires*, pas des *niches gagnantes*. C'est le
> chantier à plus haute valeur.

### 2. Re-brancher le scoring sur des données réelles 🟡
Dépend de #1. Une fois le search réparé, recâbler `_score_niche()` pour consommer BSR,
nombre de résultats et concurrents organiques ciblés (le code de scoring existe déjà, il est juste
nourri à vide aujourd'hui). Ajouter quelques niches « témoins » connues pour calibrer les seuils.

### 3. Tests automatisés sur le parsing 🟡
Figer le format de réponse Scrapingdog/Amazon dans des *fixtures* JSON et tester `_parse_bsr`,
`_is_sponsored`, `compute_bsr_stats`, `flatten_suggestions`. Évite les régressions silencieuses
quand Amazon change sa structure (cause classique de panne d'un scraper).

---

## P1 — Coût (réduire la consommation de crédits)

### 4. Cache global de requêtes par run 🟢 — gain immédiat
Le log montre la **même** requête autocomplete payée plusieurs fois dans un run (ex.
`livre jeûne intermittent`, `jeûne intermittent femme` réapparaissent via les niveaux 1/2 de seeds
différents). Un simple `dict` en mémoire (clé = requête normalisée) garantissant « 1 string = 1
appel max » peut **couper 20–40 % des crédits** sans rien changer aux résultats.

### 5. Cache inter-runs avec TTL 🟡
L'autocomplete Amazon est stable de semaine en semaine. Persister un cache (ex. `99-logs/ac-cache.json`)
avec TTL 7–14 jours : sur un rythme bi-mensuel, l'essentiel d'un scout devient gratuit. Le mécanisme
de reprise intra-journée existe déjà (`amazon_autocomplete.run`), il suffit de l'étendre.

### 6. Rendre l'expansion niveau 2 paramétrable 🟢
Le niveau 2 (jusqu'à 4 sous-requêtes par seed) est le **premier poste de coût**. L'exposer en option
(`--expand-level2 / --no-level2`, profondeur réglable) et ne le déclencher que si le niveau 1 d'un
seed est « prometteur » (assez de suggestions multi-mots).

### 7. Aligner config et documentation 🟢
`credits-config.md` = `MAX_CREDITS_PER_RUN=400` / `DRY_RUN=False`, alors que `CLAUDE.md` documente
50 / True. Réconcilier (et refléter la valeur réelle dans le README — déjà fait).

---

## P2 — Produit & monétisation (pré-requis à la vente)

### 8. Interface utilisateur 🔴
Aujourd'hui : CLI + pilotage Cowork. Pour vendre, prévoir une UI web minimale :
saisie des seeds/focus → bouton « Lancer le scout » → table de résultats triable/filtrable →
export Excel/CSV → compteur de crédits en direct. Stack légère possible : FastAPI + un front
React/Svelte, ou Streamlit pour un MVP rapide.

### 9. Dé-hardcoder la configuration utilisateur 🔴
Le système est câblé pour **un** profil (Baptiste, pharmacien, Amazon.fr) :
- Externaliser les `KDP_SEEDS`, `EXCLUSIONS`, `PHARMA_CATEGORIES` dans des fichiers de config par
  utilisateur (le « bonus pharmacien » devient un « bonus expertise » paramétrable).
- Rendre la **marketplace** configurable (`amazon.fr`/`.de`/`.com`/`.co.uk` → le `mid` et la langue
  sont déjà des constantes faciles à externaliser). C'est un fort argument de vente (marché EN bien
  plus large que FR).

### 10. Gestion multi-utilisateurs des secrets 🔴
Pour un SaaS : clés API par utilisateur, chiffrées en base — pas un `.env` local. Et soit chaque
client apporte sa clé Scrapingdog (*bring-your-own-key*), soit revente de crédits avec marge.

### 11. Modèle de prix 🟡
Le coût marginal (crédits Scrapingdog) se prête naturellement à un pricing **à l'usage** :
- *Bring-your-own-key* + abonnement fixe (logiciel seul) — marge prévisible, risque faible.
- Crédits inclus par palier (ex. 5 / 20 / 50 scouts par mois) — refacturation crédits + marge.
- Le free tier 1000 crédits ≈ ~5 scouts actuels (≈200 crédits/run) ; les optimisations P1 le
  poussent à 10–20 scouts → meilleur produit d'appel gratuit.

### 12. Analyse inter-runs / tendances montantes 🟡
Comparer les scouts successifs pour détecter les niches en accélération (déjà listé comme évolution
prévue dans `CLAUDE.md` §11). Fort différenciateur produit.

---

## P3 — Qualité de code / hygiène

### 13. Nettoyer les artefacts 🟢
- `01-scripts/amazon_autocomplete 2.py` : doublon obsolète (artefact de synchro) → à supprimer.
- `99-logs/debug_autocomplete_response.txt` : dump de debug → à supprimer.
- `debug_autocomplete.py`, `test_*.py` : utiles pour le debug du search (P0), à déplacer dans un
  dossier `tests/` clair.
> (Ces deux fichiers sont déjà exclus du suivi git via `.gitignore`.)

### 14. Petits correctifs 🟢
- `_filter_keywords` / `GENERIC_WORDS` : doublons de clés (`"français"`, `"monde"`) — inoffensif
  mais à nettoyer.
- `amazon_search.py` : `except (ValueError, Exception)` attrape tout et rend le `ValueError`
  redondant → resserrer la gestion d'erreurs.
- Centraliser les constantes de chemins (chaque script redéfinit `BASE_DIR`).

---

## Ordre d'attaque conseillé

1. **#4 (cache run)** — gain de coût immédiat, effort minimal.
2. **#1 + #2 (search BSR via proxy)** — débloque la vraie valeur de l'outil.
3. **#9 (marketplace + config externe)** — ouvre le marché et prépare la vente.
4. **#8 (UI)** + **#11 (pricing)** — passage au produit vendable.
