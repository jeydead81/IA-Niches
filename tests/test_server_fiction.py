"""test_server_fiction.py — M6-3 : endpoint SSE /api/fiction, même contrat que /api/scout
(progress -> result -> cost -> done), et 400 explicite sur un sous-genre inconnu (jamais une
KeyError 500 remontée depuis fiction_taxonomy.sous_genre). run_fiction_scout est monkeypatché :
aucun réseau, aucun LLM en test."""
import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "web"))


def _parse_sse(body: str) -> list[tuple[str, object]]:
    """Reconstruit (event, data) depuis un corps SSE brut — plus robuste qu'un test sur la
    chaîne JSON exacte (espacement, ordre des clés)."""
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


def _client(monkeypatch, tmp_path):
    """Session ouverte : depuis l'authentification, /api/fiction rend 401 sans compte."""
    pytest.importorskip("httpx")
    from fastapi.testclient import TestClient
    import server
    from tests.conftest import isoler_bases, ouvrir_session
    isoler_bases(monkeypatch, server, tmp_path)
    client = TestClient(server.app)
    ouvrir_session(client)
    return client, server


def test_endpoint_fiction_refuse_un_sous_genre_inconnu(tmp_path, monkeypatch):
    """400 explicite plutôt qu'une KeyError 500 venue de la taxonomie."""
    client, _ = _client(monkeypatch, tmp_path)
    r = client.get("/api/fiction?sous_genre=inexistant")
    assert r.status_code == 400


def test_endpoint_fiction_refuse_sous_genre_absent(tmp_path, monkeypatch):
    """Paramètre manquant = même traitement propre, pas une 422 opaque."""
    client, _ = _client(monkeypatch, tmp_path)
    r = client.get("/api/fiction")
    assert r.status_code == 400


def test_endpoint_fiction_stream_sse(tmp_path, monkeypatch):
    """Même contrat SSE que /api/scout : progress -> result -> cost -> done."""
    pytest.importorskip("httpx")
    from fastapi.testclient import TestClient
    import server
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
    from tests.conftest import isoler_bases, ouvrir_session
    isoler_bases(monkeypatch, server, tmp_path)
    client = TestClient(server.app)
    ouvrir_session(client)
    r = client.get("/api/fiction?sous_genre=cosy_mystery&n_niches=1")
    assert r.status_code == 200

    events = _parse_sse(r.text)
    kinds = [e for e, _ in events]
    assert "progress" in kinds
    assert "result" in kinds
    assert "cost" in kinds
    assert kinds[-1] == "done"

    result = next(d for k, d in events if k == "result")
    assert result[0]["niche"]["query"] == "cosy mystery village"
    assert result[0]["saturation_trio"] == 0.3
    # La sonde n'a jamais été appelée par le faux run -> autocomplete_score doit être None,
    # PAS 0 : le champ n'existe que via une propriété non sérialisée par model_dump(), le
    # endpoint doit l'ajouter explicitement (CLAUDE.md §10 : ne pas confondre non-mesuré et zéro).
    assert result[0]["autocomplete_score"] is None

    cost = next(d for k, d in events if k == "cost")
    assert cost["llm_usd"] > 0


def test_endpoint_fiction_sous_genres_liste_la_taxonomie(tmp_path, monkeypatch):
    """Peuple le sélecteur fiction de l'UI à partir de la taxonomie (source de vérité
    unique) — jamais une liste dupliquée en dur côté JS."""
    client, _ = _client(monkeypatch, tmp_path)
    r = client.get("/api/fiction/sous-genres")
    assert r.status_code == 200
    cles = [item["cle"] for item in r.json()]
    assert "cosy_mystery" in cles
