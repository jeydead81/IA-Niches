# Fiction M3 — Sonde autocomplete (soft signal) — Plan d'implémentation

> **For agentic workers:** REQUIRED SUB-SKILL: superpowers:subagent-driven-development.

**Goal:** Mesurer, **gratuitement**, si une niche fiction est réellement tapée dans la barre de recherche amazon.fr, et rendre ce signal exploitable par M5 **sans jamais qu'il puisse gater seul**.

**Faits qui pilotent le design** (`docs/spike_fiction_M0.md` §V3, mesuré live sur 10 requêtes) :
- Les requêtes commerciales larges sont riches (`romance milliardaire` → 4 suggestions), les trios trope × décor précis ne remontent **rien** (`romantasy ennemis` → 0). C'est **attendu**, pas un défaut de la niche.
- Verdict du spike : **soft signal, score 0 / 0,5 / 1, ne gate JAMAIS seul**, sert uniquement à désambiguïser la matrice de demande M5.
- L'autocomplete est **préfixe-based** : tester un libellé long produit des faux négatifs (leçon déjà payée sur le scout non-fiction, cf. `requete_amazon`).

**Décision de conception — l'échelle à deux barreaux.** Sonder la seule requête du trio ne permet pas de distinguer deux situations opposées :

| barreau 1 (`niche.query`) | barreau 2 (`sous_genre.query_fr`) | lecture |
|---|---|---|
| 0 | 1 | trio trop précis pour l'autocomplete — **normal**, aucune conclusion négative |
| 0 | 0 | le **sous-genre lui-même** n'est pas un terme de recherche FR — vrai signal d'alerte |
| ≥ 0,5 | — | le trio est tapé tel quel — signal positif franc |

Seul le barreau 1 est scoré ; le barreau 2 est du contexte. Sans lui, M5 confondrait « niche pointue » et « sous-genre fantôme ».

**Décision de conception — l'échec doit être visible.** `amazon_autocomplete._default_fetch_json` rend `{}` aussi bien sur HTTP 503 que sur une vraie absence de suggestions. Un score 0 signifierait alors indifféremment « personne ne cherche ça » (conclusion forte) et « le réseau a toussé » (aucune information). CLAUDE.md §10 l'interdit : la sonde doit porter son propre échec.

**Tech Stack :** Python 3.13, pytest (`pythonpath=01-scripts`, `testpaths=tests`), pydantic v2. **Aucun coût** : endpoint public gratuit.

---

## Task M3-1 : `fetch_json_strict` — un échec réseau cesse d'être un « 0 »

**Files:** Modify `01-scripts/amazon_autocomplete.py` · Test `tests/test_amazon_autocomplete.py`

Ne PAS changer le comportement de `fetch_suggestions` : le scout non-fiction (`niche_validator`) s'appuie dessus en production et son mode « silencieux » lui convient. On **extrait** la variante stricte et on fait déléguer l'ancienne, pour garder une seule implémentation d'URL et de parsing.

- [ ] **Step 1 : Tests (échouent)** — ajouter à `tests/test_amazon_autocomplete.py` :
```python
import pytest

from amazon_autocomplete import AutocompleteError, fetch_json_strict


class _Resp:
    def __init__(self, status_code, text):
        self.status_code, self.text = status_code, text


def test_strict_leve_sur_http_non_200(monkeypatch):
    monkeypatch.setattr("util.http_get", lambda url, timeout=15: _Resp(503, ""))
    with pytest.raises(AutocompleteError):
        fetch_json_strict("cosy mystery")


def test_strict_leve_sur_json_invalide(monkeypatch):
    monkeypatch.setattr("util.http_get", lambda url, timeout=15: _Resp(200, "<html>"))
    with pytest.raises(AutocompleteError):
        fetch_json_strict("cosy mystery")


def test_strict_rend_le_json_quand_tout_va_bien(monkeypatch):
    monkeypatch.setattr("util.http_get",
                        lambda url, timeout=15: _Resp(200, '{"suggestions":[{"value":"x"}]}'))
    assert fetch_json_strict("x")["suggestions"][0]["value"] == "x"


def test_fetch_suggestions_reste_silencieux_sur_echec(monkeypatch):
    """Contrat inchangé pour l'appelant non-fiction en production."""
    monkeypatch.setattr("util.http_get", lambda url, timeout=15: _Resp(503, ""))
    assert fetch_suggestions("cosy mystery") == []
```

