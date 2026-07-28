"""test_history.py — historique des niches et delta entre deux passages.

C'est la seule fonction du produit qui répond à « est-ce que ça bouge ? ». Sans elle,
chaque run est un cliché isolé : impossible de voir qu'une niche se referme."""
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
    h.enregistrer("local", "scout", "stoicisme", {"bsr_best": 194})
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
    monkeypatch.setattr(server, "_HISTORY_DB", tmp_path / nom)
    monkeypatch.setattr(server, "_JOBS_DB", tmp_path / "j.db")
    monkeypatch.setattr(server, "_USAGE_DB", tmp_path / "u.db")
    return TestClient(server.app), server


def test_le_serveur_expose_l_historique_et_sa_lecture(tmp_path, monkeypatch):
    """Sans endpoint, l'historique n'existerait que sur le papier : personne ne va lire
    une base SQLite à la main."""
    client, _ = _client_hist(monkeypatch, tmp_path)
    h = NicheHistory(tmp_path / "h.db")
    h.enregistrer("local", "scout", "stoicisme", {"bsr_best": 194})
    h.enregistrer("local", "scout", "stoicisme", {"bsr_best": 52000})

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
