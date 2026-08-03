"""test_securite_depense.py — les failles confirmées par la revue adversariale du 2026-08-03.

Dans ce produit, chaque analyse coûte de l'argent réel (DataForSEO + API Anthropic). Une
faille qui fait dépenser n'est donc pas un risque théorique : c'est une facture. Les tests
ci-dessous ferment, dans l'ordre de gravité, ce que la revue a REPRODUIT — pas ce qu'elle a
supposé (sept failles annoncées ont été écartées après réfutation et n'ont pas de test ici).

Aucun moteur réel n'est jamais atteint : `run_scout`, `run_fiction_scout`, le verdict et les
mots-clés sont bouchonnés. Un test de sécurité qui dépense pour prouver qu'on dépense trop
serait une contradiction — et c'est déjà arrivé dans cette session."""
import time

import pytest

from tests.conftest import MDP_TEST, isoler_bases, ouvrir_session


def _client(monkeypatch, tmp_path, plafond=None):
    pytest.importorskip("httpx")
    from fastapi.testclient import TestClient
    import server
    isoler_bases(monkeypatch, server, tmp_path)
    if plafond is not None:
        monkeypatch.setenv("PLAFOND_ANALYSES_MENSUEL", str(plafond))
    client = TestClient(server.app)
    uid = ouvrir_session(client)
    return client, server, uid


def _sans_moteur(monkeypatch, server):
    """Neutralise tout ce qui dépense. Le corps des SSE n'est lu par aucun de ces tests."""
    monkeypatch.setattr(server, "run_scout", lambda **kw: [])
    monkeypatch.setattr(server, "run_fiction_scout", lambda *a, **kw: [])
    monkeypatch.setattr(server, "generate_verdict", lambda *a, **kw: None)
    monkeypatch.setattr(server, "generer_mots_cles", lambda *a, **kw: None)


# ── 1. Toute dépense passe par le plafond ───────────────────────────────────────────

@pytest.mark.parametrize("methode,chemin,corps", [
    ("get", "/api/scout?seed=x", None),
    ("get", "/api/fiction?sous_genre=cosy_mystery", None),
    ("post", "/api/verdict", {"niche": "x", "global_score": 7.0}),
    ("post", "/api/kdp-keywords", {"niche": "x", "global_score": 7.0}),
])
def test_aucun_endpoint_payant_ne_depense_au_dela_du_plafond(tmp_path, monkeypatch,
                                                             methode, chemin, corps):
    """CONFIRMÉ EN REVUE (critique et élevée). `UsageMeter.autorise` n'avait qu'UN SEUL site
    d'appel dans tout le dépôt : `POST /api/jobs`. Les quatre endpoints ci-dessous
    dépensaient donc sans jamais consulter le plafond — or ce sont ceux que l'interface
    utilise réellement. Un plafond qui ne couvre que le chemin que personne n'emprunte ne
    protège rien."""
    client, server, uid = _client(monkeypatch, tmp_path, plafond=0)
    _sans_moteur(monkeypatch, server)
    r = getattr(client, methode)(chemin, **({"json": corps} if corps else {}))
    assert r.status_code == 429, f"{methode.upper()} {chemin} a dépensé malgré le plafond"


def test_les_endpoints_sse_imputent_leur_consommation(tmp_path, monkeypatch):
    """Ils ne comptaient rien : le bandeau « Ce mois-ci » restait à 0 quoi que fasse
    l'utilisateur, et le plafond ne pouvait jamais être atteint puisque rien ne montait."""
    client, server, uid = _client(monkeypatch, tmp_path)
    _sans_moteur(monkeypatch, server)
    assert client.get("/api/usage").json()["n_analyses"] == 0
    client.get("/api/scout?seed=x")
    assert client.get("/api/usage").json()["n_analyses"] == 1


# ── 2. Les paramètres de volume sont bornés ─────────────────────────────────────────

