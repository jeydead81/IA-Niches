"""Contrôle du solde du fournisseur AVANT de lancer une analyse.

Run fiction du 2026-10-05 : compte DataForSEO à sec (solde −0,05 $), cinq recherches refusées
« 40200 Payment Required ». Avant d'échouer, le run avait déjà dépensé l'appel de génération des
trios (~0,014 $) et consommé une unité de plafond. Un client qui lance une analyse sur un service
dont le fournisseur est à sec paie donc pour rien — et n'apprend la cause nulle part.

Ce que ce fichier tient :
1. `lire_solde` (GRATUIT : `appendix/user_data`) rend le solde, ou None pour TOUT ce qui n'est pas
   lisible : un solde illisible n'est pas un solde vide (règle 3), le run n'est pas bloqué sur un
   contrôle qui n'a pas pu se faire ;
2. `POST /api/jobs` refuse en 503, AVANT la réservation de l'unité de plafond et avant tout appel
   payant, quand le solde ne couvre pas les recherches du run. Il refuse ce qui échouera à COUP
   SÛR (les recherches : une par niche, jamais servies par le cache en fiction), pas ce qui
   pourrait échouer (les fiches, que le cache peut servir) ;
3. le client ne lit ni le nom du fournisseur ni un montant : un opérateur seul le sait, en local.

FORME RÉELLE : lue le 2026-10-05 sur `appendix/user_data`, réduite aux champs que le code lit
(`tasks[0].result[0].money.balance`). Le reste de la réponse (identifiants du compte) n'est
volontairement pas versionné.
"""
import sys
import time
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "web"))

import search_providers  # noqa: E402
from search_providers import lire_solde  # noqa: E402  (la version d'origine, avant la garde réseau)

_REEL = {"status_code": 20000, "status_message": "Ok.",
         "tasks": [{"status_code": 20000, "status_message": "Ok.",
                    "result": [{"money": {"balance": -0.04899999999999993, "total": 1.01}}]}]}


# ── 1. lire_solde ───────────────────────────────────────────────────────────────

def test_le_solde_est_lu_sur_la_forme_reelle():
    assert lire_solde(get_json=lambda u: _REEL) == pytest.approx(-0.049)


def test_l_adresse_appelee_est_celle_du_solde_gratuit():
    vues = []
    lire_solde(get_json=lambda u: vues.append(u) or _REEL)
    assert vues == ["https://api.dataforseo.com/v3/appendix/user_data"]


@pytest.mark.parametrize("reponse", [
    {}, {"status_code": 40101}, {"status_code": 20000, "tasks": []},
    {"status_code": 20000, "tasks": [{"status_code": 40000}]},
    {"status_code": 20000, "tasks": [{"status_code": 20000, "result": []}]},
    {"status_code": 20000, "tasks": [{"status_code": 20000, "result": [{}]}]},
    {"status_code": 20000, "tasks": [{"status_code": 20000, "result": [{"money": {}}]}]},
    {"status_code": 20000, "tasks": [{"status_code": 20000,
                                      "result": [{"money": {"balance": "12,50"}}]}]},
    {"status_code": 20000, "tasks": [{"status_code": 20000,
                                      "result": [{"money": {"balance": True}}]}]},
    {"status_code": 20000, "tasks": [{"status_code": 20000,
                                      "result": [{"money": {"balance": None}}]}]},
    None, "texte", 7,
])
def test_tout_ce_qui_n_est_pas_lisible_est_None_jamais_zero(reponse):
    assert lire_solde(get_json=lambda u: reponse) is None


def test_une_panne_reseau_est_None_et_ne_leve_pas():
    def get(u):
        raise ConnectionError("réseau coupé")

    assert lire_solde(get_json=get) is None


def test_un_solde_entier_est_rendu_en_flottant():
    r = {"status_code": 20000, "tasks": [{"status_code": 20000,
                                          "result": [{"money": {"balance": 3}}]}]}
    v = lire_solde(get_json=lambda u: r)
    assert v == 3.0 and isinstance(v, float)


