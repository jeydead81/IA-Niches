import json
from pathlib import Path

from fiction_books import parse_enriched_book, _series_hint_from_title
from models import EnrichedBook

_FIC = Path(__file__).parent / "fixtures" / "fiction"
_PRINT = json.loads((_FIC / "v2_asin_payloads.json").read_text(encoding="utf-8"))
_KINDLE = json.loads((_FIC / "m1_kindle_nodes.json").read_text(encoding="utf-8"))


def test_parse_livre_papier_reel():
    b = parse_enriched_book(_PRINT["1923235036"], serp_position=8)
    assert isinstance(b, EnrichedBook)
    assert b.asin == "1923235036"
    assert b.title.startswith("Les Racines du Mal")
    assert b.author == "H.Y. Hanna"
    assert b.bsr == 1597 and b.bsr_rayon == "Livres" and b.bsr_gratuit is False
    assert b.serie_tome == 5 and b.serie_total == 6 and b.est_serie is True
    assert b.publisher and b.langue and b.publication_date
    assert b.serp_position == 8


def test_parse_ebook_gratuit_marque_mais_conserve():
    b = parse_enriched_book(_PRINT["B0FF82S9MW"], serp_position=1)
    assert b.bsr == 478 and b.bsr_rayon == "Boutique Kindle"
    assert b.bsr_gratuit is True                  # marqué ici, écarté au scoring (M5)
    assert b.est_payant_dans("Boutique Kindle") is False


def test_parse_sans_bsr_ne_plante_pas():
    b = parse_enriched_book(_PRINT["B0FS7JQNJ6"], serp_position=3)
    assert b is not None and b.bsr is None and b.bsr_rayon is None


def test_series_hint_heuristique():
    assert _series_hint_from_title("Meurtres et cupcakes - tome 15") is True
    assert _series_hint_from_title("Black Sword, T2 : la suite") is True
    assert _series_hint_from_title("Les Enquêtes d'Etsy, Livre 3") is True
    assert _series_hint_from_title("Un meurtre absolument splendide") is False


def test_parse_payload_vide():
    assert parse_enriched_book({}, serp_position=0) is None


def test_parse_livre_1_sur_1_nest_pas_une_serie():
    # B0GN4G414V porte la clé « Livre 1 sur 1 » : Amazon balise ainsi un tome UNIQUE
    # (collection d'un seul titre), pas une série. serie_total=1 ne doit pas déclencher
    # est_serie.
    b = parse_enriched_book(_PRINT["B0GN4G414V"], serp_position=2)
    assert b.serie_tome == 1 and b.serie_total == 1
    assert b.est_serie is False


def test_parse_price_from_chaine_fr_ne_plante_pas():
    # price_from="13,70" (virgule FR) vu en vrai sur des payloads DataForSEO -> float("13,70")
    # lève ValueError. Le docstring promet "None si inexploitable", pas un crash.
    payload = {
        "asin": "X1",
        "items": [{"type": "amazon_product_info", "data_asin": "X1", "title": "Titre",
                   "price_from": "13,70", "product_information": []}],
    }
    b = parse_enriched_book(payload)
    assert b is not None and b.price is None


def test_parse_langue_type_inattendu_ne_plante_pas():
    # Amazon peut rendre un champ "texte" sous une forme inattendue (liste au lieu de str) ;
    # on force str(...) plutôt que de laisser pydantic lever.
    payload = {
        "asin": "X2",
        "items": [{"type": "amazon_product_info", "data_asin": "X2", "title": "Titre",
                   "product_information": [
                       {"body": {"Langue": ["Français", "Anglais"]}}]}],
    }
    b = parse_enriched_book(payload)
    assert b is not None
    assert b.langue == str(["Français", "Anglais"])


def test_parse_product_information_dict_au_lieu_de_liste_ne_plante_pas():
    # product_information est censé être une liste de sections ; un dict isolé (forme
    # atypique observée) ne doit pas faire planter le parseur.
    payload = {
        "asin": "X3",
        "items": [{"type": "amazon_product_info", "data_asin": "X3", "title": "Titre",
                   "product_information": {"body": {"Langue": "Français"}}}],
    }
    b = parse_enriched_book(payload)
    assert b is not None and b.langue is None


