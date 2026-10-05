"""`POST /api/verdict` accepte `type: "fiction"` — mêmes gardes que les deux autres verdicts.

Un SEUL endpoint pour les trois : en créer un second ferait diverger les gardes de plafond, ce
que le commit 5257323 a déjà payé. Ce que ce fichier tient :

1. plafond (`_verifier_plafond`) ET débit à la pièce (`_reserver_appel`) comme les autres ;
2. un rayon NON MESURÉ est refusé en 400 AVANT toute réservation : rien n'est dépensé, rien
   n'est consommé du débit horaire, et surtout aucun « No-Go » ne sort d'une absence de
   mesure (règle 3) ;
3. coût soldé dans un `finally` quand la lecture lève après l'appel payé (§5.29) ;
4. l'analyse est rangée par le SERVEUR dans le travail, sous `analyse` et NON sous `verdict` :
   un résultat fiction porte déjà un `verdict` (le TEXTE du moteur, avec ses réserves — rayon
   incomplet, sous-genre fantôme). L'écraser par l'objet du modèle effacerait ces réserves de
   l'écran ;
5. les champs que l'interface ajoute au rapport (`autocomplete_score`, `analyse`) ne le font
   pas rejeter : `FictionNicheReport` interdit les champs extra, le corps vient d'une page.

FIXTURES INVENTÉES (comme `test_fiction_verdict.py`) : aucune réponse réelle capturée.
"""
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "web"))

from jobs import JobStore  # noqa: E402
from models import FictionNicheReport  # noqa: E402
from tests.test_fiction_verdict import _Client, _payload, _rapport  # noqa: E402

QUERY = "romance ennemis to lovers petite ville bretonne"


def _corps(**kw) -> dict:
    """Ce que la page renvoie : le rapport tel que le job l'a rendu (`model_dump` + la
    propriété ré-injectée à la main par `_run_fiction_job`)."""
    d = _rapport(**kw).model_dump()
    d["autocomplete_score"] = 1.0
    return {"type": "fiction", **d}


def _client(monkeypatch, tmp_path, plafond=None, faux=None):
    pytest.importorskip("httpx")
    from fastapi.testclient import TestClient
    import server
    from tests.conftest import isoler_bases, ouvrir_session
    isoler_bases(monkeypatch, server, tmp_path)
    if plafond is not None:
        monkeypatch.setenv("PLAFOND_ANALYSES_MENSUEL", str(plafond))
    faux = faux or _Client(_payload())
    monkeypatch.setattr("fiction_verdict._default_client", lambda: faux)
    c = TestClient(server.app, raise_server_exceptions=False)
    return c, server, ouvrir_session(c), faux


def _cout(server, uid) -> float:
    from usage import UsageMeter
    return UsageMeter(server._USAGE_DB).resume(uid).cout_usd


def _job(server, uid, resultat):
    s = JobStore(server._JOBS_DB)
    jid = s.create("fiction", {}, user_id=uid)
    s.finish(jid, resultat, {})
    return jid


# ── Le chemin nominal ───────────────────────────────────────────────────────────

def test_un_verdict_fiction_rend_200_avec_ses_comparables_et_impute(monkeypatch, tmp_path):
    c, server, uid, faux = _client(monkeypatch, tmp_path)
    r = c.post("/api/verdict", json=_corps())
    assert r.status_code == 200, r.text
    v = r.json()
    assert v["verdict"] == "Go" and v["confiance"] == 7
    assert [x["asin"] for x in v["comparables"]] == ["B000000001", "B000000002", "B000000003"]
    assert len(faux.appels) == 1
    assert _cout(server, uid) > 0


def test_les_champs_ajoutes_par_la_page_ne_font_pas_rejeter_le_rapport(monkeypatch, tmp_path):
    c, *_ = _client(monkeypatch, tmp_path)
    corps = _corps()
    corps["analyse"] = {"verdict": "Go"}          # déjà rangé dans la carte rouverte
    assert c.post("/api/verdict", json=corps).status_code == 200


def test_un_rapport_invalide_est_une_400_pas_une_500(monkeypatch, tmp_path):
    c, *_ = _client(monkeypatch, tmp_path)
    assert c.post("/api/verdict", json={"type": "fiction", "niche": "pas un objet"}
                  ).status_code == 400


# ── Plafond et débit ────────────────────────────────────────────────────────────

def test_le_plafond_couvre_le_verdict_fiction(monkeypatch, tmp_path):
    c, server, uid, faux = _client(monkeypatch, tmp_path, plafond=0)
    assert c.post("/api/verdict", json=_corps()).status_code == 429
    assert faux.appels == []


def test_le_debit_a_la_piece_couvre_le_verdict_fiction(monkeypatch, tmp_path):
    monkeypatch.setenv("DEBIT_APPELS_MAX", "1")
    c, server, uid, faux = _client(monkeypatch, tmp_path)
    assert c.post("/api/verdict", json=_corps()).status_code == 200
    assert c.post("/api/verdict", json=_corps()).status_code == 429
    assert len(faux.appels) == 1


# ── Un rayon non mesuré ne coûte rien et ne conclut rien ────────────────────────

