"""Fournisseur, facturation, canal BSR — ce que le rejeu à blanc du 2026-09-14 a mesuré.

Cinq chemins où une tâche DataForSEO est CRÉÉE, donc facturée, sans que le coût du run le
dise, ou où une panne se lit comme une mesure :

- R7 : une SERP créée puis non lue (poll épuisé, réponse illisible) n'était imputée sur
  aucun des trois moteurs. Seul un refus EXPLICITE de `task_post` n'est pas facturé : c'est
  lui, et lui seul, que `TaskPostRefuse` distingue.
- R8 : un seul GET de relecture illisible pendant le poll du batch ASIN abandonnait tout le
  lot — 185 fiches déjà facturées au run 4.
- R9 : un Ctrl-C pendant le batch n'imputait rien (0,0000 $ mesuré sur 185 tâches créées),
  et la CLI affirmait que les fiches rendues étaient en cache.
- R6 : un refus de COMPTE (40104 posé à la racine) déclenchait un `task_post` par niche en
  rafale, alors que le cache pouvait encore servir une partie du rayon gratuitement.
- R14 : le canal BSR de repli écrivait une PANNE dans le cache MUTUALISÉ comme « absence
  de classement », pour 3 jours et pour tous les comptes.

Données : les 8 payloads ASIN RÉELS de `fixtures/fiction/v2_asin_payloads.json` (amazon.fr,
2026-07-20), la SERP RÉELLE `v1a_serp_cosy_mystery.json`, et la forme RÉELLE du refus 40104
relevée le 2026-09-13. Sont INVENTÉS, et dits comme tels là où ils servent : les
identifiants de tâche, les ASIN de remplissage (volume de 185 ou 18 tâches), le code 40501
d'un refus par tâche, les requêtes des niches, et le statut `20100` rendu par un task_get
pour une tâche NON PRÊTE — aucune réponse task_get d'une tâche en file n'est capturée ; le
code ne teste que `20000`, tout autre statut fait repoller. Idem pour le code d'ERREUR
définitive d'une tâche ASIN (R14) : forme jamais capturée, déclarée là où elle sert. Aucun réseau : HTTP injecté dans le VRAI
`DataForSEOProvider`, jamais la fonction testée remplacée (§2.16).
"""
import json
import re
from pathlib import Path

import pytest

from cache import Cache
from cost_tracker import CostTracker
from models import EnrichedBook, SearchResult

_FIX = Path(__file__).parent / "fixtures" / "fiction"
_PAYLOADS = json.loads((_FIX / "v2_asin_payloads.json").read_text(encoding="utf-8"))
_SERP_REELLE = SearchResult(**json.loads(
    (_FIX / "v1a_serp_cosy_mystery.json").read_text(encoding="utf-8")))

# Forme RÉELLE (2026-09-13) : code et message à la racine, aucune tâche.
_COMPTE_NON_VERIFIE = {
    "status_code": 40104,
    "status_message": "Please verify your account before using the API. You can complete "
                      "verification in the user panel: https://app.dataforseo.com/ .",
    "tasks": None,
}


def _fournisseur():
    from search_providers import DataForSEOProvider
    return DataForSEOProvider(login="l", password="p")


@pytest.fixture(autouse=True)
def _sans_sommeil(monkeypatch):
    """Le poll dort 8 s entre deux lectures : 40 cycles × 3 tâches rendraient la suite
    inutilisable. Seul le sommeil est coupé, jamais la boucle."""
    monkeypatch.setattr("search_providers.time.sleep", lambda s: None)
    monkeypatch.setattr("bsr_source.time.sleep", lambda s: None)


def _post_echo(url, body):
    """task_post accepté : une tâche par ASIN posté, écho de l'ASIN (id INVENTÉ)."""
    return {"status_code": 20000, "tasks": [
        {"status_code": 20100, "id": f"t-{it['asin']}", "data": {"asin": it["asin"]}}
        for it in body]}


def _reponse_tache(payload):
    return {"tasks": [{"status_code": 20000, "result": [payload]}]}


