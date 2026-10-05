"""« Analyser cette niche » sur la page FICTION (accord de Baptiste, 2026-10-03).

Ce que l'écran doit tenir, vérifié en EXÉCUTANT les fonctions (harnais node, §2.10) et pas en
cherchant des chaînes dans le fichier (§5.26) :

- le bouton existe sur une carte mesurée, et PAS sur un rayon non mesuré (le serveur le refuse
  en 400 : un bouton qui rend une erreur est un bouton mort) ;
- l'analyse rouverte est affichée sans rien repayer : elle vit sous `analyse`, car `verdict`
  est déjà le texte du moteur, avec ses réserves (rayon incomplet, sous-genre fantôme) ;
- l'angle d'abord, trois livres à étudier dans le rayon réel, aucun PDF ni mot-clé KDP (hors
  périmètre v1 : leurs endpoints refusent la fiction, un bouton y serait mort) ;
- la clé de la niche dans le travail est la requête du trio.

FIXTURES INVENTÉES : aucune analyse fiction réelle n'a été capturée.
"""
import json
import shutil
import subprocess

import pytest

from tests.js_harness import _source_js, appeler, extraire_fonction

_SLOT = ("esc", "verdictGrade", "verdictBlock", "verdictSlot", "ETATS_NON_CONCLUANTS_FIC",
         "verdictSlotFic")

_TRIO = {"sous_genre": "romance_contemporaine", "tropes": ["enemies_to_lovers"],
         "decor": "small_town", "query": "romance ennemis to lovers petite ville bretonne"}


def _rapport(**kw):
    base = {"niche": _TRIO, "demand_matrix": "pepite",
            "books": [{"asin": "B000000001", "title": "Ennemis à Saint-Malo", "bsr": 1200}],
            "verdict": "pepite. Saturation du trio mesurée uniquement sur les livres classés."}
    base.update(kw)
    return base


def _analyse(**kw):
    a = {"verdict": "Go", "confiance": 7,
         "facteur_decisif": "Rayon profond et peu saturé. Une place existe sous le top 3.",
         "saturation": "Un tiers du rayon reprend le trio", "faux_concurrent": "aucun",
         "differenciation": "Le huis clos breton",
         "angles": [{"angle": "ennemis dans une librairie de port", "pourquoi": "décor peu occupé",
                     "risque": "trope très vu", "titre": "La Librairie des Marées",
                     "sous_titre": "Ils se détestent. La tempête les enferme.",
                     "direction_couverture": "port breton au crépuscule",
                     "prix_suggere": "4,99 €", "requete_principale": "romance ennemis to lovers",
                     "requetes_secondaires": ["romance bretagne"]}],
         "comparables": [{"asin": "B000000001", "titre": "Ennemis à Saint-Malo",
                          "pourquoi": "le meilleur rang du rayon"},
                         {"asin": "B000000002", "titre": "Le café des rivaux",
                          "pourquoi": "même trio, prix voisin"}]}
    a.update(kw)
    return a


# ── Le bouton ───────────────────────────────────────────────────────────────────

def test_une_carte_mesuree_offre_le_bouton_d_analyse():
    html = appeler("verdictSlotFic", _rapport(), dependances=_SLOT)
    assert "btn-verdict" in html and "Analyser cette niche" in html


def test_un_rayon_non_mesure_n_offre_pas_le_bouton():
    """Le serveur refuse (400) : le bouton serait mort. Et la carte dit déjà « à relancer »."""
    html = appeler("verdictSlotFic", _rapport(demand_matrix="non_mesurable"), dependances=_SLOT)
    assert html == ""


def test_un_rayon_sans_livre_n_offre_pas_le_bouton():
    html = appeler("verdictSlotFic", _rapport(books=[], demand_matrix=""), dependances=_SLOT)
    assert html == ""


def test_le_bouton_promet_des_livres_du_rayon_pas_des_mots_cles():
    html = appeler("verdictSlotFic", _rapport(), dependances=_SLOT)
    assert "livres" in html.lower()


# ── L'analyse ───────────────────────────────────────────────────────────────────

def test_l_analyse_deja_faite_est_affichee_sans_bouton_pour_la_refaire():
    html = appeler("verdictSlotFic", _rapport(analyse=_analyse()), dependances=_SLOT)
    assert "La Librairie des Marées" in html and "btn-verdict" not in html


