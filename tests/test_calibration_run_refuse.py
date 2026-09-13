"""Le premier run RÉEL de calibration (2026-09-13) — et ce qu'il a montré.

Compte DataForSEO neuf, identifiants acceptés par `appendix/user_data`… et refusés par tout
le reste : le compte n'était pas VÉRIFIÉ. DataForSEO répond alors `40104` À LA RACINE du
JSON, sans aucune tâche. Le run a coûté 0 $ chez DataForSEO et 0,0905 $ chez Anthropic (le
classement, payé avant la première SERP), et il a mis deux défauts à nu :

1. **Le motif du refus était jeté.** `search` ne lisait que `tasks[0]` : absente, elle
   devenait `{}`, et l'écran a affiché « task_post refusé : None None » trente et une fois
   alors que la réponse disait en toutes lettres « Please verify your account ». Côté batch
   ASIN c'était pire : un refus de compte ne levait RIEN, ne créait aucune tâche et ne
   laissait aucune trace de sa cause — exactement ce qui arriverait à un solde épuisé en
   cours de run.
2. **La CLI conseillait de corriger les seuils sur un run à zéro mesure.** « ❌ porte NON
   franchie — corriger data/lowcontent_criteres.json » s'est affiché avec 0 niche
   calibrée. Suivi, ce conseil aurait fait régler les critères sur rien : la règle 3
   appliquée au conseil lui-même. Une porte INDÉCIDABLE n'est pas une porte ÉCHOUÉE.

Un contrôle préalable gratuit (`appendix/errors`, qui renvoie 40104 là où `user_data` laisse
passer) a été proposé, puis écarté par Baptiste : il n'est pas testé ici.

Aucun réseau : HTTP injecté, orchestrateur remplacé.
"""
import pytest

from lowcontent_validation import RapportCalibration, exporter_gabarit, rapport_calibration
from models import LowContentNiche, LowContentScored
from search_providers import DataForSEOProvider

# Forme RÉELLE relevée le 2026-09-13 (HTTP 403) sur `appendix/errors` : code et message à la
# racine, aucune tâche exploitable (absente ou nulle). `task_post` a produit le même
# « None None » trente et une fois.
_COMPTE_NON_VERIFIE = {
    "status_code": 40104,
    "status_message": "Please verify your account before using the API. You can complete "
                      "verification in the user panel: https://app.dataforseo.com/ .",
    "tasks": None,
}


def _fournisseur():
    return DataForSEOProvider(login="l", password="p")


# ══ 1. Le motif du refus arrive jusqu'à l'écran ═════════════════════════════════

def test_un_refus_de_COMPTE_dit_son_motif_cote_SERP():
    with pytest.raises(RuntimeError) as exc:
        _fournisseur().search("carnet de voyage",
                              post_json=lambda url, body: _COMPTE_NON_VERIFIE,
                              get_json=lambda url: {}, poll_interval=0)
    assert "40104" in str(exc.value)
    assert "verify your account" in str(exc.value)
    assert "None None" not in str(exc.value)


def test_un_refus_de_REQUETE_garde_le_motif_de_sa_tache():
    """Le motif le plus précis prime : la racine dit « Ok », la tâche dit pourquoi."""
    reponse = {"status_code": 20000, "status_message": "Ok.",
               "tasks": [{"status_code": 40501, "status_message": "Invalid Field."}]}
    with pytest.raises(RuntimeError) as exc:
        _fournisseur().search("carnet", post_json=lambda url, body: reponse,
                              get_json=lambda url: {}, poll_interval=0)
    assert "40501" in str(exc.value) and "Invalid Field" in str(exc.value)


