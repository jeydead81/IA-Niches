# Spike M0 — Module Fiction (bloquant) — résultats & décisions

**Date :** 2026-07-13 · **Marketplace testé :** amazon.fr · **Sous-genre témoin :** cosy mystery
**Coût réel :** ~0,03 $ (2 SERP + 8 ASIN, file Priority) · **Fixtures :** `tests/fixtures/fiction/`

> Spike prescrit par le brief Module Fiction : *« Aucun code produit avant la fin du spike. »*
> Les décisions ci-dessous sont tranchées **sur payloads réels**, pas sur hypothèse.

---

## V1 — Contrainte de catégorie (browse node) sur l'endpoint Products → ✅ **GO**

`search_param=rh=n:<node_id>` **est bien pris en compte** par `merchant/amazon/products`.

| | organiques | observation |
|---|---|---|
| « cosy mystery » sans contrainte | **53** | inclut du hors-sujet : *« Cosy Mystery : le détective, c'est vous ! »* est un **jeu** (catégories : Loisirs créatifs → Jeux) |
| « cosy mystery » + `rh=n:9691488031` | **30** | quasi intégralement des cosy mysteries FR pertinents (Provence, Oxford, Christmas, « à la française »…) |
| recouvrement | **7 ASIN communs** | la contrainte filtre réellement (elle n'est pas ignorée) |

**Décision : mode « rayon catégorie » retenu.** La SERP contrainte au node est nettement plus propre que la SERP libre — c'est le rayon que voit un lecteur qui navigue la catégorie. Fixtures : `v1a_serp_cosy_mystery.json`, `v1b_serp_node.json`.

> Tri par ventes (`s=salesrank`) non testé : l'ordre de pertinence Amazon est déjà fortement pondéré ventes, et la contrainte node suffit pour v1. À retester si le besoin apparaît.

---

## V2 — Champs disponibles dans le payload ASIN (amazon.fr) — 8 livres

### Disponibles et exploitables
| Champ | Couverture | Chemin |
|---|---|---|
| **blurb / description** | **8/8 (100 %)** | `items[0].description` — *entrée du classifieur, critique* |
| prix | 8/8 (100 %) | `items[0].price_from` / `price_to` / `currency` |
| auteur | 8/8 (100 %) | `items[0].author` |
| catégories + **node IDs** | 8/8 (100 %) | `items[0].categories[].category` / `.url` (`node=\d+`) |
| date de publication | 7/8 (87 %) | détails → `Date de publication` |
| langue | 7/8 (87 %) | détails → `Langue` |
| **BSR** | 7/8 (87 %) | détails → `Classement des meilleures ventes d'Amazon` (parseur existant) |
| note + nb d'avis | 7/8 (87 %) | `items[0].rating.value` / `.votes_count` |
| éditeur | 6/8 (75 %) | détails → `Éditeur` |

### Absents — deux replis déclenchés
- **`bought_past_month` : ABSENT (0/8).** Aucune occurrence du champ ni de « achetés au cours du mois » dans les payloads amazon.fr.
  → **Décision : `depth_score` en mode BSR-first** (règle §11 du brief : « si < 40 %, bascule BSR-first » — ici 0 %).
- **Badge Kindle Unlimited : ABSENT (0/8).** Zéro occurrence de « Kindle Unlimited » / « unlimited ».
  → **Décision : `ku_share = None` et masqué dans l'UI** (contingence explicitement prévue au brief).
  *(Les champs Kindle présents — `Taille du fichier`, `Word Wise`, `Page Flip` — indiquent une édition Kindle, pas l'appartenance à KU.)*

### Série — meilleure que prévu 🎁
Clé **structurée** `Livre N sur M` dans les détails (ex. `Livre 5 sur 6`, `Livre 8 sur 12`, `Livre 1 sur 10`) → donne **le tome ET la longueur de la série**, présente sur **4/8 (50 %)**.
→ **Décision : `series_*` = clé structurée quand présente, sinon fallback heuristique** (regex titre `Tome \d` / `T\d` + répétition d'auteur dans le top N), comme prévu au brief. Reste un **proxy** affiché comme tel, jamais présenté comme du read-through mesuré.

---

## V3 — Couverture autocomplétion FR sur les tropes → **5/10** (soft signal confirmé)

| Requête | Suggestions |
|---|---|
| romance milliardaire | **4** (`en français`, `avec trahison`, `adulte`) |
| romance hockey | **4** (`francais`, `mm`, `sur glace`) |
| romance seconde chance · cosy mystery bretagne · polar breton | 1 (écho de la requête) |
| romance noel montagne · romantasy ennemis · thriller psychologique famille · cosy mystery libraire · fantasy academie magie | **0** |

**Décision : statut *soft signal* confirmé — ne gate JAMAIS seul.** Score 0 / 0.5 / 1 conservé, utilisé uniquement pour désambiguïser la matrice de demande (M5). Les requêtes « commerciales » larges sont riches ; les trios trope×décor précis ne remontent rien — ce qui est exactement l'hypothèse du brief.

---

## Bonus — la taxonomie est semi-automatisable

Le payload ASIN renvoie le fil d'Ariane **avec les node IDs** dans `categories[].url` (`…&node=9691488031`). Nodes relevés sur ce seul échantillon : `301061` (Livres), `9691488031`, `9691472031`, `9691469031`, `672108031`, `302054`, `302068`, `355635011`, `895004031`, `205566718031`, `301134`, `695398031`.

→ **Le « seul travail manuel incompressible » du brief se réduit fortement** : pour chaque sous-genre, il suffit d'**un ASIN représentatif** → l'appel ASIN rend ses nodes. Relevé assisté au lieu de 100 % manuel.

---

## Impacts sur le plan de construction

| Module | Ajustement issu du spike |
|---|---|
| **M1** taxonomie | node IDs récupérés via ASIN représentatif (semi-auto) |
| **M2** acquisition | `EnrichedBook` **sans** `bought_past_month` ni `is_ku` ; série via clé `Livre N sur M` + fallback ; SERP contrainte au node |
| **M5** scoring | `depth_score` **BSR-first** ; `ku_share` retiré de la v1 ; `autocomplete_score` reste soft |
| **M4** classifieur | entrée sécurisée : blurb disponible à 100 % |

**Déjà en place (non prévu au brief) :** endpoint ASIN **batché** (`product_info_batch`), **cache SQLite inter-runs**, `cost_tracker` (le brief cite encore `credits_tracker`, remplacé). Modèles en **pydantic v2** (pas `@dataclass`) pour rester homogène avec le codebase.

---

## Reste à trancher (décisions produit, hors spike)
1. Marketplace v1 : **FR seul** ou FR + COM ?
2. Périmètre taxonomie v1 : **5-6 sous-genres** pour valider la chaîne, ou les 15 d'emblée ?
3. Set de validation du classifieur (≥ 80 % d'accord sur 50 livres) : qui étiquette, et comment ?
