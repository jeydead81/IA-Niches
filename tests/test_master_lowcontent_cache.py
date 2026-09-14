"""Le master low-content face à un cache CHAUD : ce qu'il prévoit de payer, ce qu'il annonce.

Deux défauts, tous deux invisibles tant que les tests tournaient sur un cache vide :

- **R4.** Le garde prédictif du batch ASIN comptait TOUTE l'union, fiches déjà en cache
  comprises. Un plafond calé au plus juste refusait donc un batch qui ne coûtait rien — puis
  le canal BSR repartait scraper chaque ASIN « non enrichi ». Seules les fiches ABSENTES du
  cache partent chez le fournisseur ; ce sont elles, et elles seules, que le plafond doit
  voir. `enrich_fn` reste appelé : c'est lui qui SERT le cache.
- **R29.** Rien à l'écran ne disait qu'une SERP ou une fiche venait du cache. Après le run 4,
  « 185/185 fiches servies par le cache » était exactement l'alerte qui manquait : ces
  fiches avaient été lues par l'ancien parseur. Jamais « à payer » : la ligne apparaît à
  l'écran du client (§5.27).

Données : les 8 captures RÉELLES de `fixtures/fiction/v2_asin_payloads.json` (amazon.fr,
2026-07-20), le classeur RÉEL `99-logs/validation-lc.xlsx` (lecture seule) et l'état RÉEL
du cache après le run 4, extrait en lecture seule dans `fixtures/cache_calibration_run4_reel.json`. Sont INVENTÉS, et dits là où ils servent : la SERP qui aligne les ASIN v2 sous une
requête (sa forme est celle de `SearchResult`, pas une capture), les fournisseurs factices.
"""
import json
import sqlite3
from pathlib import Path

import pytest

from autocomplete_expand import Suggestion
from cache import BOOK_TTL_S, Cache
from cost_tracker import CostTracker
from fiction_books import parse_enriched_book
from models import LowContentNiche, SearchItem, SearchResult

_RACINE = Path(__file__).resolve().parent.parent
_PAYLOADS = json.loads((_RACINE / "tests" / "fixtures" / "fiction" / "v2_asin_payloads.json")
                       .read_text(encoding="utf-8"))
# Les six captures qui portent un éditeur ET un rang du rayon Livres.
_ASIN_LIVRES = ["1923235036", "2749187052", "B0CH23Z17T", "2253253103", "2036073689",
                "B0GN4G414V"]
_REQUETE = "carnet de suivi migraine"


def _niche(requete, **kw):
    base = dict(niche=requete, requete_amazon=requete, rationale="r", categorie="c",
                format_cle="journal_suivi", theme="t", public="adulte",
                n_enfants_autocomplete=4)
    base.update(kw)
    return LowContentNiche(**base)


class _ProvInterdit:
    """Tout appel payant LÈVE : si le test passe, rien n'est parti chez le fournisseur."""
    location_code, language_code, priority = 2250, "fr_FR", 2

    def __init__(self):
        self.appels = []

    def search(self, q, books_only=True, **kw):
        self.appels.append(("search", q))
        raise AssertionError("SERP demandée alors qu'elle est en cache")

    def product_raw_batch(self, asins, **kw):
        self.appels.append(("batch", list(asins)))
        raise AssertionError("fiches demandées alors qu'elles sont en cache")


def _cache_garni(tmp_path, en_cache, serp_asins):
    """SERP INVENTÉE (forme `SearchResult`) alignant `serp_asins`, fiches RÉELLES parsées."""
    cache = Cache(tmp_path / "df-cache.db")
    cache.set_search(_REQUETE, 2250, "fr_FR", SearchResult(
        keyword=_REQUETE, organic=[SearchItem(asin=a, title=f"carnet {a}")
                                   for a in serp_asins]), 3600)
    for a in en_cache:
        cache.set_book(a, 2250, parse_enriched_book(_PAYLOADS[a]), BOOK_TTL_S)
    return cache


