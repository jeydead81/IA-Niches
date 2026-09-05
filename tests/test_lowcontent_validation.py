"""Jeu de validation low-content — la mesure qui manque au scoring.

Les seuils de `data/lowcontent_criteres.json` sont des HYPOTHÈSES : `variantes_max=6`,
`part_indie_bonne=0.5`, `redevance_min_bonne=2.0` n'ont jamais été confrontés à un rayon
réel. Le moteur fonctionne, mais rien ne prouve que son classement correspond à ce que
Baptiste sait du terrain.

Le protocole inverse celui du classifieur fiction, et il faut le voir : en fiction,
Baptiste CORRIGE des étiquettes que l'IA a produites. Ici, il étiquette des requêtes
AVANT toute analyse — son jugement est la référence, pas la correction d'une sortie.
C'est ce qui rend la mesure indépendante : si l'IA produisait les étiquettes, on
calibrerait le scoring sur lui-même.

Critère de sortie du plan : **Spearman ≥ 0,5 ET aucune requête « morte » en vert**. Les
deux, pas l'un ou l'autre — une corrélation honnête qui recommande quand même un rayon
mort ferait publier dans le vide, et c'est la faute la plus chère du produit.
"""
import json
from pathlib import Path

import pytest

from lowcontent_validation import (ETIQUETTES, charger_etiquettes, exporter_gabarit,
                                    rapport_calibration, spearman)
from models import LowContentNiche, LowContentScored


def _scored(score, etiquette_niche="carnet", **kw) -> LowContentScored:
    n = LowContentNiche(niche=etiquette_niche, requete_amazon=etiquette_niche,
                        rationale="r", categorie="c", format_cle="journal_suivi",
                        theme="t", public="adulte")
    base = dict(niche=n, global_score=score, concurrence_mesuree=True,
                priorite="🟢 À analyser en priorité" if score >= 7.5
                else "🟡 Intéressant" if score >= 6.0 else "🔴 Faible")
    base.update(kw)
    return LowContentScored(**base)


# ── Spearman, pur ──────────────────────────────────────────────────────────────

def test_un_classement_parfait_donne_un():
    assert spearman([1, 2, 3, 4], [10, 20, 30, 40]) == pytest.approx(1.0)


def test_un_classement_inverse_donne_moins_un():
    assert spearman([1, 2, 3, 4], [40, 30, 20, 10]) == pytest.approx(-1.0)


def test_les_ex_aequo_recoivent_un_rang_MOYEN():
    """LE point d'implémentation. Les étiquettes n'ont que trois valeurs : il y aura
    beaucoup d'ex aequo, et un Spearman qui les classerait arbitrairement mesurerait
    l'ordre de saisie du fichier, pas la qualité du scoring."""
    assert spearman([1, 1, 2, 2], [5, 5, 9, 9]) == pytest.approx(1.0)


def test_moins_de_deux_points_ne_rend_RIEN():
    """Une corrélation sur un point n'est pas faible, elle est indéfinie. `None` le dit ;
    zéro le cacherait derrière un chiffre."""
    assert spearman([1], [1]) is None
    assert spearman([], []) is None


def test_une_serie_constante_rend_None():
    """Si toutes les étiquettes sont identiques, il n'y a pas de classement à corréler."""
    assert spearman([2, 2, 2], [1, 5, 9]) is None


# ── Le gabarit ─────────────────────────────────────────────────────────────────

def test_le_gabarit_liste_les_familles_a_couvrir(tmp_path):
    """Le plan exige au moins 3 requêtes par famille : sans ça on calibrerait sur un seul
    type de rayon. Le gabarit doit donc les rappeler, pas laisser une page blanche."""
    openpyxl = pytest.importorskip("openpyxl")
    out = exporter_gabarit(tmp_path / "g.xlsx")
    wb = openpyxl.load_workbook(out)
    texte = " ".join(str(c.value) for row in wb.active.iter_rows() for c in row
                     if c.value)
    for famille in ("carnets", "pro", "coloriage", "grilles", "enfant"):
        assert famille in texte


def test_le_gabarit_rappelle_les_etiquettes_autorisees(tmp_path):
    openpyxl = pytest.importorskip("openpyxl")
    wb = openpyxl.load_workbook(exporter_gabarit(tmp_path / "g.xlsx"))
    texte = " ".join(str(c.value) for row in wb.active.iter_rows() for c in row
                     if c.value)
    for e in ETIQUETTES:
        assert e in texte


def test_le_gabarit_se_relit(tmp_path):
    """Un gabarit non rempli doit rendre zéro ligne, pas lever : c'est l'état normal
    juste après sa création."""
    pytest.importorskip("openpyxl")
    assert charger_etiquettes(exporter_gabarit(tmp_path / "g.xlsx")) == []