# ══ R7 — seule une tâche REFUSÉE n'est pas facturée ═══════════════════════════════

def test_R7_un_refus_de_task_post_est_un_TaskPostRefuse():
    from search_providers import RefusCompte, TaskPostRefuse
    with pytest.raises(TaskPostRefuse) as exc:
        _fournisseur().search("carnet de voyage",
                              post_json=lambda url, body: _COMPTE_NON_VERIFIE,
                              get_json=lambda url: {}, poll_interval=0)
    assert isinstance(exc.value, RefusCompte)
    assert isinstance(exc.value, RuntimeError)       # aucun appelant existant ne casse


def test_R7_un_refus_PAR_TACHE_est_refuse_mais_pas_un_refus_de_compte():
    """Code 40501 INVENTÉ pour le test (forme observée : racine Ok, motif dans la tâche)."""
    from search_providers import RefusCompte, TaskPostRefuse
    reponse = {"status_code": 20000, "status_message": "Ok.",
               "tasks": [{"status_code": 40501, "status_message": "Invalid Field."}]}
    with pytest.raises(TaskPostRefuse) as exc:
        _fournisseur().search("carnet", post_json=lambda url, body: reponse,
                              get_json=lambda url: {}, poll_interval=0)
    assert not isinstance(exc.value, RefusCompte)


def test_R7_une_tache_CREEE_jamais_prete_n_est_pas_un_refus():
    """Statut task_get `20100` INVENTÉ (non capturé) : seul `20000` est lu comme prêt."""
    from search_providers import TaskPostRefuse
    en_file = {"tasks": [{"status_code": 20100}]}
    with pytest.raises(TimeoutError, match="non prêt") as exc:
        _fournisseur().search("carnet", post_json=_post_echo_serp,
                              get_json=lambda url: en_file, poll_interval=0, max_polls=2)
    assert not isinstance(exc.value, TaskPostRefuse)


def _post_echo_serp(url, body):
    return {"status_code": 20000, "tasks": [{"status_code": 20100, "id": "serp-1"}]}


class _ProvSerp:
    """Fournisseur de masters : un vrai `DataForSEOProvider` y dormirait 320 s par niche.
    `search` lève `TimeoutError` (tâche créée, jamais lue) sur une requête et un refus
    explicite sur une autre ; les requêtes sont INVENTÉES."""
    priority = 2
    location_code = 2250
    language_code = "fr_FR"

    def __init__(self):
        self.appels = []

    def search(self, q, books_only=True, **kw):
        from search_providers import TaskPostRefuse
        self.appels.append(q)
        if "lente" in q:
            raise TimeoutError("résultat DataForSEO non prêt après 320 s (id=x)")
        raise TaskPostRefuse("task_post refusé : 40501 Invalid Field.")

    def product_raw_batch(self, asins, **kw):
        raise AssertionError("aucun ASIN ne doit être enrichi ici")


def test_R7_lowcontent_impute_la_SERP_creee_et_pas_la_SERP_refusee():
    from lowcontent_master import run_lowcontent_scout
    from tests.test_lowcontent_master import _expand_fige, _ideate_fige, _niche
    cost = CostTracker(plafond_usd=None)
    requetes = ["carnet file lente", "carnet refuse net"]
    run_lowcontent_scout(seed="carnet", expand_fn=_expand_fige(requetes),
                         ideate=_ideate_fige([_niche(r) for r in requetes]),
                         provider=_ProvSerp(), use_cache=False, cost=cost,
                         fetch_bsr_fn=lambda a: None, bsr_pause=0)
    assert cost.breakdown()["dataforseo_calls"] == 1


