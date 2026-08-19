"""Dix utilisateurs simultanés — sans que le dernier attende une heure.

Trois problèmes distincts, qu'il ne faut pas confondre :

1. DÉBIT. Un worker séquentiel traite un job à la fois : dix analyses fiction à la suite,
   c'est deux heures et demie pour la dernière. Il faut un POOL.

2. ÉQUITÉ. Avec un pool mais une file purement chronologique, un utilisateur qui lance
   cinq analyses occupe cinq créneaux et fait attendre neuf personnes derrière lui. Le
   plafond mensuel ne protège pas de ça : il compte des analyses sur trente jours, pas
   des créneaux à l'instant t.

3. PLAFOND DE CHARGE. En mode thread (le défaut local), le serveur lançait un thread par
   job SANS AUCUNE LIMITE : dix utilisateurs, c'est dix runs DataForSEO simultanés et
   autant de connexions SQLite en écriture. « Ça marche » jusqu'au jour où ça ne marche
   plus, et l'erreur ne dira pas pourquoi.
"""
import sys
import threading
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "web"))

from jobs import JobStore


def _store(tmp_path, now=None) -> JobStore:
    return JobStore(tmp_path / "jobs.db", now=now)


def _drainer(store, user_id, timeout=15.0):
    """Attend que TOUS les travaux soient dans un etat terminal.

    Indispensable, et pas seulement par proprete : un fil bloque sur un creneau reprend la
    main APRES la fin du test, donc APRES que monkeypatch a restaure `server._JOBS_DB` et
    `server.run_scout`. Il ecrirait alors dans la VRAIE base et lancerait le VRAI moteur.
    C'est la meme famille de fuite que les 45 lignes fabriquees dans history.db
    (test_isolation_bases.py), avec en plus une depense reelle a la cle."""
    fin = time.time() + timeout
    etats = []
    while time.time() < fin:
        # `list_jobs` filtre sur user_id, et son defaut est "local" : interroger sans le
        # passer rendait une liste VIDE, donc un `all([])` vrai -- le drain croyait avoir
        # fini alors qu'il n'avait rien regarde. Un test qui verifie une liste vide ne
        # verifie rien.
        etats = [j.statut for j in store.list_jobs(user_id=user_id, limit=50)]
        if etats and all(e in ("termine", "echec") for e in etats):
            return etats
        time.sleep(0.02)
    raise AssertionError(f"travaux encore actifs apres {timeout}s : {etats}")


# ── 2. Équité ──────────────────────────────────────────────────────────────────

def test_un_utilisateur_ne_monopolise_pas_la_file(tmp_path):
    """LE test de ce lot. Alice lance cinq analyses, Bob arrive juste après avec une.
    Une file purement chronologique servirait les cinq d'Alice d'abord ; Bob attendrait
    cinq runs pour un seul. À créneaux égaux, on sert celui qui en a le moins."""
    horloge = [1000.0]
    s = _store(tmp_path, now=lambda: horloge[0])
    for _ in range(5):
        s.create("scout", {}, user_id="alice")
        horloge[0] += 1
    s.create("scout", {}, user_id="bob")

    premier = s.claim_next()               # alice : personne n'a de créneau
    assert premier.user_id == "alice"
    second = s.claim_next()                # alice en occupe 1, bob 0 -> bob passe
    assert second.user_id == "bob"


def test_a_egalite_de_creneaux_le_plus_ancien_passe(tmp_path):
    """L'équité ne remplace pas l'ordre d'arrivée, elle le précède seulement : entre deux
    utilisateurs à égalité, le premier arrivé reste le premier servi."""
    horloge = [1000.0]
    s = _store(tmp_path, now=lambda: horloge[0])
    premier = s.create("scout", {}, user_id="alice")
    horloge[0] += 10
    s.create("scout", {}, user_id="bob")
    assert s.claim_next().id == premier


def test_un_utilisateur_seul_garde_tous_les_creneaux(tmp_path):
    """L'équité ne doit pas brider quand il n'y a personne d'autre : Baptiste seul sur son
    poste doit pouvoir enchaîner ses analyses."""
    s = _store(tmp_path)
    for _ in range(3):
        s.create("scout", {}, user_id="baptiste")
    assert all(s.claim_next() is not None for _ in range(3))


def test_les_travaux_finis_ne_comptent_plus_comme_des_creneaux(tmp_path):
    """Sinon un utilisateur serait pénalisé à vie pour ses analyses passées."""
    horloge = [1000.0]
    s = _store(tmp_path, now=lambda: horloge[0])
    fini = s.create("scout", {}, user_id="alice")
    s.claim_next()
    s.finish(fini, [], {"usd": 0.01})
    s.create("scout", {}, user_id="alice")
    s.create("scout", {}, user_id="bob")
    assert s.claim_next().user_id == "alice"      # son run termine ne compte plus


