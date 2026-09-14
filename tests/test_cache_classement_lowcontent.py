"""R12 — le classement Anthropic du low-content, mis en cache PARTAGÉ (mode classement seul).

Chaque relance de la calibration repayait ~0,08-0,09 $ (mesuré, runs du 2026-09-13) pour
reclasser exactement les mêmes 31 requêtes, avec le même modèle et la même consigne. Rien
n'y dépend du compte : les requêtes sont des complétions PUBLIQUES d'Amazon, le cache peut
donc être mutualisé (§1), comme les SERP.

Ce qui est mis en cache est la réponse BRUTE de l'outil (`block.input`), jamais les niches
déjà analysées : la relecture repasse par la logique COURANTE (remappage de format, filtre
IP rejoué, recalage verbatim). Un correctif de cette logique s'applique donc aux
classements déjà en cache, sans rien repayer.

Une réponse n'est écrite que si elle est COMPLÈTE : ni tronquée, ni partiellement
illisible, ni porteuse d'une requête hors liste, ni — en mesure — amputée d'une requête
omise. Mettre en cache une réponse défectueuse la resservirait 15 jours à tout le monde.
Jamais en idéation : la graine est une intention de l'utilisateur, et une relance y est
voulue.

Données : les 31 requêtes RÉELLES du classeur `99-logs/validation-lc.xlsx` (lecture seule).
Sont INVENTÉS : le client Anthropic factice, les étiquettes qu'il rend (format, thème,
public) et le `n_enfants` des suggestions.
"""
from pathlib import Path

import pytest

import lowcontent_ideator
from autocomplete_expand import Suggestion
from cache import Cache
from ip_filter import filtrer_ip
from lowcontent_ideator import generate_lowcontent_niches

_RACINE = Path(__file__).resolve().parent.parent
_CLASSEUR = _RACINE / "99-logs" / "validation-lc.xlsx"


def _requetes_reelles() -> list[str]:
    if not _CLASSEUR.exists():
        pytest.skip("classeur réel absent (clone neuf)")
    from lowcontent_validation import charger_etiquettes
    return [e.requete for e in charger_etiquettes(_CLASSEUR)]


class _Bloc:
    type = "tool_use"

    def __init__(self, payload):
        self.input = payload


class _Usage:
    input_tokens = 2100
    output_tokens = 4300


class _Reponse:
    def __init__(self, payload, stop_reason):
        self.content = [_Bloc(payload)]
        self.usage = _Usage()
        self.stop_reason = stop_reason


class _Client:
    """Compte les `create` : un appel compté est un appel payé."""

    def __init__(self, payload, stop_reason="tool_use"):
        self.payload, self.stop_reason, self.appels = payload, stop_reason, []
        self.messages = self

    def create(self, **kw):
        self.appels.append(kw)
        return _Reponse(self.payload, self.stop_reason)


def _suggestions():
    sugg = [Suggestion(requete=q, parent="", profondeur=0, n_enfants=3)
            for q in _requetes_reelles()]
    return filtrer_ip(sugg)[0]


def _payload(requetes):
    return {"niches": [{"requete_amazon": q, "niche": q, "format_cle": "journal_suivi",
                        "theme": "t", "public": "adulte", "rationale": "r",
                        "categorie": "c"} for q in requetes]}


def _classer(client, cache, suggestions, **kw):
    usages, etapes = [], []
    base = dict(suggestions=suggestions, n=len(suggestions), inclure_saisonnier=True,
                client=client, cache=cache, classer_toutes=True,
                on_usage=lambda i, o, m: usages.append((i, o, m)),
                progress=etapes.append)
    base.update(kw)
    return generate_lowcontent_niches(**base), usages, etapes


def test_R12_deux_classements_identiques_un_seul_appel(tmp_path):
    sugg = _suggestions()
    assert len(sugg) >= 30
    client = _Client(_payload([s.requete for s in sugg]))
    cache = Cache(tmp_path / "c.db")
    n1, u1, _ = _classer(client, cache, sugg)
    n2, u2, etapes = _classer(client, cache, sugg)
    assert len(client.appels) == 1
    assert len(u1) == 1 and u2 == [], "un classement repris du cache ne coûte rien"
    assert [n.model_dump() for n in n1] == [n.model_dump() for n in n2]
    assert any("classement repris du cache (0 appel)" in e.lower() for e in etapes), etapes


def test_R12_un_classement_repris_du_cache_n_ouvre_meme_pas_de_client(tmp_path, monkeypatch):
    sugg = _suggestions()
    cache = Cache(tmp_path / "c.db")
    _classer(_Client(_payload([s.requete for s in sugg])), cache, sugg)

    def _interdit():
        raise AssertionError("client Anthropic construit alors que le cache répond")
    monkeypatch.setattr(lowcontent_ideator, "_default_client", _interdit)
    n, _, _ = _classer(None, cache, sugg)
    assert len(n) == len(sugg)


