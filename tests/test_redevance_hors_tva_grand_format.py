"""Redevance KDP : le prix HORS TVA et le grand format — deux erreurs de la formule.

Le prix qu'on lit sur amazon.fr est celui que paie le client, TVA comprise. Le prix
catalogue que l'auteur saisit dans KDP est HORS TVA, et c'est sur lui que KDP calcule la
redevance ET applique le seuil de 9,99 €. La formule d'avant comparait le prix TTC au
seuil : un carnet affiché 10,49 € (8,74 € HT) passait pour « 60 % » et prenait +2 en
rentabilité. Elle ignorait aussi le grand format, soit 120 des 184 fiches lisibles du run 4.

Sources, toutes RÉELLES et datées :

- Tableau de bord KDP de Baptiste, 2026-09-15, page « Tarification, redevances et
  distribution », Amazon.fr. Deux livres, captures d'écran lues à l'œil :
  * broché 12,7 x 20,32 cm (5 x 8 po), encre noire, papier blanc, impression 2,42 € :
    12,49 € -> 13,18 € TVA FR incluse, 60 %, 5,08 € ; 10,49 € -> 11,07 €, 60 %, 3,88 € ;
    9,47 € -> 9,99 €, 50 %, 2,32 €.
  * broché 21,01 x 29,69 cm (8,27 x 11,69 po, A4), encre noire, papier crème,
    impression 2,48 € : 12,49 € -> 60 %, 5,01 € ; 10,49 € -> 60 %, 3,81 €.
  Ces écrans établissent que le prix saisi est HORS TVA (la TVA s'ajoute ensuite), que la
  redevance se calcule sur lui, et que le seuil aussi : à 9,47 € HT, le client paie 9,99 €
  TTC et KDP verse 50 %. Ces deux livres-là sont au taux réduit de 5,5 %.
- Pagination DÉDUITE, pas lue sur l'écran : 139 pages pour le 5 x 8 (seule valeur entière
  qui rend 5,08 / 3,88 / 2,32 au barème relevé) ; 110 pages ou moins pour l'A4 (2,48 € est
  le forfait de la bande courte ; 111 pages coûteraient déjà 2,53 €).
- Aide KDP G201834340 (fr_FR), HTML brut relu le 2026-09-15 : grand format en encre noire,
  2,48 € jusqu'à 110 pages, 0,75 € + 0,016 €/page au-delà ; couleur standard grand format,
  0,75 € + 0,035 €/page.
- Définition du grand format : « largeur supérieure à 155,5 mm OU hauteur supérieure à
  228,6 mm » sur G201834180 (fr_FR et en_US) et G201834340 (en_US). La version fr_FR de
  G201834340 écrit « et » : écartée, trois pages contre une. Le tableau officiel le
  confirme : 18,2 x 20,6 cm y figure en « Tailles de coupe grand format »
  (kdp.amazon.co.jp), avec une hauteur SOUS 22,86 cm.
- Aide KDP GPQL5W3J6WNRCZTV : carnets, planificateurs, agendas, livres de coloriage,
  cahiers d'activités au taux standard de 20 %. C'est le taux retenu pour le low-content ;
  il n'est observable sur aucune fiche.
- Dimensions : chaînes réelles des fiches du run 4 (`cache_calibration_run4_reel.json`),
  184 lisibles sur 185, toutes sous la forme « largeur x épaisseur x hauteur cm ».
"""
import json
from pathlib import Path

import pytest

from lowcontent_scoring import (charger_couts, format_coupe_dominant, format_coupe_livre,
                                prix_catalogue_ht, redevance_estimee, score_lowcontent)
from models import EnrichedBook, LowContentNiche, NicheValidation, SearchItem, SearchResult

_RUN4 = json.loads((Path(__file__).parent / "fixtures" / "cache_calibration_run4_reel.json")
                   .read_text(encoding="utf-8"))
_DIM = {e["asin"]: e["value"].get("dimensions") for e in _RUN4["book"]}


# ── Le prix catalogue KDP est hors TVA ─────────────────────────────────────────

@pytest.mark.parametrize("ttc,ht", [(13.18, 12.49), (11.07, 10.49), (9.99, 9.47)])
def test_le_prix_catalogue_se_deduit_du_prix_affiche_comme_dans_kdp(ttc, ht):
    """Les trois couples de l'écran KDP (TVA 5,5 %), lus à l'envers : du prix que voit le
    client au prix que l'auteur saisit."""
    assert prix_catalogue_ht(ttc, taux_tva=0.055) == ht