- [ ] **Step 2 : Lancer** → FAIL. **Step 3 : Implémenter** dans `01-scripts/amazon_autocomplete.py` :
```python
class AutocompleteError(RuntimeError):
    """Échec de la sonde (réseau, HTTP, JSON) — à distinguer d'une absence de suggestions :
    « personne ne cherche ça » est une conclusion, « le réseau a toussé » n'en est pas une."""


def fetch_json_strict(prefix: str) -> dict:
    """Comme _default_fetch_json mais LÈVE au lieu d'avaler l'échec."""
    r = util.http_get(_build_url(prefix), timeout=15)
    status = getattr(r, "status_code", None)
    if status != 200:
        raise AutocompleteError(f"HTTP {status}")
    try:
        return json.loads(r.text)
    except Exception as e:
        raise AutocompleteError(f"JSON invalide : {e}") from e
```
puis faire déléguer l'existante (comportement silencieux **inchangé**) :
```python
def _default_fetch_json(prefix: str) -> dict:
    try:
        return fetch_json_strict(prefix)
    except AutocompleteError as e:
        print(f"[autocomplete] {e}")
        return {}
```

- [ ] **Step 4 : Lancer** toute la suite → verte (vérifie particulièrement `tests/test_niche_validator.py`). **Step 5 : Commit**
```bash
git add 01-scripts/amazon_autocomplete.py tests/test_amazon_autocomplete.py
git commit -m "feat(autocomplete): fetch_json_strict — un échec réseau cesse de ressembler à zéro suggestion"
```

---

## Task M3-2 : Modèles du signal

**Files:** Modify `01-scripts/models.py` · Test `tests/test_models_fiction.py` (ou le fichier de tests de modèles existant)

- [ ] **Step 1 : Tests (échouent)** :
```python
def test_probe_extras_exclut_l_echo():
    p = AutocompleteProbe(requete="romance hockey",
                          suggestions=["romance hockey", "romance hockey mm"])
    assert p.echo is True
    assert p.extras == ["romance hockey mm"]


def test_probe_echo_insensible_casse_espaces():
    p = AutocompleteProbe(requete=" Romance Hockey ", suggestions=["romance hockey"])
    assert p.echo is True and p.extras == []


def test_signal_libelle_lisible():
    absent = AutocompleteSignal(niche_query="q", score=0.0)
    assert "absent" in absent.libelle.lower()
```

- [ ] **Step 2 : Lancer** → FAIL. **Step 3 : Implémenter** dans `01-scripts/models.py` :
```python
class AutocompleteProbe(BaseModel):
    """Une requête sondée. `echec`/`erreur` renseignés = la sonde n'a rien mesuré ;
    ce n'est PAS la même chose que zéro suggestion (CLAUDE.md §10)."""
    requete: str
    suggestions: list[str] = Field(default_factory=list)
    echec: bool = False
    erreur: str | None = None

    @staticmethod
    def _norm(s: str) -> str:
        return " ".join((s or "").split()).casefold()

    @property
    def echo(self) -> bool:
        """Amazon renvoie souvent la requête elle-même : présence = le terme existe,
        mais sans aucune expansion (signal faible, pas nul)."""
        return any(self._norm(s) == self._norm(self.requete) for s in self.suggestions)

    @property
    def extras(self) -> list[str]:
        """Suggestions autres que l'écho — la vraie mesure d'intérêt."""
        n = self._norm(self.requete)
        return [s for s in self.suggestions if self._norm(s) != n]


class AutocompleteSignal(BaseModel):
    """Soft signal M5. Le spike M0 §V3 est formel : ne gate JAMAIS seul."""
    niche_query: str
    score: float = 0.0                     # 0 / 0.5 / 1
    probes: list[AutocompleteProbe] = Field(default_factory=list)
    sous_genre_cherche: bool | None = None  # barreau 2 : None si non sondé
    mesure: bool = True                     # False si la sonde du barreau 1 a échoué

    @property
    def libelle(self) -> str:
        if not self.mesure:
            return "non mesuré (sonde en échec)"
        return {1.0: "expansions", 0.5: "écho seul"}.get(self.score, "absent")
```

