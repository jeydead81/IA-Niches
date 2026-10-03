"""Arrêter une analyse (Baptiste, 2026-10-03 : « il faut pouvoir arrêter une analyse, pour ensuite
la supprimer si elle bug ou tourne dans le vide »).

Le problème technique : une analyse vit dans un THREAD du serveur (ou dans le worker). On ne tue
pas un thread. L'arrêt est donc COOPÉRATIF, en deux temps :

1. IMMÉDIAT côté données : `annuler` pose le statut « annule » dans `jobs.db`. L'utilisateur voit
   son analyse arrêtée tout de suite, peut relancer, peut la supprimer.
2. Le thread, lui, s'arrête au prochain point de contrôle (message de progression, avant un appel
   payant, à chaque cycle d'attente du fournisseur) : `annulation.verifier()` lève `Annulation`,
   une `BaseException` — jamais une `Exception` : les moteurs ont des `except Exception` « un
   échec ne coule jamais le run » qui l'avaleraient. Ils relèvent déjà les `BaseException`
   (Ctrl-C) en imputant le pire cas pour une tâche créée puis non lue : l'arrêt en hérite.

Règles de dépense : l'argent déjà engagé reste imputé, et l'unité de plafond reste prise (arrêter
ne rembourse pas : sinon « lancer puis arrêter » serait gratuit). Une analyse arrêtée n'envoie
aucune notification et n'écrit jamais « terminé » après coup.
"""
import sys
import threading
import time
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "web"))

from annulation import Annulation, installer, retirer, verifier  # noqa: E402
from jobs import JobStore  # noqa: E402


# ── Le mécanisme : un point de contrôle, une exception qui ne se laisse pas avaler ──────────

def test_Annulation_n_est_pas_une_Exception():
    """Sinon le `except Exception` « un échec ne coule jamais le run » l'avalerait."""
    assert issubclass(Annulation, BaseException) and not issubclass(Annulation, Exception)


def test_verifier_leve_quand_le_controle_dit_stop_et_se_tait_sinon():
    try:
        installer(lambda: False)
        verifier()                                   # ne lève pas
        installer(lambda: True)
        with pytest.raises(Annulation):
            verifier()
    finally:
        retirer()


def test_sans_controle_installe_verifier_ne_fait_rien():
    retirer()
    verifier()


def test_le_controle_est_propre_a_chaque_fil():
    """Deux analyses simultanées : arrêter l'une ne doit jamais arrêter l'autre."""
    vu = {}

    def fil(nom, stop):
        installer(lambda: stop)
        try:
            verifier()
            vu[nom] = "continue"
        except Annulation:
            vu[nom] = "arrete"
        finally:
            retirer()
    ts = [threading.Thread(target=fil, args=("a", True)), threading.Thread(target=fil, args=("b", False))]
    for t in ts:
        t.start()
    for t in ts:
        t.join()
    assert vu == {"a": "arrete", "b": "continue"}


def test_un_controle_qui_leve_ne_tue_pas_l_analyse():
    """Une base illisible ne doit pas arrêter une analyse payée : on continue."""
    def casse():
        raise RuntimeError("disque")
    try:
        installer(casse)
        verifier()
    finally:
        retirer()


# ── JobStore ─────────────────────────────────────────────────────────────────────────────────

def _s(tmp_path):
    return JobStore(tmp_path / "jobs.db")


@pytest.mark.parametrize("etat", ["en_attente", "en_cours"])
def test_annuler_arrete_une_analyse_pas_finie(tmp_path, etat):
    s = _s(tmp_path)
    jid = s.create("scout", {}, user_id="u1")
    if etat == "en_cours":
        s.start(jid)
    assert s.annuler(jid, "u1") == "annule"
    job = s.get(jid)
    assert job.statut == "annule" and job.fini_le is not None and "arrêt" in (job.erreur or "").lower()
    assert s.est_annule(jid) is True


def test_annuler_une_analyse_finie_rend_deja_fini_sans_rien_changer(tmp_path):
    s = _s(tmp_path)
    jid = s.create("scout", {}, user_id="u1")
    s.finish(jid, [{"niche": "a"}], {})
    assert s.annuler(jid, "u1") == "deja_fini"
    assert s.get(jid).statut == "termine"


