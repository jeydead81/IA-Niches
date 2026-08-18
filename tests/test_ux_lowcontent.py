"""Onglet Low-content — rendu exercé, pas seulement cherché dans le fichier.

Même discipline que `test_ux_verdict_atteignable` : les fonctions de rendu sont PURES et
appelées pour de vrai (harnais node). Un test qui cherche une chaîne dans `index.html`
prouve qu'elle est écrite, jamais qu'elle est affichée — c'est ce qui a laissé trois
endpoints inatteignables pendant des semaines (§5.26).

Ce que les cartes doivent dire, et qui n'existe dans aucun autre onglet :
- PART INDIE, avec « non mesurée » quand aucun éditeur n'a pu être lu ;
- VARIANTES, dont l'échelle est INVERSÉE — élevé = mauvais, comme la saturation fiction ;
- le SEUIL DE 9,99 €, qui décide de 50 % ou 60 % de redevance.
"""
import re
from pathlib import Path

import pytest

from tests.js_harness import appeler

_INDEX = Path(__file__).resolve().parent.parent / "web" / "index.html"
# Dépendances de `carteLowContent`, dans l'ordre où node en a besoin.
_DEPS = ("esc", "fmt", "fmtEur", "fmtPct", "fmtDec", "grade", "mesure",
         "verdictGrade", "verdictBlock", "verdictSlot")


def _lc(**kw) -> dict:
    base = {
        "niche": {"niche": "carnet de suivi glycémie",
                  "requete_amazon": "carnet suivi glycemie diabete",
                  "format_cle": "journal_suivi", "theme": "glycémie",
                  "public": "adulte", "source": "autocomplete",
                  "profondeur_autocomplete": 2, "n_enfants_autocomplete": 4},
        "global_score": 7.4, "priorite": "🟡 Intéressant",
        "demande": 7.5, "penetration": 7.0, "rentabilite": 7.0, "faisabilite": 9.0,
        "part_indie": 0.8, "part_editeurs_traditionnels": 0.2, "n_editeur_inconnu": 0,
        "n_variantes_quasi_identiques": 3, "prix_median": 11.99,
        "prix_sous_seuil_60pct": False, "redevance_estimee": 3.15, "pages_median": 120,
        "bsr_best": 8214, "bsr_top_avg": 41000, "concurrence_mesuree": True,
        "n_organic": 12, "n_sponsored": 3, "n_concurrents_cibles": 6,
        "risques": [], "top_books": [], "verdict": None,
    }
    base.update(kw)
    return base


def _carte(**kw) -> str:
    return appeler("carteLowContent", _lc(**kw), dependances=_DEPS)


# ── Part indie ─────────────────────────────────────────────────────────────────

def test_la_part_indie_est_affichee_en_pourcentage():
    """C'est LE signal qui décide si un auteur seul peut attaquer le rayon."""
    assert "80" in _carte(part_indie=0.8)


def test_une_part_indie_non_mesuree_le_dit_au_lieu_d_afficher_zero():
    """« 0 % d'indie » se lirait « rayon tenu par des éditeurs », donc « n'y va pas ».
    C'est une conclusion, là où il n'y a qu'une absence de lecture (§5.10)."""
    html = _carte(part_indie=None, n_editeur_inconnu=6)
    assert "non mesur" in html.lower()
    assert not re.search(r"(?<!\d)0\s?%", html)


def test_le_nombre_d_editeurs_illisibles_est_dit():
    """« 60 % d'indie » sur deux livres ne se lit pas comme sur vingt."""
    assert "6" in _carte(part_indie=0.6, n_editeur_inconnu=6)


# ── Variantes : l'échelle inversée ─────────────────────────────────────────────

def test_beaucoup_de_variantes_est_signale_comme_MAUVAIS():
    """Piège n°1 du dépôt, transposé au low-content : sur `variantes`, élevé = mauvais.
    Une jauge colorée uniformément ferait recommander les pires rayons."""
    peu = _carte(n_variantes_quasi_identiques=1)
    beaucoup = _carte(n_variantes_quasi_identiques=9)
    assert 'class="v-bad"' in beaucoup or "v-bad" in beaucoup
    assert "v-bad" not in peu