def test_R7_scout_non_fiction_impute_la_SERP_creee_et_pas_la_SERP_refusee():
    from scout_master import run_scout
    from models import NicheCandidate, NicheValidation
    requetes = ["tarot file lente", "tarot refuse net"]

    def ideate(**kw):
        return [NicheCandidate(niche=r, requete_amazon=r, rationale="r", categorie="c")
                for r in requetes]

    def validate(cands, **kw):
        return [NicheValidation(niche=r, requete_amazon=r, categorie="c", demand_score=5,
                                validated=True) for r in requetes]

    cost = CostTracker(plafond_usd=None)
    run_scout(seed="tarot", ideate=ideate, validate=validate, provider=_ProvSerp(),
              use_cache=False, cost=cost, fetch_bsr_fn=lambda a: None, bsr_pause=0)
    assert cost.breakdown()["dataforseo_calls"] == 1


def test_R7_fetch_shelf_asins_impute_puis_relance_une_SERP_creee():
    from fiction_serp_provider import fetch_shelf_asins
    from models import FictionNiche
    from search_providers import TaskPostRefuse
    lente = FictionNiche(sous_genre="cosy_mystery", tropes=["t"], decor="d",
                         rayon="kindle", query="cosy file lente")
    refusee = lente.model_copy(update={"query": "cosy refuse net"})
    cost = CostTracker(plafond_usd=None)
    with pytest.raises(TimeoutError):
        fetch_shelf_asins(lente, _ProvSerp(), cost=cost)
    with pytest.raises(TaskPostRefuse):
        fetch_shelf_asins(refusee, _ProvSerp(), cost=cost)
    assert cost.breakdown()["dataforseo_calls"] == 1


# ══ R8 — un GET illisible n'abandonne plus un lot facturé ═════════════════════════

_TROIS = ["1923235036", "2749187052", "B0CH23Z17T"]      # payloads RÉELS


def _get_qui_trebuche(n_echecs_par_tache=1):
    """Le premier GET de la première tâche lève l'exception RÉELLE de `requests` sur un
    corps non-JSON (502 HTML), puis les payloads réels reviennent."""
    import requests
    vus = {}

    def get(url):
        tid = url.rsplit("/", 1)[-1]
        vus[tid] = vus.get(tid, 0) + 1
        if tid == f"t-{_TROIS[0]}" and vus[tid] <= n_echecs_par_tache:
            raise requests.exceptions.JSONDecodeError("Expecting value", "<html>502", 0)
        return _reponse_tache(_PAYLOADS[tid[2:]])
    return get


def test_R8_un_GET_illisible_ne_fait_pas_perdre_le_lot():
    out = _fournisseur().product_raw_batch(_TROIS, post_json=_post_echo,
                                           get_json=_get_qui_trebuche(), poll_interval=0)
    assert all(out[a] is not None for a in _TROIS)
    assert out.taches_creees == 3
    assert out.lectures_en_echec == {"JSONDecodeError": 1}


def test_R8_via_enrich_asins_les_fiches_arrivent_en_cache_et_l_echec_est_dit(tmp_path):
    from fiction_serp_provider import enrich_asins
    prov = _fournisseur()
    prov._post = _post_echo
    prov._get = _get_qui_trebuche()
    cache, cost, etapes = Cache(tmp_path / "c.db"), CostTracker(plafond_usd=None), []
    out = enrich_asins(_TROIS, provider=prov, cache=cache, cost=cost,
                       progress=etapes.append)
    assert set(out) == set(_TROIS)
    assert all(cache.get_book(a, 2250) is not None for a in _TROIS)
    assert cost.breakdown()["dataforseo_calls"] == 3
    assert any("JSONDecodeError" in e for e in etapes)


def test_R8_un_GET_qui_leve_TOUJOURS_ne_leve_pas_et_impute_quand_meme():
    def jamais(url):
        raise ConnectionError("réseau coupé")
    out = _fournisseur().product_raw_batch(_TROIS, post_json=_post_echo,
                                           get_json=jamais, poll_interval=0)
    assert all(out[a] is None for a in _TROIS)
    assert out.taches_creees == 3


# ══ R9 — Ctrl-C : imputé au pire cas, puis relancé ════════════════════════════════

_185 = [f"B0FAKE{i:04d}" for i in range(185)]           # ASIN INVENTÉS : seul le volume compte