- [ ] **Step 4 : Lancer** → verte. **Step 5 : Commit**
```bash
git add 01-scripts/models.py tests/
git commit -m "feat(fiction): modèles AutocompleteProbe / AutocompleteSignal"
```

---

## Task M3-3 : `probe_niche` — l'échelle à deux barreaux

**Files:** Create `01-scripts/fiction_autocomplete.py` · Test `tests/test_fiction_autocomplete.py`

Barème (calé sur les mesures live du spike, cf. tableau §V3) :

| extras (hors écho) | écho | score |
|---|---|---|
| ≥ 2 | — | **1.0** |
| 1 | — | **0.5** |
| 0 | oui | **0.5** |
| 0 | non | **0.0** |

- [ ] **Step 1 : Tests (échouent)** — `tests/test_fiction_autocomplete.py`, **calés sur la fixture live** `tests/fixtures/fiction/v3_autocomplete.json` :
```python
import json
from pathlib import Path

from fiction_autocomplete import probe_niche, score_suggestions
from models import FictionNiche

_LIVE = json.loads((Path(__file__).parent / "fixtures" / "fiction" /
                    "v3_autocomplete.json").read_text(encoding="utf-8"))


def _niche(query, sg="cosy_mystery"):
    return FictionNiche(sous_genre=sg, tropes=["enquetrice_amatrice"], rayon="kindle",
                        query=query)


def test_bareme_cale_sur_les_mesures_live():
    # 4 suggestions dont l'écho -> 3 extras -> signal franc
    assert score_suggestions("romance milliardaire", _LIVE["romance milliardaire"]) == 1.0
    # écho seul -> le terme existe mais rien ne s'y greffe
    assert score_suggestions("polar breton", _LIVE["polar breton"]) == 0.5
    # rien -> trio trop précis (ou terme inexistant) : c'est le barreau 2 qui tranchera
    assert score_suggestions("romantasy ennemis", _LIVE["romantasy ennemis"]) == 0.0


def test_deux_barreaux_trio_precis_mais_sous_genre_cherche():
    appels = []

    def fake(prefix):
        appels.append(prefix)
        return {"cosy mystery": [{"value": "cosy mystery"},
                                 {"value": "cosy mystery francais"}]}.get(prefix, [])

    sig = probe_niche(_niche("cosy mystery libraire village"),
                      fetch_json=lambda p: {"suggestions": fake(p)}, pause=0)
    assert appels == ["cosy mystery libraire village", "cosy mystery"]   # spécifique -> large
    assert sig.score == 0.0                 # le trio n'est pas tapé…
    assert sig.sous_genre_cherche is True   # …mais le sous-genre l'est : pas d'alerte
    assert sig.mesure is True


def test_sous_genre_fantome_est_signale():
    sig = probe_niche(_niche("x"), fetch_json=lambda p: {"suggestions": []}, pause=0)
    assert sig.score == 0.0 and sig.sous_genre_cherche is False


def test_echec_de_sonde_nest_pas_un_zero():
    from amazon_autocomplete import AutocompleteError

    def ko(prefix):
        raise AutocompleteError("HTTP 503")

    sig = probe_niche(_niche("cosy mystery libraire"), fetch_json=ko, pause=0)
    assert sig.mesure is False                     # <- la distinction qui compte
    assert sig.score == 0.0
    assert "non mesuré" in sig.libelle
    assert sig.probes[0].echec is True and "503" in (sig.probes[0].erreur or "")


def test_barreau_2_saute_si_le_trio_suffit():
    """Économie de requêtes : un trio déjà positif n'a pas besoin du contexte."""
    appels = []

    def fake(prefix):
        appels.append(prefix)
        return {"suggestions": [{"value": prefix}, {"value": prefix + " 2"},
                                {"value": prefix + " 3"}]}

    sig = probe_niche(_niche("cosy mystery libraire"), fetch_json=fake, pause=0)
    assert sig.score == 1.0 and len(appels) == 1
```