def test_la_lecture_par_defaut_a_un_delai_court(monkeypatch):
    """`post_job` est `async` : un fournisseur qui ne répond pas ne doit pas figer le serveur
    30 s (le délai de `_get`). Le contrôle porte son propre délai, de quelques secondes."""
    import inspect
    assert search_providers.SOLDE_DELAI_S <= 10
    assert "SOLDE_DELAI_S" in inspect.getsource(lire_solde)


def test_aucun_test_ne_touche_le_reseau_pour_le_solde():
    """Garde du harnais (conftest) : sans lecteur injecté, la lecture rend None au lieu
    d'appeler DataForSEO avec les identifiants du `.env`."""
    assert search_providers.lire_solde() is None


# ── 2. POST /api/jobs ───────────────────────────────────────────────────────────

@pytest.fixture
def banc(monkeypatch, tmp_path):
    pytest.importorskip("httpx")
    from fastapi.testclient import TestClient
    import server
    from tests.conftest import isoler_bases, ouvrir_session
    isoler_bases(monkeypatch, server, tmp_path)
    lancements = []

    def runner(nom):
        def f(*a, **k):
            lancements.append(nom)
            return []
        return f

    monkeypatch.setattr(server, "run_scout", runner("scout"))
    monkeypatch.setattr(server, "run_fiction_scout", runner("fiction"))
    monkeypatch.setattr(server, "run_lowcontent_scout", runner("lowcontent"))
    c = TestClient(server.app, raise_server_exceptions=False)
    uid = ouvrir_session(c)
    return c, server, uid, lancements


def _corps(type_):
    return {"scout": {"type": "scout"},
            "fiction": {"type": "fiction", "sous_genre": "feel_good", "n_niches": 5},
            "lowcontent": {"type": "lowcontent", "n_search": 5}}[type_]


def _unites(server, uid) -> int:
    from usage import UsageMeter
    return UsageMeter(server._USAGE_DB).resume(uid).n_analyses


@pytest.mark.parametrize("type_", ["scout", "fiction", "lowcontent"])
def test_un_solde_epuise_refuse_les_trois_moteurs_avant_toute_depense(banc, monkeypatch, type_):
    c, server, uid, lancements = banc
    monkeypatch.setattr(server, "_lire_solde", lambda: -0.049)
    r = c.post("/api/jobs", json=_corps(type_))
    assert r.status_code == 503, r.text
    assert lancements == [], "aucun moteur, donc aucun appel de génération payant"
    assert _unites(server, uid) == 0, "l'unité de plafond n'est pas consommée"
    from jobs import JobStore
    assert JobStore(server._JOBS_DB).list_jobs(uid) == [], "aucun travail créé"


def test_le_client_ne_lit_ni_fournisseur_ni_montant(banc, monkeypatch):
    c, server, uid, _ = banc
    monkeypatch.setattr(server, "_lire_solde", lambda: -0.049)
    monkeypatch.setenv("APP_ENV", "prod")
    d = c.post("/api/jobs", json=_corps("fiction")).json()["detail"]
    assert "Rien n'a été lancé" in d and "décompté" in d
    for interdit in ("dataforseo", "fournisseur", "0,049", "0.049", "solde", "40200", "$"):
        assert interdit.lower() not in d.lower(), interdit


def test_hors_production_l_operateur_lit_la_cause(banc, monkeypatch):
    c, server, uid, _ = banc
    monkeypatch.setattr(server, "_lire_solde", lambda: -0.049)
    monkeypatch.delenv("APP_ENV", raising=False)
    d = c.post("/api/jobs", json=_corps("fiction")).json()["detail"]
    assert "Hors production" in d and "solde" in d.lower()
    assert "0,049" not in d and "0.049" not in d and "dataforseo" not in d.lower()


def test_un_solde_suffisant_laisse_passer(banc, monkeypatch):
    c, server, uid, _ = banc
    monkeypatch.setattr(server, "_lire_solde", lambda: 5.0)
    assert c.post("/api/jobs", json=_corps("fiction")).status_code == 202


