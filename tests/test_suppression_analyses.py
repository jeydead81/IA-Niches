"""Supprimer une analyse (Baptiste, 2026-10-03 : « il faudrait pouvoir supprimer les analyses »).

Ce qui est supprimé : le TRAVAIL (ses étapes, son résultat, les verdicts et mots-clés qu'on y a
rangés) dans `jobs.db`. Ce qui ne l'est PAS, volontairement :
- la consommation (`usage.db`) : l'analyse a eu lieu et coûté, la supprimer de l'écran ne
  rembourse rien et ne doit surtout pas libérer d'unité de plafond (règle 4 : sinon supprimer
  puis relancer contournerait le plafond mensuel) ;
- l'historique d'évolution des niches (`history.db`) : c'est une série dans le temps, partagée
  par toutes les analyses de la même niche.

Règles : on ne supprime que SES analyses (404, jamais 403, pour ne pas confirmer qu'un
identifiant existe), pas une analyse en cours (409 : son thread écrirait ensuite dans le vide),
et la route passe par `origine_sure` comme tout ce qui modifie des données.
"""
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "web"))

from jobs import JobStore  # noqa: E402


def _store(tmp_path):
    return JobStore(tmp_path / "jobs.db")


# ── JobStore.supprimer ───────────────────────────────────────────────────────────

def test_supprimer_efface_un_travail_termine(tmp_path):
    s = _store(tmp_path)
    jid = s.create("scout", {}, user_id="u1")
    s.finish(jid, [{"niche": "t"}], {})
    assert s.supprimer(jid, "u1") == "supprime"
    assert s.get(jid) is None


def test_supprimer_efface_un_travail_en_echec(tmp_path):
    s = _store(tmp_path)
    jid = s.create("scout", {}, user_id="u1")
    s.fail(jid, "boom")
    assert s.supprimer(jid, "u1") == "supprime"


@pytest.mark.parametrize("etat", ["en_attente", "en_cours"])
def test_supprimer_refuse_une_analyse_qui_n_est_pas_finie(tmp_path, etat):
    """Son thread écrirait ensuite dans une ligne disparue, et l'usage réservé ne serait
    jamais soldé proprement."""
    s = _store(tmp_path)
    jid = s.create("scout", {}, user_id="u1")
    if etat == "en_cours":
        s.start(jid)
    assert s.supprimer(jid, "u1") == "en_cours"
    assert s.get(jid) is not None


def test_supprimer_refuse_le_travail_d_un_autre_utilisateur(tmp_path):
    s = _store(tmp_path)
    jid = s.create("scout", {}, user_id="u1")
    s.finish(jid, [], {})
    assert s.supprimer(jid, "intrus") == "introuvable"
    assert s.get(jid) is not None


def test_supprimer_un_travail_inconnu_ne_leve_pas(tmp_path):
    assert _store(tmp_path).supprimer("nope", "u1") == "introuvable"


def test_supprimer_ne_touche_pas_aux_autres_travaux(tmp_path):
    s = _store(tmp_path)
    a = s.create("scout", {}, user_id="u1"); s.finish(a, [], {})
    b = s.create("scout", {}, user_id="u1"); s.finish(b, [], {})
    s.supprimer(a, "u1")
    assert s.get(b) is not None


# ── L'endpoint ───────────────────────────────────────────────────────────────────

def _client(monkeypatch, tmp_path):
    pytest.importorskip("httpx")
    from fastapi.testclient import TestClient
    import server
    from tests.conftest import isoler_bases, ouvrir_session
    isoler_bases(monkeypatch, server, tmp_path)
    c = TestClient(server.app, raise_server_exceptions=False)
    uid = ouvrir_session(c)
    return c, server, uid


def _job(server, uid, termine=True):
    s = JobStore(server._JOBS_DB)
    jid = s.create("scout", {}, user_id=uid)
    if termine:
        s.finish(jid, [{"niche": "t"}], {})
    return jid


def test_delete_efface_l_analyse_et_rend_204(monkeypatch, tmp_path):
    c, server, uid = _client(monkeypatch, tmp_path)
    jid = _job(server, uid)
    assert c.delete(f"/api/jobs/{jid}").status_code == 204
    assert c.get(f"/api/jobs/{jid}").status_code == 404
    assert all(j["id"] != jid for j in c.get("/api/jobs").json())


def test_delete_d_une_analyse_en_cours_rend_409(monkeypatch, tmp_path):
    c, server, uid = _client(monkeypatch, tmp_path)
    jid = _job(server, uid, termine=False)
    r = c.delete(f"/api/jobs/{jid}")
    assert r.status_code == 409 and "en cours" in r.json()["detail"].lower()
    assert c.get(f"/api/jobs/{jid}").status_code == 200


def test_delete_du_travail_d_autrui_rend_404_et_ne_supprime_rien(monkeypatch, tmp_path):
    """404 et non 403 : distinguer les deux confirmerait que l'identifiant existe."""
    from fastapi.testclient import TestClient
    from tests.conftest import ouvrir_session
    c, server, uid = _client(monkeypatch, tmp_path)
    jid = _job(server, uid)
    monkeypatch.setenv("INSCRIPTIONS_OUVERTES", "1")
    intrus = TestClient(server.app, raise_server_exceptions=False)
    ouvrir_session(intrus, "intrus@example.com")
    assert intrus.delete(f"/api/jobs/{jid}").status_code == 404
    assert c.get(f"/api/jobs/{jid}").status_code == 200


def test_delete_exige_une_session(monkeypatch, tmp_path):
    from fastapi.testclient import TestClient
    c, server, uid = _client(monkeypatch, tmp_path)
    jid = _job(server, uid)
    anonyme = TestClient(server.app, raise_server_exceptions=False)
    assert anonyme.delete(f"/api/jobs/{jid}").status_code == 401


def test_delete_depuis_un_autre_site_est_refuse(monkeypatch, tmp_path):
    """`origine_sure` : le cookie seul ne suffit pas (CSRF)."""
    c, server, uid = _client(monkeypatch, tmp_path)
    jid = _job(server, uid)
    r = c.delete(f"/api/jobs/{jid}", headers={"Sec-Fetch-Site": "cross-site"})
    assert r.status_code == 403
    assert c.get(f"/api/jobs/{jid}").status_code == 200


def test_supprimer_une_analyse_ne_libere_aucune_unite_de_plafond(monkeypatch, tmp_path):
    """Sinon « supprimer puis relancer » contournerait le plafond mensuel."""
    from usage import UsageMeter
    c, server, uid = _client(monkeypatch, tmp_path)
    meter = UsageMeter(server._USAGE_DB)
    meter.reserver_analyse(uid, "scout")
    avant = meter.resume(uid).n_analyses
    jid = _job(server, uid)
    c.delete(f"/api/jobs/{jid}")
    assert meter.resume(uid).n_analyses == avant == 1
