"""Le plafond mensuel compte des NICHES, plus des runs (2026-10-06).

Un run de 6 niches et un run de 20 niches pesaient la même unité : le compteur ne mesurait ni
le coût ni la valeur livrée, et « 30 analyses par mois » pouvait cacher 600 niches. Le produit
se vend par niche analysée ; le compteur doit dire la même chose que l'offre.

Règles, dans l'ordre de ce qu'elles coûteraient si on les cassait :

1. La place est prise AU LANCEMENT pour toutes les niches demandées (réservation atomique,
   inchangée) : une rafale ne dépasse pas le plafond.
2. Un run RÉUSSI est décompté de ce qu'il a réellement MESURÉ, avec un minimum de une niche :
   « non mesuré » n'est pas une niche livrée (règle 3), mais un run qui a dépensé de l'argent
   ne peut pas être gratuit.
3. Un échec AVANT toute dépense ne consomme rien (décision laissée ouverte au ROADMAP §2.4.6) :
   rien n'a coûté, rien n'a été livré. Un échec APRÈS dépense, comme un arrêt demandé par
   l'utilisateur, garde la réservation entière : arrêter ne rembourse rien, sinon « lancer
   puis arrêter » serait gratuit.

Aucun moteur réel n'est atteint : les runners sont bouchonnés.
"""
import pytest

from tests.conftest import isoler_bases, ouvrir_session
from tests.test_server_jobs import _attendre_job


def _client(monkeypatch, tmp_path, plafond=None):
    pytest.importorskip("httpx")
    from fastapi.testclient import TestClient
    import server
    isoler_bases(monkeypatch, server, tmp_path)
    monkeypatch.delenv("PLAFOND_NICHES_MENSUEL", raising=False)
    if plafond is not None:
        monkeypatch.setenv("PLAFOND_NICHES_MENSUEL", str(plafond))
    client = TestClient(server.app)
    ouvrir_session(client)
    return client, server


def _runner(mesurees=0, non_mesurees=0, depense=False, leve=None):
    """Un moteur bouchonné : rend des cartes (dicts) dont `mesurees` portent une mesure."""
    def run(params, progress, cost, user_id):
        if depense:
            cost.add_llm("claude-sonnet-5", 1000, 1000)
        if leve is not None:
            raise leve
        return ([{"niche": f"m{i}", "concurrence_mesuree": True} for i in range(mesurees)]
                + [{"niche": f"n{i}", "concurrence_mesuree": False}
                   for i in range(non_mesurees)])
    return run


def _lancer(client, server, monkeypatch, runner, n_search=6):
    monkeypatch.setitem(server._JOB_RUNNERS, "scout", runner)
    r = client.post("/api/jobs", json={"type": "scout", "n_search": n_search})
    assert r.status_code == 202, r.text
    return _attendre_job(client, r.json()["id"])


def _niches(client) -> int:
    return client.get("/api/usage").json()["n_niches"]


# ── Ce que le run décompte ──────────────────────────────────────────────────────────

def test_un_run_complet_compte_toutes_ses_niches(tmp_path, monkeypatch):
    client, server = _client(monkeypatch, tmp_path)
    job = _lancer(client, server, monkeypatch, _runner(mesurees=4), n_search=4)
    assert job["statut"] == "termine"
    assert _niches(client) == 4


def test_une_niche_non_mesuree_n_est_pas_decomptee(tmp_path, monkeypatch):
    """Quatre niches demandées, trois mesurées : la quatrième n'a rien livré (recherche Amazon
    tombée). La facturer se lirait comme un vol, et la présenter comme mesurée comme une
    erreur de marché (règle 3)."""
    client, server = _client(monkeypatch, tmp_path)
    _lancer(client, server, monkeypatch, _runner(mesurees=3, non_mesurees=1), n_search=4)
    assert _niches(client) == 3


