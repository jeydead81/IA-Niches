"""R11 + R10 — la CLI de calibration refuse AVANT de dépenser, et le dit.

Le run 4 (0,7208 $) est parti alors que les 185 fiches en cache n'avaient AUCUNE pagination :
la porte était indécidable avant le premier centime, et rien ne le calculait. Deux arrêts
gratuits, tous deux en code de sortie 5 (« refus avant toute dépense ») :

- R11, le DEVIS : SERP et fiches à payer lues dans le cache tel que le master le lira,
  poste LLM calculé comme `devis.py`, fiches en cache INUTILISABLES (pages None) comptées.
  Refus si le total atteint `--plafond` (même comparaison `>=` que `CostTracker.verifier`),
  ou si aucune fiche utile n'est ni en cache ni à payer.
- R10, la SONDE : une re-sonde gratuite, puis arrêt AVANT l'appel Anthropic si toutes les
  sondes restent muettes ou si une « morte » le reste — la porte serait certainement
  indécidable (décision de Baptiste).

Données : classeur RÉEL `99-logs/validation-lc.xlsx`, restreint aux 31 requêtes du lot
« run 4 » (lecture seule ; 20 neuves y ont été ajoutées le 2026-09-15), captures
RÉELLES v2, état RÉEL du cache après le run 4 (`fixtures/cache_calibration_run4_reel.json`). Inventés et déclarés : la forme des SERP
(`outils_calibration`), l'altération « sans pages », les runs espions. Aucun réseau : le
master réel est remplacé par un espion qui LÈVE s'il est appelé.
"""
import json
from functools import partial

import pytest

import build_lowcontent_validation_set as cli
from autocomplete_expand import Suggestion
from cost_tracker import CostTracker
from devis import cout_max_estime
from lowcontent_validation import SondeIndisponible
from models import LowContentNiche, LowContentScored
from tests.outils_calibration import (cache_run4_reel, cache_seme, etiquetees_run4,
                                      xlsx_run4)


@pytest.fixture(autouse=True)
def _aucun_run_reel(monkeypatch):
    """Le vrai master ne doit JAMAIS partir d'ici : il appellerait le réseau. `wraps` garde
    sa signature, que le devis lit pour connaître N (jamais recopié)."""
    import functools
    import lowcontent_master

    @functools.wraps(lowcontent_master.run_lowcontent_scout)
    def interdit(**kw):
        raise AssertionError("run_lowcontent_scout appelé : la CLI aurait dépensé")

    monkeypatch.setattr(lowcontent_master, "run_lowcontent_scout", interdit)


def _espion_construire(monkeypatch):
    appels = []

    def construire(*a, **k):
        appels.append(k)
        from lowcontent_validation import RapportCalibration
        return RapportCalibration(n_requetes=31)

    monkeypatch.setattr(cli, "construire_rapport", construire)
    return appels


def _sonde_interdite(monkeypatch):
    def interdit(*a, **k):
        raise AssertionError("sonde lancée malgré le refus du devis")
    monkeypatch.setattr(cli, "sonder", interdit)


# ══ R11 — le devis ═══════════════════════════════════════════════════════════════

def test_R11_le_devis_REFUSE_quand_les_fiches_en_cache_n_ont_pas_de_pages(
        tmp_path, monkeypatch, capsys):
    requetes = [e.requete for e in etiquetees_run4()]
    chemin = tmp_path / "cache.db"
    cache_seme(chemin, requetes, sans_pages=True)
    appels = _espion_construire(monkeypatch)
    _sonde_interdite(monkeypatch)
    sortie = tmp_path / "r.json"

    code = cli.main(["--xlsx", str(xlsx_run4(tmp_path)), "--cache", str(chemin), "--out", str(sortie)])

    out = capsys.readouterr().out
    assert code == 5
    assert appels == []
    assert "--purger-fiches-sans-pages" in out
    r = json.loads(sortie.read_text(encoding="utf-8"))
    assert r["porte_franchie"] is False and r["porte_indecidable"] is True
    assert any("rien n'a été dépensé" in a for a in r["avertissements"])
    assert r["devis"]["n_serp_cache"] == 31 and r["devis"]["n_asin_a_payer"] == 0
    assert r["devis"]["n_asin_cache_sans_pages"] == 8 and r["devis"]["n_asin_cache_utiles"] == 0