def test_le_texte_du_moteur_n_est_pas_pris_pour_l_analyse():
    """`verdict` est une CHAÎNE sur une carte fiction : si l'écran la lisait comme l'analyse,
    il rendrait un bloc vide à la place du bouton."""
    html = appeler("verdictSlotFic", _rapport(), dependances=_SLOT)
    assert "vbox" not in html


def test_l_angle_vient_avant_le_raisonnement():
    html = appeler("verdictSlotFic", _rapport(analyse=_analyse()), dependances=_SLOT)
    assert html.index("La Librairie des Marées") < html.index("Facteur décisif")


def test_trois_livres_a_etudier_pointent_vers_le_rayon_reel():
    html = appeler("verdictSlotFic", _rapport(analyse=_analyse()), dependances=_SLOT)
    assert "https://www.amazon.fr/dp/B000000001" in html
    assert "Ennemis à Saint-Malo" in html and "le meilleur rang du rayon" in html
    visible = html[:html.index('<details class="va-pli"')]
    assert "Ennemis à Saint-Malo" in visible, "les comparables se lisent sans déplier"


def test_ni_pdf_ni_mots_cles_kdp_en_fiction():
    html = appeler("verdictSlotFic", _rapport(analyse=_analyse()), dependances=_SLOT)
    assert "btn-pdf" not in html and "btn-kdp" not in html and "kdpslot" not in html


def test_aucun_comparable_ne_laisse_ni_trou_ni_titre_vide():
    html = appeler("verdictSlotFic", _rapport(analyse=_analyse(comparables=[])), dependances=_SLOT)
    assert "undefined" not in html and "null" not in html and "va-comp" not in html


def test_le_prix_et_le_risque_restent_visibles_sans_deplier():
    html = appeler("verdictSlotFic", _rapport(analyse=_analyse()), dependances=_SLOT)
    visible = html[:html.index('<details class="va-pli"')]
    assert "4,99 €" in visible and "trope très vu" in visible


def test_pas_de_redevance_ni_de_specification_d_interieur_en_fiction():
    html = appeler("verdictSlotFic", _rapport(analyse=_analyse()), dependances=_SLOT)
    assert "Intérieur" not in html and "Source réglementaire" not in html


def test_le_non_fiction_et_le_low_content_gardent_leurs_boutons():
    deps = ("esc", "verdictGrade")
    v = _analyse()
    assert "btn-pdf" in appeler("verdictBlock", {"niche": "n", "verdict": v}, dependances=deps)
    assert "btn-kdp" in appeler("verdictBlock", {"niche": {"niche": "x"}, "verdict": v},
                                dependances=deps)


# ── La clé de la niche dans le travail ──────────────────────────────────────────

def test_la_cle_d_un_trio_est_sa_requete():
    assert appeler("cleNiche", {"niche": _TRIO}) == _TRIO["query"]


def test_la_cle_du_non_fiction_et_du_low_content_est_inchangee():
    assert appeler("cleNiche", {"niche": "tarot"}) == "tarot"
    assert appeler("cleNiche", {"niche": {"niche": "n", "requete_amazon": "rq"}}) == "rq"


# ── Le branchement : exécuté, pas lu ────────────────────────────────────────────

def _jouer(corps_js: str) -> dict:
    node = shutil.which("node")
    if not node:
        pytest.skip("node absent")
    src = _source_js()
    morceaux = [extraire_fonction(d, src) for d in
                ("esc", "verdictGrade", "verdictBlock", "verdictSlot", "ETATS_NON_CONCLUANTS_FIC", "verdictSlotFic",
                 "cleNiche", "urlConservee", "noteNonConservee", "brancherActionsFic",
                 "loadVerdictFic")]
    # Les doublures vivent au NIVEAU DU PROGRAMME : les fonctions testées lisent `VUE_FIC` et
    # `fetch` comme des globales, pas comme des variables de l'IIFE ci-dessous.
    prog = _DECOR + "\n".join(morceaux) + "\n(async () => {\n" + corps_js + "\n})().then(" \
        "r => process.stdout.write(JSON.stringify(r)), e => { console.error(e); process.exit(1); });"
    out = subprocess.run([node, "-e", prog], capture_output=True, text=True, encoding="utf-8",
                         timeout=30)
    assert out.returncode == 0, out.stderr
    return json.loads(out.stdout)


