"""Plafond de COÛT par run — garde-fou distinct du plafond d'ANALYSES.

`PLAFOND_ANALYSES_MENSUEL` compte des runs, pas des dollars : une seule « analyse » sur
un rayon lent peut enchaîner des dizaines d'appels DataForSEO. Les bornes de volume
(`MAX_RECHERCHES`…) bornent ce qui est DEMANDÉ, pas ce qui est DÉPENSÉ — un run borné à
6 niches paie quand même 6 SERP + le batch ASIN + les tokens de l'ideator. Le plafond de
coût est la dernière ligne : il arrête le run entre deux phases payantes.

Invariant de §5.29 : un arrêt au plafond n'interrompt pas le run, il le CLÔTURE — on rend
ce qui a été mesuré, en disant combien de niches n'ont pas été traitées. Jamais un
plantage muet, jamais un rapport qui se lit comme complet.
"""
import pytest

from cost_tracker import CostTracker, PlafondCoutAtteint


def test_le_plafond_se_declenche_sur_le_cout_reel_pas_sur_un_compteur_d_appels():
    """0,003 $ x 10 appels = 0,03 $ : au-dessus d'un plafond à 0,01 $."""
    cost = CostTracker(plafond_usd=0.01)
    assert cost.plafond_atteint is False
    cost.add_dataforseo(10, 2)
    assert cost.plafond_atteint is True
    with pytest.raises(PlafondCoutAtteint):
        cost.verifier()


def test_sans_plafond_verifier_ne_leve_jamais():
    """Le défaut historique (aucun plafond) reste un no-op : les runs CLI et les tests
    existants ne doivent pas changer de comportement."""
    cost = CostTracker(plafond_usd=None)
    cost.add_dataforseo(1000, 2)
    assert cost.plafond_atteint is False
    cost.verifier()


def test_les_tokens_llm_comptent_dans_le_plafond():
    """L'ideator fiction est un poste LLM dominant : un plafond qui n'écouterait que
    DataForSEO laisserait filer le coût réel."""
    cost = CostTracker(plafond_usd=0.02)
    cost.add_llm("claude-sonnet-5", 1_000_000, 1_000_000)   # 2 $ + 10 $
    assert cost.plafond_atteint is True


def test_le_plafond_par_defaut_vient_de_l_environnement(monkeypatch):
    monkeypatch.setenv("PLAFOND_USD_PAR_RUN", "0.005")
    cost = CostTracker()
    cost.add_dataforseo(2, 2)          # 0,006 $
    assert cost.plafond_atteint is True


def test_une_valeur_d_environnement_illisible_ne_casse_pas_le_run(monkeypatch):
    """Même posture que PLAFOND_ANALYSES_MENSUEL : une saisie fautive retombe sur le
    défaut, elle ne fait pas planter tous les runs."""
    monkeypatch.setenv("PLAFOND_USD_PAR_RUN", "beaucoup")
    cost = CostTracker()
    assert cost.plafond_usd == 0.60


def test_le_message_dit_le_montant_et_le_plafond():
    """« Erreur » ne dit rien ; « 0,03 $ sur un plafond de 0,01 $ » dit quoi régler."""
    cost = CostTracker(plafond_usd=0.01)
    cost.add_dataforseo(10, 2)
    with pytest.raises(PlafondCoutAtteint) as e:
        cost.verifier()
    assert "0.01" in str(e.value) and "0.03" in str(e.value)


# ---------------------------------------------------------------------------
# Arrêt propre côté orchestrateur : le run se CLÔTURE, il ne plante pas.
# ---------------------------------------------------------------------------
from models import NicheCandidate, NicheValidation, SearchResult, SearchItem, BsrInfo
from scout_master import run_scout


def _ideate_4(seed, signals, n, model, on_usage=None):
    return [NicheCandidate(niche=f"n{i}", requete_amazon=f"q{i}", rationale="r",
                           categorie="c") for i in range(4)]


def _validate_4(cands, **kw):
    return [NicheValidation(niche=f"n{i}", requete_amazon=f"q{i}", categorie="c",
                            demand_score=5, validated=True) for i in range(4)]


class _ProviderCompteur:
    """Chaque SERP coûte 0,003 $ : au plafond de 0,007 $, la 3e doit être refusée."""
    priority = 2
    location_code = 2250
    language_code = "fr_FR"

    def __init__(self):
        self.appels = 0

    def search(self, q, books_only=True):
        self.appels += 1
        return SearchResult(keyword=q, sponsored=[], organic=[
            SearchItem(title=f"Livre {q}", asin=f"A{self.appels}", rating=4.0,
                       reviews_count=10)])


