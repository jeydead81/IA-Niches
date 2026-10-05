"""Les 7 mots-clés KDP d'un trio FICTION, comme en non-fiction et en low-content.

Demande de Baptiste (2026-10-05) : « et les mots clés ? (idem que non fiction) ». Hors périmètre de
la première version du verdict fiction (le bouton n'existait pas, `/api/kdp-keywords` refusait
`type: fiction` en 400) ; il l'ouvre. Même endpoint, mêmes gardes que les deux autres : plafond,
débit à la pièce, coût soldé dans un `finally`, 502 neutre.

Ce que le roman change : le générateur lit le TRIO (sous-genre, tropes, décor), le TITRE prévu par
l'analyse (« n'en reprends pas les mots : Amazon les indexe déjà ») et le PITCH (l'ambiance, sans en
recopier les phrases). Le titre et le pitch viennent du champ `analyse` que la page renvoie avec la
carte ; sans analyse, la génération reste possible, sans eux.

FIXTURES INVENTÉES : aucune réponse réelle de ce générateur sur un roman n'a été capturée.
"""
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "web"))

from jobs import JobStore  # noqa: E402
from models import FictionNiche, NicheCandidate  # noqa: E402
from tests.test_fiction_verdict import _livre, _payload, _rapport  # noqa: E402

TITRE = "La Librairie des Marées"
SOUS_TITRE = "Ils se détestent. La tempête les enferme."
PITCH = ("Léa reprend la librairie de sa grand-mère dans un port breton. Un rival veut racheter "
         "les murs avant l'hiver.")

CANDIDATS = ["romance ennemis amants petite ville", "librairie des marées",       # dans le titre
             "feel good deuil lumineux", "roman huis clos tempête bretagne",
             "amitié entre générations roman", "reconstruction après un deuil roman",
             "histoire de port breton", "lecture cocooning hiver"]


class _Usage:
    input_tokens, output_tokens = 900, 300


class _Bloc:
    type = "tool_use"

    def __init__(self, entree):
        self.input = entree


class _Rep:
    def __init__(self, entree):
        self.content, self.usage, self.stop_reason = [_Bloc(entree)], _Usage(), "tool_use"


class _Anthropic:
    def __init__(self, entree):
        self.entree, self.appels = entree, []
        self.messages = self

    def create(self, **kw):
        self.appels.append(kw)
        return _Rep(self.entree)

    @property
    def prompt(self) -> str:
        return " ".join(m["content"] for a in self.appels for m in a["messages"])


def _corps(**kw) -> dict:
    d = _rapport().model_dump()
    d["autocomplete_score"] = 1.0
    d["analyse"] = {"verdict": "Go", "confiance": 7, "facteur_decisif": "f",
                    "angles": [{"angle": "a", "pourquoi": "p", "risque": "r", "titre": TITRE,
                                "sous_titre": SOUS_TITRE, "pitch": PITCH}]}
    d.update(kw)
    return {"type": "fiction", **d}


@pytest.fixture
def banc(monkeypatch, tmp_path):
    pytest.importorskip("httpx")
    from fastapi.testclient import TestClient
    import server
    from tests.conftest import isoler_bases, ouvrir_session
    isoler_bases(monkeypatch, server, tmp_path)
    faux = _Anthropic({"candidats": CANDIDATS})
    monkeypatch.setattr("kdp_keywords._default_client", lambda: faux)
    monkeypatch.setattr("kdp_keywords._default_sonde", lambda prefixe: ["suggestion"])
    c = TestClient(server.app, raise_server_exceptions=False)
    return c, server, ouvrir_session(c), faux


def _cout(server, uid) -> float:
    from usage import UsageMeter
    return UsageMeter(server._USAGE_DB).resume(uid).cout_usd


# ── Le chemin nominal ───────────────────────────────────────────────────────────

def test_les_mots_cles_d_un_trio_sont_rendus_et_imputes(banc):
    c, server, uid, faux = banc
    r = c.post("/api/kdp-keywords", json=_corps())
    assert r.status_code == 200, r.text
    d = r.json()
    assert 1 <= len(d["emplacements"]) <= 7 and d["confirmes_par_amazon"]
    assert len(faux.appels) == 1 and _cout(server, uid) > 0


def test_le_generateur_lit_le_trio_le_titre_et_le_pitch(banc):
    c, server, uid, faux = banc
    c.post("/api/kdp-keywords", json=_corps())
    p = faux.prompt
    assert "romance contemporaine" in p and "enemies to lovers" in p and "small town" in p
    assert TITRE in p and PITCH in p
    assert "n'en reprends pas les mots" in p.lower() or "n’en reprends pas les mots" in p.lower()


def test_un_mot_cle_deja_dans_le_titre_est_rejete_avec_son_motif(banc):
    c, *_ = banc
    d = c.post("/api/kdp-keywords", json=_corps()).json()
    assert "librairie des marées" not in d["emplacements"]
    assert any(r["mot"] == "librairie des marées" and "titre" in r["motif"] for r in d["rejetes"])


def test_sans_analyse_la_generation_reste_possible(banc):
    c, server, uid, faux = banc
    corps = _corps()
    corps.pop("analyse")
    assert c.post("/api/kdp-keywords", json=corps).status_code == 200
    assert TITRE not in faux.prompt


