"""Ce que le pré-mortem du run de calibration a trouvé, et que la répétition à blanc ne
pouvait pas voir.

La répétition passait un faux modèle qui rendait TOUT ce qu'on lui donnait. Le vrai prompt,
lui, ordonne au modèle d'en jeter une partie « sans le signaler ». Cinq défauts, chacun
confirmé par un réfutateur indépendant, tous invisibles pour la suite existante :

1. **RÈGLE DE SÉLECTION.** Le prompt système dit : ne retiens que les requêtes à DEUX
   spécificateurs, « écarte le reste sans le signaler ». Sur les 31 requêtes de Baptiste,
   une quinzaine n'en ont qu'un — et ce sont surtout ses « morte ». Omises, elles remontaient
   comme « écartées pour zéro centime : le gate gratuit a fait son travail » (faux : elles
   étaient dans le prompt payé, et aucun gate ne joue en mode classement), sortaient du
   critère « aucune morte en vert », et le Spearman se calculait sur un sous-ensemble choisi
   par le LLM. Exactement l'auto-sélection que le protocole dit exclure.
2. **PLUS DE 100 ASIN EN UN SEUL ENVOI.** DataForSEO plafonne un task_post à 100 tâches ;
   30 niches × 6 ASIN en font 180. La fin de la shortlist perdait son enrichissement en
   silence — et la FICTION du produit y est exposée dès aujourd'hui (11 trios × 12 = 132).
3. **UN RANG « FOURNITURES DE BUREAU » LU COMME UN RANG « LIVRES ».** Les carnets sont
   souvent classés hors du rayon Livres ; leur rang entrait tel quel dans des seuils calés
   sur les Livres (§5.5) : +2 en demande, critères BSR basculés à « OK ».
4. **UNE SONDE EN PANNE LUE COMME UNE MESURE.** `expand` prenait par défaut la version
   laxiste de l'autocomplete : un 503 devenait « zéro complétion », écrit dans le CACHE
   MUTUALISÉ pour 15 jours — tous les comptes lisaient ensuite « Amazon ne complète rien ».
5. **DES SOUS-CATÉGORIES PAYÉES PUIS JETÉES.** Le dossier low-content annonçait « donnée non
   mesurée » alors qu'elle avait été lue — et facturée — dans le batch ASIN.
"""
import pytest

from autocomplete_expand import Suggestion
from lowcontent_ideator import generate_lowcontent_niches
from lowcontent_validation import RequeteEtiquetee, rapport_calibration
from models import (EnrichedBook, LowContentNiche, LowContentScored, SearchItem,
                    SearchResult)


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
        self.payload = payload
        self.appels = []
        self.messages = self

    def create(self, **kw):
        self.appels.append(kw)
        return _Reponse(self.payload)


def _sugg(requete, n_enfants=3):
    return Suggestion(requete=requete, parent="", profondeur=0, n_enfants=n_enfants)


def _niche_llm(requete):
    return {"requete_amazon": requete, "format_cle": "journal_suivi", "theme": "t",
            "public": "adulte", "niche": requete, "rationale": "r", "categorie": "c"}


