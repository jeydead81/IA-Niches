"""Tests de l'endpoint PDF — couvre le bug d'en-tête Content-Disposition (latin-1)
qui faisait planter (500) le téléchargement pour les noms de niche français (« œ », accents)."""
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "web"))


def test_content_disposition_latin1_safe_and_rfc5987():
    from server import _content_disposition
    for name in ["cœur & l'œuvre — été", "stoïcisme pratique", "développement personnel", "", None]:
        cd = _content_disposition(name)
        cd.encode("latin-1")                       # Starlette encode les en-têtes en latin-1 -> ne doit PAS lever
        assert "filename*=UTF-8''" in cd and cd.startswith("attachment; filename=")


def test_api_pdf_french_niche_returns_pdf():
    pytest.importorskip("httpx")
    from fastapi.testclient import TestClient
    from server import app
    r = TestClient(app).post("/api/pdf", json={"niche": "cœur & stoïcisme — édition", "verdict": None})
    assert r.status_code == 200
    assert r.content[:5] == b"%PDF-"
    assert r.headers["content-type"] == "application/pdf"


def test_api_pdf_bad_body_returns_400():
    pytest.importorskip("httpx")
    from fastapi.testclient import TestClient
    from server import app
    r = TestClient(app).post("/api/pdf", json={"pas": "une niche"})   # 'niche' requis manquant
    assert r.status_code == 400