def _bsr(asin):
    return BsrInfo(rank_livres=5000, asin=asin)


def test_le_scout_s_arrete_au_plafond_et_rend_les_niches_deja_mesurees():
    prov = _ProviderCompteur()
    etapes = []
    res = run_scout(seed="x", n_search=4, bsr_pause=0, use_cache=False,
                    cost=CostTracker(plafond_usd=0.007), progress=etapes.append,
                    ideate=_ideate_4, validate=_validate_4, provider=prov,
                    fetch_bsr_fn=_bsr)
    # 2 SERP payées (0,006 $), la 3e refusée avant l'appel : on ne dépasse jamais.
    assert prov.appels == 2
    assert len(res) == 2
    assert all(s.concurrence_mesuree for s in res)


def test_l_arret_au_plafond_est_annonce_et_chiffre():
    """Un rapport partiel muet se lit comme un rapport complet : c'est exactement la
    faute de §5.29 / règle 3 (une absence de mesure présentée comme un verdict)."""
    etapes = []
    run_scout(seed="x", n_search=4, bsr_pause=0, use_cache=False,
              cost=CostTracker(plafond_usd=0.007), progress=etapes.append,
              ideate=_ideate_4, validate=_validate_4, provider=_ProviderCompteur(),
              fetch_bsr_fn=_bsr)
    msg = " ".join(etapes)
    assert "plafond" in msg.lower()
    assert "2" in msg and "partiel" in msg.lower()


def test_sans_plafond_atteint_le_run_reste_complet():
    """Non-régression : le plafond ne doit rien changer à un run nominal."""
    prov = _ProviderCompteur()
    res = run_scout(seed="x", n_search=4, bsr_pause=0, use_cache=False,
                    cost=CostTracker(plafond_usd=10.0), ideate=_ideate_4,
                    validate=_validate_4, provider=prov, fetch_bsr_fn=_bsr)
    assert prov.appels == 4 and len(res) == 4


def test_le_plafond_est_predictif_quand_le_tarif_est_connu():
    """Une SERP vaut 0,003 $ : rien n'oblige à la payer pour découvrir qu'elle faisait
    franchir la ligne. Sans `cout_prevu`, le plafond se dépasse toujours d'une phase."""
    cost = CostTracker(plafond_usd=0.007)
    cost.add_dataforseo(2, 2)                  # 0,006 $ — sous le plafond
    cost.verifier()                            # constat seul : ça passe
    with pytest.raises(PlafondCoutAtteint):
        cost.verifier(0.003)                   # 0,009 $ franchirait : refusé AVANT de payer


# ---------------------------------------------------------------------------
# Fiction : même garde. La phase B (une SERP par niche) est le seul poste par-niche ;
# la file ASIN, elle, se paie UNE fois par run (§5.16) et ne se fractionne pas.
# ---------------------------------------------------------------------------
from fiction_master import run_fiction_scout
from models import AutocompleteSignal, EnrichedBook, FictionNiche


def _trios(sous_genre_cle, n=8, rayon="kindle", model=None, on_usage=None,
           version="fr_v1", **_kw):
    return [FictionNiche(sous_genre=sous_genre_cle, tropes=["t"], decor="d", rayon=rayon,
                         query=f"trio {i}") for i in range(n)]


class _SerpCompteur:
    """Signature de fiction_serp_provider.fetch_shelf_asins : rend (search_param, asins)."""

    def __init__(self):
        self.appels = 0

    def __call__(self, niche, cost=None, **kw):
        self.appels += 1
        if cost is not None:
            cost.add_dataforseo(1, 2)
        return "rh=n:1", [f"A{self.appels}"]


def _enrich(asins, **kw):
    return {a: EnrichedBook(asin=a, title=f"T{a}") for a in asins}


def _probe(niche, **kw):
    return AutocompleteSignal(niche_query=niche.query, mesure=True, score=0.0)


def test_le_scout_fiction_s_arrete_au_plafond_et_annonce_le_rapport_partiel():
    serp = _SerpCompteur()
    etapes = []
    run_fiction_scout("cosy_mystery", n_niches=4, cost=CostTracker(plafond_usd=0.007),
                      progress=etapes.append, use_cache=False, ideate=_trios,
                      serp_fn=serp, enrich_fn=_enrich, classify=lambda *a, **k: [],
                      probe=_probe)
    assert serp.appels == 2
    msg = " ".join(etapes).lower()
    assert "plafond" in msg and "partiel" in msg
