import pytest
import requests

from util import http_get, BROWSER_HEADERS


class FakeResp:
    def __init__(self, status, text):
        self.status_code = status
        self.text = text


def test_headers_have_browser_ua():
    assert "Mozilla" in BROWSER_HEADERS["User-Agent"]
    assert BROWSER_HEADERS["Accept-Language"].startswith("fr-FR")


def test_http_get_retries_then_succeeds():
    calls = {"n": 0}

    def fake_get(url, headers=None, timeout=None):
        calls["n"] += 1
        if calls["n"] == 1:
            raise requests.exceptions.ConnectionError("boom")
        return FakeResp(200, "OK")

    r = http_get("https://example.test", getter=fake_get, retries=1, delay=0)
    assert r.status_code == 200
    assert calls["n"] == 2


def test_http_get_does_not_retry_non_network_errors():
    """Un bug de programmation (ex: ValueError) ne doit PAS être avalé par le
    retry réseau : il doit se propager immédiatement, sans tentative supplémentaire."""
    calls = {"n": 0}

    def fake_get(url, headers=None, timeout=None):
        calls["n"] += 1
        raise ValueError("bug de programmation, pas une erreur réseau")

    with pytest.raises(ValueError):
        http_get("https://example.test", getter=fake_get, retries=1, delay=0)
    assert calls["n"] == 1
