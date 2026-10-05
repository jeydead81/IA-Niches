"""Des trios qui partagent une requête partagent la recherche payée.

Revue adverse du 2026-10-05 : une requête courte (« roman feel good village ») décrit un RAYON, pas
un trio. Six décors pour onze trios : plusieurs trios tombent légitimement sur le même rayon, et
chaque trio garde sa carte (sa saturation dépend de SES tropes). Payer la même recherche deux fois
n'ajoute rien — et deux cartes au même rayon n'ont pas à se mentir sur ce qu'elles partagent.

Ce fichier tient : une recherche payée par requête DISTINCTE ; chaque trio garde sa carte ; un
échec de recherche vaut pour tous les trios qui la partagent ; rien de caché à l'écran.
"""
from fiction_master import run_fiction_scout
from models import AutocompleteSignal, EnrichedBook, FictionNiche, TropeClassification


def _ideate(requetes):
    def f(sous_genre_cle, n=8, **kw):
        return [FictionNiche(sous_genre=sous_genre_cle, tropes=[f"t{i}"], decor="d",
                             rayon="kindle", query=q) for i, q in enumerate(requetes)]
    return f


def _enrich(asins, **kw):
    return {a: EnrichedBook(asin=a, title=a, blurb="b", bsr=3000 + len(a),
                            bsr_rayon="Boutique Kindle") for a in asins}


def _classify(books, sg, **kw):
    return [TropeClassification(asin=b.asin, taxonomy_version="fr_v1", est_roman=True)
            for b in books]


def _probe(niche, **kw):
    return AutocompleteSignal(niche_query=niche.query, mesure=True, score=0.0)


def _lancer(requetes, serp):
    msgs = []
    rapports = run_fiction_scout("feel_good", n_niches=len(requetes), ideate=_ideate(requetes),
                                 serp_fn=serp, enrich_fn=_enrich, classify=_classify,
                                 probe=_probe, progress=msgs.append, use_cache=False)
    return rapports, msgs


def test_une_requete_partagee_n_est_payee_qu_une_fois():
    appels = []

    def serp(niche, **kw):
        appels.append(niche.query)
        return "i=digital-text", ["A1", "A2", "A3"]

    rapports, _ = _lancer(["roman feel good village"] * 3 + ["roman feel good montagne"], serp)
    assert appels == ["roman feel good village", "roman feel good montagne"]
    assert len(rapports) == 4, "chaque trio garde sa carte"


def test_la_comparaison_ignore_casse_et_accents():
    appels = []

    def serp(niche, **kw):
        appels.append(niche.query)
        return "i=digital-text", ["A1", "A2", "A3"]

    _lancer(["Roman Feel Good Île", "roman feel good ile"], serp)
    assert len(appels) == 1


def test_les_trios_au_meme_rayon_ont_les_memes_livres_et_chacun_ses_tropes():
    def serp(niche, **kw):
        return "i=digital-text", ["A1", "A2", "A3"]

    rapports, _ = _lancer(["roman feel good village"] * 2, serp)
    assert {r.niche.tropes[0] for r in rapports} == {"t0", "t1"}
    assert [b.asin for b in rapports[0].books] == [b.asin for b in rapports[1].books]


def test_la_progression_dit_que_le_rayon_est_reutilise_sans_jargon():
    from progression_publique import message_public

    def serp(niche, **kw):
        return "i=digital-text", ["A1", "A2", "A3"]

    _, msgs = _lancer(["roman feel good village"] * 2, serp)
    reut = [m for m in msgs if "déjà lu" in m]
    assert len(reut) == 1 and reut[0].startswith("[2/2]")
    assert message_public(reut[0]) == reut[0]


def test_un_echec_de_recherche_vaut_pour_tous_les_trios_qui_la_partagent():
    appels = []

    def serp(niche, **kw):
        appels.append(niche.query)
        if "village" in niche.query:
            raise TimeoutError("résultat non prêt")
        return "i=digital-text", ["A1", "A2", "A3"]

    rapports, msgs = _lancer(["roman feel good village"] * 2 + ["roman feel good montagne"], serp)
    assert appels == ["roman feel good village", "roman feel good montagne"], \
        "on ne repaie pas une recherche qui vient d'échouer pour la même requête"
    assert len(rapports) == 1
    assert any("2 niche(s) en échec sur 3" in m for m in msgs)


def test_un_rayon_vide_partage_est_dit_pour_chaque_trio():
    def serp(niche, **kw):
        return "i=digital-text", []

    rapports, msgs = _lancer(["roman feel good village"] * 2, serp)
    assert len(rapports) == 2 and all(r.demand_matrix == "non_mesurable" for r in rapports)
    assert len([m for m in msgs if "aucun livre pour cette requête" in m]) == 2


def test_le_plafond_n_est_verifie_que_devant_une_recherche_reellement_payee():
    class _Cost:
        def __init__(self):
            self.verifs = 0

        def verifier(self, *a, **k):
            self.verifs += 1

        def add_llm(self, *a, **k):
            pass

        def breakdown(self):
            return {"dataforseo_calls": 0, "usd": 0, "dataforseo_usd": 0, "llm_usd": 0}

        def total_usd(self):
            return 0.0

    cost = _Cost()

    def serp(niche, **kw):
        return "i=digital-text", ["A1", "A2", "A3"]

    run_fiction_scout("feel_good", n_niches=3, ideate=_ideate(["roman feel good village"] * 3),
                      serp_fn=serp, enrich_fn=_enrich, classify=_classify, probe=_probe,
                      progress=lambda m: None, use_cache=False, cost=cost)
    assert cost.verifs == 1
