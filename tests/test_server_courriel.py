"""Vérification d'e-mail et mot de passe oublié : les routes et le garde (2026-10-06).

Ce qui est en jeu n'est pas le confort : sans adresse vérifiée, un « compte de plus » est un
plafond neuf (INSCRIPTIONS_OUVERTES s'ouvrira un jour), et sans mot de passe récupérable un
client payant se retrouve facturé sans accès, puis conteste le prélèvement.

Aucun courriel réel n'est envoyé : `server._envoyer_courriel` est bouchonné et enregistre ce
qui serait parti.
"""
import re
import threading
import time

import pytest

from tests.conftest import MDP_TEST, isoler_bases

BASE = "https://niches.example.test"
NOUVEAU = "un-autre-mot-de-passe-solide"


def _client(monkeypatch, tmp_path, smtp=True):
    pytest.importorskip("httpx")
    from fastapi.testclient import TestClient
    import server
    isoler_bases(monkeypatch, server, tmp_path)
    for v in ("APP_ENV", "PLAFOND_NICHES_MENSUEL", "NOTIFICATIONS_EMAIL"):
        monkeypatch.delenv(v, raising=False)
    monkeypatch.setenv("BASE_URL", BASE)
    if smtp:
        monkeypatch.setenv("SMTP_HOST", "smtp.example.test")
    else:
        monkeypatch.delenv("SMTP_HOST", raising=False)
    partis = []
    monkeypatch.setattr(server, "_envoyer_courriel",
                        lambda dest, sujet, corps: partis.append((dest, sujet, corps)))
    # Le travail de fond tourne EN LIGNE dans les tests : sans cela, on lirait `partis` avant qu'il
    # n'ait eu lieu (voir test_la_reponse_d_oubli_ne_fait_aucun_travail_dependant_du_compte).
    monkeypatch.setattr(server, "_en_arriere_plan", lambda fn, *a: fn(*a))
    return TestClient(server.app), server, partis


def _inscrire(client, email="a@example.com"):
    r = client.post("/api/auth/inscription", json={"email": email, "mot_de_passe": MDP_TEST})
    assert r.status_code == 201, r.text
    return r.json()


def _jeton(corps: str, param: str) -> str:
    m = re.search(rf"{param}=([A-Za-z0-9_\-]+)", corps)
    assert m, corps
    return m.group(1)


# ── L'inscription envoie un lien ────────────────────────────────────────────────────

def test_l_inscription_envoie_un_lien_de_verification(monkeypatch, tmp_path):
    client, server, partis = _client(monkeypatch, tmp_path)
    d = _inscrire(client)
    assert d["email_verifie"] is False
    assert len(partis) == 1
    dest, sujet, corps = partis[0]
    assert dest == "a@example.com"
    assert f"{BASE}/#verif=" in corps
    assert MDP_TEST not in corps, "un courriel est un canal en clair : jamais le mot de passe"


def test_sans_serveur_de_courriel_l_inscription_reussit_quand_meme(monkeypatch, tmp_path):
    """Poste local : rien à envoyer, rien ne doit casser. En production, c'est le démarrage qui
    refuse cette configuration (voir plus bas), pas l'inscription."""
    client, server, partis = _client(monkeypatch, tmp_path, smtp=False)
    assert _inscrire(client)["email_verifie"] is False
    assert partis == []


def test_sans_url_de_base_aucun_lien_mort_n_est_envoye(monkeypatch, tmp_path):
    client, server, partis = _client(monkeypatch, tmp_path)
    monkeypatch.delenv("BASE_URL")
    _inscrire(client)
    assert partis == [], "un lien relatif ne mène nulle part depuis une boîte de réception"


