"""Ce que la carte fiction montre d'une niche NON CONCLUANTE (zéro livre mesuré, ou trop peu).

Capture de Baptiste (2026-10-05) : une carte « Non mesuré » affichait `Saturation 0,00 · peu
couvert` en VERT, `Profondeur 0,00 · faible`, `Ouverture 0,00 · faible`. Ces zéros ne sont pas des
mesures : ils sont le résultat d'un calcul sur AUCUN livre. Lus à côté d'un cartouche gris, ils
disaient quand même « rayon vierge, peu couvert » — la lecture que la règle 3 interdit.

Fonctions PURES, exécutées pour de vrai (harnais node, §2.10).
"""
import json
import shutil
import subprocess

import pytest

from tests.js_harness import _declaration, _source_js, appeler, extraire_fonction

_SLOT = ("esc", "verdictGrade", "verdictBlock", "verdictSlot", "ETATS_NON_CONCLUANTS_FIC",
         "verdictSlotFic")


def _dm():
    node = shutil.which("node")
    if not node:
        pytest.skip("node absent")
    prog = (_declaration("DM_CONCLUSION", _source_js())
            + "\nprocess.stdout.write(JSON.stringify(DM_CONCLUSION));")
    out = subprocess.run([node, "-e", prog], capture_output=True, text=True, encoding="utf-8",
                         timeout=60)
    assert out.returncode == 0, out.stderr
    return json.loads(out.stdout)


# ── La conclusion ───────────────────────────────────────────────────────────────

def test_la_mesure_mince_a_sa_conclusion_neutre():
    emo, titre, grade, texte = _dm()["mesure_mince"]
    assert grade == "n", "gris, jamais rouge : ce n'est pas un mauvais résultat"
    assert "mince" in titre.lower()
    assert "pas un rayon mort" in texte and "mesure insuffisante" in texte


def test_les_deux_etats_non_concluants_ne_se_confondent_pas():
    dm = _dm()
    assert dm["mesure_mince"][3] != dm["non_mesurable"][3]
    assert dm["mesure_mince"][1] != dm["non_mesurable"][1]


# ── Les tuiles ──────────────────────────────────────────────────────────────────

def test_une_niche_non_concluante_n_affiche_aucun_zero():
    html = appeler("tuilesVidesFic")
    assert html.count('class="fic-cle fic-vide"') == 4
    assert html.count("<b>—</b>") == 4
    assert "0,00" not in html and "peu couvert" not in html and "faible" not in html
    assert "non mesuré" in html


# ── La ligne « mesuré sur N livres » ────────────────────────────────────────────

@pytest.mark.parametrize("n,m,attendu", [
    (4, 12, "4 livres mesurés sur 12"),
    (1, 12, "1 livre mesuré sur 12"),
    (0, 2, "Aucun livre mesuré sur 2"),
    (0, 0, "Aucun livre trouvé"),
])
def test_la_ligne_de_mesure_dit_sur_combien_de_livres_repose_la_carte(n, m, attendu):
    html = appeler("mesureFic", {"n_livres_mesures": n, "books": [{}] * m})
    assert attendu in html and "📏" in html


def test_un_resultat_anterieur_au_compteur_n_affiche_aucune_ligne():
    assert appeler("mesureFic", {"n_livres_mesures": None, "books": [{}] * 5}) == ""
    assert appeler("mesureFic", {"books": [{}] * 5}) == ""


# ── Le bouton d'analyse ─────────────────────────────────────────────────────────

def test_pas_de_bouton_d_analyse_sur_une_mesure_mince():
    r = {"niche": {"query": "q"}, "demand_matrix": "mesure_mince", "books": [{"asin": "A"}]}
    assert appeler("verdictSlotFic", r, dependances=_SLOT) == ""


def test_le_bouton_reste_offert_sur_une_carte_assez_mesuree():
    r = {"niche": {"query": "q"}, "demand_matrix": "mur_installe", "books": [{"asin": "A"}]}
    assert "btn-verdict" in appeler("verdictSlotFic", r, dependances=_SLOT)


# ── Le câblage dans la carte ────────────────────────────────────────────────────

