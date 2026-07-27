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
