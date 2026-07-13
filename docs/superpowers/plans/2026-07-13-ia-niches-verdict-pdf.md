# IA-Niches — Verdict IA par niche + PDF one-pager — Plan d'implémentation

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax.

**Goal:** Ajouter un **verdict IA « directeur éditorial »** par niche (Go/No-Go + confiance + facteur décisif + 2-3 angles titre/sous-titre + critique stratégique), gaté sur le **top-3** des niches classées, affiché dans l'UI et exportable en **PDF one-pager** à la demande. Retirer l'export Excel mort (`report_builder.py`).

**Architecture :** Nouveau module `niche_verdict.py` calqué sur `niche_ideator.py` (client Anthropic injectable, **tool-use forcé**, schéma strict), appliquant le directeur éditorial de `CLAUDE.md §7-8` **sur les données structurées du scout** (BSR, concurrents organiques, sponsorisés écartés, demande, titres du top). `run_scout` gate le verdict au top-N après le tri (deps injectables, coût mesuré dans le `CostTracker`). `positioning_pdf.py` rend un one-pager via **fpdf2** (police core Helvetica + assainisseur latin-1). Le serveur expose `POST /api/pdf` (sans état : reçoit la niche JSON, renvoie le PDF) ; l'UI affiche le verdict et propose un bouton de téléchargement.

**Tech Stack :** Python 3.13, pytest (pythonpath=`01-scripts`, testpaths=`tests`), pydantic v2, Anthropic SDK (tool-use forcé), **fpdf2** (nouvelle dépendance), FastAPI.

**Décisions verrouillées :** verdict complet ; modèle **`claude-sonnet-5`** par défaut (`VERDICT_MODEL` configurable) ; gate **top-3** (`n_verdict=3`, 0 = off) ; verdict **injectable** (`verdict_fn`) et non-bloquant (un échec de verdict → `None`, le run continue, §11.11) ; PDF **fpdf2/Helvetica** + assainisseur ; endpoint PDF **sans état**. `report_builder.py` **retiré** (choix B).

---

## Task 1 : Retirer `report_builder.py` (export Excel mort)

**Files:** Delete `01-scripts/report_builder.py`

- [ ] **Step 1 : Confirmer qu'il est mort** — `rg -n "report_builder" 01-scripts web tests`. Attendu : aucune référence en code (seulement lui-même / docs). Si un module ou un test l'importe → STOP, reporter BLOCKED.
- [ ] **Step 2 : Supprimer** — `git rm 01-scripts/report_builder.py`
- [ ] **Step 3 : Vérifier** — `python -m pytest -q` reste vert (65 passed).
- [ ] **Step 4 : Commit**
```bash
git commit -m "chore: retire report_builder.py (export Excel jamais branché — choix B)"
```

---

## Task 2 : Modèles du verdict (`models.py`)

**Files:** Modify `01-scripts/models.py` · Test `tests/test_models.py`

- [ ] **Step 1 : Test (échoue)** — ajouter à `tests/test_models.py` :
```python
def test_niche_verdict_and_scored_niche_field():
    from models import AngleAttaque, NicheVerdict, ScoredNiche
    a = AngleAttaque(angle="a", pourquoi="p", risque="r", titre="T", sous_titre="ST")
    v = NicheVerdict(verdict="Go", confiance=8, facteur_decisif="f", angles=[a],
                     saturation="non", faux_concurrent="aucun", differenciation="exécution")
    sc = ScoredNiche(niche="x", verdict=v)
    assert sc.verdict.verdict == "Go" and sc.verdict.angles[0].titre == "T"
    assert ScoredNiche(niche="y").verdict is None
    # round-trip JSON (l'UI/serveur sérialisent via model_dump)
    d = sc.model_dump()
    assert ScoredNiche.model_validate(d).verdict.confiance == 8
```
- [ ] **Step 2 : Run** `python -m pytest tests/test_models.py -k verdict -v` → FAIL (ImportError).
- [ ] **Step 3 : Implémenter** — dans `01-scripts/models.py`, ajouter avant `ScoredNiche` :
```python
class AngleAttaque(BaseModel):
    """Un angle d'attaque proposé par le verdict directeur éditorial."""
    angle: str
    pourquoi: str
    risque: str
    titre: str
    sous_titre: str
    direction_couverture: str = ""
    prix_suggere: str = ""                 # fourchette lisible, ex. "14,90-19,90 €"
    requete_principale: str = ""
    requetes_secondaires: list[str] = Field(default_factory=list)


class NicheVerdict(BaseModel):
    """Verdict éditorial d'une niche (directeur éditorial §7-8, sur données du scout)."""
    verdict: str                           # "Go" | "Go prudent" | "No-Go"
    confiance: int = 0                     # 1-10
    facteur_decisif: str = ""
    angles: list[AngleAttaque] = Field(default_factory=list)  # 1-3
    saturation: str = ""                   # critique stratégique Q1
    faux_concurrent: str = ""              # Q2 ("aucun" si pas de faux concurrent)
    differenciation: str = ""             # Q3 (exécution / angle / autorité)
```
Puis ajouter le champ à `ScoredNiche` (après `top_asins`) :
```python
    verdict: NicheVerdict | None = None    # rempli pour le top-N (gate coût)
```
- [ ] **Step 4 : Run** `python -m pytest -q` → 66 passed.
- [ ] **Step 5 : Commit**
```bash
git add 01-scripts/models.py tests/test_models.py
git commit -m "feat(models): AngleAttaque + NicheVerdict + ScoredNiche.verdict"
```

