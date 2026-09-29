"""La revue adversariale du correctif de calibration : ce qu'il cassait, ou corrigeait à moitié.

Onze constats confirmés par des réfutateurs indépendants, cinq défauts distincts :

1. **La sonde stricte tuait le job du produit.** Passer l'autocomplete en strict — pour ne
   plus écrire une panne dans le cache mutualisé — faisait remonter UN seul 503 parmi 80
   sondes jusqu'au job : échec, unité de plafond consommée, rien à l'écran, là où le run
   continuait avant. §5.29 inversé. La sonde RESTE stricte ; c'est `expand` qui absorbe
   une panne PAR SONDE, et ne lève que si AUCUNE n'aboutit.
2. **Un lot ASIN qui échoue abandonnait le lot déjà facturé.** Un 2e envoi qui lève faisait
   sortir `product_raw_batch` avant tout poll : les 100 tâches du 1er lot, créées donc
   facturées, n'étaient ni relues ni imputées — et le low-content les repayait ensuite par
   le canal BSR. Plafond franchi en silence, famille §5.31.
3. **La porte ne se fermait que pour une voie sur trois.** Une « morte » à SERP tombée ou à
   demande non mesurée est aussi indécidable qu'une morte omise par le modèle.
4. **Un rejet du filtre IP rejoué APRÈS le modèle finissait en « non rendue »**, sous un
   avertissement qui affirmait l'inverse (« ni le filtre IP ne l'a écartée »).
5. **Le devis ignorait que la réponse du modèle grandit avec n**, et l'enrichissement — le
   poste le plus lourd du run — n'était pas gardé de façon prédictive.

Les tests des défauts 1 et 2 tournent là où la régression se voyait : le MASTER avec la sonde
par défaut, et le fournisseur réel avec un envoi qui lève. Les tests précédents appelaient
`expand` isolé ou ne couvraient que le chemin heureux — la régression leur était invisible.
"""
from functools import partial

import pytest

from autocomplete_expand import Suggestion
from lowcontent_ideator import generate_lowcontent_niches
from lowcontent_validation import RequeteEtiquetee, rapport_calibration
from models import LowContentNiche, LowContentScored, SearchItem, SearchResult


class _Bloc:
    type = "tool_use"

    def __init__(self, payload):
        self.input = payload


class _Usage:
    input_tokens = 1000
    output_tokens = 900


class _Reponse:
    def __init__(self, payload):
        self.content = [_Bloc(payload)]
        self.usage = _Usage()
        self.stop_reason = "tool_use"


class _Client:
    def __init__(self, payload):
        self.payload, self.appels, self.messages = payload, [], self

    def create(self, **kw):
        self.appels.append(kw)
        return _Reponse(self.payload)


def _sugg(requete, n_enfants=3):
    return Suggestion(requete=requete, parent="", profondeur=0, n_enfants=n_enfants)


def _niche_llm(requete):
    return {"requete_amazon": requete, "format_cle": "journal_suivi", "theme": "t",
            "public": "adulte", "niche": requete, "rationale": "r", "categorie": "c"}


def _niche(requete, **kw):
    base = dict(niche=requete, requete_amazon=requete, rationale="r", categorie="c",
                format_cle="journal_suivi", theme="t", public="adulte")
    base.update(kw)
    return LowContentNiche(**base)


def _scored(score, requete="carnet", **kw):
    base = dict(niche=_niche(requete), global_score=score, concurrence_mesuree=True,
                priorite="🟢 À analyser en priorité" if score >= 7.5
                else "🟡 Intéressant" if score >= 6.0 else "🔴 Faible")
    base.update(kw)
    return LowContentScored(**base)


def _paires_alignees():
    return [("bonne", _scored(8.2, "b1")), ("bonne", _scored(8.0, "b2")),
            ("bonne", _scored(7.8, "b3")),
            ("mauvaise", _scored(6.4, "m1")), ("mauvaise", _scored(6.1, "m2")),
            ("mauvaise", _scored(5.8, "m3")),
            ("morte", _scored(3.1, "d1")), ("morte", _scored(2.7, "d2")),
            ("morte", _scored(2.4, "d3"))]


class _ProvHorsLigne:
    location_code, language_code, priority = 2250, "fr_FR", 2

    def search(self, q, books_only=True):
        raise RuntimeError("hors ligne")


# ══ 1. Une sonde en panne ne tue plus le run — mais une panne TOTALE l'arrête ══

def _autocomplete_en_panne_sur(monkeypatch, prefixes):
    """Coupe l'autocomplete sous `expand`, au niveau de la sonde STRICTE réelle."""
    import amazon_autocomplete
    import autocomplete_expand
    monkeypatch.setattr(autocomplete_expand.time, "sleep", lambda s: None)

    def fetch(prefixe):
        if prefixes == "toutes" or prefixe in prefixes:
            raise amazon_autocomplete.AutocompleteError("HTTP 503")
        return {"suggestions": [{"value": f"{prefixe} pour adulte"}]}

    monkeypatch.setattr(amazon_autocomplete, "fetch_json_strict", fetch)


