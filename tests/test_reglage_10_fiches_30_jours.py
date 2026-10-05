"""10 fiches livres par niche (au lieu de 12) et cache à 30 jours (au lieu de 15).

Décision de Baptiste (2026-10-05), après un run fiction de 5 niches à 0,171 $ côté DataForSEO :
52 fiches à 0,003 $ = 0,156 $, soit 81 % du poste. Dix fiches par niche au lieu de douze retirent
un sixième de ce poste ; un cache de 30 jours rend gratuit, deux fois plus longtemps, tout rayon
déjà lu (le cache est MUTUALISÉ entre les comptes).

Ce que ce fichier tient : les TROIS endroits qui portent le « 10 » (orchestrateur, fournisseur,
devis) ne divergent pas — le devis qui croirait encore à 12 refuserait des runs qui tiennent, ou
laisserait passer ceux qui ne tiennent pas (§5.32) — et le TTL ÉCRIT est bien celui annoncé.

Ce que ça coûte en échange : un BSR ou un prix lus dans une fiche peuvent avoir jusqu'à un mois.
Le produit compare des ordres de grandeur, pas un classement à la journée.
"""
import inspect
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "web"))

from cost_tracker import PLAFOND_USD_PAR_RUN_DEFAUT
from devis import _MODELES, ventilation_max_estimee, volume_maximal
from fiction_master import run_fiction_scout
from fiction_serp_provider import fetch_fiction_shelf, fetch_shelf_asins
from models import AutocompleteSignal, FictionNiche, SearchItem, SearchResult

N_TOP = 10
JOURS = 24 * 3600


def _defaut(fn, nom="n_top"):
    return inspect.signature(fn).parameters[nom].default


# ── 10 fiches ───────────────────────────────────────────────────────────────────

def test_les_trois_defauts_de_n_top_valent_dix():
    assert _defaut(run_fiction_scout) == N_TOP
    assert _defaut(fetch_shelf_asins) == N_TOP
    assert _defaut(fetch_fiction_shelf) == N_TOP


def test_le_devis_suit_les_orchestrateurs():
    """`devis` DOIT suivre `n_top` : une fiche par livre du rayon, une classification par livre."""
    m = _MODELES["fiction"]
    assert m["asin_par_unite"] == _defaut(run_fiction_scout) == N_TOP
    assert m["classif_par_unite"] == N_TOP


def test_le_devis_compte_cinquante_fiches_pour_cinq_niches():
    v = ventilation_max_estimee("fiction", {"n_niches": 5})
    assert v["n_asin"] == 50 and v["_classif"] == 50


def test_la_borne_de_niches_du_serveur_tient_toujours_sous_le_plafond():
    import server
    assert volume_maximal("fiction", PLAFOND_USD_PAR_RUN_DEFAUT) >= server.MAX_NICHES_FICTION


class _Prov:
    priority = 2

    def search(self, keyword, depth=100, books_only=True, search_param=None):
        return SearchResult(keyword=keyword, sponsored=[], organic=[
            SearchItem(title=f"T{i}", asin=f"A{i:02d}") for i in range(30)])


def test_le_fournisseur_garde_dix_asin_par_defaut():
    niche = FictionNiche(sous_genre="feel_good", rayon="kindle", query="roman feel good village")
    _, asins = fetch_shelf_asins(niche, _Prov())
    assert asins == [f"A{i:02d}" for i in range(N_TOP)]


def test_l_orchestrateur_demande_dix_asin_par_niche():
    vus = []

    def ideate(sg, n=8, **kw):
        return [FictionNiche(sous_genre=sg, tropes=["t"], decor="d", query="roman feel good x")]

    def serp(niche, **kw):
        vus.append(kw.get("n_top"))
        return "i=digital-text", []

    run_fiction_scout("feel_good", n_niches=1, ideate=ideate, serp_fn=serp,
                      enrich_fn=lambda a, **k: {}, classify=lambda *a, **k: [],
                      probe=lambda n, **k: AutocompleteSignal(niche_query="q"),
                      progress=lambda m: None, use_cache=False)
    assert vus == [N_TOP]


# ── 30 jours ────────────────────────────────────────────────────────────────────

def test_les_durees_de_cache_courantes_sont_de_trente_jours():
    import autocomplete_expand
    import bsr_source
    import cache
    import lowcontent_master
    import scout_master
    for nom, valeur in (("cache.BOOK_TTL_S", cache.BOOK_TTL_S),
                        ("cache.AUTOCOMPLETE_TTL_S", cache.AUTOCOMPLETE_TTL_S),
                        ("bsr_source.BSR_TTL_S", bsr_source.BSR_TTL_S),
                        ("autocomplete_expand.AUTOCOMPLETE_TTL_S",
                         autocomplete_expand.AUTOCOMPLETE_TTL_S),
                        ("scout_master._SEARCH_TTL_S", scout_master._SEARCH_TTL_S),
                        ("lowcontent_master._SEARCH_TTL_S", lowcontent_master._SEARCH_TTL_S)):
        assert valeur == 30 * JOURS, nom


def test_une_absence_de_classement_reste_a_trois_jours():
    """Volontairement NON allongée : un livre peut entrer au classement à tout moment."""
    import bsr_source
    assert bsr_source.ECHEC_BSR_TTL_S == 3 * JOURS


def test_le_devis_a_dix_fiches_est_celui_a_douze_moins_deux_fiches_et_deux_classifications_par_niche(
        monkeypatch):
    """Le seul écart entre les deux réglages, et il se calcule : 2 × (0,003 $ de fiche + 0,001 $ de
    classification) par niche."""
    from devis import _MODELES, cout_max_estime
    a_dix = cout_max_estime("fiction", {"n_niches": 5})
    monkeypatch.setitem(_MODELES["fiction"], "asin_par_unite", 12)
    monkeypatch.setitem(_MODELES["fiction"], "classif_par_unite", 12)
    a_douze = cout_max_estime("fiction", {"n_niches": 5})
    assert a_douze - a_dix == __import__("pytest").approx(5 * 2 * (0.003 + 0.001), abs=1e-3)
