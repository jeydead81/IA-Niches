"""L'écran de résultats non-fiction : des cartes, pas un tableau de base de données.

Refonte décidée par Baptiste (handoff du 2026-10-02). L'ancien écran affichait huit colonnes
de même importance visuelle — score, niche, demande, pénétration, BSR meilleur et moyen,
concurrents, sponsorisés écartés — ce qui oblige le lecteur à trier lui-même ce qui compte.
Aucune donnée ne disparaît : ce qui sortait du tableau descend dans la carte dépliée.

Les fonctions testées ici sont PURES et appelées pour de vrai (harnais node, §2.10) : un test
qui chercherait les chaînes dans le fichier passerait au vert sur une carte jamais rendue
(§5.26).
"""
import pytest

from tests.js_harness import appeler, appeler_json

_DEPS = ("esc", "fmt", "fmtDec", "grade", "verdict", "nonMesuree")


def _niche(**kw):
    base = {"niche": "Sommeil et insomnie", "categorie": "Santé / Bien-être",
            "global_score": 7.4, "demande": 10.0, "penetration": 4.5,
            "bsr_best": 964, "bsr_top5_avg": 48248, "n_concurrents_cibles": 98,
            "n_sponsored": 1, "concurrence_mesuree": True, "criteres_bsr_ok": True}
    base.update(kw)
    return base


def test_la_carte_montre_le_score_le_nom_et_quatre_chiffres():
    html = appeler("carteNicheTete", _niche(), dependances=_DEPS)
    assert "7,4" in html and "Sommeil et insomnie" in html
    for valeur in ("10,0", "4,5", "964", "98"):
        assert valeur in html, f"chiffre manquant sur la carte : {valeur}"


def test_le_vocabulaire_est_celui_de_l_auteur():
    """« Pénétration » est le mot du moteur ; l'auteur lit « Accessibilité »."""
    html = appeler("carteNicheTete", _niche(), dependances=_DEPS)
    assert "Accessibilité" in html and "Pénétration" not in html


def test_une_niche_NON_MESUREE_ne_porte_pas_de_note():
    """Afficher un score calculé sans la concurrence, c'est présenter une absence de mesure
    comme un verdict (règle 3). La carte le dit, elle ne note pas."""
    html = appeler("carteNicheTete", _niche(concurrence_mesuree=False), dependances=_DEPS)
    assert "Non mesurée" in html
    assert "7,4" not in html


@pytest.mark.parametrize("cle,attendu", [
    ("score", ["b", "c", "a"]),
    ("demande", ["c", "b", "a"]),
    ("bsr", ["a", "c", "b"]),
])
def test_le_tri_porte_sur_des_FAITS(cle, attendu):
    """Pas de « trier par potentiel » : mesuré sur 95 niches, le score ne départage pas une
    bonne niche d'une mauvaise. On trie sur ce qui est observé — la note de demande, le
    classement des ventes — et le score reste un tri par défaut, pas une promesse."""
    rows = [_niche(niche="a", global_score=5.0, demande=6.0, bsr_best=100),
            _niche(niche="b", global_score=8.0, demande=7.0, bsr_best=900),
            _niche(niche="c", global_score=6.0, demande=9.0, bsr_best=500)]
    tries = appeler_json("trierNiches", rows, cle, dependances=())
    assert [n["niche"] for n in tries] == attendu


def test_le_tri_par_BSR_ignore_les_niches_SANS_bsr_plutot_que_de_les_mettre_en_tete():
    """`null` trié comme zéro remonterait en tête les niches dont on ne sait RIEN — le
    classement le plus flatteur possible pour une absence de mesure."""
    rows = [_niche(niche="connu", bsr_best=500), _niche(niche="inconnu", bsr_best=None)]
    tries = appeler_json("trierNiches", rows, "bsr", dependances=())
    assert [n["niche"] for n in tries] == ["connu", "inconnu"]