def test_R11_photo_du_run_4_sur_l_etat_REEL_du_cache(tmp_path):
    """État RÉEL du cache après le run 4 (fixture extraite en lecture seule) : 31 SERP en
    cache, 185 fiches toutes sans pagination, rien à payer — le devis doit refuser en nommant
    la purge. Inconditionnel : aucune branche ne recalcule la règle qu'il vérifie."""
    copie = cache_run4_reel(tmp_path)
    requetes = [e.requete for e in etiquetees_run4()]
    d = cli.devis_calibration(requetes, cli.ouvrir_cache_lecture(copie), plafond_usd=0.72)
    assert (d.n_serp_cache, d.n_serp_a_payer) == (31, 0)
    assert (d.n_asin_cache_sans_pages, d.n_asin_cache_utiles, d.n_asin_a_payer) == (185, 0, 0)
    assert d.refus is not None and "--purger-fiches-sans-pages" in d.refus


def test_R11_un_plafond_trop_bas_refuse_avant_la_sonde_et_le_run(tmp_path, monkeypatch):
    appels = _espion_construire(monkeypatch)
    _sonde_interdite(monkeypatch)
    code = cli.main(["--xlsx", str(xlsx_run4(tmp_path)), "--cache", str(tmp_path / "vide.db"),
                     "--out", str(tmp_path / "r.json"), "--plafond", "0.01"])
    assert code == 5 and appels == []


def test_R11_cache_vide_le_devis_vaut_celui_du_produit_et_n_ecrit_rien(tmp_path):
    requetes = [e.requete for e in etiquetees_run4()]
    absent = tmp_path / "absent.db"
    d = cli.devis_calibration(requetes, cli.ouvrir_cache_lecture(absent), plafond_usd=2.0)
    assert d.total_usd == pytest.approx(cout_max_estime("lowcontent", {"n_search": 31}))
    assert d.total_usd == pytest.approx(0.7792, abs=1e-4)
    assert d.n_serp_a_payer == 31 and d.n_asin_a_payer == 186
    import inspect
    from lowcontent_master import run_lowcontent_scout
    assert d.n_asin_par_requete == inspect.signature(
        run_lowcontent_scout).parameters["n_enrich_per_niche"].default
    assert d.refus is None
    assert not absent.exists(), "le devis a créé un fichier de cache"


def test_R11_le_devis_ne_modifie_pas_le_cache_qu_il_lit(tmp_path):
    from tests.outils_calibration import cles
    requetes = [e.requete for e in etiquetees_run4()]
    chemin = tmp_path / "cache.db"
    cache_seme(chemin, requetes[:5], sans_pages=False)
    avant = cles(chemin)
    d = cli.devis_calibration(requetes, cli.ouvrir_cache_lecture(chemin), plafond_usd=2.0)
    assert cles(chemin) == avant
    # 5 SERP en cache : il reste 26 SERP et 26 × 6 fiches à payer. Des 8 captures réelles,
    # B0FS7JQNJ6 n'a PAS de pagination sur amazon.fr : 7 utiles, 1 sans pages.
    assert d.n_serp_cache == 5 and d.n_asin_cache_utiles == 7
    assert d.n_asin_cache_sans_pages == 1
    assert d.n_asin_a_payer == 26 * 6 and d.refus is None


def test_R11_des_fiches_utiles_en_cache_laissent_partir_le_run(tmp_path, monkeypatch):
    """Cache chaud et exploitable : SERP et ASIN à 0 $, seul le poste LLM reste au devis."""
    requetes = [e.requete for e in etiquetees_run4()]
    chemin = tmp_path / "cache.db"
    cache_seme(chemin, requetes, sans_pages=False)
    appels = _espion_construire(monkeypatch)
    code = cli.main(["--xlsx", str(xlsx_run4(tmp_path)), "--cache", str(chemin),
                     "--out", str(tmp_path / "r.json"), "--plafond", "0.72"])
    assert len(appels) == 1 and code != 5
    assert appels[0]["cache_path"] == str(chemin)


# ══ R10 — la sonde ═══════════════════════════════════════════════════════════════

def _espion_run():
    """Rend, pour chaque requête injectée, une niche scorée dont la demande reprend la
    MESURE de la sonde — c'est ce que fait le master en mode classement."""
    appels = []

    def run(**kw):
        appels.append(kw)
        out = []
        for s in kw["expand_fn"]():
            n = LowContentNiche(niche=s.requete, requete_amazon=s.requete, rationale="r",
                                categorie="c", format_cle="journal_suivi", theme="t",
                                public="adulte", n_enfants_autocomplete=s.n_enfants)
            out.append(LowContentScored(niche=n, global_score=5.0, concurrence_mesuree=True,
                                        priorite="🔴 Faible"))
        return out

    run.appels = appels
    return run


