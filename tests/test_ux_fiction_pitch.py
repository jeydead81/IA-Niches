"""Pitch et mots-clés KDP dans l'analyse d'un trio fiction (demande de Baptiste, 2026-10-05).

« Sous la couverture, un pitch en 3-4 phrases max de ce que pourrait raconter le livre, et les mots
clés, idem que non fiction. » Vérifié en EXÉCUTANT les fonctions (harnais node, §2.10) :

- le pitch est lisible sans rien déplier, juste sous la couverture, et jamais « undefined » quand une
  analyse ANTÉRIEURE n'en porte pas (elle reste affichée, sans bloc vide) ;
- le texte d'un modèle est de la donnée : échappé, et ses tirets cadratins (« — ») deviennent des
  virgules comme dans le reste de l'interface ;
- le bouton « Mots-clés KDP » est offert en fiction, SANS le PDF (le dossier n'existe pas pour la
  fiction) ; un clic poste `type: fiction` avec la carte ET l'analyse, dans le travail affiché ;
- des mots-clés déjà générés (analyse rouverte) se réaffichent sans rien repayer.

FIXTURES INVENTÉES : aucune analyse fiction réelle avec pitch n'a été capturée.
"""
import json
import shutil
import subprocess

import pytest

from tests.js_harness import _source_js, appeler, extraire_fonction

_SLOT = ("esc", "verdictGrade", "verdictBlock", "verdictSlot", "ETATS_NON_CONCLUANTS_FIC",
         "verdictSlotFic")

PITCH = ("Léa reprend la librairie de sa grand-mère dans un port breton. Elle y trouve un carnet "
         "de commandes jamais livrées. Un rival veut racheter les murs avant l'hiver.")


def _analyse(**angle):
    a = {"angle": "ennemis dans une librairie de port", "pourquoi": "décor peu occupé",
         "risque": "trope très vu", "titre": "La Librairie des Marées",
         "sous_titre": "Ils se détestent. La tempête les enferme.",
         "direction_couverture": "port breton au crépuscule", "pitch": PITCH,
         "prix_suggere": "4,99 €", "requete_principale": "romance ennemis to lovers",
         "requetes_secondaires": ["romance bretagne"]}
    a.update(angle)
    return {"verdict": "Go", "confiance": 7, "facteur_decisif": "Rayon profond. Une place existe.",
            "angles": [a], "comparables": []}


def _rapport(**kw):
    r = {"niche": {"sous_genre": "feel_good", "tropes": ["deuil_lumineux"], "decor": "village",
                   "query": "roman feel good village", "cle": "CLE-1"},
         "demand_matrix": "pepite", "n_livres_mesures": 5, "books": [{"asin": "A1"}],
         "analyse": _analyse()}
    r.update(kw)
    return r


def _html(**kw):
    return appeler("verdictSlotFic", _rapport(**kw), dependances=_SLOT)


# ── Le pitch ────────────────────────────────────────────────────────────────────

def test_le_pitch_est_lisible_sans_deplier():
    html = _html()
    visible = html[:html.index('<details class="va-pli"')]
    assert PITCH in visible


def test_le_pitch_vient_juste_sous_la_couverture():
    html = _html()
    assert html.index("port breton au crépuscule") < html.index(PITCH) < html.index("Requêtes à tester")


def test_le_bloc_dit_ce_que_c_est():
    assert "Ce que pourrait raconter le livre" in _html()


def test_une_analyse_anterieure_sans_pitch_s_affiche_sans_bloc_vide():
    html = _html(analyse=_analyse(pitch=""))
    assert "va-pitch" not in html and "undefined" not in html and "null" not in html
    html2 = appeler("verdictSlotFic", _rapport(analyse={k: v for k, v in _analyse().items()
                                                        if k != "angles"} | {
        "angles": [{k: v for k, v in _analyse()["angles"][0].items() if k != "pitch"}]}),
        dependances=_SLOT)
    assert "va-pitch" not in html2 and "undefined" not in html2


def test_le_texte_du_modele_est_echappe():
    html = _html(analyse=_analyse(pitch="Elle ouvre <script>alert(1)</script> la porte."))
    assert "<script>" not in html and "&lt;script&gt;" in html