---

## Task 3 : `niche_verdict.py` — generate_verdict (tool-use forcé)

**Files:** Create `01-scripts/niche_verdict.py` · Test `tests/test_niche_verdict.py`

- [ ] **Step 1 : Test (échoue)** — créer `tests/test_niche_verdict.py` :
```python
from niche_verdict import generate_verdict, build_user_prompt
from models import ScoredNiche, SearchResult, SearchItem, NicheVerdict


def _sample_scored():
    return ScoredNiche(niche="stoïcisme pratique", requete_amazon="stoïcisme",
                       categorie="philosophie", global_score=8.0, demande=9.0,
                       penetration=6.0, compatibilite=8.0, verdict=None,
                       n_organic=16, n_concurrents_cibles=12, n_sponsored=4,
                       avg_rating=4.4, total_reviews=8000, bsr_best=2279,
                       bsr_top5_avg=21445, bsr_worst_top10=120000, criteres_bsr_ok=True,
                       top_asins=["A1", "A2"])


def test_build_user_prompt_contains_key_data():
    sr = SearchResult(keyword="stoïcisme", organic=[
        SearchItem(title="Petit manuel de stoïcisme", asin="A1"),
        SearchItem(title="Pensées de Marc Aurèle", asin="A2")])
    p = build_user_prompt(_sample_scored(), sr)
    assert "stoïcisme" in p and "2279" in p            # requête + BSR meilleur
    assert "Petit manuel de stoïcisme" in p            # titres concurrents fournis
    assert "4" in p                                     # sponsorisés écartés mentionnés


def test_generate_verdict_forced_tool_use_and_usage():
    class _Usage:
        input_tokens = 900
        output_tokens = 1100

    class _Block:
        type = "tool_use"
        input = {"verdict": "Go", "confiance": 8, "facteur_decisif": "couverture pro",
                 "angles": [{"angle": "stoïcisme pour débutants", "pourquoi": "demande forte",
                             "risque": "niche connue", "titre": "Stoïcisme facile",
                             "sous_titre": "le guide du quotidien", "direction_couverture": "sobre",
                             "prix_suggere": "14,90 €", "requete_principale": "stoïcisme",
                             "requetes_secondaires": ["marc aurèle"]}],
                 "saturation": "moyenne", "faux_concurrent": "aucun",
                 "differenciation": "exécution"}

    class _Resp:
        content = [_Block()]
        usage = _Usage()

    class _Client:
        class messages:
            @staticmethod
            def create(**kw):
                # tool-use forcé : un outil + tool_choice forcé
                assert kw["tool_choice"]["type"] == "tool"
                assert kw["tools"][0]["name"]
                return _Resp()

    seen = {}
    v = generate_verdict(_sample_scored(), search=None, client=_Client(),
                         model="claude-sonnet-5", on_usage=lambda i, o, m: seen.update(i=i, o=o))
    assert isinstance(v, NicheVerdict)
    assert v.verdict == "Go" and v.confiance == 8 and v.angles[0].titre == "Stoïcisme facile"
    assert seen == {"i": 900, "o": 1100}
```
- [ ] **Step 2 : Run** `python -m pytest tests/test_niche_verdict.py -v` → FAIL (module absent).
- [ ] **Step 3 : Implémenter** `01-scripts/niche_verdict.py` :
```python
"""niche_verdict.py — verdict éditorial d'une niche (directeur éditorial CLAUDE.md §7-8),
appliqué sur les DONNÉES DU SCOUT (pas de screenshots). Tool-use forcé, client injectable."""
import os

from dotenv import load_dotenv

from models import NicheVerdict, ScoredNiche  # noqa: F401

DEFAULT_MODEL = os.getenv("VERDICT_MODEL", "claude-sonnet-5")

SYSTEM_PROMPT = """\
Tu es un DIRECTEUR ÉDITORIAL SENIOR et analyste concurrentiel pour un grand éditeur français. \
Tu tranches l'angle d'attaque optimal pour positionner un NOUVEAU LIVRE sur Amazon.fr dans une \
niche donnée. L'échec commercial n'est pas une option : tu es payé pour avoir raison.

DONNÉES : tu reçois les métriques déjà calculées d'un scout automatique (BSR des livres \
ORGANIQUES du top, demande, concurrence, titres concurrents). Les livres SPONSORISÉS ont DÉJÀ \
été écartés des calculs. Ne réclame pas de screenshots : raisonne sur ces chiffres.

POSTURE : factuel, tranché, sans complaisance. Pas de compliments gratuits. Quantifie ce qui \
peut l'être. Signale les zones d'incertitude. Impartial : ne privilégie aucun domaine a priori.

CRITÈRES DE DEMANDE (rappel) : une niche est forte si le top organique a au moins 1 BSR < 10 000 \
(demande prouvée), une moyenne < 50 000 (marché actif), ET au moins 1 BSR > 50 000 (« place à \
prendre » : un livre mal positionné mais bien classé = détronnable par une meilleure exécution).

TU PRODUIS (via l'outil rendre_verdict, OBLIGATOIRE) :
- verdict : "Go" / "Go prudent" / "No-Go" + confiance /10 + LE facteur décisif (la seule chose \
  qui fera la différence).
- 2 à 3 ANGLES d'attaque classés par priorité, chacun : l'angle (1 phrase), pourquoi ça marche \
  (justif. factuelle), le risque principal, un TITRE + SOUS-TITRE de travail concrets, la \
  direction de couverture, une fourchette de prix, la requête Amazon principale visée + 1-3 \
  requêtes secondaires (logique de titre multi-requêtes pour maximiser la surface de capture).
- CRITIQUE STRATÉGIQUE : saturation (non / oui mais bonne → différenciation par angle / oui et \
  morte → skip) ; faux_concurrent (un livre qui semble dominer mais dont la force vient d'une \
  niche voisine — donc battable sur LA requête ; "aucun" sinon) ; differenciation (par exécution \
  / par angle / par autorité — tranche laquelle est prioritaire).

Les titres et angles doivent être ACTIONNABLES : un auteur doit pouvoir s'y mettre directement.
"""

VERDICT_INPUT_SCHEMA = {
    "type": "object",
    "properties": {
        "verdict": {"type": "string", "enum": ["Go", "Go prudent", "No-Go"]},
        "confiance": {"type": "integer", "description": "1 à 10"},
        "facteur_decisif": {"type": "string", "description": "LA chose qui fera la différence"},
        "angles": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "angle": {"type": "string"},
                    "pourquoi": {"type": "string"},
                    "risque": {"type": "string"},
                    "titre": {"type": "string"},
                    "sous_titre": {"type": "string"},
                    "direction_couverture": {"type": "string"},
                    "prix_suggere": {"type": "string"},
                    "requete_principale": {"type": "string"},
                    "requetes_secondaires": {"type": "array", "items": {"type": "string"}},
                },
                "required": ["angle", "pourquoi", "risque", "titre", "sous_titre",
                             "direction_couverture", "prix_suggere", "requete_principale",
                             "requetes_secondaires"],
            },
        },
        "saturation": {"type": "string"},
        "faux_concurrent": {"type": "string", "description": "'aucun' si pas de faux concurrent"},
        "differenciation": {"type": "string"},
    },
    "required": ["verdict", "confiance", "facteur_decisif", "angles", "saturation",
                 "faux_concurrent", "differenciation"],
}


def build_user_prompt(scored: ScoredNiche, search=None) -> str:
    """Formate les données du scout en brief pour le directeur éditorial."""
    titres = []
    if search is not None:
        titres = [o.title for o in search.organic if o.title][:12]
    lignes = [
        f"NICHE : {scored.niche}",
        f"Requête Amazon : « {scored.requete_amazon or scored.niche} » | catégorie : {scored.categorie}",
        f"Scores scout /10 : global {scored.global_score} · demande {scored.demande} · "
        f"pénétration {scored.penetration} · compatibilité {scored.compatibilite}",
        f"Demande : {scored.demand_autocomplete} complétions Amazon · "
        f"note moyenne {scored.avg_rating} · {scored.total_reviews} avis cumulés (top organique)",
        f"BSR organique (Livres) : meilleur {scored.bsr_best} · moyenne top {scored.bsr_top5_avg} · "
        f"plus haut {scored.bsr_worst_top10} · critères §4.1 remplis : "
        f"{'OUI' if scored.criteres_bsr_ok else 'non'}",
        f"Concurrence : {scored.n_organic} résultats organiques · "
        f"{scored.n_concurrents_cibles} concurrents ciblant vraiment la requête · "
        f"{scored.n_sponsored} sponsorisés écartés des calculs",
    ]
    if titres:
        lignes.append("Titres concurrents organiques du top :\n- " + "\n- ".join(titres))
    else:
        lignes.append("(titres concurrents non disponibles — raisonne sur les métriques)")
    lignes.append("\nRends ton verdict via l'outil rendre_verdict.")
    return "\n".join(lignes)


def _default_client():
    load_dotenv()
    import anthropic
    return anthropic.Anthropic(api_key=os.getenv("ANTHROPIC_API_KEY"))


def generate_verdict(scored: ScoredNiche, search=None, model: str | None = None,
                     client=None, on_usage=None) -> NicheVerdict:
    """Verdict éditorial d'une niche. `client` injectable. `on_usage(in,out,model)` optionnel."""
    client = client or _default_client()
    model = model or DEFAULT_MODEL
    resp = client.messages.create(
        model=model,
        max_tokens=4000,
        system=SYSTEM_PROMPT,
        tools=[{
            "name": "rendre_verdict",
            "description": "Renvoie le verdict éditorial structuré de la niche.",
            "input_schema": VERDICT_INPUT_SCHEMA,
        }],
        tool_choice={"type": "tool", "name": "rendre_verdict"},
        messages=[{"role": "user", "content": build_user_prompt(scored, search)}],
    )
    if on_usage is not None and getattr(resp, "usage", None) is not None:
        on_usage(getattr(resp.usage, "input_tokens", 0),
                 getattr(resp.usage, "output_tokens", 0), model)
    for block in resp.content:
        if getattr(block, "type", None) == "tool_use":
            return NicheVerdict.model_validate(block.input)
    return NicheVerdict(verdict="No-Go", confiance=0, facteur_decisif="(pas de sortie LLM)")
```
- [ ] **Step 4 : Run** `python -m pytest tests/test_niche_verdict.py -v` puis `python -m pytest -q` → 68 passed.
- [ ] **Step 5 : Commit**
```bash
git add 01-scripts/niche_verdict.py tests/test_niche_verdict.py
git commit -m "feat(verdict): niche_verdict.generate_verdict — directeur éditorial sur données scout (tool-use)"
```