def test_la_carte_branche_les_tuiles_vides_et_la_ligne_de_mesure():
    src = extraire_fonction("renderFic")
    assert "tuilesVidesFic()" in src and "mesureFic(r)" in src
    assert "ETATS_NON_CONCLUANTS_FIC" in src and "metriquesRayonFic(r, acVal)" in src


_DETAIL = ("esc", "fmtPct", "glossBtn", "ETATS_NON_CONCLUANTS_FIC")


def test_une_niche_non_concluante_n_affiche_ni_zero_pour_cent_ni_part_series_a_zero():
    """« Les livres du rayon reprennent déjà 0 % de votre trio » et « Part séries 0 % » sur une
    niche sans livre mesuré : deux zéros de plus qui se liraient comme des faits."""
    for etat in ("non_mesurable", "mesure_mince"):
        html = appeler("metriquesRayonFic", {"demand_matrix": etat, "saturation_trio": 0.0,
                                             "series_share": 0.0}, "<i>ac</i>",
                       dependances=_DETAIL)
        assert "0 %" not in html and "0%" not in html
        assert "non mesuré" in html and "<i>ac</i>" in html


def test_une_niche_mesuree_garde_sa_note_de_saturation_et_sa_part_series():
    html = appeler("metriquesRayonFic", {"demand_matrix": "pepite", "saturation_trio": 0.5,
                                         "series_share": 0.25}, "<i>ac</i>",
                   dependances=_DETAIL)
    assert "50 % de votre trio" in html and "25%" in html and "non mesuré" not in html


# ── Le cliquet Python <-> JS ────────────────────────────────────────────────────

def test_les_etats_non_concluants_du_js_sont_ceux_de_python():
    """`ETATS_NON_CONCLUANTS_FIC` est le MIROIR de `fiction_scoring.NON_CONCLUANTES`. Un troisième
    état ajouté d'un seul côté laisserait un zéro se lire comme une mesure, sans qu'aucun test ne
    le dise (revue adverse du 2026-10-05)."""
    from fiction_scoring import NON_CONCLUANTES
    node = shutil.which("node")
    if not node:
        pytest.skip("node absent")
    prog = (_declaration("ETATS_NON_CONCLUANTS_FIC", _source_js())
            + "\nprocess.stdout.write(JSON.stringify(ETATS_NON_CONCLUANTS_FIC));")
    out = subprocess.run([node, "-e", prog], capture_output=True, text=True, encoding="utf-8",
                         timeout=60)
    assert out.returncode == 0, out.stderr
    assert sorted(json.loads(out.stdout)) == sorted(NON_CONCLUANTES)


def test_chaque_etat_non_concluant_a_sa_conclusion_a_l_ecran():
    from fiction_scoring import NON_CONCLUANTES
    dm = _dm()
    assert all(e in dm and dm[e][2] == "n" for e in NON_CONCLUANTES)


# ── « Aucun livre trouvé » n'est pas « aucune fiche lue » ────────────────────────

def test_aucun_livre_rendu_mais_des_fiches_demandees_ne_se_dit_pas_aucun_livre_trouve():
    html = appeler("mesureFic", {"n_livres_mesures": 0, "books": [], "asins_demandes": 12,
                                 "n_echecs": 12})
    assert "n’a pu être lue" in html and "Aucun livre trouvé" not in html


def test_aucun_livre_et_aucune_fiche_demandee_reste_aucun_livre_trouve():
    html = appeler("mesureFic", {"n_livres_mesures": 0, "books": [], "asins_demandes": 0})
    assert "Aucun livre trouvé" in html


# ── renderFic EXÉCUTÉ : le câblage, pas la présence de chaînes ───────────────────

_REND = ("esc", "fmt", "fmtEur", "fmtDec", "fmtPct", "libCle", "glossBtn", "niveau3",
         "niveau3Inverse", "autocompleteLabel", "couvertureTrio", "blocLivresFic", "verdictGrade",
         "verdictBlock", "verdictSlot", "ETATS_NON_CONCLUANTS_FIC", "verdictSlotFic", "cleNiche",
         "urlConservee", "noteNonConservee", "mesureFic", "tuilesVidesFic", "metriquesRayonFic",
         "brancherActionsFic", "loadVerdictFic", "DM_CONCLUSION", "WARN_RE", "ICON_WARN",
         "renderFic")