def test_R12_une_reponse_TRONQUEE_n_est_pas_mise_en_cache(tmp_path):
    sugg = _suggestions()
    client = _Client(_payload([s.requete for s in sugg]), stop_reason="max_tokens")
    cache = Cache(tmp_path / "c.db")
    _classer(client, cache, sugg)
    _classer(client, cache, sugg)
    assert len(client.appels) == 2


def test_R12_en_mesure_une_requete_OMISE_empeche_la_mise_en_cache(tmp_path):
    sugg = _suggestions()
    client = _Client(_payload([s.requete for s in sugg][1:]))
    cache = Cache(tmp_path / "c.db")
    _classer(client, cache, sugg)
    _classer(client, cache, sugg)
    assert len(client.appels) == 2


def test_R12_une_requete_HORS_LISTE_empeche_la_mise_en_cache(tmp_path):
    sugg = _suggestions()
    client = _Client(_payload([s.requete for s in sugg] + ["carnet invente par le modele"]))
    cache = Cache(tmp_path / "c.db")
    _classer(client, cache, sugg)
    _classer(client, cache, sugg)
    assert len(client.appels) == 2


def test_R12_une_entree_ILLISIBLE_empeche_la_mise_en_cache(tmp_path):
    sugg = _suggestions()
    payload = _payload([s.requete for s in sugg])
    payload["niches"].append("texte hors schéma")
    client = _Client(payload)
    cache = Cache(tmp_path / "c.db")
    _classer(client, cache, sugg)
    _classer(client, cache, sugg)
    assert len(client.appels) == 2


def test_R12_jamais_en_IDEATION(tmp_path):
    client = _Client(_payload(["carnet de suivi glycemie", "registre des visiteurs"]))
    cache = Cache(tmp_path / "c.db")
    for _ in range(2):
        generate_lowcontent_niches(seed=None, suggestions=None, n=2, client=client,
                                   cache=cache)
    assert len(client.appels) == 2


def test_R12_changer_la_CONSIGNE_invalide_le_cache(tmp_path, monkeypatch):
    sugg = _suggestions()
    client = _Client(_payload([s.requete for s in sugg]))
    cache = Cache(tmp_path / "c.db")
    _classer(client, cache, sugg)
    monkeypatch.setattr(lowcontent_ideator, "SYSTEM_PROMPT",
                        lowcontent_ideator.SYSTEM_PROMPT + "\nConsigne durcie.")
    _classer(client, cache, sugg)
    assert len(client.appels) == 2


def test_R12_changer_de_MODELE_invalide_le_cache(tmp_path):
    sugg = _suggestions()
    client = _Client(_payload([s.requete for s in sugg]))
    cache = Cache(tmp_path / "c.db")
    _classer(client, cache, sugg, model="claude-sonnet-5")
    _classer(client, cache, sugg, model="claude-opus-4-8")
    assert len(client.appels) == 2


def test_R12_la_relecture_passe_par_la_logique_COURANTE(tmp_path, monkeypatch):
    """Ce qui est en cache est le brut : un format retiré de la taxonomie depuis la mise en
    cache doit ressortir remappé en « other », pas tel qu'il avait été lu à l'époque."""
    sugg = _suggestions()
    client = _Client(_payload([s.requete for s in sugg]))
    cache = Cache(tmp_path / "c.db")
    _classer(client, cache, sugg)
    vrai = lowcontent_ideator.valid_formats
    monkeypatch.setattr(lowcontent_ideator, "valid_formats",
                        lambda v: [f for f in vrai(v) if f != "journal_suivi"])
    n, _, _ = _classer(client, cache, sugg)
    assert len(client.appels) == 1
    assert {x.format_cle for x in n} == {"other"}


def test_R12_de_bout_en_bout_le_second_run_ne_rappelle_pas_le_modele(tmp_path):
    from cost_tracker import CostTracker
    from lowcontent_master import run_lowcontent_scout
    from models import SearchItem, SearchResult
    sugg = _suggestions()[:3]
    client = _Client(_payload([s.requete for s in sugg]))

    class _Prov:
        location_code, language_code, priority = 2250, "fr_FR", 2

        def search(self, q, books_only=True):
            return SearchResult(keyword=q, organic=[SearchItem(asin="X1", title=q)])

    couts = []
    for _ in range(2):
        cost = CostTracker()
        run_lowcontent_scout(
            seed="carnet", cache_path=str(tmp_path / "df-cache.db"), provider=_Prov(),
            cost=cost, bsr_pause=0, n_search=3, inclure_saisonnier=True,
            classer_toutes=True, expand_fn=lambda *a, **k: list(sugg),
            ideate=lambda **kw: generate_lowcontent_niches(client=client, **kw),
            enrich_fn=lambda asins, **kw: {}, fetch_bsr_fn=lambda asin: None)
        couts.append(cost.breakdown())
    assert len(client.appels) == 1
    assert couts[1]["usd"] == 0