- [ ] **Step 2 : Lancer** → FAIL. **Step 3 : Implémenter `01-scripts/fiction_autocomplete.py`** :
```python
"""fiction_autocomplete.py — sonde de demande GRATUITE pour une niche fiction.

Soft signal : le spike M0 §V3 a mesuré que les trios trope × décor précis ne remontent
rien dans l'autocomplete alors que les requêtes commerciales larges sont riches. Un 0 ne
veut donc PAS dire « niche morte » — d'où l'échelle à deux barreaux (le sous-genre est-il
lui-même cherché ?) et l'interdiction faite à M5 de gater sur ce seul score."""
import time

from amazon_autocomplete import AutocompleteError, fetch_json_strict, parse_suggestions
from fiction_taxonomy import sous_genre
from models import AutocompleteProbe, AutocompleteSignal, FictionNiche


def score_suggestions(requete: str, suggestions: list[str]) -> float:
    """Barème 0 / 0,5 / 1 calé sur les mesures live du spike (§V3)."""
    p = AutocompleteProbe(requete=requete, suggestions=suggestions)
    if len(p.extras) >= 2:
        return 1.0
    if p.extras or p.echo:
        return 0.5
    return 0.0


def _sonde(requete: str, fetch_json, pause: float) -> AutocompleteProbe:
    if pause:
        time.sleep(pause)
    try:
        return AutocompleteProbe(requete=requete,
                                 suggestions=parse_suggestions(fetch_json(requete)))
    except AutocompleteError as e:
        return AutocompleteProbe(requete=requete, echec=True, erreur=str(e))


def probe_niche(niche: FictionNiche, fetch_json=None, pause: float = 0.4,
                version: str = "fr_v1") -> AutocompleteSignal:
    """Sonde la requête du trio, puis — seulement si elle ne donne rien — la requête
    canonique du sous-genre, pour distinguer « trio trop précis » de « sous-genre fantôme »."""
    fetch_json = fetch_json or fetch_json_strict
    p1 = _sonde(niche.query, fetch_json, 0)
    sig = AutocompleteSignal(niche_query=niche.query, probes=[p1])
    if p1.echec:
        sig.mesure = False
        return sig
    sig.score = score_suggestions(niche.query, p1.suggestions)
    if sig.score > 0:
        return sig                      # inutile de payer le contexte : le trio parle déjà

    large = (sous_genre(niche.sous_genre, version).get("query_fr") or "").strip()
    if not large or large.casefold() == niche.query.strip().casefold():
        return sig
    p2 = _sonde(large, fetch_json, pause)
    sig.probes.append(p2)
    if not p2.echec:
        sig.sous_genre_cherche = score_suggestions(large, p2.suggestions) > 0
    return sig
```

- [ ] **Step 4 : Lancer** `python -m pytest -q` → toute la suite verte. **Step 5 : Commit**
```bash
git add 01-scripts/fiction_autocomplete.py tests/test_fiction_autocomplete.py
git commit -m "feat(fiction): probe_niche — sonde autocomplete à deux barreaux (soft signal)"
```

---

## Self-Review
- Soft signal, jamais gatant : le barème est isolé dans `score_suggestions`, et `AutocompleteSignal` porte `mesure` pour que M5 ne puisse pas confondre 0 mesuré et 0 par défaut. ✓
- Échec de sonde ≠ absence de demande — la distinction est dans le modèle, pas seulement dans un log (§10). ✓
- Gratuit : aucun `CostTracker` impliqué, aucun appel payant. ✓
- Économie de requêtes : le barreau 2 n'est sondé que lorsqu'il apporte une information. ✓
- Contrat de `fetch_suggestions` inchangé pour le scout non-fiction en production. ✓
- Tests calés sur la fixture **live** du spike plutôt que sur des valeurs inventées. ✓

