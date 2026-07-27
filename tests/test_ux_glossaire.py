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


def test_chaque_fiche_dit_une_conclusion_actionnable():
    """La matrice sort une valeur technique (`porteur_encombre`) ; l'utilisateur doit lire
    une conclusion, mot pour mot (plan U3). `non_mesurable` n'est pas un mauvais résultat,
    c'est une absence de résultat — la phrase doit le dire explicitement."""
    titres = ("Pépite", "Porteur mais encombré", "Mur installé", "Désert",
              "Sans intérêt", "Non mesuré")
    for titre in titres:
        assert titre in HTML, f"titre manquant : {titre}"
    conseils = ("À creuser en priorité", "Gardez le sous-genre", "angle très différent",
                "Risqué", "Passez à autre chose", "absence de résultat")
    for conseil in conseils:
        assert conseil.lower() in HTML.lower(), f"conseil manquant : {conseil}"


def test_duree_reelle_annoncee():
    """Sans ça, 10-15 minutes d'attente (mesuré à 869 s) passent pour un plantage."""
    phrase = ("Une analyse fiction prend 10 à 15 minutes. Vous pouvez fermer cette page, "
              "le travail continue et vous le retrouverez ici.")
    assert phrase in HTML


def test_panneau_aide_repliable_present():
    """Panneau repliable, ouvert la première fois : à quoi sert l'outil, ce qu'est un bon
    résultat, l'ordre de lecture des colonnes."""
    assert "<details" in HTML, "un élément repliable natif (<details>) est attendu"
    for extrait in ("à quoi sert", "bon résultat", "ordre de lecture"):
        assert extrait.lower() in HTML.lower(), f"contenu d'aide manquant : {extrait}"


def test_consommation_mensuelle_affichee():
    """Un plafond qui bloque sans qu'on ait pu voir où on en était se vit comme une panne."""
    assert "/api/usage" in HTML