def _expand_selon(pannes: dict):
    """`pannes[requete]` = nombre d'appels qui lèvent avant de répondre (inf = toujours)."""
    vus = {}

    def expand(seed, **kw):
        vus[seed] = vus.get(seed, 0) + 1
        if vus[seed] <= pannes.get(seed, 0):
            raise TimeoutError("503 simulé")
        return [Suggestion(requete=f"{seed} {i}", parent=seed, profondeur=1)
                for i in range(3)]

    expand.vus = vus
    return expand


def test_R10_une_sonde_qui_leve_PARTOUT_arrete_avant_tout_appel_paye():
    etq = etiquetees_run4()
    run, cost = _espion_run(), CostTracker(plafond_usd=2.0)
    expand = _expand_selon({e.requete: float("inf") for e in etq})
    with pytest.raises(SondeIndisponible):
        cli.construire_rapport(etq, run=run, cost=cost,
                               sonde=partial(cli.sonder, expand_fn=expand, pause=0))
    assert run.appels == []
    assert cost.total_usd() == 0
    assert all(n == 2 for n in expand.vus.values()), "une et une seule re-sonde"


def test_R10_une_seule_MORTE_muette_deux_fois_arrete_et_est_nommee():
    etq = etiquetees_run4()
    morte = next(e.requete for e in etq if e.etiquette == "morte")
    run = _espion_run()
    expand = _expand_selon({morte: 2})
    with pytest.raises(SondeIndisponible) as exc:
        cli.construire_rapport(etq, run=run,
                               sonde=partial(cli.sonder, expand_fn=expand, pause=0))
    assert morte in str(exc.value)
    assert run.appels == []


def test_R10_une_morte_muette_puis_qui_repond_laisse_partir_le_run():
    etq = etiquetees_run4()
    morte = next(e.requete for e in etq if e.etiquette == "morte")
    run = _espion_run()
    expand = _expand_selon({morte: 1})
    r = cli.construire_rapport(etq, run=run,
                               sonde=partial(cli.sonder, expand_fn=expand, pause=0))
    assert len(run.appels) == 1
    assert r.n_demande_non_mesuree == 0


def test_R10_une_BONNE_muette_apres_re_sonde_ne_bloque_pas_et_se_compte():
    etq = etiquetees_run4()
    bonne = next(e.requete for e in etq if e.etiquette == "bonne")
    run = _espion_run()
    expand = _expand_selon({bonne: float("inf")})
    r = cli.construire_rapport(etq, run=run,
                               sonde=partial(cli.sonder, expand_fn=expand, pause=0))
    assert len(run.appels) == 1
    assert r.n_demande_non_mesuree == 1


def test_R10_la_CLI_ecrit_un_rapport_RIEN_DEPENSE_et_sort_en_5(tmp_path, monkeypatch, capsys):
    def muette(requetes, **kw):
        return [Suggestion(requete=q, parent="", profondeur=0, n_enfants=None)
                for q in requetes]

    monkeypatch.setattr(cli, "sonder", muette)
    sortie = tmp_path / "r.json"
    code = cli.main(["--xlsx", str(xlsx_run4(tmp_path)), "--cache", str(tmp_path / "vide.db"),
                     "--out", str(sortie)])
    assert code == 5
    r = json.loads(sortie.read_text(encoding="utf-8"))
    texte = " ".join(r["avertissements"])
    assert "rien n'a été dépensé" in texte and "aucun appel Anthropic" in texte
    assert "sera repayé" not in texte
    assert r["porte_indecidable"] is True


def test_R10_un_rapport_existant_n_est_JAMAIS_ecrase(tmp_path, monkeypatch):
    monkeypatch.setattr(cli, "sonder", lambda rs, **kw: [
        Suggestion(requete=q, parent="", profondeur=0, n_enfants=None) for q in rs])
    sortie = tmp_path / "rapport.json"
    sortie.write_text('{"run": 4}', encoding="utf-8")
    cli.main(["--xlsx", str(xlsx_run4(tmp_path)), "--cache", str(tmp_path / "vide.db"),
              "--out", str(sortie)])
    assert sortie.read_text(encoding="utf-8") == '{"run": 4}'
    nouveaux = [p for p in tmp_path.glob("rapport*.json") if p != sortie]
    assert len(nouveaux) == 1