def test_un_solde_illisible_laisse_passer(banc, monkeypatch):
    """Règle 3 : un contrôle qui n'a pas pu se faire n'est pas un solde vide."""
    c, server, uid, _ = banc
    monkeypatch.setattr(server, "_lire_solde", lambda: None)
    assert c.post("/api/jobs", json=_corps("fiction")).status_code == 202


def test_le_seuil_est_le_cout_des_recherches_du_run_pas_celui_des_fiches(banc, monkeypatch):
    """5 trios = 5 recherches à 0,003 $ = 0,015 $ (devis, lu — jamais recopié). Un solde de 0,01 $
    échoue à coup sûr ; 0,015 $ passe : les fiches, elles, peuvent être servies par le cache."""
    from devis import ventilation_max_estimee
    c, server, uid, _ = banc
    besoin = ventilation_max_estimee("fiction", {"n_niches": 5})["serp_usd"]
    assert besoin == pytest.approx(0.015)
    monkeypatch.setattr(server, "_lire_solde", lambda: besoin - 0.001)
    assert c.post("/api/jobs", json=_corps("fiction")).status_code == 503
    monkeypatch.setattr(server, "_lire_solde", lambda: besoin)
    assert c.post("/api/jobs", json=_corps("fiction")).status_code == 202


def test_le_seuil_suit_le_volume_demande(banc, monkeypatch):
    c, server, uid, _ = banc
    monkeypatch.setattr(server, "_lire_solde", lambda: 0.02)
    assert c.post("/api/jobs", json={"type": "fiction", "sous_genre": "feel_good",
                                     "n_niches": 3}).status_code == 202
    assert c.post("/api/jobs", json={"type": "fiction", "sous_genre": "feel_good",
                                     "n_niches": 8}).status_code == 503


def test_une_requete_invalide_est_refusee_avant_la_lecture_du_solde(banc, monkeypatch):
    c, server, uid, _ = banc
    lectures = []
    monkeypatch.setattr(server, "_lire_solde", lambda: lectures.append(1) or -1.0)
    assert c.post("/api/jobs", json={"type": "inconnu"}).status_code == 400
    assert c.post("/api/jobs", json={"type": "fiction", "sous_genre": "feel_good",
                                     "n_niches": 9999}).status_code == 400
    assert lectures == [], "une saisie fautive est une 400, pas un diagnostic de service"


def test_le_controle_se_fait_avant_la_reservation_de_l_unite(banc, monkeypatch):
    """Sinon un client dont le service est à sec paierait une unité de son plafond mensuel."""
    c, server, uid, _ = banc
    monkeypatch.setattr(server, "_lire_solde", lambda: -1.0)
    monkeypatch.setenv("PLAFOND_ANALYSES_MENSUEL", "1")
    for _ in range(3):
        assert c.post("/api/jobs", json=_corps("fiction")).status_code == 503
    monkeypatch.setattr(server, "_lire_solde", lambda: 5.0)
    assert c.post("/api/jobs", json=_corps("fiction")).status_code == 202, \
        "l'unique unité du plafond est restée intacte"


# ── 3. Le cache de lecture ──────────────────────────────────────────────────────

def test_la_lecture_est_mise_en_cache_quelques_secondes(monkeypatch):
    import server
    server._SOLDE_CACHE.update(t=0.0, v=None)
    lectures = []
    monkeypatch.setattr(server._sp, "lire_solde", lambda *a, **k: lectures.append(1) or 2.5)
    assert server._lire_solde() == 2.5 and server._lire_solde() == 2.5
    assert len(lectures) == 1


def test_le_cache_expire_pour_voir_une_recharge_du_compte(monkeypatch):
    import server
    server._SOLDE_CACHE.update(t=0.0, v=None)
    valeurs = iter([-0.05, 4.0])
    monkeypatch.setattr(server._sp, "lire_solde", lambda *a, **k: next(valeurs))
    t = [1000.0]
    monkeypatch.setattr(server.time, "monotonic", lambda: t[0])
    assert server._lire_solde() == -0.05
    t[0] += server._SOLDE_TTL_S + 1
    assert server._lire_solde() == 4.0
    assert server._SOLDE_TTL_S <= 60, "une recharge doit se voir en moins d'une minute"
