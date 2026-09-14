"""`POST /api/dossier` — le Dossier v2, servi par le même chemin que le reste.

`/api/pdf` est CONSERVÉ comme alias : c'est une route qu'un client tiers peut appeler, et
la casser sans prévenir n'apporterait rien. Elle sert désormais le même document.

L'endpoint peut générer les mots-clés (0,006 $) : il exige donc une marge sous le plafond,
comme `/api/verdict` et `/api/kdp-keywords`, et impute `n_analyses=0` — il complète une
analyse déjà comptée.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "web"))

from tests.test_server_jobs import _client_with_isolated_dbs

_NICHE = {"niche": "carnet de suivi glycémie", "requete_amazon": "carnet suivi glycemie",
          "categorie": "santé", "global_score": 7.8, "concurrence_mesuree": True,
          "bsr_best": 8214,
          "top_books": [{"asin": "A1", "title": "Carnet 120 pages",
                         "url": "https://www.amazon.fr/dp/A1", "bsr": 8214}]}


def test_le_dossier_est_servi_en_pdf(tmp_path, monkeypatch):
    client, _ = _client_with_isolated_dbs(monkeypatch, tmp_path)
    r = client.post("/api/dossier", json={"niche": _NICHE})
    assert r.status_code == 200
    assert r.headers["content-type"] == "application/pdf"
    assert r.content[:4] == b"%PDF"


def test_le_nom_de_fichier_supporte_les_accents(tmp_path, monkeypatch):
    """Starlette exige un en-tête encodable en latin-1 : un nom de niche accentué faisait
    planter la réponse (§5.25). Le garde existant doit valoir aussi ici."""
    client, _ = _client_with_isolated_dbs(monkeypatch, tmp_path)
    r = client.post("/api/dossier", json={"niche": {**_NICHE, "niche": "éphéméride"}})
    assert r.status_code == 200
    r.headers["content-disposition"].encode("latin-1")      # ne doit pas lever


def test_une_niche_low_content_est_acceptee(tmp_path, monkeypatch):
    client, _ = _client_with_isolated_dbs(monkeypatch, tmp_path)
    corps = {"type": "lowcontent", "niche": {
        "niche": {"niche": "registre du personnel",
                  "requete_amazon": "registre du personnel obligatoire",
                  "rationale": "r", "categorie": "pro",
                  "format_cle": "registres_reglementaires", "theme": "personnel",
                  "public": "professionnel"},
        "global_score": 7.1, "concurrence_mesuree": True, "part_indie": 0.7}}
    r = client.post("/api/dossier", json=corps)
    assert r.status_code == 200 and r.content[:4] == b"%PDF"


def test_les_categories_sont_calculees_sans_rien_payer(tmp_path, monkeypatch):
    """Elles se déduisent des BSR DÉJÀ collectés : aucun appel, aucune imputation."""
    client, server = _client_with_isolated_dbs(monkeypatch, tmp_path)
    from usage import UsageMeter
    r = client.post("/api/dossier", json={"niche": _NICHE, "inclure_categories": True})
    assert r.status_code == 200
    u = UsageMeter(server._USAGE_DB).resume(
        client.get("/api/auth/moi").json()["user_id"])
    assert u.cout_usd == 0


def test_les_mots_cles_ne_sont_generes_que_si_on_les_demande(tmp_path, monkeypatch):
    """0,006 $ l'appel : le défaut ne doit pas dépenser à l'insu de l'utilisateur."""
    client, server = _client_with_isolated_dbs(monkeypatch, tmp_path)
    appels = []
    monkeypatch.setattr(server, "generer_mots_cles",
                        lambda *a, **k: appels.append(1) or __import__("models").MotsClesKDP())

    client.post("/api/dossier", json={"niche": _NICHE})
    assert appels == []

    client.post("/api/dossier", json={"niche": _NICHE, "inclure_mots_cles": True})
    assert len(appels) == 1