def _prov_coupe_au_poll():
    prov = _fournisseur()
    prov._post = _post_echo

    def get(url):
        raise KeyboardInterrupt()
    prov._get = get
    return prov


def test_R9_un_CTRL_C_pendant_le_poll_impute_les_taches_creees():
    from fiction_serp_provider import enrich_asins
    cost = CostTracker(plafond_usd=None)
    with pytest.raises(KeyboardInterrupt):
        enrich_asins(_185, provider=_prov_coupe_au_poll(), cost=cost)
    assert cost.breakdown()["dataforseo_calls"] == 185


def test_R9_un_CTRL_C_pendant_une_SERP_lowcontent_impute_la_tache():
    from lowcontent_master import run_lowcontent_scout
    from tests.test_lowcontent_master import _expand_fige, _ideate_fige, _niche

    class _Coupe(_ProvSerp):
        def search(self, q, books_only=True, **kw):
            raise KeyboardInterrupt()

    cost = CostTracker(plafond_usd=None)
    with pytest.raises(KeyboardInterrupt):
        run_lowcontent_scout(seed="carnet", expand_fn=_expand_fige(["carnet a"]),
                             ideate=_ideate_fige([_niche("carnet a")]), provider=_Coupe(),
                             use_cache=False, cost=cost, fetch_bsr_fn=lambda a: None)
    assert cost.breakdown()["dataforseo_calls"] == 1


def test_R9_la_CLI_dit_AU_MOINS_le_montant_engage_sans_promettre_le_cache(
        tmp_path, monkeypatch, capsys):
    import build_lowcontent_validation_set as cli
    from fiction_serp_provider import enrich_asins
    from tests.test_calibration_run_plantage import _classeur
    # Isole le VRAI df-cache.db : la CLI chiffre desormais un devis en lisant le cache, et ce
    # test ne doit pas dependre de ce que le poste a deja achete.
    monkeypatch.setenv("DATA_DIR", str(tmp_path / "donnees"))

    def construire(*a, cost=None, **k):
        cost.add_llm("claude-sonnet-5", 6000, 8750)     # le classement est revenu
        enrich_asins(_185, provider=_prov_coupe_au_poll(), cost=cost)

    monkeypatch.setattr(cli, "construire_rapport", construire)
    sortie = tmp_path / "r.json"
    try:
        code = cli.main(["--xlsx", str(_classeur(tmp_path)), "--out", str(sortie)])
    except KeyboardInterrupt:
        pytest.fail("le Ctrl-C a traversé la CLI sans laisser de rapport")
    assert code == 130
    avert = " ".join(json.loads(sortie.read_text(encoding="utf-8"))["avertissements"])
    montant = float(re.search(r"au moins ([\d.]+) \$", avert).group(1))
    assert montant >= 0.555
    assert "fiches déjà rendues sont en cache" not in avert


# ══ R6 — refus de COMPTE : fin de la rafale, le cache sert encore ═════════════════

class _CompteRefuse:
    """HTTP injecté dans le VRAI fournisseur : chaque `task_post` rend la forme réelle du
    40104. Compte les envois."""

    def __init__(self, reponse=_COMPTE_NON_VERIFIE):
        self.posts = []
        self.reponse = reponse

    def poser(self, prov):
        prov._post = lambda url, body: (self.posts.append(url), self.reponse)[1]
        prov._get = lambda url: pytest.fail("aucune tâche créée, rien à relire")
        return prov


_REQ5 = [f"carnet de suivi {i}" for i in range(1, 6)]    # requêtes INVENTÉES


def _cache_avec_3_et_5(tmp_path):
    """SERP RÉELLE en cache pour les niches 3 et 5 (seul le mot-clé est réécrit) ; la fiche
    RÉELLE de 2036073689 — 5e organique de cette même SERP, éditeur « Larousse », le seul
    des 8 payloads v2 que `est_indie` sait classer — en cache sous son propre ASIN."""
    cache = Cache(tmp_path / "c.db")
    for q in (_REQ5[2], _REQ5[4]):
        cache.set_search(q, 2250, "fr_FR", _SERP_REELLE.model_copy(update={"keyword": q}),
                         3600)
    from fiction_books import parse_enriched_book
    asin = "2036073689"
    cache.set_book(asin, 2250, parse_enriched_book(_PAYLOADS[asin]), 3600)
    return cache, asin