def test_annuler_refuse_le_travail_d_un_autre_utilisateur(tmp_path):
    s = _s(tmp_path)
    jid = s.create("scout", {}, user_id="u1")
    assert s.annuler(jid, "intrus") == "introuvable"
    assert s.get(jid).statut == "en_attente" and s.annuler("nope", "u1") == "introuvable"


def test_un_travail_annule_ne_ressuscite_jamais(tmp_path):
    """Le thread peut finir APRÈS l'arrêt : ni `finish`, ni `fail`, ni `start` ne le font
    revenir à « terminé », « échec » ou « en cours »."""
    s = _s(tmp_path)
    jid = s.create("scout", {}, user_id="u1")
    s.start(jid)
    s.annuler(jid, "u1")
    s.finish(jid, [{"niche": "tard"}], {"usd": 1})
    s.fail(jid, "boom")
    s.start(jid)
    job = s.get(jid)
    assert job.statut == "annule" and job.resultat is None


def test_l_argent_engage_avant_l_arret_est_conserve_sur_le_travail(tmp_path):
    s = _s(tmp_path)
    jid = s.create("scout", {}, user_id="u1")
    s.annuler(jid, "u1")
    s.enregistrer_cout_annule(jid, {"usd": 0.042})
    assert s.get(jid).cout == {"usd": 0.042}


def test_la_file_du_worker_ignore_une_analyse_annulee(tmp_path):
    s = _s(tmp_path)
    jid = s.create("scout", {}, user_id="u1")
    s.annuler(jid, "u1")
    assert s.claim_next() is None


def test_une_analyse_annulee_se_supprime(tmp_path):
    s = _s(tmp_path)
    jid = s.create("scout", {}, user_id="u1")
    s.annuler(jid, "u1")
    assert s.supprimer(jid, "u1") == "supprime"


# ── Le serveur : endpoint, thread, usage ─────────────────────────────────────────────────────

def _client(monkeypatch, tmp_path):
    pytest.importorskip("httpx")
    from fastapi.testclient import TestClient
    import server
    from tests.conftest import isoler_bases, ouvrir_session
    isoler_bases(monkeypatch, server, tmp_path)
    c = TestClient(server.app, raise_server_exceptions=False)
    uid = ouvrir_session(c)
    return c, server, uid


def test_l_endpoint_arrete_une_analyse_en_cours_et_rend_204(monkeypatch, tmp_path):
    c, server, uid = _client(monkeypatch, tmp_path)
    s = JobStore(server._JOBS_DB)
    jid = s.create("scout", {}, user_id=uid)
    s.start(jid)
    assert c.post(f"/api/jobs/{jid}/annuler").status_code == 204
    assert c.get(f"/api/jobs/{jid}").json()["statut"] == "annule"


def test_arreter_une_analyse_finie_rend_409(monkeypatch, tmp_path):
    c, server, uid = _client(monkeypatch, tmp_path)
    s = JobStore(server._JOBS_DB)
    jid = s.create("scout", {}, user_id=uid)
    s.finish(jid, [], {})
    r = c.post(f"/api/jobs/{jid}/annuler")
    assert r.status_code == 409 and "terminée" in r.json()["detail"]


def test_arreter_l_analyse_d_autrui_rend_404(monkeypatch, tmp_path):
    from fastapi.testclient import TestClient
    from tests.conftest import ouvrir_session
    c, server, uid = _client(monkeypatch, tmp_path)
    s = JobStore(server._JOBS_DB)
    jid = s.create("scout", {}, user_id=uid)
    monkeypatch.setenv("INSCRIPTIONS_OUVERTES", "1")
    intrus = TestClient(server.app, raise_server_exceptions=False)
    ouvrir_session(intrus, "intrus@example.com")
    assert intrus.post(f"/api/jobs/{jid}/annuler").status_code == 404
    assert s.get(jid).statut == "en_attente"


def test_arreter_exige_une_session_et_refuse_un_autre_site(monkeypatch, tmp_path):
    from fastapi.testclient import TestClient
    c, server, uid = _client(monkeypatch, tmp_path)
    jid = JobStore(server._JOBS_DB).create("scout", {}, user_id=uid)
    assert TestClient(server.app, raise_server_exceptions=False).post(
        f"/api/jobs/{jid}/annuler").status_code == 401
    r = c.post(f"/api/jobs/{jid}/annuler", headers={"Sec-Fetch-Site": "cross-site"})
    assert r.status_code == 403
    assert JobStore(server._JOBS_DB).get(jid).statut == "en_attente"