def test_un_refus_de_COMPTE_n_est_plus_MUET_cote_ASIN():
    """Aucune exception, aucune tâche créée : le batch rendait des payloads vides et rien ne
    disait pourquoi. Il ne lève toujours pas — un lot refusé n'est pas facturé, et les
    autres lots doivent être relus (§5.29) — mais il DIT pourquoi."""
    out = _fournisseur().product_raw_batch(
        ["A1", "A2"], post_json=lambda url, body: _COMPTE_NON_VERIFIE,
        get_json=lambda url: {}, poll_interval=0)
    assert out.taches_creees == 0
    assert out["A1"] is None and out["A2"] is None
    assert len(out.lots_en_echec) == 1
    n, cause = out.lots_en_echec[0]
    assert n == 2 and "40104" in cause


def test_une_tache_ASIN_refusee_seule_est_comptee_avec_son_motif():
    """Le code 40200 est INVENTÉ pour le test : on n'a jamais observé en live le refus d'un
    solde épuisé, ni su s'il tombe à la racine ou par tâche. Ce qui est vérifié ici, c'est
    qu'un refus PAR TÂCHE garde son motif au lieu d'être sauté en silence."""
    def faux_post(url, body):
        return {"status_code": 20000, "status_message": "Ok.", "tasks": [
            {"status_code": 20100, "id": "T1", "data": {"asin": "A1"}},
            {"status_code": 40200, "status_message": "Payment Required."}]}

    def faux_get(url):
        return {"tasks": [{"status_code": 20000, "result": [{"asin": "A1"}]}]}

    out = _fournisseur().product_raw_batch(["A1", "A2"], post_json=faux_post,
                                           get_json=faux_get, poll_interval=0)
    assert out.taches_creees == 1
    assert out["A1"] is not None and out["A2"] is None
    assert (1, "40200 Payment Required.") in out.lots_en_echec


def test_le_motif_du_refus_ASIN_ARRIVE_a_l_ecran():
    """Par la VRAIE chaîne fournisseur -> enrich_asins -> progress, sans remplacer la
    fonction testée (§2.16 : remplacer ce qu'on teste, c'est tester le harnais)."""
    from fiction_serp_provider import enrich_asins
    prov = _fournisseur()
    prov._post = lambda url, body: _COMPTE_NON_VERIFIE
    prov._get = lambda url: {}
    etapes = []
    enrich_asins(["A1", "A2"], provider=prov, progress=etapes.append)
    assert any("40104" in e for e in etapes)


# ══ 2. Une porte INDÉCIDABLE n'est pas une porte ÉCHOUÉE ════════════════════════

def _scored(score, requete, **kw):
    n = LowContentNiche(niche=requete, requete_amazon=requete, rationale="r",
                        categorie="c", format_cle="journal_suivi", theme="t",
                        public="adulte")
    base = dict(niche=n, global_score=score, concurrence_mesuree=True,
                priorite="🟢 À analyser en priorité" if score >= 7.5
                else "🟡 Intéressant" if score >= 6.0 else "🔴 Faible")
    base.update(kw)
    return LowContentScored(**base)


_LU = dict(part_indie=0.7, redevance_estimee=3.1)     # le rayon a été lu
_ALIGNES = [8.2, 8.0, 7.8, 6.4, 6.1, 5.8, 3.1, 2.7, 2.4]
_INVERSES = list(reversed(_ALIGNES))                  # les mortes finissent en vert


def _paires(scores, **kw):
    etiquettes = ["bonne"] * 3 + ["mauvaise"] * 3 + ["morte"] * 3
    return [(e, _scored(s, f"{e}{i}", **kw))
            for i, (e, s) in enumerate(zip(etiquettes, scores))]


def test_le_run_du_13_septembre_est_INDECIDABLE():
    """La forme exacte du run : toutes les SERP tombées, donc 0 niche calibrée."""
    r = rapport_calibration(_paires(_ALIGNES, concurrence_mesuree=False, **_LU))
    assert r.n_calibrees == 0 and r.spearman is None
    assert r.porte_franchie is False
    assert r.porte_indecidable is True