@pytest.mark.parametrize("chemin", [
    "/api/scout?ideas=9999&search=9999",
    "/api/fiction?sous_genre=cosy_mystery&n_niches=9999",
])
def test_les_parametres_de_volume_sont_bornes(tmp_path, monkeypatch, chemin):
    """CONFIRMÉ EN REVUE (moyenne). Le plafond compte des ANALYSES, pas des appels payants :
    une seule « analyse » avec search=9999 coûte des milliers de requêtes DataForSEO tout en
    ne consommant qu'une unité du plafond. Borner le volume est la seule protection réelle
    du montant."""
    client, server, uid = _client(monkeypatch, tmp_path)
    _sans_moteur(monkeypatch, server)
    assert client.get(chemin).status_code == 400


def test_un_job_ne_peut_pas_non_plus_demander_un_volume_illimite(tmp_path, monkeypatch):
    client, server, uid = _client(monkeypatch, tmp_path)
    _sans_moteur(monkeypatch, server)
    r = client.post("/api/jobs", json={"type": "scout", "n_ideas": 9999, "n_search": 9999})
    assert r.status_code == 400


# ── 3. Pas de dépense déclenchable depuis un autre site ─────────────────────────────

def test_une_page_tierce_ne_peut_pas_declencher_une_depense(tmp_path, monkeypatch):
    """CONFIRMÉ EN REVUE (élevée). `/api/scout` et `/api/fiction` sont des GET : une simple
    balise <img> ou une navigation depuis un site malveillant les déclenche, et SameSite=Lax
    laisse partir le cookie sur une navigation de premier niveau. L'argent de Baptiste se
    dépense alors depuis l'onglet d'un site qu'il visite."""
    client, server, uid = _client(monkeypatch, tmp_path)
    _sans_moteur(monkeypatch, server)
    r = client.get("/api/scout?seed=x", headers={"Sec-Fetch-Site": "cross-site"})
    assert r.status_code == 403
    r = client.get("/api/scout?seed=x", headers={"Origin": "https://mechant.example"})
    assert r.status_code == 403


def test_une_requete_du_meme_site_passe(tmp_path, monkeypatch):
    """Le garde ne doit pas casser l'usage normal : l'interface envoie same-origin."""
    client, server, uid = _client(monkeypatch, tmp_path)
    _sans_moteur(monkeypatch, server)
    assert client.get("/api/scout?seed=x",
                      headers={"Sec-Fetch-Site": "same-origin"}).status_code == 200


# ── 4. Cloisonnement des jobs (IDOR) ────────────────────────────────────────────────

def test_un_compte_ne_lit_pas_le_job_d_un_autre(tmp_path, monkeypatch):
    """CONFIRMÉ EN REVUE (moyenne). `GET /api/jobs/{id}` liait bien `user_id` mais ne s'en
    servait jamais : connaître un identifiant suffisait à lire le résultat, le coût et la
    progression du run de quelqu'un d'autre — c'est-à-dire les niches qu'il analyse."""
    client, server, uid = _client(monkeypatch, tmp_path)
    _sans_moteur(monkeypatch, server)
    job_id = client.post("/api/jobs", json={"type": "scout"}).json()["id"]

    client.post("/api/auth/deconnexion")
    client.post("/api/auth/inscription",
                json={"email": "autre@example.com", "mot_de_passe": MDP_TEST})
    assert client.get(f"/api/jobs/{job_id}").status_code == 404
    flux = client.get(f"/api/jobs/{job_id}/stream").text
    assert "resultat" not in flux and "result" not in flux


# ── 5. L'adoption des données locales n'est pas un butin ────────────────────────────

def test_l_adoption_des_donnees_locales_doit_etre_demandee(tmp_path, monkeypatch):
    """CONFIRMÉ EN REVUE (moyenne). Le premier inscrit VENU raflait l'historique et l'usage
    accumulés sous « local ». Sur une instance exposée, le premier visiteur devenait
    propriétaire des données de Baptiste. La reprise doit être demandée explicitement."""
    client, server, uid = _client(monkeypatch, tmp_path)
    from history import NicheHistory
    NicheHistory(tmp_path / "history.db").enregistrer("local", "scout", "ancienne",
                                                      {"global_score": 7.0})
    client.post("/api/auth/deconnexion")
    r = client.post("/api/auth/inscription",
                    json={"email": "opportuniste@example.com", "mot_de_passe": MDP_TEST})
    assert r.status_code == 201
    assert r.json()["donnees_locales_reprises"] is False
    assert not client.get("/api/history", params={"niche": "ancienne"}).json()["passages"]


