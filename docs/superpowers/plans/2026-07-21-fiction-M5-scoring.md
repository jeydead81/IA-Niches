# Fiction M5 — Scoring & matrice de demande — Plan d'implémentation

> **For agentic workers:** REQUIRED SUB-SKILL: superpowers:subagent-driven-development.

**Goal:** Transformer un rayon lu (M2) + ses étiquettes (M4) + la sonde (M3) en un `FictionNicheReport` qui répond à **une** question : *ce trio vaut-il un roman ?*

**Le différenciateur est `saturation_trio`.** N'importe qui lit un BSR. Ce module répond à « combien de livres promettent DÉJÀ exactement ce que je veux écrire ? » — ça n'existe nulle part ailleurs, et ça n'est possible que parce que M4 a lu les quatrièmes de couverture.

**Faits mesurés qui pilotent les seuils** (live, Kindle FR — pas des valeurs inventées) :
- `thriller psychologique manipulation` → BSR top 5 : **1 960 / 2 168 / 7 422 / 14 924 / 47 262** → rayon actif.
- `cosy mystery village` → BSR top 5 : **62 230 / 95 309 / 150 766 / 156 045 / 204 800** → rayon faible.
- **25 % du top Kindle sont des titres gratuits** (classement distinct) → hors scoring.
- Rangs « Livres » et « Boutique Kindle » **non comparables** → passer par `label_rayon()`.
- Un rayon contraint contient des **non-romans** (jeu, coloriage) → hors scoring.

**Décision — les seuils sont des constantes nommées, en un seul endroit.** Ce sont des repères marché, pas des vérités : un produit vendu devra les exposer. Les enfouir dans des `if` les rendrait intouchables.

**Décision — l'autocomplete ne gate jamais, et son barème n'est pas uniforme.** Mesuré en M3 : en romance le trope EST la requête (`dark romance mafia` → 1,0) ; ailleurs le rayon se navigue (`cosy mystery boulangerie bretagne` → 0,0 alors que le sous-genre est massivement cherché). Un 0 en cosy est normal ; un 0 sur un trope de romance est une vraie information négative.

**Tech Stack :** Python 3.13, pytest, pydantic v2. **Aucun réseau, aucun LLM** — M5 est du calcul pur sur des objets déjà acquis.

---

## Task M5-1 : `fiction_scoring` — les métriques élémentaires

**Files:** Create `01-scripts/fiction_scoring.py` · Test `tests/test_fiction_scoring.py`

- [ ] **Step 1 : Tests (échouent)** — valeurs calées sur les mesures live ci-dessus :
```python
from fiction_scoring import (SEUILS, livres_scorables, depth_score, openness_score,
                             saturation_trio, series_share, price_band)
from models import EnrichedBook, FictionNiche, TropeClassification


def _livre(asin, bsr, rayon="Boutique Kindle", gratuit=False, prix=3.99, avis=20,
           serie=False, pos=1):
    return EnrichedBook(asin=asin, title="T", bsr=bsr, bsr_rayon=rayon,
                        bsr_gratuit=gratuit, price=prix, reviews_count=avis,
                        serie_total=5 if serie else None, serie_tome=1 if serie else None,
                        serp_position=pos)


def test_scorables_ecarte_gratuits_non_romans_et_mauvais_rayon():
    """Trois exclusions mesurées au spike : un titre gratuit a un classement DISTINCT,
    un jeu n'est pas un roman, et un rang « Livres » n'est pas comparable à un rang
    « Boutique Kindle »."""
    livres = [_livre("A1", 2000), _livre("A2", 478, gratuit=True),
              _livre("A3", 1597, rayon="Livres"), _livre("A4", 5000), _livre("A5", None)]
    cl = {"A4": TropeClassification(asin="A4", taxonomy_version="fr_v1", est_roman=False)}
    ok = livres_scorables(livres, cl, rayon="kindle")
    assert [b.asin for b in ok] == ["A1"]


def test_depth_calee_sur_les_rayons_mesures():
    """thriller psy (best 1960) doit sortir nettement au-dessus de cosy village (best 62230)."""
    actif = [_livre(f"A{i}", b) for i, b in enumerate([1960, 2168, 7422, 14924, 47262])]
    faible = [_livre(f"B{i}", b) for i, b in enumerate([62230, 95309, 150766, 156045, 204800])]
    assert depth_score(actif) > 0.7
    assert depth_score(faible) < 0.4
    assert depth_score([]) == 0.0                 # rayon vide -> pas de demande prouvée


def test_saturation_trio_compte_les_livres_qui_promettent_DEJA_le_trio():
    """Le différenciateur : 3 livres sur 4 promettent déjà mafia+captivite -> saturé."""
    niche = FictionNiche(sous_genre="dark_romance", tropes=["mafia", "captivite"],
                         rayon="kindle", query="q")
    livres = [_livre(f"A{i}") for i in range(4)]
    cl = {
        "A0": TropeClassification(asin="A0", taxonomy_version="fr_v1",
                                  tropes=["mafia", "captivite"]),
        "A1": TropeClassification(asin="A1", taxonomy_version="fr_v1",
                                  tropes=["mafia", "captivite", "vengeance"]),
        "A2": TropeClassification(asin="A2", taxonomy_version="fr_v1", tropes=["mafia"]),
        "A3": TropeClassification(asin="A3", taxonomy_version="fr_v1",
                                  tropes=["mariage_arrange"]),
    }
    # A0 et A1 couvrent le trio entier ; A2 partiellement ; A3 pas du tout
    s = saturation_trio(niche, livres, cl)
    assert 0.4 < s < 0.7
    assert saturation_trio(niche, livres, {}) == 0.0      # rien de classé -> rien de prouvé


def test_openness_recompense_un_rayon_peu_dote_en_avis():
    """Peu d'avis sur les leaders = places prenables ; beaucoup = mur installé."""
    ouvert = [_livre(f"A{i}", 5000, avis=15) for i in range(5)]
    ferme = [_livre(f"B{i}", 5000, avis=3000) for i in range(5)]
    assert openness_score(ouvert) > openness_score(ferme)


def test_series_share_et_price_band():
    livres = [_livre("A1", 2000, prix=2.99, serie=True), _livre("A2", 3000, prix=4.99),
              _livre("A3", 4000, prix=3.99, serie=True)]
    assert series_share(livres) == 2 / 3
    b = price_band(livres)
    assert b[0] == 2.99 and b[-1] == 4.99


def test_les_seuils_sont_exposes_et_documentes():
    """Repères marché, pas vérités : un produit vendu devra les exposer."""
    assert SEUILS["bsr_kindle_excellent"] < SEUILS["bsr_kindle_correct"]
```

