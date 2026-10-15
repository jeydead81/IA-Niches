"""Verdicts et mots-clés « inclus » : un jeu par niche, et un plafond MENSUEL (2026-10-06).

Le seul garde des appels à la pièce était un DÉBIT : 40 par heure. C'est un limiteur de
rythme, pas un quota : 40 × 24 × 30 = 28 800 appels par mois, soit jusqu'à environ 950 € de
coût pour un abonné à quelques euros. Un verdict coûte 0,037 $ ; au-delà de la ~365e requête
l'abonné coûte plus qu'il ne paie, et rien ne bronchait — le cas tient à `/api/verdict` sans
état, que n'importe quel client HTTP rejoue.

Deux fermetures, volontairement petites :

1. **Un jeu par niche.** Quand la page indique la niche (`?job=…&cle=…`) et qu'elle porte déjà
   le résultat, le SERVEUR le rend — sans rappeler le modèle, sans réservation, sans coût. Le
   bouton de l'interface disparaît une fois le résultat rangé ; ceci protège du double clic,
   de deux onglets, et d'un client qui rejoue.
2. **Un plafond mensuel**, dérivé de l'offre : une analyse détaillée et un jeu de mots-clés
   par niche autorisée, soit DEUX appels par niche du plafond mensuel (`APPELS_PIECE_PAR_NICHE`).
   Sans plafond de niches (poste local), un fusible de 120.

Le plafond de niches n'est PLUS la condition d'un verdict : un abonné qui a consommé ses 60
niches doit pouvoir lire le verdict des 60 — sinon « verdict inclus » serait un mensonge pile
à la fin du mois. Ce qui borne le LLM, c'est ce plafond mensuel d'appels.

Aucun modèle réel n'est atteint : les générateurs sont bouchonnés.
"""
import pytest

from tests.conftest import isoler_bases, ouvrir_session


class _Objet:
    """Ce que rendent les générateurs : un objet pydantic, vu seulement par `model_dump`."""
    def __init__(self, **d):
        self._d = d

    def model_dump(self):
        return dict(self._d)


def _client(monkeypatch, tmp_path, plafond=None):
    pytest.importorskip("httpx")
    from fastapi.testclient import TestClient
    import server
    isoler_bases(monkeypatch, server, tmp_path)
    monkeypatch.delenv("PLAFOND_NICHES_MENSUEL", raising=False)
    monkeypatch.delenv("DEBIT_APPELS_MAX", raising=False)
    if plafond is not None:
        monkeypatch.setenv("PLAFOND_NICHES_MENSUEL", str(plafond))
    appels = {"verdict": 0, "mots": 0}

    def faux_verdict(scored, on_usage=None, **kw):
        appels["verdict"] += 1
        return _Objet(verdict="Go", confiance=7)

    def faux_mots(candidat, **kw):
        appels["mots"] += 1
        return _Objet(mots=["a", "b"])

    monkeypatch.setattr(server, "generate_verdict", faux_verdict)
    monkeypatch.setattr(server, "generer_mots_cles", faux_mots)
    client = TestClient(server.app)
    uid = ouvrir_session(client)
    return client, server, uid, appels


NICHE = {"niche": "tarot du matin", "global_score": 7.0}


def _travail_avec_niche(server, uid, **champs):
    from jobs import JobStore
    s = JobStore(server._JOBS_DB)
    jid = s.create("scout", {}, user_id=uid)
    s.finish(jid, [{**NICHE, **champs}], {})
    return jid


# ── Le plafond mensuel d'appels ─────────────────────────────────────────────────────

def test_le_plafond_mensuel_vaut_deux_appels_par_niche_autorisee(monkeypatch, tmp_path):
    client, server, uid, appels = _client(monkeypatch, tmp_path, plafond=2)
    assert server._appels_a_la_piece_max() == 4
    for _ in range(4):
        assert client.post("/api/verdict", json=NICHE).status_code == 200
    r = client.post("/api/verdict", json=NICHE)
    assert r.status_code == 429
    assert "mensuel" in r.json()["detail"].lower() and "rien n" in r.json()["detail"].lower()
    assert appels["verdict"] == 4, "le cinquième appel ne doit JAMAIS atteindre le modèle"


def test_verdicts_et_mots_cles_partagent_le_meme_plafond(monkeypatch, tmp_path):
    client, server, uid, appels = _client(monkeypatch, tmp_path, plafond=1)      # 2 appels
    assert client.post("/api/verdict", json=NICHE).status_code == 200
    assert client.post("/api/kdp-keywords", json=NICHE).status_code == 200
    assert client.post("/api/verdict", json=NICHE).status_code == 429
    assert client.post("/api/kdp-keywords", json=NICHE).status_code == 429