def test_un_rayon_non_mesure_est_refuse_avant_toute_reservation(monkeypatch, tmp_path):
    c, server, uid, faux = _client(monkeypatch, tmp_path)
    r = c.post("/api/verdict", json=_corps(demand_matrix="non_mesurable"))
    assert r.status_code == 400
    assert "mesur" in r.json()["detail"].lower()
    assert faux.appels == []
    assert _cout(server, uid) == 0
    # le débit horaire n'a pas bougé : un refus ne consomme pas la place d'un appel
    from usage import UsageMeter
    assert UsageMeter(server._USAGE_DB).compter(uid, ("verdict",), 3600) == 0


def test_le_refus_ne_dit_jamais_que_la_niche_est_morte(monkeypatch, tmp_path):
    c, *_ = _client(monkeypatch, tmp_path)
    detail = c.post("/api/verdict", json=_corps(demand_matrix="non_mesurable")).json()["detail"]
    assert "no-go" not in detail.lower() and "morte" not in detail.lower()


# ── Solde après exception ───────────────────────────────────────────────────────

def test_une_lecture_qui_leve_apres_l_appel_solde_le_cout(monkeypatch, tmp_path):
    c, server, uid, faux = _client(monkeypatch, tmp_path,
                                   faux=_Client("texte libre, pas un objet"))
    r = c.post("/api/verdict", json=_corps())
    assert r.status_code == 502
    assert "texte libre" not in r.text                 # rien d'interne ne sort (§2.7)
    assert len(faux.appels) == 1
    assert _cout(server, uid) > 0


# ── Conservation dans le travail ────────────────────────────────────────────────

def test_l_analyse_est_rangee_sous_analyse_et_le_verdict_du_moteur_reste_intact(
        monkeypatch, tmp_path):
    c, server, uid, _ = _client(monkeypatch, tmp_path)
    rapport = _corps()
    entree = {k: v for k, v in rapport.items() if k != "type"}
    jid = _job(server, uid, [entree])
    r = c.post("/api/verdict", params={"job": jid, "cle": QUERY}, json=rapport)
    assert r.status_code == 200 and r.json()["_conserve"] is True
    relu = c.get(f"/api/jobs/{jid}").json()["resultat"][0]
    assert relu["analyse"]["verdict"] == "Go"
    assert relu["analyse"]["comparables"][0]["titre"] == "Ennemis à Saint-Malo"
    assert "_cout" not in relu["analyse"]
    assert isinstance(relu["verdict"], str) and "Saturation du trio" in relu["verdict"], \
        "le texte du moteur (ses réserves) ne doit pas être écrasé par l'objet du modèle"


def test_une_cle_inconnue_ne_conserve_rien_et_le_dit(monkeypatch, tmp_path):
    c, server, uid, _ = _client(monkeypatch, tmp_path)
    rapport = _corps()
    jid = _job(server, uid, [{k: v for k, v in rapport.items() if k != "type"}])
    r = c.post("/api/verdict", params={"job": jid, "cle": "autre requete"}, json=rapport)
    assert r.status_code == 200 and r.json()["_conserve"] is False
    assert "analyse" not in c.get(f"/api/jobs/{jid}").json()["resultat"][0]


def test_une_cle_vide_ne_designe_aucune_niche():
    """Un trio sans requête ne doit pas « correspondre » à une clé vide."""
    assert JobStore._est_la_niche({"niche": {"query": ""}}, "") is False
    assert JobStore._est_la_niche({"niche": {"query": QUERY}}, QUERY) is True


def test_sans_job_le_comportement_sans_etat_est_inchange(monkeypatch, tmp_path):
    c, server, uid, _ = _client(monkeypatch, tmp_path)
    rapport = _corps()
    jid = _job(server, uid, [{k: v for k, v in rapport.items() if k != "type"}])
    r = c.post("/api/verdict", json=rapport)
    assert r.status_code == 200 and "_conserve" not in r.json()
    assert "analyse" not in c.get(f"/api/jobs/{jid}").json()["resultat"][0]


def test_le_travail_d_un_autre_compte_n_est_pas_annote(monkeypatch, tmp_path):
    c, server, uid, _ = _client(monkeypatch, tmp_path)
    rapport = _corps()
    jid = _job(server, "autre-compte", [{k: v for k, v in rapport.items() if k != "type"}])
    r = c.post("/api/verdict", params={"job": jid, "cle": QUERY}, json=rapport)
    assert r.status_code == 200 and r.json()["_conserve"] is False
    assert "analyse" not in JobStore(server._JOBS_DB).get(jid).resultat[0]


# ── Hors périmètre v1 ───────────────────────────────────────────────────────────

def test_les_mots_cles_kdp_ne_sont_pas_offerts_pour_la_fiction(monkeypatch, tmp_path):
    c, *_ = _client(monkeypatch, tmp_path)
    assert c.post("/api/kdp-keywords", json=_corps()).status_code == 400


def test_le_rapport_fiction_est_la_forme_que_le_serveur_valide():
    """Garde-fou de fixture : `_corps()` doit rester constructible par le modèle réel."""
    d = _corps()
    d.pop("type"), d.pop("autocomplete_score")
    FictionNicheReport.model_validate(d)