---

## Task 4 : Intégration du verdict dans `run_scout` (gate top-3)

**Files:** Modify `01-scripts/scout_master.py` · Test `tests/test_scout_master.py`

- [ ] **Step 1 : Mettre à jour le test (échoue)** — dans `tests/test_scout_master.py`, ajouter un fake verdict + le passer + asserter. Remplacer le test end-to-end par :
```python
from models import NicheVerdict

def _fake_verdict(scored, search=None, model=None, on_usage=None):
    if on_usage:
        on_usage(500, 400, model or "claude-sonnet-5")
    return NicheVerdict(verdict="Go", confiance=8, facteur_decisif="exécution",
                        angles=[], saturation="non", faux_concurrent="aucun",
                        differenciation="exécution")


def test_run_scout_end_to_end_mocked():
    cost = CostTracker()
    res = run_scout(seed="ésotérisme", n_search=3, bsr_pause=0, use_cache=False, cost=cost,
                    ideate=_fake_ideate, validate=_fake_validate, provider=_FakeProvider(),
                    fetch_bsr_fn=_fake_bsr, verdict_fn=_fake_verdict)
    assert len(res) == 1
    s = res[0]
    assert s.niche == "tarot" and s.bsr_best == 3000 and s.criteres_bsr_ok is True
    assert s.verdict is not None and s.verdict.verdict == "Go"      # verdict attaché (top-N)
    assert cost.breakdown()["llm_tokens_in"] == 1000 + 500          # ideator + verdict


def test_run_scout_verdict_off_when_n_verdict_zero():
    res = run_scout(seed="x", n_search=3, bsr_pause=0, use_cache=False, n_verdict=0,
                    ideate=_fake_ideate, validate=_fake_validate, provider=_FakeProvider(),
                    fetch_bsr_fn=_fake_bsr, verdict_fn=_fake_verdict)
    assert res and res[0].verdict is None                          # gate off -> pas de verdict
```
(Garder `test_run_scout_no_validated_returns_empty` tel quel.)
- [ ] **Step 2 : Run** `python -m pytest tests/test_scout_master.py -v` → FAIL (`run_scout` ne prend pas `verdict_fn`).
- [ ] **Step 3 : Implémenter** — dans `01-scripts/scout_master.py` :
  - Ajouter l'import : `from niche_verdict import generate_verdict as _generate_verdict`.
  - Signature `run_scout` : ajouter `n_verdict: int = 3, verdict_model: str | None = None, verdict_fn=None` (après `bsr_priority`).
  - En tête de fonction : `verdict_fn = verdict_fn or _generate_verdict`.
  - **Phase C** : construire des paires `(scored, sr)`, trier, puis gater le verdict au top-N. Remplacer la Phase C actuelle par :
