"""R5 (crochets) — un journal BRUT injectable, pour qu'un correctif de parseur ne fasse
jamais repayer.

Le run 4 a payé 185 fiches lues par un parseur qui ne trouvait pas la pagination. Le brut
n'était gardé nulle part : corriger le parseur obligeait à tout racheter. Ces crochets
exposent le brut AU MOMENT où il arrive — payload ASIN rendu par `task_get`, réponse SERP,
réponse de l'outil de classement — AVANT tout parsing. Ils ne décident pas où il est écrit :
c'est la CLI de calibration qui en fait un fichier de run, jamais le cache partagé
(décision de Baptiste). Par défaut rien n'est journalisé : le produit ne change pas.

Données : les 8 captures RÉELLES de `fixtures/fiction/v2_asin_payloads.json` (amazon.fr,
2026-07-20) et la forme RÉELLE du refus 40104 (2026-09-13). Sont INVENTÉS : identifiants de
tâche, fournisseurs et client factices, le résultat SERP de `test_search_providers._RESULT`.
"""
import json
from pathlib import Path

import pytest

from cost_tracker import CostTracker
from fiction_books import parse_enriched_book

_PAYLOADS = json.loads((Path(__file__).parent / "fixtures" / "fiction" /
                        "v2_asin_payloads.json").read_text(encoding="utf-8"))


def _octets(x):
    return json.dumps(x, sort_keys=True, ensure_ascii=False)


@pytest.fixture(autouse=True)
def _sans_sommeil(monkeypatch):
    monkeypatch.setattr("search_providers.time.sleep", lambda s: None)


def _fournisseur(**kw):
    from search_providers import DataForSEOProvider
    return DataForSEOProvider(login="l", password="p", **kw)


def _post_echo(url, body):
    return {"status_code": 20000, "tasks": [
        {"status_code": 20100, "id": f"t-{it['asin']}", "data": {"asin": it["asin"]}}
        for it in body]}


def _get_reel(url):
    asin = url.rsplit("t-", 1)[1]
    return {"tasks": [{"status_code": 20000, "result": [_PAYLOADS[asin]]}]}


# ══ ASIN ═════════════════════════════════════════════════════════════════════════

def test_R5_enrich_asins_journalise_le_payload_brut_avant_parsing():
    from fiction_serp_provider import enrich_asins
    appels = []

    class _Prov:
        location_code, priority = 2250, 2

        def product_raw_batch(self, asins):
            appels.append(list(asins))
            return {a: _PAYLOADS[a] for a in asins}

    journal = []
    enrich_asins(["1923235036"], _Prov(), cost=CostTracker(), journal_brut=journal)
    assert len(journal) == 1 and journal[0]["asin"] == "1923235036"
    assert _octets(journal[0]["payload"]) == _octets(_PAYLOADS["1923235036"])
    # Rejeu : le brut suffit, le fournisseur n'est pas rappelé.
    assert parse_enriched_book(journal[0]["payload"]).pages == 335
    assert len(appels) == 1


def test_R5_product_raw_batch_journalise_au_moment_de_la_LECTURE():
    journal = []
    out = _fournisseur().product_raw_batch(["1923235036", "2749187052"],
                                           post_json=_post_echo, get_json=_get_reel,
                                           poll_interval=0, journal_brut=journal)
    assert {e["asin"] for e in journal} == {"1923235036", "2749187052"}
    for e in journal:
        assert _octets(e["payload"]) == _octets(_PAYLOADS[e["asin"]])
        assert e["payload"] is out[e["asin"]] or _octets(e["payload"]) == _octets(out[e["asin"]])


def test_R5_un_ctrl_c_en_plein_poll_laisse_le_brut_deja_lu_dans_le_journal():
    """Le journal est la liste de l'APPELANT : ce qui a été lu avant l'interruption y reste,
    alors que le dict de retour, lui, n'est jamais rendu."""
    lus = []

    def get(url):
        if lus:
            raise KeyboardInterrupt
        lus.append(url)
        return _get_reel(url)

    journal = []
    with pytest.raises(KeyboardInterrupt):
        _fournisseur().product_raw_batch(["1923235036", "2749187052"], post_json=_post_echo,
                                         get_json=get, poll_interval=0, journal_brut=journal)
    assert len(journal) == 1


def test_R5_enrich_asins_avec_le_vrai_fournisseur_ne_journalise_qu_une_fois(monkeypatch):
    from fiction_serp_provider import enrich_asins
    prov = _fournisseur()
    monkeypatch.setattr(prov, "_post", _post_echo)
    monkeypatch.setattr(prov, "_get", _get_reel)
    journal = []
    out = enrich_asins(["1923235036", "2749187052"], prov, cost=CostTracker(),
                       journal_brut=journal)
    assert len(out) == 2
    assert sorted(e["asin"] for e in journal) == ["1923235036", "2749187052"]


def test_R5_sans_journal_rien_ne_change():
    from fiction_serp_provider import enrich_asins

    class _Prov:
        location_code, priority = 2250, 2

        def product_raw_batch(self, asins):          # signature historique, sans journal
            return {a: _PAYLOADS[a] for a in asins}

    assert enrich_asins(["1923235036"], _Prov(), cost=CostTracker())["1923235036"].pages == 335


