"""
debug_autocomplete.py
---------------------
Diagnostic : teste plusieurs variantes de l'URL Amazon autocomplete via Scrapingdog.
Lance avec : python 01-scripts/debug_autocomplete.py
Génère : 99-logs/debug_autocomplete_response.txt
"""

import json
import os
import sys
from pathlib import Path
from urllib.parse import urlencode, quote

import requests
from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent.parent
load_dotenv(BASE_DIR / ".env")
API_KEY = os.getenv("SCRAPINGDOG_API_KEY", "")
LOG_FILE = BASE_DIR / "99-logs" / "debug_autocomplete_response.txt"
LOG_FILE.parent.mkdir(parents=True, exist_ok=True)

SCRAPE_URL = "https://api.scrapingdog.com/scrape"
KEYWORD = "jeune intermittent"  # sans accent pour éviter problème d'encodage

lines = []

def p(msg):
    print(msg)
    lines.append(msg)

def test_variant(label, amazon_url, dynamic="false"):
    p(f"\n{'='*60}")
    p(f"TEST : {label}")
    p(f"Amazon URL : {amazon_url}")
    p(f"dynamic={dynamic}")
    try:
        resp = requests.get(
            SCRAPE_URL,
            params={"api_key": API_KEY, "url": amazon_url, "dynamic": dynamic},
            timeout=25,
        )
        p(f"HTTP status : {resp.status_code}")
        p(f"Content-Type : {resp.headers.get('content-type', 'N/A')}")
        raw = resp.text
        p(f"Longueur réponse : {len(raw)} chars")
        p(f"Début réponse (500 chars) :\n{raw[:500]}")
        # Tentative parse JSON
        try:
            data = json.loads(raw)
            suggestions = data.get("suggestions", data.get("completion", []))
            p(f"✓ JSON valide — suggestions trouvées : {suggestions}")
        except json.JSONDecodeError:
            p("✗ Pas du JSON valide (HTML ou autre)")
    except Exception as e:
        p(f"✗ Erreur réseau : {e}")


# ── Variante 1 : paramètre q= (version actuelle) ──────────────────────────────
url1 = f"https://completion.amazon.fr/api/2017/suggestions?q={quote(KEYWORD)}&alias=aps&mid=A13V1IB3VIYZZH"
test_variant("q= (version actuelle)", url1, dynamic="false")

# ── Variante 2 : paramètre prefix= (autre variante Amazon) ────────────────────
url2 = f"https://completion.amazon.fr/api/2017/suggestions?mid=A13V1IB3VIYZZH&alias=aps&prefix={quote(KEYWORD)}&event=onkeypress&limit=11&b2b=0&fresh=0"
test_variant("prefix= (variante Amazon)", url2, dynamic="false")

# ── Variante 3 : dynamic=true ──────────────────────────────────────────────────
test_variant("prefix= + dynamic=true", url2, dynamic="true")

# ── Variante 4 : autre MID Amazon.fr ─────────────────────────────────────────
# Certaines sources mentionnent ce MID alternatif pour amazon.fr
url4 = f"https://completion.amazon.fr/api/2017/suggestions?mid=A13V1IB3VIYZZH&alias=aps&prefix={quote(KEYWORD)}&limit=11"
test_variant("prefix= + limit=11 seul", url4, dynamic="false")

# ── Variante 5 : avec headers custom passés via Scrapingdog ──────────────────
p(f"\n{'='*60}")
p("TEST 5 : prefix= + headers custom (Accept: application/json)")
try:
    resp = requests.get(
        SCRAPE_URL,
        params={
            "api_key": API_KEY,
            "url": url2,
            "dynamic": "false",
            "header_accept": "application/json, text/javascript, */*; q=0.01",
            "header_x-requested-with": "XMLHttpRequest",
        },
        timeout=25,
    )
    p(f"HTTP status : {resp.status_code}")
    raw = resp.text
    p(f"Longueur : {len(raw)} / Début : {raw[:300]}")
except Exception as e:
    p(f"✗ {e}")

# ── Résumé ────────────────────────────────────────────────────────────────────
p(f"\n{'='*60}")
p(f"Fichier de log complet : {LOG_FILE}")

LOG_FILE.write_text("\n".join(lines), encoding="utf-8")
print(f"\n→ Log sauvegardé dans {LOG_FILE}")