def test_un_run_qui_ne_mesure_rien_compte_une_niche_au_minimum(tmp_path, monkeypatch):
    """Il a dépensé (idéation) : le rendre gratuit ouvrirait un robinet — des graines absurdes
    en boucle, chacune payant un appel LLM sans jamais rien décompter."""
    client, server = _client(monkeypatch, tmp_path)
    _lancer(client, server, monkeypatch, _runner(mesurees=0, depense=True), n_search=6)
    assert _niches(client) == 1


def test_un_echec_avant_toute_depense_ne_consomme_rien(tmp_path, monkeypatch):
    """Cas du ROADMAP §2.4.6 : autocomplete entièrement indisponible, run arrêté à 0 $. Rien
    n'a été livré ni dépensé : l'utilisateur ne perd pas six niches pour une panne."""
    client, server = _client(monkeypatch, tmp_path)
    job = _lancer(client, server, monkeypatch, _runner(leve=RuntimeError("panne")), n_search=6)
    assert job["statut"] == "echec"
    assert _niches(client) == 0


def test_un_echec_apres_depense_garde_la_reservation(tmp_path, monkeypatch):
    client, server = _client(monkeypatch, tmp_path)
    job = _lancer(client, server, monkeypatch,
                  _runner(depense=True, leve=RuntimeError("panne")), n_search=6)
    assert job["statut"] == "echec"
    assert _niches(client) == 6


# ── Le plafond ──────────────────────────────────────────────────────────────────────

def test_le_plafond_refuse_un_run_trop_gros_en_disant_ce_qui_reste(tmp_path, monkeypatch):
    client, server = _client(monkeypatch, tmp_path, plafond=5)
    monkeypatch.setitem(server._JOB_RUNNERS, "scout", _runner(mesurees=6))
    r = client.post("/api/jobs", json={"type": "scout", "n_search": 6})
    assert r.status_code == 429
    detail = r.json()["detail"]
    assert "niche" in detail and "5" in detail and "6" in detail, detail


def test_le_plafond_laisse_passer_exactement_son_quota(tmp_path, monkeypatch):
    client, server = _client(monkeypatch, tmp_path, plafond=5)
    _lancer(client, server, monkeypatch, _runner(mesurees=5), n_search=5)
    r = client.post("/api/jobs", json={"type": "scout", "n_search": 1})
    assert r.status_code == 429


def test_les_niches_non_mesurees_rendent_de_la_place(tmp_path, monkeypatch):
    """La place libérée à la fin du run profite au suivant : 5 demandées, 3 mesurées, il
    reste deux niches sur un plafond de cinq."""
    client, server = _client(monkeypatch, tmp_path, plafond=5)
    _lancer(client, server, monkeypatch, _runner(mesurees=3, non_mesurees=2), n_search=5)
    assert client.post("/api/jobs", json={"type": "scout", "n_search": 2}).status_code == 202


def test_l_usage_expose_les_niches_et_le_plafond(tmp_path, monkeypatch):
    client, server = _client(monkeypatch, tmp_path, plafond=30)
    d = client.get("/api/usage").json()
    assert d["n_niches"] == 0 and d["plafond_niches"] == 30 and "cout_usd" in d
    assert "n_analyses" not in d, "un compteur de niches ne doit pas porter le nom d'un compteur de runs"


def test_sans_plafond_l_usage_le_dit(tmp_path, monkeypatch):
    client, server = _client(monkeypatch, tmp_path)
    assert client.get("/api/usage").json()["plafond_niches"] is None


# ── Le volume demandé et le volume mesuré, par moteur ───────────────────────────────

@pytest.mark.parametrize("type_,params,attendu", [
    ("scout", {}, 6),
    ("scout", {"n_search": 9}, 9),
    ("scout", {"search": 7}, 7),                      # nom historique, §5.22
    ("fiction", {}, 8),
    ("fiction", {"n_niches": 5}, 5),
    ("lowcontent", {}, 6),
    ("lowcontent", {"n_search": 12}, 12),
])
def test_le_volume_demande_suit_les_defauts_et_les_alias_des_runners(type_, params, attendu):
    import server
    assert server._niches_demandees(type_, params) == attendu