def _run(tmp_path, plafond, **kw):
    from lowcontent_master import run_lowcontent_scout
    etapes, bsr_appels = [], []
    prov = kw.pop("provider", None) or _ProvInterdit()
    out = run_lowcontent_scout(
        seed="carnet", cache_path=str(tmp_path / "df-cache.db"), provider=prov,
        cost=CostTracker(plafond_usd=plafond), bsr_pause=0,
        expand_fn=lambda *a, **k: [Suggestion(requete=_REQUETE, parent="", profondeur=0,
                                              n_enfants=4)],
        ideate=lambda **k: [_niche(_REQUETE)],
        fetch_bsr_fn=lambda asin: bsr_appels.append(asin) or None,
        progress=etapes.append, **kw)
    return out, etapes, bsr_appels, prov


# ══ R4 — le plafond ne voit que ce qui partira chez le fournisseur ════════════════

def test_R4_un_batch_entierement_en_cache_n_est_pas_refuse_par_le_plafond(tmp_path):
    """Plafond 0,010 $ : six fiches à payer vaudraient 0,018 $, six fiches en cache 0 $."""
    _cache_garni(tmp_path, en_cache=_ASIN_LIVRES, serp_asins=_ASIN_LIVRES)
    out, etapes, bsr_appels, prov = _run(tmp_path, plafond=0.010)
    assert not any("plafond de coût atteint" in e for e in etapes), etapes
    assert prov.appels == []
    assert bsr_appels == [], "le canal BSR a re-sondé des fiches servies par le cache"
    assert len(out) == 1 and out[0].part_indie is not None
    assert out[0].pages_median is not None


def test_R4_seules_les_fiches_ABSENTES_du_cache_entrent_dans_le_devis(tmp_path):
    """3 en cache + 3 à relire : 0,009 $ prévus sous un plafond de 0,010 $ — le batch part.
    Le garde d'avant comptait 6 × 0,003 = 0,018 $ et le refusait."""
    en_cache, absents = _ASIN_LIVRES[:3], _ASIN_LIVRES[3:]
    _cache_garni(tmp_path, en_cache=en_cache, serp_asins=_ASIN_LIVRES)

    class _Prov(_ProvInterdit):
        def product_raw_batch(self, asins, **kw):
            self.appels.append(("batch", list(asins)))
            return {a: _PAYLOADS[a] for a in asins}

    out, etapes, bsr_appels, prov = _run(tmp_path, plafond=0.010, provider=_Prov())
    assert not any("plafond de coût atteint" in e for e in etapes), etapes
    assert prov.appels == [("batch", absents)]
    assert bsr_appels == []


def test_R4_un_plafond_qui_refuse_les_absentes_laisse_le_cache_SERVIR_les_autres(tmp_path):
    """Plafond 0,005 $ : les 3 fiches à relire (0,009 $) sont refusées, mais les 3 fiches en
    cache ne coûtent rien et restent une mesure. Les jeter perdait éditeurs et pagination
    déjà lus, pour zéro centime d'économie.

    Les trois fiches en cache sont celles dont l'éditeur est RECONNU (Le Livre de Poche,
    Larousse, Cherche Midi) : sur des éditeurs inconnus, `part_indie` vaut None par
    construction, et le test ne prouverait rien."""
    en_cache = ["2253253103", "2036073689", "2749187052"]
    _cache_garni(tmp_path, en_cache=en_cache, serp_asins=_ASIN_LIVRES)
    out, etapes, bsr_appels, prov = _run(tmp_path, plafond=0.005)
    assert any("plafond de coût atteint" in e for e in etapes)
    assert not any(a == "batch" for a, _ in prov.appels)
    assert any("3/3 fiche(s) servie(s) par le cache" in e for e in etapes), etapes
    assert out[0].part_indie is not None and out[0].pages_median is not None
    assert sorted(bsr_appels) == sorted(a for a in _ASIN_LIVRES if a not in en_cache)