def test_l_envoi_ne_retient_pas_la_reponse(monkeypatch, tmp_path):
    """Un SMTP lent ne doit ni bloquer l'inscription ni laisser deviner, au temps de réponse,
    qu'une adresse existe (mot de passe oublié)."""
    pytest.importorskip("httpx")
    from fastapi.testclient import TestClient
    import server
    isoler_bases(monkeypatch, server, tmp_path)
    monkeypatch.setenv("BASE_URL", BASE)
    monkeypatch.setenv("SMTP_HOST", "smtp.example.test")
    termine = threading.Event()

    def lent(dest, sujet, corps):
        time.sleep(1.0)
        termine.set()

    monkeypatch.setattr(server, "_envoyer_courriel_maintenant", lent)
    client = TestClient(server.app)
    debut = time.monotonic()
    _inscrire(client)
    assert time.monotonic() - debut < 0.9 and not termine.is_set()
    assert termine.wait(3.0)


# ── La vérification ─────────────────────────────────────────────────────────────────

def test_le_lien_verifie_l_adresse(monkeypatch, tmp_path):
    client, server, partis = _client(monkeypatch, tmp_path)
    _inscrire(client)
    jeton = _jeton(partis[0][2], "verif")
    r = client.post("/api/auth/verification", json={"jeton": jeton})
    assert r.status_code == 204
    moi = client.get("/api/auth/moi").json()
    assert moi["email_verifie"] is True
    assert client.post("/api/auth/verification", json={"jeton": jeton}).status_code == 400


def test_un_lien_invalide_dit_invalide_ou_expire_sans_plus(monkeypatch, tmp_path):
    client, server, partis = _client(monkeypatch, tmp_path)
    r = client.post("/api/auth/verification", json={"jeton": "n-importe-quoi"})
    assert r.status_code == 400 and "invalide ou expiré" in r.json()["detail"]
    assert client.post("/api/auth/verification", json={"jeton": 12}).status_code == 400
    assert client.post("/api/auth/verification", json={}).status_code == 400


def test_renvoyer_le_lien_exige_une_session_et_se_limite(monkeypatch, tmp_path):
    client, server, partis = _client(monkeypatch, tmp_path)
    assert client.post("/api/auth/verification/renvoyer").status_code == 401
    _inscrire(client)
    partis.clear()
    for _ in range(3):
        assert client.post("/api/auth/verification/renvoyer").status_code == 204
    assert len(partis) == 3
    assert client.post("/api/auth/verification/renvoyer").status_code == 429
    assert len(partis) == 3, "un refus n'envoie rien"


def test_renvoyer_le_lien_d_une_adresse_deja_verifiee_ne_fait_rien(monkeypatch, tmp_path):
    client, server, partis = _client(monkeypatch, tmp_path)
    _inscrire(client)
    client.post("/api/auth/verification", json={"jeton": _jeton(partis[0][2], "verif")})
    partis.clear()
    assert client.post("/api/auth/verification/renvoyer").status_code == 204
    assert partis == []


# ── Mot de passe oublié ─────────────────────────────────────────────────────────────

def test_le_mot_de_passe_oublie_repond_pareil_pour_une_adresse_connue_ou_non(monkeypatch, tmp_path):
    """Anti-énumération : la réponse, son code et son corps ne disent rien de l'existence du
    compte. Seule la boîte du titulaire reçoit quelque chose."""
    client, server, partis = _client(monkeypatch, tmp_path)
    _inscrire(client)
    partis.clear()
    connue = client.post("/api/auth/mot-de-passe-oublie", json={"email": "a@example.com"})
    inconnue = client.post("/api/auth/mot-de-passe-oublie", json={"email": "z@example.com"})
    assert connue.status_code == inconnue.status_code == 202
    assert connue.json() == inconnue.json()
    assert [p[0] for p in partis] == ["a@example.com"]
    assert f"{BASE}/#reinit=" in partis[0][2]


def test_un_mot_de_passe_oublie_mal_forme_ne_leve_pas(monkeypatch, tmp_path):
    client, server, partis = _client(monkeypatch, tmp_path)
    for corps in ({}, {"email": 3}, {"email": ""}, {"email": None}):
        assert client.post("/api/auth/mot-de-passe-oublie", json=corps).status_code in (202, 400)
    assert partis == []