_DECORS = """
const cartes = [], hist = [];
const gridFic = {innerHTML: '', appendChild(c){ cartes.push(c); }};
const rcountFic = {textContent: ''}, emptyFic = {style: {}}, resultsFic = {classList: {add(){}}};
const VUE_FIC = {jobId: 'j'};
function loadHistorique(cle, slot){ hist.push(cle); }
const document = {createElement(){
  const o = {style: {setProperty(){}}, className: '', _html: '', _ecouteurs: [],
    set innerHTML(v){ this._html = v; }, get innerHTML(){ return this._html; },
    querySelector(sel){ return {innerHTML: '', addEventListener(ev, fn){ o._ecouteurs.push([sel, ev, fn]); }}; }};
  return o; }};
"""


def _rendre(rows):
    node = shutil.which("node")
    if not node:
        pytest.skip("node absent")
    src = _source_js()
    morceaux = "\n".join(extraire_fonction(d, src) for d in _REND)
    prog = (_DECORS + morceaux + "\nrenderFic(" + json.dumps(rows) + ");\n"
            "for (const c of cartes) for (const [sel, ev, fn] of c._ecouteurs)"
            " if (sel === '.fic-detail') fn({target: {open: true}});\n"
            "process.stdout.write(JSON.stringify({cartes: cartes.map(c => ({html: c._html,"
            " ecouteurs: c._ecouteurs.map(e => e[0])})), hist}));")
    out = subprocess.run([node, "-e", prog], capture_output=True, text=True, encoding="utf-8",
                         timeout=60)
    assert out.returncode == 0, out.stderr
    return json.loads(out.stdout)


def _rapport_ecran(matrice, cle, n_mesures=5, livres=6, **kw):
    r = {"niche": {"sous_genre": "feel_good", "tropes": ["deuil_lumineux"], "decor": "village",
                   "query": "roman feel good village", "cle": cle},
         "demand_matrix": matrice, "n_livres_mesures": n_mesures,
         "books": [{"asin": f"A{i}", "title": f"T{i}", "bsr": 3000 + i} for i in range(livres)],
         "classifications": [], "depth_score": 0.7, "openness_score": 0.6, "saturation_trio": 0.3,
         "series_share": 0.2, "price_band": [3.0, 5.0, 7.0], "verdict": "", "autocomplete": None,
         "autocomplete_score": None, "asins_demandes": livres, "n_echecs": 0}
    r.update(kw)
    return r


def test_renderFic_une_carte_mesuree_montre_ses_chiffres_son_bouton_et_son_historique():
    sortie = _rendre([_rapport_ecran("pepite", "CLE-A")])
    (carte,) = sortie["cartes"]
    assert 'class="fic-cle fic-vide"' not in carte["html"] and "0,70" in carte["html"]
    assert "btn-verdict" in carte["html"] and "histslot" in carte["html"]
    assert ".fic-detail" in carte["ecouteurs"]
    assert sortie["hist"] == ["CLE-A"], "l'historique se charge sous la CLÉ du trio"


@pytest.mark.parametrize("etat,n", [("mesure_mince", 1), ("non_mesurable", 0)])
def test_renderFic_une_niche_non_concluante_n_a_ni_chiffre_ni_bouton_ni_historique(etat, n):
    sortie = _rendre([_rapport_ecran(etat, "CLE-B", n_mesures=n, livres=2)])
    (carte,) = sortie["cartes"]
    assert carte["html"].count('class="fic-cle fic-vide"') == 4
    assert "0,70" not in carte["html"] and "btn-verdict" not in carte["html"]
    assert "histslot" not in carte["html"]
    assert ".fic-detail" not in carte["ecouteurs"] and sortie["hist"] == []
    assert "📏" in carte["html"]


def test_renderFic_un_resultat_ancien_sans_cle_charge_l_historique_sous_sa_requete():
    ancien = _rapport_ecran("pepite", "x")
    ancien["niche"].pop("cle")
    assert _rendre([ancien])["hist"] == ["roman feel good village"]


def test_renderFic_deux_trios_de_meme_requete_chargent_chacun_leur_historique():
    sortie = _rendre([_rapport_ecran("pepite", "CLE-1"), _rapport_ecran("pepite", "CLE-2")])
    assert sortie["hist"] == ["CLE-1", "CLE-2"]
