"""Un résultat fiction ENREGISTRÉ avant `mesure_mince` est relu sous la règle d'aujourd'hui.

Revue adverse du 2026-10-05, constat confirmé (quatre fois, par quatre angles) : un travail déjà
dans `jobs.db` — les deux runs réels de Baptiste en sont — porte `demand_matrix = "mort"` ou
`"mur_installe"` bâti sur UN livre, et pas de `n_livres_mesures`. Rouvert, il affichait la
conclusion rouge et un bouton d'analyse que le serveur refusait ensuite : exactement le défaut que
le seuil corrige, resté intact sur ce qui existe déjà.

La relecture se fait à la LECTURE (`GET /api/jobs/{id}`, flux SSE), avec la MÊME fonction que le
moteur (`livres_scorables`) : une seconde définition de « mesuré » côté JS divergerait (§5.32). Le
brut reste dans la base. Elle ne fait que DÉGRADER : un état déjà non concluant n'est pas remonté,
et un résultat qui porte déjà son compteur n'est pas touché.

FIXTURES : construites avec `build_report` puis amputées de `n_livres_mesures`, comme les deux runs
réels de `jobs.db` (qui n'ont jamais eu ce champ).
"""
import copy

import pytest

from fiction_scoring import build_report, relire_resultat_fiction
from fiction_taxonomy import label_rayon
from models import (AutocompleteSignal, EnrichedBook, FictionNiche, FictionShelf,
                    TropeClassification)


def _ancien(n_mesurables, n_total=12, etiquette="mort", rayon="papier"):
    lib = label_rayon(rayon)
    niche = FictionNiche(sous_genre="feel_good", tropes=["deuil_lumineux"], decor="village",
                         rayon=rayon, query="roman feel good village")
    livres = [EnrichedBook(asin=f"A{i}", title=f"T{i}", bsr=3000 + i, bsr_rayon=lib,
                           serp_position=i + 1) for i in range(n_mesurables)]
    livres += [EnrichedBook(asin=f"X{i}", title=f"X{i}", serp_position=50 + i)
               for i in range(n_total - n_mesurables)]
    shelf = FictionShelf(niche=niche, search_param="i=stripbooks", books=livres,
                         asins_demandes=len(livres), n_echecs=0)
    cl = {b.asin: TropeClassification(asin=b.asin, taxonomy_version="fr_v1") for b in livres}
    d = build_report(niche, shelf, cl, AutocompleteSignal(niche_query="q", mesure=True)).model_dump()
    d.pop("n_livres_mesures")
    d["demand_matrix"] = etiquette
    return d


def test_un_ancien_mort_sur_un_livre_devient_mesure_mince():
    r = relire_resultat_fiction([_ancien(1, etiquette="mort")])[0]
    assert r["demand_matrix"] == "mesure_mince" and r["n_livres_mesures"] == 1


def test_un_ancien_mur_installe_sur_deux_livres_devient_mesure_mince():
    r = relire_resultat_fiction([_ancien(2, etiquette="mur_installe")])[0]
    assert r["demand_matrix"] == "mesure_mince" and r["n_livres_mesures"] == 2


def test_un_ancien_resultat_sans_aucun_livre_mesurable_devient_non_mesurable():
    r = relire_resultat_fiction([_ancien(0, 4, etiquette="mort")])[0]
    assert r["demand_matrix"] == "non_mesurable" and r["n_livres_mesures"] == 0


def test_un_ancien_resultat_assez_mesure_garde_son_etiquette_et_recoit_son_compteur():
    r = relire_resultat_fiction([_ancien(4, etiquette="pepite")])[0]
    assert r["demand_matrix"] == "pepite" and r["n_livres_mesures"] == 4


def test_la_relecture_ne_remonte_jamais_un_etat_non_concluant():
    r = relire_resultat_fiction([_ancien(5, etiquette="non_mesurable")])[0]
    assert r["demand_matrix"] == "non_mesurable", "ne fait que dégrader"


def test_un_resultat_qui_porte_deja_son_compteur_n_est_pas_touche():
    d = _ancien(1, etiquette="mort")
    d["n_livres_mesures"] = 7
    assert relire_resultat_fiction([d])[0] is d


def test_l_original_n_est_pas_modifie():
    d = _ancien(1, etiquette="mort")
    avant = copy.deepcopy(d)
    relire_resultat_fiction([d])
    assert d == avant, "le brut reste tel qu'enregistré"


def test_le_seuil_relu_est_celui_de_SEUILS(monkeypatch):
    from fiction_scoring import SEUILS
    monkeypatch.setitem(SEUILS, "livres_mesures_min", 1)
    assert relire_resultat_fiction([_ancien(1, etiquette="mort")])[0]["demand_matrix"] == "mort"


@pytest.mark.parametrize("entree", [None, "texte", 7, {}, {"niche": 3}, {"books": "x"},
                                    {"niche": {"rayon": "inconnu"}, "books": [{"asin": "A"}]}])
def test_une_entree_illisible_est_rendue_telle_quelle_sans_lever(entree):
    sortie = relire_resultat_fiction([entree])
    assert sortie[0] is entree or sortie[0] == entree


def test_ce_qui_n_est_pas_une_liste_est_rendu_tel_quel():
    assert relire_resultat_fiction(None) is None
    assert relire_resultat_fiction({"a": 1}) == {"a": 1}


# ── À la lecture d'un travail ────────────────────────────────────────────────────

def _client(monkeypatch, tmp_path):
    import sys
    from pathlib import Path
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "web"))
    pytest.importorskip("httpx")
    from fastapi.testclient import TestClient
    import server
    from tests.conftest import isoler_bases, ouvrir_session
    isoler_bases(monkeypatch, server, tmp_path)
    c = TestClient(server.app, raise_server_exceptions=False)
    return c, server, ouvrir_session(c)


def _job(server, uid, type_, resultat):
    from jobs import JobStore
    s = JobStore(server._JOBS_DB)
    jid = s.create(type_, {}, user_id=uid)
    s.finish(jid, resultat, {})
    return jid


def test_la_lecture_d_un_travail_fiction_relit_les_anciens_resultats(monkeypatch, tmp_path):
    c, server, uid = _client(monkeypatch, tmp_path)
    jid = _job(server, uid, "fiction", [_ancien(1, etiquette="mort")])
    r = c.get(f"/api/jobs/{jid}").json()["resultat"][0]
    assert r["demand_matrix"] == "mesure_mince" and r["n_livres_mesures"] == 1


def test_le_flux_sse_relit_aussi(monkeypatch, tmp_path):
    c, server, uid = _client(monkeypatch, tmp_path)
    jid = _job(server, uid, "fiction", [_ancien(1, etiquette="mort")])
    corps = c.get(f"/api/jobs/{jid}/stream").text
    assert "mesure_mince" in corps


def test_la_base_garde_le_brut(monkeypatch, tmp_path):
    from jobs import JobStore
    c, server, uid = _client(monkeypatch, tmp_path)
    jid = _job(server, uid, "fiction", [_ancien(1, etiquette="mort")])
    c.get(f"/api/jobs/{jid}")
    assert JobStore(server._JOBS_DB).get(jid).resultat[0]["demand_matrix"] == "mort"


def test_les_autres_types_de_travaux_ne_sont_pas_touches(monkeypatch, tmp_path):
    c, server, uid = _client(monkeypatch, tmp_path)
    jid = _job(server, uid, "scout", [{"niche": "tarot", "demand_matrix": "mort"}])
    assert c.get(f"/api/jobs/{jid}").json()["resultat"] == [{"niche": "tarot",
                                                             "demand_matrix": "mort"}]