def test_une_analyse_illisible_est_ignoree_sans_lever(banc):
    c, *_ = banc
    for illisible in ("texte", 7, [], {"angles": "x"}, {"angles": [3]}, {"angles": [{}]}):
        assert c.post("/api/kdp-keywords", json=_corps(analyse=illisible)).status_code == 200


def test_le_titre_et_le_pitch_envoyes_au_modele_sont_bornes(banc):
    """La page est le client : un pitch de 50 000 caractères ne doit pas grossir l'appel facturé."""
    c, server, uid, faux = banc
    enorme = {"angles": [{"titre": "T" * 5000, "pitch": "mot " * 20000}]}
    assert c.post("/api/kdp-keywords", json=_corps(analyse=enorme)).status_code == 200
    assert len(faux.prompt) < 6000


def test_un_rapport_invalide_est_une_400(banc):
    c, *_ = banc
    assert c.post("/api/kdp-keywords", json={"type": "fiction", "niche": "pas un objet"}
                  ).status_code == 400


def test_un_type_inconnu_reste_une_400(banc):
    c, *_ = banc
    assert c.post("/api/kdp-keywords", json={"type": "bidon"}).status_code == 400


# ── Les gardes, comme les autres chemins payants ────────────────────────────────

def test_le_plafond_couvre_les_mots_cles_fiction(monkeypatch, tmp_path):
    pytest.importorskip("httpx")
    from fastapi.testclient import TestClient
    import server
    from tests.conftest import isoler_bases, ouvrir_session
    isoler_bases(monkeypatch, server, tmp_path)
    monkeypatch.setenv("PLAFOND_ANALYSES_MENSUEL", "0")
    faux = _Anthropic({"candidats": CANDIDATS})
    monkeypatch.setattr("kdp_keywords._default_client", lambda: faux)
    c = TestClient(server.app, raise_server_exceptions=False)
    ouvrir_session(c)
    assert c.post("/api/kdp-keywords", json=_corps()).status_code == 429
    assert faux.appels == []


def test_le_debit_a_la_piece_couvre_les_mots_cles_fiction(banc, monkeypatch):
    c, *_ = banc
    monkeypatch.setenv("DEBIT_APPELS_MAX", "1")
    assert c.post("/api/kdp-keywords", json=_corps()).status_code == 200
    assert c.post("/api/kdp-keywords", json=_corps()).status_code == 429


def test_une_reponse_du_modele_en_erreur_est_une_502_et_le_cout_est_solde(banc, monkeypatch):
    c, server, uid, _ = banc

    class _Casse:
        def __init__(self):
            self.messages = self

        def create(self, **kw):
            r = _Rep(None)
            r.content = None            # lecture qui LÈVE après l'appel payé
            return r

    monkeypatch.setattr("kdp_keywords._default_client", lambda: _Casse())
    r = c.post("/api/kdp-keywords", json=_corps())
    assert r.status_code == 502 and _cout(server, uid) > 0


# ── Conservation dans le travail ────────────────────────────────────────────────

def _job(server, uid, entrees):
    s = JobStore(server._JOBS_DB)
    jid = s.create("fiction", {}, user_id=uid)
    s.finish(jid, entrees, {})
    return jid


def _entree(niche: FictionNiche) -> dict:
    d = _rapport(niche=niche).model_dump()
    return d


def test_les_mots_cles_sont_ranges_sous_le_bon_trio_quand_deux_partagent_la_requete(banc):
    c, server, uid, _ = banc
    a = FictionNiche(sous_genre="romance_contemporaine", tropes=["enemies_to_lovers"],
                     decor="small_town", query="romance ennemis to lovers petite ville")
    b = FictionNiche(sous_genre="romance_contemporaine", tropes=["grumpy_sunshine"],
                     decor="small_town", query="romance ennemis to lovers petite ville")
    assert a.query == b.query and a.cle != b.cle
    jid = _job(server, uid, [_entree(a), _entree(b)])
    corps = _corps(niche=b.model_dump())
    r = c.post("/api/kdp-keywords", params={"job": jid, "cle": b.cle}, json=corps)
    assert r.status_code == 200 and r.json()["_conserve"] is True
    relu = c.get(f"/api/jobs/{jid}").json()["resultat"]
    assert "mots_cles" not in relu[0] and relu[1]["mots_cles"]["emplacements"]
    assert "_cout" not in relu[1]["mots_cles"]


def test_sans_job_le_comportement_sans_etat_est_inchange(banc):
    c, server, uid, _ = banc
    r = c.post("/api/kdp-keywords", json=_corps())
    assert r.status_code == 200 and "_conserve" not in r.json()


def test_le_travail_d_un_autre_compte_n_est_pas_annote(banc):
    c, server, uid, _ = banc
    n = _rapport().niche
    jid = _job(server, "autre-compte", [_entree(n)])
    r = c.post("/api/kdp-keywords", params={"job": jid, "cle": n.cle}, json=_corps())
    assert r.status_code == 200 and r.json()["_conserve"] is False


# ── Le candidat construit pour le générateur ────────────────────────────────────

def test_le_candidat_fiction_porte_le_trio_en_clair():
    from kdp_keywords import candidat_fiction
    cand, contexte = candidat_fiction(_rapport(), pitch=PITCH)
    assert isinstance(cand, NicheCandidate)
    assert cand.requete_amazon == "romance ennemis to lovers petite ville bretonne"
    assert "_" not in cand.niche and "_" not in contexte, "les clés de taxonomie se lisent en français"
    assert "romance contemporaine" in contexte and PITCH in contexte
