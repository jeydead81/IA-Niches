"""Worker séparé — un redéploiement ne perd plus un run, et n'en laisse plus un fantôme.

Aujourd'hui le run vit dans un thread du processus serveur. Le job SURVIT à la fermeture de
l'onglet (c'est déjà acquis), mais pas au redémarrage du serveur : le thread meurt, et le
job reste `en_cours` POUR TOUJOURS. L'utilisateur voit une analyse éternellement en cours,
son unité de plafond est consommée, et rien ne le lui dit.

Deux mécanismes, deux invariants distincts :

- `claim_next` doit être ATOMIQUE. Deux workers (ou un worker et un serveur en mode thread)
  qui prennent le même job le paieraient DEUX FOIS — deux fois les SERP, deux fois les
  tokens. C'est le seul endroit du dépôt où une course coûte de l'argent réel.

- `orphelins` doit distinguer « interrompu » de « long ». Un run fiction dure 10 à 15
  minutes : le déclarer orphelin sur sa seule ancienneté tuerait des runs vivants. C'est
  l'ABSENCE DE PROGRESSION qui fait l'orphelin, pas l'âge — même famille d'invariant que
  « une absence de mesure n'est pas une mesure ».
"""
import sqlite3
import sys
import time
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "web"))

from jobs import JobStore


def _store(tmp_path, now=None) -> JobStore:
    return JobStore(tmp_path / "jobs.db", now=now)


# ── claim_next ─────────────────────────────────────────────────────────────────

def test_claim_next_rend_le_plus_ancien_en_attente(tmp_path):
    horloge = [1000.0]
    s = _store(tmp_path, now=lambda: horloge[0])
    premier = s.create("scout", {"seed": "a"})
    horloge[0] += 10
    s.create("scout", {"seed": "b"})

    job = s.claim_next()
    assert job is not None and job.id == premier
    assert job.statut == "en_cours"


def test_claim_next_rend_None_quand_rien_n_attend(tmp_path):
    s = _store(tmp_path)
    assert s.claim_next() is None


def test_un_job_deja_pris_n_est_pas_repris(tmp_path):
    """LE test du module. Deux workers qui prennent le même job le paieraient DEUX fois :
    deux fois les SERP, deux fois les tokens. C'est le seul endroit du dépôt où une course
    coûte de l'argent réel."""
    s = _store(tmp_path)
    s.create("scout", {"seed": "a"})

    a = s.claim_next()
    b = s.claim_next()
    assert a is not None and b is None


def test_deux_magasins_concurrents_ne_prennent_jamais_le_meme_job(tmp_path):
    """Deux instances distinctes = deux connexions SQLite, comme deux processus worker.
    C'est la configuration réelle, pas le cas d'école."""
    s1 = _store(tmp_path)
    s2 = JobStore(tmp_path / "jobs.db")
    s1.create("scout", {"seed": "a"})

    pris = [s1.claim_next(), s2.claim_next()]
    obtenus = [j.id for j in pris if j is not None]
    assert len(obtenus) == 1


def test_claim_next_marque_la_derniere_activite(tmp_path):
    """Sans ça, un job à peine réclamé serait immédiatement vu comme orphelin par un autre
    worker — il n'a pas encore eu le temps de logger sa première étape."""
    horloge = [5000.0]
    s = _store(tmp_path, now=lambda: horloge[0])
    s.create("scout", {})
    job = s.claim_next()
    assert s.derniere_activite(job.id) == 5000.0


# ── orphelins ──────────────────────────────────────────────────────────────────

def test_un_job_sans_progression_depuis_longtemps_est_orphelin(tmp_path):
    horloge = [1000.0]
    s = _store(tmp_path, now=lambda: horloge[0])
    s.create("scout", {})
    job = s.claim_next()

    horloge[0] += 2000                       # 33 min sans le moindre signe de vie
    assert [o.id for o in s.orphelins(depuis_s=1800)] == [job.id]


def test_un_job_qui_progresse_n_est_JAMAIS_orphelin(tmp_path):
    """Un run fiction dure 10 à 15 minutes. Le déclarer orphelin sur son seul âge tuerait
    des runs vivants — et l'utilisateur perdrait un travail déjà payé."""
    horloge = [1000.0]
    s = _store(tmp_path, now=lambda: horloge[0])
    s.create("fiction", {})
    job = s.claim_next()

    for _ in range(4):                       # une étape toutes les 10 min pendant 40 min
        horloge[0] += 600
        s.append_progress(job.id, "étape")

    assert s.orphelins(depuis_s=1800) == []


def test_un_job_en_attente_n_est_pas_un_orphelin(tmp_path):
    """Il n'a jamais démarré : il attend un worker, c'est le fonctionnement normal."""
    horloge = [1000.0]
    s = _store(tmp_path, now=lambda: horloge[0])
    s.create("scout", {})
    horloge[0] += 100000
    assert s.orphelins(depuis_s=1800) == []


