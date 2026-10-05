"""Un solde épuisé (40200 « Payment Required ») est un refus de COMPTE, et l'écran le dit.

Run fiction du 2026-10-05 : « direct erreur, pas de résultats en 30 s ». Le compte DataForSEO était
à sec (solde −0,05 $, 1,01 $ déposé au total, lu gratuitement par `appendix/user_data`). Les cinq
recherches ont toutes été refusées « task_post refusé : 40200 Payment Required. », et le produit :

1. a envoyé les CINQ au lieu d'une : le refus, posé PAR TÂCHE, n'était pas reconnu comme un refus
   de compte (`RefusCompte`) — seul le refus posé à la racine l'était (« Non couvert : un refus de
   solde posé PAR TÂCHE », CLAUDE.md §2.14) ;
2. a rendu un travail « terminé » et un écran vide, sans un mot sur la cause : les avertissements
   de la progression disparaissent avec le panneau, et l'état vide dit « lancez une analyse ».

FORME : DÉDUITE du message du run (« 40200 Payment Required. », donc posé dans la tâche, puisque la
version posée à la racine aurait levé `RefusCompte` d'emblée) ; la réponse brute n'a pas été
capturée. Le statut de la RACINE est supposé 20000. Seul le statut de tâche compte pour le code.
"""
import json
import shutil
import subprocess

import pytest

from cost_tracker import CostTracker
from fiction_master import run_fiction_scout
from fiction_serp_provider import fetch_shelf_asins
from models import AutocompleteSignal, FictionNiche
from search_providers import DataForSEOProvider, RefusCompte, TaskPostRefuse
from tests.js_harness import _declaration, _source_js, extraire_fonction

_REFUS = {"status_code": 20000, "status_message": "Ok.",
          "tasks": [{"status_code": 40200, "status_message": "Payment Required."}]}


def _prov():
    return DataForSEOProvider(login="l", password="p", priority=2)


# ── Le fournisseur ──────────────────────────────────────────────────────────────

def test_un_solde_epuise_pose_dans_la_tache_est_un_refus_de_compte():
    appels = []

    def post(url, body):
        appels.append(url)
        return _REFUS

    with pytest.raises(RefusCompte) as e:
        _prov().search("roman feel good", post_json=post, get_json=lambda u: {}, poll_interval=0)
    assert "40200" in str(e.value) and len(appels) == 1


def test_un_autre_refus_par_tache_reste_un_refus_de_requete():
    """Pas d'élargissement sans observation : un code qu'on n'a jamais vu ne doit pas faire
    cesser les appels pour toutes les niches suivantes."""
    def post(url, body):
        return {"status_code": 20000, "tasks": [{"status_code": 40501,
                                                  "status_message": "Invalid Field."}]}

    with pytest.raises(TaskPostRefuse) as e:
        _prov().search("q", post_json=post, get_json=lambda u: {}, poll_interval=0)
    assert not isinstance(e.value, RefusCompte)


def test_le_refus_de_solde_n_est_pas_impute():
    """Aucune tâche créée : rien de facturé (même règle que tout `TaskPostRefuse`)."""
    class _Prov:
        priority = 2

        def search(self, *a, **k):
            raise RefusCompte("task_post refusé : 40200 Payment Required.")

    cost = CostTracker()
    niche = FictionNiche(sous_genre="feel_good", rayon="kindle", query="roman feel good")
    with pytest.raises(RefusCompte):
        fetch_shelf_asins(niche, _Prov(), cost=cost)
    assert cost.breakdown()["dataforseo_calls"] == 0


# ── L'orchestrateur : un seul appel, puis plus rien ─────────────────────────────

def _ideate(sous_genre_cle, n=8, **kw):
    return [FictionNiche(sous_genre=sous_genre_cle, tropes=[f"t{i}"], decor="d", rayon="kindle",
                         query=f"roman feel good requete{i}") for i in range(n)]


def _lancer(n=5):
    appels, msgs = [], []

    def serp(niche, **kw):
        appels.append(niche.query)
        raise RefusCompte("task_post refusé : 40200 Payment Required.")

    rapports = run_fiction_scout("feel_good", n_niches=n, ideate=_ideate, serp_fn=serp,
                                 enrich_fn=lambda a, **k: {}, classify=lambda *a, **k: [],
                                 probe=lambda n, **k: AutocompleteSignal(niche_query="q"),
                                 progress=msgs.append, use_cache=False)
    return rapports, appels, msgs


def test_un_solde_epuise_n_envoie_qu_une_recherche_sur_cinq():
    rapports, appels, _ = _lancer(5)
    assert len(appels) == 1 and rapports == []