def test_une_etiquette_inconnue_est_signalee_pas_avalee(tmp_path):
    """« bof » n'est pas une étiquette. L'ignorer ferait disparaître une ligne du jeu sans
    que personne s'en aperçoive — et un jeu de validation amputé en silence mesure faux."""
    openpyxl = pytest.importorskip("openpyxl")
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.append(["requete", "famille", "etiquette", "note"])
    ws.append(["carnet glycemie", "carnets", "bof", ""])
    chemin = tmp_path / "rempli.xlsx"
    wb.save(chemin)
    with pytest.raises(ValueError, match="bof"):
        charger_etiquettes(chemin)


# ── Le rapport ─────────────────────────────────────────────────────────────────

def _paires_alignees():
    """Un scoring qui classe comme Baptiste : bonnes hautes, mortes basses.

    Trois par étiquette et pas deux : c'est le minimum pour qu'un seul contre-exemple ne
    fasse pas passer la corrélation sous 0,5 à lui tout seul. Sinon le test « un mort en
    vert bloque » prouverait juste qu'un outlier abîme un Spearman calculé sur six
    points — ce qui est vrai de n'importe quelle corrélation et ne dit rien du produit."""
    return [("bonne", _scored(8.2)), ("bonne", _scored(8.0)), ("bonne", _scored(7.8)),
            ("mauvaise", _scored(6.4)), ("mauvaise", _scored(6.1)),
            ("mauvaise", _scored(5.8)),
            ("morte", _scored(3.1)), ("morte", _scored(2.7)), ("morte", _scored(2.4))]


def test_un_scoring_aligne_franchit_la_porte():
    r = rapport_calibration(_paires_alignees())
    assert r.spearman is not None and r.spearman >= 0.5
    assert r.morts_en_vert == []
    assert r.porte_franchie is True


def test_un_scoring_inverse_ne_la_franchit_pas():
    paires = [("bonne", _scored(2.0)), ("bonne", _scored(2.5)),
              ("mauvaise", _scored(6.0)), ("morte", _scored(9.0))]
    r = rapport_calibration(paires)
    assert r.porte_franchie is False


def test_UN_SEUL_mort_en_vert_suffit_a_bloquer():
    """Les deux critères sont conjoints. Une corrélation excellente qui recommande quand
    même un rayon mort ferait publier dans le vide : c'est la faute la plus chère du
    produit, et elle ne se compense pas par une bonne moyenne."""
    paires = _paires_alignees() + [("morte", _scored(8.8, "coloriage mort"))]
    r = rapport_calibration(paires)
    assert r.spearman >= 0.5
    assert r.morts_en_vert == ["coloriage mort"]
    assert r.porte_franchie is False


def test_le_rapport_dit_les_signaux_par_etiquette():
    """C'est ce qui permet de RÉGLER les seuils : si les « mauvaises » ont en médiane
    9 variantes et les « bonnes » 2, `variantes_max=6` est bien placé. Sans ces
    distributions, on ajuste au hasard."""
    paires = [("bonne", _scored(8.0, part_indie=0.9, n_variantes_quasi_identiques=2,
                                prix_median=12.99, redevance_estimee=3.2)),
              ("mauvaise", _scored(5.0, part_indie=0.2, n_variantes_quasi_identiques=9,
                                   prix_median=6.99, redevance_estimee=1.1))]
    r = rapport_calibration(paires)
    assert "bonne" in r.signaux and "mauvaise" in r.signaux
    assert r.signaux["bonne"]["part_indie"] == pytest.approx(0.9)
    assert r.signaux["mauvaise"]["n_variantes"] == pytest.approx(9)


def test_les_signaux_non_mesures_sont_EXCLUS_pas_comptes_zero():
    """L'invariant du dépôt vaut aussi dans le rapport de calibration : une part indie
    non mesurée n'est pas une part indie nulle, et la moyenner à zéro fausserait
    exactement le seuil qu'on cherche à régler."""
    paires = [("bonne", _scored(8.0, part_indie=0.8)),
              ("bonne", _scored(7.9, part_indie=None))]
    r = rapport_calibration(paires)
    assert r.signaux["bonne"]["part_indie"] == pytest.approx(0.8)
    assert r.signaux["bonne"]["n_part_indie_mesuree"] == 1


