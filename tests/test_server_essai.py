"""L'essai gratuit côté serveur (2026-10-15).

Décision de Baptiste : un nouveau compte reçoit **2 recherches** (5 niches au plus chacune, donc 10) et 4
analyses détaillées, sans carte bancaire ; un plafond global de nouveaux essais par jour borne la perte
quoi que fassent les fraudeurs ; ensuite un « plan » dira si le compte est abonné.

Ce que ces tests tiennent, ce sont les endroits où l'offre se retourne contre le vendeur ou contre le client :

- le premier compte (amorçage) n'est JAMAIS limité, tous les suivants le sont ;
- une saisie refusée (400) ou un fournisseur à sec (503) ne brûle PAS une recherche d'essai ;
- une analyse qui échoue sans rien dépenser rend sa recherche (même règle que les niches) ;
- un refus après coup (plafond de niches) défait aussi le démarrage de l'essai ;
- les messages disent la cause : « terminé », « indisponible depuis ce réseau », « quota du jour ».

Aucun moteur réel n'est atteint : les runners sont bouchonnés.
"""
import pytest

import essai
from tests.conftest import isoler_bases, ouvrir_session
from tests.test_server_jobs import _attendre_job


def _instance(monkeypatch, tmp_path, par_jour=None):
    pytest.importorskip("httpx")
    from fastapi.testclient import TestClient
    import server
    isoler_bases(monkeypatch, server, tmp_path)
    monkeypatch.delenv("PLAFOND_NICHES_MENSUEL", raising=False)
    monkeypatch.delenv("ESSAIS_PAR_JOUR_MAX", raising=False)
    monkeypatch.delenv("INSCRIPTIONS_OUVERTES", raising=False)
    if par_jour is not None:
        monkeypatch.setenv("ESSAIS_PAR_JOUR_MAX", str(par_jour))
    return TestClient(server.app), server


def _proprietaire(client):
    """Le PREMIER compte : amorçage, illimité."""
    return ouvrir_session(client, "proprio@gmail.com")


def _essai(client, monkeypatch, email="visiteur@gmail.com"):
    """Un compte créé APRÈS le premier : en essai. Le cookie du client devient le sien."""
    monkeypatch.setenv("INSCRIPTIONS_OUVERTES", "1")
    return ouvrir_session(client, email)


def _runner(mesurees=5, depense=False, leve=None):
    def run(params, progress, cost, user_id):
        if depense:
            cost.add_llm("claude-sonnet-5", 1000, 1000)
        if leve is not None:
            raise leve
        return [{"niche": f"m{i}", "concurrence_mesuree": True} for i in range(mesurees)]
    return run


def _lancer(client, server, monkeypatch, runner=None, n_search=5, attendre=True):
    monkeypatch.setitem(server._JOB_RUNNERS, "scout", runner or _runner())
    r = client.post("/api/jobs", json={"type": "scout", "n_search": n_search})
    if r.status_code != 202 or not attendre:
        return r
    _attendre_job(client, r.json()["id"])
    return r


def _situation(client):
    return client.get("/api/usage").json()["essai"]


# ── Le plan ─────────────────────────────────────────────────────────────────────────────

def test_le_premier_compte_est_illimite_les_suivants_en_essai(tmp_path, monkeypatch):
    client, server = _instance(monkeypatch, tmp_path)
    _proprietaire(client)
    assert client.get("/api/auth/moi").json()["plan"] == "illimite"
    _essai(client, monkeypatch)
    assert client.get("/api/auth/moi").json()["plan"] == "essai"


def test_usage_dit_ou_en_est_l_essai(tmp_path, monkeypatch):
    client, server = _instance(monkeypatch, tmp_path)
    _proprietaire(client)
    u = client.get("/api/usage").json()
    assert u["plan"] == "illimite" and u["essai"] is None
    _essai(client, monkeypatch)
    u = client.get("/api/usage").json()
    assert u["plan"] == "essai"
    assert u["essai"] == {"recherches_restantes": 2, "recherches_max": 2, "niches_par_recherche": 5,
                          "analyses_detaillees_max": 4, "analyses_detaillees_restantes": 4,
                          "demarre": False}