def test_bsr_subcats_une_seule_sous_categorie():
    # 1923235036 : "1 597 en Livres ( Voir les 100 premiers en Livres )  6 en Enquêtes et humour"
    b = parse_enriched_book(_PRINT["1923235036"])
    assert b.bsr_subcats == [{"rang": 6, "categorie": "Enquêtes et humour"}]


def test_bsr_subcats_plusieurs_sous_categories_separees_par_saut_de_ligne():
    # B0CH23Z17T : "... 280 en Enquêtes et humour\n 551 en Femmes détectives"
    b = parse_enriched_book(_PRINT["B0CH23Z17T"])
    assert b.bsr_subcats == [{"rang": 280, "categorie": "Enquêtes et humour"},
                             {"rang": 551, "categorie": "Femmes détectives"}]


def test_bsr_subcats_conserve_le_qualificatif_entre_parentheses():
    # 2036073689 : "... 3 955 en Jeux (Livres)" — le "(Livres)" fait partie du libellé
    # Amazon de la sous-catégorie (disambiguïsation papier/Kindle), pas du bruit à couper.
    b = parse_enriched_book(_PRINT["2036073689"])
    assert b.bsr_subcats == [{"rang": 3955, "categorie": "Jeux (Livres)"}]


def test_bsr_subcats_trois_niveaux_avec_qualificatif_mixte():
    # 2253253103 : trois sous-catégories, dont une avec le qualificatif "(Livres)".
    b = parse_enriched_book(_PRINT["2253253103"])
    assert b.bsr_subcats == [
        {"rang": 718, "categorie": "Crime et enquête"},
        {"rang": 1420, "categorie": "Romans policiers (Livres)"},
        {"rang": 5905, "categorie": "Romans et littérature"},
    ]


def test_bsr_subcats_vide_quand_pas_de_bsr():
    b = parse_enriched_book(_PRINT["B0FS7JQNJ6"])
    assert b.bsr_subcats == []


def test_parse_bsr_reconnait_aussi_la_cle_anglaise_best_sellers_rank():
    # _BSR_KEY était une chaîne unique ("meilleures ventes") ; parse_asin_bsr (search_providers)
    # accepte déjà les deux formes FR/EN, fiction_books.py devait suivre.
    payload = {
        "asin": "X4",
        "items": [{"type": "amazon_product_info", "data_asin": "X4", "title": "Titre",
                   "product_information": [{"body": {
                       "Best Sellers Rank": "1 234 en Livres ( Voir les 100 premiers en Livres )  9 en Romans"}}]}],
    }
    b = parse_enriched_book(payload)
    assert b.bsr == 1234 and b.bsr_rayon == "Livres"
    assert b.bsr_subcats == [{"rang": 9, "categorie": "Romans"}]


def test_series_hint_notation_t_point_la_plus_courante_sur_amazon_fr():
    # « t. 1 » (avec point) est la notation la plus fréquente sur amazon.fr ; l'ancienne
    # regex (\bvol\.?\s*\d+|\bt\s*\d+) la ratait car elle exigeait "vol" ou "t" collé aux
    # digits sans jamais matcher le point de « t. 1 » explicitement testé ici.
    assert _series_hint_from_title("t. 1") is True
    assert _series_hint_from_title("T2") is True
    assert _series_hint_from_title("tome 15") is True
    assert _series_hint_from_title("vol. 2") is True


def test_series_hint_faux_positifs_vol_sans_point():
    # « vol » sans point est un mot courant en polar (numéro de vol d'avion) : ne doit
    # jamais déclencher la détection de série.
    assert _series_hint_from_title("Vol 714 pour Sydney") is False
    assert _series_hint_from_title("Le Vol 800 n'existe pas") is False
    assert _series_hint_from_title("Le Livre des morts") is False
    assert _series_hint_from_title("Un meurtre absolument splendide") is False


def test_series_hint_fixtures_live_non_regression():
    """Balaie les titres réels des fixtures live (SERP v1a + v1b) : la regex doit détecter
    au moins 30 séries sur ~80 titres uniques (l'ancienne regex n'en trouvait que 16)."""
    titres = set()
    for name in ("v1a_serp_cosy_mystery.json", "v1b_serp_node.json"):
        d = json.loads((_FIC / name).read_text(encoding="utf-8"))
        for it in d.get("organic", []) + d.get("sponsored", []):
            t = it.get("title")
            if t:
                titres.add(t)
    hits = [t for t in titres if _series_hint_from_title(t)]
    assert len(titres) >= 70
    assert len(hits) >= 30