```python
    # Phase C — scoring
    pairs = []          # (ScoredNiche, SearchResult|None)
    for v, sr, asins in per_niche:
        bsrs = [bsr_map[a].rank_livres for a in asins
                if bsr_map.get(a) and bsr_map[a].rank_livres]
        pairs.append((score_niche(v, sr, bsrs), sr))
    pairs.sort(key=lambda p: p[0].global_score, reverse=True)

    # Verdict IA (directeur éditorial), gaté au top-N pour maîtriser le coût
    if n_verdict:
        for sc, sr in pairs[:n_verdict]:
            progress(f"Verdict éditorial : {sc.niche}…")
            try:
                sc.verdict = verdict_fn(sc, sr, model=verdict_model,
                                        on_usage=lambda i, o, m: cost.add_llm(m, i, o))
            except Exception as e:  # noqa: BLE001 — un échec de verdict ne coule pas le run (§11.11)
                progress(f"  ⚠ verdict indisponible ({e})")

    scored = [sc for sc, _ in pairs]
```
  - Le bloc de fin (`scored.sort(...)`) devient inutile (déjà trié via `pairs`) — **retirer** le `scored.sort(...)` restant s'il existe, garder l'affichage du coût final.
- [ ] **Step 4 : CLI** — dans `main()`, après l'affichage des lignes, imprimer le verdict du top-3 :
```python
    for s in results[:3]:
        if s.verdict:
            print(f"\n▸ {s.niche} — Verdict : {s.verdict.verdict} ({s.verdict.confiance}/10)")
            print(f"  Facteur décisif : {s.verdict.facteur_decisif}")
            for a in s.verdict.angles[:2]:
                print(f"  • « {a.titre} » — {a.sous_titre}")
```
- [ ] **Step 5 : Run** `python -m pytest -q` → 70 passed (2 tests scout ajoutés/modifiés).
- [ ] **Step 6 : Commit**
```bash
git add 01-scripts/scout_master.py tests/test_scout_master.py
git commit -m "feat(scout): verdict IA gaté top-3 dans run_scout + rendu CLI"
```

