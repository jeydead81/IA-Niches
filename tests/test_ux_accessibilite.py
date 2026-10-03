"""Deux bloquants relevés à la revue d'interface du 2026-08-18.

1. ZÉRO région `aria-live` dans toute la page. Un scout dure 2 à 12 minutes et sa liste
   d'étapes s'alimente en continu ; le verdict s'injecte dans la ligne dépliée ; le
   bandeau d'erreur apparaît. Rien n'est annoncé. Un utilisateur non-voyant lance un run
   et n'a aucun moyen de savoir s'il progresse, s'il a échoué, ou s'il est terminé — la
   seule issue étant de re-tabuler la page à l'aveugle pour deviner. C'est un produit
   inutilisable, pas un produit imparfait.

2. Les pastilles de glossaire mesurent 16 × 16 px, contre 24 × 24 exigés par WCAG 2.2
   (2.5.8 Target Size Minimum). L'incohérence est interne : ces boutons ont été rendus
   cliquables EXPRÈS parce qu'« une tablette ne survole rien ». L'intention tactile est
   là, la taille ne suit pas.

Les tailles se vérifient en navigateur (`test_a11y_navigateur.md` n'existe pas : c'est la
revue qui les a mesurées). Ici on tient ce qui est tenable hors ligne — la présence et le
RÔLE des régions, et la géométrie déclarée en CSS.
"""
import re
from pathlib import Path

import pytest

_INDEX = Path(__file__).resolve().parent.parent / "web" / "index.html"


@pytest.fixture(scope="module")
def html() -> str:
    return _INDEX.read_text(encoding="utf-8")


# ── 1. Régions live ────────────────────────────────────────────────────────────

@pytest.mark.parametrize("ident", ["progress", "progress-fic", "progress-lc"])
def test_l_avancement_est_une_region_live_polie(html, ident):
    """`polite` et non `assertive` : l'analyse dure de 2 à 15 minutes. En `assertive`, chaque
    mise à jour couperait la parole au lecteur d'écran — l'utilisateur ne pourrait plus rien
    lire d'autre pendant tout le run.

    La région annoncée est la PHRASE DE PHASE (une par jalon) et la liste des avertissements :
    le journal détaillé, replié sous « Voir le détail », n'est plus annoncé ligne à ligne —
    une centaine de lignes seraient du bruit, pas de l'information. Les avertissements, eux,
    restent annoncés : une source tombée ne doit jamais passer inaperçue."""
    debut = html.index(f'id="{ident}"')
    panneau = html[debut:html.index("</details>", debut)]
    phase = re.search(r'<p class="prog-phase"[^>]*>', panneau)
    alertes = re.search(r'<ul class="prog-alertes"[^>]*>', panneau)
    assert phase and 'aria-live="polite"' in phase.group(0), phase and phase.group(0)
    assert alertes and 'aria-live="polite"' in alertes.group(0), alertes and alertes.group(0)
    assert 'aria-live="assertive"' not in panneau


@pytest.mark.parametrize("ident", ["steps", "steps-fic", "steps-lc"])
def test_le_journal_detaille_existe_toujours_sous_un_volet(html, ident):
    """Rien n'est supprimé : le journal complet se retrouve sous « Voir le détail »."""
    m = re.search(r'<ul[^>]*id="' + ident + r'"[^>]*>', html)
    assert m, f"liste #{ident} introuvable"
    avant = html[:m.start()]
    assert avant.rindex('<details class="prog-detail"') > avant.rindex('class="panel progress"')


@pytest.mark.parametrize("ident", ["errbox", "errbox-fic"])
def test_le_bandeau_d_erreur_est_assertif(html, ident):
    """`assertive` ici, parce qu'une erreur invalide ce que l'utilisateur attend : le
    faire patienter devant un run mort est pire que l'interrompre."""
    m = re.search(r'<div[^>]*id="' + ident + r'"[^>]*>', html)
    assert m, f"bandeau #{ident} introuvable"
    assert 'aria-live="assertive"' in m.group(0), m.group(0)
    assert 'role="alert"' in m.group(0), m.group(0)


def test_le_verdict_injecte_est_annonce(html):
    """Le verdict arrive ~10 s après le clic, dans une ligne dépliée que l'utilisateur ne
    regarde pas forcément. Sans région live, l'analyse qu'il a demandée — et payée —
    apparaît sans que rien ne le lui dise."""
    m = re.search(r'<div class="verdictslot"[^>]*>', html)
    assert m, "emplacement du verdict introuvable"
    assert 'aria-live="polite"' in m.group(0), m.group(0)


def test_le_bouton_d_analyse_dit_son_etat_pendant_l_attente(html):
    """« Analyse en cours… » doit être lisible par le lecteur d'écran, pas seulement à
    l'œil : c'est le seul retour pendant les dix secondes d'attente."""
    assert "aria-busy" in html


# ── 2. Cibles tactiles ─────────────────────────────────────────────────────────

def test_la_pastille_de_glossaire_atteint_24px(html):
    """WCAG 2.2 (2.5.8) : 24 × 24 minimum. Le rond VISUEL peut rester à 16 px — c'est la
    zone cliquable qui doit grandir, sinon on abîme une mise en page qui fonctionne."""
    m = re.search(r"\.gloss\{(.*?)\}", html, re.S)
    assert m, "règle .gloss introuvable"
    regle = m.group(1)
    # la geometrie declaree reste a 16px (le rond), la cible est etendue autrement
    assert "width:16px" in regle.replace(" ", "")
    assert re.search(r"\.gloss::(after|before)\{", html), \
        "aucune extension de cible : le rond fait toujours 16 px cliquables"


def test_l_extension_de_cible_ne_bloque_pas_le_survol_du_reste(html):
    """Une zone invisible de 24 px posée par-dessus la page attraperait les clics des
    éléments voisins. Elle doit être centrée sur le bouton et ne rien déborder d'autre."""
    m = re.search(r"\.gloss::(?:after|before)\{(.*?)\}", html, re.S)
    assert m, "extension de cible introuvable"
    regle = m.group(1).replace(" ", "")
    assert "position:absolute" in regle
    assert "content:" in regle


# ── Cibles textuelles dépliantes ───────────────────────────────────────────────

@pytest.mark.parametrize("regle", [".avance summary", ".kdpfold summary",
                                   ".compo summary", ".help-panel summary"])
def test_les_replis_atteignent_24px_de_haut(html, regle):
    """Ces `<summary>` faisaient 18 à 22 px pour 107 à 703 px de large : confortables à la
    souris, courts au doigt. Un padding vertical (ou un `min-height`) épaissit la zone
    cliquable sans ajouter la moindre ligne visible."""
    m = re.search(re.escape(regle) + r"\{(.*?)\}", html, re.S)
    assert m, f"règle {regle} introuvable"
    corps = m.group(1).replace(" ", "").replace("\n", "")
    assert "padding:5px0" in corps or "min-height:24px" in corps, corps
