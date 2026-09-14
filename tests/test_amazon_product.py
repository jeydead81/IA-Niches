import json
from pathlib import Path

from amazon_product import parse_bsr, fetch_bsr, _to_int

# Fragment INVENTÉ (forme reconstituée à la main, jamais capturée). Les données RÉELLES sont
# en fin de fichier : c'est sur elles que le parseur a été corrigé.
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


# Fragment réaliste avec un qualificatif parenthétique après le nom de la sous-catégorie
FIXTURE_PARENTHETICAL = (
    "<div id='detailBullets'>"
    "<span>Classement des meilleures ventes d'Amazon :</span> "
    "<span>23 372 en <a href='/gp/bestsellers/books'>Livres</a> "
    "(<a href='/gp/bestsellers/books'>Voir les 100 premiers en Livres</a>)</span>"
    "<ul><li><span>9 en <a href='/x'>Santé, Forme et Diététique</a> (Livres)</span></li></ul>"
    "</div>"
)


def test_parse_bsr_subcategory_with_parenthetical_qualifier_not_dropped():
    info = parse_bsr(FIXTURE_PARENTHETICAL)
    assert info is not None
    cats = {s["category"]: s["rank"] for s in info.subcategories}
    assert cats.get("Santé, Forme et Diététique") == 9


def test_parse_bsr_survives_bulky_dom_before_rank():
    noise = "<span class='a-tracking-noise'>x</span>" * 80  # ~2500+ chars de bruit DOM
    assert len(noise) > 2000
    fixture_bulky = (
        "<div id='detailBullets'>"
        "<span>Classement des meilleures ventes d'Amazon :</span>"
        f"{noise}"
        "<span>23 372 en <a href='/gp/bestsellers/books'>Livres</a></span>"
        "</div>"
    )
    info = parse_bsr(fixture_bulky)
    assert info is not None
    assert info.rank_livres == 23372


# ── R36 : données RÉELLES ───────────────────────────────────────────────────────
# `fixtures/bsr_scrape_fr_reel.json` : les 29 entrées `bsr:8f680c0a` du cache local, relevées
# sur amazon.fr par le canal scrape entre le 2026-07-15 et le 2026-08-06 (copie en lecture
# seule). Limite à connaître : ce n'est PAS le HTML des fiches, que le cache ne garde pas,
# mais `BsrInfo.raw` — le bloc « Classement » déjà DÉBALISÉ, tronqué à 300 caractères.
# `parse_bsr` débalise puis cherche ce même bloc : ce texte lui est une entrée valide, et il
# porte les deux bruits réels qui faisaient perdre des sous-catégories (« Commentaires
# client » et le CSS « .ask-product-docs-expander-content { … »). `rank_livres` vient du
# parse de la page ENTIÈRE au moment du relevé : c'est une référence indépendante.
_REELS = json.loads((Path(__file__).parent / "fixtures" / "bsr_scrape_fr_reel.json")
                    .read_text(encoding="utf-8"))
_PAR_ASIN = {e["asin"]: e for e in _REELS}


def _subs_reelles(asin: str) -> dict:
    return {s["category"]: s["rank"] for s in parse_bsr(_PAR_ASIN[asin]["raw"]).subcategories}


def test_la_fixture_reelle_porte_les_29_fiches():
    assert len(_REELS) == 29


def test_aucun_nom_de_sous_categorie_n_avale_le_bruit_de_page():
    for e in _REELS:
        for s in parse_bsr(e["raw"]).subcategories:
            assert "Commentaires" not in s["category"], e["asin"]
            assert ".ask" not in s["category"] and "{" not in s["category"], e["asin"]


def test_une_sous_categorie_suivie_des_commentaires_n_est_plus_perdue():
    assert _subs_reelles("B0GKPJBG5Q") == {"Grandes doctrines et courants philosophiques": 2}
    assert _subs_reelles("2271139775") == {"Pollution": 48, "Géologie": 53, "Limnologie": 116}


def test_un_nom_long_suivi_de_css_n_est_plus_perdu():
    """58 caractères : au-delà de l'ancien plafond de 50, la sous-catégorie disparaissait."""
    assert _subs_reelles("B0H6B15C9P") == {
        "Rénovation et modernisation à haute efficacité énergétique": 27}
    assert _subs_reelles("2017075221") == {"Vie et mort": 72, "Animaux de A à Z": 318,
                                          "Sport et activités extérieures": 809}


def test_les_75_sous_categories_des_29_fiches_sont_lues():
    """75 « N en <rayon> » hors rayon racine, comptés à part dans le texte. L'ancien parseur
    en lisait 64, dont 7 au nom pollué."""
    assert sum(len(parse_bsr(e["raw"]).subcategories) for e in _REELS) == 75


def test_le_rang_livres_reel_est_inchange():
    for e in _REELS:
        assert parse_bsr(e["raw"]).rank_livres == e["rank_livres"], e["asin"]