def test_les_demandes_de_reinitialisation_sont_limitees_par_adresse_connue_ou_non(monkeypatch, tmp_path):
    """Compter aussi les adresses INCONNUES : un 429 qui ne frapperait que les adresses
    existantes serait lui-même un oracle d'énumération."""
    client, server, partis = _client(monkeypatch, tmp_path)
    for adresse in ("a@example.com", "inconnue@example.com"):
        codes = [client.post("/api/auth/mot-de-passe-oublie", json={"email": adresse}).status_code
                 for _ in range(5)]
        assert codes[:3] == [202, 202, 202] and codes[3:] == [429, 429], (adresse, codes)


def test_la_reinitialisation_complete(monkeypatch, tmp_path):
    client, server, partis = _client(monkeypatch, tmp_path)
    _inscrire(client)
    partis.clear()
    client.post("/api/auth/mot-de-passe-oublie", json={"email": "a@example.com"})
    jeton = _jeton(partis[0][2], "reinit")
    # mot de passe refusé : le jeton survit
    faible = client.post("/api/auth/mot-de-passe-reinitialiser",
                         json={"jeton": jeton, "nouveau": "court"})
    assert faible.status_code == 400 and "12" in faible.json()["detail"]
    ok = client.post("/api/auth/mot-de-passe-reinitialiser",
                     json={"jeton": jeton, "nouveau": NOUVEAU})
    assert ok.status_code == 204
    # l'ancienne session est fermée, l'ancien mot de passe ne marche plus, le nouveau si
    assert client.get("/api/auth/moi").status_code == 401
    assert client.post("/api/auth/connexion",
                       json={"email": "a@example.com", "mot_de_passe": MDP_TEST}).status_code == 401
    assert client.post("/api/auth/connexion",
                       json={"email": "a@example.com", "mot_de_passe": NOUVEAU}).status_code == 200
    assert client.get("/api/auth/moi").json()["email_verifie"] is True
    # un lien ne sert qu'une fois
    assert client.post("/api/auth/mot-de-passe-reinitialiser",
                       json={"jeton": jeton, "nouveau": NOUVEAU}).status_code == 400


def test_un_lien_de_reinitialisation_invalide_dit_invalide_ou_expire(monkeypatch, tmp_path):
    client, server, partis = _client(monkeypatch, tmp_path)
    r = client.post("/api/auth/mot-de-passe-reinitialiser",
                    json={"jeton": "faux", "nouveau": NOUVEAU})
    assert r.status_code == 400 and "invalide ou expiré" in r.json()["detail"]
    assert client.post("/api/auth/mot-de-passe-reinitialiser",
                       json={"jeton": "faux", "nouveau": 12}).status_code == 400


# ── Garde anti-CSRF ─────────────────────────────────────────────────────────────────

@pytest.mark.parametrize("chemin,corps", [
    ("/api/auth/verification", {"jeton": "x"}),
    ("/api/auth/verification/renvoyer", {}),
    ("/api/auth/mot-de-passe-oublie", {"email": "a@example.com"}),
    ("/api/auth/mot-de-passe-reinitialiser", {"jeton": "x", "nouveau": NOUVEAU}),
])
def test_une_page_tierce_ne_declenche_aucune_de_ces_routes(monkeypatch, tmp_path, chemin, corps):
    client, server, partis = _client(monkeypatch, tmp_path)
    _inscrire(client)
    partis.clear()
    assert client.post(chemin, json=corps, headers={"Sec-Fetch-Site": "cross-site"}).status_code == 403
    assert partis == []


def test_les_liens_portent_le_jeton_dans_le_fragment_pas_dans_la_requete(monkeypatch, tmp_path):
    """Un fragment (`#verif=...`) n'est JAMAIS envoyé au serveur : il n'entre ni dans le journal
    d'accès d'uvicorn, ni dans celui d'un proxy, ni dans un en-tête Referer. Dans la requête
    (`?verif=...`), le jeton était écrit en clair dans tous les journaux."""
    client, server, partis = _client(monkeypatch, tmp_path)
    _inscrire(client)
    client.post("/api/auth/mot-de-passe-oublie", json={"email": "a@example.com"})
    assert len(partis) == 2
    for _, _, corps in partis:
        assert "/?verif=" not in corps and "/?reinit=" not in corps
        assert "/#verif=" in corps or "/#reinit=" in corps