def _runner_qui_boucle(compteur, arret):
    """Un faux moteur : il émet un message de progression toutes les 20 ms, comme les vrais."""
    def runner(params, progress, cost, user_id):
        cost.add_llm("claude-sonnet-5", 1000, 500)          # de l'argent DÉJÀ engagé
        for i in range(500):
            progress(f"étape {i}")
            compteur["n"] += 1
            if arret.is_set():
                break
            time.sleep(0.02)
        return [{"niche": "ne devrait jamais etre ecrit"}]
    return runner


def test_le_thread_s_arrete_vraiment_et_n_ecrit_jamais_termine(monkeypatch, tmp_path):
    c, server, uid = _client(monkeypatch, tmp_path)
    compteur, arret = {"n": 0}, threading.Event()
    monkeypatch.setitem(server._JOB_RUNNERS, "scout", _runner_qui_boucle(compteur, arret))
    monkeypatch.setattr(server, "verifier_devis", lambda *a, **k: None)
    monkeypatch.setattr(server, "_valider_volumes", lambda *a, **k: None)
    jid = c.post("/api/jobs", json={"type": "scout"}).json()["id"]
    time.sleep(0.3)
    assert c.get(f"/api/jobs/{jid}").json()["statut"] == "en_cours"
    assert c.post(f"/api/jobs/{jid}/annuler").status_code == 204
    time.sleep(1.2)                  # le contrôle lit la base au plus une fois par demi-seconde
    figé = compteur["n"]
    time.sleep(0.4)
    arret.set()
    assert compteur["n"] == figé, "le thread a continué après l'arrêt"
    job = c.get(f"/api/jobs/{jid}").json()
    assert job["statut"] == "annule" and job["resultat"] is None


def test_l_argent_engage_reste_impute_et_l_unite_de_plafond_reste_prise(monkeypatch, tmp_path):
    """Arrêter ne rembourse rien : sinon « lancer puis arrêter » serait gratuit."""
    from usage import UsageMeter
    c, server, uid = _client(monkeypatch, tmp_path)
    compteur, arret = {"n": 0}, threading.Event()
    monkeypatch.setitem(server._JOB_RUNNERS, "scout", _runner_qui_boucle(compteur, arret))
    monkeypatch.setattr(server, "verifier_devis", lambda *a, **k: None)
    monkeypatch.setattr(server, "_valider_volumes", lambda *a, **k: None)
    jid = c.post("/api/jobs", json={"type": "scout"}).json()["id"]
    time.sleep(0.3)
    c.post(f"/api/jobs/{jid}/annuler")
    time.sleep(1.5)
    arret.set()
    resume = UsageMeter(server._USAGE_DB).resume(uid)
    assert resume.n_analyses == 1, "l'unité reste prise"
    assert resume.cout_usd > 0, "le coût déjà engagé reste imputé"
    assert JobStore(server._JOBS_DB).get(jid).cout["usd"] > 0


def test_une_analyse_arretee_n_envoie_aucune_notification(monkeypatch, tmp_path):
    c, server, uid = _client(monkeypatch, tmp_path)
    envoyes = []
    monkeypatch.setattr(server, "_notifier", lambda *a, **k: envoyes.append(a))
    compteur, arret = {"n": 0}, threading.Event()
    monkeypatch.setitem(server._JOB_RUNNERS, "scout", _runner_qui_boucle(compteur, arret))
    monkeypatch.setattr(server, "verifier_devis", lambda *a, **k: None)
    monkeypatch.setattr(server, "_valider_volumes", lambda *a, **k: None)
    jid = c.post("/api/jobs", json={"type": "scout"}).json()["id"]
    time.sleep(0.3)
    c.post(f"/api/jobs/{jid}/annuler")
    time.sleep(1.5)
    arret.set()
    assert envoyes == []


