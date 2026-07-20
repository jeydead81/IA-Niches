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