@pytest.mark.parametrize("statut", ["termine", "echec"])
def test_un_job_fini_n_est_pas_un_orphelin(tmp_path, statut):
    horloge = [1000.0]
    s = _store(tmp_path, now=lambda: horloge[0])
    s.create("scout", {})
    job = s.claim_next()
    if statut == "termine":
        s.finish(job.id, [], {"usd": 0.01})
    else:
        s.fail(job.id, "boum", cout={"usd": 0.01})
    horloge[0] += 100000
    assert s.orphelins(depuis_s=1800) == []


# ── Migration ──────────────────────────────────────────────────────────────────

def test_une_base_existante_sans_la_colonne_est_migree(tmp_path):
    """Baptiste a déjà un `jobs.db`. Une colonne ajoutée sans migration ferait planter le
    serveur au démarrage sur SA base, pas sur une base neuve — donc jamais en test."""
    chemin = tmp_path / "vieux.db"
    cx = sqlite3.connect(chemin)
    cx.execute(
        "CREATE TABLE jobs (id TEXT PRIMARY KEY, user_id TEXT NOT NULL, type TEXT NOT NULL,"
        " params TEXT NOT NULL, statut TEXT NOT NULL, progression TEXT NOT NULL,"
        " resultat TEXT, cout TEXT, erreur TEXT, cree_le REAL NOT NULL, fini_le REAL)")
    cx.execute("INSERT INTO jobs VALUES ('vieux','local','scout','{}','en_attente','[]',"
               "NULL,NULL,NULL,1000.0,NULL)")
    cx.commit()
    cx.close()

    s = JobStore(chemin)
    job = s.claim_next()
    assert job is not None and job.id == "vieux"


def test_un_job_migre_sans_activite_connue_retombe_sur_sa_date_de_creation(tmp_path):
    """Les lignes déjà `en_cours` au moment de la migration n'ont pas de `maj_le`. Les
    traiter comme « activité inconnue = maintenant » les rendrait immortelles."""
    chemin = tmp_path / "vieux.db"
    cx = sqlite3.connect(chemin)
    cx.execute(
        "CREATE TABLE jobs (id TEXT PRIMARY KEY, user_id TEXT NOT NULL, type TEXT NOT NULL,"
        " params TEXT NOT NULL, statut TEXT NOT NULL, progression TEXT NOT NULL,"
        " resultat TEXT, cout TEXT, erreur TEXT, cree_le REAL NOT NULL, fini_le REAL)")
    cx.execute("INSERT INTO jobs VALUES ('zombie','local','scout','{}','en_cours','[]',"
               "NULL,NULL,NULL,1000.0,NULL)")
    cx.commit()
    cx.close()

    s = JobStore(chemin, now=lambda: 1000.0 + 5000)
    assert [o.id for o in s.orphelins(depuis_s=1800)] == ["zombie"]


# ── Récupération ───────────────────────────────────────────────────────────────

def test_recuperer_orphelins_les_passe_en_echec_avec_leur_cout(tmp_path):
    """L'argent déjà dépensé reste imputé (§5.29). Le remettre à zéro ferait croire qu'un
    run interrompu était gratuit."""
    import worker
    horloge = [1000.0]
    s = _store(tmp_path, now=lambda: horloge[0])
    s.create("scout", {})
    job = s.claim_next()
    s.append_progress(job.id, "3 SERP payées")
    s.finish_cost_partiel = None
    horloge[0] += 5000

    n = worker.recuperer_orphelins(s, depuis_s=1800)
    assert n == 1
    apres = s.get(job.id)
    assert apres.statut == "echec"
    assert "interrompu" in (apres.erreur or "").lower()
    assert apres.progression == ["3 SERP payées"]      # ce qui a été fait reste lisible


def test_recuperer_orphelins_ne_touche_pas_un_run_vivant(tmp_path):
    import worker
    horloge = [1000.0]
    s = _store(tmp_path, now=lambda: horloge[0])
    s.create("fiction", {})
    job = s.claim_next()
    horloge[0] += 60
    s.append_progress(job.id, "en vie")

    assert worker.recuperer_orphelins(s, depuis_s=1800) == 0
    assert s.get(job.id).statut == "en_cours"


# ── Boucle du worker ───────────────────────────────────────────────────────────

def test_le_worker_execute_un_job_et_le_termine(tmp_path, monkeypatch):
    import worker
    s = _store(tmp_path)
    jid = s.create("scout", {"seed": "tarot"})

    vus = []

    def faux_runner(params, progress, cost, user_id):
        vus.append(params)
        progress("une étape")
        cost.add_llm("claude-sonnet-5", 10, 5)
        return [{"niche": "tarot"}]

    monkeypatch.setattr(worker, "_RUNNERS", {"scout": faux_runner})
    monkeypatch.setattr(worker, "_imputer", lambda *a, **k: None)

    assert worker.executer_un_job(s) is True
    job = s.get(jid)
    assert job.statut == "termine"
    assert job.resultat == [{"niche": "tarot"}]
    assert job.progression == ["une étape"]
    assert vus == [{"seed": "tarot"}]