def test_le_proprietaire_n_est_jamais_limite(tmp_path, monkeypatch):
    client, server = _instance(monkeypatch, tmp_path, par_jour=0)       # robinet fermé : sans effet sur lui
    _proprietaire(client)
    for _ in range(3):
        assert _lancer(client, server, monkeypatch, n_search=6).status_code == 202


# ── Deux recherches, cinq niches ────────────────────────────────────────────────────────

def test_deux_recherches_puis_l_essai_est_termine(tmp_path, monkeypatch):
    client, server = _instance(monkeypatch, tmp_path)
    _proprietaire(client)
    _essai(client, monkeypatch)
    assert _lancer(client, server, monkeypatch).status_code == 202
    assert _situation(client)["recherches_restantes"] == 1
    assert _lancer(client, server, monkeypatch).status_code == 202
    assert _situation(client)["recherches_restantes"] == 0
    appels = []
    monkeypatch.setitem(server._JOB_RUNNERS, "scout", lambda *a, **k: appels.append(1) or [])
    r = client.post("/api/jobs", json={"type": "scout", "n_search": 3})
    assert r.status_code == 429
    assert "essai gratuit est terminé" in r.json()["detail"]
    assert "Rien n'a été lancé" in r.json()["detail"]
    assert not appels and len(client.get("/api/jobs").json()) == 2


@pytest.mark.parametrize("type_, champ", [("scout", "n_search"), ("fiction", "n_niches"),
                                          ("lowcontent", "n_search")])
def test_plus_de_cinq_niches_est_refuse_sans_rien_consommer(tmp_path, monkeypatch, type_, champ):
    client, server = _instance(monkeypatch, tmp_path)
    _proprietaire(client)
    _essai(client, monkeypatch)
    params = {"type": type_, champ: 6}
    if type_ == "fiction":
        params["sous_genre"] = sorted(server.load_taxonomy()["sous_genres"])[0]
    r = client.post("/api/jobs", json=params)
    assert r.status_code == 400, r.text
    assert "5 niches" in r.json()["detail"] and "essai gratuit" in r.json()["detail"]
    assert _situation(client) == {"recherches_restantes": 2, "recherches_max": 2,
                                  "niches_par_recherche": 5, "analyses_detaillees_max": 4,
                                  "analyses_detaillees_restantes": 4, "demarre": False}
    assert client.get("/api/usage").json()["n_niches"] == 0


def test_cinq_niches_passent_et_la_valeur_par_defaut_de_l_ancien_formulaire_non(tmp_path, monkeypatch):
    """Sans `n_search`, un run non-fiction en demande 6 : un essai doit le dire plutôt que de rogner."""
    client, server = _instance(monkeypatch, tmp_path)
    _proprietaire(client)
    _essai(client, monkeypatch)
    monkeypatch.setitem(server._JOB_RUNNERS, "scout", _runner())
    assert client.post("/api/jobs", json={"type": "scout"}).status_code == 400
    assert client.post("/api/jobs", json={"type": "scout", "n_search": 5}).status_code == 202


# ── Ce qui ne brûle pas une recherche ───────────────────────────────────────────────────

def test_un_fournisseur_a_sec_ne_brule_pas_l_essai(tmp_path, monkeypatch):
    client, server = _instance(monkeypatch, tmp_path)
    _proprietaire(client)
    _essai(client, monkeypatch)
    monkeypatch.setattr(server, "_lire_solde", lambda frais=False: 0.0)
    monkeypatch.setitem(server._JOB_RUNNERS, "scout", _runner())
    assert client.post("/api/jobs", json={"type": "scout", "n_search": 5}).status_code == 503
    assert _situation(client)["recherches_restantes"] == 2 and _situation(client)["demarre"] is False


