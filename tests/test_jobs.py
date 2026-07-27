"""test_jobs.py — JobStore : le magasin de travaux asynchrones (plan SaaS S2).
LE point du module : un run vit dans le magasin, pas dans le thread de la connexion HTTP —
fermer l'onglet ne doit ni tuer le run ni perdre l'argent déjà dépensé."""
from jobs import JobStore


def test_un_job_survit_a_la_deconnexion_du_client(tmp_path):
    """LE point du module : aujourd'hui le run vit dans le thread de la connexion SSE.
    Fermer l'onglet tue un run de 15 min ET perd l'argent déjà dépensé."""
    store = JobStore(tmp_path / "j.db")
    jid = store.create("fiction", {"sous_genre": "cosy_mystery"})
    store.start(jid)
    store.append_progress(jid, "SERP 1/3…")
    # le "client" disparaît ici — le job continue de vivre dans le magasin
    store.finish(jid, resultat=[{"niche": "x"}], cout={"usd": 0.15})
    j = store.get(jid)
    assert j.statut == "termine" and j.resultat and j.cout["usd"] == 0.15
    assert "SERP 1/3…" in j.progression


def test_un_job_en_echec_conserve_son_message_et_son_cout(tmp_path):
    """L'argent dépensé avant l'échec doit rester imputé — sinon on facture dans le vide."""
    store = JobStore(tmp_path / "j.db")
    jid = store.create("fiction", {"sous_genre": "cosy_mystery"})
    store.start(jid)
    store.append_progress(jid, "SERP 1/3…")
    store.fail(jid, "TimeoutError: file DataForSEO saturée", cout={"usd": 0.09})
    j = store.get(jid)
    assert j.statut == "echec" and "Timeout" in j.erreur and j.cout["usd"] == 0.09


def test_liste_par_utilisateur_et_par_recence(tmp_path):
    """user_id dès maintenant (défaut 'local') : brancher l'auth deviendra un remplissage
    de colonne, pas une migration."""
    clock = {"t": 1000.0}
    store = JobStore(tmp_path / "j.db", now=lambda: clock["t"])
    j1 = store.create("fiction", {}, user_id="local")
    clock["t"] += 1
    j2 = store.create("fiction", {}, user_id="local")
    clock["t"] += 1
    j3 = store.create("fiction", {}, user_id="local")
    clock["t"] += 1
    store.create("fiction", {}, user_id="autre")   # autre utilisateur, doit rester invisible
    assert [j.id for j in store.list_jobs(user_id="local", limit=2)] == [j3, j2]
    assert j1 not in [j.id for j in store.list_jobs(user_id="local", limit=2)]


def test_progression_bornee(tmp_path):
    """Un run de 15 min log beaucoup : la progression ne doit pas gonfler la base sans fin."""
    store = JobStore(tmp_path / "j.db", max_progress=5)
    jid = store.create("fiction", {})
    for i in range(20):
        store.append_progress(jid, f"étape {i}")
    j = store.get(jid)
    assert len(j.progression) == 5
    assert j.progression[-1] == "étape 19"
    assert j.progression[0] == "étape 15"


def test_job_par_defaut_est_en_attente_pour_lutilisateur_local(tmp_path):
    """Défaut prudent : user_id='local' et statut='en_attente' tant que start() n'a pas
    été appelé — un job créé mais pas encore pris en charge par le worker doit rester
    distinguable d'un job en cours."""
    store = JobStore(tmp_path / "j.db")
    jid = store.create("scout", {"seed": "tarot"})
    j = store.get(jid)
    assert j.user_id == "local" and j.statut == "en_attente" and j.progression == []


def test_get_job_absent_rend_none(tmp_path):
    store = JobStore(tmp_path / "j.db")
    assert store.get("id-inconnu") is None
