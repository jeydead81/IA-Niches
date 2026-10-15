"""Les polices sont servies par le service lui-même (2026-10-15).

La page chargeait Newsreader, DM Sans et JetBrains Mono depuis Google Fonts : chaque visite envoyait
l'adresse IP du visiteur à un tiers (problème RGPD, relevé au ROADMAP) et une instance sans sortie
Internet retombait sur les polices système. Les trois fichiers (sous-ensemble latin, WOFF2, licence
SIL OFL 1.1) vivent maintenant dans `web/fonts/`, servis par `GET /fonts/{nom}`.

La route est SANS session : l'écran de connexion en a besoin avant qu'il y ait une session. Elle ne
sert que des noms qui existent déjà dans `web/fonts/` et que la regex `[a-z0-9-]+.woff2` autorise :
aucun chemin n'est jamais construit à partir de ce que le client envoie.
"""
import re
from pathlib import Path

import pytest

from tests.conftest import isoler_bases

RACINE = Path(__file__).resolve().parent.parent
HTML = (RACINE / "web" / "index.html").read_text(encoding="utf-8")
FICHIERS = sorted(p.name for p in (RACINE / "web" / "fonts").glob("*.woff2"))


def _client(monkeypatch, tmp_path):
    pytest.importorskip("httpx")
    from fastapi.testclient import TestClient
    import server
    isoler_bases(monkeypatch, server, tmp_path)
    return TestClient(server.app)


# ── La page ne parle plus à un tiers ────────────────────────────────────────────────

def test_la_page_n_appelle_plus_google_fonts():
    for interdit in ("fonts.googleapis.com", "fonts.gstatic.com", "@import url("):
        assert interdit not in HTML, interdit


def test_aucune_requete_vers_un_tiers_dans_la_page():
    """Seuls restent les liens `amazon.fr/dp/` des ASIN (un clic de l'utilisateur, pas un chargement)."""
    externes = [u for u in re.findall(r"https?://[^\s'\"<>)]+", HTML)
                if "amazon.fr" not in u and "w3.org" not in u]
    assert externes == [], externes


@pytest.mark.parametrize("famille", ["Newsreader", "DM Sans", "JetBrains Mono"])
def test_chaque_famille_est_declaree_avec_un_fichier_local(famille):
    m = re.search(r"@font-face\s*\{[^}]*font-family:\s*'" + re.escape(famille) + r"'[^}]*\}", HTML)
    assert m, famille
    bloc = m.group(0)
    assert "font-display:swap" in bloc.replace(" ", "")
    fichier = re.search(r"url\('/fonts/([a-z0-9\-]+\.woff2)'\)", bloc)
    assert fichier and fichier.group(1) in FICHIERS


def test_les_trois_fichiers_sont_de_vrais_woff2():
    assert len(FICHIERS) == 3
    for nom in FICHIERS:
        assert (RACINE / "web" / "fonts" / nom).read_bytes()[:4] == b"wOF2", nom


def test_la_licence_accompagne_les_fichiers():
    texte = (RACINE / "web" / "fonts" / "LICENSES.txt").read_text(encoding="utf-8")
    assert "SIL Open Font License" in texte
    for famille in ("Newsreader", "DM Sans", "JetBrains Mono"):
        assert famille in texte


# ── La route ────────────────────────────────────────────────────────────────────────

@pytest.mark.parametrize("nom", FICHIERS)
def test_les_polices_sont_servies_sans_session(monkeypatch, tmp_path, nom):
    r = _client(monkeypatch, tmp_path).get(f"/fonts/{nom}")
    assert r.status_code == 200 and r.content[:4] == b"wOF2"
    assert r.headers["content-type"] == "font/woff2"
    assert "immutable" in r.headers["cache-control"] and "max-age=31536000" in r.headers["cache-control"]


@pytest.mark.parametrize("nom", ["inconnue.woff2", "dm-sans-latin.ttf", "LICENSES.txt", "..%2findex.html",
                                 "..%5cindex.html", "%2e%2e%2fserver.py", "dm-sans-latin.woff2%00.txt",
                                 "DM-SANS-LATIN.woff2", "a b.woff2"])
def test_aucun_autre_nom_n_est_servi(monkeypatch, tmp_path, nom):
    r = _client(monkeypatch, tmp_path).get(f"/fonts/{nom}")
    assert r.status_code in (400, 404), (nom, r.status_code)


def test_un_chemin_a_plusieurs_segments_n_est_pas_servi(monkeypatch, tmp_path):
    c = _client(monkeypatch, tmp_path)
    for chemin in ("/fonts/../index.html", "/fonts/sous/dm-sans-latin.woff2", "/fonts/"):
        assert c.get(chemin).status_code in (307, 400, 404), chemin


def test_la_route_n_ecrit_rien_et_n_expose_que_des_polices(monkeypatch, tmp_path):
    c = _client(monkeypatch, tmp_path)
    assert c.post("/fonts/dm-sans-latin.woff2").status_code in (404, 405)