- [ ] **Step 2 : Lancer** → FAIL. **Step 3 : Implémenter `01-scripts/fiction_scoring.py`** :
  - `SEUILS` : dict de constantes nommées et commentées, calées sur les mesures live (`bsr_kindle_excellent=5_000`, `bsr_kindle_correct=20_000`, `bsr_kindle_faible=100_000`, `avis_leader_mur=500`, `saturation_haute=0.6`, …).
  - `livres_scorables(livres, classifications, rayon, version="fr_v1")` : garde ceux qui sont `est_payant_dans(label_rayon(rayon))` **et** dont la classification (si elle existe) n'est pas `est_roman=False`. Un livre non classé reste scorable (on ne l'invente pas non-roman).
  - `depth_score(livres) -> float` **BSR-first** : combine le **meilleur** BSR et la **médiane** (un rayon porté par un seul best-seller n'est pas un rayon profond). 0.0 sur liste vide.
  - `openness_score(livres) -> float` : peu d'avis médians = ouvert ; forte dispersion de BSR = ouvert (présence d'un livre mal positionné qui range bien, § « place à prendre ») ; leaders anciens = ouvert si la date est exploitable.
  - `saturation_trio(niche, livres, classifications) -> float` : moyenne, sur les livres classés, du **recouvrement** entre les tropes du trio et ceux du livre (Jaccard ou couverture — au choix, documenté). 0.0 si rien n'est classé (aucune preuve ≠ rayon libre).
  - `series_share(livres)`, `price_band(livres) -> list[float]` (min, médiane, max sur les prix connus).

- [ ] **Step 4 : Lancer** toute la suite → verte. **Step 5 : Commit**
```bash
git add 01-scripts/fiction_scoring.py tests/test_fiction_scoring.py
git commit -m "feat(fiction): métriques de scoring — seuils calés sur les rayons mesurés en live"
```

---

## Task M5-2 : `build_report` — la matrice de demande

**Files:** Modify `01-scripts/fiction_scoring.py` · Test `tests/test_fiction_scoring.py`

