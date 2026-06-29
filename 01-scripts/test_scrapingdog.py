"""
test_scrapingdog.py — Test final avec query + domain + page
Lance : python 01-scripts/test_scrapingdog.py
"""
import sys, requests, os, json
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent))
from dotenv import load_dotenv
load_dotenv(Path(__file__).parent.parent / ".env")

API_KEY = os.getenv("SCRAPINGDOG_API_KEY", "")
BASE_URL = "https://api.scrapingdog.com/amazon/search"
print(f"Clé API : OK ({len(API_KEY)} chars)\n")

# Test final : query + domain + page (différentes valeurs de page)
for page_val in [1, "1", 0, "0"]:
    params = {
        "api_key": API_KEY,
        "query": "stoïcisme",
        "domain": "amazon.fr",
        "page": page_val,
    }
    try:
        resp = requests.get(BASE_URL, params=params, timeout=20)
        raw = resp.text.strip()
        status = resp.status_code
        is_json = raw.startswith("{") or raw.startswith("[")
        print(f"page={repr(page_val)} | HTTP {status} | {'JSON ✓' if is_json else 'HTML ✗'} | {raw[:200]}")
    except Exception as e:
        print(f"page={repr(page_val)} | Erreur : {e}")
    print()