def test_UNE_sonde_en_panne_n_arrete_plus_l_arbre(monkeypatch):
    from autocomplete_expand import expand
    _autocomplete_en_panne_sur(monkeypatch, {"carnet b"})
    etapes = []
    out = expand("carnet", depth=1, alphabet=True, max_probes=4, progress=etapes.append)
    assert out, "l'arbre partiel doit être rendu"
    assert any("panne" in e for e in etapes), "la panne doit être annoncée"


def test_le_JOB_low_content_survit_a_un_503_pendant_l_arbre(monkeypatch):
    """LE test du lot, là où la régression se voyait : le master, avec la sonde PAR DÉFAUT."""
    from lowcontent_master import run_lowcontent_scout
    _autocomplete_en_panne_sur(monkeypatch, {"carnet b"})
    etapes, vus = [], {}

    def ideate(**kw):
        vus.update(kw)
        return []

    run_lowcontent_scout(seed="carnet", use_cache=False, depth=1, alphabet=True,
                         max_probes=4, ideate=ideate, progress=etapes.append)
    assert vus.get("suggestions"), "le run n'a pas atteint le classement"
    assert any("panne" in e for e in etapes)


def test_si_AUCUNE_sonde_n_aboutit_le_run_s_arrete_AVANT_toute_depense(monkeypatch):
    """Rendre [] ferait basculer le master en idéation sur la graine — c'est-à-dire sur une
    demande inventée, et payée. Mieux vaut s'arrêter, le dire, et n'avoir rien dépensé."""
    from lowcontent_master import run_lowcontent_scout
    _autocomplete_en_panne_sur(monkeypatch, "toutes")
    etapes, vus = [], {}
    with pytest.raises(Exception):
        run_lowcontent_scout(seed="carnet", use_cache=False, depth=1, alphabet=True,
                             max_probes=3, ideate=lambda **kw: vus.update(kw) or [],
                             progress=etapes.append)
    assert vus == {}, "le modèle a été appelé — et payé — sur un arbre vide"
    assert any("indisponible" in e.lower() for e in etapes)


def test_en_IDEATION_une_re_sonde_en_panne_laisse_la_demande_non_mesuree():
    """Sans graine, chaque proposition repasse par l'arbre APRÈS l'appel LLM payé. Une panne
    tuait le run et perdait les jetons ; elle laisse désormais `n_enfants=None` (jamais
    sondée, neutre au scoring) — jamais 0, qui serait une mesure défavorable."""
    from lowcontent_master import run_lowcontent_scout
    from models import NicheValidation
    etapes, vues = [], {}

    def en_panne(*a, **k):
        raise RuntimeError("503")

    def validate(niches, **kw):
        vues["n_enfants"] = [n.n_enfants_autocomplete for n in niches]
        return [NicheValidation(niche=n.niche, requete_amazon=n.requete_amazon,
                                categorie="c", validated=False) for n in niches]

    run_lowcontent_scout(seed=None, use_cache=False, expand_fn=en_panne,
                         ideate=lambda **kw: [_niche("carnet de suivi migraine",
                                                     source="ideation")],
                         validate=validate, progress=etapes.append)
    assert vues["n_enfants"] == [None]
    assert any("panne" in e for e in etapes)


# ══ 2. Un lot qui échoue n'abandonne pas le lot déjà facturé ═══════════════════

def _fournisseur_a_lots(monkeypatch, echec_au_envoi=2):
    import search_providers
    from search_providers import DataForSEOProvider
    monkeypatch.setattr(search_providers.time, "sleep", lambda s: None)
    prov = DataForSEOProvider(login="x", password="y", priority=2)
    tache_asin, compteur, n_envois = {}, iter(range(100_000)), [0]

    def faux_post(url, body):
        n_envois[0] += 1
        if n_envois[0] == echec_au_envoi:
            raise ConnectionError("ReadTimeout sur ce lot")
        taches = []
        for t in body:
            tid = f"t{next(compteur)}"
            tache_asin[tid] = t["asin"]
            taches.append({"status_code": 20100, "id": tid, "data": {"asin": t["asin"]}})
        return {"tasks": taches}

    def faux_get(url):
        tid = url.rsplit("/", 1)[1]
        return {"tasks": [{"status_code": 20000, "result": [{"asin": tache_asin[tid]}]}]}

    prov._post, prov._get = faux_post, faux_get
    return prov


def test_un_lot_qui_echoue_n_abandonne_pas_le_lot_deja_facture(monkeypatch):
    prov = _fournisseur_a_lots(monkeypatch)
    asins = [f"B{i:04d}" for i in range(150)]
    out = prov.product_raw_batch(asins)
    assert all(out[a] is not None for a in asins[:100]), \
        "le lot 1, créé donc facturé, n'a pas été relu"
    assert all(out[a] is None for a in asins[100:])
    assert out.taches_creees == 100


