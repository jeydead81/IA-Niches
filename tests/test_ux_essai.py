"""L'écran de l'essai gratuit (2026-10-15).

Deux choses seulement, et toutes deux doivent être vraies AVANT le clic :

1. le compteur dit ce qu'il reste de l'ESSAI (« 2 recherches, 5 niches maximum chacune »), pas un compteur de
   niches mensuel qui n'existe pas pour ce compte ;
2. le formulaire ne propose pas ce que le serveur refusera : en essai, le champ « niches » plafonne à 5,
   presets compris (le preset « approfondi » écrit 10 — un clic proposé par l'interface elle-même ne doit
   pas rendre une 400).

Les fonctions de rendu sont PURES et appelées pour de vrai avec node (§2.10). Le branchement au DOM, lui,
n'est vérifié que par le texte : il l'a été à l'écran le 2026-10-15 (serveur isolé).
"""
import re
from pathlib import Path

from tests.js_harness import appeler_json

HTML = (Path(__file__).resolve().parent.parent / "web" / "index.html").read_text(encoding="utf-8")

ESSAI = {"recherches_restantes": 2, "recherches_max": 2, "niches_par_recherche": 5,
         "analyses_detaillees_max": 4, "demarre": False}


def _u(**essai):
    return {"n_niches": 0, "plafond_niches": None, "plan": "essai", "essai": {**ESSAI, **essai}}


# ── Compteur ────────────────────────────────────────────────────────────────────────────

def test_en_essai_l_ecran_dit_les_recherches_restantes_et_les_cinq_niches():
    l = appeler_json("libelleUsage", _u())
    assert "Essai gratuit" in l["barre"]
    assert "<strong>2</strong>" in l["barre"] and "sur 2" in l["barre"]
    assert "5 niches" in l["barre"]
    assert "<strong>2</strong>" in l["pied"] and "recherche" in l["pied"]
    assert l["titre"] == "Essai gratuit"          # le bloc du bas ne dit pas « Ce mois-ci » : l'essai n'a pas de mois


def test_hors_essai_le_bloc_du_bas_garde_son_titre_mensuel():
    for u in ({"n_niches": 3, "plafond_niches": None}, {"n_niches": 3, "plafond_niches": 60, "essai": None}):
        assert appeler_json("libelleUsage", u)["titre"] == "Ce mois-ci"


def test_apres_une_recherche_il_en_reste_une():
    l = appeler_json("libelleUsage", _u(recherches_restantes=1, demarre=True))
    assert "<strong>1</strong>" in l["barre"] and "sur 2" in l["barre"]


def test_un_essai_termine_le_dit_au_lieu_d_afficher_zero_recherche_restante():
    l = appeler_json("libelleUsage", _u(recherches_restantes=0, demarre=True))
    assert "terminé" in l["barre"].lower()
    assert "NaN" not in l["barre"] + l["pied"] and "undefined" not in l["barre"] + l["pied"]


def test_hors_essai_le_compteur_de_niches_est_inchange():
    l = appeler_json("libelleUsage", {"n_niches": 18, "plafond_niches": 60, "plan": "illimite",
                                      "essai": None})
    assert "42" in l["barre"] and "sur 60" in l["barre"] and "Essai" not in l["barre"]


def test_un_essai_illisible_ne_s_affiche_pas_en_nan():
    l = appeler_json("libelleUsage", {"plan": "essai", "essai": {}})
    assert "NaN" not in l["barre"] + l["pied"] and "undefined" not in l["barre"] + l["pied"]


# ── Plafond du formulaire ───────────────────────────────────────────────────────────────

def test_le_plafond_de_volume_vient_du_serveur_et_n_existe_qu_en_essai():
    assert appeler_json("plafondVolumeEssai", _u()) == 5
    assert appeler_json("plafondVolumeEssai", _u(niches_par_recherche=7)) == 7
    assert appeler_json("plafondVolumeEssai", {"plan": "illimite", "essai": None}) is None
    assert appeler_json("plafondVolumeEssai", {}) is None
    assert appeler_json("plafondVolumeEssai", None) is None


def test_un_plafond_illisible_n_en_est_pas_un():
    assert appeler_json("plafondVolumeEssai", _u(niches_par_recherche="beaucoup")) is None
    assert appeler_json("plafondVolumeEssai", _u(niches_par_recherche=0)) is None


def test_le_volume_autorise_ne_depasse_jamais_le_plafond_et_ne_change_rien_sans_plafond():
    assert appeler_json("volumeAutorise", 10, 5) == 5          # preset « approfondi »
    assert appeler_json("volumeAutorise", 3, 5) == 3
    assert appeler_json("volumeAutorise", 6, None) == 6
    assert appeler_json("volumeAutorise", 20, None) == 20


def test_les_presets_et_le_chargement_du_compteur_passent_par_le_plafond():
    """Le branchement au DOM : les presets écrivent la valeur plafonnée, le compteur applique le plafond
    aux trois champs dès que le serveur a dit le plan."""
    corps = re.search(r"function brancherPresets\(.*?\n\}\n", HTML, re.S).group(0)
    assert "volumeAutorise(" in corps
    usage = re.search(r"function chargerUsage\(\)\{.*?\n\}\n", HTML, re.S).group(0)
    assert "appliquerPlafondVolume(" in usage
    appli = re.search(r"function appliquerPlafondVolume\(.*?\n\}\n", HTML, re.S).group(0)
    for champ in ("#search", "#fic-n", "#lc-search"):
        assert champ in appli, champ
    assert "'max'" in appli or '"max"' in appli or ".max" in appli