# ── Fiche niche (2026-10-02) ───────────────────────────────────────────────────
#
# Le cœur du produit : ce qu'un auteur lit avant de décider d'écrire. Elle ne doit INVENTER
# aucun seuil — « pourquoi cette niche ? » rejoue exactement ceux du scoring (10 000 pour la
# preuve de vente, 30 et 50 pour la concurrence, le critère « place à prendre »). Une phrase
# d'explication qui reposerait sur un seuil maison dirait autre chose que la note affichée
# juste au-dessus, et c'est l'utilisateur qui paierait l'incohérence.

def test_pourquoi_lit_la_PREUVE_DE_VENTE_au_seuil_du_scoring():
    cartes = appeler_json("pourquoiNiche", _niche(bsr_best=964),
                            dependances=("fmt", "nonMesuree"))
    demande = [c for c in cartes if c["cle"] == "demande"][0]
    assert demande["ton"] == "bon" and "964" in demande["texte"]

    faible = appeler_json("pourquoiNiche", _niche(bsr_best=48000),
                           dependances=("fmt", "nonMesuree"))
    assert [c for c in faible if c["cle"] == "demande"][0]["ton"] == "neutre"


def test_pourquoi_signale_une_concurrence_INSTALLEE():
    cartes = appeler_json("pourquoiNiche", _niche(n_concurrents_cibles=98),
                           dependances=("fmt", "nonMesuree"))
    conc = [c for c in cartes if c["cle"] == "concurrence"][0]
    assert conc["ton"] == "alerte" and "98" in conc["texte"]


def test_pourquoi_ne_conclut_RIEN_quand_la_concurrence_n_est_pas_mesuree():
    """Règle 3 : une absence de mesure n'est pas un verdict de marché."""
    cartes = appeler_json("pourquoiNiche", _niche(concurrence_mesuree=False),
                           dependances=("fmt", "nonMesuree"))
    assert [c["cle"] for c in cartes] == ["non_mesuree"]
    assert "pas" in cartes[0]["texte"].lower()


def test_la_fiche_porte_les_quatre_chiffres_et_le_retour():
    html = appeler("ficheNiche", _niche(),
                   dependances=("esc", "fmt", "fmtDec", "grade", "verdict", "nonMesuree",
                                "pourquoiNiche"))
    assert "Retour aux résultats" in html
    assert "Sommeil et insomnie" in html
    for valeur in ("7,4", "10,0", "964", "98"):
        assert valeur in html
    assert "Pourquoi cette niche" in html


# ── Hiérarchie de la fiche (2026-10-02, second passage) ────────────────────────
#
# Verdict de Baptiste devant l'écran : « quand on regarde le screen on soupire, y'a aucune
# hiérarchie ». C'était vrai : le titre proposé par l'IA — ce que l'auteur peut réellement
# écrire — arrivait APRÈS un paragraphe d'analyse, dans la même taille que tout le reste, et
# le prix du rayon se perdait au milieu d'une page de texte.

def test_le_prix_du_rayon_est_une_TUILE_pas_une_ligne_perdue():
    html = appeler("ficheNiche", _niche(prix_median=12.93, n_prix_connus=56),
                   dependances=("esc", "fmt", "fmtEur", "fmtDec", "grade", "verdict",
                                "nonMesuree", "pourquoiNiche"))
    tuiles = html[html.index('class="fiche-kpis"'):html.index('class="fiche-h"')]
    assert "Prix médian" in tuiles and "12,93" in tuiles


def test_l_ANGLE_passe_AVANT_le_facteur_decisif():
    """L'angle est ce que l'auteur peut écrire ; le facteur décisif est le raisonnement du
    modèle. Mettre le raisonnement en premier, c'est faire lire l'outil avant le livre."""
    verdict = {"verdict": "Go prudent", "confiance": 6, "facteur_decisif": "raisonnement long",
               "angles": [{"angle": "a", "titre": "Mieux Dormir en 21 Jours",
                           "sous_titre": "le protocole simple", "pourquoi": "parce que",
                           "requete_principale": "mieux dormir", "requetes_secondaires": []}]}
    html = appeler("verdictBlock", {"verdict": verdict}, dependances=("esc", "verdictGrade"))
    assert html.index("Mieux Dormir en 21 Jours") < html.index("raisonnement long")
    assert "Angle proposé par l’IA" in html or "Angle proposé par l'IA" in html
