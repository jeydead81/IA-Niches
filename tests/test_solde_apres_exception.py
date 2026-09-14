"""R16 — /api/verdict et /api/kdp-keywords SOLDENT le coût quand la lecture de la réponse
lève APRÈS l'appel payé (§5.29).

`solder` suivait l'appel : une exception entre les deux laissait la réservation à 0 $ dans
usage.db, alors que les jetons étaient facturés. Or c'est usage.db qui porte tout le
raisonnement de marge — ce qu'il ne voit pas, personne ne le voit.

Le chemin passe par le VRAI générateur (niche_verdict, lowcontent_verdict, kdp_keywords) :
seuls le client Anthropic et la sonde autocomplete sont remplacés. Remplacer la fonction
testée ne prouverait que le harnais (§2.16).

FIXTURES INVENTÉES : les réponses factices (5 000 / 1 500 jetons, `input` en texte libre,
`content` absent) ne sont pas des captures. La forme « texte à la place d'objets » est celle,
réelle, du plantage du 2026-09-13.
"""
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "web"))

_NICHE = {"niche": "tarot", "requete_amazon": "tarot", "categorie": "éso"}
_NICHE_LC = {"niche": {"niche": "registre du personnel",
                       "requete_amazon": "registre du personnel obligatoire",
                       "rationale": "r", "categorie": "pro",
                       "format_cle": "registres_reglementaires", "theme": "personnel",
                       "public": "professionnel"},
             "global_score": 7.1, "concurrence_mesuree": True}


class _Usage:
    input_tokens = 5000
    output_tokens = 1500


class _Bloc:
    type = "tool_use"

    def __init__(self, entree):
        self.input = entree


class _Reponse:
    def __init__(self, entree, sans_contenu):
        self.usage = _Usage()
        self.stop_reason = "tool_use"
        self.content = None if sans_contenu else [_Bloc(entree)]


class _Anthropic:
    def __init__(self, entree=None, sans_contenu=False):
        self.entree, self.sans_contenu, self.appels = entree, sans_contenu, 0
        self.messages = self

    def create(self, **kw):
        self.appels += 1
        return _Reponse(self.entree, self.sans_contenu)


def _client(monkeypatch, tmp_path):
    """Comme `_client_with_isolated_dbs`, mais une exception du serveur devient une
    réponse : on veut lire le statut ET la ligne d'usage, pas l'exception."""
    pytest.importorskip("httpx")
    from fastapi.testclient import TestClient
    import server
    from tests.conftest import isoler_bases, ouvrir_session
    isoler_bases(monkeypatch, server, tmp_path)
    monkeypatch.setattr("kdp_keywords._default_sonde", lambda p: [])   # jamais le réseau
    c = TestClient(server.app, raise_server_exceptions=False)
    return c, server, ouvrir_session(c)


def _cout(server, user_id) -> float:
    from usage import UsageMeter
    return UsageMeter(server._USAGE_DB).resume(user_id).cout_usd


# ── Une exception APRÈS l'appel payé ─────────────────────────────────────────────

def test_verdict_scout_qui_leve_apres_l_appel_solde_le_cout(tmp_path, monkeypatch):
    client, server, uid = _client(monkeypatch, tmp_path)
    faux = _Anthropic("texte libre")
    monkeypatch.setattr("niche_verdict._default_client", lambda: faux)
    r = client.post("/api/verdict", json=_NICHE)
    assert faux.appels == 1
    assert r.status_code == 502
    assert "texte libre" not in r.text                  # rien d'interne ne sort (§2.7)
    assert _cout(server, uid) > 0


def test_verdict_lowcontent_qui_leve_apres_l_appel_solde_le_cout(tmp_path, monkeypatch):
    client, server, uid = _client(monkeypatch, tmp_path)
    faux = _Anthropic("texte libre")
    monkeypatch.setattr("lowcontent_verdict._default_client", lambda: faux)
    r = client.post("/api/verdict", json={"type": "lowcontent", **_NICHE_LC})
    assert faux.appels == 1
    assert r.status_code == 502
    assert _cout(server, uid) > 0


def test_mots_cles_qui_levent_apres_l_appel_soldent_le_cout(tmp_path, monkeypatch):
    client, server, uid = _client(monkeypatch, tmp_path)
    faux = _Anthropic(sans_contenu=True)
    monkeypatch.setattr("kdp_keywords._default_client", lambda: faux)
    r = client.post("/api/kdp-keywords", json=_NICHE)
    assert faux.appels == 1
    assert r.status_code == 502
    assert _cout(server, uid) > 0


# ── Témoins : le chemin nominal, et /api/dossier qui était déjà conforme ──────────

def test_temoin_un_verdict_lisible_rend_200_et_impute(tmp_path, monkeypatch):
    client, server, uid = _client(monkeypatch, tmp_path)
    monkeypatch.setattr("niche_verdict._default_client", lambda: _Anthropic(
        {"verdict": "Go", "confiance": 8, "facteur_decisif": "x"}))
    assert client.post("/api/verdict", json=_NICHE).status_code == 200
    assert _cout(server, uid) > 0


def test_temoin_des_mots_cles_lisibles_rendent_200_et_imputent(tmp_path, monkeypatch):
    client, server, uid = _client(monkeypatch, tmp_path)
    monkeypatch.setattr("kdp_keywords._default_client", lambda: _Anthropic(
        {"candidats": ["enquête village pâtissière"]}))
    assert client.post("/api/kdp-keywords", json=_NICHE).status_code == 200
    assert _cout(server, uid) > 0


def test_non_regression_le_dossier_avec_mots_cles_impute_toujours(tmp_path, monkeypatch):
    client, server, uid = _client(monkeypatch, tmp_path)
    monkeypatch.setattr("kdp_keywords._default_client", lambda: _Anthropic(
        {"candidats": ["enquête village pâtissière"]}))
    r = client.post("/api/dossier", json={"niche": {**_NICHE, "concurrence_mesuree": True},
                                          "inclure_mots_cles": True})
    assert r.status_code == 200 and r.content[:4] == b"%PDF"
    assert _cout(server, uid) > 0