def test_le_low_content_est_au_taux_standard_de_20_pct():
    assert charger_couts()["tva"]["taux_lowcontent"] == 0.20
    assert prix_catalogue_ht(11.99) == 9.99
    assert prix_catalogue_ht(10.49) == 8.74


def test_sans_prix_affiche_il_n_y_a_pas_de_prix_catalogue():
    """None, jamais 0 : un prix inconnu n'est pas un prix nul (§5.10)."""
    assert prix_catalogue_ht(None) is None


# ── Le barème, confronté aux écrans KDP ────────────────────────────────────────

@pytest.mark.parametrize("prix_ht,affiche", [(12.49, 5.08), (10.49, 3.88), (9.47, 2.32)])
def test_la_redevance_du_5x8_tombe_au_centime_sur_l_ecran_kdp(prix_ht, affiche):
    """139 pages DÉDUITES (voir l'en-tête). 9,47 € HT = 9,99 € TTC et KDP verse 50 % : le
    seuil compare bien le prix HORS TVA. `redevance_estimee` prend le prix catalogue KDP."""
    assert redevance_estimee(prix_ht, 139) == pytest.approx(affiche, abs=0.005)


@pytest.mark.parametrize("prix_ht,affiche", [(12.49, 5.01), (10.49, 3.81)])
def test_la_redevance_de_l_a4_tombe_au_centime_au_bareme_grand_format(prix_ht, affiche):
    """100 pages : toute pagination de la bande courte donne le même forfait de 2,48 €. Au
    barème standard, la redevance affichée serait trop haute de 0,43 € par vente."""
    assert redevance_estimee(prix_ht, 100, format_coupe="grand") == pytest.approx(
        affiche, abs=0.005)
    assert redevance_estimee(prix_ht, 100) == pytest.approx(affiche + 0.43, abs=0.005)


def test_grand_format_au_dela_de_110_pages():
    assert redevance_estimee(14.99, 200, format_coupe="grand") == pytest.approx(
        0.60 * 14.99 - (0.75 + 200 * 0.016), abs=1e-3)


def test_grand_format_en_couleur_standard():
    assert redevance_estimee(14.99, 120, encre="couleur_standard",
                             format_coupe="grand") == pytest.approx(
        0.60 * 14.99 - (0.75 + 120 * 0.035), abs=1e-3)


def test_un_format_de_coupe_inconnu_leve():
    """Deviner une grille fabriquerait un chiffre présenté comme relevé."""
    with pytest.raises(ValueError):
        redevance_estimee(9.99, 120, format_coupe="poche")


# ── Le format de coupe, lu sur les dimensions réelles ──────────────────────────

@pytest.mark.parametrize("asin,attendu", [
    ("B0863S7ZXB", "standard"),   # 12,7 x 20,32 cm : 5 x 8 po
    ("B0CF4P1N9S", "standard"),   # 15,24 x 22,86 cm : 6 x 9 po, aucune borne DÉPASSÉE
    ("B09R3JZTL9", "grand"),      # 21,59 x 27,94 cm : 8,5 x 11 po
    ("2036074715", "grand"),      # 21,4 x 21,6 cm : carré, la largeur suffit (OU)
    ("B0H2923FGV", "grand"),      # 20,96 x 15,24 cm : paysage, la largeur suffit (OU)
])
def test_le_format_de_coupe_se_lit_sur_les_dimensions_reelles(asin, attendu):
    assert format_coupe_livre(_DIM[asin]) == attendu


def test_la_regle_est_OU_et_non_ET_sur_les_fiches_du_run_4():
    """120 grands formats sur 184 fiches lisibles avec « ou » ; « et » en compterait 102.
    Les 18 d'écart sont surtout des carrés de 21,59 cm."""
    lus = [format_coupe_livre(d) for d in _DIM.values()]
    assert sum(1 for f in lus if f is not None) == 184
    assert lus.count("grand") == 120


@pytest.mark.parametrize("brut", [None, "", "21.59 x 27.94 cm", "215.9 x 5.8 x 279.4 mm",
                                  "0.58 x 21.59 x 27.94 cm"])
