"""tests/test_ux_kdp_historique.py — les deux fonctions ne valent que si l'utilisateur les voit.

Même motif que test_ux_glossaire.py : on lit le HTML servi tel quel et on vérifie la
présence des textes et des appels attendus, pas le rendu visuel.

L'enjeu n'est pas cosmétique : un endpoint sans bouton est une fonction que personne
n'utilisera jamais, et un backend d'historique sans affichage est une base SQLite que
personne n'ira lire à la main."""
from pathlib import Path

HTML = (Path(__file__).resolve().parent.parent / "web" / "index.html").read_text("utf-8")


def test_le_bouton_mots_cles_kdp_existe_et_appelle_l_endpoint():
    assert "Mots-clés KDP" in HTML
    assert "/api/kdp-keywords" in HTML


def test_chaque_emplacement_est_copiable_un_par_un():
    """L'auteur colle les 7 expressions dans 7 champs distincts de KDP. Un bloc unique
    l'obligerait à découper à la main — et à se tromper."""
    assert "clipboard" in HTML.lower(), "un bouton copier par emplacement est attendu"
    assert "/50" in HTML, "la longueur consommée sur les 50 caractères doit être visible"


def test_le_statut_confirme_par_amazon_est_lisible():
    """LE point de vente du module : on ne devine pas le volume, on vérifie qu'Amazon
    complète l'expression. Sans pastille, cette vérification reste invisible."""
    assert "confirmé par Amazon" in HTML.lower() or "Confirmé par Amazon" in HTML
    assert "à vérifier" in HTML.lower()


def test_les_rejets_sortent_avec_leur_motif():
    """CLAUDE.md §10 : un mot-clé écarté en silence est une décision invisible."""
    assert "motif" in HTML.lower()
    assert "écarté" in HTML.lower()


def test_une_sonde_indisponible_est_annoncee_et_non_masquee():
    """Une panne d'autocomplete doit se lire comme une panne, jamais comme « aucun de tes
    mots-clés n'est cherché » — le contresens serait total et l'auteur jetterait de bons
    mots-clés."""
    assert "sonde_indisponible" in HTML
    for extrait in ("n'a pas répondu", "n'ont pas pu être vérifi"):
        assert extrait.lower() in HTML.lower(), f"message de panne manquant : {extrait}"


def test_l_historique_est_affiche_et_son_absence_n_est_pas_une_erreur():
    """Une niche vue une seule fois n'a pas d'évolution : il faut le DIRE (« premier
    passage »), pas afficher une erreur ni un delta à zéro qui se lirait « stable »."""
    assert "/api/history" in HTML
    assert "premier passage" in HTML.lower()


def test_l_evolution_est_lue_en_francais_pas_en_delta_brut():
    """C'est le champ `lecture` de DeltaNiche qui fait agir l'auteur, pas `variations` :
    « +0,23 » ne déclenche aucune décision, « la niche s'est densifiée » si. Le nombre de
    jours est déjà porté par `lecture` — le répéter dans l'en-tête ferait lire deux fois
    la même information (constaté au navigateur)."""
    assert "delta.lecture" in HTML
    assert "delta.variations" not in HTML, "le delta brut ne doit pas remonter à l'écran"
    assert "n_passages" in HTML
