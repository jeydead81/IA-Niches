"""L'analyse éditoriale et les mots-clés KDP sont GARDÉS dans le travail qui les a vus naître.

Signalé par Baptiste devant l'écran (2026-10-03) : « attention, l'analyse n'est pas gardée en
mémoire ». C'était exact. `/api/verdict` et `/api/kdp-keywords` sont des appels payants
(~0,028 $ et ~0,006 $) et SANS ÉTAT : le résultat n'existait que dans la page. Rouvrir
l'analyse depuis « Mes analyses », ou simplement recharger, le faisait disparaître — et le
bouton « Analyser cette niche » proposait de le repayer.

Ce que ce fichier tient :
1. le résultat est écrit dans `jobs.db`, dans la niche concernée, par le SERVEUR (jamais par
   le client : ce que la page poserait elle-même serait une écriture non vérifiée) ;
2. il ne s'écrit que dans un travail qui APPARTIENT à la session (le `user_id` vient du
   cookie, règle 4) ;
3. un échec d'écriture ne fait pas échouer la réponse : elle a été payée ;
4. sans `job`, le comportement d'origine (sans état) est strictement inchangé.
"""
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "web"))

from jobs import JobStore  # noqa: E402
from models import NicheVerdict  # noqa: E402

_NICHE_NF = {"niche": "tarot", "requete_amazon": "tarot", "categorie": "éso"}
_NICHE_LC = {"niche": {"niche": "registre du personnel",
                       "requete_amazon": "registre du personnel obligatoire",
                       "rationale": "r", "categorie": "pro",
                       "format_cle": "registres_reglementaires", "theme": "personnel",
                       "public": "professionnel"},
             "global_score": 7.1, "concurrence_mesuree": True}
_VERDICT = NicheVerdict(verdict="Go prudent", confiance=7, facteur_decisif="demande prouvée")


# ── JobStore.annoter_resultat ────────────────────────────────────────────────────

def _store(tmp_path):
    return JobStore(tmp_path / "jobs.db")


def _job_termine(store, resultat, user_id="u1"):
    jid = store.create("scout", {}, user_id=user_id)
    store.finish(jid, resultat, {})
    return jid


def test_annoter_ecrit_le_champ_dans_la_niche_designee_et_rien_d_autre(tmp_path):
    s = _store(tmp_path)
    jid = _job_termine(s, [{"niche": "tarot", "global_score": 7.0},
                           {"niche": "runes", "global_score": 6.0}])
    assert s.annoter_resultat(jid, "u1", "tarot", "verdict", {"verdict": "Go"}) is True
    job = s.get(jid)
    assert job.resultat[0]["verdict"] == {"verdict": "Go"}
    assert "verdict" not in job.resultat[1]
    assert job.resultat[0]["global_score"] == 7.0 and job.statut == "termine"


def test_annoter_retrouve_une_niche_low_content_par_sa_requete(tmp_path):
    s = _store(tmp_path)
    jid = _job_termine(s, [{"niche": {"niche": "Registre", "requete_amazon": "registre obligatoire"}}])
    assert s.annoter_resultat(jid, "u1", "registre obligatoire", "verdict", {"verdict": "Go"})
    assert s.get(jid).resultat[0]["verdict"] == {"verdict": "Go"}


def test_annoter_refuse_le_travail_d_un_autre_utilisateur(tmp_path):
    """Règle 4 : connaître un identifiant ne donne aucun droit d'écriture."""
    s = _store(tmp_path)
    jid = _job_termine(s, [{"niche": "tarot"}], user_id="u1")
    assert s.annoter_resultat(jid, "intrus", "tarot", "verdict", {"verdict": "Go"}) is False
    assert "verdict" not in s.get(jid).resultat[0]


@pytest.mark.parametrize("cas", ["job_inconnu", "niche_inconnue", "pas_de_resultat", "resultat_dict"])
def test_annoter_rend_False_sans_lever_quand_la_cible_n_existe_pas(tmp_path, cas):
    s = _store(tmp_path)
    if cas == "job_inconnu":
        assert s.annoter_resultat("nope", "u1", "tarot", "verdict", {}) is False
        return
    jid = s.create("scout", {}, user_id="u1")
    if cas == "niche_inconnue":
        s.finish(jid, [{"niche": "runes"}], {})
    elif cas == "resultat_dict":
        s.finish(jid, {"autre": 1}, {})
    assert s.annoter_resultat(jid, "u1", "tarot", "verdict", {}) is False


