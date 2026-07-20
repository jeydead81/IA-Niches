# Fiction M1 — Taxonomie, modèles, parseur BSR multi-rayon, ideator — Plan d'implémentation

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development. Steps use checkbox (`- [ ]`) syntax.

**Goal:** Poser les fondations du module Fiction : une **taxonomie versionnée** (6 sous-genres FR, nodes Kindle **et** papier), les **modèles pydantic**, un **parseur BSR multi-rayon** qui distingue Boutique Kindle / Livres et **rejette les classements « titres gratuits »**, et l'**ideator fiction** (trios contraints à la taxonomie).

**Architecture :** Le **rayon** (`kindle` défaut | `papier`) et le **marketplace** (`fr`) sont des paramètres de premier rang — changer de rayon = changer un paramètre + remplir `node_papier`. La taxonomie est un fichier de **données versionné** (`fr_v1`) dont la version entre dans la clé de cache du futur classifieur. Tout ce qui est LLM passe en **tool-use forcé** avec client injectable ; aucun appel réseau en unit-test.

**Faits du terrain (spike M0 + récoltes M1 — tout est vérifié, rien n'est supposé) :**
- `search_param=i=digital-text` **contraint bien au rayon Kindle** (16 organiques vs 48-53 sans contrainte) ; `i=stripbooks` = papier.
- **BSR payant** : `« 20 en Boutique Kindle ( … ) »` / `« 1 597 en Livres ( … ) »`.
- **BSR gratuit** : `« n°478 des titres gratuits dans la Boutique Kindle ( … ) »` — **un autre classement**, pas des ventes payantes. **25 % du top Kindle échantillonné sont des titres gratuits.**
- Les rangs **Livres** et **Boutique Kindle** ne sont **pas comparables**.
- Série : clé structurée **`Livre N sur M`** (tome + longueur), présente ~50 % ; fallback heuristique sinon.
- `bought_past_month` et le badge **KU** n'existent pas sur amazon.fr → hors modèles.
- 2 des 6 sous-genres n'ont **pas de rayon Amazon** (feel-good, et romance/dark en partagent un) → **mode « rayon requête »** par sous-genre.

**Tech Stack :** Python 3.13, pytest (`pythonpath=01-scripts`, `testpaths=tests`), pydantic v2, Anthropic SDK (tool-use forcé).

---

## Task F1 : Taxonomie versionnée + chargeur validé

**Files:** Create `data/fiction_taxonomy_fr_v1.json` · Create `01-scripts/fiction_taxonomy.py` · Test `tests/test_fiction_taxonomy.py`

- [ ] **Step 1 : Créer `data/fiction_taxonomy_fr_v1.json`** (nodes issus des récoltes réelles ; `null` = pas de rayon Amazon → mode requête) :
```json
{
  "version": "fr_v1",
  "marketplace": "fr",
  "rayon_defaut": "kindle",
  "filtres_rayon": { "kindle": "i=digital-text", "papier": "i=stripbooks" },
  "sous_genres": {
    "cosy_mystery": {
      "label": "Cosy mystery",
      "query_fr": "cosy mystery",
      "node_kindle": "205566725031",
      "node_papier": "9691472031",
      "tropes": ["enquetrice_amatrice", "petite_communaute", "animal_compagnon",
                 "metier_gourmand", "librairie_ou_fleuriste", "retour_au_village",
                 "duo_improbable", "paranormal_leger", "huis_clos_festif"],
      "decors": ["village_breton", "provence", "cote_normande", "cotswolds_uk",
                 "ile", "montagne", "bord_de_mer", "petite_ville"]
    },
    "thriller_psychologique": {
      "label": "Thriller psychologique",
      "query_fr": "thriller psychologique",
      "node_kindle": "205566731031",
      "node_papier": "302068",
      "tropes": ["narrateur_non_fiable", "secret_de_famille", "voisin_inquietant",
                 "disparition", "amnesie", "manipulation_conjugale",
                 "huis_clos_domestique", "double_vie"],
      "decors": ["banlieue_pavillonnaire", "chalet_isole", "bord_de_mer_hors_saison",
                 "grande_ville", "campagne_isolee", "maison_de_famille"]
    },
    "romantasy": {
      "label": "Romantasy",
      "query_fr": "romantasy",
      "node_kindle": "895261031",
      "node_papier": null,
      "tropes": ["ennemis_to_lovers", "elu_prophetie", "dragons", "cour_feerique",
                 "academie_magie", "lien_ame_soeur", "malediction", "mariage_force"],
      "decors": ["royaume_feerique", "academie", "montagne_glace", "cite_antique",
                 "foret_ancienne", "cour_royale"]
    },
    "romance_contemporaine": {
      "label": "Romance contemporaine",
      "query_fr": "romance contemporaine",
      "node_kindle": "894269031",
      "node_papier": null,
      "tropes": ["seconde_chance", "faux_couple", "ennemis_to_lovers", "slow_burn",
                 "frere_du_meilleur_ami", "small_town", "celebrite_anonyme",
                 "coloc_forcee"],
      "decors": ["small_town", "grande_ville", "bord_de_mer", "montagne",
                 "milieu_sportif", "milieu_medical"]
    },
    "dark_romance": {
      "label": "Dark romance",
      "query_fr": "dark romance",
      "node_kindle": "894269031",
      "node_papier": null,
      "tropes": ["mafia", "possessif_obsessionnel", "captivite", "vengeance",
                 "mariage_arrange", "anti_heros", "triangle_toxique", "omegaverse"],
      "decors": ["milieu_mafieux", "campus", "milieu_criminel", "huis_clos",
                 "monde_underground"]
    },
    "feel_good": {
      "label": "Feel-good",
      "query_fr": "roman feel good",
      "node_kindle": null,
      "node_papier": null,
      "tropes": ["reconstruction_apres_rupture", "changement_de_vie",
                 "heritage_inattendu", "retour_aux_sources",
                 "amitie_intergenerationnelle", "deuil_lumineux", "seconde_carriere"],
      "decors": ["village", "bord_de_mer", "montagne", "librairie_cafe", "ferme", "ile"]
    }
  },
  "saisonnalite": {
    "noel": { "cles": ["huis_clos_festif", "montagne", "montagne_glace"],
              "fenetre": "oct-dec", "risque_hors_saison": "fort" },
    "ete": { "cles": ["bord_de_mer", "ile", "cote_normande"],
             "fenetre": "mai-aout", "risque_hors_saison": "moyen" }
  }
}
```

- [ ] **Step 2 : Test (échoue)** — `tests/test_fiction_taxonomy.py` :
```python
import pytest
from fiction_taxonomy import load_taxonomy, sous_genre, node_for, search_param_for, valid_keys


def test_load_and_shape():
    t = load_taxonomy()
    assert t["version"] == "fr_v1" and t["rayon_defaut"] == "kindle"
    assert len(t["sous_genres"]) == 6
    for k, sg in t["sous_genres"].items():
        assert sg["label"] and sg["query_fr"]
        assert sg["tropes"] and sg["decors"]
        assert all(x == x.lower() and " " not in x for x in sg["tropes"] + sg["decors"])


def test_node_for_rayon_et_repli_requete():
    assert node_for("cosy_mystery", "kindle") == "205566725031"
    assert node_for("cosy_mystery", "papier") == "9691472031"
    assert node_for("feel_good", "kindle") is None          # pas de rayon -> mode requête
    assert node_for("romantasy", "papier") is None


def test_search_param_par_rayon():
    assert search_param_for("kindle") == "i=digital-text"
    assert search_param_for("papier") == "i=stripbooks"
    with pytest.raises(ValueError):
        search_param_for("audio")


def test_valid_keys_contraint_le_classifieur():
    tropes, decors = valid_keys("cosy_mystery")
    assert "enquetrice_amatrice" in tropes and "village_breton" in decors
    assert "mafia" not in tropes                            # trope d'un autre sous-genre


def test_sous_genre_inconnu_leve():
    with pytest.raises(KeyError):
        sous_genre("space_opera")
```

- [ ] **Step 3 : Lancer** `python -m pytest tests/test_fiction_taxonomy.py -v` → FAIL (module absent).

- [ ] **Step 4 : Implémenter `01-scripts/fiction_taxonomy.py`** :
```python
"""fiction_taxonomy.py — chargement + validation de la taxonomie fiction versionnée.
Le classifieur ne sortira QUE des clés de cette taxo (+ un champ libre `other`).
Le rayon (kindle/papier) et le marketplace sont des paramètres : un node absent
(`null`) bascule le couple sous-genre × rayon en mode « rayon requête »."""
import json
from functools import lru_cache
from pathlib import Path

_DATA = Path(__file__).resolve().parent.parent / "data"
_FILTRES = {"kindle": "i=digital-text", "papier": "i=stripbooks"}


@lru_cache(maxsize=4)
def load_taxonomy(version: str = "fr_v1") -> dict:
    p = _DATA / f"fiction_taxonomy_{version}.json"
    if not p.exists():
        raise FileNotFoundError(f"taxonomie introuvable : {p}")
    return json.loads(p.read_text(encoding="utf-8"))


def sous_genre(cle: str, version: str = "fr_v1") -> dict:
    sgs = load_taxonomy(version)["sous_genres"]
    if cle not in sgs:
        raise KeyError(f"sous-genre inconnu : {cle} (dispo : {sorted(sgs)})")
    return sgs[cle]


def node_for(cle: str, rayon: str = "kindle", version: str = "fr_v1") -> str | None:
    """Browse node du sous-genre pour ce rayon. None -> mode « rayon requête »."""
    if rayon not in _FILTRES:
        raise ValueError(f"rayon inconnu : {rayon}")
    return sous_genre(cle, version).get(f"node_{rayon}")


def search_param_for(rayon: str) -> str:
    if rayon not in _FILTRES:
        raise ValueError(f"rayon inconnu : {rayon} (dispo : {sorted(_FILTRES)})")
    return _FILTRES[rayon]


def valid_keys(cle: str, version: str = "fr_v1") -> tuple[list[str], list[str]]:
    """(tropes, décors) autorisés pour ce sous-genre — contraint la sortie du classifieur."""
    sg = sous_genre(cle, version)
    return list(sg["tropes"]), list(sg["decors"])
```

- [ ] **Step 5 : Lancer** `python -m pytest -q` → suite verte (5 tests ajoutés).
- [ ] **Step 6 : Commit**
```bash
git add data/fiction_taxonomy_fr_v1.json 01-scripts/fiction_taxonomy.py tests/test_fiction_taxonomy.py
git commit -m "feat(fiction): taxonomie fr_v1 (6 sous-genres, nodes kindle+papier) + chargeur validé"
```

---

## Task F2 : Modèles pydantic fiction

**Files:** Modify `01-scripts/models.py` · Test `tests/test_fiction_models.py`

> Ajustés aux faits : **pas** de `bought_past_month`, **pas** de `is_ku` (inexistants sur amazon.fr) ; série en `serie_tome`/`serie_total` ; **`bsr_rayon`** obligatoire pour ne jamais mélanger deux classements ; `bsr_gratuit` pour écarter les titres gratuits du scoring.

- [ ] **Step 1 : Test (échoue)** — `tests/test_fiction_models.py` :
```python
from models import FictionNiche, EnrichedBook, TropeClassification, FictionNicheReport


def test_fiction_niche_defauts():
    n = FictionNiche(sous_genre="cosy_mystery", tropes=["animal_compagnon"], query="cosy mystery chat")
    assert n.marketplace == "fr" and n.rayon == "kindle" and n.decor is None


def test_enriched_book_rayon_et_gratuit():
    b = EnrichedBook(asin="B1", title="T", bsr=20, bsr_rayon="Boutique Kindle",
                     bsr_gratuit=False, serp_position=1)
    assert b.est_payant_dans("Boutique Kindle") is True
    b2 = EnrichedBook(asin="B2", title="T", bsr=73, bsr_rayon="Boutique Kindle",
                      bsr_gratuit=True, serp_position=2)
    assert b2.est_payant_dans("Boutique Kindle") is False      # titre gratuit -> exclu
    b3 = EnrichedBook(asin="B3", title="T", bsr=1597, bsr_rayon="Livres", serp_position=3)
    assert b3.est_payant_dans("Boutique Kindle") is False       # mauvais rayon -> exclu


def test_serie_structuree():
    b = EnrichedBook(asin="B1", title="T", serp_position=1, serie_tome=5, serie_total=6)
    assert b.est_serie is True
    assert EnrichedBook(asin="B2", title="T", serp_position=2, series_hint=True).est_serie is True
    assert EnrichedBook(asin="B3", title="T", serp_position=3).est_serie is False


def test_classification_et_report():
    c = TropeClassification(asin="B1", taxonomy_version="fr_v1", tropes=["mafia"],
                            decor="campus", other=["x"], confidence=0.8)
    r = FictionNicheReport(
        niche=FictionNiche(sous_genre="dark_romance", tropes=["mafia"], query="dark romance mafia"),
        books=[], classifications=[c], depth_score=0.4, openness_score=0.7,
        saturation_trio=0.2, autocomplete_score=0.5, demand_matrix="ouvert_valide")
    assert r.demand_matrix == "ouvert_valide" and r.classifications[0].asin == "B1"
```

- [ ] **Step 2 : Lancer** → FAIL (ImportError).

- [ ] **Step 3 : Implémenter** — ajouter à `01-scripts/models.py` (à la fin) :
```python
class FictionNiche(BaseModel):
    """Un trio fiction : sous-genre × trope(s) × décor, sur un marketplace et un rayon."""
    sous_genre: str
    tropes: list[str] = Field(default_factory=list)     # 1..3 clés de la taxonomie
    decor: str | None = None
    marketplace: str = "fr"                             # paramètre de premier rang
    rayon: str = "kindle"                               # "kindle" | "papier" — commutable
    query: str = ""                                     # requête naturelle dérivée


class EnrichedBook(BaseModel):
    """Un livre du rayon, enrichi via l'endpoint ASIN. Le BSR porte TOUJOURS son rayon :
    les rangs « Livres » et « Boutique Kindle » ne sont pas comparables, et un classement
    « titres gratuits » n'est pas un rang de ventes payantes."""
    asin: str
    title: str
    author: str | None = None
    price: float | None = None
    reviews_count: int | None = None
    rating: float | None = None
    bsr: int | None = None
    bsr_rayon: str | None = None                        # "Boutique Kindle" | "Livres"
    bsr_gratuit: bool = False                           # rang « titres gratuits » -> hors scoring
    bsr_subcats: list[dict] = Field(default_factory=list)
    publication_date: str | None = None
    publisher: str | None = None
    langue: str | None = None
    serie_tome: int | None = None                       # clé « Livre N sur M »
    serie_total: int | None = None
    series_hint: bool = False                           # fallback heuristique
    serp_position: int = 0

    @property
    def est_serie(self) -> bool:
        return bool(self.serie_total or self.series_hint)

    def est_payant_dans(self, rayon_vise: str) -> bool:
        """Le BSR est-il exploitable pour le scoring de ce rayon ?"""
        return bool(self.bsr) and not self.bsr_gratuit and self.bsr_rayon == rayon_vise


class TropeClassification(BaseModel):
    """Classification sémantique d'un blurb, contrainte à la taxonomie."""
    asin: str
    taxonomy_version: str
    tropes: list[str] = Field(default_factory=list)
    decor: str | None = None
    other: list[str] = Field(default_factory=list)      # hors taxo -> fait évoluer la taxo
    confidence: float = 0.0


class FictionNicheReport(BaseModel):
    """Rapport complet d'une niche fiction (couches 1 et 2)."""
    niche: FictionNiche
    books: list[EnrichedBook] = Field(default_factory=list)
    classifications: list[TropeClassification] = Field(default_factory=list)
    depth_score: float = 0.0
    openness_score: float = 0.0
    saturation_trio: float = 0.0
    autocomplete_score: float = 0.0
    demand_matrix: str = ""
    series_share: float = 0.0
    price_band: list[float] = Field(default_factory=list)
    seasonality: str | None = None
    verdict: str = ""
    cost_run: float = 0.0
```

- [ ] **Step 4 : Lancer** `python -m pytest -q` → vert. **Step 5 : Commit**
```bash
git add 01-scripts/models.py tests/test_fiction_models.py
git commit -m "feat(fiction): modèles pydantic (FictionNiche, EnrichedBook, TropeClassification, Report)"
```

---

## Task F3 : Parseur BSR multi-rayon (Kindle + Livres, hors titres gratuits)

**Files:** Modify `01-scripts/search_providers.py` · Test `tests/test_bsr_rayon.py`

- [ ] **Step 1 : Test (échoue)** — `tests/test_bsr_rayon.py`, **chaînes réelles relevées en récolte** :
```python
from search_providers import parse_bsr_rank


def test_rang_papier():
    assert parse_bsr_rank("1 597 en Livres ( Voir les 100 premiers en Livres )  6 en Enquêtes") \
        == (1597, "Livres", False)


def test_rang_kindle_payant():
    assert parse_bsr_rank("20 en Boutique Kindle ( Voir les 100 premiers en Boutique Kindle )  4 en Romance") \
        == (20, "Boutique Kindle", False)
    assert parse_bsr_rank("2 968 en Boutique Kindle ( Voir les 100 premiers en Boutique Kindle )") \
        == (2968, "Boutique Kindle", False)


def test_titres_gratuits_signales():
    rang, rayon, gratuit = parse_bsr_rank(
        "n°478 des titres gratuits dans la Boutique Kindle ( Voir les 100 premiers en Boutique Kindle )"
        "  5 en Livres électroniques de fiction criminelle")
    assert (rang, rayon) == (478, "Boutique Kindle") and gratuit is True


def test_sous_categorie_jamais_prise_pour_le_rayon():
    # le « 5 en Livres électroniques… » ne doit jamais devenir le rang principal
    rang, rayon, _ = parse_bsr_rank(
        "n°73 des titres gratuits dans la Boutique Kindle ( … )  1 en Livres électroniques de romance")
    assert rang == 73 and rayon == "Boutique Kindle"


def test_vide():
    assert parse_bsr_rank("") == (None, None, False)
    assert parse_bsr_rank(None) == (None, None, False)
```

- [ ] **Step 2 : Lancer** → FAIL (fonction absente).

- [ ] **Step 3 : Implémenter** — ajouter dans `01-scripts/search_providers.py`, à côté de `parse_asin_bsr` :
```python
_BSR_RAYON = re.compile(r".*?(?:\ben\b|\bdans\s+la\b)\s+(.+?)\s*$", re.I | re.S)


def parse_bsr_rank(raw) -> tuple[int | None, str | None, bool]:
    """(rang, rayon, gratuit) depuis une chaîne BSR Amazon.

    Le rang PRINCIPAL est dans la tête de chaîne (avant la 1re parenthèse) ; les
    sous-catégories suivent et ne doivent jamais être prises pour le rayon.
    « titres gratuits » = classement des gratuits, PAS un rang de ventes payantes."""
    head = (raw or "").split("(")[0].strip()
    if not head:
        return None, None, False
    gratuit = "gratuit" in head.lower()
    m = _BSR_RAYON.match(head)
    rayon = m.group(1).strip(" .,;:") if m else None
    num = re.search(r"([\d][\d\s .]*)", head)
    return (_bsr_to_int(num.group(1)) if num else None), rayon, gratuit
```

- [ ] **Step 4 : Lancer** `python -m pytest -q` → vert (l'existant `parse_asin_bsr` reste inchangé). **Step 5 : Commit**
```bash
git add 01-scripts/search_providers.py tests/test_bsr_rayon.py
git commit -m "feat(fiction): parse_bsr_rank — rang + rayon + drapeau titres gratuits"
```

---

## Task F4 : Ideator fiction (trios contraints à la taxonomie)

**Files:** Create `01-scripts/fiction_ideator.py` · Test `tests/test_fiction_ideator.py`

- [ ] **Step 1 : Test (échoue)** — `tests/test_fiction_ideator.py` :
```python
from fiction_ideator import generate_trios, build_user_prompt
from models import FictionNiche


def test_prompt_contient_la_taxonomie_du_sous_genre():
    p = build_user_prompt("cosy_mystery", n=3, rayon="kindle")
    assert "cosy_mystery" in p and "enquetrice_amatrice" in p and "village_breton" in p
    assert "mafia" not in p                        # tropes d'un autre sous-genre exclus


def test_generate_trios_contraint_et_usage():
    class _Usage:
        input_tokens = 700
        output_tokens = 900

    class _Block:
        type = "tool_use"
        input = {"trios": [
            {"tropes": ["animal_compagnon", "petite_communaute"], "decor": "village_breton",
             "query": "cosy mystery chat village breton", "rationale": "r"},
            {"tropes": ["mafia"], "decor": "campus",              # HORS taxo -> doit être filtré
             "query": "x", "rationale": "r"}]}

    class _Resp:
        content = [_Block()]
        usage = _Usage()

    class _Client:
        class messages:
            @staticmethod
            def create(**kw):
                assert kw["tool_choice"]["type"] == "tool"
                return _Resp()

    seen = {}
    trios = generate_trios("cosy_mystery", n=2, client=_Client(),
                           on_usage=lambda i, o, m: seen.update(i=i, o=o))
    assert len(trios) == 1                         # le trio hors taxonomie est écarté
    t = trios[0]
    assert isinstance(t, FictionNiche)
    assert t.sous_genre == "cosy_mystery" and t.decor == "village_breton"
    assert set(t.tropes) <= {"animal_compagnon", "petite_communaute"}
    assert t.rayon == "kindle" and t.marketplace == "fr"
    assert seen == {"i": 700, "o": 900}
```

- [ ] **Step 2 : Lancer** → FAIL. **Step 3 : Implémenter `01-scripts/fiction_ideator.py`** — calqué sur `niche_ideator.py` : `DEFAULT_MODEL = os.getenv("FICTION_IDEATOR_MODEL", "claude-sonnet-5")`, `_default_client()` identique, `build_user_prompt(sous_genre, n, rayon)` qui **injecte la liste exacte des tropes/décors autorisés** (via `fiction_taxonomy.valid_keys`), un `TRIOS_INPUT_SCHEMA` (tool-use forcé, outil `proposer_trios`, chaque trio = `tropes[]`, `decor`, `query`, `rationale`), et `generate_trios(sous_genre, n=8, rayon="kindle", model=None, client=None, on_usage=None) -> list[FictionNiche]` qui :
  1. appelle le LLM en tool-use forcé,
  2. remonte l'usage via `on_usage` (comme l'ideator non-fiction),
  3. **filtre** : tout trio dont un trope ou le décor n'est pas dans `valid_keys(sous_genre)` est **écarté** (le brief impose la contrainte taxonomie — on ne fait pas confiance au LLM, on vérifie),
  4. renvoie des `FictionNiche(sous_genre=…, tropes=…, decor=…, marketplace="fr", rayon=rayon, query=…)`.

  Le SYSTEM_PROMPT reprend la posture des ideators existants (auteur/éditeur FR, tranché, evergreen, exclusions KDP) **plus** : « tu ne proposes QUE des tropes et décors de la liste fournie » et « la `query` doit être ce qu'un lecteur tape réellement sur Amazon ».

- [ ] **Step 4 : Lancer** `python -m pytest -q` → vert. **Step 5 : Commit**
```bash
git add 01-scripts/fiction_ideator.py tests/test_fiction_ideator.py
git commit -m "feat(fiction): fiction_ideator — trios contraints à la taxonomie (tool-use forcé)"
```

---

## Self-Review
- Rayon **commutable** (`kindle` défaut, `papier` prêt) : F1 (`node_kindle`/`node_papier`, `search_param_for`) + F2 (`FictionNiche.rayon`, `EnrichedBook.bsr_rayon`) + F3 (rayon détecté). ✓
- **Titres gratuits** écartés du scoring : F3 (drapeau) + F2 (`est_payant_dans`). ✓
- Champs inexistants (**`bought_past_month`, KU**) absents des modèles. ✓ Série structurée + fallback. ✓
- Sous-genres **sans rayon** → `null` → mode requête, sans cas particulier dans le code. ✓
- Contrainte taxonomie **vérifiée côté code** (F4 filtre), pas seulement demandée au LLM. ✓
- Aucun réseau en test (client injecté partout). ✓

## Suite (hors périmètre M1)
M2 acquisition (SERP contrainte + enrichissement ASIN → `EnrichedBook`), M3 sonde autocomplete, M4 classifieur de blurb + validation 50 livres, M5 scoring (depth **BSR-first**, matrice de demande), M6 orchestration/UI. Puis le **compteur de crédits**.