def test_le_volume_demande_ne_leve_jamais():
    """Appelé à la fin d'un run, parfois depuis le worker : une exception ici ferait échouer
    un run payé pour un souci de comptabilité."""
    import server
    assert server._niches_demandees("scout", {"n_search": "beaucoup"}) == 6
    assert server._niches_demandees("scout", {"n_search": 99999}) == server.MAX_RECHERCHES


def test_les_niches_mesurees_se_lisent_sur_le_bon_drapeau_de_chaque_moteur():
    import server
    scout = [{"concurrence_mesuree": True}, {"concurrence_mesuree": False}, {}]
    assert server._niches_mesurees("scout", scout) == 1
    assert server._niches_mesurees("lowcontent", scout) == 1
    fiction = [{"demand_matrix": "desert"}, {"demand_matrix": "non_mesurable"},
               {"demand_matrix": "mesure_mince"}, {"demand_matrix": "mur_installe"}]
    assert server._niches_mesurees("fiction", fiction) == 2
    assert server._niches_mesurees("scout", None) == 0
    assert server._niches_mesurees("scout", "pas une liste") == 0


# ── Le renommage de la variable ─────────────────────────────────────────────────────

def test_l_ancien_nom_du_plafond_refuse_le_demarrage_en_production(monkeypatch):
    """PLAFOND_ANALYSES_MENSUEL comptait des runs. Lue comme des niches elle serait 6 fois
    trop stricte ; ignorée, elle ouvrirait un service SANS plafond, en silence — c'est le sens
    dangereux. Le refus de démarrer est la seule issue lisible, comme pour BSR_SOURCE."""
    import server
    monkeypatch.setenv("APP_ENV", "prod")
    monkeypatch.setenv("BSR_SOURCE", "dataforseo")
    monkeypatch.setenv("PLAFOND_ANALYSES_MENSUEL", "30")
    with pytest.raises(RuntimeError, match="PLAFOND_NICHES_MENSUEL"):
        server._verifier_config_prod()


def test_le_nouveau_nom_est_lu(monkeypatch):
    import server
    monkeypatch.setenv("PLAFOND_NICHES_MENSUEL", "30")
    assert server._plafond_niches_mensuel() == 30
    monkeypatch.delenv("PLAFOND_NICHES_MENSUEL")
    assert server._plafond_niches_mensuel() is None


# ── Le worker règle le décompte comme le serveur ────────────────────────────────────

def _worker_run(tmp_path, monkeypatch, runner, params):
    """Un job empilé puis exécuté par `worker.executer_un_job` ; rend les imputations."""
    import worker
    from jobs import JobStore
    store = JobStore(tmp_path / "jobs.db")
    store.create("scout", params, user_id="u")
    imputes = []
    monkeypatch.setattr(worker, "_RUNNERS", {"scout": runner})
    monkeypatch.setattr(worker, "_imputer", lambda uid, t, usd, n: imputes.append((t, usd, n)))
    worker.executer_un_job(store)
    return imputes


def test_le_worker_rend_les_niches_non_mesurees(tmp_path, monkeypatch):
    imputes = _worker_run(tmp_path, monkeypatch, _runner(mesurees=3, non_mesurees=1, depense=True),
                          {"n_search": 4})
    assert ("scout", 0.0, -1) in imputes, imputes


def test_le_worker_ne_rend_rien_apres_une_depense_suivie_d_un_echec(tmp_path, monkeypatch):
    imputes = _worker_run(tmp_path, monkeypatch,
                          _runner(depense=True, leve=RuntimeError("boum")), {"n_search": 4})
    assert all(n >= 0 for _, _, n in imputes), imputes