---

## Correctifs post-revue (2026-07-20)

Six défauts relevés en revue, tous vérifiés sur exécution avant correction — aucun ne faisait planter les tests, tous faussaient une note :

1. **Panne réseau réelle = crash.** `util.http_get` re-lève `requests.RequestException` après ses retries ; `_sonde` n'attrapait qu'`AutocompleteError`. Sur le chemin de production, un timeout DNS tuait le run au lieu de rendre `mesure=False`. Corrigé **côté fiction uniquement** : attraper la `RequestException` dans `fetch_json_strict` ferait avaler les pannes par `fetch_suggestions`, qui les rendrait comme « 0 suggestion » et invaliderait la niche du scout non-fiction en production.
2. **Requête vide → score maximal.** `FictionNiche.query` a un défaut vide et n'est jamais vérifiée côté code ; aucune suggestion ne pouvant être l'écho de `""`, toutes comptaient comme extras → **1.0**. Garde ajouté avant toute sonde.
3. **Écho non reconnu à cause des accents.** `_norm` ignorait les diacritiques alors qu'Amazon suggère indifféremment « francais » et « français » et que les requêtes viennent d'un LLM en français naturel — la même donnée changeait de note d'un cran entier. Dépouillement NFKD.
4. **Sous-genre fantôme dégradé en `None`.** Quand le barreau 1 **est** la requête canonique et rend 0, le sous-genre vient d'être mesuré à zéro : c'est l'alerte. Le garde d'égalité utilisait en plus une normalisation plus faible que `_norm`, si bien que deux écritures du même libellé donnaient des verdicts opposés.
5. **`mesure=True` par défaut.** Un signal jamais sondé était indiscernable d'un zéro mesuré — exactement la garantie vendue à M5. Défaut passé à `False`, positionné explicitement après un barreau 1 réussi.
6. **Extras non dédupliqués** (mineur) : deux fois la même suggestion faisait deux signaux d'intérêt. `niche_validator` dédupliquait déjà, lui.

Également : le `pause` n'était appliqué qu'avant le barreau 2 — M6 aurait bouclé sur l'endpoint sans délai. Il couvre désormais les deux barreaux.

## ⚠ Dette à trancher dans le plan M5
`FictionNicheReport.autocomplete_score` est un `float` : c'est aujourd'hui le seul point d'atterrissage du signal. Si M5 se contente de copier ce float, **`mesure` et `sous_genre_cherche` s'évaporent** et `0.0` redevient à la fois le défaut et le verdict « absent » — la confusion que tout ce chunk s'emploie à empêcher. **M5 doit porter l'`AutocompleteSignal` entier**, pas sa note.

## Constat live à intégrer à M5 (14 trios sondés le 2026-07-20)
Le clivage n'est **pas** « trio précis vs sous-genre large » comme le supposait le spike. Les requêtes qui décrochent 1.0 sont `dark romance mafia`, `romance hockey`, `romance milliardaire`, `roman feel good` — des **tropes de romance**, tapés tels quels. Les montages cosy mystery / thriller / romantasy (décor + situation) ne remontent rien alors que leurs sous-genres sont massivement cherchés.
→ **En romance, le trope EST la requête ; ailleurs, le rayon se navigue au lieu de se chercher.** Le barème ne doit donc pas s'appliquer uniformément : un 0 sur un trio cosy mystery est normal, un 0 sur un trope de romance est une vraie information négative. Conséquence produit au-delà du scoring : sur une niche romance le trope doit figurer au titre (mot-clé réellement tapé), sur un cosy mystery c'est le rayon et la couverture qui portent la découverte.

## Suite
M4 classifieur de blurb (+ validation 50 livres) · M5 scoring (matrice de demande) · M6 orchestration/UI · puis le compteur de crédits.