def test_le_rapport_liste_les_requetes_hors_taxonomie():
    """Les « other » sont le seul retour terrain du run : ils font la taxonomie v2. Les
    laisser dans le tas les perdrait."""
    n = LowContentNiche(niche="carnet lunaire", requete_amazon="carnet rituels lunaires",
                        rationale="r", categorie="c", format_cle="other",
                        other_libelle="grimoire", theme="t", public="adulte")
    r = rapport_calibration([("bonne", LowContentScored(niche=n, global_score=7.0))])
    assert r.hors_taxonomie == [{"requete": "carnet rituels lunaires",
                                 "libelle_observe": "grimoire"}]


def test_le_rapport_signale_une_famille_sous_representee():
    """Moins de 3 requêtes dans une famille = calibration aveugle sur ce rayon. Le rapport
    doit le DIRE, sinon on croit avoir mesuré ce qu'on n'a pas mesuré."""
    r = rapport_calibration(_paires_alignees(), familles=["carnets"] * 9)
    assert any("famille" in a.lower() for a in r.avertissements)


def test_une_niche_dont_la_concurrence_n_a_pas_ete_MESUREE_sort_du_CALCUL():
    """Sa priorité est « ⚪ à relancer » et son score a été calculé sans le moindre bonus
    ni malus de concurrence. La corréler au jugement de Baptiste corrélerait du bruit :
    on mesurerait l'écart entre un humain qui a vu le rayon et un score qui ne l'a pas vu.

    Elle est comptée et annoncée — pas jetée en silence, sinon le rapport annoncerait
    30 requêtes calibrées alors qu'il en a lu 24."""
    paires = _paires_alignees() + [("bonne", _scored(1.0, "serp tombee",
                                                     concurrence_mesuree=False))]
    r = rapport_calibration(paires)
    assert r.n_non_mesurees == 1
    assert r.n_calibrees == 9
    assert r.spearman == pytest.approx(rapport_calibration(_paires_alignees()).spearman)
    assert any("mesur" in a.lower() for a in r.avertissements)


def test_zero_requete_mesurable_ne_rend_pas_un_scoring_parfait():
    """Toutes les SERP tombées = rien à calibrer. `None` le dit, la porte reste fermée."""
    r = rapport_calibration([("bonne", _scored(8.0, concurrence_mesuree=False))])
    assert r.spearman is None and r.porte_franchie is False


def test_un_rapport_vide_ne_franchit_rien():
    """Zéro requête n'est pas un scoring parfait."""
    r = rapport_calibration([])
    assert r.porte_franchie is False and r.spearman is None


def test_le_rapport_se_serialise_en_json():
    """Il doit s'archiver dans `99-logs/`, comme celui du classifieur fiction."""
    r = rapport_calibration(_paires_alignees())
    d = json.loads(r.model_dump_json())
    assert "spearman" in d and "porte_franchie" in d


def test_le_gabarit_REFUSE_d_ecraser_un_classeur_deja_rempli(tmp_path):
    """Le gabarit et le fichier de travail portent le même nom : relancer `--gabarit`
    après avoir étiqueté trente requêtes effacerait une demi-heure de travail, en
    silence et sans retour arrière — il n'y a pas de corbeille pour un xlsx écrasé.

    C'est la règle 10 du dépôt appliquée à l'outil lui-même : confirmation avant
    d'écraser un fichier existant. On refuse plutôt qu'on sauvegarde à côté : un
    `.bak` créé sans le dire est un fichier de plus que personne ne relira."""
    openpyxl = pytest.importorskip("openpyxl")
    chemin = exporter_gabarit(tmp_path / "g.xlsx")

    # Un gabarit VIERGE se régénère sans discuter : rien à perdre.
    exporter_gabarit(chemin)

    wb = openpyxl.load_workbook(chemin)
    ws = wb.active
    ws["A7"], ws["C7"] = "carnet suivi glycemie", "bonne"
    wb.save(chemin)

    with pytest.raises(FileExistsError, match="carnet suivi glycemie|rempli|étiquet"):
        exporter_gabarit(chemin)

    # Et le fichier est INTACT après le refus.
    assert charger_etiquettes(chemin)[0].requete == "carnet suivi glycemie"


def test_on_peut_forcer_la_regeneration_explicitement(tmp_path):
    """Le refus doit être contournable — sinon on force la main de l'utilisateur qui
    veut vraiment repartir de zéro, et il ira supprimer le fichier lui-même sans
    réfléchir."""
    openpyxl = pytest.importorskip("openpyxl")
    chemin = exporter_gabarit(tmp_path / "g.xlsx")
    wb = openpyxl.load_workbook(chemin)
    wb.active["A7"], wb.active["C7"] = "carnet a", "bonne"
    wb.save(chemin)

    exporter_gabarit(chemin, ecraser=True)
    assert charger_etiquettes(chemin) == []