---

## Task 5 : `positioning_pdf.py` — one-pager fpdf2

**Files:** Create `01-scripts/positioning_pdf.py` · Modify `01-scripts/requirements.txt` · Test `tests/test_positioning_pdf.py`

- [ ] **Step 1 : Dépendance** — ajouter `fpdf2` à `01-scripts/requirements.txt`, puis `python -m pip install fpdf2`.
- [ ] **Step 2 : Test (échoue)** — créer `tests/test_positioning_pdf.py` :
```python
from models import ScoredNiche, NicheVerdict, AngleAttaque
from positioning_pdf import build_positioning_pdf, _safe


def test_safe_sanitizes_non_latin1():
    assert _safe("prix 19,90 € — l'œuvre") == "prix 19,90 EUR - l'oeuvre"


def _scored():
    a = AngleAttaque(angle="stoïcisme pour débutants", pourquoi="demande forte",
                     risque="niche connue", titre="Stoïcisme facile",
                     sous_titre="le guide du quotidien", direction_couverture="sobre, ocre",
                     prix_suggere="14,90-19,90 €", requete_principale="stoïcisme",
                     requetes_secondaires=["marc aurèle", "sénèque"])
    v = NicheVerdict(verdict="Go", confiance=8, facteur_decisif="une couverture pro",
                     angles=[a], saturation="moyenne", faux_concurrent="aucun",
                     differenciation="exécution")
    return ScoredNiche(niche="stoïcisme pratique", requete_amazon="stoïcisme",
                       categorie="philosophie", global_score=8.0, demande=9.0, penetration=6.0,
                       compatibilite=8.0, n_organic=16, n_concurrents_cibles=12, n_sponsored=4,
                       avg_rating=4.4, total_reviews=8000, bsr_best=2279, bsr_top5_avg=21445,
                       bsr_worst_top10=120000, criteres_bsr_ok=True, verdict=v)


def test_build_pdf_writes_file(tmp_path):
    out = build_positioning_pdf(_scored(), tmp_path / "p.pdf")
    assert out.exists() and out.stat().st_size > 800
    assert out.read_bytes()[:5] == b"%PDF-"


def test_build_pdf_without_verdict(tmp_path):
    sc = _scored()
    sc.verdict = None
    out = build_positioning_pdf(sc, tmp_path / "n.pdf")   # ne doit pas planter
    assert out.exists() and out.read_bytes()[:5] == b"%PDF-"
```
- [ ] **Step 3 : Run** `python -m pytest tests/test_positioning_pdf.py -v` → FAIL (module absent).
- [ ] **Step 4 : Implémenter** `01-scripts/positioning_pdf.py`. Objectif : un **A4 portrait** propre, aux couleurs du dashboard (bleu `#1E40AF`, ambre `#D97706`, texte `#1E293B`, atténué `#64748B`), police core **Helvetica**. Rendu robuste via `_safe` (aucun caractère hors latin-1). Structure : bandeau titre (niche + badge verdict coloré + confiance), bloc « Chiffres clés » (BSR meilleur/moy/haut, badge §4.1, concurrents, sponsorisés écartés, demande, note/avis), « Angle recommandé » (titre en gros + sous-titre + pourquoi/risque + couverture + prix + requêtes), angles alternatifs condensés, facteur décisif, critique stratégique, pied de page (date + coût si dispo). Référence d'implémentation (adapter les marges/positions au besoin, garder l'API et le comportement) :
```python
"""positioning_pdf.py — one-pager PDF de positionnement d'une niche (verdict + angles).
fpdf2, police core Helvetica + assainisseur latin-1 (portable, sans fichier de police)."""
from pathlib import Path

from fpdf import FPDF

from models import ScoredNiche

_BLUE = (30, 64, 175)
_AMBER = (217, 119, 6)
_DARK = (30, 41, 59)
_MUTED = (100, 116, 139)
_LIGHT = (241, 245, 249)
_GREEN = (22, 163, 74)
_RED = (220, 38, 38)

_REPL = {"€": "EUR", "œ": "oe", "Œ": "OE", "’": "'", "‘": "'", "“": '"', "”": '"',
         "–": "-", "—": "-", "…": "...", " ": " ", "•": "-"}


def _safe(s) -> str:
    s = "" if s is None else str(s)
    for k, v in _REPL.items():
        s = s.replace(k, v)
    return s.encode("latin-1", "replace").decode("latin-1")


def _verdict_color(verdict: str):
    v = (verdict or "").lower()
    return _GREEN if v == "go" else _RED if v == "no-go" else _AMBER


def build_positioning_pdf(scored: ScoredNiche, out_path) -> Path:
    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    pdf = FPDF(orientation="P", unit="mm", format="A4")
    pdf.set_auto_page_break(auto=True, margin=15)
    pdf.add_page()
    W = pdf.w - 20  # largeur utile (marges 10)

    # ── Bandeau titre ──
    pdf.set_fill_color(*_BLUE)
    pdf.rect(0, 0, pdf.w, 26, "F")
    pdf.set_xy(10, 7)
    pdf.set_text_color(255, 255, 255)
    pdf.set_font("Helvetica", "B", 17)
    pdf.cell(W - 45, 8, _safe(scored.niche), ln=0)
    v = scored.verdict
    if v:
        pdf.set_fill_color(*_verdict_color(v.verdict))
        pdf.set_xy(pdf.w - 55, 6)
        pdf.set_font("Helvetica", "B", 12)
        pdf.cell(45, 10, _safe(f"{v.verdict}  {v.confiance}/10"), border=0, align="C", fill=True)
    pdf.set_xy(10, 16)
    pdf.set_font("Helvetica", "", 10)
    pdf.cell(W, 6, _safe(f"Requête : « {scored.requete_amazon or scored.niche} »  ·  "
                         f"{scored.categorie}  ·  score global {scored.global_score}/10"), ln=1)

    pdf.ln(6)
    pdf.set_text_color(*_DARK)

    def h(txt):
        pdf.set_text_color(*_BLUE)
        pdf.set_font("Helvetica", "B", 11)
        pdf.cell(0, 7, _safe(txt), ln=1)
        pdf.set_text_color(*_DARK)

    def kv(label, value):
        pdf.set_font("Helvetica", "B", 9)
        pdf.cell(52, 5.5, _safe(label), ln=0)
        pdf.set_font("Helvetica", "", 9)
        pdf.multi_cell(W - 52, 5.5, _safe(value))

    # ── Chiffres clés ──
    h("Chiffres clés (organique, sponsorisés écartés)")
    bsr41 = "OUI — place à prendre" if scored.criteres_bsr_ok else "non"
    kv("BSR Livres", f"meilleur {scored.bsr_best} · moyenne {scored.bsr_top5_avg} · "
                     f"plus haut {scored.bsr_worst_top10}  |  critères §4.1 : {bsr41}")
    kv("Concurrence", f"{scored.n_organic} résultats · {scored.n_concurrents_cibles} concurrents "
                      f"ciblés · {scored.n_sponsored} sponsorisés écartés")
    kv("Demande", f"{scored.demand_autocomplete} complétions Amazon · note {scored.avg_rating} · "
                  f"{scored.total_reviews} avis cumulés")
    pdf.ln(2)

    if not v:
        pdf.set_text_color(*_MUTED)
        pdf.set_font("Helvetica", "I", 9)
        pdf.multi_cell(0, 5, _safe("Verdict IA non disponible pour cette niche "
                                   "(hors top-3 analysé ou échec de génération)."))
        pdf.output(str(out_path))
        return out_path

    # ── Facteur décisif ──
    h("Le facteur décisif")
    pdf.set_font("Helvetica", "", 10)
    pdf.multi_cell(0, 5.5, _safe(v.facteur_decisif))
    pdf.ln(2)

    # ── Angle recommandé ──
    if v.angles:
        a = v.angles[0]
        pdf.set_fill_color(*_LIGHT)
        y0 = pdf.get_y()
        pdf.set_font("Helvetica", "B", 11)
        pdf.set_text_color(*_AMBER)
        pdf.cell(0, 7, _safe("Angle recommandé"), ln=1)
        pdf.set_text_color(*_DARK)
        pdf.set_font("Helvetica", "B", 14)
        pdf.multi_cell(0, 7, _safe(a.titre))
        pdf.set_font("Helvetica", "I", 11)
        pdf.set_text_color(*_MUTED)
        pdf.multi_cell(0, 6, _safe(a.sous_titre))
        pdf.set_text_color(*_DARK)
        kv("Pourquoi", a.pourquoi)
        kv("Risque", a.risque)
        kv("Couverture", a.direction_couverture)
        kv("Prix", a.prix_suggere)
        kv("Requêtes", _safe(a.requete_principale + " · " + " · ".join(a.requetes_secondaires)))
        pdf.ln(2)

    # ── Angles alternatifs ──
    if len(v.angles) > 1:
        h("Angles alternatifs")
        for a in v.angles[1:]:
            pdf.set_font("Helvetica", "B", 10)
            pdf.multi_cell(0, 5.5, _safe(f"« {a.titre} » — {a.sous_titre}"))
            pdf.set_font("Helvetica", "", 9)
            pdf.set_text_color(*_MUTED)
            pdf.multi_cell(0, 5, _safe(f"{a.angle} (risque : {a.risque})"))
            pdf.set_text_color(*_DARK)
        pdf.ln(1)

    # ── Critique stratégique ──
    h("Critique stratégique")
    kv("Saturation", v.saturation)
    kv("Faux concurrent", v.faux_concurrent)
    kv("Différenciation", v.differenciation)

    # ── Pied de page ──
    pdf.set_y(-14)
    pdf.set_font("Helvetica", "I", 7)
    pdf.set_text_color(*_MUTED)
    foot = "IA-Niches — analyse indicative, à valider par tes propres screenshots Amazon."
    if scored.__dict__.get("cost_run") is not None:  # champ optionnel si un jour ajouté
        foot += f"  Coût run : ~{scored.__dict__['cost_run']:.3f} $"
    pdf.cell(0, 5, _safe(foot), align="C")

    pdf.output(str(out_path))
    return out_path
```
> Note fpdf2 : `pdf.output(str(path))` écrit le fichier. Le `_safe` garantit qu'aucun caractère hors latin-1 n'atteint Helvetica (sinon fpdf2 lève `FPDFUnicodeEncodingException`). Si `multi_cell` sur une largeur pleine pose souci de largeur, laisser `0` (pleine largeur courante).
- [ ] **Step 5 : Run** `python -m pytest tests/test_positioning_pdf.py -v` → 3 pass. Puis `python -m pytest -q` → 73 passed.
- [ ] **Step 6 : Commit**
```bash
git add 01-scripts/positioning_pdf.py 01-scripts/requirements.txt tests/test_positioning_pdf.py
git commit -m "feat(pdf): positioning_pdf — one-pager fpdf2 (verdict + angles, assainisseur latin-1)"
```

