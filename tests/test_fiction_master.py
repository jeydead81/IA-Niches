"""test_fiction_master.py — M6-2 : run_fiction_scout, l'orchestrateur en 5 phases.
Tout est injecté (ideate/serp_fn/enrich_fn/classify/probe) : aucun réseau, aucun appel LLM.
LE point du module : la file ASIN (~250 s quel que soit le nb d'ASIN) est payée UNE SEULE
fois par run, jamais une fois par niche."""
from cost_tracker import CostTracker
from fiction_master import run_fiction_scout
from models import AutocompleteSignal, EnrichedBook, FictionNiche, TropeClassification


def _faux_ideate(sous_genre_cle, n=8, rayon="kindle", model=None, client=None,
                 on_usage=None, version="fr_v1", **_kw):
    """Signature calquée sur fiction_ideator.generate_trios : n trios distincts, une
    query numérotée pour que les fakes serp/classify puissent s'y raccrocher par index."""
    if on_usage:
        on_usage(100, 50, model or "claude-sonnet-5")
    return [FictionNiche(sous_genre=sous_genre_cle, tropes=["t"], decor="d", rayon=rayon,
                         query=f"{sous_genre_cle} requete {i}") for i in range(n)]


def _faux_serp(niche, **kw):
    """Signature calquée sur fiction_serp_provider.fetch_shelf_asins (sans provider,
    puisque déjà lié) : rend (search_param, [asins]), dont un ASIN "PARTAGE" commun à
    toutes les niches pour exercer la dédup inter-niches."""
    idx = niche.query.rsplit(" ", 1)[-1]
    return "rh=n:1", [f"A{idx}", "PARTAGE"]


def _faux_enrich(asins, **kw):
    """Signature calquée sur fiction_serp_provider.enrich_asins (sans provider)."""
    return {a: EnrichedBook(asin=a, title="T", blurb="b") for a in asins}


def _faux_classify(books, sous_genre_cle, **kw):
    """Signature calquée sur fiction_classifier.classify_books."""
    return [TropeClassification(asin=b.asin, taxonomy_version="fr_v1", tropes=[],
                                est_roman=True) for b in books]


def _faux_probe(niche, **kw):
    """Signature calquée sur fiction_autocomplete.probe_niche."""
    return AutocompleteSignal(niche_query=niche.query, mesure=True, score=0.0)


def test_un_seul_batch_asin_pour_toutes_les_niches():
    """LE point du module : la file ASIN (~250 s) est payée UNE fois, pas N fois."""
    appels = {"serp": 0, "enrich": 0}

    def faux_serp(niche, **kw):
        appels["serp"] += 1
        return "rh=n:1", [f"A{appels['serp']}", "PARTAGE"]

    def faux_enrich(asins, **kw):
        appels["enrich"] += 1
        return {a: EnrichedBook(asin=a, title="T", blurb="b", bsr=3000,
                                bsr_rayon="Boutique Kindle") for a in asins}

    rapports = run_fiction_scout("cosy_mystery", n_niches=3, ideate=_faux_ideate,
                                 serp_fn=faux_serp, enrich_fn=faux_enrich,
                                 classify=_faux_classify, probe=_faux_probe)
    assert appels["serp"] == 3
    assert appels["enrich"] == 1               # <- UN SEUL batch, quel que soit N
    assert len(rapports) == 3


def test_asins_dedupliques_entre_niches():
    """Deux trios du même sous-genre partagent des livres : les payer deux fois est du
    gaspillage."""
    vus = {}

    def faux_enrich(asins, **kw):
        vus["asins"] = list(asins)
        return {a: EnrichedBook(asin=a, title="T", blurb="b") for a in asins}

    run_fiction_scout("cosy_mystery", n_niches=3, ideate=_faux_ideate, serp_fn=_faux_serp,
                      enrich_fn=faux_enrich, classify=_faux_classify, probe=_faux_probe)
    assert len(vus["asins"]) == len(set(vus["asins"]))     # aucun doublon payé
    assert len(vus["asins"]) == 4                          # A0, A1, A2, PARTAGE (pas 6)


