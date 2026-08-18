"""`pages`, `dimensions`, `format_papier` — les trois champs sans lesquels le low-content
ne peut pas être scoré.

En non-fiction et en fiction, ces champs n'intéressent personne. En low-content ils SONT
le produit : la redevance KDP se calcule sur le nombre de pages (coût d'impression fixe
sous 110 pages, au-delà coût par page), et le format papier décide de la grille de coût.
Sans eux, `redevance_estimee` n'existe pas.

Fixture : `tests/fixtures/asin_fr_lowcontent.json` reproduit la structure exacte du payload
réel (`asin_fr.json`) avec les clés d'un broché KDP. Les CLÉS sont celles du plan ; les
VALEURS sont plausibles, pas capturées — à confirmer au premier run réel.
"""
import json
from pathlib import Path

import pytest

from fiction_books import parse_enriched_book

_FIX = Path(__file__).parent / "fixtures"


def _lowcontent() -> dict:
    return json.loads((_FIX / "asin_fr_lowcontent.json").read_text(encoding="utf-8"))


def test_le_nombre_de_pages_est_extrait_du_libelle_de_format():
    """amazon.fr écrit « Broché : 120 pages » — le nombre est dans la VALEUR, le format
    dans la CLÉ. Les deux se lisent d'un seul champ."""
    b = parse_enriched_book(_lowcontent())
    assert b.pages == 120


def test_le_format_papier_vient_du_libelle_amazon():
    b = parse_enriched_book(_lowcontent())
    assert b.format_papier == "Broché"


def test_les_dimensions_sont_gardees_telles_quelles():
    """Texte brut, jamais découpé en trois flottants : « 15.24 x 0.71 x 22.86 cm » est ce
    qu'Amazon affiche, et l'ordre des axes n'est garanti nulle part."""
    b = parse_enriched_book(_lowcontent())
    assert b.dimensions == "15.24 x 0.71 x 22.86 cm"


def test_l_editeur_indie_est_lu():
    """« Independently published » est LE marqueur d'un rayon attaquable en KDP."""
    b = parse_enriched_book(_lowcontent())
    assert b.publisher == "Independently published"


def test_un_livre_sans_ces_champs_les_laisse_a_None_jamais_a_zero():
    """Zéro page serait une mesure ; l'absence de la clé n'en est pas une (§5.10)."""
    b = parse_enriched_book(json.loads((_FIX / "asin_fr.json").read_text(encoding="utf-8")))
    assert b is not None
    assert b.pages is None and b.dimensions is None and b.format_papier is None


@pytest.mark.parametrize("valeur,attendu", [
    ("120 pages", 120),
    ("1 248 pages", 1248),        # espace fine des milliers, écriture française
    ("pages", None),              # libellé sans nombre : rien de mesuré
    ("", None),
])
def test_le_nombre_de_pages_supporte_les_ecritures_reelles(valeur, attendu):
    fix = _lowcontent()
    fix["items"][0]["product_information"][0]["body"]["Broché"] = valeur
    assert parse_enriched_book(fix).pages == attendu


def test_les_fixtures_fiction_ne_regressent_pas():
    """Les nouveaux champs sont optionnels : un payload fiction déjà couvert doit rendre
    exactement ce qu'il rendait."""
    b = parse_enriched_book(json.loads((_FIX / "asin_fr.json").read_text(encoding="utf-8")))
    assert b.publisher == "FLAMMARION" and b.bsr == 194