---

## Task 6 : Web — endpoint PDF + affichage verdict + bouton

**Files:** Modify `web/server.py` · Modify `web/index.html`

- [ ] **Step 1 : Endpoint `POST /api/pdf` (sans état)** — dans `web/server.py`, ajouter :
```python
import tempfile
from fastapi import Request
from fastapi.responses import Response
from models import ScoredNiche          # noqa: E402
from positioning_pdf import build_positioning_pdf  # noqa: E402


@app.post("/api/pdf")
async def api_pdf(request: Request):
    data = await request.json()
    scored = ScoredNiche.model_validate(data)
    with tempfile.TemporaryDirectory() as d:
        p = build_positioning_pdf(scored, f"{d}/positioning.pdf")
        pdf_bytes = p.read_bytes()
    name = "".join(c for c in (scored.niche or "niche") if c.isalnum() or c in " -_")[:40].strip()
    return Response(content=pdf_bytes, media_type="application/pdf",
                    headers={"Content-Disposition": f'attachment; filename="{name or "niche"}.pdf"'})
```
Vérifier que le serveur importe toujours proprement :
`python -c "import sys; sys.path.insert(0,'01-scripts'); sys.path.insert(0,'web'); import server; print('OK')"`.
- [ ] **Step 2 : UI — afficher le verdict + bouton** — dans `web/index.html`, dans le panneau détail d'une niche (là où sont déjà affichés satellites/ASINs), ajouter, **si `niche.verdict`** :
  - un bloc verdict : badge coloré (`Go` vert / `No-Go` rouge / autre ambre) + `confiance/10`, le `facteur_decisif`, puis pour l'angle `verdict.angles[0]` : titre (gras) + sous-titre + pourquoi/risque + requêtes ;
  - un bouton **« Télécharger le PDF »** qui poste la niche à `/api/pdf` et déclenche le téléchargement :
