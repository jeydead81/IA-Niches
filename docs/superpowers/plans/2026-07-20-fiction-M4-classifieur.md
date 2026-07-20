# Fiction M4 — Classifieur de blurb + set de validation — Plan d'implémentation

> **For agentic workers:** REQUIRED SUB-SKILL: superpowers:subagent-driven-development.

**Goal:** Lire les quatrièmes de couverture d'un rayon et en extraire **ce que chaque livre promet réellement** (tropes, décor), pour savoir ce qui est saturé et ce qui manque — puis **prouver** que cette lecture est fiable, sur 50 livres étiquetés par l'IA et corrigés par Baptiste.

C'est le vrai différenciateur du module : n'importe qui peut lire un BSR, personne ne lit 20 blurbs par niche.

**Faits qui pilotent le design** (`docs/spike_fiction_M0.md`, mesurés live) :
- **Blurb disponible à 8/8 (100 %)**, `items[0].description`, 1 200 à 1 800 caractères. L'entrée du classifieur est sûre.
- Mais **`EnrichedBook` ne le porte pas** : `parse_enriched_book` ne mappe pas `description`. Premier trou à combler.
- Un rayon contraint au node contient quand même des **non-romans** : la fixture `2036073689` (428 car., *« En tant que détective expérimenté, vous partez… »*) est un **jeu**, et le #1 « romantasy » du spike était un **livre de coloriage**. Les classer en tropes produirait du bruit ; il faut pouvoir les écarter.

**Asymétrie assumée avec `fiction_ideator`.** L'ideator **écarte** un trio contenant une clé hors taxonomie : il invente, donc on le contraint. Le classifieur **observe** : un trope hors taxonomie vu dans un vrai livre est une **information** qui fait évoluer la taxonomie, pas un déchet. Il part donc dans `other[]`, jamais à la poubelle.

**Coût.** 20 blurbs ≈ 9k tokens d'entrée → un seul appel batché par rayon, ~0,03 $ en Sonnet 5. Un appel par livre coûterait le même prix en tokens mais 20× la latence.

**Tech Stack :** Python 3.13, pytest, pydantic v2, SDK Anthropic (tool-use forcé, client injectable → **aucun réseau en unit-test**), openpyxl (déjà une dépendance).

---

## Task M4-1 : le blurb (et le filtre non-roman) entrent dans les modèles

**Files:** Modify `01-scripts/models.py`, `01-scripts/fiction_books.py` · Test `tests/test_fiction_books.py`, `tests/test_fiction_models.py`

- [ ] **Step 1 : Tests (échouent)** — sur les **fixtures live** :
```python
def test_blurb_extrait_des_payloads_reels():
    b = parse_enriched_book(_PRINT["1923235036"])
    assert b.blurb and len(b.blurb) > 200
    assert "Poppy" in b.blurb            # contenu réel, pas un placeholder


def test_blurb_couverture_totale_sur_la_fixture():
    """M0 mesure 8/8 : si ça tombe, l'entrée du classifieur n'est plus sûre."""
    avec = [a for a in _PRINT if (parse_enriched_book(_PRINT[a]) or EnrichedBook(asin="x", title="")).blurb]
    assert len(avec) == len(_PRINT)


def test_blurb_absent_ne_leve_pas():
    b = parse_enriched_book({"asin": "X", "items": [{"type": "amazon_product_info",
                                                    "title": "T", "description": None}]})
    assert b is not None and b.blurb is None
```
et dans les tests de modèles :
```python
def test_classification_ecarte_les_non_romans():
    c = TropeClassification(asin="A", taxonomy_version="fr_v1", est_roman=False,
                            hors_sujet="jeu de société, pas un roman")
    assert c.est_roman is False and "jeu" in c.hors_sujet
```

- [ ] **Step 2 : Lancer** → FAIL. **Step 3 : Implémenter**
  - `models.py`, dans `EnrichedBook` : `blurb: str | None = None  # items[0].description — entrée du classifieur M4 (100 % de couverture mesurée au spike)`
  - `models.py`, dans `TropeClassification` : 
    ```python
    est_roman: bool = True          # False = jeu, coloriage, cahier… -> hors scoring
    hors_sujet: str = ""            # pourquoi, quand est_roman est False
    ```
  - `fiction_books.py`, dans `parse_enriched_book` : `blurb=_text(item.get("description"))` (le helper existant protège déjà des types inattendus).

- [ ] **Step 4 : Lancer** toute la suite → verte. **Step 5 : Commit**
```bash
git add 01-scripts/models.py 01-scripts/fiction_books.py tests/
git commit -m "feat(fiction): EnrichedBook porte le blurb + TropeClassification sait écarter un non-roman"
```