def test_sans_plafond_de_niches_un_fusible_borne_quand_meme(monkeypatch, tmp_path):
    """Un poste local sans plafond n'est pas un poste sans fusible : le mois est borné."""
    client, server, uid, appels = _client(monkeypatch, tmp_path)
    monkeypatch.setattr(server, "APPELS_PIECE_MENSUEL_DEFAUT", 3)
    assert server._appels_a_la_piece_max() == 3
    for _ in range(3):
        assert client.post("/api/verdict", json=NICHE).status_code == 200
    assert client.post("/api/verdict", json=NICHE).status_code == 429


def test_un_abonne_qui_a_consomme_ses_niches_lit_encore_ses_verdicts(monkeypatch, tmp_path):
    """Le plafond de niches ne conditionne plus le verdict. Avant : « marge d'une unité »
    exigée, donc le verdict de la 60e niche refusé à un abonné qui venait de la payer."""
    from usage import UsageMeter
    client, server, uid, appels = _client(monkeypatch, tmp_path, plafond=3)
    UsageMeter(server._USAGE_DB).enregistrer(uid, "scout", 0.1, n_analyses=3)   # quota épuisé
    assert client.post("/api/verdict", json=NICHE).status_code == 200


def test_un_plafond_de_zero_niche_ferme_aussi_les_appels_a_la_piece(monkeypatch, tmp_path):
    client, server, uid, appels = _client(monkeypatch, tmp_path, plafond=0)
    assert client.post("/api/verdict", json=NICHE).status_code == 429
    assert client.post("/api/kdp-keywords", json=NICHE).status_code == 429
    assert appels == {"verdict": 0, "mots": 0}


# ── Un jeu par niche : le rappel ne coûte rien ──────────────────────────────────────

def test_un_verdict_deja_range_est_rendu_sans_rappeler_le_modele(monkeypatch, tmp_path):
    from usage import UsageMeter
    client, server, uid, appels = _client(monkeypatch, tmp_path)
    jid = _travail_avec_niche(server, uid, verdict={"verdict": "No-Go", "confiance": 4})
    r = client.post("/api/verdict", params={"job": jid, "cle": NICHE["niche"]}, json=NICHE)
    assert r.status_code == 200
    d = r.json()
    assert d["verdict"] == "No-Go" and d["_deja_fait"] is True and d["_conserve"] is True
    assert appels["verdict"] == 0
    assert UsageMeter(server._USAGE_DB).compter(uid, server.TYPES_A_LA_PIECE, 3600) == 0


def test_des_mots_cles_deja_ranges_sont_rendus_sans_rappeler_le_modele(monkeypatch, tmp_path):
    client, server, uid, appels = _client(monkeypatch, tmp_path)
    jid = _travail_avec_niche(server, uid, mots_cles={"mots": ["deja"]})
    r = client.post("/api/kdp-keywords", params={"job": jid, "cle": NICHE["niche"]}, json=NICHE)
    assert r.status_code == 200 and r.json()["mots"] == ["deja"] and r.json()["_deja_fait"]
    assert appels["mots"] == 0


def test_le_rappel_ne_consomme_pas_le_plafond_mensuel(monkeypatch, tmp_path):
    client, server, uid, appels = _client(monkeypatch, tmp_path, plafond=1)      # 2 appels
    jid = _travail_avec_niche(server, uid, verdict={"verdict": "Go"})
    for _ in range(10):
        assert client.post("/api/verdict", params={"job": jid, "cle": NICHE["niche"]},
                           json=NICHE).status_code == 200
    assert appels["verdict"] == 0


def test_une_niche_sans_resultat_range_appelle_le_modele_une_fois(monkeypatch, tmp_path):
    client, server, uid, appels = _client(monkeypatch, tmp_path)
    jid = _travail_avec_niche(server, uid)
    r = client.post("/api/verdict", params={"job": jid, "cle": NICHE["niche"]}, json=NICHE)
    assert r.status_code == 200 and "_deja_fait" not in r.json()
    assert appels["verdict"] == 1
    # le résultat est maintenant rangé : le deuxième appel est un rappel gratuit
    r2 = client.post("/api/verdict", params={"job": jid, "cle": NICHE["niche"]}, json=NICHE)
    assert r2.json()["_deja_fait"] is True and appels["verdict"] == 1