def test_un_plafond_de_niches_atteint_defait_aussi_le_demarrage(tmp_path, monkeypatch):
    client, server = _instance(monkeypatch, tmp_path)
    _proprietaire(client)
    _essai(client, monkeypatch)
    monkeypatch.setenv("PLAFOND_NICHES_MENSUEL", "3")                   # 5 demandées, 3 permises
    assert _lancer(client, server, monkeypatch, attendre=False).status_code == 429
    s = _situation(client)
    assert s["recherches_restantes"] == 2 and s["demarre"] is False


def test_une_analyse_qui_echoue_sans_rien_depenser_rend_sa_recherche(tmp_path, monkeypatch):
    client, server = _instance(monkeypatch, tmp_path)
    _proprietaire(client)
    _essai(client, monkeypatch)
    _lancer(client, server, monkeypatch, runner=_runner(leve=RuntimeError("panne")))
    s = _situation(client)
    assert s["recherches_restantes"] == 2 and s["demarre"] is True       # rendue, mais l'essai a bien démarré


def test_une_analyse_qui_echoue_apres_avoir_depense_garde_sa_recherche(tmp_path, monkeypatch):
    """« Lancer puis échouer » ne doit pas être gratuit : même règle que les niches."""
    client, server = _instance(monkeypatch, tmp_path)
    _proprietaire(client)
    _essai(client, monkeypatch)
    _lancer(client, server, monkeypatch, runner=_runner(depense=True, leve=RuntimeError("panne")))
    assert _situation(client)["recherches_restantes"] == 1


def test_le_reglement_d_un_echec_a_zero_rend_la_recherche_quel_que_soit_l_executeur(tmp_path, monkeypatch):
    """Le serveur, le worker et la récupération des orphelins passent tous par `_regler_niches` : c'est là que
    se rend la recherche, jamais dans un seul des chemins."""
    client, server = _instance(monkeypatch, tmp_path)
    _proprietaire(client)
    uid = _essai(client, monkeypatch)
    magasin = server.UserStore(server._USERS_DB)
    magasin.reserver_recherche_essai(uid, client=None, par_jour_max=20)
    server._regler_niches(uid, "scout", {"n_search": 5}, "echec", 0.0)
    assert magasin.situation_essai(uid)["recherches_restantes"] == 2
    magasin.reserver_recherche_essai(uid, client=None, par_jour_max=20)
    server._regler_niches(uid, "scout", {"n_search": 5}, "echec", 0.02)     # dépense : gardée
    assert magasin.situation_essai(uid)["recherches_restantes"] == 1
    server._regler_niches(uid, "scout", {"n_search": 5}, "termine", 0.05, [])   # réussi : gardée
    assert magasin.situation_essai(uid)["recherches_restantes"] == 1


# ── Plafond global du jour, identités, réseau ───────────────────────────────────────────

def test_le_plafond_global_du_jour_dit_quota_journalier_du_serveur(tmp_path, monkeypatch):
    client, server = _instance(monkeypatch, tmp_path, par_jour=1)
    _proprietaire(client)
    _essai(client, monkeypatch, "premier@gmail.com")
    assert _lancer(client, server, monkeypatch).status_code == 202
    _essai(client, monkeypatch, "second@gmail.com")
    appels = []
    monkeypatch.setitem(server._JOB_RUNNERS, "scout", lambda *a, **k: appels.append(1) or [])
    r = client.post("/api/jobs", json={"type": "scout", "n_search": 5})
    assert r.status_code == 429
    assert "quota gratuit journalier du serveur" in r.json()["detail"].lower()
    assert "Rien n'a été lancé" in r.json()["detail"]
    assert not appels
    assert _situation(client)["recherches_restantes"] == 2 and _situation(client)["demarre"] is False


def test_un_essai_deja_demarre_continue_meme_quand_le_plafond_du_jour_est_atteint(tmp_path, monkeypatch):
    client, server = _instance(monkeypatch, tmp_path, par_jour=1)
    _proprietaire(client)
    _essai(client, monkeypatch)
    assert _lancer(client, server, monkeypatch).status_code == 202
    assert _lancer(client, server, monkeypatch).status_code == 202           # la 2e recherche passe


