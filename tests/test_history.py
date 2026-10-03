"""test_history.py — historique des niches et delta entre deux passages.

C'est la seule fonction du produit qui répond à « est-ce que ça bouge ? ». Sans elle,
chaque run est un cliché isolé : impossible de voir qu'une niche se referme."""
import time

from history import NicheHistory, cle_niche


def test_la_cle_de_niche_est_stable_malgre_la_casse_et_les_accents():
    """Si « Cosy Mystery » et « cosy mystery » produisent deux clés, on ne comparera
    jamais deux passages sur la même niche — la fonction entière serait inopérante."""
    assert cle_niche("Cosy Mystery  Breton") == cle_niche("cosy mystery breton")
    assert cle_niche("Stoïcisme") == cle_niche("stoicisme")


def test_un_seul_passage_ne_produit_AUCUNE_tendance(tmp_path):
    """Un point unique n'est pas une tendance. Inventer une évolution à partir d'une seule
    mesure serait exactement le travers qu'on combat partout ailleurs (§10)."""
    h = NicheHistory(tmp_path / "h.db")
    h.enregistrer("u1", "scout", "stoicisme", {"bsr_best": 194})
    assert h.delta("local", "stoicisme") is None


def test_le_delta_compare_les_DEUX_derniers_passages(tmp_path):
    t = [1000.0]
    h = NicheHistory(tmp_path / "h.db", now=lambda: t[0])
    h.enregistrer("local", "fiction", "dark romance mafia", {"saturation_trio": 0.45})
    t[0] += 86400 * 30
    h.enregistrer("local", "fiction", "dark romance mafia", {"saturation_trio": 0.68})
    d = h.delta("local", "dark romance mafia")
    assert d.n_passages == 2
    assert abs(d.variations["saturation_trio"] - 0.23) < 1e-9
    assert d.jours_ecoules == 30


def test_le_delta_dit_ce_que_ca_signifie_pas_seulement_le_chiffre(tmp_path):
    """« +0,23 » ne dit rien à un auteur. « La niche s'est densifiée » le fait agir."""
    t = [1000.0]
    h = NicheHistory(tmp_path / "h.db", now=lambda: t[0])
    h.enregistrer("local", "fiction", "n", {"saturation_trio": 0.30})
    t[0] += 86400 * 10
    h.enregistrer("local", "fiction", "n", {"saturation_trio": 0.70})
    assert "densifi" in h.delta("local", "n").lecture.lower()


def test_un_bsr_qui_MONTE_est_une_MAUVAISE_nouvelle(tmp_path):
    """Piège d'interprétation : sur le BSR, plus le nombre est grand, MOINS ça se vend.
    Une lecture naïve du signe dirait « en hausse » pour un marché qui s'effondre."""
    t = [1000.0]
    h = NicheHistory(tmp_path / "h.db", now=lambda: t[0])
    h.enregistrer("local", "scout", "n", {"bsr_best": 2000})
    t[0] += 86400 * 10
    h.enregistrer("local", "scout", "n", {"bsr_best": 90000})
    lec = h.delta("local", "n").lecture.lower()
    assert "moins" in lec or "recul" in lec or "baisse" in lec


def test_les_metriques_absentes_d_un_passage_ne_sont_pas_comparees(tmp_path):
    """Comparer une métrique présente d'un seul côté fabriquerait une variation fictive."""
    t = [1000.0]
    h = NicheHistory(tmp_path / "h.db", now=lambda: t[0])
    h.enregistrer("local", "fiction", "n", {"depth_score": 0.5})
    t[0] += 86400
    h.enregistrer("local", "fiction", "n", {"depth_score": 0.6, "saturation_trio": 0.2})
    assert set(h.delta("local", "n").variations) == {"depth_score"}


def test_l_historique_est_cloisonne_par_utilisateur(tmp_path):
    h = NicheHistory(tmp_path / "h.db")
    h.enregistrer("alice", "scout", "n", {"bsr_best": 100})
    h.enregistrer("bob", "scout", "n", {"bsr_best": 200})
    assert len(h.historique("alice", "n")) == 1


def _client_hist(monkeypatch, tmp_path, nom="h.db"):
    """Magasins en tmp_path — jamais les fichiers réels du dépôt en test."""
    import sys
    from pathlib import Path as P
    sys.path.insert(0, str(P(__file__).resolve().parent.parent / "web"))
    import pytest
    pytest.importorskip("httpx")
    from fastapi.testclient import TestClient
    import server
    from tests.conftest import isoler_bases, ouvrir_session
    isoler_bases(monkeypatch, server, tmp_path)
    monkeypatch.setattr(server, "_HISTORY_DB", tmp_path / nom)   # nom propre au test
    client = TestClient(server.app)
    # Les tests d'historique écrivent en base sous ce user_id, puis relisent par l'API.
    server.USER_ID_TEST = ouvrir_session(client)
    return client, server