def test_annoter_ne_laisse_ecrire_que_des_champs_connus(tmp_path):
    """Le client choisit la CLÉ de la niche, jamais le nom du champ écrit."""
    s = _store(tmp_path)
    jid = _job_termine(s, [{"niche": "tarot", "global_score": 7.0}])
    assert s.annoter_resultat(jid, "u1", "tarot", "global_score", 10.0) is False
    assert s.get(jid).resultat[0]["global_score"] == 7.0


# ── Les endpoints ────────────────────────────────────────────────────────────────

def _client(monkeypatch, tmp_path):
    pytest.importorskip("httpx")
    from fastapi.testclient import TestClient
    import server
    from tests.conftest import isoler_bases, ouvrir_session
    isoler_bases(monkeypatch, server, tmp_path)
    monkeypatch.setattr(server, "generate_verdict", lambda scored, on_usage=None: _VERDICT)
    monkeypatch.setattr(server, "generate_lowcontent_verdict",
                        lambda scored, on_usage=None: _VERDICT)
    from models import MotsClesKDP
    monkeypatch.setattr(server, "generer_mots_cles",
                        lambda *a, **k: MotsClesKDP(emplacements=["tarot débutant"]))
    c = TestClient(server.app, raise_server_exceptions=False)
    uid = ouvrir_session(c)
    return c, server, uid


def _job(server, uid, resultat):
    s = JobStore(server._JOBS_DB)
    jid = s.create("scout", {}, user_id=uid)
    s.finish(jid, resultat, {})
    return jid


def test_le_verdict_est_conserve_dans_le_travail(monkeypatch, tmp_path):
    c, server, uid = _client(monkeypatch, tmp_path)
    jid = _job(server, uid, [_NICHE_NF])
    r = c.post(f"/api/verdict?job={jid}&cle=tarot", json=_NICHE_NF)
    assert r.status_code == 200 and r.json()["verdict"] == "Go prudent"
    relu = c.get(f"/api/jobs/{jid}").json()["resultat"][0]
    assert relu["verdict"]["verdict"] == "Go prudent" and relu["verdict"]["confiance"] == 7
    assert "_cout" not in relu["verdict"], "le coût n'a rien à faire dans le résultat rouvert"


def test_le_verdict_low_content_est_conserve_par_sa_requete(monkeypatch, tmp_path):
    c, server, uid = _client(monkeypatch, tmp_path)
    jid = _job(server, uid, [_NICHE_LC])
    r = c.post("/api/verdict", params={"job": jid, "cle": "registre du personnel obligatoire"},
               json={"type": "lowcontent", **_NICHE_LC})
    assert r.status_code == 200
    assert c.get(f"/api/jobs/{jid}").json()["resultat"][0]["verdict"]["verdict"] == "Go prudent"


def test_les_mots_cles_sont_conserves_dans_le_travail(monkeypatch, tmp_path):
    c, server, uid = _client(monkeypatch, tmp_path)
    jid = _job(server, uid, [_NICHE_NF])
    r = c.post(f"/api/kdp-keywords?job={jid}&cle=tarot", json=_NICHE_NF)
    assert r.status_code == 200
    relu = c.get(f"/api/jobs/{jid}").json()["resultat"][0]
    assert relu["mots_cles"]["emplacements"] == ["tarot débutant"]
    assert "_cout" not in relu["mots_cles"]


def test_sans_job_le_comportement_sans_etat_est_inchange(monkeypatch, tmp_path):
    c, server, uid = _client(monkeypatch, tmp_path)
    jid = _job(server, uid, [_NICHE_NF])
    assert c.post("/api/verdict", json=_NICHE_NF).status_code == 200
    assert "verdict" not in c.get(f"/api/jobs/{jid}").json()["resultat"][0]


def test_le_travail_d_un_autre_compte_n_est_jamais_ecrit(monkeypatch, tmp_path):
    """Règle 4 : le `user_id` vient du cookie. L'intrus obtient SON verdict (il le paie), mais
    le travail d'autrui reste intact."""
    from fastapi.testclient import TestClient
    from tests.conftest import ouvrir_session
    c, server, uid = _client(monkeypatch, tmp_path)
    jid = _job(server, uid, [_NICHE_NF])
    intrus = TestClient(server.app, raise_server_exceptions=False)
    monkeypatch.setenv("INSCRIPTIONS_OUVERTES", "1")
    ouvrir_session(intrus, "intrus@example.com")
    r = intrus.post(f"/api/verdict?job={jid}&cle=tarot", json=_NICHE_NF)
    assert r.status_code == 200
    assert "verdict" not in c.get(f"/api/jobs/{jid}").json()["resultat"][0]


