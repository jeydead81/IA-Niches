"""La navigation latérale — Explorer / Analyses / Compte (2026-10-02).

Avant : tout vivait sur une seule page empilée — en-tête, pavé d'aide, onglets des trois
moteurs, historique, formulaires, résultats. L'historique des analyses s'intercalait entre
les onglets et le formulaire, et le compte n'existait que dans un menu déroulant posé sur
l'adresse e-mail.

Trois sections, pas plus (« Mes niches » viendra quand les favoris existeront en base — les
inventer dans l'interface ferait un bouton qui ne sauvegarde rien).

Ce que ce fichier tient : la structure, pas le style. Et une règle que la refonte ne doit
pas casser : les trois MOTEURS (non-fiction, fiction, low-content) restent des onglets À
L'INTÉRIEUR d'Explorer. En faire des entrées de navigation aurait suggéré trois produits.
"""
import re
from pathlib import Path

import pytest

_INDEX = Path(__file__).resolve().parent.parent / "web" / "index.html"


@pytest.fixture(scope="module")
def html() -> str:
    return _INDEX.read_text(encoding="utf-8")


@pytest.mark.parametrize("cle,libelle", [("explorer", "Explorer"), ("analyses", "Analyses"),
                                         ("compte", "Compte")])
def test_les_trois_entrees_existent(html, cle, libelle):
    assert f'data-vue="{cle}"' in html
    assert libelle in html


def test_mes_niches_n_est_PAS_propose_tant_que_les_favoris_n_existent_pas(html):
    """Un bouton qui ne sauvegarde rien est pire qu'un bouton absent."""
    assert 'data-vue="niches"' not in html


def test_chaque_entree_a_sa_section(html):
    for cle in ("explorer", "analyses", "compte"):
        assert f'id="vue-{cle}"' in html, f"section manquante : vue-{cle}"


def test_les_trois_moteurs_restent_des_onglets_dans_explorer(html):
    """Les séparer en entrées de navigation aurait suggéré trois produits distincts."""
    explorer = html[html.index('id="vue-explorer"'):html.index('id="vue-analyses"')]
    for onglet in ('id="tab-nf"', 'id="tab-fic"', 'id="tab-lc"'):
        assert onglet in explorer


def test_l_historique_a_quitte_le_flux_principal(html):
    """Il s'intercalait entre les onglets et le formulaire : une liste de courses posée
    au milieu de l'action principale."""
    analyses = html[html.index('id="vue-analyses"'):html.index('id="vue-compte"')]
    assert 'id="hist-liste"' in analyses


def test_un_seul_id_par_element(html):
    """Déplacer des blocs à la main duplique un id une fois sur deux, et `querySelector`
    rend alors silencieusement le mauvais élément."""
    ids = re.findall(r'\sid="([^"]+)"', html)
    doublons = {i for i in ids if ids.count(i) > 1}
    assert not doublons, f"ids dupliqués : {sorted(doublons)}"