# ══ R29 — dire ce que le cache a servi ════════════════════════════════════════════

def test_R29_enrich_asins_annonce_les_fiches_servies_par_le_cache(tmp_path):
    from fiction_serp_provider import enrich_asins
    cache = Cache(tmp_path / "c.db")
    for a in _ASIN_LIVRES[:2]:
        cache.set_book(a, 2250, parse_enriched_book(_PAYLOADS[a]), BOOK_TTL_S)

    class _Prov:
        location_code, priority = 2250, 2

        def product_raw_batch(self, asins):
            return {a: _PAYLOADS[a] for a in asins}

    etapes = []
    out = enrich_asins(_ASIN_LIVRES[:3], _Prov(), cache=cache, cost=CostTracker(),
                       progress=etapes.append)
    assert len(out) == 3
    assert any("2/3 fiche(s) servie(s) par le cache, 1 à relire" in e for e in etapes), etapes
    assert not any("payer" in e for e in etapes)


def test_R29_tout_en_cache_le_fournisseur_n_est_pas_appele_et_c_est_DIT(tmp_path):
    from fiction_serp_provider import enrich_asins
    cache = Cache(tmp_path / "c.db")
    for a in _ASIN_LIVRES[:3]:
        cache.set_book(a, 2250, parse_enriched_book(_PAYLOADS[a]), BOOK_TTL_S)
    etapes = []
    out = enrich_asins(_ASIN_LIVRES[:3], _ProvInterdit(), cache=cache, cost=CostTracker(),
                       progress=etapes.append)
    assert len(out) == 3
    assert any("3/3 fiche(s) servie(s) par le cache, 0 à relire" in e for e in etapes), etapes


def test_R29_le_master_annonce_les_SERP_reelles_servies_par_le_cache(tmp_path, monkeypatch):
    """Deux des 31 requêtes RÉELLES du classeur, dont la SERP a été payée au run 4 et dort
    dans le cache (état RÉEL extrait en fixture, jamais le vrai fichier). Fournisseur qui lève :
    rien ne doit partir, et l'écran doit le dire. L'horloge du cache est figée sous
    l'expiration de ces SERP, pour que le test ne dépende pas de la date du jour."""
    import lowcontent_master
    from tests.outils_calibration import cache_run4_reel, etiquetees_reelles
    copie = cache_run4_reel(tmp_path, "df-cache.db")
    requetes = [e.requete for e in etiquetees_reelles()]

    cx = sqlite3.connect(copie)
    lecture = Cache(copie, now=lambda: 0)
    expirations = {}
    for q in requetes:
        row = cx.execute("SELECT expires FROM kv WHERE key=?",
                         (lecture._search_key(q, 2250, "fr_FR"),)).fetchone()
        if row:
            expirations[q] = row[0]
    cx.close()
    choisies = sorted(expirations)[:2]
    assert len(choisies) == 2, "le cache réel ne porte plus deux SERP du jeu de calibration"
    fige = min(expirations[q] for q in choisies) - 60
    monkeypatch.setattr(lowcontent_master, "Cache", lambda p: Cache(p, now=lambda: fige))

    etapes = []
    prov = _ProvInterdit()
    prov.product_raw_batch = lambda asins, **kw: (_ for _ in ()).throw(
        RuntimeError("hors ligne"))
    lowcontent_master.run_lowcontent_scout(
        seed="carnet", cache_path=str(copie), provider=prov, cost=CostTracker(),
        bsr_pause=0, n_search=2,
        expand_fn=lambda *a, **k: [Suggestion(requete=q, parent="", profondeur=0, n_enfants=3)
                                   for q in choisies],
        ideate=lambda **k: [_niche(q) for q in choisies],
        fetch_bsr_fn=lambda asin: None, progress=etapes.append)
    assert not any(a == "search" for a, _ in prov.appels)
    assert any("2/2 recherche(s) Amazon servie(s) par le cache" in e for e in etapes), etapes
    assert not any("payer" in e for e in etapes)