def test_un_rayon_JAMAIS_LU_est_indecidable():
    r = rapport_calibration(_paires(_ALIGNES))        # ni part_indie, ni redevance
    assert r.porte_franchie is False and r.porte_indecidable is True


def test_une_morte_OMISE_rend_la_porte_indecidable():
    r = rapport_calibration(_paires(_ALIGNES, **_LU),
                            non_rendues=[("carnet de suivi migraine", "morte")])
    assert r.porte_franchie is False and r.porte_indecidable is True


def test_un_echec_MESURE_n_est_pas_indecidable():
    """Le SEUL cas où corriger `lowcontent_criteres.json` a un sens : tout a été mesuré, et
    le scoring contredit le terrain."""
    r = rapport_calibration(_paires(_INVERSES, **_LU))
    assert r.spearman is not None and r.spearman < 0.5
    assert r.porte_franchie is False
    assert r.porte_indecidable is False


def test_une_porte_franchie_n_est_pas_indecidable():
    r = rapport_calibration(_paires(_ALIGNES, **_LU))
    assert r.porte_franchie is True and r.porte_indecidable is False


def test_un_echec_mesure_mais_INCOMPLET_reste_indecidable():
    """Choix assumé, et c'est le plus discutable : le Spearman est calculé et mauvais, mais
    une « morte » manque. Conseiller de modifier les seuils sur une mesure incomplète, c'est
    risquer de les régler sur ce qui manquait. On relance d'abord."""
    r = rapport_calibration(_paires(_INVERSES, **_LU),
                            non_rendues=[("carnet de suivi migraine", "morte")])
    assert r.spearman is not None and r.spearman < 0.5
    assert r.porte_indecidable is True


def test_un_rapport_vierge_est_indecidable_par_defaut():
    """Défaut PESSIMISTE, comme `concurrence_mesuree=False` : un rapport qui n'a rien mesuré
    ne doit jamais pouvoir se lire « échec mesuré »."""
    assert RapportCalibration().porte_indecidable is True


# ══ 3. Ce que la CLI conseille réellement ═══════════════════════════════════════

_CONSEIL_CRITERES = "corriger data/lowcontent_criteres.json"


def _classeur(tmp_path):
    openpyxl = pytest.importorskip("openpyxl")
    chemin = exporter_gabarit(tmp_path / "v.xlsx")
    wb = openpyxl.load_workbook(chemin)
    wb.active["A7"], wb.active["C7"] = "carnet de voyage", "bonne"
    wb.save(chemin)
    return chemin


def _sortie_cli(tmp_path, monkeypatch, capsys, rapport):
    import build_lowcontent_validation_set as cli
    monkeypatch.setattr(cli, "construire_rapport", lambda *a, **k: rapport)
    code = cli.main(["--xlsx", str(_classeur(tmp_path)),
                     "--out", str(tmp_path / "r.json")])
    return code, capsys.readouterr().out


def test_la_CLI_ne_conseille_JAMAIS_les_criteres_sur_une_porte_indecidable(
        tmp_path, monkeypatch, capsys):
    rapport = RapportCalibration(n_requetes=31, n_calibrees=0, n_non_mesurees=31,
                                 porte_indecidable=True)
    code, sortie = _sortie_cli(tmp_path, monkeypatch, capsys, rapport)
    assert _CONSEIL_CRITERES not in sortie
    assert "INDÉCIDABLE" in sortie
    assert code == 2          # porte non franchie : le code de sortie, lui, ne change pas


def test_la_CLI_conseille_les_criteres_sur_un_echec_MESURE(tmp_path, monkeypatch, capsys):
    rapport = RapportCalibration(n_requetes=9, n_calibrees=9, spearman=-0.9,
                                 porte_indecidable=False)
    _, sortie = _sortie_cli(tmp_path, monkeypatch, capsys, rapport)
    assert _CONSEIL_CRITERES in sortie
