"""Orchestrateur low-content — mêmes invariants d'orchestration que les deux autres scouts.

Trois choses qu'il ne doit jamais perdre :

- LE GATE GRATUIT. Aucune niche non validée ne coûte un appel payant. C'est structurel
  (règle 9), pas une optimisation.
- UN SEUL batch ASIN par run. La file DataForSEO met ~250 s quel que soit le nombre
  d'ASIN : la payer une fois par niche ferait passer 6 niches de 5 à 25 minutes (§5.16).
- UN ÉCHEC N'INTERROMPT JAMAIS UN RUN, mais il est toujours compté, et il ne se lit jamais
  comme une mesure (§5.29).

Et un invariant propre au low-content : en mode CLASSEMENT, la demande est déjà acquise —
les requêtes viennent de l'arbre, donc Amazon les complète par construction. Re-sonder
l'autocomplete pour « valider » ce qu'on vient d'y lire serait payer du temps pour
confirmer une tautologie.
"""
import pytest

from autocomplete_expand import Suggestion
from cost_tracker import CostTracker
from lowcontent_master import run_lowcontent_scout
from models import EnrichedBook, LowContentNiche, SearchItem, SearchResult


def _niche(requete, prof=2, enfants=3, format_cle="journal_suivi", **kw):
    base = dict(niche=requete, requete_amazon=requete, rationale="r", categorie="santé",
                format_cle=format_cle, theme="t", public="adulte", source="autocomplete",
                profondeur_autocomplete=prof, n_enfants_autocomplete=enfants)
    base.update(kw)
    return LowContentNiche(**base)


def _expand_fige(requetes):
    def expand(seed, **kw):
        return [Suggestion(requete=r, parent=seed, profondeur=2, n_enfants=3)
                for r in requetes]
    return expand


def _ideate_fige(niches):
    def ideate(**kw):
        return list(niches)
    return ideate


class _Provider:
    priority = 2
    location_code = 2250
    language_code = "fr_FR"

    def __init__(self, echoue_sur=()):
        self.appels = []
        self.echoue_sur = set(echoue_sur)

    def search(self, q, books_only=True):
        self.appels.append(q)
        if q in self.echoue_sur:
            raise RuntimeError("SERP indisponible")
        return SearchResult(keyword=q, sponsored=[], organic=[
            SearchItem(title=f"Carnet {q} {i}", asin=f"{q[:3]}{i}", price=11.99,
                       reviews_count=8)
            for i in range(3)])


def _enrich_compteur():
    appels = []

    def enrich(asins, **kw):
        appels.append(list(asins))
        return {a: EnrichedBook(asin=a, title=f"T{a}", publisher="Independently published",
                                publication_date="2026-06-01", price=11.99, pages=120)
                for a in asins}
    enrich.appels = appels
    return enrich


def _bsr(asin):
    from models import BsrInfo
    return BsrInfo(rank_livres=8000, asin=asin)


def _run(**kw):
    defauts = dict(seed="carnet", n_search=2, bsr_pause=0, use_cache=False,
                   expand_fn=_expand_fige(["carnet suivi glycemie diabete",
                                           "carnet suivi tension arterielle"]),
                   ideate=_ideate_fige([_niche("carnet suivi glycemie diabete"),
                                        _niche("carnet suivi tension arterielle")]),
                   provider=_Provider(), enrich_fn=_enrich_compteur(),
                   fetch_bsr_fn=_bsr)
    defauts.update(kw)
    return run_lowcontent_scout(**defauts)


# ── Chemin nominal ─────────────────────────────────────────────────────────────

def test_le_run_rend_des_niches_scorees():
    out = _run()
    assert len(out) == 2
    assert all(0 < s.global_score <= 10 for s in out)
    assert all(s.niche.source == "autocomplete" for s in out)


def test_les_niches_sont_triees_par_score_decroissant():
    out = _run()
    assert [s.global_score for s in out] == sorted(
        (s.global_score for s in out), reverse=True)


def test_les_signaux_low_content_sont_remplis():
    s = _run()[0]
    assert s.part_indie == 1.0
    assert s.prix_median == 11.99 and s.pages_median == 120
    assert s.redevance_estimee is not None
    assert s.top_books and s.top_books[0].url.startswith("https://www.amazon.fr/dp/")


# ── Le batch ASIN unique ───────────────────────────────────────────────────────

def test_un_seul_batch_asin_pour_toutes_les_niches():
    """LE point d'orchestration : la file DataForSEO met ~250 s quel que soit le lot.
    Un batch par niche ferait passer 6 niches de 5 à 25 minutes (§5.16)."""
    enrich = _enrich_compteur()
    _run(enrich_fn=enrich)
    assert len(enrich.appels) == 1


def test_les_asin_sont_dedupliques_entre_niches():
    """Deux niches voisines partagent des livres : les payer deux fois est un gaspillage
    silencieux, puisque rien dans le rapport ne le montrerait."""
    enrich = _enrich_compteur()

    class _ProviderPartage(_Provider):
        def search(self, q, books_only=True):
            self.appels.append(q)
            return SearchResult(keyword=q, sponsored=[], organic=[
                SearchItem(title="Commun", asin="PARTAGE", price=11.99),
                SearchItem(title=f"Propre {q}", asin=f"P{len(self.appels)}", price=11.99)])

    _run(provider=_ProviderPartage(), enrich_fn=enrich)
    lot = enrich.appels[0]
    assert lot.count("PARTAGE") == 1


# ── Gate de coût et bornes ─────────────────────────────────────────────────────

def _validate_rien(cands, **kw):
    from models import NicheValidation
    return [NicheValidation(niche=c.niche, requete_amazon=c.requete_amazon,
                            categorie=c.categorie, demand_score=0, validated=False)
            for c in cands]


