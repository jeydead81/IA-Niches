"""Trois finitions de la revue d'interface du 2026-08-18.

Aucune n'est un bug de calcul : ce sont des choses vraies qui n'atteignent pas l'écran, ou
qui l'atteignent mal. C'est le même genre de défaut que les trois endpoints inatteignables
(§5.26) — du travail fait, payé, et invisible.
"""
import re
from pathlib import Path

import pytest

_INDEX = Path(__file__).resolve().parent.parent / "web" / "index.html"


@pytest.fixture(scope="module")
def html() -> str:
    return _INDEX.read_text(encoding="utf-8")


# ── 1. L'historique fiction était écrit et jamais lu ───────────────────────────

def test_la_carte_fiction_lit_son_historique(html):
    """`_consigner_fiction` écrit dans `history.db` à CHAQUE run fiction depuis le début.
    Mais `renderFic` n'avait ni emplacement ni appel : l'auteur accumulait un historique
    qu'aucun écran ne lui montrait. La seule fonction capable de répondre à « est-ce que ça
    bouge ? » était aveugle sur la moitié du produit."""
    i = html.index("function renderFic")
    j = html.index("formFic.addEventListener", i)
    corps = html[i:j]
    assert "histslot" in corps, "la carte fiction n'a pas d'emplacement d'historique"
    assert "loadHistorique" in corps, "la carte fiction ne charge jamais son historique"


def test_l_historique_fiction_se_charge_a_l_ouverture_pas_au_rendu(html):
    """Même discipline qu'en non-fiction : interroger l'historique de dix trios que
    l'utilisateur ne dépliera jamais, c'est dix requêtes pour rien."""
    i = html.index("function renderFic")
    j = html.index("formFic.addEventListener", i)
    corps = html[i:j]
    assert "addEventListener" in corps and "histCharge" in corps


# ── 2. Aucun point de rupture responsive ───────────────────────────────────────

def test_il_existe_un_point_de_rupture(html):
    """La seule media query du fichier était `prefers-reduced-motion`. Sur 375 px, le
    tableau fait 936 px : il scrolle dans son conteneur, donc rien ne casse — mais lire
    sept colonnes en balayant n'est pas une lecture, c'est un déchiffrage."""
    largeurs = re.findall(r"@media\s*\([^)]*width[^)]*\)", html)
    assert largeurs, "aucune media query de largeur"


def test_le_tableau_allege_ses_colonnes_secondaires_sur_petit_ecran(html):
    """Score, niche et BSR suffisent à trier sur mobile. Demande, pénétration et
    sponsorisés restent lisibles dans la ligne dépliée — on les masque, on ne les perd
    pas."""
    m = re.search(r"@media\s*\([^)]*max-width[^)]*\)\s*\{(.*?)\n  \}", html, re.S)
    assert m, "pas de bloc max-width exploitable"
    assert "display:none" in m.group(1).replace(" ", "")


def test_le_formulaire_passe_en_colonne_sur_petit_ecran(html):
    m = re.search(r"@media\s*\([^)]*max-width[^)]*\)\s*\{(.*?)\n  \}", html, re.S)
    bloc = m.group(1).replace(" ", "")
    assert "flex-direction:column" in bloc or "grid-template-columns:1fr" in bloc


# ── 3. Contrastes à la décimale près ───────────────────────────────────────────

def _luminance(hexa: str) -> float:
    hexa = hexa.lstrip("#")
    canaux = [int(hexa[i:i + 2], 16) / 255 for i in (0, 2, 4)]
    lin = [c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4 for c in canaux]
    return 0.2126 * lin[0] + 0.7152 * lin[1] + 0.0722 * lin[2]


def _contraste(a: str, b: str) -> float:
    la, lb = _luminance(a), _luminance(b)
    return (max(la, lb) + 0.05) / (min(la, lb) + 0.05)


