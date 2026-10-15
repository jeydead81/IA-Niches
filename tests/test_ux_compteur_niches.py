"""L'écran dit la même chose que le compteur : des NICHES, et ce qu'il en RESTE (2026-10-06).

« 12 analyses » ne voulait rien dire pour quelqu'un qui paie par niche. Avec un plafond on montre
ce qu'il reste ; sans plafond (poste local), ce qui a été analysé. Fonction pure, appelée pour
de vrai avec node (§2.10).
"""
import re
from pathlib import Path

from tests.js_harness import appeler_json

HTML = (Path(__file__).resolve().parent.parent / "web" / "index.html").read_text(encoding="utf-8")


def test_avec_un_plafond_l_ecran_dit_ce_qu_il_reste():
    l = appeler_json("libelleUsage", {"n_niches": 18, "plafond_niches": 60, "cout_usd": 0.4})
    assert "42" in l["barre"] and "sur 60" in l["barre"] and "restantes" in l["barre"]
    assert "42" in l["pied"] and "restante" in l["pied"]


def test_un_plafond_depasse_ne_montre_jamais_un_nombre_negatif():
    l = appeler_json("libelleUsage", {"n_niches": 70, "plafond_niches": 60})
    assert "<strong>0</strong>" in l["barre"]


def test_sans_plafond_l_ecran_dit_ce_qui_a_ete_analyse():
    l = appeler_json("libelleUsage", {"n_niches": 7, "plafond_niches": None})
    assert "7" in l["barre"] and "analysée" in l["barre"] and "restantes" not in l["barre"]


def test_un_compteur_illisible_ne_s_affiche_pas_en_nan():
    l = appeler_json("libelleUsage", {})
    assert "NaN" not in l["barre"] + l["pied"] and "undefined" not in l["barre"] + l["pied"]


def test_la_page_ne_parle_plus_d_analyses_lancees():
    """Le compteur ne compte plus des runs : l'ancien libellé mentirait sur ce qu'il mesure."""
    assert "analyse(s) lancée(s)" not in HTML
    assert "u.n_analyses" not in HTML


def test_les_refus_de_plafond_montrent_le_motif_du_serveur():
    """Le serveur dit ce qu'il RESTE (« il vous en reste 2, cette analyse en demande 6 ») : un
    texte figé côté page le masquerait derrière un « limite atteinte » qui ressemble à une panne."""
    for m in re.finditer(r"rep\.status===429|r\.status===429", HTML):
        extrait = HTML[max(0, m.start() - 80):m.start() + 120]
        assert "d.detail ||" in extrait, extrait


def test_le_marqueur_de_rappel_ne_reste_jamais_dans_la_carte():
    """`_deja_fait` est une réponse, pas une donnée : la page renvoie la carte telle quelle au
    serveur (mots-clés), qui la valide — un champ de trop y serait refusé."""
    assert HTML.count("delete v._deja_fait") == 3 and HTML.count("delete mots._deja_fait") == 1