def test_le_serveur_expose_l_historique_et_sa_lecture(tmp_path, monkeypatch):
    """Sans endpoint, l'historique n'existerait que sur le papier : personne ne va lire
    une base SQLite à la main."""
    client, server = _client_hist(monkeypatch, tmp_path)
    h = NicheHistory(tmp_path / "h.db")
    h.enregistrer(server.USER_ID_TEST, "scout", "stoicisme", {"bsr_best": 194})
    h.enregistrer(server.USER_ID_TEST, "scout", "stoicisme", {"bsr_best": 52000})

    r = client.get("/api/history", params={"niche": "Stoïcisme"})   # casse/accents différents
    assert r.status_code == 200
    d = r.json()
    assert d["delta"] is not None
    assert "moins" in d["delta"]["lecture"].lower()
    assert len(d["passages"]) == 2


def test_une_niche_vue_une_seule_fois_nest_pas_une_erreur(tmp_path, monkeypatch):
    """« Pas encore d'historique » est une réponse, pas un échec : rendre 404 pousserait
    l'interface à afficher une erreur là où il n'y a qu'une absence de recul."""
    client, _ = _client_hist(monkeypatch, tmp_path, "h2.db")
    r = client.get("/api/history", params={"niche": "jamais vue"})
    assert r.status_code == 200 and r.json()["delta"] is None


# ── Le chemin asynchrone doit consigner l'historique lui aussi ──────────────────────

# 10 s et non 3 : un job de test tient en quelques millisecondes, mais sous charge (suite
# complete, machine occupee par ailleurs) le fil du job peut etre servi tard -- un echec
# ponctuel a ete vu ainsi le 2026-10-03, sans cause reproductible en isole. Le delai ne fait
# qu'attendre PLUS longtemps un job qui finit : il ne masque aucun defaut.
def _attendre(client, job_id, timeout=10.0):
    fin = time.time() + timeout
    while time.time() < fin:
        if client.get(f"/api/jobs/{job_id}").json()["statut"] in ("termine", "echec"):
            return
        time.sleep(0.02)
    raise AssertionError(f"job {job_id} non terminé")


def test_un_job_asynchrone_consigne_l_historique(tmp_path, monkeypatch):
    """DÉFAUT TROUVÉ EN REVUE : seuls les endpoints SSE consignaient. Or `POST /api/jobs`
    est le chemin RECOMMANDÉ (il survit à la fermeture de l'onglet, vérifie le plafond et
    impute l'usage) — un utilisateur qui suit la recommandation n'aurait jamais eu de
    delta, et l'historique serait resté vide sans qu'aucun test ne s'en aperçoive."""
    client, server = _client_hist(monkeypatch, tmp_path, "hj.db")
    from models import ScoredNiche
    monkeypatch.setattr(server, "run_scout",
                        lambda **kw: [ScoredNiche(niche="tarot de marseille",
                                                  requete_amazon="tarot",
                                                  categorie="ésotérisme",
                                                  global_score=7.1, bsr_best=900,
                                                  concurrence_mesuree=True)])

    job_id = client.post("/api/jobs", json={"type": "scout", "seed": "tarot"}).json()["id"]
    _attendre(client, job_id)

    h = client.get("/api/history", params={"niche": "Tarot de Marseille"}).json()
    assert h["passages"], "un run asynchrone doit laisser une trace dans l'historique"
    assert h["passages"][0]["metriques"]["global_score"] == 7.1


def test_le_job_consigne_sous_l_utilisateur_du_job(tmp_path, monkeypatch):
    """L'historique est cloisonné par utilisateur (à la différence du cache de scraping,
    mutualisé par conception). Depuis l'authentification, l'identité du job vient de la
    SESSION : un `user_id` glissé dans le corps de la requête doit rester sans effet."""
    client, server = _client_hist(monkeypatch, tmp_path, "hu.db")
    from models import ScoredNiche
    monkeypatch.setattr(server, "run_scout",
                        lambda **kw: [ScoredNiche(niche="tarot", global_score=7.1,
                                                  concurrence_mesuree=True)])

    job_id = client.post("/api/jobs",
                         json={"type": "scout", "user_id": "usurpateur"}).json()["id"]
    _attendre(client, job_id)

    # Consigné sous le compte de la session…
    assert client.get("/api/history", params={"niche": "tarot"}).json()["passages"]
    # …et rien sous l'identité soufflée par le client.
    from history import NicheHistory as _NH
    assert not _NH(tmp_path / "hu.db").historique("usurpateur", "tarot")


def test_une_niche_non_mesuree_n_entre_pas_dans_l_historique(tmp_path, monkeypatch):
    """Consigner une niche dont la SERP a échoué injecterait des zéros non mesurés dans
    la série : le passage suivant, mesuré celui-là, produirait un delta spectaculaire et
    faux (« la niche s'est densifiée ») alors que seule la panne a cessé. Un point qu'on
    sait faux est pire qu'un point manquant."""
    client, server = _client_hist(monkeypatch, tmp_path, "hnm.db")
    from models import ScoredNiche
    monkeypatch.setattr(server, "run_scout", lambda **kw: [
        ScoredNiche(niche="mesuree", global_score=7.0, concurrence_mesuree=True),
        ScoredNiche(niche="non mesuree", global_score=6.1, concurrence_mesuree=False),
    ])

    job_id = client.post("/api/jobs", json={"type": "scout"}).json()["id"]
    _attendre(client, job_id)

    assert client.get("/api/history", params={"niche": "mesuree"}).json()["passages"]
    assert not client.get("/api/history", params={"niche": "non mesuree"}).json()["passages"]