def test_un_echec_de_mots_cles_ne_coule_pas_le_dossier(tmp_path, monkeypatch):
    """Le document reste utile sans eux : c'est l'invariant §5.29 applique au PDF."""
    client, server = _client_with_isolated_dbs(monkeypatch, tmp_path)

    def boum(*a, **k):
        raise RuntimeError("LLM indisponible")

    monkeypatch.setattr(server, "generer_mots_cles", boum)
    r = client.post("/api/dossier", json={"niche": _NICHE, "inclure_mots_cles": True})
    assert r.status_code == 200 and r.content[:4] == b"%PDF"


def test_un_corps_invalide_rend_400_jamais_500(tmp_path, monkeypatch):
    client, _ = _client_with_isolated_dbs(monkeypatch, tmp_path)
    assert client.post("/api/dossier", json={"niche": {"pas": "une niche"}}).status_code == 400


def test_l_endpoint_exige_une_session(tmp_path, monkeypatch):
    client, _ = _client_with_isolated_dbs(monkeypatch, tmp_path)
    client.cookies.clear()
    assert client.post("/api/dossier", json={"niche": _NICHE}).status_code == 401


def test_l_ancienne_route_pdf_sert_le_meme_document(tmp_path, monkeypatch):
    """Conservée comme alias : un client tiers peut l'appeler, et la casser sans prévenir
    n'apporterait rien."""
    client, _ = _client_with_isolated_dbs(monkeypatch, tmp_path)
    r = client.post("/api/pdf", json=_NICHE)
    assert r.status_code == 200 and r.content[:4] == b"%PDF"


def test_les_mots_cles_d_un_dossier_low_content_sont_reellement_generes(tmp_path, monkeypatch):
    """R32. `generer_mots_cles` recevait le `LowContentScored` entier, qui ne porte ni
    `requete_amazon` ni `categorie` : AttributeError AVANT l'appel, avalée par le garde
    §5.29, dossier sans mots-clés et créneau de débit consommé — sans rien dire.

    Rien du chemin testé n'est remplacé : seuls le client Anthropic (réponse figée,
    INVENTÉE) et la sonde autocomplete (vide, jamais le réseau) le sont."""
    import kdp_keywords
    from usage import UsageMeter
    client, server = _client_with_isolated_dbs(monkeypatch, tmp_path)
    prompts = []

    class _Bloc:
        type = "tool_use"
        input = {"candidats": ["registre personnel entreprise"]}

    class _Usage:
        input_tokens, output_tokens = 900, 300

    class _Reponse:
        content, usage, stop_reason = [_Bloc()], _Usage(), "tool_use"

    class _Faux:
        def __init__(self):
            self.messages = self

        def create(self, **kw):
            prompts.append(kw["messages"][0]["content"])
            return _Reponse()

    monkeypatch.setattr(kdp_keywords, "_default_client", _Faux)
    monkeypatch.setattr(kdp_keywords, "_default_sonde", lambda p: [])
    corps = {"type": "lowcontent", "inclure_mots_cles": True, "niche": {
        "niche": {"niche": "registre du personnel",
                  "requete_amazon": "registre du personnel obligatoire",
                  "rationale": "r", "categorie": "pro",
                  "format_cle": "registres_reglementaires", "theme": "personnel",
                  "public": "professionnel"},
        "global_score": 7.1, "concurrence_mesuree": True}}
    r = client.post("/api/dossier", json=corps)
    assert r.status_code == 200 and r.content[:4] == b"%PDF"
    assert len(prompts) == 1
    assert "registre du personnel obligatoire" in prompts[0]
    uid = client.get("/api/auth/moi").json()["user_id"]
    assert UsageMeter(server._USAGE_DB).resume(uid).cout_usd > 0

    import io
    pypdf = __import__("pytest").importorskip("pypdf")
    texte = "\n".join(p.extract_text() or "" for p in pypdf.PdfReader(io.BytesIO(r.content)).pages)
    assert "registre personnel entreprise" in texte