def test_R6_lowcontent_un_seul_post_le_cache_sert_le_reste(tmp_path):
    from lowcontent_master import run_lowcontent_scout
    from tests.test_lowcontent_master import _expand_fige, _ideate_fige, _niche
    _cache_avec_3_et_5(tmp_path)
    espion, etapes = _CompteRefuse(), []
    out = run_lowcontent_scout(seed="carnet", expand_fn=_expand_fige(_REQ5),
                               ideate=_ideate_fige([_niche(r) for r in _REQ5]),
                               provider=espion.poser(_fournisseur()),
                               cache_path=str(tmp_path / "c.db"),
                               cost=CostTracker(plafond_usd=None),
                               fetch_bsr_fn=lambda a: None, bsr_pause=0,
                               progress=etapes.append)
    assert len(espion.posts) == 1, espion.posts
    assert len(out) == 5
    mesurees = {s.niche.requete_amazon for s in out if s.concurrence_mesuree}
    assert mesurees == {_REQ5[2], _REQ5[4]}
    assert any("3 niche(s) non mesurée(s)" in e and "40104" in e for e in etapes)
    # la fiche en cache est rendue : le rayon lu gratuitement n'est pas jeté
    assert any(s.part_indie is not None for s in out if s.niche.requete_amazon == _REQ5[2])


def test_R6_un_refus_PAR_TACHE_ne_coupe_pas_la_suite(tmp_path):
    from lowcontent_master import run_lowcontent_scout
    from tests.test_lowcontent_master import _expand_fige, _ideate_fige, _niche
    _cache_avec_3_et_5(tmp_path)
    par_tache = {"status_code": 20000, "status_message": "Ok.",
                 "tasks": [{"status_code": 40501, "status_message": "Invalid Field."}]}
    espion = _CompteRefuse(par_tache)
    run_lowcontent_scout(seed="carnet", expand_fn=_expand_fige(_REQ5),
                         ideate=_ideate_fige([_niche(r) for r in _REQ5]),
                         provider=espion.poser(_fournisseur()),
                         cache_path=str(tmp_path / "c.db"),
                         cost=CostTracker(plafond_usd=None),
                         fetch_bsr_fn=lambda a: None, bsr_pause=0)
    # 3 SERP absentes du cache, chacune tentée : le batch, lui, part aussi (1 lot).
    assert sum("products/task_post" in u for u in espion.posts) == 3


def test_R6_scout_non_fiction_meme_traitement(tmp_path):
    from scout_master import run_scout
    from models import NicheCandidate, NicheValidation
    _cache_avec_3_et_5(tmp_path)

    def ideate(**kw):
        return [NicheCandidate(niche=r, requete_amazon=r, rationale="r", categorie="c")
                for r in _REQ5]

    def validate(cands, **kw):
        return [NicheValidation(niche=r, requete_amazon=r, categorie="c", demand_score=5,
                                validated=True) for r in _REQ5]

    espion, etapes = _CompteRefuse(), []
    out = run_scout(seed="carnet", ideate=ideate, validate=validate, n_search=5,
                    provider=espion.poser(_fournisseur()), cache_path=str(tmp_path / "c.db"),
                    cost=CostTracker(plafond_usd=None), fetch_bsr_fn=lambda a: None,
                    bsr_pause=0, progress=etapes.append)
    assert len(espion.posts) == 1
    assert len(out) == 5
    assert {s.niche for s in out if s.concurrence_mesuree} == {_REQ5[2], _REQ5[4]}
    assert any("3 niche(s) non mesurée(s)" in e for e in etapes)


