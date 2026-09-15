"""`pages` et `dimensions` : les champs sans lesquels le low-content ne peut pas être scoré.

En non-fiction et en fiction, ils n'intéressent personne. En low-content ils SONT le
produit : la redevance KDP se calcule sur le nombre de pages (forfait sous 110 pages, coût
par page au-delà). Sans pagination, `redevance_estimee` n'existe pas.

Fixture : `tests/fixtures/fiction/v2_asin_payloads.json`, 8 captures RÉELLES amazon.fr du
2026-07-20. La pagination y est écrite sous « Nombre de pages de l'édition imprimée ».
Une fixture fabriquée l'écrivait « Broché : 120 pages » ; le parseur a été écrit pour
elle, a passé ses tests, et a rendu `pages=None` sur les 185 fiches payées du run 4.

`asin_fr.json` n'est PAS un payload complet : c'est un EXTRAIT (Éditeur, ISBN-13,
Classement) d'une capture brute locale non versionnée. Il ne prouve rien sur la pagination.
"""
import copy
import json
from pathlib import Path

import pytest

from fiction_books import parse_enriched_book
from lowcontent_scoring import (format_coupe_dominant, prix_catalogue_ht, redevance_estimee,
                                score_lowcontent)
from models import LowContentNiche, NicheValidation

_FIX = Path(__file__).parent / "fixtures"
_REEL = json.loads((_FIX / "fiction" / "v2_asin_payloads.json").read_text(encoding="utf-8"))
_CLE_PAGES = "Nombre de pages de l'édition imprimée"
_RACINE = Path(__file__).resolve().parent.parent

# Valeurs lues à l'œil dans les captures, clé par clé.
PAGES_REELLES = {
    "B0FF82S9MW": 140,      # ebook Kindle : porte la pagination de l'édition IMPRIMÉE
    "1923235036": 335,
    "2749187052": 208,
    "B0CH23Z17T": 337,
    "2253253103": 448,
    "2036073689": 224,
    "B0GN4G414V": 285,
}


def _body(payload: dict) -> dict:
    return payload["items"][0]["product_information"][0]["body"]


@pytest.mark.parametrize("asin,attendu", sorted(PAGES_REELLES.items()))
def test_le_nombre_de_pages_est_lu_sur_les_fiches_reelles(asin, attendu):
    assert parse_enriched_book(_REEL[asin]).pages == attendu


def test_l_ebook_rend_la_pagination_de_l_edition_imprimee():
    """Décision explicite : B0FF82S9MW est une fiche Kindle, mais Amazon y écrit la
    pagination de l'édition imprimée. Le low-content est PAPIER : c'est exactement la
    donnée dont la redevance a besoin. « Page Flip » ne doit pas être pris pour elle."""
    b = parse_enriched_book(_REEL["B0FF82S9MW"])
    assert b.pages == 140 and b.format_papier is None


def test_le_livre_audio_rend_une_fiche_sans_pagination():
    """B0FS7JQNJ6 (livre audio) : aucune puce de détail. Une fiche, jamais un plantage ;
    et des champs absents, jamais zéro (§5.10)."""
    b = parse_enriched_book(_REEL["B0FS7JQNJ6"])
    assert b is not None
    assert b.pages is None and b.dimensions is None and b.format_papier is None
    assert b.publisher is None and b.bsr is None


def test_une_fiche_lue_sans_la_cle_des_pages_les_laisse_a_None_jamais_a_zero():
    """Capture réelle dont on RETIRE la clé ici même : le reste du corps doit rester lu.
    Zéro page serait une mesure ; l'absence de la clé n'en est pas une (§5.10)."""
    p = copy.deepcopy(_REEL["1923235036"])
    del _body(p)[_CLE_PAGES]
    b = parse_enriched_book(p)
    assert b.pages is None
    assert b.publisher == "H.Y. Hanna" and b.bsr == 1597


@pytest.mark.parametrize("valeur,attendu", [
    ("335 pages", 335),
    ("1 248 pages", 1248),   # espace fine insécable des milliers (celle des BSR réels)
    ("1\xa0248 pages", 1248),     # espace insécable
    ("pages", None),              # libellé sans nombre : rien de mesuré
    ("", None),
])
def test_le_nombre_de_pages_supporte_les_ecritures_de_milliers(valeur, attendu):
    """Seule la VALEUR de la vraie clé change, sur une capture réelle. Les séparateurs
    sont ceux qu'amazon.fr emploie dans les classements des mêmes fiches."""
    p = copy.deepcopy(_REEL["1923235036"])
    _body(p)[_CLE_PAGES] = valeur
    assert parse_enriched_book(p).pages == attendu