_DECOR = """
const VUE_FIC = {jobId: 'job-42'};
const appels = [];
const slot = {innerHTML: ''};
const para = {classList: {add(){}}, setAttribute(){}, textContent: ''};
const btn = {disabled: false, textContent: 'Analyser cette niche (~10 s)',
             setAttribute(){}, removeAttribute(){}};
const carte = {querySelector(s){ return s === '.verdictslot' ? slot : s === '.vask p' ? para : null; }};
"""


def test_le_clic_poste_un_type_fiction_et_range_l_analyse_dans_le_travail():
    sortie = _jouer("""
globalThis.fetch = async (url, opts) => { appels.push({url, corps: JSON.parse(opts.body)});
  return {ok: true, status: 200, json: async () => (""" + json.dumps(_analyse()) + """ )}; };
const r = """ + json.dumps(_rapport()) + """;
await loadVerdictFic(r, carte, btn);
return {appels, analyse: r.analyse && r.analyse.verdict, slot: slot.innerHTML,
        verdict_moteur: typeof r.verdict};
""")
    (appel,) = sortie["appels"]
    assert appel["url"].startswith("/api/verdict?job=job-42&cle=")
    assert "romance%20ennemis%20to%20lovers" in appel["url"]
    assert appel["corps"]["type"] == "fiction"
    assert sortie["analyse"] == "Go" and "La Librairie des Marées" in sortie["slot"]
    assert sortie["verdict_moteur"] == "string", "le texte du moteur ne doit pas être écrasé"


def test_une_limite_atteinte_se_dit_comme_une_limite():
    sortie = _jouer("""
globalThis.fetch = async () => ({ok: false, status: 429, json: async () => ({detail: 'x'})});
const r = """ + json.dumps(_rapport()) + """;
await loadVerdictFic(r, carte, btn);
return {texte: para.textContent, actif: !btn.disabled, analyse: r.analyse === undefined};
""")
    assert "Limite" in sortie["texte"] and "Rien n" in sortie["texte"]
    assert sortie["actif"] and sortie["analyse"]


def test_un_echec_de_conservation_est_dit():
    sortie = _jouer("""
globalThis.fetch = async () => ({ok: true, status: 200,
  json: async () => Object.assign(""" + json.dumps(_analyse()) + """, {_conserve: false})});
const r = """ + json.dumps(_rapport()) + """;
await loadVerdictFic(r, carte, btn);
return {slot: slot.innerHTML, cout: r.analyse._cout === undefined && r.analyse._conserve === undefined};
""")
    assert "pas pu être enregistrée" in sortie["slot"] and sortie["cout"]


# ── La carte ────────────────────────────────────────────────────────────────────

def test_la_carte_fiction_porte_l_emplacement_de_l_analyse_et_le_branche():
    src = extraire_fonction("renderFic")
    assert 'class="verdictslot"' in src and "verdictSlotFic(r)" in src
    assert "brancherActionsFic(r, card)" in src


# ── Les notes du CODE ne sont pas l'accroche du raisonnement ────────────────────

def test_les_notes_du_code_sortent_de_l_accroche_du_facteur_decisif():
    """`fiction_verdict` PRÉFIXE le facteur décisif de ses constats (rayon incomplet, livre
    écarté). Sans les isoler, la première phrase lue sous « Facteur décisif » serait un constat
    technique, pas le jugement du modèle."""
    f = ("Rayon incomplet : 3 fiche(s) du rayon n'ont pas pu être lues, « Go » ramené à « Go "
         "prudent ». 1 livre(s) cité(s) par l'IA n'appartiennent pas au rayon mesuré : écarté(s). "
         "Le rayon est profond et le trio peu repris. Une place existe sous le top 3.")
    html = appeler("verdictSlotFic", _rapport(analyse=_analyse(facteur_decisif=f)),
                   dependances=_SLOT)
    accroche = html[html.index('class="vf-accroche"'):][:160]
    assert "Le rayon est profond" in accroche
    assert html.count('class="vf-note"') == 2


def test_un_rayon_incomplet_se_dit_avec_un_avertissement_visible():
    f = "Rayon incomplet : 3 fiche(s) du rayon n'ont pas pu être lues. Le rayon est profond."
    html = appeler("verdictSlotFic", _rapport(analyse=_analyse(facteur_decisif=f)),
                   dependances=_SLOT)
    note = html[html.index('class="vf-note"'):][:120]
    assert "⚠️" in note and "Rayon incomplet" in note
    assert html.index("Rayon incomplet") < html.index('<details class="va-pli"><summary>🧠')
