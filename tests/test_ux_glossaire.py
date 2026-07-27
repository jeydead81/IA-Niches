"""tests/test_ux_glossaire.py — revue UX lisibilité (plan docs/superpowers/plans/2026-07-21-ux-lisibilite.md).

Ces tests lisent le HTML servi tel quel (pas de rendu navigateur) : ils vérifient la
PRÉSENCE des textes/mots d'habillage attendus, pas le rendu visuel (couvert par une
vérification manuelle au navigateur, cf. rapport de tâche)."""
from pathlib import Path

HTML = (Path(__file__).resolve().parent.parent / "web" / "index.html").read_text("utf-8")


def test_chaque_terme_technique_a_son_explication():
    """Sans ancrage, « Profondeur 0,96 » ne veut rien dire pour un non-initié."""
    for terme in ("BSR", "Saturation du trio", "Profondeur", "Ouverture", "Part séries"):
        assert terme in HTML
    for extrait in ("Plus le nombre est", "promettent", "se vendent", "reste-t-il"):
        assert extrait.lower() in HTML.lower(), f"explication manquante : {extrait}"


def test_saturation_habillage_inverse_et_seuils_alignes():
    """Piège n°1 du plan : la saturation est le SEUL score où haut = mauvais. L'habiller
    comme les autres (vert quand élevé) serait un contresens exactement inverse de la
    réalité. Les mots d'habillage (profondeur/ouverture forte-moyenne-faible, saturation
    déjà très couvert / peu couvert) doivent tous apparaître."""
    for mot in ("forte", "moyenne", "faible", "déjà très couvert", "peu couvert"):
        assert mot.lower() in HTML.lower(), f"habillage manquant : {mot}"


def test_scores_en_virgule_decimale_francaise():
    """0,96 et non 0.96 : l'utilisateur cible est français. Un formateur décimal dédié,
    aligné sur le style déjà en place pour fmt()/fmtEur() (toLocaleString('fr-FR', ...))."""
    assert "fmtDec" in HTML, "un formateur décimal fr-FR dédié aux scores est attendu"