# ── 1. Débit ───────────────────────────────────────────────────────────────────

def test_le_worker_traite_plusieurs_travaux_de_front(tmp_path, monkeypatch):
    """Sans pool, dix analyses fiction font attendre la dernière deux heures et demie."""
    import worker
    s = _store(tmp_path)
    for _ in range(6):
        s.create("scout", {})

    simultanes, maxi, verrou = [0], [0], threading.Lock()

    def runner_lent(params, progress, cost, user_id):
        with verrou:
            simultanes[0] += 1
            maxi[0] = max(maxi[0], simultanes[0])
        time.sleep(0.15)
        with verrou:
            simultanes[0] -= 1
        return []

    monkeypatch.setattr(worker, "_RUNNERS", {"scout": runner_lent})
    monkeypatch.setattr(worker, "_imputer", lambda *a, **k: None)
    worker.boucle(s, concurrence=3, repos_s=0.01, max_tours=4, journal=lambda _m: None)

    assert maxi[0] >= 2, "les travaux ont été traités un par un"
    assert maxi[0] <= 3, "le pool a dépassé sa concurrence"


def test_la_concurrence_du_worker_est_reglable(monkeypatch):
    import worker
    monkeypatch.setenv("WORKER_CONCURRENCE", "7")
    assert worker.concurrence_configuree() == 7


def test_une_concurrence_illisible_retombe_sur_le_defaut(monkeypatch):
    """Même posture que les autres variables : une saisie fautive ne fait pas planter le
    service, elle retombe sur un défaut sûr."""
    import worker
    monkeypatch.setenv("WORKER_CONCURRENCE", "beaucoup")
    assert worker.concurrence_configuree() == worker.CONCURRENCE_DEFAUT


def test_la_concurrence_ne_descend_jamais_sous_un(monkeypatch):
    import worker
    monkeypatch.setenv("WORKER_CONCURRENCE", "0")
    assert worker.concurrence_configuree() >= 1


# ── 3. Plafond de charge côté serveur ──────────────────────────────────────────

def test_le_serveur_borne_le_nombre_de_runs_simultanes(tmp_path, monkeypatch):
    """En mode thread, le serveur lançait un thread par job sans aucune limite. Dix
    utilisateurs, c'était dix runs DataForSEO simultanés et autant d'écrivains SQLite."""
    from tests.test_server_jobs import _client_with_isolated_dbs
    from jobs import JobStore as JS

    client, server = _client_with_isolated_dbs(monkeypatch, tmp_path)
    monkeypatch.setenv("RUNS_SIMULTANES_MAX", "2")

    simultanes, maxi, verrou = [0], [0], threading.Lock()

    def run_lent(seed=None, progress=None, cost=None, **kw):
        with verrou:
            simultanes[0] += 1
            maxi[0] = max(maxi[0], simultanes[0])
        time.sleep(0.25)
        with verrou:
            simultanes[0] -= 1
        return []

    monkeypatch.setattr(server, "run_scout", run_lent)
    for i in range(5):
        assert client.post("/api/jobs",
                           json={"type": "scout", "seed": f"s{i}"}).status_code == 202

    uid = client.get("/api/auth/moi").json()["user_id"]
    etats = _drainer(JS(server._JOBS_DB), uid)
    assert maxi[0] <= 2, f"{maxi[0]} runs simultanés pour une limite de 2"
    assert len(etats) == 5 and all(e == "termine" for e in etats)


def test_un_job_en_attente_de_creneau_reste_en_attente(tmp_path, monkeypatch):
    """Il ne doit pas être marqué « en cours » avant d'avoir un créneau : l'utilisateur
    verrait une analyse démarrée qui ne progresse pas, et ne saurait pas si elle est
    bloquée ou lente."""
    from tests.test_server_jobs import _client_with_isolated_dbs
    from jobs import JobStore as JS

    client, server = _client_with_isolated_dbs(monkeypatch, tmp_path)
    monkeypatch.setenv("RUNS_SIMULTANES_MAX", "1")
    monkeypatch.setattr(server, "run_scout",
                        lambda seed=None, progress=None, cost=None, **kw: time.sleep(0.4) or [])

    client.post("/api/jobs", json={"type": "scout", "seed": "a"})
    deuxieme = client.post("/api/jobs", json={"type": "scout", "seed": "b"}).json()["id"]
    time.sleep(0.15)
    assert JS(server._JOBS_DB).get(deuxieme).statut == "en_attente"
    # Draine AVANT de sortir : sans ca le fil du second travail reprendrait la main apres
    # la fin du test, donc contre la vraie base et le vrai moteur.
    _drainer(JS(server._JOBS_DB), client.get("/api/auth/moi").json()["user_id"])