def test_les_tirets_cadratins_du_modele_deviennent_des_virgules():
    html = _html(analyse=_analyse(pitch="Elle part — il reste. Rien ne change."))
    assert "—" not in html[html.index("va-pitch"):html.index("Requêtes à tester")]
    assert "Elle part, il reste." in html


def test_le_pitch_n_existe_pas_hors_fiction():
    deps = ("esc", "verdictGrade")
    nf = appeler("verdictBlock", {"niche": "n", "verdict": _analyse()}, dependances=deps)
    assert "va-pitch" not in nf


# ── Les mots-clés ───────────────────────────────────────────────────────────────

def test_le_bouton_mots_cles_est_offert_en_fiction_sans_le_pdf():
    html = _html()
    assert "btn-kdp" in html and "kdpslot" in html
    assert "btn-pdf" not in html


def test_le_non_fiction_et_le_low_content_gardent_pdf_et_mots_cles():
    deps = ("esc", "verdictGrade")
    for niche in ("n", {"niche": "x"}):
        h = appeler("verdictBlock", {"niche": niche, "verdict": _analyse()}, dependances=deps)
        assert "btn-pdf" in h and "btn-kdp" in h


@pytest.mark.parametrize("niche,attendu", [
    ("tarot", "scout"),
    ({"niche": "registre", "requete_amazon": "registre du personnel", "format_cle": "x"}, "lowcontent"),
    ({"sous_genre": "feel_good", "tropes": [], "query": "q", "cle": "k"}, "fiction"),
])
def test_le_type_d_une_niche_se_lit_sur_sa_forme(niche, attendu):
    assert appeler("typeNiche", {"niche": niche}) == attendu


# ── Le clic, EXÉCUTÉ ────────────────────────────────────────────────────────────

_DECOR = """
const VUE_FIC = {jobId: 'job-9'}, VUE_NF = {jobId: 'job-n'}, VUE_LC = {jobId: 'job-l'};
const appels = [];
const slot = {innerHTML: '', querySelectorAll(){ return []; }};
const btn = {disabled: false, textContent: '🏷️ Mots-clés KDP', setAttribute(){}, removeAttribute(){}};
"""
_FONCTIONS = ("esc", "kdpBlock", "brancherCopie", "typeNiche", "cleNiche", "urlConservee",
              "noteNonConservee", "loadKdp")
_REPONSE = {"emplacements": ["romance ennemis amants", "librairie port breton"],
            "confirmes_par_amazon": ["romance ennemis amants"], "a_verifier": [], "rejetes": [],
            "sonde_indisponible": False, "_cout": {"usd": 0.006}, "_conserve": True}


def _jouer(corps_js: str):
    node = shutil.which("node")
    if not node:
        pytest.skip("node absent")
    src = _source_js()
    morceaux = "\n".join(extraire_fonction(d, src) for d in _FONCTIONS)
    prog = (_DECOR + morceaux + "\n(async () => {\n" + corps_js + "\n})().then("
            "r => process.stdout.write(JSON.stringify(r)), e => { console.error(e); process.exit(1); });")
    out = subprocess.run([node, "-e", prog], capture_output=True, text=True, encoding="utf-8",
                         timeout=60)
    assert out.returncode == 0, out.stderr
    return json.loads(out.stdout)


def test_le_clic_poste_la_carte_et_l_analyse_avec_type_fiction_dans_le_travail():
    sortie = _jouer("""
globalThis.fetch = async (url, opts) => { appels.push({url, corps: JSON.parse(opts.body)});
  return {ok: true, status: 200, json: async () => (""" + json.dumps(_REPONSE) + """)}; };
const r = """ + json.dumps(_rapport()) + """;
await loadKdp(r, slot, btn, VUE_FIC);
return {appels, mots: r.mots_cles && r.mots_cles.emplacements, slot: slot.innerHTML,
        residus: [r.mots_cles._cout, r.mots_cles._conserve]};
""")
    (a,) = sortie["appels"]
    assert a["url"].startswith("/api/kdp-keywords?job=job-9&cle=CLE-1")
    assert a["corps"]["type"] == "fiction"
    assert a["corps"]["analyse"]["angles"][0]["titre"] == "La Librairie des Marées"
    assert sortie["mots"] == ["romance ennemis amants", "librairie port breton"]
    assert "romance ennemis amants" in sortie["slot"] and sortie["residus"] == [None, None]