def test_la_page_ne_fuit_pas_son_adresse_aux_tiers(monkeypatch, tmp_path):
    """Le lien de vérification porte un jeton DANS l'URL : la page charge des polices tierces, et
    un en-tête Referer complet les enverrait avec le jeton."""
    client, server, partis = _client(monkeypatch, tmp_path)
    assert client.get("/").headers.get("referrer-policy") == "no-referrer"


# ── Le garde : une adresse non vérifiée ne dépense pas (production) ─────────────────

def test_en_production_une_adresse_non_verifiee_ne_lance_rien(monkeypatch, tmp_path):
    from usage import UsageMeter
    client, server, partis = _client(monkeypatch, tmp_path)
    monkeypatch.setattr(server, "run_scout", lambda **kw: [])
    _inscrire(client)
    monkeypatch.setenv("APP_ENV", "prod")
    r = client.post("/api/jobs", json={"type": "scout", "n_search": 1})
    assert r.status_code == 403 and "e-mail" in r.json()["detail"].lower()
    assert "rien n" in r.json()["detail"].lower()
    uid = client.get("/api/auth/moi").json()["user_id"]
    assert UsageMeter(server._USAGE_DB).resume(uid).n_analyses == 0, "rien n'est décompté"
    for chemin in ("/api/verdict", "/api/kdp-keywords"):
        assert client.post(chemin, json={"niche": "x", "global_score": 7.0}).status_code == 403
    assert client.post("/api/dossier", json={"niche": {"niche": "x"},
                                             "inclure_mots_cles": True}).status_code == 403


def test_en_production_une_fois_verifiee_l_adresse_lance(monkeypatch, tmp_path):
    client, server, partis = _client(monkeypatch, tmp_path)
    monkeypatch.setattr(server, "run_scout", lambda **kw: [])
    _inscrire(client)
    client.post("/api/auth/verification", json={"jeton": _jeton(partis[0][2], "verif")})
    monkeypatch.setenv("APP_ENV", "prod")
    assert client.post("/api/jobs", json={"type": "scout", "n_search": 1}).status_code == 202


def test_hors_production_le_garde_ne_joue_pas(monkeypatch, tmp_path):
    """Poste local : aucun serveur de courriel, personne à vérifier."""
    client, server, partis = _client(monkeypatch, tmp_path, smtp=False)
    monkeypatch.setattr(server, "run_scout", lambda **kw: [])
    _inscrire(client)
    assert client.post("/api/jobs", json={"type": "scout", "n_search": 1}).status_code == 202


def test_moi_dit_si_la_verification_est_exigee(monkeypatch, tmp_path):
    client, server, partis = _client(monkeypatch, tmp_path)
    _inscrire(client)
    d = client.get("/api/auth/moi").json()
    assert d["email_verifie"] is False and d["verification_requise"] is False
    monkeypatch.setenv("APP_ENV", "prod")
    assert client.get("/api/auth/moi").json()["verification_requise"] is True


# ── Le démarrage en production ──────────────────────────────────────────────────────

def test_la_production_refuse_de_demarrer_sans_serveur_de_courriel(monkeypatch):
    """Sans lui, personne ne pourrait vérifier son adresse : tous les comptes seraient
    verrouillés dehors, sans erreur ni journal — c'est le défaut muet que le dépôt refuse."""
    import server
    monkeypatch.setenv("APP_ENV", "prod")
    monkeypatch.delenv("SMTP_HOST", raising=False)
    monkeypatch.setenv("BASE_URL", BASE)
    with pytest.raises(RuntimeError, match="SMTP_HOST"):
        server._verifier_courriel_prod()


def test_la_production_refuse_de_demarrer_sans_url_de_base(monkeypatch):
    import server
    monkeypatch.setenv("APP_ENV", "prod")
    monkeypatch.setenv("SMTP_HOST", "smtp.example.test")
    monkeypatch.delenv("BASE_URL", raising=False)
    with pytest.raises(RuntimeError, match="BASE_URL"):
        server._verifier_courriel_prod()


def test_hors_production_aucune_exigence_de_courriel(monkeypatch):
    import server
    monkeypatch.delenv("APP_ENV", raising=False)
    monkeypatch.delenv("SMTP_HOST", raising=False)
    monkeypatch.delenv("BASE_URL", raising=False)
    server._verifier_courriel_prod()