---

## Task M4-2 : `classify_books` — le classifieur batché

**Files:** Create `01-scripts/fiction_classifier.py` · Test `tests/test_fiction_classifier.py`

- [ ] **Step 1 : Tests (échouent)** — client **injecté**, aucun réseau :
```python
from fiction_classifier import classify_books
from models import EnrichedBook


class _Block:
    type = "tool_use"

    def __init__(self, payload):
        self.input = payload


class _Resp:
    def __init__(self, payload, usage=None):
        self.content = [_Block(payload)]
        self.usage = usage


class _Client:
    """Client Anthropic factice : capture l'appel, rend une réponse figée."""
    def __init__(self, payload, usage=None):
        self.payload, self.usage, self.vu = payload, usage, {}
        self.messages = self

    def create(self, **kw):
        self.vu = kw
        return _Resp(self.payload, self.usage)


def _livres():
    return [EnrichedBook(asin="A1", title="T1", blurb="Une pâtissière enquête au village."),
            EnrichedBook(asin="A2", title="T2", blurb="Un chat, une libraire, un meurtre.")]


def test_cles_hors_taxonomie_vont_dans_other_pas_a_la_poubelle():
    """Asymétrie voulue avec l'ideator : un trope observé dans un vrai livre fait évoluer
    la taxonomie. L'écarter perdrait l'information la plus utile du module."""
    cl = classify_books(_livres(), "cosy_mystery", client=_Client({"livres": [
        {"asin": "A1", "tropes": ["metier_gourmand", "vampires_pirates"],
         "decor": "village_breton", "confidence": 0.8}]}))
    assert cl[0].tropes == ["metier_gourmand"]
    assert cl[0].other == ["vampires_pirates"]
    assert cl[0].taxonomy_version == "fr_v1"


def test_decor_hors_taxonomie_bascule_aussi_dans_other():
    cl = classify_books(_livres(), "cosy_mystery", client=_Client({"livres": [
        {"asin": "A1", "tropes": ["metier_gourmand"], "decor": "station_spatiale"}]}))
    assert cl[0].decor is None and "station_spatiale" in cl[0].other


def test_asin_inconnu_ignore():
    """Le LLM ne doit pas pouvoir inventer un livre qui n'est pas dans le rayon."""
    cl = classify_books(_livres(), "cosy_mystery", client=_Client({"livres": [
        {"asin": "FANTOME", "tropes": ["metier_gourmand"]}]}))
    assert cl == []


def test_non_roman_conserve_mais_marque():
    cl = classify_books(_livres(), "cosy_mystery", client=_Client({"livres": [
        {"asin": "A1", "tropes": [], "est_roman": False, "hors_sujet": "jeu"}]}))
    assert cl[0].est_roman is False and cl[0].hors_sujet == "jeu"


def test_livres_sans_blurb_ne_sont_pas_envoyes():
    """Payer des tokens pour un blurb vide n'apporte rien — et le LLM inventerait."""
    livres = _livres() + [EnrichedBook(asin="A3", title="T3", blurb=None)]
    c = _Client({"livres": []})
    classify_books(livres, "cosy_mystery", client=c)
    envoye = c.vu["messages"][0]["content"]
    assert "A1" in envoye and "A3" not in envoye


def test_aucun_appel_si_aucun_blurb():
    c = _Client({"livres": []})
    assert classify_books([EnrichedBook(asin="A9", title="T")], "cosy_mystery", client=c) == []
    assert c.vu == {}                     # pas d'appel LLM du tout


def test_tool_use_force_et_cout_remonte():
    vus = []
    c = _Client({"livres": []}, usage=type("U", (), {"input_tokens": 100, "output_tokens": 20})())
    classify_books(_livres(), "cosy_mystery", client=c,
                   on_usage=lambda i, o, m: vus.append((i, o, m)))
    assert c.vu["tool_choice"] == {"type": "tool", "name": "classer_livres"}
    assert vus == [(100, 20, c.vu["model"])]
```

