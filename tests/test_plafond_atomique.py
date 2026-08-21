"""Le plafond mensuel était vérifié AVANT le run et imputé APRÈS.

Entre les deux, il se passe deux à quinze minutes. Une rafale de `POST /api/jobs` passait
donc le contrôle EN ENTIER : dix requêtes envoyées en même temps voyaient toutes le même
compteur, celui d'avant la première. Le plafond ne bridait qu'un client qui attend
sagement la fin de chaque analyse — c'est-à-dire personne d'intéressé à le contourner.

La correction n'est pas de vérifier plus souvent : c'est de RÉSERVER. La place est prise
au moment du contrôle, dans la même transaction, et le coût vient s'inscrire dessus plus
tard. `BEGIN IMMEDIATE` prend le verrou d'écriture AVANT de compter — sans lui, deux
processus lisent le même total puis écrivent tous les deux, et SQLite ne s'y oppose pas.

Même idiome que `JobStore.claim_next`, pour la même raison : c'est un des rares endroits
du dépôt où une course coûte de l'argent réel.
"""
import sys
import threading
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "web"))

from usage import PlafondAtteint, UsageMeter


def _meter(tmp_path, plafond=None):
    return UsageMeter(tmp_path / "usage.db", plafond_analyses=plafond)


def test_la_reservation_compte_immediatement(tmp_path):
    m = _meter(tmp_path, plafond=3)
    m.reserver_analyse("u", "scout")
    assert m.resume("u").n_analyses == 1


def test_au_plafond_la_reservation_est_REFUSEE(tmp_path):
    m = _meter(tmp_path, plafond=2)
    m.reserver_analyse("u", "scout")
    m.reserver_analyse("u", "scout")
    with pytest.raises(PlafondAtteint):
        m.reserver_analyse("u", "scout")


def test_une_rafale_ne_passe_pas_en_entier(tmp_path):
    """LE test. Dix réservations lancées ensemble sur un plafond de 3 : exactement 3
    doivent passer. Avec l'ancien « vérifier puis imputer plus tard », les dix voyaient le
    même compteur et passaient toutes."""
    m = _meter(tmp_path, plafond=3)
    acceptes, refuses = [], []
    verrou = threading.Lock()

    def tenter():
        try:
            UsageMeter(tmp_path / "usage.db", plafond_analyses=3).reserver_analyse("u", "scout")
            with verrou:
                acceptes.append(1)
        except PlafondAtteint:
            with verrou:
                refuses.append(1)

    fils = [threading.Thread(target=tenter) for _ in range(10)]
    for f in fils:
        f.start()
    for f in fils:
        f.join()

    assert len(acceptes) == 3, f"{len(acceptes)} acceptés pour un plafond de 3"
    assert len(refuses) == 7
    assert m.resume("u").n_analyses == 3


def test_sans_plafond_configure_rien_n_est_refuse(tmp_path):
    """Défaut historique : pas de plafond = illimité, mais l'usage reste journalisé."""
    m = _meter(tmp_path, plafond=None)
    for _ in range(5):
        m.reserver_analyse("u", "scout")
    assert m.resume("u").n_analyses == 5


def test_le_plafond_est_PAR_utilisateur(tmp_path):
    m = _meter(tmp_path, plafond=1)
    m.reserver_analyse("alice", "scout")
    m.reserver_analyse("bob", "scout")          # ne doit pas lever
    with pytest.raises(PlafondAtteint):
        m.reserver_analyse("alice", "scout")


def test_solder_inscrit_le_cout_sans_recompter_l_analyse(tmp_path):
    """La place a déjà été prise à la réservation. La recompter à l'imputation ferait
    consommer DEUX unités de plafond par run."""
    m = _meter(tmp_path, plafond=5)
    rid = m.reserver_analyse("u", "scout")
    m.solder(rid, 0.084)
    r = m.resume("u")
    assert r.n_analyses == 1 and r.cout_usd == pytest.approx(0.084)


def test_un_run_en_echec_garde_sa_place_prise_et_son_cout(tmp_path):
    """L'argent parti reste compté (§5.29), et l'analyse a bien eu lieu : un échec ne
    rembourse pas une unité de plafond, sinon un run qui échoue en boucle serait gratuit."""
    m = _meter(tmp_path, plafond=5)
    rid = m.reserver_analyse("u", "scout")
    m.solder(rid, 0.031)                        # 3 SERP payées avant la panne
    r = m.resume("u")
    assert r.n_analyses == 1 and r.cout_usd == pytest.approx(0.031)


# ── Bout en bout ───────────────────────────────────────────────────────────────

def test_une_rafale_d_API_ne_depasse_pas_le_plafond(tmp_path, monkeypatch):
    from tests.test_server_jobs import _client_with_isolated_dbs
    client, server = _client_with_isolated_dbs(monkeypatch, tmp_path)
    monkeypatch.setenv("PLAFOND_ANALYSES_MENSUEL", "2")
    monkeypatch.setattr(server, "run_scout",
                        lambda seed=None, progress=None, cost=None, **kw: [])

    codes = [client.post("/api/jobs", json={"type": "scout", "seed": f"s{i}"}).status_code
             for i in range(6)]
    assert codes.count(202) == 2, f"codes obtenus : {codes}"
    assert codes.count(429) == 4


def test_le_refus_de_plafond_ne_cree_aucun_job(tmp_path, monkeypatch):
    """Un job créé puis refusé encombrerait la file et fausserait « Mes analyses »."""
    from tests.test_server_jobs import _client_with_isolated_dbs
    from jobs import JobStore
    client, server = _client_with_isolated_dbs(monkeypatch, tmp_path)
    monkeypatch.setenv("PLAFOND_ANALYSES_MENSUEL", "1")
    monkeypatch.setattr(server, "run_scout",
                        lambda seed=None, progress=None, cost=None, **kw: [])

    client.post("/api/jobs", json={"type": "scout", "seed": "a"})
    client.post("/api/jobs", json={"type": "scout", "seed": "b"})
    uid = client.get("/api/auth/moi").json()["user_id"]
    assert len(JobStore(server._JOBS_DB).list_jobs(user_id=uid, limit=20)) == 1