La matrice croise **profondeur** (y a-t-il de l'argent ?) et **place** (reste-t-il de la place ?), la saturation du trio servant d'arbitre :

| depth | openness | saturation_trio | `demand_matrix` |
|---|---|---|---|
| haute | haute | basse | `pepite` |
| haute | haute | haute | `porteur_encombre` |
| haute | basse | — | `mur_installe` |
| basse | haute | — | `desert` |
| basse | basse | — | `mort` |

- [ ] **Step 1 : Tests (échouent)** :
```python
def test_matrice_pepite_vs_porteur_encombre():
    """Même rayon profond et ouvert : c'est la saturation du trio — donc la LECTURE DES
    BLURBS — qui distingue une pépite d'un sujet déjà traité par tout le monde."""
    r1 = build_report(_niche(), _shelf_profond(), _classif_trio_absent(), _sig())
    r2 = build_report(_niche(), _shelf_profond(), _classif_trio_partout(), _sig())
    assert r1.demand_matrix == "pepite"
    assert r2.demand_matrix == "porteur_encombre"


def test_autocomplete_ne_gate_jamais_seul():
    """Spike M0 §V3 : un 0 sur un trio cosy est NORMAL (le rayon se navigue). Le verdict
    ne doit pas basculer sur ce seul signal."""
    muet = AutocompleteSignal(niche_query="q", score=0.0, mesure=True,
                              sous_genre_cherche=True)
    parlant = AutocompleteSignal(niche_query="q", score=1.0, mesure=True)
    a = build_report(_niche(), _shelf_profond(), _classif_trio_absent(), muet)
    b = build_report(_niche(), _shelf_profond(), _classif_trio_absent(), parlant)
    assert a.demand_matrix == b.demand_matrix == "pepite"


def test_sonde_non_mesuree_ne_compte_pas_comme_zero():
    """mesure=False : le rapport ne doit pas rendre une note (cf. dette M3 réglée)."""
    r = build_report(_niche(), _shelf_profond(), _classif_trio_absent(),
                     AutocompleteSignal(niche_query="q"))
    assert r.autocomplete_score is None


def test_sous_genre_fantome_est_une_alerte():
    """Le sous-genre lui-même n'est pas cherché -> le signalement remonte dans le verdict."""
    fantome = AutocompleteSignal(niche_query="q", score=0.0, mesure=True,
                                 sous_genre_cherche=False)
    r = build_report(_niche(), _shelf_profond(), _classif_trio_absent(), fantome)
    assert "sous-genre" in r.verdict.lower()


def test_rayon_ampute_est_signale_pas_lu_comme_desert():
    """FictionShelf.n_echecs > 0 : un rayon incomplet ne doit pas passer pour vide (§10)."""
    shelf = _shelf_profond().model_copy(update={"n_echecs": 9})
    r = build_report(_niche(), shelf, _classif_trio_absent(), _sig())
    assert "incomplet" in r.verdict.lower()
```

- [ ] **Step 2 : Lancer** → FAIL. **Step 3 : Implémenter** `build_report(niche, shelf, classifications, signal, version="fr_v1", cost=None) -> FictionNicheReport` :
  - remplit toutes les métriques de M5-1 ;
  - porte l'**`AutocompleteSignal` entier** (jamais son float — dette réglée le 2026-07-20) ;
  - calcule `demand_matrix` selon le tableau, **sans jamais utiliser l'autocomplete comme critère de bascule** ;
  - compose un `verdict` court et tranché, qui **signale explicitement** : un rayon incomplet (`n_echecs > 0`), un sous-genre fantôme, une part de livres non classés, et le fait que la saturation n'est mesurée que sur les livres classés.

- [ ] **Step 4 : Lancer** → verte. **Step 5 : Commit**
```bash
git add 01-scripts/fiction_scoring.py tests/test_fiction_scoring.py
git commit -m "feat(fiction): matrice de demande — la saturation du trio distingue pépite et sujet encombré"
```

---

## Task M5-3 : top 12 par défaut (économie −40 % sur le rayon)

**Files:** Modify `01-scripts/fiction_serp_provider.py`, `01-scripts/build_validation_set.py` · Test existant

Le signal concurrentiel est dans les 12 premiers ; les ASIN 13-20 coûtent 0,024 $ et n'apportent presque rien.

- [ ] **Step 1 : Test** — vérifier que `fetch_fiction_shelf` a bien `n_top: int = 12` par défaut et que passer `n_top=20` reste possible.
- [ ] **Step 2-3** : changer le défaut, **documenter le compromis en commentaire** (`price_band` et `series_share` deviennent plus bruités sur 12 livres que sur 20).
- [ ] **Step 4 : Lancer** → verte. **Step 5 : Commit**
```bash
git commit -am "perf(fiction): rayon top 12 par défaut (-40% de coût ASIN, signal préservé)"
```

---

## Self-Review
- `saturation_trio` est le différenciateur, et il est **impossible sans M4** — c'est ce qui justifie tout le module. ✓
- Titres gratuits, non-romans et mauvais rayon exclus **avant** tout calcul (les trois pièges mesurés au spike). ✓
- Seuils en constantes nommées, calés sur des rayons réellement mesurés — pas de nombre inventé. ✓
- L'autocomplete ne gate jamais ; `mesure=False` ne rend pas de note. ✓
- Rayon incomplet ≠ rayon désert : signalé dans le verdict (§10). ✓
- Aucun réseau, aucun LLM : M5 est du calcul pur, donc entièrement testable. ✓

## Suite
M6 orchestration + UI (**toutes les SERP d'abord, puis UN SEUL batch ASIN global** — sinon 10 niches = 40 min) · puis les briques SaaS (file standard/asynchrone, compteur d'usage).
