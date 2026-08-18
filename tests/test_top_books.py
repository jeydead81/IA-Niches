"""`ScoredNiche.top_books` — les concurrents du top voyagent AVEC la niche.

`top_asins` ne portait que des identifiants : ni titre, ni prix, ni avis, ni BSR. Tout
consommateur en aval (le tableau de l'UI, le Dossier PDF, le verdict low-content) devait
donc soit re-payer une SERP, soit se passer des concurrents — c'est-à-dire priver l'auteur
de la seule chose qu'il veut vraiment voir : contre QUI il publierait.

Deux invariants que ce module ne doit jamais perdre :
- SEULEMENT les organiques (§4.1). Un sponsorisé dans la liste ferait juger le rayon sur
  un livre qui a payé sa place, pas sur un livre qui l'a gagnée.
- ORDRE de la SERP conservé. La position organique EST une donnée : la reclasser par BSR
  ou par prix effacerait ce qu'Amazon montre réellement à un acheteur.
"""
from models import NicheValidation, ScoredNiche, SearchItem, SearchResult, TopBook
from scoring import score_niche


def _validation() -> NicheValidation:
    return NicheValidation(niche="tarot", requete_amazon="tarot debutant",
                           categorie="eso", demand_score=6, validated=True)


def _serp() -> SearchResult:
    return SearchResult(
        keyword="tarot debutant",
        sponsored=[SearchItem(title="Sponso payant", asin="SPONSO", sponsored=True)],
        organic=[
            SearchItem(title="Tarot pour debutants", asin="A1", price=19.9,
                       rating=4.5, reviews_count=620),
            SearchItem(title="Le tarot de Marseille", asin="A2", price=14.0,
                       rating=4.1, reviews_count=88),
        ])


def test_top_books_porte_titre_prix_note_avis_et_lien():
    sn = score_niche(_validation(), _serp(), [3000], bsr_map={"A1": 3000, "A2": 61000})
    assert len(sn.top_books) == 2
    a1 = sn.top_books[0]
    assert isinstance(a1, TopBook)
    assert a1.asin == "A1" and a1.title == "Tarot pour debutants"
    assert a1.price == 19.9 and a1.rating == 4.5 and a1.reviews_count == 620
    assert a1.bsr == 3000
    assert a1.url == "https://www.amazon.fr/dp/A1"


def test_les_sponsorises_ne_sont_jamais_dans_le_top():
    """Un livre qui a payé sa place n'est pas un concurrent organique (§4.1)."""
    sn = score_niche(_validation(), _serp(), [3000])
    assert all(b.asin != "SPONSO" for b in sn.top_books)
    assert all(b.sponsored is False for b in sn.top_books)


def test_l_ordre_organique_de_la_serp_est_conserve():
    """La position EST une donnée : la reclasser effacerait ce qu'Amazon montre."""
    sn = score_niche(_validation(), _serp(), [3000], bsr_map={"A1": 3000, "A2": 61000})
    assert [b.asin for b in sn.top_books] == ["A1", "A2"]


def test_un_bsr_inconnu_reste_None_jamais_zero():
    """Zéro serait le MEILLEUR classement possible : un BSR manquant lu comme un
    best-seller est exactement l'inversion que §5.10 interdit."""
    sn = score_niche(_validation(), _serp(), [3000], bsr_map={"A1": 3000})
    assert sn.top_books[0].bsr == 3000
    assert sn.top_books[1].bsr is None


def test_sans_bsr_map_la_liste_existe_quand_meme():
    """Rétro-compatibilité : `bsr_map` est optionnel, aucun appelant existant ne le passe."""
    sn = score_niche(_validation(), _serp(), [3000])
    assert len(sn.top_books) == 2 and all(b.bsr is None for b in sn.top_books)


def test_la_liste_est_bornee_a_huit():
    serp = SearchResult(keyword="q", sponsored=[], organic=[
        SearchItem(title=f"L{i}", asin=f"A{i}") for i in range(20)])
    sn = score_niche(_validation(), serp, [])
    assert len(sn.top_books) == 8


def test_sans_serp_la_liste_est_vide_pas_absente():
    """SERP en échec : aucun concurrent CONNU, ce qui n'est pas « aucun concurrent »."""
    sn = score_niche(_validation(), None, [])
    assert sn.top_books == [] and sn.concurrence_mesuree is False


# ---------------------------------------------------------------------------
# Branchement : sans lui, `top_books` existerait avec des BSR toujours vides — le
# scout est le SEUL endroit du produit qui connaisse la table ASIN -> BSR.
# ---------------------------------------------------------------------------
from scout_master import run_scout
from models import BsrInfo, NicheCandidate


def _ideate(seed, signals, n, model, on_usage=None):
    return [NicheCandidate(niche="tarot", requete_amazon="tarot", rationale="r",
                           categorie="eso")]


def _validate(cands, **kw):
    return [NicheValidation(niche="tarot", requete_amazon="tarot", categorie="eso",
                            demand_score=6, validated=True)]


class _Provider:
    priority = 2
    location_code = 2250
    language_code = "fr_FR"

    def search(self, q, books_only=True):
        return SearchResult(keyword=q, sponsored=[], organic=[
            SearchItem(title="Tarot pour debutants", asin="A1", price=19.9,
                       rating=4.5, reviews_count=620),
            SearchItem(title="Le tarot de Marseille", asin="A2", price=14.0)])


def _bsr(asin):
    return {"A1": BsrInfo(rank_livres=3000, asin="A1"),
            "A2": BsrInfo(rank_livres=61000, asin="A2")}.get(asin)


def test_le_scout_remplit_les_bsr_des_top_books():
    res = run_scout(seed="x", n_search=1, bsr_pause=0, use_cache=False, ideate=_ideate,
                    validate=_validate, provider=_Provider(), fetch_bsr_fn=_bsr)
    assert len(res) == 1
    livres = {b.asin: b for b in res[0].top_books}
    assert livres["A1"].bsr == 3000
    assert livres["A1"].title == "Tarot pour debutants" and livres["A1"].price == 19.9


def test_un_livre_hors_du_lot_bsr_garde_un_bsr_None():
    """Le scout ne resout le BSR que des `n_bsr_per_niche` premiers ASIN : les suivants
    apparaissent dans top_books SANS classement. None, jamais 0."""
    res = run_scout(seed="x", n_search=1, n_bsr_per_niche=1, bsr_pause=0, use_cache=False,
                    ideate=_ideate, validate=_validate, provider=_Provider(),
                    fetch_bsr_fn=_bsr)
    livres = {b.asin: b for b in res[0].top_books}
    assert livres["A1"].bsr == 3000
    assert livres["A2"].bsr is None