- [ ] **Step 2 : Lancer** → FAIL. **Step 3 : Implémenter `01-scripts/fiction_classifier.py`**, sur le modèle exact de `fiction_ideator.py` (mêmes conventions : `DEFAULT_MODEL` par variable d'env `FICTION_CLASSIFIER_MODEL`, `SYSTEM_PROMPT`, `build_user_prompt`, client injectable, `on_usage`), avec :
  - un outil `classer_livres` dont le schéma demande, par livre : `asin`, `tropes[]`, `decor`, `est_roman`, `hors_sujet`, `confidence` ;
  - le prompt **injecte les clés autorisées** du sous-genre et **numérote les blurbs par ASIN** ; il demande explicitement de ne PAS forcer une clé approchante quand aucune ne colle (mieux vaut un `other` honnête) ;
  - la validation **côté code** : clés connues → `tropes`/`decor` ; clés inconnues → `other` ; ASIN hors du lot → ignoré ; `taxonomy_version` estampillée ;
  - **aucun appel** si aucun livre n'a de blurb.

- [ ] **Step 4 : Lancer** → verte. **Step 5 : Commit**
```bash
git add 01-scripts/fiction_classifier.py tests/test_fiction_classifier.py
git commit -m "feat(fiction): classifieur de blurb batché — clés vérifiées côté code, hors-taxo conservé"
```

---

## Task M4-3 : le protocole de validation (mesurable, pas déclaratif)

**Files:** Create `01-scripts/fiction_validation.py` · Test `tests/test_fiction_validation.py`

Le brief exige « ≥ 80 % d'accord sur 50 livres » sans définir *accord*. **Définition retenue, à assumer explicitement dans le rapport** :

- **tropes** : indice de Jaccard entre l'ensemble IA et l'ensemble humain. Deux ensembles vides = accord parfait (1.0) — s'accorder sur « aucun trope » est un accord.
- **décor** : égalité stricte, `None` compris.
- **un livre est en accord** si `jaccard(tropes) ≥ 0.5` **et** décor identique **et** `est_roman` identique.
- **la porte** : ≥ 80 % des livres en accord. En dessous, ce n'est pas le classifieur qu'on rafistole — c'est la **taxonomie** qui est ambiguë, et le rapport doit dire quelles clés.

- [ ] **Step 1 : Tests (échouent)** :
```python
def test_jaccard_deux_vides_est_un_accord():
    assert jaccard(set(), set()) == 1.0


def test_livre_en_accord_exige_les_trois_criteres():
    ia = TropeClassification(asin="A", taxonomy_version="v", tropes=["a", "b"], decor="d")
    hu = TropeClassification(asin="A", taxonomy_version="v", tropes=["a"], decor="d")
    assert accord(ia, hu) is True                        # jaccard 0.5, décor ok
    hu2 = hu.model_copy(update={"decor": "autre"})
    assert accord(ia, hu2) is False                      # décor diverge -> désaccord


def test_rapport_donne_le_taux_et_la_porte():
    paires = [(TropeClassification(asin=str(i), taxonomy_version="v", tropes=["a"]),
               TropeClassification(asin=str(i), taxonomy_version="v",
                                   tropes=["a"] if i < 8 else ["z"])) for i in range(10)]
    r = agreement_report(paires)
    assert r.n_livres == 10 and r.n_accord == 8
    assert r.taux == 0.8 and r.porte_franchie is True


def test_rapport_pointe_les_cles_litigieuses():
    """Sous la porte, il faut savoir QUELLE clé pose problème — sinon on ne peut rien corriger."""
    paires = [(TropeClassification(asin="1", taxonomy_version="v", tropes=["flou"]),
               TropeClassification(asin="1", taxonomy_version="v", tropes=["net"]))]
    r = agreement_report(paires)
    assert r.porte_franchie is False
    assert r.cles_litigieuses["flou"]["ia_seule"] == 1
    assert r.cles_litigieuses["net"]["humain_seul"] == 1


def test_export_puis_relecture_conserve_les_etiquettes(tmp_path):
    """Aller-retour Excel : ce que Baptiste corrige doit revenir tel quel."""
    livres = [EnrichedBook(asin="A1", title="Titre", blurb="Un blurb.")]
    ia = [TropeClassification(asin="A1", taxonomy_version="fr_v1",
                              tropes=["metier_gourmand"], decor="village_breton")]
    p = tmp_path / "valid.xlsx"
    export_validation(livres, ia, "cosy_mystery", p)
    assert p.exists()
    relu = load_corrections(p)            # sans correction humaine -> colonnes vides
    assert relu == []                     # rien de corrigé = rien à comparer
```

- [ ] **Step 2 : Lancer** → FAIL. **Step 3 : Implémenter `01-scripts/fiction_validation.py`** :
  - `jaccard(a: set, b: set) -> float` (deux vides → 1.0) ;
  - `accord(ia, humain) -> bool` selon la définition ci-dessus ;
  - `AgreementReport` (pydantic) : `n_livres`, `n_accord`, `taux`, `porte_franchie`, `cles_litigieuses: dict[str, dict[str, int]]` (`ia_seule` / `humain_seul` par clé), `desaccords: list[str]` (ASIN) ;
  - `agreement_report(paires) -> AgreementReport` ;
  - `export_validation(livres, classifications, sous_genre_cle, path)` → **xlsx openpyxl** : feuille 1 une ligne par livre (ASIN, titre, auteur, blurb tronqué à ~600 car., `tropes_ia`, `decor_ia`, `est_roman_ia`, `confiance`, puis les colonnes **vides** `tropes_ok`, `decor_ok`, `est_roman_ok`, `notes`), colonnes larges et blurb en retour à la ligne ; feuille 2 = **les clés autorisées du sous-genre**, à copier-coller ;
  - `load_corrections(path) -> list[TropeClassification]` : ne rend que les lignes **effectivement corrigées** (au moins une colonne `*_ok` remplie) — une ligne laissée vide n'est pas un avis, et la compter comme un accord gonflerait le taux.

- [ ] **Step 4 : Lancer** → verte. **Step 5 : Commit**
```bash
git add 01-scripts/fiction_validation.py tests/test_fiction_validation.py
git commit -m "feat(fiction): protocole de validation du classifieur (Jaccard, porte 80 %, clés litigieuses)"
```

---

## Task M4-4 : CLI de constitution du set de 50 livres

**Files:** Create `01-scripts/build_validation_set.py` · Test `tests/test_build_validation_set.py`

- [ ] **Step 1 : Test (échoue)** — dépendances injectées, **aucun réseau** :
```python
def test_assemble_les_rayons_et_deduplique(tmp_path):
    livres = [EnrichedBook(asin="A1", title="T", blurb="b"),
              EnrichedBook(asin="A2", title="T", blurb="b")]

    def faux_shelf(niche, **kw):
        return FictionShelf(niche=niche, search_param="x", books=livres,
                            asins_demandes=2)

    out = tmp_path / "v.xlsx"
    n = build_set([_niche("cosy mystery a"), _niche("cosy mystery b")], out,
                  fetch_shelf=faux_shelf,
                  classify=lambda bks, sg, **kw: [
                      TropeClassification(asin=b.asin, taxonomy_version="fr_v1") for b in bks])
    assert n == 2                 # A1/A2 vus deux fois -> comptés une seule
    assert out.exists()
```

- [ ] **Step 2 : Lancer** → FAIL. **Step 3 : Implémenter `01-scripts/build_validation_set.py`** : `build_set(niches, path, fetch_shelf=..., classify=..., n_top=20, cache=..., cost=...) -> int` qui enchaîne rayon → classification → export, **déduplique par ASIN** entre niches, ignore les livres sans blurb, et affiche le coût réel en fin de course. Plus un `main()` argparse (`--sous-genre`, `--n-niches`, `--out`) pour l'usage réel.

- [ ] **Step 4 : Lancer** → verte. **Step 5 : Commit**
```bash
git add 01-scripts/build_validation_set.py tests/test_build_validation_set.py
git commit -m "feat(fiction): CLI de constitution du set de validation (50 livres, dédupliqué)"
```

---

## Ce qui est demandé à Baptiste (une seule fois, ~1 h)
1. Je produis `validation-fiction-[date].xlsx` : 50 livres, blurb lisible, étiquettes IA pré-remplies.
2. Il corrige **uniquement ce qui lui semble faux**, dans les colonnes `*_ok` (feuille 2 = les clés autorisées à copier-coller).
3. Je relis le fichier et sors le rapport d'accord : taux, porte 80 %, et **quelles clés de taxonomie sont litigieuses**.
4. Sous 80 %, on corrige la **taxonomie** (clés ambiguës, définitions à trancher) avant de toucher au prompt — un classifieur ne peut pas être plus net que les catégories qu'on lui donne.

## Self-Review
- Entrée du classifieur sécurisée d'abord (le blurb n'était pas mappé — M4 aurait classé du vide). ✓
- Hors-taxonomie **conservé** dans `other` : c'est le signal qui fait évoluer la taxo, l'écarter serait la pire perte du module. ✓
- Non-romans (jeu, coloriage — vus au spike) marqués au lieu d'être classés en bruit. ✓
- Un seul appel LLM par rayon ; aucun appel si aucun blurb ; coût remonté au `CostTracker`. ✓
- ASIN inventé par le LLM → ignoré (il ne peut pas ajouter un livre au rayon). ✓
- « 80 % d'accord » enfin **défini** et mesurable, et une ligne non corrigée n'est pas comptée comme un accord. ✓
- Aucun réseau en unit-test (client et fetchers injectés). ✓

## Suite
M5 scoring (matrice de demande — porter l'`AutocompleteSignal` entier, cf. dette réglée le 2026-07-20 ; barème non uniforme romance vs cosy) · M6 orchestration/UI · puis le compteur de crédits.
