"""Non-régression : un ebook ne doit JAMAIS produire un faux rang « Livres ».

Chaîne réelle relevée au spike M0 (fixture `fiction/v2_asin_payloads.json`) :
    « n°478 des titres gratuits dans la Boutique Kindle ( … )
      5 en Livres électroniques de fiction criminelle »
Le « 5 » est une SOUS-CATÉGORIE, pas le rayon Livres. Avant correctif, les deux
parseurs renvoyaient 5 — un rang flatteur et totalement faux, qui aurait fait
passer la niche pour une mine d'or."""
import json
from pathlib import Path

from amazon_product import parse_bsr
from search_providers import parse_asin_bsr

_FIX = json.loads(
    (Path(__file__).parent / "fixtures" / "fiction" / "v2_asin_payloads.json")
    .read_text(encoding="utf-8"))


def test_ebook_kindle_ne_produit_pas_de_faux_rang():
    assert parse_asin_bsr(_FIX["B0FF82S9MW"]) is None      # surtout PAS 5


def test_livres_papier_gardent_leur_vrai_rang():
    assert parse_asin_bsr(_FIX["1923235036"]).rank_livres == 1597
    assert parse_asin_bsr(_FIX["2749187052"]).rank_livres == 11611
    assert parse_asin_bsr(_FIX["B0CH23Z17T"]).rank_livres == 40133


def test_parseur_scrape_a_le_meme_garde_fou():
    ko = ("<div>Classement des meilleures ventes d'Amazon "
          "n°478 des titres gratuits dans la Boutique Kindle "
          "( Voir les 100 premiers en Boutique Kindle ) "
          "5 en Livres électroniques de fiction criminelle</div>")
    assert parse_bsr(ko) is None
    ok = ("<div>Classement des meilleures ventes d'Amazon 1 597 en Livres "
          "( Voir les 100 premiers en Livres ) 6 en Enquêtes et humour</div>")
    assert parse_bsr(ok).rank_livres == 1597