def test_un_alias_de_la_meme_boite_n_a_pas_de_second_essai(tmp_path, monkeypatch):
    client, server = _instance(monkeypatch, tmp_path)
    _proprietaire(client)
    _essai(client, monkeypatch, "jean.martin@gmail.com")
    assert _lancer(client, server, monkeypatch).status_code == 202
    _essai(client, monkeypatch, "jeanmartin+kdp@gmail.com")
    monkeypatch.setitem(server._JOB_RUNNERS, "scout", _runner())
    r = client.post("/api/jobs", json={"type": "scout", "n_search": 5})
    assert r.status_code == 403
    assert "essai gratuit" in r.json()["detail"].lower() and "Rien n'a été lancé" in r.json()["detail"]
    assert "journalier" not in r.json()["detail"].lower()                   # pas « revenez demain »


def test_le_reseau_du_client_est_transmis_au_plafond_par_reseau(tmp_path, monkeypatch):
    client, server = _instance(monkeypatch, tmp_path)
    _proprietaire(client)
    monkeypatch.setattr(server, "_client_distant", lambda request: "8.8.8.8")
    for i in range(essai.ESSAI_PAR_RESEAU):
        _essai(client, monkeypatch, f"v{i}@gmail.com")
        assert _lancer(client, server, monkeypatch).status_code == 202
    _essai(client, monkeypatch, "v9@gmail.com")
    assert _lancer(client, server, monkeypatch, attendre=False).status_code == 403


def test_un_reseau_prive_ne_bloque_personne(tmp_path, monkeypatch):
    """Derrière un proxy mal réglé, tout le monde arrive de la même adresse privée."""
    client, server = _instance(monkeypatch, tmp_path)
    _proprietaire(client)
    monkeypatch.setattr(server, "_client_distant", lambda request: "10.0.0.7")
    for i in range(essai.ESSAI_PAR_RESEAU + 2):
        _essai(client, monkeypatch, f"w{i}@gmail.com")
        assert _lancer(client, server, monkeypatch).status_code == 202


def test_une_adresse_jetable_n_ouvre_pas_d_essai(tmp_path, monkeypatch):
    client, server = _instance(monkeypatch, tmp_path)
    _proprietaire(client)
    _essai(client, monkeypatch, "x@mailinator.com")
    assert _lancer(client, server, monkeypatch, attendre=False).status_code == 403


# ── Analyses détaillées ─────────────────────────────────────────────────────────────────

def test_quatre_analyses_detaillees_a_vie_pendant_l_essai(tmp_path, monkeypatch):
    from fastapi import HTTPException
    from usage import UsageMeter
    client, server = _instance(monkeypatch, tmp_path)
    _proprietaire(client)
    uid = _essai(client, monkeypatch)
    assert _lancer(client, server, monkeypatch).status_code == 202           # l'essai doit avoir démarré
    meter = UsageMeter(server._USAGE_DB)
    for _ in range(essai.ESSAI_APPELS_A_LA_PIECE - 1):
        meter.reserver(uid, "verdict")
    server._verifier_plafond(uid)                                            # le 4e passe
    meter.reserver(uid, "kdp_keywords")
    with pytest.raises(HTTPException) as e:
        server._verifier_plafond(uid)                                        # le 5e non
    assert e.value.status_code == 429
    assert "essai gratuit" in e.value.detail.lower() and "4" in e.value.detail


def test_les_analyses_detaillees_du_proprietaire_gardent_leur_plafond_mensuel(tmp_path, monkeypatch):
    from usage import UsageMeter
    client, server = _instance(monkeypatch, tmp_path)
    uid = _proprietaire(client)
    meter = UsageMeter(server._USAGE_DB)
    for _ in range(essai.ESSAI_APPELS_A_LA_PIECE + 3):
        meter.reserver(uid, "verdict")
    server._verifier_plafond(uid)                                            # 7 < 120 : aucune limite d'essai
