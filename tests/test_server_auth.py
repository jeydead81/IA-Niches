"""test_server_auth.py — l'authentification côté serveur.

Le point central : **le `user_id` ne vient plus jamais du client**. Avant l'authentification,
`POST /api/jobs` le lisait dans le corps de la requête et s'en servait pour vérifier le
plafond mensuel — n'importe qui pouvait donc changer d'identité à chaque appel et dépenser
sans limite. C'est le test `test_le_client_ne_choisit_plus_son_identite` qui ferme ça ;
les autres protègent le tour de la maison."""
import sys
import time
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "web"))

MDP = "un-mot-de-passe-solide"


def _client(monkeypatch, tmp_path):
    """Toutes les bases en tmp_path — jamais les fichiers réels du dépôt."""
    pytest.importorskip("httpx")
    from fastapi.testclient import TestClient
    import server
    for attr, nom in (("_JOBS_DB", "j.db"), ("_USAGE_DB", "u.db"),
                      ("_HISTORY_DB", "h.db"), ("_USERS_DB", "c.db")):
        monkeypatch.setattr(server, attr, tmp_path / nom)
    return TestClient(server.app), server


def _inscrire(client, email="baptiste@example.com", mdp=MDP):
    return client.post("/api/auth/inscription", json={"email": email, "mot_de_passe": mdp})


# ── Accès ───────────────────────────────────────────────────────────────────────────

def test_la_page_reste_servie_sans_session(tmp_path, monkeypatch):
    """Exiger une session pour servir la page rendrait le formulaire de connexion
    inatteignable : on ne pourrait plus jamais se connecter."""
    client, _ = _client(monkeypatch, tmp_path)
    assert client.get("/").status_code == 200


@pytest.mark.parametrize("methode,chemin", [
    ("get", "/api/usage"),
    ("get", "/api/history?niche=x"),
    ("get", "/api/jobs"),
    ("post", "/api/jobs"),
    ("get", "/api/scout"),
    ("get", "/api/fiction?sous_genre=cosy_mystery"),
    ("post", "/api/verdict"),
    ("post", "/api/kdp-keywords"),
    ("post", "/api/pdf"),
])
def test_sans_session_les_endpoints_rendent_401(tmp_path, monkeypatch, methode, chemin):
    """Aucun endpoint qui dépense, lit des données personnelles ou révèle un historique ne
    doit répondre à un inconnu.

    Les deux moteurs sont neutralisés MÊME SI ce test ne devrait jamais les atteindre :
    c'est une ceinture de sécurité, pas une commodité. Sans elle, faire tourner ce test
    avant que le garde d'authentification ne soit branché lance un VRAI run — appel LLM
    facturé compris. C'est arrivé pendant l'écriture de ce fichier."""
    client, server = _client(monkeypatch, tmp_path)
    monkeypatch.setattr(server, "run_scout", lambda **kw: _interdit())
    monkeypatch.setattr(server, "run_fiction_scout", lambda *a, **kw: _interdit())
    r = getattr(client, methode)(chemin, **({"json": {}} if methode == "post" else {}))
    assert r.status_code == 401, f"{methode.upper()} {chemin} a rendu {r.status_code}"


def _interdit():
    raise AssertionError("un endpoint a lancé un moteur payant sans session valide")


# ── Inscription et connexion ────────────────────────────────────────────────────────

def test_inscription_puis_identite_connue(tmp_path, monkeypatch):
    client, _ = _client(monkeypatch, tmp_path)
    r = _inscrire(client)
    assert r.status_code == 201, r.text
    moi = client.get("/api/auth/moi")
    assert moi.status_code == 200 and moi.json()["email"] == "baptiste@example.com"


def test_un_email_deja_pris_rend_409(tmp_path, monkeypatch):
    client, _ = _client(monkeypatch, tmp_path)
    _inscrire(client)
    assert _inscrire(client).status_code == 409