def test_R6_fiction_plus_aucune_SERP_apres_un_refus_de_compte(tmp_path):
    """Le VRAI `enrich_asins`, avec un fournisseur espion : ce qui compte est qu'aucun lot ne
    parte, pas le nom du paramètre passé. Fiche `A1` INVENTÉE, servie par le cache."""
    from fiction_master import run_fiction_scout
    from fiction_serp_provider import enrich_asins
    from search_providers import RefusCompte
    from tests.test_fiction_master import _faux_classify, _faux_ideate, _faux_probe
    appels, enrich_kw, etapes = [], [], []

    def serp(niche, **kw):
        appels.append(niche.query)
        if len(appels) == 1:
            return "rh=n:1", ["A1", "A9"]         # A9 INVENTÉ, absent du cache : il PARTIRAIT
        raise RefusCompte("task_post refusé : 40104 Please verify your account")

    cache = Cache(tmp_path / "c.db")
    cache.set_book("A1", 2250, EnrichedBook(asin="A1", title="T", blurb="b"), 3600)
    espion = _CompteRefuse()
    fournisseur = espion.poser(_fournisseur())

    def enrich(asins, **kw):
        enrich_kw.append(kw)
        return enrich_asins(asins, fournisseur, **kw)

    rapports = run_fiction_scout("cosy_mystery", n_niches=4, ideate=_faux_ideate,
                                 serp_fn=serp, enrich_fn=enrich, classify=_faux_classify,
                                 probe=_faux_probe, cache=cache,
                                 cost=CostTracker(plafond_usd=None), progress=etapes.append)
    assert len(appels) == 2
    assert len(rapports) == 1
    assert espion.posts == [], "un lot ASIN est parti malgré le refus de compte"
    assert enrich_kw
    assert any("3 niche(s) non mesurée(s)" in e and "40104" in e for e in etapes)


def test_R6_enrich_asins_cache_seul_n_appelle_pas_le_fournisseur(tmp_path):
    from fiction_serp_provider import enrich_asins
    cache = Cache(tmp_path / "c.db")
    livre = EnrichedBook(asin="A1", title="T")       # fiche INVENTÉE, seule la présence compte
    cache.set_book("A1", 2250, livre, 3600)
    espion, etapes = _CompteRefuse(), []
    cost = CostTracker(plafond_usd=None)
    out = enrich_asins(["A1", "A2"], provider=espion.poser(_fournisseur()), cache=cache,
                       cost=cost, progress=etapes.append, cache_seul=True)
    assert set(out) == {"A1"}
    assert espion.posts == []
    assert cost.breakdown()["dataforseo_calls"] == 0
    assert any("1 ASIN" in e for e in etapes)


# ══ R14 — une PANNE n'est pas une absence de classement ═══════════════════════════

def test_R14_une_panne_du_canal_n_est_pas_memorisee_comme_absence(tmp_path):
    from bsr_source import resolve_bsrs
    cache = Cache(tmp_path / "c.db")

    def leve(asin):
        raise RuntimeError("réseau indisponible")
    out = resolve_bsrs(["A"], fetch_bsr_fn=leve, cache=cache, bsr_pause=0)
    assert out["A"] is None
    assert cache.bsr_absent("A", 2250) is False

    resolve_bsrs(["B"], fetch_bsr_fn=lambda a: None, cache=cache, bsr_pause=0)
    assert cache.bsr_absent("B", 2250) is True       # une absence RENDUE reste mémorisée


def test_R14_scrape_par_defaut_une_fiche_non_lue_n_est_pas_une_absence(tmp_path,
                                                                       monkeypatch):
    from bsr_source import resolve_bsrs
    monkeypatch.setattr("amazon_product._default_fetch_html", lambda asin: None)
    cache = Cache(tmp_path / "c.db")
    out = resolve_bsrs(["2266283340"], source="scrape", cache=cache, bsr_pause=0)
    assert out["2266283340"] is None
    assert cache.bsr_absent("2266283340", 2250) is False