def test_les_courriels_de_compte_n_exigent_pas_l_opt_in_des_notifications(monkeypatch):
    """Poser un hôte SMTP n'est pas consentir à des messages de fin d'analyse ; mais un lien
    de vérification n'est pas une notification, c'est le service. Les deux politiques restent
    distinctes."""
    import notification
    monkeypatch.delenv("NOTIFICATIONS_EMAIL", raising=False)
    monkeypatch.setenv("SMTP_HOST", "smtp.example.test")
    assert notification.config_smtp() is None
    assert notification.config_smtp(notifications=False).hote == "smtp.example.test"
    monkeypatch.delenv("SMTP_HOST")
    assert notification.config_smtp(notifications=False) is None


def test_le_corps_du_courriel_ne_porte_que_le_lien(monkeypatch):
    import notification
    sujet, corps = notification.corps_verification("https://x.test/?verif=ABC")
    assert "https://x.test/?verif=ABC" in corps and "verif" in corps
    sujet2, corps2 = notification.corps_reinitialisation("https://x.test/?reinit=DEF")
    assert "https://x.test/?reinit=DEF" in corps2 and "1 heure" in corps2
    assert "ignorez" in corps2.lower(), "le destinataire doit savoir qu'il peut ignorer le message"


# ── Revue adversariale du 2026-10-06 ─────────────────────────────────────────────────

def test_sans_moyen_d_envoyer_un_courriel_l_instance_le_dit(monkeypatch, tmp_path):
    """Répondre « un lien vient d'être envoyé » quand rien ne peut partir ferait attendre un
    courriel qui ne viendra jamais. La réponse ne dépend pas du COMPTE (aucune énumération) : c'est
    un fait de configuration."""
    client, server, partis = _client(monkeypatch, tmp_path, smtp=False)
    _inscrire(client)
    r = client.post("/api/auth/mot-de-passe-oublie", json={"email": "a@example.com"})
    assert r.status_code == 503 and "pas disponible" in r.json()["detail"]
    assert client.post("/api/auth/verification/renvoyer").status_code == 503
    assert partis == []


def test_la_reponse_d_oubli_ne_fait_aucun_travail_dependant_du_compte(monkeypatch, tmp_path):
    """Chercher le compte et créer un jeton coûtent quelques millisecondes de plus pour une adresse
    connue : un oracle d'existence par le temps de réponse. Tout ce qui dépend du compte part en
    arrière-plan, pour une adresse connue COMME pour une inconnue."""
    client, server, partis = _client(monkeypatch, tmp_path)
    _inscrire(client)
    partis.clear()
    lances = []
    monkeypatch.setattr(server, "_en_arriere_plan", lambda fn, *a: lances.append((fn, a)))
    for adresse in ("a@example.com", "inconnue@example.com"):
        assert client.post("/api/auth/mot-de-passe-oublie", json={"email": adresse}).status_code == 202
    assert len(lances) == 2 and partis == []
    import sqlite3
    with sqlite3.connect(server._USERS_DB) as cx:
        assert cx.execute("SELECT COUNT(*) FROM jetons_courriel WHERE usage='reinitialisation'"
                          ).fetchone()[0] == 0, "aucun jeton créé pendant la requête"


def test_la_production_exige_une_url_de_base_en_https(monkeypatch):
    """En http, le jeton de réinitialisation — qui donne la main sur le compte — voyage en clair."""
    import server
    monkeypatch.setenv("APP_ENV", "prod")
    monkeypatch.setenv("SMTP_HOST", "smtp.example.test")
    monkeypatch.setenv("BASE_URL", "http://niches.example.test")
    with pytest.raises(RuntimeError, match="https"):
        server._verifier_courriel_prod()
    monkeypatch.setenv("BASE_URL", "niches.example.test")
    with pytest.raises(RuntimeError, match="https"):
        server._verifier_courriel_prod()
    monkeypatch.setenv("BASE_URL", "https://niches.example.test")
    server._verifier_courriel_prod()