@pytest.mark.parametrize("email,mdp", [("pas-un-email", MDP), ("a@b.fr", "court")])
def test_une_inscription_malformee_rend_400(tmp_path, monkeypatch, email, mdp):
    client, _ = _client(monkeypatch, tmp_path)
    assert _inscrire(client, email, mdp).status_code == 400


def test_connexion_et_deconnexion(tmp_path, monkeypatch):
    client, _ = _client(monkeypatch, tmp_path)
    _inscrire(client)
    client.post("/api/auth/deconnexion")
    assert client.get("/api/auth/moi").status_code == 401
    assert client.post("/api/auth/connexion",
                       json={"email": "baptiste@example.com", "mot_de_passe": MDP}).status_code == 200
    assert client.get("/api/auth/moi").status_code == 200


def test_un_mauvais_mot_de_passe_rend_401_sans_dire_pourquoi(tmp_path, monkeypatch):
    """Le message ne doit pas distinguer « email inconnu » de « mot de passe faux » :
    sinon une liste d'adresses révèle qui est client."""
    client, _ = _client(monkeypatch, tmp_path)
    _inscrire(client)
    r1 = client.post("/api/auth/connexion",
                     json={"email": "baptiste@example.com", "mot_de_passe": "mauvais-mdp-long"})
    r2 = client.post("/api/auth/connexion",
                     json={"email": "personne@example.com", "mot_de_passe": MDP})
    assert r1.status_code == r2.status_code == 401
    assert r1.json()["detail"] == r2.json()["detail"]


def test_le_cookie_de_session_est_httponly(tmp_path, monkeypatch):
    """MENACE : un cookie lisible par JavaScript se vole avec la moindre injection de
    script. HttpOnly le met hors de portée du document."""
    client, _ = _client(monkeypatch, tmp_path)
    r = _inscrire(client)
    brut = r.headers.get("set-cookie", "")
    assert "httponly" in brut.lower()
    assert "samesite=lax" in brut.lower().replace(" ", "")


# ── LE test : l'identité ne vient plus du client ─────────────────────────────────────

def test_le_client_ne_choisit_plus_son_identite(tmp_path, monkeypatch):
    """FAILLE FERMÉE ICI. `POST /api/jobs` lisait `user_id` dans le corps de la requête et
    s'en servait pour vérifier le plafond mensuel : il suffisait d'envoyer un `user_id`
    neuf à chaque appel pour dépenser sans aucune limite. Le `user_id` doit désormais venir
    EXCLUSIVEMENT de la session, et un `user_id` envoyé par le client être ignoré."""
    client, server = _client(monkeypatch, tmp_path)
    _inscrire(client)
    mien = client.get("/api/auth/moi").json()["user_id"]

    from models import ScoredNiche
    monkeypatch.setattr(server, "run_scout",
                        lambda **kw: [ScoredNiche(niche="tarot", global_score=7.1,
                                                  concurrence_mesuree=True)])

    r = client.post("/api/jobs", json={"type": "scout", "user_id": "quelqu-un-d-autre"})
    assert r.status_code == 202
    job_id = r.json()["id"]
    fin = time.time() + 10
    while time.time() < fin:
        if client.get(f"/api/jobs/{job_id}").json()["statut"] in ("termine", "echec"):
            break
        time.sleep(0.02)

    # Le job, l'usage et l'historique sont tous imputés à MON compte, pas au user_id soufflé.
    assert [j["id"] for j in client.get("/api/jobs").json()] == [job_id]
    assert client.get("/api/usage").json()["n_analyses"] == 1
    assert client.get("/api/history", params={"niche": "tarot"}).json()["passages"]
    from history import NicheHistory
    assert not NicheHistory(tmp_path / "h.db").historique("quelqu-un-d-autre", "tarot")
    assert mien and mien != "quelqu-un-d-autre"


