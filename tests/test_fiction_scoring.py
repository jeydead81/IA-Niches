from fiction_scoring import (SEUILS, livres_scorables, depth_score, openness_score,
                             saturation_trio, series_share, price_band, build_report)
from models import (AutocompleteSignal, EnrichedBook, FictionNiche, FictionShelf,
                    TropeClassification)


def _livre(asin, bsr, rayon="Boutique Kindle", gratuit=False, prix=3.99, avis=20,
           serie=False, pos=1):
    return EnrichedBook(asin=asin, title="T", bsr=bsr, bsr_rayon=rayon,
                        bsr_gratuit=gratuit, price=prix, reviews_count=avis,
                        serie_total=5 if serie else None, serie_tome=1 if serie else None,
                        serp_position=pos)


def test_scorables_ecarte_gratuits_non_romans_et_mauvais_rayon():
    """Trois exclusions mesurées au spike : un titre gratuit a un classement DISTINCT,
    un jeu n'est pas un roman, et un rang « Livres » n'est pas comparable à un rang
    « Boutique Kindle »."""
    livres = [_livre("A1", 2000), _livre("A2", 478, gratuit=True),
              _livre("A3", 1597, rayon="Livres"), _livre("A4", 5000), _livre("A5", None)]
    cl = {"A4": TropeClassification(asin="A4", taxonomy_version="fr_v1", est_roman=False)}
    ok = livres_scorables(livres, cl, rayon="kindle")
    assert [b.asin for b in ok] == ["A1"]


def test_depth_calee_sur_les_rayons_mesures():
    """thriller psy (best 1960) doit sortir nettement au-dessus de cosy village (best 62230)."""
    actif = [_livre(f"A{i}", b) for i, b in enumerate([1960, 2168, 7422, 14924, 47262])]
    faible = [_livre(f"B{i}", b) for i, b in enumerate([62230, 95309, 150766, 156045, 204800])]
    assert depth_score(actif) > 0.7
    assert depth_score(faible) < 0.4
    assert depth_score([]) == 0.0                 # rayon vide -> pas de demande prouvée


def test_saturation_trio_compte_les_livres_qui_promettent_DEJA_le_trio():
    """Le différenciateur : 3 livres sur 4 promettent déjà mafia+captivite -> saturé."""
    niche = FictionNiche(sous_genre="dark_romance", tropes=["mafia", "captivite"],
                         rayon="kindle", query="q")
    livres = [_livre(f"A{i}", 2000) for i in range(4)]
    cl = {
        "A0": TropeClassification(asin="A0", taxonomy_version="fr_v1",
                                  tropes=["mafia", "captivite"]),
        "A1": TropeClassification(asin="A1", taxonomy_version="fr_v1",
                                  tropes=["mafia", "captivite", "vengeance"]),
        "A2": TropeClassification(asin="A2", taxonomy_version="fr_v1", tropes=["mafia"]),
        "A3": TropeClassification(asin="A3", taxonomy_version="fr_v1",
                                  tropes=["mariage_arrange"]),
    }
    # A0 et A1 couvrent le trio entier ; A2 partiellement ; A3 pas du tout
    s = saturation_trio(niche, livres, cl)
    assert 0.4 < s < 0.7
    assert saturation_trio(niche, livres, {}) == 0.0      # rien de classé -> rien de prouvé


def test_openness_recompense_un_rayon_peu_dote_en_avis():
    """Peu d'avis sur les leaders = places prenables ; beaucoup = mur installé."""
    ouvert = [_livre(f"A{i}", 5000, avis=15) for i in range(5)]
    ferme = [_livre(f"B{i}", 5000, avis=3000) for i in range(5)]
    assert openness_score(ouvert) > openness_score(ferme)


def test_series_share_et_price_band():
    livres = [_livre("A1", 2000, prix=2.99, serie=True), _livre("A2", 3000, prix=4.99),
              _livre("A3", 4000, prix=3.99, serie=True)]
    assert series_share(livres) == 2 / 3
    b = price_band(livres)
    assert b[0] == 2.99 and b[-1] == 4.99


def test_les_seuils_sont_exposes_et_documentes():
    """Repères marché, pas vérités : un produit vendu devra les exposer."""
    assert SEUILS["bsr_kindle_excellent"] < SEUILS["bsr_kindle_correct"]


