import pytest

from amazon_autocomplete import AutocompleteError, fetch_json_strict, parse_suggestions, fetch_suggestions

# Format réel observé le 2026-07-05
FIXTURE = {"suggestions": [
    {"value": "tarot"},
    {"value": "tarot divinatoire"},
    {"value": "tarot de marseille"},
    {"value": ""},          # vide → ignoré
]}


def test_parse_suggestions_filters_empty():
    out = parse_suggestions(FIXTURE)
    assert out == ["tarot", "tarot divinatoire", "tarot de marseille"]


def test_parse_suggestions_bad_payload():
    assert parse_suggestions({}) == []
    assert parse_suggestions({"suggestions": None}) == []


def test_fetch_suggestions_uses_injected_json():
    out = fetch_suggestions("tarot", fetch_json=lambda prefix: FIXTURE)
    assert "tarot divinatoire" in out


class _Resp:
    def __init__(self, status_code, text):
        self.status_code, self.text = status_code, text


def test_strict_leve_sur_http_non_200(monkeypatch):
    monkeypatch.setattr("util.http_get", lambda url, timeout=15: _Resp(503, ""))
    with pytest.raises(AutocompleteError):
        fetch_json_strict("cosy mystery")


def test_strict_leve_sur_json_invalide(monkeypatch):
    monkeypatch.setattr("util.http_get", lambda url, timeout=15: _Resp(200, "<html>"))
    with pytest.raises(AutocompleteError):
        fetch_json_strict("cosy mystery")


def test_strict_rend_le_json_quand_tout_va_bien(monkeypatch):
    monkeypatch.setattr("util.http_get",
                        lambda url, timeout=15: _Resp(200, '{"suggestions":[{"value":"x"}]}'))
    assert fetch_json_strict("x")["suggestions"][0]["value"] == "x"


def test_fetch_suggestions_reste_silencieux_sur_echec(monkeypatch):
    """Contrat inchangé pour l'appelant non-fiction en production."""
    monkeypatch.setattr("util.http_get", lambda url, timeout=15: _Resp(503, ""))
    assert fetch_suggestions("cosy mystery") == []
