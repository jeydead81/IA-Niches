from build_validation_set import build_set
from models import EnrichedBook, FictionNiche, FictionShelf, TropeClassification


def _niche(query):
    # sous_genre doit être une clé RÉELLE de fiction_taxonomy : export_validation (M4-3)
    # y appelle valid_keys() pour la feuille "Clés autorisées", qui lève KeyError sur une
    # clé inventée. Le plan proposait "cosy mystery a"/"b" comme simples libellés de niche ;
    # adapté ici en deux TRIOS distincts (query différente) du même sous-genre réel — ce que
    # produit d'ailleurs le CLI en usage normal (plusieurs trios pour UN sous-genre).
    return FictionNiche(sous_genre="cosy_mystery", query=query)


def test_assemble_les_rayons_et_deduplique(tmp_path):
    livres = [EnrichedBook(asin="A1", title="T", blurb="b"),
              EnrichedBook(asin="A2", title="T", blurb="b")]

    def faux_shelf(niche, **kw):
        return FictionShelf(niche=niche, search_param="x", books=livres,
                            asins_demandes=2)

    out = tmp_path / "v.xlsx"
    n = build_set([_niche("cosy mystery a"), _niche("cosy mystery b")], out,
                  fetch_shelf=faux_shelf,
                  classify=lambda bks, sg, **kw: [
                      TropeClassification(asin=b.asin, taxonomy_version="fr_v1") for b in bks])
    assert n == 2                 # A1/A2 vus deux fois -> comptés une seule
    assert out.exists()
