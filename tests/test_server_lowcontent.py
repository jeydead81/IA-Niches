"""Le scout low-content passe par le MÊME chemin que les deux autres : POST /api/jobs.

Aucun endpoint dédié. C'est la leçon du commit `5257323` : deux chemins pour le même
travail, dont un seul exercé, divergent — et c'est arrivé aux contraintes de composition
fiction, présentes sur un chemin et absentes de l'autre pendant tout un commit.

Le format est donc validé AVANT la création du job, comme le sous-genre fiction : une 400
immédiate, jamais un 202 suivi d'un job en échec que l'utilisateur ne saurait pas
attribuer à sa saisie.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "web"))

from tests.test_server_jobs import _attendre_job, _client_with_isolated_dbs


def test_les_formats_sont_servis_groupes_par_famille(tmp_path, monkeypatch):
    """Source de vérité unique du sélecteur : jamais de liste dupliquée en dur côté JS,
    elle se périmerait à la première taxo v2 (même règle que /api/fiction/sous-genres)."""
    client, _ = _client_with_isolated_dbs(monkeypatch, tmp_path)
    r = client.get("/api/lowcontent/formats")
    assert r.status_code == 200
    formats = r.json()
    assert isinstance(formats, list) and len(formats) >= 20
    for f in formats:
        assert {"cle", "label", "famille"} <= set(f)
    cles = [f["cle"] for f in formats]
    assert "registres_reglementaires" in cles and "mots_meles" in cles


def test_les_formats_normes_sont_signales(tmp_path, monkeypatch):
    """L'UI doit pouvoir poser un badge « normé » : le contenu est imposé par une règle,
    et le verdict devra citer sa source. Le déduire côté JS dupliquerait la taxonomie."""
    client, _ = _client_with_isolated_dbs(monkeypatch, tmp_path)
    formats = {f["cle"]: f for f in client.get("/api/lowcontent/formats").json()}
    assert formats["registres_reglementaires"]["norme"] is True
    assert formats["mots_meles"]["norme"] is False


def test_l_endpoint_des_formats_exige_une_session(tmp_path, monkeypatch):
    client, _ = _client_with_isolated_dbs(monkeypatch, tmp_path)
    client.cookies.clear()
    assert client.get("/api/lowcontent/formats").status_code == 401


def test_un_job_lowcontent_se_lance_et_rend_son_resultat(tmp_path, monkeypatch):
    client, server = _client_with_isolated_dbs(monkeypatch, tmp_path)
    from models import LowContentNiche, LowContentScored

    def faux_run(seed=None, format_cle=None, progress=None, cost=None, **kw):
        if progress:
            progress("arbre lu")
        if cost is not None:
            cost.add_llm("claude-sonnet-5", 10, 5)
        n = LowContentNiche(niche="carnet suivi glycémie",
                            requete_amazon="carnet suivi glycemie", rationale="r",
                            categorie="santé", format_cle="journal_suivi",
                            theme="glycémie", public="adulte")
        return [LowContentScored(niche=n, global_score=7.4, priorite="🟡 Intéressant")]

    monkeypatch.setattr(server, "run_lowcontent_scout", faux_run)
    r = client.post("/api/jobs", json={"type": "lowcontent", "seed": "carnet"})
    assert r.status_code == 202
    job = _attendre_job(client, r.json()["id"])
    assert job["statut"] == "termine"
    assert job["resultat"][0]["niche"]["format_cle"] == "journal_suivi"


def test_un_format_inconnu_rend_400_avant_de_creer_le_job(tmp_path, monkeypatch):
    """400 immédiate, jamais un 202 suivi d'un job en échec : levée depuis le thread
    détaché, l'erreur arriverait après un 202 déjà rendu, et l'utilisateur verrait une
    analyse « lancée » qui rate sans comprendre que sa saisie était fautive."""
    client, _ = _client_with_isolated_dbs(monkeypatch, tmp_path)
    r = client.post("/api/jobs", json={"type": "lowcontent", "format_cle": "grimoire"})
    assert r.status_code == 400
    assert "grimoire" in r.text


def test_les_volumes_sont_bornes_comme_les_autres_scouts(tmp_path, monkeypatch):
    """Le plafond compte des ANALYSES, pas des appels payants : sans borne, une seule
    « analyse » avec n_search=9999 déclencherait des milliers de requêtes DataForSEO."""
    client, _ = _client_with_isolated_dbs(monkeypatch, tmp_path)
    r = client.post("/api/jobs", json={"type": "lowcontent", "seed": "x",
                                       "n_search": 9999})
    assert r.status_code == 400


def test_la_graine_est_bornee_en_longueur(tmp_path, monkeypatch):
    """Elle part dans un prompt LLM : une graine de 4 000 caractères n'est pas une graine."""
    client, _ = _client_with_isolated_dbs(monkeypatch, tmp_path)
    r = client.post("/api/jobs", json={"type": "lowcontent", "seed": "x" * 400})
    assert r.status_code == 400


def test_le_verdict_low_content_passe_par_le_meme_endpoint(tmp_path, monkeypatch):
    """UN SEUL /api/verdict pour les deux. Un second endpoint ferait diverger les gardes
    de plafond — c'est la leçon du commit `5257323`."""
    client, server = _client_with_isolated_dbs(monkeypatch, tmp_path)
    from models import NicheVerdict

    vus = []

    def faux_verdict_lc(scored, **kw):
        vus.append(scored)
        return NicheVerdict(verdict="Go prudent", confiance=7,
                            facteur_decisif="la conformité")

    monkeypatch.setattr(server, "generate_lowcontent_verdict", faux_verdict_lc)
    corps = {
        "type": "lowcontent",
        "niche": {"niche": "registre du personnel",
                  "requete_amazon": "registre du personnel obligatoire",
                  "rationale": "r", "categorie": "pro",
                  "format_cle": "registres_reglementaires", "theme": "personnel",
                  "public": "professionnel"},
        "global_score": 7.1,
    }
    r = client.post("/api/verdict", json=corps)
    assert r.status_code == 200 and r.json()["verdict"] == "Go prudent"
    assert vus and vus[0].niche.format_cle == "registres_reglementaires"


def test_sans_type_le_verdict_reste_celui_du_scout(tmp_path, monkeypatch):
    """Rétro-compatibilité : un client existant n'envoie pas `type` et doit continuer à
    obtenir le verdict non-fiction."""
    client, server = _client_with_isolated_dbs(monkeypatch, tmp_path)
    from models import NicheVerdict

    appele = []
    monkeypatch.setattr(server, "generate_verdict",
                        lambda s, **kw: appele.append(s) or NicheVerdict(
                            verdict="Go", confiance=8, facteur_decisif="x"))
    r = client.post("/api/verdict", json={"niche": "tarot", "requete_amazon": "tarot",
                                          "categorie": "éso"})
    assert r.status_code == 200 and appele


def test_un_type_de_verdict_inconnu_rend_400(tmp_path, monkeypatch):
    client, _ = _client_with_isolated_dbs(monkeypatch, tmp_path)
    r = client.post("/api/verdict", json={"type": "fiction", "niche": "x"})
    assert r.status_code == 400