# --- Helpers M5-2 : rayon "profond" calé sur le thriller psy mesuré en live (voir plan
# M5 « Faits mesurés » : BSR top 5 1960/2168/7422/14924/47262 -> rayon actif). Sert de
# base commune à build_report() : seule la classification change entre pépite et
# porteur_encombre, ce qui prouve que c'est bien saturation_trio qui arbitre.

def _niche():
    return FictionNiche(sous_genre="thriller_psychologique",
                        tropes=["manipulation_conjugale", "secret_de_famille"],
                        rayon="kindle", query="thriller psychologique manipulation")


def _shelf_profond():
    bsrs = [1960, 2168, 7422, 14924, 47262]
    livres = [_livre(f"P{i}", b, pos=i + 1) for i, b in enumerate(bsrs)]
    return FictionShelf(niche=_niche(), search_param="rh=n:205566731031", books=livres,
                        asins_demandes=5, n_echecs=0)


def _classif_trio_absent():
    """Les 5 livres du rayon sont classés mais AUCUN ne porte le trio visé (trope hors
    sujet) -> saturation basse malgré un rayon profond et ouvert."""
    return {f"P{i}": TropeClassification(asin=f"P{i}", taxonomy_version="fr_v1",
                                         tropes=["voisin_inquietant"])
           for i in range(5)}


def _classif_trio_partout():
    """Les 5 livres portent déjà le trio entier -> saturation haute : le même rayon,
    profond et ouvert, devient un sujet encombré plutôt qu'une pépite."""
    return {f"P{i}": TropeClassification(asin=f"P{i}", taxonomy_version="fr_v1",
                                         tropes=["manipulation_conjugale", "secret_de_famille"])
           for i in range(5)}


def _sig():
    return AutocompleteSignal(niche_query="thriller psychologique manipulation", score=0.5,
                              mesure=True, sous_genre_cherche=True)


def test_matrice_pepite_vs_porteur_encombre():
    """Même rayon profond et ouvert : c'est la saturation du trio — donc la LECTURE DES
    BLURBS — qui distingue une pépite d'un sujet déjà traité par tout le monde."""
    r1 = build_report(_niche(), _shelf_profond(), _classif_trio_absent(), _sig())
    r2 = build_report(_niche(), _shelf_profond(), _classif_trio_partout(), _sig())
    assert r1.demand_matrix == "pepite"
    assert r2.demand_matrix == "porteur_encombre"


def test_autocomplete_ne_gate_jamais_seul():
    """Spike M0 §V3 : un 0 sur un trio cosy est NORMAL (le rayon se navigue). Le verdict
    ne doit pas basculer sur ce seul signal."""
    muet = AutocompleteSignal(niche_query="q", score=0.0, mesure=True,
                              sous_genre_cherche=True)
    parlant = AutocompleteSignal(niche_query="q", score=1.0, mesure=True)
    a = build_report(_niche(), _shelf_profond(), _classif_trio_absent(), muet)
    b = build_report(_niche(), _shelf_profond(), _classif_trio_absent(), parlant)
    assert a.demand_matrix == b.demand_matrix == "pepite"


def test_sonde_non_mesuree_ne_compte_pas_comme_zero():
    """mesure=False : le rapport ne doit pas rendre une note (cf. dette M3 réglée)."""
    r = build_report(_niche(), _shelf_profond(), _classif_trio_absent(),
                     AutocompleteSignal(niche_query="q"))
    assert r.autocomplete_score is None


def test_sous_genre_fantome_est_une_alerte():
    """Le sous-genre lui-même n'est pas cherché -> le signalement remonte dans le verdict."""
    fantome = AutocompleteSignal(niche_query="q", score=0.0, mesure=True,
                                 sous_genre_cherche=False)
    r = build_report(_niche(), _shelf_profond(), _classif_trio_absent(), fantome)
    assert "sous-genre" in r.verdict.lower()


def test_rayon_ampute_est_signale_pas_lu_comme_desert():
    """FictionShelf.n_echecs > 0 : un rayon incomplet ne doit pas passer pour vide (§10)."""
    shelf = _shelf_profond().model_copy(update={"n_echecs": 9})
    r = build_report(_niche(), shelf, _classif_trio_absent(), _sig())
    assert "incomplet" in r.verdict.lower()