def test_le_creneau_est_rendu_apres_l_arret(monkeypatch, tmp_path):
    """Sinon une analyse arrêtée garderait sa place du pool et ferait attendre les autres."""
    c, server, uid = _client(monkeypatch, tmp_path)
    monkeypatch.setenv("RUNS_SIMULTANES_MAX", "1")       # un seul créneau : le rendre est observable
    compteur, arret = {"n": 0}, threading.Event()
    monkeypatch.setitem(server._JOB_RUNNERS, "scout", _runner_qui_boucle(compteur, arret))
    monkeypatch.setattr(server, "verifier_devis", lambda *a, **k: None)
    monkeypatch.setattr(server, "_valider_volumes", lambda *a, **k: None)
    jid = c.post("/api/jobs", json={"type": "scout"}).json()["id"]
    time.sleep(0.3)
    c.post(f"/api/jobs/{jid}/annuler")
    time.sleep(1.5)
    arret.set()
    # Le suivant a SON PROPRE faux moteur, qui ne s'arrête pas tout seul.
    compteur2, arret2 = {"n": 0}, threading.Event()
    monkeypatch.setitem(server._JOB_RUNNERS, "scout", _runner_qui_boucle(compteur2, arret2))
    suivant = c.post("/api/jobs", json={"type": "scout"}).json()["id"]
    time.sleep(0.6)
    assert c.get(f"/api/jobs/{suivant}").json()["statut"] == "en_cours", "le créneau n'a pas été rendu"
    c.post(f"/api/jobs/{suivant}/annuler")
    time.sleep(1.5)
    arret2.set()


def test_le_flux_sse_d_une_analyse_arretee_se_termine_proprement(monkeypatch, tmp_path):
    c, server, uid = _client(monkeypatch, tmp_path)
    s = JobStore(server._JOBS_DB)
    jid = s.create("scout", {}, user_id=uid)
    s.start(jid)
    s.annuler(jid, uid)
    corps = c.get(f"/api/jobs/{jid}/stream").text
    assert "event: error" in corps and "arrêt" in corps.lower() and "event: done" in corps
    assert "event: result" not in corps


def test_le_controle_lit_le_statut_en_base_et_ne_declenche_que_pour_ce_travail(monkeypatch, tmp_path):
    from annulation import controle_du_travail
    s = _s(tmp_path)
    a = s.create("scout", {}, user_id="u1")
    b = s.create("scout", {}, user_id="u1")
    s.annuler(a, "u1")
    assert controle_du_travail(s, a, intervalle_s=0)() is True
    assert controle_du_travail(s, b, intervalle_s=0)() is False


def test_cost_tracker_verifier_est_un_point_de_controle():
    """Avant chaque phase payante : c'est le moment le moins coûteux pour s'arrêter."""
    from cost_tracker import CostTracker
    try:
        installer(lambda: True)
        with pytest.raises(Annulation):
            CostTracker().verifier()
    finally:
        retirer()


# ── Le worker séparé (JOBS_MODE=worker) arrête lui aussi ─────────────────────────────────────

def test_le_worker_s_arrete_impute_le_cout_et_ne_notifie_pas(monkeypatch, tmp_path):
    pytest.importorskip("httpx")
    import worker
    s = _s(tmp_path)
    jid = s.create("scout", {}, user_id="u1")
    imputes, notifies = [], []
    arret = threading.Event()

    def runner(params, progress, cost, user_id):
        cost.add_llm("claude-sonnet-5", 1000, 500)
        for i in range(400):
            progress(f"étape {i}")
            if arret.is_set():
                break
            time.sleep(0.02)
        return [{"niche": "jamais écrit"}]
    monkeypatch.setattr(worker, "_RUNNERS", {"scout": runner})
    monkeypatch.setattr(worker, "_imputer", lambda user, typ, usd, n: imputes.append(usd))
    monkeypatch.setattr(worker.server, "_notifier", lambda *a, **k: notifies.append(a))

    fil = threading.Thread(target=lambda: worker.executer_un_job(s, journal=lambda m: None))
    fil.start()
    time.sleep(0.3)
    assert s.annuler(jid, "u1") == "annule"
    fil.join(timeout=5)
    arret.set()
    assert not fil.is_alive(), "le worker ne s'est pas arrêté"
    job = s.get(jid)
    assert job.statut == "annule" and job.resultat is None and job.cout["usd"] > 0
    assert imputes and imputes[0] > 0, "l'argent déjà engagé reste imputé"
    assert notifies == []
