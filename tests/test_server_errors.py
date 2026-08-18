"""Fuite d'information par le message d'exception.

`job_store.fail(job_id, f"{type(e).__name__}: {e}")` recopiait le texte de l'exception
dans un champ que le client lit — par `GET /api/jobs/{id}` ET par le flux SSE. Or le texte
d'une exception réseau porte régulièrement l'URL appelée, et l'URL DataForSEO porte les
identifiants HTTP Basic. Une panne de fournisseur suffisait donc à afficher un secret à
l'écran, sans qu'aucune ligne du code ne « logue un secret ».

Le client reçoit désormais une référence d'incident ; le détail part dans le log serveur,
qui n'est pas rendu par une route. Même famille que §2.7 `_corps_json` : un chemin non
prévu ne doit renseigner ni l'utilisateur ni l'attaquant sur l'intérieur.
"""
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "web"))

from tests.test_server_jobs import _attendre_job, _client_with_isolated_dbs

SECRET = "login=identifiant-dataforseo&password=SECRET-A-NE-PAS-FUITER"


def _run_qui_leve(*a, **kw):
    raise RuntimeError(f"HTTPError 401 sur https://api.dataforseo.com/v3/?{SECRET}")


def test_le_message_d_exception_ne_remonte_pas_au_client(tmp_path, monkeypatch):
    client, server = _client_with_isolated_dbs(monkeypatch, tmp_path)
    monkeypatch.setattr(server, "run_scout", _run_qui_leve)

    job_id = client.post("/api/jobs", json={"type": "scout", "seed": "x"}).json()["id"]
    job = _attendre_job(client, job_id)

    assert job["statut"] == "echec"
    # Sur l'objet ENTIER : le champ `erreur` est le canal de fuite, mais un futur champ
    # « detail » ou « trace » le rouvrirait sans que ce test bronche s'il ne regardait
    # qu'`erreur`. Le mot « dataforseo » seul ne peut pas servir de sonde : il apparaît
    # légitimement dans les clés de coût (dataforseo_usd, dataforseo_calls).
    assert "SECRET-A-NE-PAS-FUITER" not in json_dumps(job)
    assert "api.dataforseo.com" not in json_dumps(job)
    assert "RuntimeError" not in json_dumps(job)


def json_dumps(o) -> str:
    import json
    return json.dumps(o, ensure_ascii=False)


def test_le_client_recoit_une_reference_d_incident_pas_un_silence(tmp_path, monkeypatch):
    """« Erreur interne » sans référence rend le support impossible : Baptiste doit
    pouvoir relier ce que voit l'utilisateur à une ligne de log."""
    client, server = _client_with_isolated_dbs(monkeypatch, tmp_path)
    monkeypatch.setattr(server, "run_scout", _run_qui_leve)

    job_id = client.post("/api/jobs", json={"type": "scout", "seed": "x"}).json()["id"]
    job = _attendre_job(client, job_id)

    import re
    assert re.search(r"ref [0-9a-f]{8}", job["erreur"]), job["erreur"]


def test_le_detail_reel_part_dans_le_log_serveur(tmp_path, monkeypatch, caplog):
    """La référence ne sert à rien si le détail n'est nulle part. Il doit être loggé —
    côté serveur, jamais rendu par une route."""
    import logging
    client, server = _client_with_isolated_dbs(monkeypatch, tmp_path)
    monkeypatch.setattr(server, "run_scout", _run_qui_leve)

    with caplog.at_level(logging.ERROR):
        job_id = client.post("/api/jobs", json={"type": "scout", "seed": "x"}).json()["id"]
        job = _attendre_job(client, job_id)

    ref = job["erreur"].split("ref ")[1].rstrip(")")
    assert SECRET in caplog.text
    assert ref in caplog.text          # la référence relie le log à ce que voit le client


def test_le_flux_sse_ne_fuit_pas_non_plus(tmp_path, monkeypatch):
    """Le SSE est un second chemin de lecture du même champ : le corriger d'un seul côté
    laisserait la fuite entière sur l'autre."""
    client, server = _client_with_isolated_dbs(monkeypatch, tmp_path)
    monkeypatch.setattr(server, "run_scout", _run_qui_leve)

    job_id = client.post("/api/jobs", json={"type": "scout", "seed": "x"}).json()["id"]
    _attendre_job(client, job_id)
    corps = client.get(f"/api/jobs/{job_id}/stream").text
    assert "SECRET-A-NE-PAS-FUITER" not in corps