def test_rapports_tries_par_interet():
    """Tri par intérêt : profondeur décroissante, puis saturation croissante à profondeur
    égale (§ scoring). Construit 3 niches à profondeur/saturation contrôlées pour vérifier
    l'ordre exact, pas seulement l'invariant de tri."""
    def ideate3(sous_genre_cle, n=8, **kw):
        return [FictionNiche(sous_genre=sous_genre_cle, tropes=[f"t{i}"], decor="d",
                             query=f"requete {i}") for i in range(3)]

    def serp3(niche, **kw):
        # TROIS livres par niche : sous `livres_mesures_min`, une niche sort « mesure_mince » et
        # ne se classe plus par profondeur. Avec un livre chacune, ce test passait pour une
        # AUTRE raison que celle qu'il annonce (revue adverse du 2026-10-05).
        i = niche.query.rsplit(" ", 1)[-1]
        return "rh=n:1", [f"A{i}{x}" for x in "abc"]

    bsr_par_niche = {"0": 3000, "1": 50000, "2": 3000}   # niche 1 nettement moins profonde

    def enrich3(asins, **kw):
        return {a: EnrichedBook(asin=a, title="T", blurb="b", bsr=bsr_par_niche[a[1]],
                                bsr_rayon="Boutique Kindle") for a in asins}

    def classify3(books, sous_genre_cle, **kw):
        # seule la niche 2 est déjà couverte par son propre trope -> saturation haute
        return [TropeClassification(asin=b.asin, taxonomy_version="fr_v1",
                                    tropes=[f"t{b.asin[1]}"] if b.asin[1] == "2" else [],
                                    est_roman=True) for b in books]

    rapports = run_fiction_scout("cosy_mystery", n_niches=3, ideate=ideate3, serp_fn=serp3,
                                 enrich_fn=enrich3, classify=classify3, probe=_faux_probe)
    scores = [(r.depth_score, -r.saturation_trio) for r in rapports]
    assert scores == sorted(scores, reverse=True)
    # niche 0 (depth haute, non saturée) avant niche 2 (depth haute, saturée) avant
    # niche 1 (depth basse) : la profondeur prime, la saturation ne départage qu'à égalité.
    assert [r.niche.tropes[0] for r in rapports] == ["t0", "t2", "t1"]
    assert all(r.demand_matrix not in ("mesure_mince", "non_mesurable") for r in rapports),         "fixture : les trois niches doivent être MESURÉES, sinon le tri ne prouve rien"


def test_une_niche_en_echec_ne_coule_pas_le_run():
    """Un rayon qui lève ne doit pas faire perdre les rayons DÉJÀ PAYÉS (§10.11)."""
    def ideate_boum(sous_genre_cle, n=8, **kw):
        return [FictionNiche(sous_genre=sous_genre_cle, tropes=["t"], query=q) for q in
               ["cosy chat ile", "cosy chien boum village", "cosy corbeau phare"]]

    def serp_capricieux(niche, **kw):
        if "boum" in niche.query:
            raise RuntimeError("SERP HS")
        return "rh=n:1", ["A1"]

    msgs = []
    rapports = run_fiction_scout("cosy_mystery", n_niches=3, ideate=ideate_boum,
                                 serp_fn=serp_capricieux, enrich_fn=_faux_enrich,
                                 classify=_faux_classify, probe=_faux_probe,
                                 progress=msgs.append)
    assert len(rapports) == 2                              # les 2 autres sont conservés
    assert any("échec" in m.lower() for m in msgs)


def test_progress_et_cout_remontent():
    cost = CostTracker()
    msgs = []
    run_fiction_scout("cosy_mystery", n_niches=2, ideate=_faux_ideate, serp_fn=_faux_serp,
                      enrich_fn=_faux_enrich, classify=_faux_classify, probe=_faux_probe,
                      cost=cost, progress=msgs.append)
    assert msgs and cost is not None


def test_les_classifications_deja_connues_ne_sont_pas_repayees(tmp_path):
    """Une classification est déterministe : la re-payer à chaque run est du gaspillage.
    Sur un sous-genre exploré plusieurs fois — le cas normal — les rayons se recouvrent
    largement, et en SaaS tous les clients d'un même sous-genre repayaient les mêmes
    livres."""
    from cache import Cache
    from models import TropeClassification

    cache = Cache(tmp_path / "c.db")
    cache.set_classification("PARTAGE", "fr_v1", "claude-sonnet-5",
                             TropeClassification(asin="PARTAGE", taxonomy_version="fr_v1",
                                                 tropes=["mafia"]),
                             ttl_s=1000)
    envoyes = {}

    def faux_classify(livres, sg, **kw):
        envoyes["asins"] = [b.asin for b in livres]
        return [TropeClassification(asin=b.asin, taxonomy_version="fr_v1") for b in livres]

    def faux_enrich(asins, **kw):
        return {a: EnrichedBook(asin=a, title="T", blurb="b", bsr=3000,
                                bsr_rayon="Boutique Kindle") for a in asins}

    def faux_serp(niche, **kw):
        return "rh=n:1", ["PARTAGE", "NEUF"]

    rapports = run_fiction_scout("dark_romance", n_niches=1, ideate=_faux_ideate,
                                 serp_fn=faux_serp, enrich_fn=faux_enrich,
                                 classify=faux_classify, probe=_faux_probe, cache=cache)
    assert envoyes["asins"] == ["NEUF"]          # PARTAGE servi par le cache, pas repayé
    assert rapports                               # et le rapport dispose des DEUX étiquettes
