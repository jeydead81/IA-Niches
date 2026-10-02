"""Le nouvel écran d'accueil — refonte UX décidée par Baptiste le 2026-10-02.

L'ancien accueil ouvrait sur un pavé permanent de trois paragraphes (« Comment lire ces
résultats ? »), puis un formulaire au vocabulaire du moteur : « Graine », « Profondeur
d'analyse », « Lancer le scout ». Un auteur KDP ne parle pas comme ça, et un bloc de texte
ouvert en permanence au-dessus du champ principal repousse l'action sous la ligne de
flottaison.

Ce que ce fichier tient — et PAS le style, qui bougera encore :
1. le pavé permanent a disparu (l'aide contextuelle par onglet existe, elle, depuis §2.9) ;
2. le vocabulaire est celui de l'auteur, pas du moteur ;
3. l'action principale est nommée par son résultat, pas par l'outil ;
4. et surtout : AUCUN écran ne promet un classement par « potentiel ». Mesuré sur 95 niches
   et validé sur un lot neuf, le score sépare un rayon mort d'un rayon vivant et ne
   départage pas une bonne niche d'une mauvaise. Le mot qui a le droit d'exister est
   « vitalité ».
"""
import re
from pathlib import Path

import pytest

_INDEX = Path(__file__).resolve().parent.parent / "web" / "index.html"


@pytest.fixture(scope="module")
def html() -> str:
    return _INDEX.read_text(encoding="utf-8")


def test_le_pave_permanent_a_disparu(html):
    assert "Comment lire ces résultats" not in html
    assert 'id="help-panel"' not in html


def test_le_vocabulaire_est_celui_de_l_auteur(html):
    for ancien in (">Graine<", "Profondeur d'analyse", ">Lancer le scout<"):
        assert ancien not in html, f"vocabulaire du moteur encore à l'écran : {ancien}"
    assert "thématique" in html.lower()
    assert "Niveau d'analyse" in html


def test_l_accueil_annonce_le_resultat_attendu(html):
    assert "Trouvez votre prochaine niche KDP" in html
    assert "Trouver les niches" in html


def test_des_thematiques_cliquables_amorcent_la_recherche(html):
    """Un champ vide devant un auteur qui découvre l'outil est un mur. Les suggestions ne
    sont pas décoratives : elles montrent la forme attendue d'une entrée."""
    assert 'class="suggestions"' in html
    assert re.search(r'data-theme="[^"]+"', html)


def test_aucun_ecran_ne_promet_un_classement_par_POTENTIEL(html):
    """La mesure autorise « vitalité », pas « potentiel » : le score ne classe pas la
    qualité (AUC 0,43 sur le lot de validation, intervalle à cheval sur le hasard)."""
    assert "potentiel élevé" not in html.lower()
    assert "trier par potentiel" not in html.lower()