def test_l_ecran_recoit_des_avertissements_sans_nom_de_fournisseur_ni_code():
    from progression_publique import liste_publique
    _, _, msgs = _lancer(5)
    publics = liste_publique(msgs)
    alertes = [m for m in publics if "⚠" in m]
    assert len(alertes) >= 2
    texte = " ".join(alertes)
    assert "indisponible" in texte.lower()
    for jargon in ("40200", "Payment", "DataForSEO", "task_post", "fournisseur"):
        assert jargon.lower() not in texte.lower(), jargon


# ── L'écran : un résultat vide dit POURQUOI ─────────────────────────────────────

def _src_jalons():
    return _declaration("PROG_JALONS", _source_js())


def _raison(type_, msgs):
    node = shutil.which("node")
    if not node:
        pytest.skip("node absent")
    src = _source_js()
    prog = (_src_jalons() + "\n" + extraire_fonction("progressionEtat", src) + "\n"
            + extraire_fonction("raisonSansResultat", src)
            + f"\nprocess.stdout.write(JSON.stringify(raisonSansResultat({json.dumps(type_)}, "
              f"{json.dumps(msgs)})));")
    out = subprocess.run([node, "-e", prog], capture_output=True, text=True, encoding="utf-8",
                         timeout=60)
    assert out.returncode == 0, out.stderr
    return json.loads(out.stdout)


def test_un_resultat_vide_dit_pourquoi_avec_les_avertissements_de_la_progression():
    msgs = ["Génération de 5 trios pour « feel_good »…", "5 trios générés.",
            "[1/5] Recherche « roman feel good ferme »…",
            "  ⚠ Service de données indisponible : les niches restantes ne seront pas mesurées.",
            "⚠ 5 niche(s) non mesurée(s) : service de données indisponible.",
            "Scout fiction terminé : aucun rayon exploitable."]
    r = _raison("fiction", msgs)
    assert "Service de données indisponible" in r and "5 niche(s) non mesurée(s)" in r
    assert "⚠" not in r and not r.startswith(" "), "le symbole et l'indentation sont retirés"


def test_sans_avertissement_il_n_y_a_pas_de_raison_inventee():
    assert _raison("fiction", ["5 trios générés.", "Scout fiction terminé (3 recherches)."]) == ""


def test_la_raison_est_bornee():
    msgs = [f"  ⚠ recherche impossible sur « requete {i} » : niche écartée." for i in range(40)]
    assert len(_raison("fiction", msgs)) < 600


def _vide_ou_raison(msgs, n_cartes=0, deja_erreur=False):
    """Exécute `videOuRaison` (node) avec un errbox et un état vide factices."""
    node = shutil.which("node")
    if not node:
        pytest.skip("node absent")
    src = _source_js()
    prog = "\n".join([_src_jalons(), extraire_fonction("progressionEtat", src),
                      extraire_fonction("raisonSansResultat", src),
                      extraire_fonction("videOuRaison", src)]) + """
const classes = new Set(%s ? ['on'] : []);
const errbox = {textContent: '', classList: {contains: c => classes.has(c),
                                              add: (...cs) => cs.forEach(c => classes.add(c))}};
const vide = {style: {display: 'none'}};
videOuRaison('fiction', {_msgs: %s}, errbox, vide, %d);
process.stdout.write(JSON.stringify({texte: errbox.textContent, classes: [...classes].sort(),
                                     vide: vide.style.display}));
""" % (json.dumps(deja_erreur), json.dumps(msgs), n_cartes)
    out = subprocess.run([node, "-e", prog], capture_output=True, text=True, encoding="utf-8",
                         timeout=60)
    assert out.returncode == 0, out.stderr
    return json.loads(out.stdout)


_MSGS_REFUS = ["5 trios générés.",
               "  ⚠ Service de données indisponible : les niches restantes ne seront pas mesurées.",
               "Scout fiction terminé : aucun rayon exploitable."]


def test_sans_carte_ni_erreur_la_raison_remplace_l_etat_vide_muet():
    r = _vide_ou_raison(_MSGS_REFUS)
    assert "Service de données indisponible" in r["texte"]
    assert r["classes"] == ["info", "on", "raison"] and r["vide"] == "none"


def test_sans_raison_l_etat_vide_s_affiche_comme_avant():
    r = _vide_ou_raison(["5 trios générés."])
    assert r["texte"] == "" and r["vide"] == "block" and r["classes"] == []


def test_avec_des_cartes_rien_n_est_ajoute():
    r = _vide_ou_raison(_MSGS_REFUS, n_cartes=3)
    assert r["texte"] == "" and r["vide"] == "none"


def test_une_erreur_deja_affichee_n_est_pas_ecrasee():
    r = _vide_ou_raison(_MSGS_REFUS, deja_erreur=True)
    assert r["texte"] == "" and r["vide"] == "none"


def test_les_trois_vues_appellent_videOuRaison():
    src = _source_js()
    for vue in ("VUE_NF", "VUE_FIC", "VUE_LC"):
        i = src.index("const " + vue + " = {")
        j = src.index("\n};", i)
        assert "videOuRaison(" in src[i:j], vue
