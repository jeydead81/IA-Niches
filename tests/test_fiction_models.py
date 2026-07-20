from models import FictionNiche, EnrichedBook, TropeClassification, FictionNicheReport


def test_fiction_niche_defauts():
    n = FictionNiche(sous_genre="cosy_mystery", tropes=["animal_compagnon"], query="cosy mystery chat")
    assert n.marketplace == "fr" and n.rayon == "kindle" and n.decor is None


def test_enriched_book_rayon_et_gratuit():
    b = EnrichedBook(asin="B1", title="T", bsr=20, bsr_rayon="Boutique Kindle",
                     bsr_gratuit=False, serp_position=1)
    assert b.est_payant_dans("Boutique Kindle") is True
    b2 = EnrichedBook(asin="B2", title="T", bsr=73, bsr_rayon="Boutique Kindle",
                      bsr_gratuit=True, serp_position=2)
    assert b2.est_payant_dans("Boutique Kindle") is False
    b3 = EnrichedBook(asin="B3", title="T", bsr=1597, bsr_rayon="Livres", serp_position=3)
    assert b3.est_payant_dans("Boutique Kindle") is False


def test_serie_structuree():
    b = EnrichedBook(asin="B1", title="T", serp_position=1, serie_tome=5, serie_total=6)
    assert b.est_serie is True
    assert EnrichedBook(asin="B2", title="T", serp_position=2, series_hint=True).est_serie is True
    assert EnrichedBook(asin="B3", title="T", serp_position=3).est_serie is False


def test_classification_et_report():
    c = TropeClassification(asin="B1", taxonomy_version="fr_v1", tropes=["mafia"],
                            decor="campus", other=["x"], confidence=0.8)
    r = FictionNicheReport(
        niche=FictionNiche(sous_genre="dark_romance", tropes=["mafia"], query="dark romance mafia"),
        books=[], classifications=[c], depth_score=0.4, openness_score=0.7,
        saturation_trio=0.2, autocomplete_score=0.5, demand_matrix="ouvert_valide")
    assert r.demand_matrix == "ouvert_valide" and r.classifications[0].asin == "B1"