def test_le_premier_compte_reprend_s_il_le_demande(tmp_path, monkeypatch):
    pytest.importorskip("httpx")
    from fastapi.testclient import TestClient
    import server
    isoler_bases(monkeypatch, server, tmp_path)
    from history import NicheHistory
    NicheHistory(tmp_path / "history.db").enregistrer("local", "scout", "ancienne",
                                                      {"global_score": 7.0})
    client = TestClient(server.app)
    r = client.post("/api/auth/inscription",
                    json={"email": "baptiste@example.com", "mot_de_passe": MDP_TEST,
                          "reprendre_donnees_locales": True})
    assert r.status_code == 201 and r.json()["donnees_locales_reprises"] is True
    assert client.get("/api/history", params={"niche": "ancienne"}).json()["passages"]


# ── 6. Robustesse des entrées ───────────────────────────────────────────────────────

@pytest.mark.parametrize("corps", [
    "pas du json", '{"email": 42, "mot_de_passe": 42}', '{"email": [], "mot_de_passe": {}}',
])
def test_un_corps_malforme_rend_400_jamais_500(tmp_path, monkeypatch, corps):
    """CONFIRMÉ EN REVUE (basse). Une 500 sur entrée malformée expose une trace et signale
    à l'attaquant qu'il a trouvé un chemin non prévu."""
    pytest.importorskip("httpx")
    from fastapi.testclient import TestClient
    import server
    isoler_bases(monkeypatch, server, tmp_path)
    client = TestClient(server.app, raise_server_exceptions=False)
    for chemin in ("/api/auth/inscription", "/api/auth/connexion"):
        r = client.post(chemin, content=corps.encode(),
                        headers={"Content-Type": "application/json"})
        assert r.status_code == 400, f"{chemin} sur {corps[:20]} -> {r.status_code}"


def test_un_mot_de_passe_demesure_est_refuse(tmp_path, monkeypatch):
    """CONFIRMÉ EN REVUE (moyenne). Sans longueur maximale, un mot de passe de plusieurs
    mégaoctets fait tourner scrypt très longtemps ; quelques requêtes parallèles suffisent
    alors à figer le serveur, sans authentification et sans coût pour l'attaquant."""
    pytest.importorskip("httpx")
    from fastapi.testclient import TestClient
    import server
    isoler_bases(monkeypatch, server, tmp_path)
    client = TestClient(server.app)
    r = client.post("/api/auth/inscription",
                    json={"email": "a@b.fr", "mot_de_passe": "x" * 10_000})
    assert r.status_code == 400


def test_un_mot_de_passe_trop_courant_est_refuse(tmp_path, monkeypatch):
    """CONFIRMÉ EN REVUE. « azertyuiop » et « motdepasse » passaient la règle des 10
    caractères. C'est la politique de mot de passe, et non le réglage de scrypt, qui décide
    si un dictionnaire casse les comptes — la revue l'a mesuré : le dictionnaire tombe dans
    les trois paramétrages testés."""
    pytest.importorskip("httpx")
    from fastapi.testclient import TestClient
    import server
    isoler_bases(monkeypatch, server, tmp_path)
    client = TestClient(server.app)
    for faible in ("azertyuiop", "motdepasse", "1234567890"):
        r = client.post("/api/auth/inscription",
                        json={"email": f"{faible}@b.fr", "mot_de_passe": faible})
        assert r.status_code == 400, f"« {faible} » a été accepté"


# ── 7. Le serveur reste répondant sous des connexions répétées ──────────────────────

def test_les_tentatives_de_connexion_sont_limitees(tmp_path, monkeypatch):
    """CONFIRMÉ EN REVUE (basse, mais c'est le chemin le plus court vers une prise de
    compte). Sans limitation, un top-1000 de mots de passe se teste EN LIGNE en moins d'une
    minute contre une adresse connue."""
    client, server, uid = _client(monkeypatch, tmp_path)
    client.post("/api/auth/deconnexion")
    codes = [client.post("/api/auth/connexion",
                         json={"email": "test@example.com",
                               "mot_de_passe": "mauvais-mot-de-passe"}).status_code
             for _ in range(12)]
    assert 429 in codes, "aucune limitation après 12 tentatives infructueuses"