def test_le_texte_attenue_a_de_la_marge_sous_le_seuil_AA(html):
    """Tout le texte secondaire était calé entre 4,55 et 4,76 pour un seuil AA à 4,5, sur
    des tailles de 11 à 12,5 px. Ça passe, mais la marge est nulle : un gris légèrement
    éclairci, un fond de carte modifié, et plusieurs valeurs basculent sous le seuil sans
    que rien ne le signale. On vise 5,5 pour avoir de quoi bouger."""
    m = re.search(r"--text-muted:\s*(#[0-9A-Fa-f]{6})", html)
    assert m, "--text-muted introuvable"
    c = _contraste(m.group(1), "#FFFFFF")
    assert c >= 5.5, f"contraste {c:.2f} sur blanc — trop juste sous le seuil AA de 4,5"


def test_le_texte_attenue_reste_ATTENUE(html):
    """L'assombrir ne doit pas le rendre indiscernable du texte principal : la hiérarchie
    visuelle repose sur cet écart."""
    mu = re.search(r"--text-muted:\s*(#[0-9A-Fa-f]{6})", html).group(1)
    txt = re.search(r"--text:\s*(#[0-9A-Fa-f]{6})", html).group(1)
    assert _luminance(mu) > _luminance(txt) * 1.5


# ── 4. Le troisième onglet a été ajouté sans son aide ni sa reprise ────────────

def test_l_onglet_low_content_a_SA_PROPRE_aide(html):
    """`AIDE` ne portait que `nf` et `fic`. L'onglet low-content recevait donc
    silencieusement le tutoriel de la NON-FICTION — et c'est le moteur qui a le plus de
    pièges de lecture : `n_variantes_quasi_identiques` s'y lit à l'envers, « normé » n'y
    veut pas dire « difficile », une part indie non mesurée n'y est pas une part nulle.

    Afficher le mauvais tutoriel est pire que n'en afficher aucun : l'auteur croit avoir
    lu les pièges du rayon qu'il regarde."""
    i = html.index("const AIDE")
    j = html.index("function ouvrir(", i)
    bloc = html[i:j]
    assert "lc:" in bloc, "AIDE n'a pas d'entrée pour l'onglet low-content"
    # C'est le tableau `pieges:` qui porte la section, pas son titre — celui-ci n'est écrit
    # qu'une fois, dans le gabarit de rendu (`:2113`). Compter le titre reviendrait à
    # vérifier la présence d'une chaîne au lieu de la structure qui la remplit.
    assert bloc.count("pieges:") == 3, \
        f"{bloc.count('pieges:')} tableau(x) de pièges pour trois onglets"


def test_l_aide_low_content_porte_SES_pieges_a_lui(html):
    """Les deux qui font publier à côté : l'échelle inversée des variantes, et « normé »
    qui ne veut pas dire « difficile »."""
    i = html.index("const AIDE")
    j = html.index("function ouvrir(", i)
    bloc = html[i:j]
    lc = bloc[bloc.index("lc:"):]
    assert "variantes" in lc.lower()
    assert "norm" in lc.lower()


def test_ongletActif_connait_les_TROIS_onglets(html):
    """`return (t && t.classList.contains('active')) ? 'fic' : 'nf'` est exactement la
    cascade booléenne à deux issues que le passage à trois onglets rend fausse : sur
    `#tab-lc` elle rend `'nf'`, sans erreur et sans rien signaler."""
    i = html.index("function ongletActif")
    corps = html[i:i + 700]
    assert "#tab-lc" in corps, "ongletActif ne regarde jamais l'onglet low-content"


def test_la_reprise_low_content_attend_la_SESSION(html):
    """`reprendreTravail(VUE_NF)` et `(VUE_FIC)` sont appelés dans `entrer()`, donc après
    une session confirmée. `(VUE_LC)` était appelé au niveau module, au chargement du
    script : il partait avant l'authentification, se prenait un 401 et ne reprenait rien.

    Un run low-content de neuf minutes était donc perdu à chaque rechargement, en
    silence — l'onglet réaffichait un formulaire vide comme si rien n'avait tourné."""
    i = html.index("function entrer(")
    j = html.index("function sortir(", i)
    corps = html[i:j]
    for vue in ("VUE_NF", "VUE_FIC", "VUE_LC"):
        assert f"reprendreTravail({vue})" in corps, \
            f"reprendreTravail({vue}) n'est pas appelé depuis entrer()"