def test_le_travail_d_un_autre_compte_n_est_jamais_rendu(monkeypatch, tmp_path):
    """Connaître un identifiant de travail ne donne aucun droit de lecture : l'appel suit son
    cours normal, payé par l'appelant, et rien du verdict d'autrui ne fuit."""
    client, server, uid, appels = _client(monkeypatch, tmp_path)
    jid = _travail_avec_niche(server, "autre-compte", verdict={"verdict": "SECRET"})
    r = client.post("/api/verdict", params={"job": jid, "cle": NICHE["niche"]}, json=NICHE)
    assert r.status_code == 200 and "SECRET" not in r.text
    assert appels["verdict"] == 1


def test_fiction_le_rappel_lit_analyse_et_non_verdict(monkeypatch, tmp_path):
    """Un résultat fiction porte déjà un `verdict` : le texte du moteur et ses réserves. Le
    rappel de l'analyse du modèle lit `analyse`, jamais ce texte."""
    from jobs import JobStore
    client, server, uid, appels = _client(monkeypatch, tmp_path)
    s = JobStore(server._JOBS_DB)
    jid = s.create("fiction", {}, user_id=uid)
    s.finish(jid, [{"niche": {"query": "roman cosy", "cle": "k1"}, "verdict": "texte du moteur",
                    "analyse": {"verdict": "Go prudent", "confiance": 6}}], {})
    got = s.lire_annotation(jid, uid, "k1", "analyse")
    assert got == {"verdict": "Go prudent", "confiance": 6}
    assert s.lire_annotation(jid, uid, "k1", "verdict") is None, \
        "`verdict` fiction est une chaîne : ce n'est pas une annotation du modèle"


def test_lire_annotation_refuse_un_champ_hors_liste(monkeypatch, tmp_path):
    from jobs import JobStore
    client, server, uid, appels = _client(monkeypatch, tmp_path)
    jid = _travail_avec_niche(server, uid, verdict={"verdict": "Go"}, secret={"x": 1})
    assert JobStore(server._JOBS_DB).lire_annotation(jid, uid, NICHE["niche"], "secret") is None


# ── Revue adversariale du 2026-10-06 ─────────────────────────────────────────────────

def test_un_appel_qui_echoue_sans_rien_depenser_ne_brule_pas_une_place_du_mois(monkeypatch, tmp_path):
    """502 à 0 $ : l'abonné n'a rien reçu, rien coûté. Garder sa réservation lui faisait perdre
    une place du plafond mensuel à chaque panne du fournisseur."""
    from usage import UsageMeter
    client, server, uid, appels = _client(monkeypatch, tmp_path, plafond=1)      # 2 appels

    def tombe(scored, on_usage=None, **kw):
        raise RuntimeError("fournisseur indisponible")

    monkeypatch.setattr(server, "generate_verdict", tombe)
    for _ in range(5):
        assert client.post("/api/verdict", json=NICHE).status_code == 502
    assert UsageMeter(server._USAGE_DB).compter(uid, server.TYPES_A_LA_PIECE, 30 * 24 * 3600) == 0
    monkeypatch.setattr(server, "generate_verdict",
                        lambda scored, on_usage=None, **kw: _Objet(verdict="Go"))
    assert client.post("/api/verdict", json=NICHE).status_code == 200


def test_un_appel_qui_echoue_apres_avoir_depense_garde_sa_place(monkeypatch, tmp_path):
    """Les jetons sont facturés dès la réponse : même règle que pour les niches, ce qui a coûté
    reste compté."""
    from usage import UsageMeter
    client, server, uid, appels = _client(monkeypatch, tmp_path, plafond=1)

    def tombe_apres_depense(scored, on_usage=None, **kw):
        on_usage(1000, 1000, "claude-sonnet-5")
        raise RuntimeError("réponse illisible")

    monkeypatch.setattr(server, "generate_verdict", tombe_apres_depense)
    assert client.post("/api/verdict", json=NICHE).status_code == 502
    assert UsageMeter(server._USAGE_DB).compter(uid, server.TYPES_A_LA_PIECE, 30 * 24 * 3600) == 1
    assert UsageMeter(server._USAGE_DB).resume(uid).cout_usd > 0


def test_les_mots_cles_qui_echouent_a_zero_liberent_aussi_leur_place(monkeypatch, tmp_path):
    from usage import UsageMeter
    client, server, uid, appels = _client(monkeypatch, tmp_path, plafond=1)

    def tombe(candidat, **kw):
        raise RuntimeError("fournisseur indisponible")

    monkeypatch.setattr(server, "generer_mots_cles", tombe)
    assert client.post("/api/kdp-keywords", json=NICHE).status_code == 502
    assert UsageMeter(server._USAGE_DB).compter(uid, server.TYPES_A_LA_PIECE, 30 * 24 * 3600) == 0
