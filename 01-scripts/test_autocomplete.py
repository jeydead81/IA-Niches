"""
test_autocomplete.py — Test Google Suggest comme remplacement autocomplete Amazon
Lance : python 01-scripts/test_autocomplete.py
"""
import sys, requests, time, json
from pathlib import Path
from urllib.parse import quote_plus
sys.path.insert(0, str(Path(__file__).parent))

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
    "Accept-Language": "fr-FR,fr;q=0.9",
}

def google_suggest(query: str) -> list[str]:
    """API Google Suggest — gratuite, pas de cookies, pas de blocage."""
    url = "https://suggestqueries.google.com/complete/search"
    params = {"output": "firefox", "q": query, "hl": "fr", "gl": "fr", "client": "firefox"}
    try:
        r = requests.get(url, params=params, headers=HEADERS, timeout=8)
        if r.status_code == 200:
            data = json.loads(r.text)
            # Format : ["requête", ["suggestion1", "suggestion2", ...]]
            return data[1] if len(data) > 1 else []
    except Exception as e:
        print(f"  Erreur : {e}")
    return []

SEEDS = [
    "jeûne intermittent",
    "santé mentale",
    "stoïcisme",
    "magie blanche",
    "microbiote intestinal",
    "guérir enfant intérieur",
    "médecine naturelle",
    "liberté financière",
]

print("=" * 60)
print("TEST 1 — Google Suggest sans préfixe")
print("=" * 60)
for seed in SEEDS:
    sugg = google_suggest(seed)
    print(f"  '{seed}' → {sugg[:4]}")
    time.sleep(0.3)

print()
print("=" * 60)
print("TEST 2 — Google Suggest avec préfixe 'livre'")
print("=" * 60)
for seed in SEEDS:
    sugg = google_suggest(f"livre {seed}")
    print(f"  'livre {seed}' → {sugg[:4]}")
    time.sleep(0.3)

print()
print("=" * 60)
print("TEST 3 — Expansion niveau 2 sur les suggestions 'livre'")
print("=" * 60)
seed_l1 = "santé mentale"
l1 = google_suggest(f"livre {seed_l1}")
print(f"Niveau 1 'livre {seed_l1}' : {l1}")
print(f"\nNiveau 2 — expansion de chaque suggestion :")
for s in l1[:5]:
    l2 = google_suggest(s)
    if l2:
        print(f"  '{s}' → {l2[:3]}")
    time.sleep(0.4)