def test_une_dimension_hors_de_la_forme_observee_n_est_pas_lue(brut):
    """FORMES INVENTÉES, déclarées : aucune n'a été observée sur les 184 fiches réelles.
    Deux axes seulement, une autre unité que le cm, ou une épaisseur qui n'est pas la plus
    petite valeur, au MILIEU : l'ordre des axes n'est plus garanti, et deviner un format
    ferait calculer la redevance sur une grille choisie au hasard."""
    assert format_coupe_livre(brut) is None


def _livre(asin, dims, prix=None, pages=None):
    return EnrichedBook(asin=asin, title="T", dimensions=dims, price=prix, pages=pages)


def test_le_format_dominant_est_la_majorite_stricte_des_fiches_lisibles():
    grand, std = _DIM["B09R3JZTL9"], _DIM["B0CF4P1N9S"]
    livres = [_livre("a", grand), _livre("b", grand), _livre("c", std), _livre("d", None)]
    assert format_coupe_dominant(livres) == ("grand", 2, 3)


def test_a_egalite_ou_sans_dimension_le_format_n_est_pas_determine():
    grand, std = _DIM["B09R3JZTL9"], _DIM["B0CF4P1N9S"]
    assert format_coupe_dominant([_livre("a", grand), _livre("b", std)]) == (None, 1, 2)
    assert format_coupe_dominant([_livre("a", None)]) == (None, 0, 0)
    assert format_coupe_dominant([]) == (None, 0, 0)


# ── Le score ───────────────────────────────────────────────────────────────────

def _niche() -> LowContentNiche:
    return LowContentNiche(niche="carnet", requete_amazon="carnet de suivi", rationale="r",
                           categorie="c", format_cle="journal_suivi", theme="t",
                           public="adulte", source="autocomplete")


def _v() -> NicheValidation:
    return NicheValidation(niche="carnet", requete_amazon="carnet de suivi", categorie="c",
                           demand_score=5, validated=True)


def _serp(prix: float) -> SearchResult:
    return SearchResult(keyword="q", sponsored=[], organic=[
        SearchItem(title=f"Carnet {i}", asin=f"A{i}", price=prix) for i in range(4)])


def test_un_rayon_a_10_49_ttc_est_sous_le_seuil_de_60_pct():
    """LE défaut : 10,49 € affichés passaient pour « au-dessus de 9,99 € ». Hors TVA à 20 %,
    c'est 8,74 € : KDP verse 50 %. Le prix médian affiché, donnée de marché, reste TTC."""
    s = score_lowcontent(_niche(), _v(), _serp(10.49), [], [])
    assert s.prix_median == 10.49
    assert s.prix_catalogue_ht == 8.74 and s.taux_tva_suppose == 0.20
    assert s.prix_sous_seuil_60pct is True


def test_le_bonus_prix_compare_le_prix_hors_tva():
    sous = score_lowcontent(_niche(), _v(), _serp(10.49), [], [])
    au_dessus = score_lowcontent(_niche(), _v(), _serp(11.99), [], [])
    assert au_dessus.prix_sous_seuil_60pct is False
    assert au_dessus.rentabilite - sous.rentabilite == pytest.approx(2.0)


def test_la_redevance_du_score_suit_le_prix_hors_tva_et_le_format_du_rayon():
    grand = _DIM["B09R3JZTL9"]
    livres = [_livre(f"A{i}", grand, 12.99, 100) for i in range(4)]
    s = score_lowcontent(_niche(), _v(), _serp(12.99), livres, [])
    assert (s.format_coupe, s.n_grand_format, s.n_format_lus) == ("grand", 4, 4)
    assert s.redevance_estimee == pytest.approx(
        redevance_estimee(prix_catalogue_ht(12.99), 100, format_coupe="grand"))
    # Ce que la formule d'avant affichait sur ce rayon : 1,73 € de trop par vente.
    assert redevance_estimee(12.99, 100) - s.redevance_estimee == pytest.approx(1.73, abs=0.01)


def test_sans_dimension_lisible_la_redevance_suppose_le_format_standard_et_le_dit():
    """Format inconnu : barème standard, et `format_coupe=None` pour que l'écran le dise.
    Ni une redevance absente (les pages et le prix sont là), ni un pire cas silencieux."""
    livres = [_livre(f"A{i}", None, 12.99, 100) for i in range(4)]
    s = score_lowcontent(_niche(), _v(), _serp(12.99), livres, [])
    assert s.format_coupe is None and s.n_format_lus == 0
    assert s.redevance_estimee == pytest.approx(
        redevance_estimee(prix_catalogue_ht(12.99), 100))