def test_l_enrichissement_impute_les_taches_creees_ET_le_lot_incertain(monkeypatch):
    """Assertion RETOURNÉE le 2026-09-29 (pré-mortem du run 6) : elle valait 100, sur
    l'hypothèse « le lot 2 n'a jamais été créé ». Le code ne peut pas le savoir — le lot 2
    tombe ici sur un `ReadTimeout`, c'est-à-dire une requête PARTIE dont la réponse s'est
    perdue, et DataForSEO a pu créer donc facturer ses 100 tâches. On impute le pire cas,
    150, comme le chemin SERP des trois moteurs le fait déjà sur le même `_post` : seul un
    refus EXPLICITE n'est pas facturé (§5.29). Le lot 1, lui, reste relu et imputé."""
    from cost_tracker import CostTracker
    from fiction_serp_provider import enrich_asins
    prov = _fournisseur_a_lots(monkeypatch)
    cost = CostTracker(plafond_usd=None)
    enrich_asins([f"B{i:04d}" for i in range(150)], provider=prov, cost=cost)
    assert cost.breakdown()["dataforseo_calls"] == 150


# ══ 3. Toute « morte » indécidable ferme la porte, pas seulement l'omise ════════

def test_une_morte_a_SERP_TOMBEE_ferme_la_porte():
    """La SERP qui expire est LA panne mesurée en live (§5.17, 3 SERP sur 3), et le run de
    calibration en enchaîne 31. Une morte « ⚪ à relancer » n'est pas « pas en vert » :
    son score n'a jamais vu le rayon."""
    tombee = _scored(8.4, "carnet de suivi migraine", concurrence_mesuree=False,
                     priorite="⚪ Concurrence non mesurée — à relancer")
    r = rapport_calibration(_paires_alignees() + [("morte", tombee)])
    assert r.porte_franchie is False
    assert any("carnet de suivi migraine" in a for a in r.avertissements)


def test_une_morte_a_DEMANDE_NON_MESUREE_ferme_la_porte():
    sans_sonde = _scored(7.2, "livre de coloriage vehicule")
    sans_sonde.niche.n_enfants_autocomplete = None
    r = rapport_calibration(_paires_alignees() + [("morte", sans_sonde)])
    assert r.porte_franchie is False


# ══ 4. Un rejet du filtre IP APRÈS le modèle reste un rejet du filtre ══════════

def test_un_rejet_IP_APRES_le_modele_reste_impute_au_filtre():
    """Requête propre, mais le modèle glisse une marque dans ses satellites : le rejeu du
    filtre IP l'écarte. C'est un rejet du filtre — un vrai faux négatif du produit si elle
    est « bonne » —, pas une absence de mesure."""
    from build_lowcontent_validation_set import construire_rapport
    from lowcontent_master import run_lowcontent_scout
    requete = "cahier de coloriage chien enfant"
    niche = _niche_llm(requete)
    niche["satellite_keywords"] = ["coloriage pat patrouille"]
    client = _Client({"niches": [niche]})
    run = partial(run_lowcontent_scout, use_cache=False, provider=_ProvHorsLigne(),
                  ideate=lambda **kw: generate_lowcontent_niches(client=client, **kw))
    r = construire_rapport([RequeteEtiquetee(requete=requete, famille="coloriage",
                                             etiquette="bonne")],
                           run=run, sonde=lambda rs, **kw: [_sugg(q) for q in rs])
    assert r.bonnes_perdues_avant_analyse == [requete]
    assert r.non_rendues == []


# ══ 5. Le devis et le plafond voient ce qui grandit vraiment ═══════════════════

def test_le_devis_low_content_compte_la_reponse_du_modele():
    """Une niche de plus coûte une SERP et six fiches (0,021 $) — ET une niche de plus dans
    la réponse du modèle. Le devis ne voyait que le premier terme."""
    from devis import cout_max_estime
    marginal = (cout_max_estime("lowcontent", {"n_search": 31})
                - cout_max_estime("lowcontent", {"n_search": 30}))
    assert marginal > 0.021 + 1e-4


def test_l_enrichissement_est_garde_de_facon_PREDICTIVE():
    """Le poste le plus lourd était vérifié avec `cout_prevu=0` : il ne refusait qu'APRÈS
    avoir dépassé. Son tarif est pourtant connu d'avance."""
    from cost_tracker import CostTracker
    from lowcontent_master import run_lowcontent_scout
    requete = "carnet de suivi migraine"
    appels, etapes = [], []

    class _Prov:
        location_code, language_code, priority = 2250, "fr_FR", 2

        def search(self, q, books_only=True):
            return SearchResult(keyword=q, organic=[SearchItem(asin=f"B{i}", title=q)
                                                    for i in range(6)])

    run_lowcontent_scout(
        seed="carnet", use_cache=False, provider=_Prov(),
        cost=CostTracker(plafond_usd=0.010), bsr_pause=0,
        expand_fn=lambda *a, **k: [_sugg(requete, 4)],
        ideate=lambda **kw: [_niche(requete, n_enfants_autocomplete=4)],
        enrich_fn=lambda asins, **kw: appels.append(list(asins)) or {},
        fetch_bsr_fn=lambda asin: None, progress=etapes.append)
    assert appels == [], "l'enrichissement est parti alors qu'il dépassait le plafond"