def test_le_type_low_content_et_non_fiction_sont_inchanges():
    sortie = _jouer("""
globalThis.fetch = async (url, opts) => { appels.push({url, corps: JSON.parse(opts.body)});
  return {ok: true, status: 200, json: async () => (""" + json.dumps(_REPONSE) + """)}; };
await loadKdp({niche: {niche: 'registre', requete_amazon: 'rq', format_cle: 'x'}}, slot, btn, VUE_LC);
await loadKdp({niche: 'tarot'}, slot, btn, VUE_NF);
return appels.map(a => [a.url, a.corps.type]);
""")
    assert sortie == [["/api/kdp-keywords?job=job-l&cle=rq", "lowcontent"],
                      ["/api/kdp-keywords?job=job-n&cle=tarot", None]]


def test_des_mots_cles_deja_generes_ne_sont_pas_repayes():
    sortie = _jouer("""
globalThis.fetch = async () => { appels.push(1); throw new Error('ne doit pas être appelé'); };
const r = """ + json.dumps(_rapport(mots_cles=_REPONSE)) + """;
await loadKdp(r, slot, btn, VUE_FIC);
return {appels: appels.length, slot: slot.innerHTML};
""")
    assert sortie["appels"] == 0 and "librairie port breton" in sortie["slot"]


def test_une_erreur_se_dit_et_le_bouton_reste_utilisable():
    sortie = _jouer("""
globalThis.fetch = async () => ({ok: false, status: 502, json: async () => ({})});
const r = """ + json.dumps(_rapport()) + """;
await loadKdp(r, slot, btn, VUE_FIC);
return {slot: slot.innerHTML, actif: !btn.disabled, texte: btn.textContent, mots: r.mots_cles === undefined};
""")
    assert "pas pu être générés" in sortie["slot"] and sortie["actif"] and sortie["mots"]


# ── Le branchement de la carte ──────────────────────────────────────────────────

def _brancher(r):
    node = shutil.which("node")
    if not node:
        pytest.skip("node absent")
    src = _source_js()
    morceaux = "\n".join(extraire_fonction(d, src) for d in
                         ("esc", "kdpBlock", "brancherCopie", "typeNiche", "cleNiche", "urlConservee",
                          "noteNonConservee", "loadKdp", "loadVerdictFic", "verdictGrade",
                          "verdictBlock", "verdictSlot", "ETATS_NON_CONCLUANTS_FIC",
                          "verdictSlotFic", "brancherActionsFic"))
    prog = (_DECOR + morceaux + """
const gestionnaires = {};
const bouton = {addEventListener(ev, fn){ gestionnaires.kdp = fn; }};
const emplacement = {innerHTML: '', querySelectorAll(){ return []; }};
const carte = {querySelector(s){ return s === '.btn-kdp' ? bouton : s === '.kdpslot' ? emplacement : null; }};
const r = """ + json.dumps(r) + """;
brancherActionsFic(r, carte);
process.stdout.write(JSON.stringify({clic: typeof gestionnaires.kdp, slot: emplacement.innerHTML}));
""")
    out = subprocess.run([node, "-e", prog], capture_output=True, text=True, encoding="utf-8",
                         timeout=60)
    assert out.returncode == 0, out.stderr
    return json.loads(out.stdout)


def test_la_carte_branche_le_bouton_mots_cles():
    assert _brancher(_rapport())["clic"] == "function"


def test_des_mots_cles_conserves_se_reaffichent_a_la_reouverture():
    sortie = _brancher(_rapport(mots_cles=_REPONSE))
    assert "librairie port breton" in sortie["slot"]


def test_sans_mots_cles_conserves_l_emplacement_reste_vide():
    assert _brancher(_rapport())["slot"] == ""