def test_la_vraie_cle_prime_sur_une_cle_de_format():
    """FIXTURE PARTIELLEMENT INVENTÉE, déclarée : la clé « Broché » n'a JAMAIS été
    observée sur amazon.fr. Elle ne sert qu'à fixer l'ordre : la lecture sous une clé de
    format reste un simple repli, et ne doit jamais masquer la pagination réelle."""
    p = copy.deepcopy(_REEL["1923235036"])
    _body(p)["Broché"] = "12 pages"
    assert parse_enriched_book(p).pages == 335


def test_les_dimensions_sont_gardees_telles_quelles():
    """Texte brut, jamais découpé en trois flottants : l'ordre des axes n'est garanti
    nulle part. Et l'épaisseur ne sert PAS à estimer les pages (écart x2,1 mesuré)."""
    assert parse_enriched_book(_REEL["1923235036"]).dimensions == "12.85 x 2.01 x 19.84 cm"


@pytest.mark.parametrize("asin", sorted(_REEL))
def test_format_papier_n_est_jamais_rempli_sur_les_fiches_reelles(asin):
    """Aucune capture ne porte de clé de format : le champ reste à None, sans source
    inventée (ni titre, ni dimensions)."""
    b = parse_enriched_book(_REEL[asin])
    assert b is not None and b.format_papier is None


def test_format_papier_n_est_consomme_par_aucun_module():
    """Cliquet : le jour où un module s'en sert, il faudra d'abord lui trouver une source
    réelle. La redevance ne dépend que du prix, des pages et de l'encre."""
    autorises = {"models.py", "fiction_books.py"}
    fautifs = [str(p.relative_to(_RACINE))
               for dossier in ("01-scripts", "web")
               for p in (_RACINE / dossier).rglob("*")
               if p.is_file() and p.suffix in {".py", ".html", ".js"}
               and p.name not in autorises
               and "format_papier" in p.read_text(encoding="utf-8", errors="ignore")]
    assert not fautifs


def _niche() -> LowContentNiche:
    return LowContentNiche(niche="carnet", requete_amazon="carnet", rationale="r",
                           categorie="c", format_cle="journal_suivi", theme="t",
                           public="adulte", source="autocomplete")


@pytest.mark.parametrize("asin", sorted(PAGES_REELLES))
def test_la_redevance_existe_de_bout_en_bout_sur_les_fiches_reelles(asin):
    """Capture réelle -> parseur -> scoring, sans rien remplacer entre les deux. Prix
    fixé à 12,99 € (la SERP est absente : le prix vient des fiches). C'est ce chemin qui
    rendait `redevance_estimee=None` sur les 31 niches du run 4.

    Attendu MODIFIÉ le 2026-09-15, déclaré : le prix d'une fiche est TTC, la redevance se
    calcule sur le prix catalogue HORS TVA, au format de coupe lu sur les dimensions
    (`test_redevance_hors_tva_grand_format.py`)."""
    b = parse_enriched_book(_REEL[asin]).model_copy(update={"price": 12.99})
    v = NicheValidation(niche="carnet", requete_amazon="carnet", categorie="c",
                        demand_score=5, validated=True)
    s = score_lowcontent(_niche(), v, None, [b], [])
    assert s.redevance_estimee is not None
    fmt = format_coupe_dominant([b])[0] or "standard"
    assert s.redevance_estimee == pytest.approx(
        redevance_estimee(prix_catalogue_ht(12.99), PAGES_REELLES[asin], format_coupe=fmt))


def test_la_redevance_de_l_ebook_de_140_pages_vaut_le_bareme_courant():
    """Valeur calculée au barème de `data/kdp_print_costs.json` en vigueur le 2026-09-14."""
    b = parse_enriched_book(_REEL["B0FF82S9MW"])
    assert redevance_estimee(12.99, b.pages) == pytest.approx(5.364, abs=1e-3)


def test_les_fixtures_fiction_ne_regressent_pas():
    """Extrait `asin_fr.json` : éditeur et BSR, les seuls champs qu'il porte."""
    b = parse_enriched_book(json.loads((_FIX / "asin_fr.json").read_text(encoding="utf-8")))
    assert b.publisher == "FLAMMARION" and b.bsr == 194
