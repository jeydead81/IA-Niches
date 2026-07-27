# Mots-clés backend KDP — Plan d'implémentation

> **For agentic workers:** REQUIRED SUB-SKILL: superpowers:subagent-driven-development.

**Goal:** Produire les **7 mots-clés backend** qu'un auteur saisit dans KDP au moment de publier — et, contrairement à tous les outils du marché, **vérifier gratuitement qu'Amazon les suggère réellement** avant de les proposer.

---

## L'angle qui change tout

Les concurrents (Publisher Rocket, KDSPY, Book Bolt) génèrent des mots-clés puis affichent une estimation de volume. Nous avons déjà un canal **gratuit et factuel** : l'autocomplete Amazon.fr, celui qui sert à valider la demande d'une niche.

Donc : le LLM propose ~22 candidats, on les **sonde tous** (0 $), et on ne retient dans les 7 que ce qu'Amazon complète vraiment. Un mot-clé qu'Amazon ne suggère pas est un mot-clé que personne ne tape.

**Coût : un seul appel LLM (~0,01 $).** Le reste est gratuit.

## Les règles KDP sont appliquées EN CODE, pas demandées au LLM

Amazon impose des contraintes dures, et un modèle les oublie sous pression. Le module les fait respecter après coup, comme `fiction_ideator` vérifie la taxonomie :

- **50 caractères maximum** par emplacement (7 emplacements).
- **Ne pas répéter** les mots déjà présents dans le titre, le sous-titre ou la catégorie : Amazon les indexe déjà, les redonner gaspille un emplacement.
- **Termes interdits** par les conditions KDP : « livre », « ebook », « kindle », « gratuit », « meilleur », « nouveau », « promotion », les noms d'auteurs ou de marques, les superlatifs subjectifs et les mentions temporelles (« 2026 »).
- Privilégier les **expressions** (3-5 mots) aux mots isolés : la longue traîne convertit mieux et se dispute moins.

**Tech Stack :** Python 3.13, pytest, pydantic v2, SDK Anthropic (tool-use forcé, client injectable), `amazon_autocomplete` (gratuit).

---

## Task K1 : modèle + règles KDP vérifiées en code

**Files:** Modify `01-scripts/models.py` · Create `01-scripts/kdp_keywords.py` · Test `tests/test_kdp_keywords.py`

- [ ] **Step 1 : Tests (échouent)** :
```python
from kdp_keywords import LIMITE_CARACTERES, TERMES_INTERDITS, nettoyer_candidats
from models import MotsClesKDP


def test_un_emplacement_ne_depasse_jamais_50_caracteres():
    """Contrainte dure de KDP : au-delà, Amazon tronque en silence et l'auteur perd la
    fin de son expression sans le savoir."""
    longs = ["a" * 60, "roman policier village breton"]
    gardes, rejets = nettoyer_candidats(longs, titre="")
    assert all(len(k) <= LIMITE_CARACTERES for k in gardes)
    assert any("50" in r or "long" in r.lower() for _, r in rejets)


def test_les_termes_interdits_par_kdp_sont_ecartes():
    """« livre », « kindle », « gratuit », « meilleur »… sont proscrits par les conditions
    KDP ou sans valeur (Amazon les indexe déjà). Les demander au LLM ne suffit pas."""
    gardes, rejets = nettoyer_candidats(
        ["meilleur livre policier", "kindle gratuit", "enquête village breton"], titre="")
    assert gardes == ["enquête village breton"]
    assert len(rejets) == 2


def test_les_mots_du_titre_ne_sont_pas_regaspilles():
    """Amazon indexe déjà titre et sous-titre : redonner ces mots gâche un emplacement
    sur les sept."""
    gardes, _ = nettoyer_candidats(
        ["cosy mystery bretagne", "enquête pâtissière village"],
        titre="Cosy Mystery en Bretagne")
    assert "cosy mystery bretagne" not in gardes


def test_les_doublons_et_la_casse_sont_normalises():
    gardes, _ = nettoyer_candidats(["Enquête Village", "enquête village", "  enquête  village "],
                                   titre="")
    assert len(gardes) == 1
```

- [ ] **Step 2 : Lancer** → FAIL. **Step 3 : Implémenter**
  - `models.py` : 
    ```python
    class MotsClesKDP(BaseModel):
        """Les 7 emplacements backend KDP + les candidats à vérifier à la main."""
        emplacements: list[str] = Field(default_factory=list)      # <= 7, <= 50 car.
        a_verifier: list[str] = Field(default_factory=list)        # ~15, volume à confirmer
        confirmes_par_amazon: list[str] = Field(default_factory=list)  # sondés avec succès
        rejetes: list[dict] = Field(default_factory=list)          # {mot, motif} — transparence
    ```
  - `kdp_keywords.py` : `LIMITE_CARACTERES = 50`, `TERMES_INTERDITS` (frozenset commenté), `nettoyer_candidats(candidats, titre) -> tuple[list[str], list[tuple[str, str]]]` rendant les gardés **et les rejetés avec leur motif** (§10 : un mot-clé écarté en silence est une décision invisible).