```javascript
async function downloadPdf(niche) {
  const r = await fetch('/api/pdf', {method: 'POST',
    headers: {'Content-Type': 'application/json'}, body: JSON.stringify(niche)});
  if (!r.ok) { alert('Erreur PDF'); return; }
  const blob = await r.blob();
  const url = URL.createObjectURL(blob);
  const a = document.createElement('a');
  a.href = url; a.download = (niche.niche || 'niche') + '.pdf';
  document.body.appendChild(a); a.click(); a.remove();
  URL.revokeObjectURL(url);
}
```
  Réutiliser les tokens CSS existants (`--blue`/`--amber`/`--text-muted`/`--mono`, badges déjà stylés). Le bouton n'apparaît que pour les niches ayant un `verdict` (top-3). Adapter au vrai code de rendu des lignes/détails (lire `index.html` d'abord ; conserver la structure et le style existants).
- [ ] **Step 3 : Vérifier en live** — `python -m pytest -q` reste vert (73). Puis lancer le serveur (`ia-niches-web`) et charger la page : confirmer via les logs console qu'il n'y a **aucune erreur JS** et que `downloadPdf` est défini (`typeof downloadPdf === 'function'`). (Le rendu complet verdict+PDF se vérifie sur un vrai run — fait par le contrôleur.)
- [ ] **Step 4 : Commit**
```bash
git add web/server.py web/index.html
git commit -m "feat(ui): verdict IA affiché + endpoint /api/pdf + bouton Télécharger le PDF"
```

---

## Self-Review (vs les décisions)
- Verdict complet (Go/No-Go + confiance + facteur décisif + 2-3 angles titre/sous-titre + critique stratégique) → T2 (modèles) + T3 (LLM). ✓
- Modèle `claude-sonnet-5` par défaut, `VERDICT_MODEL` configurable → T3. ✓
- Gate top-3, injectable, non-bloquant → T4 (`n_verdict`, `verdict_fn`, try/except §11.11). ✓ Coût dans `CostTracker` (ideator + verdict). ✓
- PDF fpdf2 à la demande, assainisseur → T5 ; endpoint sans état + bouton → T6. ✓
- `report_builder.py` retiré (choix B) → T1. ✓
- Garde-fou tests : aucun réseau (client Anthropic injecté, PDF pur, endpoint testé via import). ✓ Types cohérents (`NicheVerdict`/`AngleAttaque` définis en T2, consommés en T3/T4/T5/T6). ✓

## Handoff
`python -m pytest -q` vert à chaque tâche (cible finale : 73). Après T6 : smoke test live (contrôleur) — un vrai run pour voir un verdict réel + générer un PDF réel — puis merge sur `main` + push.