def test_le_plafond_ne_se_contourne_plus_en_changeant_de_user_id(tmp_path, monkeypatch):
    """Corollaire direct : avec un plafond à 1, le second job est refusé même si le client
    envoie une identité differente."""
    client, server = _client(monkeypatch, tmp_path)
    monkeypatch.setenv("PLAFOND_ANALYSES_MENSUEL", "1")
    _inscrire(client)
    from models import ScoredNiche
    monkeypatch.setattr(server, "run_scout",
                        lambda **kw: [ScoredNiche(niche="tarot", global_score=7.1,
                                                  concurrence_mesuree=True)])

    jid = client.post("/api/jobs", json={"type": "scout"}).json()["id"]
    fin = time.time() + 10
    while time.time() < fin:
        if client.get(f"/api/jobs/{jid}").json()["statut"] in ("termine", "echec"):
            break
        time.sleep(0.02)

    r = client.post("/api/jobs", json={"type": "scout", "user_id": "identite-neuve"})
    assert r.status_code == 429


# ── Cloisonnement entre comptes ─────────────────────────────────────────────────────

def test_deux_comptes_ne_voient_pas_l_historique_l_un_de_l_autre(tmp_path, monkeypatch):
    """L'historique, l'usage et les jobs sont PAR utilisateur — à la différence du cache de
    scraping, mutualisé par conception (CLAUDE.md)."""
    client, server = _client(monkeypatch, tmp_path)
    _inscrire(client, "un@example.com")
    from history import NicheHistory
    mien = client.get("/api/auth/moi").json()["user_id"]
    NicheHistory(tmp_path / "h.db").enregistrer(mien, "scout", "ma niche", {"global_score": 7.0})
    assert client.get("/api/history", params={"niche": "ma niche"}).json()["passages"]

    client.post("/api/auth/deconnexion")
    _inscrire(client, "deux@example.com")
    assert not client.get("/api/history", params={"niche": "ma niche"}).json()["passages"]


# ── Reprise des données locales ─────────────────────────────────────────────────────

def test_le_premier_compte_adopte_les_donnees_locales_s_il_le_demande(tmp_path, monkeypatch):
    """Baptiste a un historique et un usage sous `user_id="local"`, accumulés avant
    l'authentification. Le premier compte peut les reprendre — sinon la mise en service de
    l'authentification lui ferait perdre son antériorité, c'est-à-dire précisément ce que
    l'historique sert à mesurer.

    Mais la reprise est DEMANDÉE, pas automatique. La revue de sécurité a montré que sur une
    instance exposée, le premier inscrit venu raflait sinon l'historique et la consommation
    de Baptiste. Le drapeau est le consentement explicite du propriétaire des données."""
    client, server = _client(monkeypatch, tmp_path)
    from history import NicheHistory
    from usage import UsageMeter
    NicheHistory(tmp_path / "h.db").enregistrer("local", "scout", "ancienne", {"global_score": 7.0})
    UsageMeter(tmp_path / "u.db").enregistrer("local", "scout", 0.03, n_analyses=1)

    r = client.post("/api/auth/inscription",
                    json={"email": "baptiste@example.com", "mot_de_passe": MDP,
                          "reprendre_donnees_locales": True})
    assert r.status_code == 201 and r.json()["donnees_locales_reprises"] is True
    assert client.get("/api/history", params={"niche": "ancienne"}).json()["passages"]
    assert client.get("/api/usage").json()["n_analyses"] == 1


def test_le_second_compte_n_adopte_rien(tmp_path, monkeypatch):
    """Sinon chaque nouveau client hériterait de l'historique de Baptiste."""
    client, server = _client(monkeypatch, tmp_path)
    from history import NicheHistory
    NicheHistory(tmp_path / "h.db").enregistrer("local", "scout", "ancienne", {"global_score": 7.0})

    _inscrire(client, "premier@example.com")
    client.post("/api/auth/deconnexion")
    _inscrire(client, "second@example.com")
    assert not client.get("/api/history", params={"niche": "ancienne"}).json()["passages"]