# ══ SERP ═════════════════════════════════════════════════════════════════════════

def test_R5_le_fournisseur_journalise_la_SERP_brute_et_le_refus():
    from search_providers import RefusCompte, map_dataforseo_result
    from tests.test_search_providers import _RESULT
    journal = []
    prov = _fournisseur(journal_brut=journal)
    reponse_get = {"tasks": [{"status_code": 20000, "result": [_RESULT]}]}
    sr = prov.search("tarot", post_json=lambda u, b: {"tasks": [
        {"status_code": 20100, "id": "serp-1"}]}, get_json=lambda u: reponse_get,
        poll_interval=0)
    lu = [e for e in journal if e["type"] == "serp_get"]
    assert len(lu) == 1 and lu[0]["keyword"] == "tarot"
    assert map_dataforseo_result(lu[0]["reponse"]["tasks"][0]["result"][0]) == sr

    refus = {"status_code": 40104, "status_message": "Please verify your account before "
             "using the API.", "tasks": None}
    with pytest.raises(RefusCompte):
        prov.search("carnet", post_json=lambda u, b: refus, get_json=lambda u: {},
                    poll_interval=0)
    assert journal[-1]["type"] == "serp_post" and journal[-1]["reponse"] == refus
    assert "auth" not in _octets(journal) and '"p"' not in _octets(journal)


def test_R5_un_fournisseur_sans_journal_ne_journalise_rien():
    from tests.test_search_providers import _RESULT
    prov = _fournisseur()
    assert prov.journal_brut is None
    prov.search("tarot", post_json=lambda u, b: {"tasks": [{"status_code": 20100, "id": "s"}]},
                get_json=lambda u: {"tasks": [{"status_code": 20000, "result": [_RESULT]}]},
                poll_interval=0)
    assert prov.journal_brut is None


# ══ Classement ═══════════════════════════════════════════════════════════════════

class _Bloc:
    type = "tool_use"

    def __init__(self, payload):
        self.input = payload


class _Usage:
    input_tokens, output_tokens = 1500, 900


class _Client:
    def __init__(self, payload, stop_reason="tool_use"):
        self.payload, self.stop_reason, self.messages = payload, stop_reason, self

    def create(self, **kw):
        r = type("R", (), {})()
        r.content, r.usage, r.stop_reason = [_Bloc(self.payload)], _Usage(), self.stop_reason
        return r


def test_R5_la_reponse_brute_du_classement_est_journalisee_meme_illisible():
    """Le cas du 2026-09-13 : des niches rendues en TEXTE. Illisibles pour le code, elles
    sont exactement ce qu'il faut garder pour comprendre."""
    from autocomplete_expand import Suggestion
    from lowcontent_ideator import generate_lowcontent_niches
    payload = {"niches": "[pas du json"}
    journal = []
    out = generate_lowcontent_niches(
        suggestions=[Suggestion(requete="carnet de suivi migraine", parent="", profondeur=0,
                                n_enfants=3)],
        client=_Client(payload, stop_reason="max_tokens"), journal_brut=journal)
    assert out == []
    assert len(journal) == 1
    e = journal[0]
    assert e["type"] == "classement" and e["stop_reason"] == "max_tokens"
    assert e["inputs"] == [payload]
    assert e["usage"] == {"input_tokens": 1500, "output_tokens": 900}
    assert e["modele"]


# ══ Master : transmission, et rien par défaut ═════════════════════════════════════

def test_R5_le_master_transmet_le_journal_a_l_ideator_au_fournisseur_et_au_batch(monkeypatch):
    import lowcontent_master
    from autocomplete_expand import Suggestion
    from models import LowContentNiche, SearchItem, SearchResult
    vus = {"ideate": [], "enrich": [], "provider": []}
    niche = LowContentNiche(niche="carnet a", requete_amazon="carnet a", rationale="r",
                            categorie="c", format_cle="journal_suivi", theme="t",
                            public="adulte", n_enfants_autocomplete=3)

    class _Prov:
        location_code, language_code, priority = 2250, "fr_FR", 2

        def search(self, q, books_only=True):
            return SearchResult(keyword=q, organic=[SearchItem(asin="X1", title=q)])

    def get_provider(nom="dataforseo", **kw):
        vus["provider"].append(kw)
        return _Prov()
    monkeypatch.setattr(lowcontent_master, "get_provider", get_provider)

    def lancer(**kw):
        return lowcontent_master.run_lowcontent_scout(
            seed="carnet", use_cache=False, bsr_pause=0, cost=CostTracker(),
            expand_fn=lambda *a, **k: [Suggestion(requete="carnet a", parent="",
                                                  profondeur=0, n_enfants=3)],
            ideate=lambda **k: vus["ideate"].append(k) or [niche],
            enrich_fn=lambda asins, **k: vus["enrich"].append(k) or {},
            fetch_bsr_fn=lambda asin: None, **kw)

    lancer()
    assert "journal_brut" not in vus["ideate"][0]
    assert "journal_brut" not in vus["enrich"][0]
    assert vus["provider"][0] == {}

    journal = []
    lancer(journal_brut=journal)
    assert vus["ideate"][1]["journal_brut"] is journal
    assert vus["enrich"][1]["journal_brut"] is journal
    assert vus["provider"][1]["journal_brut"] is journal
