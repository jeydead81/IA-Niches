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


def test_un_run_fiction_complet_par_le_chemin_asynchrone(tmp_path, monkeypatch):
    """Le run fiction de bout en bout, sur le SEUL chemin restant. Le flux direct
    (GET /api/fiction) a ete retire : sa file de progression mourait avec la requete HTTP,
    donc fermer l'onglet perdait 15 minutes d'analyse. Ici l'etat vient du magasin, donc
    on peut l'interroger apres coup — c'est ce que fait ce test."""
    import time as _t
    client, server = _client(monkeypatch, tmp_path)
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
    jid = client.post("/api/jobs", json={"type": "fiction", "sous_genre": "cosy_mystery",
                                         "n_niches": 1}).json()["id"]
    fin = _t.time() + 10
    while _t.time() < fin:
        job = client.get(f"/api/jobs/{jid}").json()
        if job["statut"] in ("termine", "echec"):
            break
        _t.sleep(0.02)

    assert job["statut"] == "termine"
    assert any("trio genere" in m for m in job["progression"])
    res = job["resultat"]
    assert res[0]["niche"]["query"] == "cosy mystery village"
    assert res[0]["saturation_trio"] == 0.3
    # La sonde n'a jamais ete appelee par le faux run : autocomplete_score doit valoir None
    # et NON 0.0 — un signal jamais mesure ne se lit pas comme un zero mesure.
    assert res[0]["autocomplete_score"] is None

    # Le flux du travail rejoue tout depuis le magasin : c'est ce qui rend la reprise
    # possible apres un rechargement.
    events = _parse_sse(client.get(f"/api/jobs/{jid}/stream").text)
    kinds = [e for e, _ in events]
    assert "progress" in kinds and "result" in kinds and kinds[-1] == "done"


def test_endpoint_fiction_sous_genres_liste_la_taxonomie(tmp_path, monkeypatch):
    """Peuple le sélecteur fiction de l'UI à partir de la taxonomie (source de vérité
    unique) — jamais une liste dupliquée en dur côté JS."""
    client, _ = _client(monkeypatch, tmp_path)
    r = client.get("/api/fiction/sous-genres")
    assert r.status_code == 200
    cles = [item["cle"] for item in r.json()]
    assert "cosy_mystery" in cles


# ── Composition du trio par l'auteur ────────────────────────────────────────────────

def test_l_endpoint_expose_les_tropes_et_decors_d_un_sous_genre(tmp_path, monkeypatch):
    """Les menus déroulants doivent être peuplés depuis la TAXONOMIE, jamais depuis une
    liste dupliquée en dur côté JS — qui se périmerait à la première taxo v2."""
    client, _ = _client(monkeypatch, tmp_path)
    r = client.get("/api/fiction/taxonomie/cosy_mystery")
    assert r.status_code == 200
    d = r.json()
    assert "enquetrice_amatrice" in d["tropes"] and "village_breton" in d["decors"]
    assert "mafia" not in d["tropes"]


def test_un_sous_genre_inconnu_rend_400(tmp_path, monkeypatch):
    client, _ = _client(monkeypatch, tmp_path)
    assert client.get("/api/fiction/taxonomie/inexistant").status_code == 400


def test_un_job_fiction_transmet_les_contraintes(tmp_path, monkeypatch):
    """L'interface bascule sur POST /api/jobs (elle survit alors à la fermeture de
    l'onglet). Si ce chemin ignorait les contraintes, le compositeur de trio deviendrait
    décoratif du jour au lendemain, sans qu'aucun message ne l'annonce."""
    import time as _t
    client, server = _client(monkeypatch, tmp_path)
    vu = {}

    def faux_run(sous_genre_cle, **kw):
        vu.update(kw)
        return []

    monkeypatch.setattr(server, "run_fiction_scout", faux_run)
    r = client.post("/api/jobs", json={"type": "fiction", "sous_genre": "cosy_mystery",
                                       "tropes": ["enquetrice_amatrice"],
                                       "decor": "village_breton", "libre": "thermalisme"})
    assert r.status_code == 202
    jid = r.json()["id"]
    fin = _t.time() + 10
    while _t.time() < fin:
        if client.get(f"/api/jobs/{jid}").json()["statut"] in ("termine", "echec"):
            break
        _t.sleep(0.02)

    c = vu.get("contraintes")
    assert c is not None, "les contraintes n'ont pas atteint le moteur"
    assert c.tropes == ["enquetrice_amatrice"] and c.decor == "village_breton"
    assert c.libre == "thermalisme"


def test_un_job_fiction_refuse_une_contrainte_hors_taxonomie(tmp_path, monkeypatch):
    """Refusé AVANT la création du job : levée depuis le thread détaché, l'erreur
    arriverait après un 202 déjà rendu et l'utilisateur ne verrait qu'un job en échec sans
    comprendre pourquoi."""
    client, _ = _client(monkeypatch, tmp_path)
    r = client.post("/api/jobs", json={"type": "fiction", "sous_genre": "cosy_mystery",
                                       "tropes": ["mafia"]})
    assert r.status_code == 400 and "taxonomie" in r.json()["detail"].lower()