def test_l_echelle_inversee_est_dite_a_l_ecran():
    """Le lecteur doit savoir que le chiffre se lit à l'envers, sans avoir à le déduire."""
    html = _carte(n_variantes_quasi_identiques=9)
    assert "élevé" in html.lower() or "eleve" in html.lower()


# ── Le seuil de 9,99 € ─────────────────────────────────────────────────────────

def test_un_prix_sous_le_seuil_est_signale_avec_son_taux():
    """Un auteur qui ne connaît pas le barème verrait « 7,99 € » comme un bon prix."""
    html = _carte(prix_median=7.99, prix_sous_seuil_60pct=True)
    assert "50" in html and "9,99" in html


def test_un_prix_au_dessus_du_seuil_ne_declenche_pas_l_alerte():
    html = _carte(prix_median=12.99, prix_sous_seuil_60pct=False)
    assert "v-bad" not in html or "50 %" not in html


def test_un_prix_non_mesure_n_affiche_ni_prix_ni_taux():
    """`prix_sous_seuil_60pct` vaut False faute de mesure, pas parce que le rayon est
    cher — même défaut que celui trouvé dans le brief du verdict."""
    html = _carte(prix_median=None, prix_sous_seuil_60pct=False, redevance_estimee=None)
    assert "non mesur" in html.lower()
    assert "60 %" not in html


# ── Redevance ──────────────────────────────────────────────────────────────────

def test_une_redevance_negative_est_montree_comme_une_perte():
    """Le seul cas où la réponse est « ne publie pas ça ». La masquer serait pire que de
    ne rien afficher."""
    html = _carte(redevance_estimee=-0.42)
    assert "v-bad" in html


# ── Non mesuré ─────────────────────────────────────────────────────────────────

def test_une_niche_sans_concurrence_mesuree_est_encadree():
    html = _carte(concurrence_mesuree=False, priorite="⚪ Concurrence non mesurée — à relancer")
    assert "non mesur" in html.lower()


def test_un_format_hors_taxonomie_est_nomme():
    """Les « other » sont le matériau de la taxonomie v2 : les afficher comme les autres
    perdrait le seul retour terrain du run."""
    html = _carte(niche={**_lc()["niche"], "format_cle": "other",
                         "other_libelle": "carnet de rituels lunaires"})
    assert "rituels lunaires" in html


def test_un_format_norme_porte_son_badge():
    html = _carte(risques=["norme_a_verifier"])
    assert "norm" in html.lower()


# ── Câblage ────────────────────────────────────────────────────────────────────

@pytest.fixture(scope="module")
def src() -> str:
    return _INDEX.read_text(encoding="utf-8")


def test_l_onglet_existe_et_a_sa_vue(src):
    assert 'id="tab-lc"' in src and 'id="view-lc"' in src


def test_le_selecteur_de_format_vient_de_l_api(src):
    """Jamais une liste dupliquée en dur : elle se périmerait à la première taxo v2."""
    assert "/api/lowcontent/formats" in src


def test_le_lancement_passe_par_les_jobs(src):
    """Un seul chemin de lancement pour les trois scouts (§2.6)."""
    assert "lancerTravail('lowcontent'" in src or 'lancerTravail("lowcontent"' in src


def test_le_verdict_low_content_envoie_son_type(src):
    """`POST /api/verdict` dispatche sur `type` : sans lui, une niche low-content serait
    validée comme une `ScoredNiche` et rendrait une 400."""
    assert "type: 'lowcontent'" in src or '"type": "lowcontent"' in src


def test_le_glossaire_couvre_les_termes_low_content(src):
    for terme in ("Part indie", "Variantes", "Seuil 9,99"):
        assert terme in src, f"terme de glossaire manquant : {terme}"