def test_un_echec_d_ecriture_ne_fait_pas_echouer_la_reponse_payee(monkeypatch, tmp_path):
    """Le verdict a été facturé dès la réponse du modèle : le perdre parce qu'une écriture a
    échoué serait pire que de ne pas l'avoir gardé."""
    c, server, uid = _client(monkeypatch, tmp_path)
    jid = _job(server, uid, [_NICHE_NF])

    def boom(*a, **k):
        raise RuntimeError("disque plein")
    monkeypatch.setattr(JobStore, "annoter_resultat", boom)
    r = c.post(f"/api/verdict?job={jid}&cle=tarot", json=_NICHE_NF)
    assert r.status_code == 200 and r.json()["verdict"] == "Go prudent"
    assert r.json()["_conserve"] is False


def test_la_reponse_dit_si_le_resultat_a_ete_conserve(monkeypatch, tmp_path):
    c, server, uid = _client(monkeypatch, tmp_path)
    jid = _job(server, uid, [_NICHE_NF])
    assert c.post(f"/api/verdict?job={jid}&cle=tarot", json=_NICHE_NF).json()["_conserve"] is True
    assert c.post(f"/api/verdict?job={jid}&cle=inconnue", json=_NICHE_NF).json()["_conserve"] is False
    assert "_conserve" not in c.post("/api/verdict", json=_NICHE_NF).json()


def test_un_travail_rouvert_rend_le_verdict_sans_rien_repayer(monkeypatch, tmp_path):
    """Le scénario de Baptiste de bout en bout : analyser, puis rouvrir plus tard."""
    c, server, uid = _client(monkeypatch, tmp_path)
    jid = _job(server, uid, [_NICHE_NF])
    c.post(f"/api/verdict?job={jid}&cle=tarot", json=_NICHE_NF)
    from usage import UsageMeter
    avant = UsageMeter(server._USAGE_DB).resume(uid).cout_usd
    liste = c.get("/api/jobs").json()
    rouvert = next(j for j in liste if j["id"] == jid)["resultat"][0]
    assert rouvert["verdict"]["verdict"] == "Go prudent"
    assert UsageMeter(server._USAGE_DB).resume(uid).cout_usd == avant


# ── Mots-clés KDP pour un rayon low-content (Baptiste, 2026-10-03) ───────────────────────────
# Le dossier PDF les portait déjà ; la page d'analyse low-content n'offrait que le verdict.
# `/api/kdp-keywords` ne validait que la forme non-fiction : le bouton aurait rendu une 400.

def test_les_mots_cles_low_content_sont_generes_depuis_la_niche_et_conserves(monkeypatch, tmp_path):
    c, server, uid = _client(monkeypatch, tmp_path)
    recu = {}

    def fabrique(entree, titre="", on_usage=None, **k):
        from models import MotsClesKDP
        recu["entree"], recu["titre"] = entree, titre
        return MotsClesKDP(emplacements=["registre du personnel pdf"])
    monkeypatch.setattr(server, "generer_mots_cles", fabrique)
    jid = _job(server, uid, [_NICHE_LC])
    r = c.post("/api/kdp-keywords",
               params={"job": jid, "cle": "registre du personnel obligatoire"},
               json={"type": "lowcontent", **_NICHE_LC})
    assert r.status_code == 200 and r.json()["emplacements"] == ["registre du personnel pdf"]
    # Comme le dossier : c'est la `LowContentNiche` (requête, catégorie, satellites) qui part
    # au générateur, pas le `LowContentScored` entier, qui levait avant l'appel.
    assert recu["entree"].requete_amazon == "registre du personnel obligatoire"
    assert recu["titre"] == "registre du personnel"
    assert c.get(f"/api/jobs/{jid}").json()["resultat"][0]["mots_cles"]["emplacements"] \
        == ["registre du personnel pdf"]


def test_un_type_de_mots_cles_inconnu_rend_400(monkeypatch, tmp_path):
    c, server, uid = _client(monkeypatch, tmp_path)
    assert c.post("/api/kdp-keywords", json={"type": "fiction", **_NICHE_NF}).status_code == 400


def test_sans_type_les_mots_cles_non_fiction_sont_inchanges(monkeypatch, tmp_path):
    c, server, uid = _client(monkeypatch, tmp_path)
    assert c.post("/api/kdp-keywords", json=_NICHE_NF).status_code == 200