def test_le_worker_rend_False_quand_la_file_est_vide(tmp_path, monkeypatch):
    import worker
    monkeypatch.setattr(worker, "_RUNNERS", {})
    assert worker.executer_un_job(_store(tmp_path)) is False


def test_un_job_qui_leve_est_marque_en_echec_sans_fuiter_le_detail(tmp_path, monkeypatch):
    """Même garde qu'en ligne (A3) : le message d'exception peut porter les identifiants
    DataForSEO. Le worker écrit dans le MÊME champ que le serveur — le corriger d'un seul
    côté laisserait la fuite entière sur l'autre."""
    import worker
    s = _store(tmp_path)
    jid = s.create("scout", {})

    def runner_qui_leve(params, progress, cost, user_id):
        raise RuntimeError("HTTPError sur https://api.dataforseo.com/?password=SECRET")

    monkeypatch.setattr(worker, "_RUNNERS", {"scout": runner_qui_leve})
    monkeypatch.setattr(worker, "_imputer", lambda *a, **k: None)
    worker.executer_un_job(s)

    job = s.get(jid)
    assert job.statut == "echec"
    assert "SECRET" not in (job.erreur or "")
    assert "ref " in (job.erreur or "")


def test_un_type_de_job_inconnu_ne_bloque_pas_la_file(tmp_path, monkeypatch):
    """Sans ça, un job d'un type retiré du code resterait `en_cours` et le worker
    tournerait dessus indéfiniment."""
    import worker
    s = _store(tmp_path)
    jid = s.create("type_disparu", {})
    monkeypatch.setattr(worker, "_RUNNERS", {"scout": lambda *a: []})
    monkeypatch.setattr(worker, "_imputer", lambda *a, **k: None)

    worker.executer_un_job(s)
    assert s.get(jid).statut == "echec"


def test_le_cout_est_impute_meme_en_cas_d_echec(tmp_path, monkeypatch):
    """L'argent déjà dépensé doit rester compté : c'est l'invariant du serveur, il doit
    valoir aussi dans le worker."""
    import worker
    s = _store(tmp_path)
    s.create("scout", {})
    imputes = []

    def runner(params, progress, cost, user_id):
        cost.add_dataforseo(3, 2)
        raise RuntimeError("boum")

    monkeypatch.setattr(worker, "_RUNNERS", {"scout": runner})
    monkeypatch.setattr(worker, "_imputer",
                        lambda uid, t, usd, n: imputes.append((t, usd, n)))
    worker.executer_un_job(s)
    assert imputes and imputes[0][1] > 0


# ── JOBS_MODE ──────────────────────────────────────────────────────────────────

def test_par_defaut_le_serveur_execute_lui_meme(tmp_path, monkeypatch):
    """Le défaut reste le mode thread : sur le poste de Baptiste, il n'y a pas de second
    processus, et exiger d'en lancer un casserait l'usage local du jour au lendemain."""
    from tests.test_server_jobs import _attendre_job, _client_with_isolated_dbs
    client, server = _client_with_isolated_dbs(monkeypatch, tmp_path)
    monkeypatch.delenv("JOBS_MODE", raising=False)
    monkeypatch.setattr(server, "run_scout",
                        lambda seed=None, progress=None, cost=None, **kw: [])

    jid = client.post("/api/jobs", json={"type": "scout", "seed": "x"}).json()["id"]
    assert _attendre_job(client, jid)["statut"] == "termine"


def test_en_mode_worker_le_serveur_se_contente_d_empiler(tmp_path, monkeypatch):
    """Sans ça, serveur ET worker exécuteraient le même job : deux fois les SERP, deux
    fois les tokens. `claim_next` protège de la course, mais empiler sans exécuter est ce
    qui rend le second processus utile plutôt que redondant."""
    from tests.test_server_jobs import _client_with_isolated_dbs
    from jobs import JobStore
    client, server = _client_with_isolated_dbs(monkeypatch, tmp_path)
    monkeypatch.setenv("JOBS_MODE", "worker")

    def ne_doit_pas_tourner(**kw):
        raise AssertionError("le serveur a exécuté le job en mode worker")

    monkeypatch.setattr(server, "run_scout", ne_doit_pas_tourner)
    r = client.post("/api/jobs", json={"type": "scout", "seed": "x"})
    assert r.status_code == 202

    time.sleep(0.15)                       # laisse le temps à un thread fautif de démarrer
    job = JobStore(server._JOBS_DB).get(r.json()["id"])
    assert job.statut == "en_attente"      # empilé, jamais démarré


def test_en_mode_worker_le_job_reste_reclamable(tmp_path, monkeypatch):
    """Le job empilé doit être exactement celui qu'un worker prendra ensuite."""
    from tests.test_server_jobs import _client_with_isolated_dbs
    from jobs import JobStore
    client, server = _client_with_isolated_dbs(monkeypatch, tmp_path)
    monkeypatch.setenv("JOBS_MODE", "worker")
    jid = client.post("/api/jobs", json={"type": "scout", "seed": "x"}).json()["id"]

    pris = JobStore(server._JOBS_DB).claim_next()
    assert pris is not None and pris.id == jid