def test_R14_le_contrat_de_fetch_bsr_est_inchange_pour_le_launcher(monkeypatch, capsys):
    import launcher
    from amazon_product import fetch_bsr
    monkeypatch.setattr("amazon_product._default_fetch_html", lambda asin: None)
    assert fetch_bsr("2266283340") is None
    monkeypatch.setattr("builtins.input", lambda *a: "2266283340")
    launcher._do_bsr()
    assert "introuvable" in capsys.readouterr().out


def test_R14_dataforseo_un_batch_refuse_n_ecrit_aucune_absence_et_ne_coute_rien(tmp_path):
    from bsr_source import resolve_bsrs
    dix_huit = [f"B0FAKE{i:04d}" for i in range(18)]     # ASIN INVENTÉS
    cache, cost = Cache(tmp_path / "c.db"), CostTracker(plafond_usd=None)
    prov = _CompteRefuse().poser(_fournisseur())
    resolve_bsrs(dix_huit, source="dataforseo", provider=prov, cache=cache, cost=cost,
                 bsr_pause=0)
    assert not any(cache.bsr_absent(a, 2250) for a in dix_huit)
    assert cost.breakdown()["dataforseo_calls"] == 0


def test_R14_product_info_batch_expose_ce_qui_a_ete_LU(tmp_path):
    """Deux payloads RÉELS : 1923235036 porte un rang Livres, B0FS7JQNJ6 n'en porte aucun
    (vraie absence, lue). Un troisième ASIN INVENTÉ n'est jamais prêt (non lu)."""
    from bsr_source import resolve_bsrs
    lus_ok, sans_rang, jamais = "1923235036", "B0FS7JQNJ6", "B0FAKE9999"
    prov = _fournisseur()
    prov._post = _post_echo

    def get(url):
        asin = url.rsplit("/", 1)[-1][2:]
        if asin == jamais:
            return {"tasks": [{"status_code": 20100}]}      # statut INVENTÉ, non capturé
        return _reponse_tache(_PAYLOADS[asin])
    prov._get = get

    lu = prov.product_info_batch([lus_ok, sans_rang, jamais], poll_interval=0, max_polls=2)
    assert lu.lus == {lus_ok, sans_rang}
    assert lu.taches_creees == 3

    cache = Cache(tmp_path / "c.db")
    out = resolve_bsrs([lus_ok, sans_rang, jamais], source="dataforseo", provider=prov,
                       cache=cache, bsr_pause=0)
    assert out[lus_ok].rank_livres == 1597
    assert cache.bsr_absent(sans_rang, 2250) is True
    assert cache.bsr_absent(jamais, 2250) is False


def test_R14_une_tache_terminee_en_ERREUR_reste_une_panne_faute_de_capture(tmp_path):
    """Forme INVENTÉE : aucune capture d'une tâche ASIN finie en erreur chez DataForSEO
    (code et message ci-dessous inventés ; zéro occurrence d'une telle réponse dans le dépôt).
    Tant qu'elle n'est pas relevée (R5), le choix pessimiste est épinglé : ni lue, ni
    mémorisée comme absence dans le cache mutualisé, et la tâche créée reste imputée — le
    pire cas est de repayer, jamais de figer une fausse absence."""
    from bsr_source import resolve_bsrs
    ok, en_erreur = "1923235036", "B0FAKE4040"
    prov = _fournisseur()
    prov._post = _post_echo

    def get(url):
        asin = url.rsplit("/", 1)[-1][2:]
        if asin == en_erreur:
            return {"tasks": [{"status_code": 40400, "status_message": "INVENTE",
                               "result": None}]}
        return _reponse_tache(_PAYLOADS[asin])
    prov._get = get
    cache, cost = Cache(tmp_path / "c.db"), CostTracker(plafond_usd=None)
    resolve_bsrs([ok, en_erreur], source="dataforseo", provider=prov, cache=cache, cost=cost,
                 bsr_pause=0)
    assert cache.bsr_absent(ok, 2250) is False
    assert cache.bsr_absent(en_erreur, 2250) is False
    assert cost.breakdown()["dataforseo_calls"] == 2

