from amazon_product import parse_bsr, fetch_bsr, _to_int

# Fragment réaliste (HTML + espaces fines insécables ` ` comme sur amazon.fr)
FIXTURE = (
    "<div id='detailBullets'>"
    "<span>Classement des meilleures ventes d'Amazon :</span> "
    "<span>23 372 en <a href='/gp/bestsellers/books'>Livres</a> "
    "(<a href='/gp/bestsellers/books'>Voir les 100 premiers en Livres</a>)</span>"
    "<ul><li><span>13 en <a href='/x'>Sciences infirmières</a></span></li>"
    "<li><span>180 en <a href='/y'>Manuels de médecine</a></span></li></ul>"
    "</div>"
)


def test_to_int_handles_thin_spaces():
    assert _to_int("23 372") == 23372
    assert _to_int("1 346 172") == 1346172
    assert _to_int("") is None


def test_parse_bsr_extracts_main_rank():
    info = parse_bsr(FIXTURE)
    assert info is not None
    assert info.rank_livres == 23372


def test_parse_bsr_extracts_subcategories():
    info = parse_bsr(FIXTURE)
    cats = {s["category"]: s["rank"] for s in info.subcategories}
    assert cats.get("Sciences infirmières") == 13
    # la catégorie racine "Livres" et le bruit "Voir les 100..." ne sont PAS des sous-catégories
    assert "Livres" not in cats


def test_parse_bsr_none_when_absent():
    assert parse_bsr("<div>aucun classement ici</div>") is None


def test_fetch_bsr_sets_asin_and_uses_injected_html():
    info = fetch_bsr("2266283340", fetch_html=lambda asin: FIXTURE)
    assert info.asin == "2266283340"
    assert info.rank_livres == 23372
