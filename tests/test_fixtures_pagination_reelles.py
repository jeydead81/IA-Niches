"""Cliquet : aucune assertion sur la pagination ne repose sur une fiche INVENTÉE.

Le parseur a cherché le nombre de pages sous une clé de format (« Broché : 120 pages »)
parce qu'une fixture fabriquée l'écrivait ainsi ; ses tests passaient au vert. Les vraies
fiches amazon.fr écrivent « Nombre de pages de l'édition imprimée », et le moteur
low-content a rendu `pages=None` sur 185 fiches payées — donc aucune redevance, donc une
calibration indécidable (run 4, 0,7208 $). Un test qui valide un parseur contre une forme
que personne n'a observée ne prouve que la cohérence de son auteur avec lui-même.

Seules les captures RÉELLES déclarées ici peuvent fonder une assertion `.pages` sur une
sortie de `parse_enriched_book`. Les fiches `EnrichedBook(pages=…)` construites à la main
pour le scoring pur ne sont PAS visées : elles ne prétendent rien sur le format d'Amazon.
"""
import re
from pathlib import Path

_TESTS = Path(__file__).parent

# Captures réelles versionnées. `asin_fr.json` est un EXTRAIT (Éditeur, ISBN-13,
# Classement) : il ne porte aucune pagination et ne peut donc rien prouver sur elle.
CAPTURES_REELLES = {"v2_asin_payloads.json", "asin_fr.json"}
# Nom recomposé : écrit en clair, ce fichier se dénoncerait lui-même.
_FIXTURE_INVENTEE = "asin_fr_" + "lowcontent.json"
_NOMS_DE_FIXTURES = {p.name for p in (_TESTS / "fixtures").rglob("*.json")}


def _fichiers_de_test():
    moi = Path(__file__).name
    return [p for p in sorted(_TESTS.glob("test_*.py")) if p.name != moi]


def test_aucun_test_ne_charge_la_fixture_de_pagination_inventee():
    fautifs = [p.name for p in _fichiers_de_test()
               if _FIXTURE_INVENTEE in p.read_text(encoding="utf-8")]
    assert not fautifs, f"fixture inventée encore chargée par : {fautifs}"


def test_une_assertion_de_pagination_sur_le_parseur_ne_lit_que_des_captures_reelles():
    fautifs = {}
    for p in _fichiers_de_test():
        src = p.read_text(encoding="utf-8")
        if "parse_enriched_book" not in src or not re.search(r"\.pages\b", src):
            continue
        # Seuls les fichiers de `tests/fixtures/` sont des fiches : un barème de `data/`
        # nommé dans un docstring n'en est pas une.
        noms = set(re.findall(r"[\w\-]+\.json", src))
        hors_liste = (noms & (_NOMS_DE_FIXTURES | {_FIXTURE_INVENTEE})) - CAPTURES_REELLES
        if hors_liste:
            fautifs[p.name] = sorted(hors_liste)
    assert not fautifs, f"pagination assertée sur des fixtures non déclarées réelles : {fautifs}"