def _scored(score, requete="carnet", **kw):
    n = LowContentNiche(niche=requete, requete_amazon=requete, rationale="r",
                        categorie="c", format_cle="journal_suivi", theme="t",
                        public="adulte")
    base = dict(niche=n, global_score=score, concurrence_mesuree=True,
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


# ══ 1. La règle de sélection ne s'applique pas à un jeu de MESURE ══════════════

def test_en_mode_classer_toutes_le_prompt_ne_trie_plus():
    client = _Client({"niches": []})
    generate_lowcontent_niches(seed="x", suggestions=[_sugg("kakuro adulte")],
                               classer_toutes=True, client=client)
    appel = client.appels[0]
    assert "RÈGLE DE SÉLECTION" not in appel["system"]
    user = appel["messages"][0]["content"]
    assert "les plus spécifiques" not in user
    assert "TOUTES" in user


def test_par_defaut_le_produit_GARDE_sa_regle_de_selection():
    """Dans le produit, l'arbre rend 80 requêtes et le tri est voulu : ne rien changer."""
    client = _Client({"niches": []})
    generate_lowcontent_niches(seed="x", suggestions=[_sugg("kakuro adulte")],
                               client=client)
    assert "RÈGLE DE SÉLECTION" in client.appels[0]["system"]


def test_une_requete_fournie_mais_NON_classee_est_annoncee_par_son_nom():
    etapes = []
    client = _Client({"niches": [_niche_llm("livre de coloriage dinosaure")]})
    generate_lowcontent_niches(
        seed="x", suggestions=[_sugg("livre de coloriage dinosaure"),
                               _sugg("Carnet de suivi migraine")],
        classer_toutes=True, client=client, progress=etapes.append)
    assert any("Carnet de suivi migraine" in e for e in etapes)


def test_en_mode_produit_les_requetes_non_retenues_sont_au_moins_COMPTEES():
    """« Sans le signaler » contredit la règle 2 du dépôt : un tri n'est pas un échec,
    mais il se compte."""
    etapes = []
    client = _Client({"niches": [_niche_llm("livre de coloriage dinosaure")]})
    generate_lowcontent_niches(
        seed="x", suggestions=[_sugg("livre de coloriage dinosaure"),
                               _sugg("Carnet de suivi migraine")],
        client=client, progress=etapes.append)
    assert any("non retenue" in e for e in etapes)


def test_le_master_transmet_classer_toutes():
    from lowcontent_master import run_lowcontent_scout
    vus = {}

    def ideate(**kw):
        vus.update(kw)
        return []

    run_lowcontent_scout(seed="carnet", use_cache=False, classer_toutes=True,
                         expand_fn=lambda *a, **k: [_sugg("carnet de suivi migraine")],
                         ideate=ideate)
    assert vus.get("classer_toutes") is True


def test_la_calibration_IMPOSE_classer_toutes():
    from build_lowcontent_validation_set import construire_rapport
    vus = {}

    def run(**kw):
        vus.update(kw)
        return []

    construire_rapport([RequeteEtiquetee(requete="kakuro adulte", famille="grilles",
                                         etiquette="mauvaise")],
                       run=run, sonde=lambda rs, **kw: [Suggestion(requete=q, n_enfants=3) for q in rs])
    assert vus.get("classer_toutes") is True


def test_une_requete_OMISE_par_le_classement_n_est_PAS_imputee_au_gate():
    """LE test du lot. Aucun gate ne joue en mode classement : une requête absente de la
    sortie a été omise par le modèle, tronquée, ou coupée par le plafond — jamais
    « écartée pour zéro centime »."""
    from build_lowcontent_validation_set import construire_rapport
    etq = [RequeteEtiquetee(requete="livre de coloriage dinosaure", famille="coloriage",
                            etiquette="mauvaise"),
           RequeteEtiquetee(requete="carnet a", famille="carnets", etiquette="bonne")]
    r = construire_rapport(etq, run=lambda **kw: [_scored(8.0, "carnet a")],
                           sonde=lambda rs, **kw: [Suggestion(requete=q, n_enfants=3) for q in rs])
    assert r.ecartees_correctement == []
    assert r.non_rendues == [{"requete": "livre de coloriage dinosaure",
                              "etiquette": "mauvaise"}]


def test_une_requete_REELLEMENT_filtree_reste_imputee_au_filtre():
    from build_lowcontent_validation_set import construire_rapport
    etq = [RequeteEtiquetee(requete="coloriage pat patrouille", famille="coloriage",
                            etiquette="morte")]
    r = construire_rapport(etq, run=lambda **kw: [], sonde=lambda rs, **kw: [Suggestion(requete=q, n_enfants=3) for q in rs])
    assert r.ecartees_correctement == ["coloriage pat patrouille"]
    assert r.non_rendues == []


def test_le_saisonnier_leve_n_est_plus_impute_au_filtre():
    """Avec `--inclure-saisonnier`, le filtre ne joue plus : une requête de Noël absente
    n'a été écartée par personne."""
    from build_lowcontent_validation_set import construire_rapport
    etq = [RequeteEtiquetee(requete="livre escape game enfant noel", famille="jeux",
                            etiquette="bonne")]
    avec_filtre = construire_rapport(etq, run=lambda **kw: [], sonde=lambda rs, **kw: [Suggestion(requete=q, n_enfants=3) for q in rs],
                                     inclure_saisonnier=False)
    sans_filtre = construire_rapport(etq, run=lambda **kw: [], sonde=lambda rs, **kw: [Suggestion(requete=q, n_enfants=3) for q in rs],
                                     inclure_saisonnier=True)
    assert avec_filtre.bonnes_perdues_avant_analyse == ["livre escape game enfant noel"]
    assert sans_filtre.bonnes_perdues_avant_analyse == []
    assert [d["requete"] for d in sans_filtre.non_rendues] == \
        ["livre escape game enfant noel"]


def test_une_morte_NON_SCOREE_ferme_la_porte():
    """« Aucune morte en vert » ne se vérifie pas sur une morte qu'on n'a pas scorée. Le
    critère est INDÉCIDABLE pour elle, pas satisfait : ouvrir la porte serait lire une
    absence de mesure comme un verdict (règle 3)."""
    r = rapport_calibration(_paires_alignees(),
                            non_rendues=[("Carnet de suivi migraine", "morte")])
    assert r.spearman >= 0.5 and r.morts_en_vert == []
    assert r.porte_franchie is False
    assert any("morte" in a.lower() and "non" in a.lower() for a in r.avertissements)


def test_une_bonne_non_rendue_ne_ferme_pas_la_porte_mais_se_dit():
    """Fixture rendue réaliste : un run nominal a lu le rayon (`part_indie`,
    `redevance_estimee`). Sans ces champs, elle décrivait un enrichissement ASIN tombé —
    cas qui ferme désormais la porte pour une tout autre raison, et l'assertion ne
    porterait plus sur ce qu'elle prétend tester."""
    paires = [(e, _scored(s.global_score, f"{e}{i}", part_indie=0.7,
                          redevance_estimee=3.1))
              for i, (e, s) in enumerate(_paires_alignees())]
    r = rapport_calibration(paires,
                            non_rendues=[("livre quizz culture générale", "bonne")])
    assert r.porte_franchie is True
    assert r.non_rendues
    assert any("classement" in a.lower() for a in r.avertissements)


def test_un_tiret_ne_change_pas_de_requete():
    """« anti-stress » et « anti stress » sont la même requête. Sans ce repli, le modèle
    qui ajoute un tiret faisait écarter une requête réelle comme inventée."""
    from lowcontent_ideator import _norm
    assert _norm("livre de coloriage pour adulte anti-stress") == \
        _norm("livre de coloriage pour adulte anti stress")


# ══ 2. Plus de 100 ASIN : plusieurs envois, UNE file ═══════════════════════════

def test_plus_de_100_asin_partent_en_plusieurs_envois_et_reviennent_tous():
    from search_providers import DataForSEOProvider
    prov = DataForSEOProvider(login="x", password="y", priority=2)
    journal, tache_asin = [], {}
    compteur = iter(range(100_000))

    def faux_post(url, body):
        journal.append(("post", len(body)))
        taches = []
        for t in body:
            tid = f"t{next(compteur)}"
            tache_asin[tid] = t["asin"]
            taches.append({"status_code": 20100, "id": tid, "data": {"asin": t["asin"]}})
        return {"tasks": taches}

    def faux_get(url):
        journal.append(("get", None))
        tid = url.rsplit("/", 1)[1]
        return {"tasks": [{"status_code": 20000, "result": [{"asin": tache_asin[tid]}]}]}

    asins = [f"B{i:04d}" for i in range(150)]
    out = prov.product_raw_batch(asins, post_json=faux_post, get_json=faux_get,
                                 poll_interval=0)
    envois = [n for k, n in journal if k == "post"]
    assert len(envois) == 2 and max(envois) <= 100
    assert all(out[a] is not None for a in asins), "des ASIN reviennent sans payload"
    # Tous les envois partent AVANT la première lecture : la file ne se paie qu'une fois.
    dernier_envoi = max(i for i, (k, _) in enumerate(journal) if k == "post")
    premiere_lecture = min(i for i, (k, _) in enumerate(journal) if k == "get")
    assert dernier_envoi < premiere_lecture


# ══ 3 + 5. Le rang et les sous-catégories du RAYON LIVRES seulement ═════════════

def _run_un_livre(livre, requete="carnet de musique avec portée"):
    from cost_tracker import CostTracker
    from lowcontent_master import run_lowcontent_scout
    niche = LowContentNiche(niche=requete, requete_amazon=requete, rationale="r",
                            categorie="c", format_cle="journal_suivi", theme="t",
                            public="adulte", n_enfants_autocomplete=4)

    class _Prov:
        location_code, language_code, priority = 2250, "fr_FR", 2

        def search(self, q, books_only=True):
            return SearchResult(keyword=q, organic=[SearchItem(asin=livre.asin, title=q)])

    return run_lowcontent_scout(
        seed="carnet", use_cache=False, provider=_Prov(),
        cost=CostTracker(plafond_usd=10.0),
        expand_fn=lambda *a, **k: [_sugg(requete, n_enfants=4)],
        ideate=lambda **kw: [niche],
        enrich_fn=lambda asins, **kw: {livre.asin: livre})


def test_un_rang_FOURNITURES_DE_BUREAU_n_entre_pas_dans_les_seuils_Livres():
    livre = EnrichedBook(asin="B0001", title="t", bsr=2310,
                         bsr_rayon="Fournitures de bureau")
    out = _run_un_livre(livre)
    assert out[0].bsr_best is None, "un rang hors rayon Livres a été comparé aux seuils"


def test_un_rang_LIVRES_est_bien_retenu():
    livre = EnrichedBook(asin="B0001", title="t", bsr=2310, bsr_rayon="Livres")
    out = _run_un_livre(livre)
    assert out[0].bsr_best == 2310


def test_les_sous_categories_lues_dans_l_enrichissement_ne_sont_plus_jetees():
    """Le dossier les lit sous la forme `{category, rank}` (`categories.py`) ; le parseur
    des fiches les écrit `{rang, categorie}`. Les recopier sans les convertir les ferait
    écarter en silence par le dossier."""
    livre = EnrichedBook(asin="B0001", title="t", bsr=2310, bsr_rayon="Livres",
                         bsr_subcats=[{"rang": 6, "categorie": "Partitions"}])
    out = _run_un_livre(livre)
    subs = out[0].top_books[0].bsr_subcats
    assert any(s.get("category") == "Partitions" and s.get("rank") == 6 for s in subs)


def test_les_sous_categories_d_un_rang_hors_Livres_ne_deviennent_pas_des_categories_KDP():
    livre = EnrichedBook(asin="B0001", title="t", bsr=2310,
                         bsr_rayon="Fournitures de bureau",
                         bsr_subcats=[{"rang": 3, "categorie": "Cahiers"}])
    out = _run_un_livre(livre)
    assert out[0].top_books[0].bsr_subcats == []


# ══ 4. Une sonde en panne n'est pas une mesure ═════════════════════════════════

def test_une_erreur_HTTP_de_l_autocomplete_LEVE_au_lieu_de_valoir_zero(monkeypatch):
    import amazon_autocomplete
    from autocomplete_expand import expand

    def en_panne(prefixe):
        raise amazon_autocomplete.AutocompleteError("HTTP 503")

    monkeypatch.setattr(amazon_autocomplete, "fetch_json_strict", en_panne)
    with pytest.raises(amazon_autocomplete.AutocompleteError):
        expand("carnet", depth=1, alphabet=False, pause=0)


def test_une_panne_n_est_JAMAIS_ecrite_dans_le_cache_mutualise(monkeypatch):
    """Le cache est partagé entre tous les comptes : y écrire « rien » après un 503, c'est
    faire lire « Amazon ne complète rien » à tout le monde pendant 15 jours."""
    import amazon_autocomplete
    from autocomplete_expand import expand

    def en_panne(prefixe):
        raise amazon_autocomplete.AutocompleteError("HTTP 503")

    monkeypatch.setattr(amazon_autocomplete, "fetch_json_strict", en_panne)

    class _Cache:
        def __init__(self):
            self.ecrits = []

        def get_autocomplete(self, *a, **k):
            return None

        def set_autocomplete(self, *a, **k):
            self.ecrits.append(a)

    cache = _Cache()
    try:
        expand("carnet", depth=1, alphabet=False, pause=0, cache=cache)
    except amazon_autocomplete.AutocompleteError:
        pass
    assert cache.ecrits == []


def test_une_niche_dont_la_DEMANDE_n_a_pas_ete_mesuree_sort_du_calcul():
    """Une sonde tombée laisse `n_enfants=None`, et le master en tire `demand_score=1` —
    un minimum inventé. La corréler au jugement de Baptiste mesurerait ce minimum."""
    sans_sonde = _scored(8.0, "registre de sécurité incendie")
    sans_sonde.niche.n_enfants_autocomplete = None
    r = rapport_calibration(_paires_alignees() + [("bonne", sans_sonde)])
    assert r.n_demande_non_mesuree == 1
    assert r.n_calibrees == 9
    assert any("demande" in a.lower() for a in r.avertissements)


def test_un_rang_dont_le_RAYON_EST_ILLISIBLE_n_entre_pas_dans_les_seuils():
    """Decision assumee, figee ici plutot que laissee implicite : un rang dont le parseur
    n'a pas lu le rayon ne se compare pas aux seuils Livres. Le garder risquait un +2 en
    demande sur un rang de Fournitures de bureau mal etiquete ; l'ecarter ne coute qu'une
    absence de mesure (ni bonus ni malus), que la regle 3 du depot sait lire."""
    livre = EnrichedBook(asin="B0001", title="t", bsr=2310, bsr_rayon=None)
    out = _run_un_livre(livre)
    assert out[0].bsr_best is None
