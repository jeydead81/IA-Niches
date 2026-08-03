"""test_securite_inscription.py — les trois derniers points de la revue adversariale.

Deux étaient classés « basse » (cookie Secure oublié au déploiement, énumération des
comptes par l'inscription) et un « élevée » que ma synthèse avait omis : l'inscription est
libre et illimitée, or le plafond mensuel est PAR utilisateur — il suffit donc de créer un
compte de plus pour repartir avec un plafond neuf, et chaque compte coûte de l'argent réel.

Le même garde couvre les trois : fermer l'inscription par défaut supprime à la fois la
fabrique à plafonds et l'oracle d'énumération, et déduire `Secure` du protocole supprime le
réglage qu'on oublie."""
import pytest

from tests.conftest import MDP_TEST, isoler_bases


def _client(monkeypatch, tmp_path, **env):
    pytest.importorskip("httpx")
    from fastapi.testclient import TestClient
    import server
    isoler_bases(monkeypatch, server, tmp_path)
    for k, v in env.items():
        monkeypatch.setenv(k, v)
    return TestClient(server.app), server


def _inscrire(client, email, **extra):
    return client.post("/api/auth/inscription",
                       json={"email": email, "mot_de_passe": MDP_TEST, **extra})


# ── 1. Le cookie Secure se déduit du protocole ──────────────────────────────────────

def test_en_https_le_cookie_est_secure_sans_aucune_configuration(tmp_path, monkeypatch):
    """CONFIRMÉ EN REVUE. `COOKIE_SECURE` valait 0 par défaut : un déploiement qui oublie la
    variable diffuse un jeton de 30 jours en clair. Documenter un réglage ne suffit pas —
    ce qui s'oublie doit se déduire. Le protocole est connu à chaque requête."""
    client, _ = _client(monkeypatch, tmp_path)
    r = client.post("/api/auth/inscription",
                    json={"email": "a@b.fr", "mot_de_passe": MDP_TEST},
                    headers={"X-Forwarded-Proto": "https"})
    assert "secure" in r.headers.get("set-cookie", "").lower()


def test_en_http_local_le_cookie_reste_utilisable(tmp_path, monkeypatch):
    """Le garde ne doit pas rendre la connexion impossible en local : sur http://127.0.0.1,
    un cookie Secure ne partirait jamais et personne ne pourrait se connecter."""
    client, _ = _client(monkeypatch, tmp_path)
    r = _inscrire(client, "a@b.fr")
    assert "secure" not in r.headers.get("set-cookie", "").lower()
    assert client.get("/api/auth/moi").status_code == 200


def test_cookie_secure_explicite_force_le_drapeau(tmp_path, monkeypatch):
    """La variable reste utile pour un déploiement derrière un proxy qui n'annonce pas le
    protocole : elle FORCE, elle ne désactive plus rien."""
    client, _ = _client(monkeypatch, tmp_path, COOKIE_SECURE="1")
    r = _inscrire(client, "a@b.fr")
    assert "secure" in r.headers.get("set-cookie", "").lower()


# ── 2. L'inscription n'est pas une fabrique à plafonds ──────────────────────────────

def test_le_premier_compte_s_installe_toujours(tmp_path, monkeypatch):
    """Amorçage : sur une installation neuve, il n'y a personne pour ouvrir les
    inscriptions. Le premier compte doit donc passer, sinon le produit est inutilisable."""
    client, _ = _client(monkeypatch, tmp_path)
    assert _inscrire(client, "baptiste@example.com").status_code == 201


def test_les_inscriptions_suivantes_sont_fermees_par_defaut(tmp_path, monkeypatch):
    """CONFIRMÉ EN REVUE (élevée). Le plafond mensuel est PAR utilisateur : un compte de
    plus, c'est un plafond neuf. Un anonyme pouvait donc dépenser sans limite en créant des
    comptes — et chaque analyse coûte de l'argent réel. Fermé par défaut : c'est le bon
    défaut tant qu'aucun paiement n'est branché."""
    client, _ = _client(monkeypatch, tmp_path)
    assert _inscrire(client, "baptiste@example.com").status_code == 201
    r = _inscrire(client, "intrus@example.com")
    assert r.status_code == 403
    assert "inscription" in r.json()["detail"].lower()


def test_les_inscriptions_s_ouvrent_explicitement(tmp_path, monkeypatch):
    """Le jour où le paiement sera branché, une variable suffit à rouvrir."""
    client, _ = _client(monkeypatch, tmp_path, INSCRIPTIONS_OUVERTES="1")
    assert _inscrire(client, "baptiste@example.com").status_code == 201
    assert _inscrire(client, "client@example.com").status_code == 201


# ── 3. Plus d'oracle d'énumération à grande échelle ─────────────────────────────────

def test_l_inscription_fermee_ne_dit_pas_si_l_adresse_existe(tmp_path, monkeypatch):
    """CONFIRMÉ EN REVUE (basse). L'inscription rendait 409 sur une adresse connue et 201
    sur une inconnue : l'oracle annulait l'anti-énumération soignée de la connexion. Une
    inscription fermée doit répondre PAREIL dans les deux cas."""
    client, _ = _client(monkeypatch, tmp_path)
    _inscrire(client, "baptiste@example.com")

    connue = _inscrire(client, "baptiste@example.com")
    inconnue = _inscrire(client, "jamais-vue@example.com")
    assert connue.status_code == inconnue.status_code == 403
    assert connue.json()["detail"] == inconnue.json()["detail"]


def test_inscriptions_ouvertes_l_oracle_est_limite_en_debit(tmp_path, monkeypatch):
    """Quand les inscriptions sont ouvertes, on ne PEUT pas cacher qu'une adresse est prise
    sans mentir à l'utilisateur légitime. On empêche alors l'énumération EN MASSE : la
    limitation porte sur le client, pas sur l'adresse — sinon sonder mille adresses
    différentes ne déclencherait jamais rien."""
    client, _ = _client(monkeypatch, tmp_path, INSCRIPTIONS_OUVERTES="1")
    codes = [_inscrire(client, f"sonde{i}@example.com").status_code for i in range(15)]
    assert 429 in codes, "aucune limitation après 15 inscriptions depuis le même client"
