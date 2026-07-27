"""test_server_jobs.py — endpoints de travaux asynchrones (plan SaaS S4). Même esprit que
test_server_fiction.py (run_scout/run_fiction_scout monkeypatchés : aucun réseau, aucun LLM),
mais ici le POINT est que le run est détaché de la connexion HTTP : POST rend un id
immédiatement, le thread continue seul et persiste dans jobs.db/usage.db (isolés en tmp_path,
jamais les fichiers réels du dépôt)."""
import json
import sys
import time as _time
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "web"))


def _parse_sse(body: str) -> list[tuple[str, object]]:
    """Reconstruit (event, data) depuis un corps SSE brut (même helper que test_server_fiction)."""
    events = []
    for bloc in body.split("\n\n"):
        if not bloc.strip():
            continue
        event, data = None, None
        for ligne in bloc.splitlines():
            if ligne.startswith("event: "):
                event = ligne[len("event: "):]
            elif ligne.startswith("data: "):
                data = json.loads(ligne[len("data: "):])
        if event is not None:
            events.append((event, data))
    return events


def _client_with_isolated_dbs(monkeypatch, tmp_path):
    """jobs.db/usage.db en tmp_path — jamais les fichiers réels du dépôt en test."""
    pytest.importorskip("httpx")
    from fastapi.testclient import TestClient
    import server
    monkeypatch.setattr(server, "_JOBS_DB", tmp_path / "jobs.db")
    monkeypatch.setattr(server, "_USAGE_DB", tmp_path / "usage.db")
    return TestClient(server.app), server


def _attendre_job(client, job_id: str, timeout: float = 2.0) -> dict:
    fin = _time.time() + timeout
    job = None
    while _time.time() < fin:
        r = client.get(f"/api/jobs/{job_id}")
        assert r.status_code == 200
        job = r.json()
        if job["statut"] in ("termine", "echec"):
            return job
        _time.sleep(0.02)
    raise AssertionError(f"job {job_id} non terminé après {timeout}s : {job}")


def test_post_job_rend_un_id_immediatement(tmp_path, monkeypatch):
    """Le client ne doit PAS attendre 15 min sur une requête HTTP."""
    client, server = _client_with_isolated_dbs(monkeypatch, tmp_path)

    def fake_run(seed=None, n_ideas=12, n_search=6, progress=None, cost=None, **kw):
        if progress:
            progress("niches generees")
        return []

    monkeypatch.setattr(server, "run_scout", fake_run)
    r = client.post("/api/jobs", json={"type": "scout", "seed": "tarot"})
    assert r.status_code == 202 and r.json()["id"]


def test_get_job_rend_la_progression_puis_le_resultat(tmp_path, monkeypatch):
    """Le run est détaché de la connexion HTTP : GET peut être interrogé plus tard, sans
    lien avec la requête POST d'origine — c'est tout le sens du magasin de travaux."""
    client, server = _client_with_isolated_dbs(monkeypatch, tmp_path)
    from models import FictionNiche, FictionNicheReport

    def fake_run(sous_genre_cle, n_niches=8, rayon="kindle", progress=None, cost=None, **kw):
        if progress:
            progress("trio genere")
        if cost is not None:
            cost.add_llm("claude-sonnet-5", 10, 5)
        niche = FictionNiche(sous_genre=sous_genre_cle, tropes=["huis_clos"], decor="village",
                             rayon=rayon, query="cosy mystery village")
        return [FictionNicheReport(niche=niche, depth_score=0.7, openness_score=0.4,
                                   saturation_trio=0.3, demand_matrix="pepite",
                                   verdict="pepite — depth=0.70, openness=0.40, "
                                           "saturation_trio=0.30.")]

    monkeypatch.setattr(server, "run_fiction_scout", fake_run)
    r = client.post("/api/jobs",
                    json={"type": "fiction", "sous_genre": "cosy_mystery", "n_niches": 1})
    assert r.status_code == 202
    jid = r.json()["id"]

    job = _attendre_job(client, jid)
    assert job["statut"] == "termine"
    assert any("trio genere" in m for m in job["progression"])
    assert job["resultat"][0]["niche"]["query"] == "cosy mystery village"
    assert job["cout"]["llm_usd"] > 0
    assert job["user_id"] == "local"