def test_le_worker_rend_tout_apres_un_echec_sans_depense(tmp_path, monkeypatch):
    imputes = _worker_run(tmp_path, monkeypatch, _runner(leve=RuntimeError("boum")),
                          {"n_search": 4})
    assert ("scout", 0.0, -4) in imputes, imputes


# ── Revue adversariale du 2026-10-06 ─────────────────────────────────────────────────

def test_le_reglement_n_a_lieu_qu_une_fois_meme_si_marquer_termine_leve(tmp_path, monkeypatch):
    """`finish` lève APRÈS le règlement « termine » : la branche d'échec ne doit pas régler une
    seconde fois (à coût nul elle rendait tout, et le compteur passait négatif)."""
    from jobs import JobStore
    client, server = _client(monkeypatch, tmp_path)

    def finish_qui_leve(self, *a, **k):
        raise RuntimeError("base verrouillée")

    monkeypatch.setattr(JobStore, "finish", finish_qui_leve)
    job = _lancer(client, server, monkeypatch, _runner(mesurees=1), n_search=6)
    assert job["statut"] == "echec"
    assert _niches(client) == 1, "une niche mesurée, six réservées : une seule décomptée, jamais moins"


def test_en_mode_worker_annuler_un_travail_pas_encore_pris_rend_ses_niches(tmp_path, monkeypatch):
    """Personne ne reprendra ce travail : le serveur règle à l'annulation. En mode thread c'est le
    fil qui le fait (`est_annule` avant le démarrage) — ne jamais régler deux fois."""
    client, server = _client(monkeypatch, tmp_path)
    monkeypatch.setenv("JOBS_MODE", "worker")
    monkeypatch.setitem(server._JOB_RUNNERS, "scout", _runner(mesurees=6))
    jid = client.post("/api/jobs", json={"type": "scout", "n_search": 6}).json()["id"]
    assert _niches(client) == 6
    assert client.post(f"/api/jobs/{jid}/annuler").status_code == 204
    assert _niches(client) == 0


def test_un_deploiement_pendant_un_run_ne_coute_pas_ses_niches_a_l_abonne(tmp_path, monkeypatch):
    """Sur un hébergeur chaque mise en ligne redémarre le service : un run coupé n'a rien livré, et
    la faute n'est pas celle du client. Le coût mesuré avant la coupure, s'il existe, garde la
    réservation (règle des échecs)."""
    from jobs import JobStore
    client, server = _client(monkeypatch, tmp_path)
    monkeypatch.setenv("JOBS_MODE", "worker")            # le serveur empile seulement : rien ne tourne
    jid = client.post("/api/jobs", json={"type": "scout", "n_search": 6}).json()["id"]
    assert _niches(client) == 6
    monkeypatch.delenv("JOBS_MODE")                       # redémarrage en mode thread
    store = JobStore(server._JOBS_DB)
    job = store.claim_next()
    monkeypatch.setattr(store, "orphelins", lambda depuis_s: [job])
    assert server._recuperer_travaux_interrompus(store) == 1
    assert store.get(jid).statut == "echec"
    assert _niches(client) == 0


def test_un_orphelin_dont_le_cout_est_connu_garde_sa_reservation(tmp_path, monkeypatch):
    from jobs import JobStore
    client, server = _client(monkeypatch, tmp_path)
    monkeypatch.setenv("JOBS_MODE", "worker")
    jid = client.post("/api/jobs", json={"type": "scout", "n_search": 6}).json()["id"]
    monkeypatch.delenv("JOBS_MODE")
    store = JobStore(server._JOBS_DB)
    job = store.claim_next()
    job = job.model_copy(update={"cout": {"usd": 0.05}})
    monkeypatch.setattr(store, "orphelins", lambda depuis_s: [job])
    server._recuperer_travaux_interrompus(store)
    assert _niches(client) == 6