- [ ] **Step 4-5 : Commit** `feat(kdp): modèle des 7 mots-clés + règles KDP vérifiées côté code`

---

## Task K2 : génération + confirmation gratuite par l'autocomplete

**Files:** Modify `01-scripts/kdp_keywords.py` · Test `tests/test_kdp_keywords.py`

- [ ] **Step 1 : Tests (échouent)** — LLM et sonde **injectés**, aucun réseau :
```python
def test_les_mots_confirmes_par_amazon_passent_devant():
    """LE point du module : un mot-clé qu'Amazon ne complète pas est un mot-clé que
    personne ne tape. La sonde est gratuite, donc on ne devine pas — on vérifie."""
    def fausse_sonde(prefixe):
        return ["enquête village breton", "enquête village breton kindle"] \
            if "village breton" in prefixe else []

    r = generer_mots_cles(_niche(), client=_Client({"candidats": [
        "mot jamais cherché", "enquête village breton"]}), sonde=fausse_sonde)
    assert r.emplacements[0] == "enquête village breton"
    assert "enquête village breton" in r.confirmes_par_amazon
    assert "mot jamais cherché" in r.a_verifier      # pas jeté : à vérifier à la main


def test_sept_emplacements_maximum():
    r = generer_mots_cles(_niche(), client=_Client({"candidats": [f"expression {i}" for i in range(30)]}),
                          sonde=lambda p: [p])
    assert len(r.emplacements) == 7


def test_les_rejets_sont_expliques_pas_silencieux():
    """Un mot-clé écarté sans motif est une décision invisible (CLAUDE.md §10)."""
    r = generer_mots_cles(_niche(), client=_Client({"candidats": ["meilleur livre kindle"]}),
                          sonde=lambda p: [])
    assert r.rejetes and "motif" in r.rejetes[0]


def test_une_sonde_en_echec_ne_coule_pas_la_generation():
    """L'autocomplete peut tomber ; on rend alors des candidats non confirmés plutôt que rien."""
    def sonde_ko(prefixe):
        raise RuntimeError("réseau")
    r = generer_mots_cles(_niche(), client=_Client({"candidats": ["enquête village"]}),
                          sonde=sonde_ko)
    assert r.emplacements or r.a_verifier


def test_cout_remonte():
    ...
```

- [ ] **Step 2 : Lancer** → FAIL. **Step 3 : Implémenter** `generer_mots_cles(niche, client=None, sonde=None, model=None, on_usage=None) -> MotsClesKDP`, sur le modèle exact de `niche_verdict.py` (tool-use forcé `proposer_mots_cles`, `DEFAULT_MODEL` par variable d'env `KDP_KEYWORDS_MODEL`, client injectable, `on_usage`) :
  - le prompt demande ~22 expressions de longue traîne, en français, telles qu'un lecteur les taperait ;
  - `nettoyer_candidats` applique les règles KDP ;
  - chaque survivant est **sondé** (défaut `amazon_autocomplete.fetch_suggestions`, gratuit) ; une sonde en échec n'interrompt rien ;
  - les 7 emplacements sont remplis **en priorité par les confirmés**, complétés par les meilleurs non confirmés ;
  - le reste part dans `a_verifier` (~15), les écartés dans `rejetes` avec motif.

- [ ] **Step 4-5 : Commit** `feat(kdp): 7 mots-clés backend confirmés gratuitement par l'autocomplete Amazon`

---

## Task K3 : endpoint + bouton

**Files:** Modify `web/server.py`, `web/index.html` · Test `tests/test_server_kdp.py`

- [ ] `POST /api/kdp-keywords` — sans état, même motif que `/api/verdict` : la niche arrive entière dans le body, 400 propre si invalide, coût imputé au compteur d'usage.
- [ ] Dans l'UI, sur chaque fiche : un bouton « Mots-clés KDP ». Affichage des **7 emplacements copiables un par un** (l'auteur les colle dans les 7 champs KDP), avec pour chacun sa longueur (`38/50`) et une pastille « confirmé par Amazon ». Les `a_verifier` et les `rejetes` (avec motif) sont repliés en dessous.
- [ ] **Commit** `feat(kdp): endpoint et bouton « Mots-clés KDP » sur chaque niche`

---

## Self-Review
- Les règles KDP sont appliquées **en code**, pas seulement demandées au modèle. ✓
- La confirmation par l'autocomplete est **gratuite** et c'est ce qu'aucun concurrent ne fait. ✓
- Les mots écartés sortent **avec leur motif** — jamais de décision invisible (§10). ✓
- Une sonde en échec dégrade (candidats non confirmés) au lieu de tout perdre. ✓
- 7 emplacements et 50 caractères sont des contraintes dures de KDP, testées comme telles. ✓
- Aucun réseau en test : client LLM et sonde injectés. ✓

## Suite
Persistance des runs (historique + delta entre deux passages sur la même niche).