def test_job_refuse_quand_le_plafond_est_atteint(tmp_path, monkeypatch):
    """429 explicite avec le motif, pas un échec silencieux."""
    pytest.importorskip("httpx")
    from fastapi.testclient import TestClient
    import server
    from usage import UsageMeter

    jobs_db = tmp_path / "jobs.db"
    usage_db = tmp_path / "usage.db"
    monkeypatch.setattr(server, "_JOBS_DB", jobs_db)
    monkeypatch.setattr(server, "_USAGE_DB", usage_db)
    monkeypatch.setenv("PLAFOND_ANALYSES_MENSUEL", "1")
    # l'utilisateur "local" a déjà consommé son unique analyse autorisée ce mois-ci
    UsageMeter(usage_db, plafond_analyses=1).enregistrer("local", "fiction", cout_usd=0.1,
                                                         n_analyses=1)

    client = TestClient(server.app)
    r = client.post("/api/jobs", json={"type": "fiction", "sous_genre": "cosy_mystery"})
    assert r.status_code == 429 and "plafond" in r.json()["detail"].lower()


def test_type_de_job_inconnu_rend_400(tmp_path, monkeypatch):
    """Un type de job non reconnu doit être rejeté explicitement, jamais lancé à l'aveugle."""
    client, _ = _client_with_isolated_dbs(monkeypatch, tmp_path)
    r = client.post("/api/jobs", json={"type": "bidon"})
    assert r.status_code == 400
    assert "bidon" in r.json()["detail"]


def test_get_job_inconnu_rend_404(tmp_path, monkeypatch):
    client, _ = _client_with_isolated_dbs(monkeypatch, tmp_path)
    r = client.get("/api/jobs/id-inexistant")
    assert r.status_code == 404


def test_liste_jobs_de_lutilisateur(tmp_path, monkeypatch):
    """GET /api/jobs (liste) — user_id dès maintenant, défaut 'local'."""
    client, server = _client_with_isolated_dbs(monkeypatch, tmp_path)

    def fake_run(seed=None, n_ideas=12, n_search=6, progress=None, cost=None, **kw):
        return []

    monkeypatch.setattr(server, "run_scout", fake_run)
    r1 = client.post("/api/jobs", json={"type": "scout"})
    r2 = client.post("/api/jobs", json={"type": "scout"})
    _attendre_job(client, r1.json()["id"])
    _attendre_job(client, r2.json()["id"])

    r = client.get("/api/jobs?user_id=local")
    assert r.status_code == 200
    ids = [j["id"] for j in r.json()]
    assert r1.json()["id"] in ids and r2.json()["id"] in ids


def test_job_stream_rend_progression_puis_resultat(tmp_path, monkeypatch):
    """SSE reconnectable : l'état vient du magasin persistant, pas d'une queue liée à LA
    connexion — une reconnexion peut relire la progression à tout moment."""
    client, server = _client_with_isolated_dbs(monkeypatch, tmp_path)

    def fake_run(seed=None, n_ideas=12, n_search=6, progress=None, cost=None, **kw):
        if progress:
            progress("phase 1")
            progress("phase 2")
        return []

    monkeypatch.setattr(server, "run_scout", fake_run)
    r = client.post("/api/jobs", json={"type": "scout"})
    jid = r.json()["id"]
    _attendre_job(client, jid)

    resp = client.get(f"/api/jobs/{jid}/stream")
    assert resp.status_code == 200
    events = _parse_sse(resp.text)
    kinds = [e for e, _ in events]
    assert "progress" in kinds
    assert "result" in kinds
    assert kinds[-1] == "done"


def test_job_stream_id_inconnu_rend_erreur_puis_done(tmp_path, monkeypatch):
    client, _ = _client_with_isolated_dbs(monkeypatch, tmp_path)
    r = client.get("/api/jobs/id-inexistant/stream")
    assert r.status_code == 200
    events = _parse_sse(r.text)
    kinds = [e for e, _ in events]
    assert kinds == ["error", "done"]