def test_en_ideation_une_niche_non_validee_ne_coute_aucune_serp():
    """Le gate gratuit est structurel (regle 9). En IDEATION, la demande est une
    hypothese du modele : une requete qu'Amazon ne complete pas ne doit jamais atteindre
    la phase payante."""
    prov = _Provider()
    out = _run(seed=None, provider=prov, validate=_validate_rien,
               expand_fn=lambda seed, **kw: [],
               ideate=_ideate_fige([_niche("carnet invente", source="ideation")]))
    assert out == [] and prov.appels == []


def test_en_classement_la_validation_n_est_PAS_re_sondee():
    """Court-circuit ASSUME, et c'est pour ca qu'il a son test. En mode classement les
    requetes VIENNENT de l'arbre : Amazon les complete par construction. Les re-sonder
    pour "valider" ce qu'on vient d'y lire ferait attendre l'utilisateur quelques
    secondes de plus pour confirmer une tautologie.

    Consequence a connaitre : un `validate` injecte est IGNORE dans ce mode. Le test le
    dit explicitement plutot que de laisser un appelant le decouvrir en constatant que
    son filtre ne filtre rien."""
    appele = []

    def validate_espion(cands, **kw):
        appele.append(cands)
        return _validate_rien(cands, **kw)

    out = _run(validate=validate_espion)
    assert appele == []          # jamais appele
    assert len(out) == 2         # ...et les niches de l'arbre passent


def test_le_plafond_de_cout_cloture_le_run_sur_un_rapport_partiel():
    prov = _Provider()
    etapes = []
    _run(provider=prov, n_search=2, cost=CostTracker(plafond_usd=0.004),
         progress=etapes.append)
    assert len(prov.appels) == 1
    msg = " ".join(etapes).lower()
    assert "plafond" in msg and "partiel" in msg


def test_la_shortlist_privilegie_les_requetes_les_plus_affinees():
    """Tri par `n_enfants` puis profondeur : une requête que les acheteurs affinent encore
    porte une intention plus forte. C'est le signal que l'arbre apporte, il doit décider
    de ce qu'on paie."""
    prov = _Provider()
    _run(provider=prov, n_search=1,
         ideate=_ideate_fige([_niche("carnet plat", prof=1, enfants=0),
                              _niche("carnet tres affine", prof=2, enfants=7)]))
    assert prov.appels == ["carnet tres affine"]


# ── Échecs ─────────────────────────────────────────────────────────────────────

def test_une_serp_en_echec_ne_coule_pas_le_run():
    """La niche est scorée sans concurrence ET marquée non mesurée : le zéro de mesure ne
    doit jamais déclencher le bonus « rayon vide » (§4.1)."""
    prov = _Provider(echoue_sur=["carnet suivi tension arterielle"])
    out = _run(provider=prov)
    assert len(out) == 2
    ratee = next(s for s in out if s.niche.requete_amazon == "carnet suivi tension arterielle")
    assert ratee.concurrence_mesuree is False
    assert "non mesur" in ratee.priorite.lower()


def test_un_enrichissement_vide_n_invente_aucun_livre():
    """Un rayon non enrichi n'est pas un rayon sans éditeurs : `part_indie` doit rester
    None, jamais 0.0 (§5.10)."""
    out = _run(enrich_fn=lambda asins, **kw: {})
    assert out[0].part_indie is None


def test_aucune_niche_apres_filtrage_rend_une_liste_vide_sans_lever():
    assert _run(ideate=_ideate_fige([])) == []


# ── Mode « à partir de rien » ──────────────────────────────────────────────────

def test_sans_graine_les_niches_proposees_sont_confrontees_a_amazon():
    """En idéation, la demande est une HYPOTHÈSE : chaque requête proposée doit passer par
    l'arbre avant de coûter une SERP. Sinon on paierait pour une demande inventée."""
    sondees = []

    def expand(seed, **kw):
        sondees.append(seed)
        return [Suggestion(requete=f"{seed} precis", parent=seed, profondeur=1,
                           n_enfants=2)]

    prov = _Provider()
    _run(seed=None, expand_fn=expand, provider=prov,
         ideate=_ideate_fige([_niche("carnet suivi migraine", prof=0, enfants=0,
                                     source="ideation")]))
    assert "carnet suivi migraine" in sondees


def test_un_format_impose_sert_de_graine_quand_il_n_y_en_a_pas():
    """Le format porte ses `patterns` : « carnet de suivi {theme} » amorce l'arbre. Sans
    ça, choisir un format sans graine ne produirait rien."""
    sondees = []

    def expand(seed, **kw):
        sondees.append(seed)
        return [Suggestion(requete="registre du personnel obligatoire", parent=seed,
                           profondeur=1, n_enfants=3)]

    _run(seed=None, format_cle="registres_reglementaires", expand_fn=expand,
         ideate=_ideate_fige([_niche("registre du personnel obligatoire",
                                     format_cle="registres_reglementaires")]))
    assert sondees and "registre" in sondees[0].lower()


def test_un_format_inconnu_leve_avant_toute_depense():
    with pytest.raises(ValueError):
        _run(format_cle="grimoire")


# ── Récapitulatif de fin de run ────────────────────────────────────────────────

def test_les_requetes_hors_taxonomie_sont_recapitulees():
    """Les « other » sont le matériau de la taxonomie v2 : les laisser dans le rapport
    sans les nommer, c'est perdre le seul retour terrain du run."""
    etapes = []
    _run(progress=etapes.append,
         ideate=_ideate_fige([_niche("carnet de rituels lunaires", format_cle="other",
                                     other_libelle="grimoire")]))
    assert "hors taxonomie" in " ".join(etapes).lower()
