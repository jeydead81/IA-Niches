"""
amazon_autocomplete.py
----------------------
Expansion de mots-clés via Amazon.fr Autocomplete — proxifié par Scrapingdog.
Amazon bloque les appels directs (anti-bot) ; Scrapingdog contourne cette protection.

Stratégie d'appel :
  Niveau 1 : autocomplete("jeûne intermittent") + autocomplete("livre jeûne intermittent")
  Niveau 2 : autocomplete sur les suggestions du niveau 1 (expansion longue traîne)

Coût : 1 crédit Scrapingdog par requête (dynamic=false).
Estimation : ~120 crédits niveau 1 + ~50 crédits niveau 2 = ~170 crédits par scout.

Garde-fous appliqués :
  - Garde-fou 1 : plafond MAX_CREDITS_PER_RUN (via credits_tracker)
  - Garde-fou 2 : retry max 1, délai 5s
  - Garde-fou 4 : log CSV en temps réel
"""

import json
import time
from datetime import datetime
from pathlib import Path
from urllib.parse import urlencode, quote

import requests

from credits_tracker import (
    SCRAPINGDOG_API_KEY,
    MAX_RETRIES_PER_REQUEST,
    RETRY_DELAY_SECONDS,
    BudgetExceededError,
    check_budget,
    log_request,
)

BASE_DIR = Path(__file__).resolve().parent.parent
RAW_DIR = BASE_DIR / "02-veille-hebdo" / "raw-data"

SCRAPE_URL = "https://api.scrapingdog.com/scrape"
AMAZON_COMPLETE_BASE = "https://completion.amazon.fr/api/2017/suggestions"
AMAZON_MID_FR = "A13V1IB3VIYZZH"  # Marketplace ID Amazon.fr


def _build_amazon_complete_url(keyword: str) -> str:
    """Construit l'URL Amazon autocomplete à proxifier.
    Paramètre correct : prefix= (pas q=). q= retourne toujours suggestions=[].
    """
    params = urlencode({
        "mid": AMAZON_MID_FR,
        "alias": "aps",
        "prefix": keyword,
        "limit": 11,
    })
    return f"{AMAZON_COMPLETE_BASE}?{params}"


def fetch_autocomplete(keyword: str) -> list[str]:
    """
    Appelle Amazon.fr autocomplete via Scrapingdog (proxy anti-bot).
    Coût : 1 crédit.
    Retourne la liste des suggestions.
    """
    check_budget(1)

    amazon_url = _build_amazon_complete_url(keyword)
    params = {
        "api_key": SCRAPINGDOG_API_KEY,
        "url": amazon_url,
        "dynamic": "false",
    }

    for attempt in range(MAX_RETRIES_PER_REQUEST + 1):
        try:
            resp = requests.get(SCRAPE_URL, params=params, timeout=20)
            if resp.status_code == 200:
                raw = resp.text.strip()
                if not raw:
                    raise ValueError("Réponse vide")
                # Scrapingdog retourne le contenu de la page proxifiée
                # Amazon autocomplete retourne du JSON
                data = json.loads(raw)
                suggestions = [
                    s.get("value", "").strip()
                    for s in data.get("suggestions", [])
                    if s.get("value", "").strip()
                ]
                log_request("autocomplete_proxy", keyword, 1, True)
                return suggestions
            else:
                err_preview = resp.text[:100] if resp.text else "vide"
                print(f"[autocomplete] HTTP {resp.status_code} pour '{keyword}' : {err_preview}")
                if attempt < MAX_RETRIES_PER_REQUEST:
                    time.sleep(RETRY_DELAY_SECONDS)
        except (json.JSONDecodeError, ValueError) as e:
            print(f"[autocomplete] Parsing '{keyword}' (tentative {attempt+1}) : {e}")
            if attempt < MAX_RETRIES_PER_REQUEST:
                time.sleep(RETRY_DELAY_SECONDS)
        except requests.RequestException as e:
            print(f"[autocomplete] Réseau '{keyword}' (tentative {attempt+1}) : {e}")
            if attempt < MAX_RETRIES_PER_REQUEST:
                time.sleep(RETRY_DELAY_SECONDS)

    log_request("autocomplete_proxy", keyword, 1, False)
    return []


def run(seeds: list[str], output_dir: Path = None, expand_level2: bool = True) -> dict:
    """
    Lance l'autocomplete sur une liste de seeds.
    Pour chaque seed, fait deux appels : seed seul + "livre [seed]".
    Si expand_level2=True, fait un 2ème niveau d'expansion sur les suggestions.

    Retourne un dict :
    {
      "seed": {
        "direct": ["suggestion1", ...],
        "livre": ["livre suggestion1", ...],
        "level2": ["suggestion longue traîne", ...]
      }
    }
    """
    if output_dir is None:
        date_str = datetime.now().strftime("%Y-%m-%d")
        output_dir = RAW_DIR / date_str
    output_dir.mkdir(parents=True, exist_ok=True)

    # ── Reprise automatique : charger les seeds déjà traités ──────────────────
    # Si un JSON partiel existe pour aujourd'hui, on reprend là où on s'est arrêté.
    # Seuls les seeds absents du JSON sont relancés → 0 crédit gaspillé.
    out_file = output_dir / "amazon_autocomplete.json"
    results = {}
    errors = []
    stopped_early = False
    total_suggestions = 0

    if out_file.exists():
        try:
            with open(out_file, "r", encoding="utf-8") as f:
                existing = json.load(f)
            already_done = existing.get("data", {})
            results = dict(already_done)
            total_suggestions = existing.get("total_suggestions", 0)
            skipped = [s for s in seeds if s in results]
            seeds = [s for s in seeds if s not in results]
            if skipped:
                print(f"[autocomplete] ↩ Reprise : {len(skipped)} seeds déjà traités chargés, "
                      f"{len(seeds)} seeds restants à traiter")
        except Exception as e:
            print(f"[autocomplete] ⚠️ Impossible de charger le JSON existant : {e} — relance complète")
            results = {}
            total_suggestions = 0

    for seed in seeds:
        seed_results = {"direct": [], "livre": [], "level2": []}

        # ── Niveau 1a : seed direct ──────────────────────────────────────────
        try:
            direct = fetch_autocomplete(seed)
            seed_results["direct"] = direct
            total_suggestions += len(direct)
            time.sleep(0.5)
        except BudgetExceededError as e:
            print(f"[autocomplete] 🛑 {e}")
            errors.append(str(e))
            stopped_early = True
            break

        # ── Niveau 1b : "livre [seed]" ───────────────────────────────────────
        try:
            livre = fetch_autocomplete(f"livre {seed}")
            seed_results["livre"] = livre
            total_suggestions += len(livre)
            time.sleep(0.5)
        except BudgetExceededError as e:
            print(f"[autocomplete] 🛑 {e}")
            errors.append(str(e))
            stopped_early = True
            results[seed] = seed_results
            break

        # ── Niveau 2 : expansion des suggestions niveau 1 ───────────────────
        if expand_level2 and not stopped_early:
            # Prendre les suggestions multi-mots du niveau 1 (candidates à expansion)
            l1_candidates = list(set(direct + livre))
            # Filtrer : au moins 2 mots, pas trop long, pas identique au seed
            l1_to_expand = [
                s for s in l1_candidates
                if len(s.split()) >= 2
                and s.lower() != seed.lower()
                and len(s) < 50
            ][:4]  # max 4 expansions niveau 2 par seed (limite de crédits)

            level2 = []
            for suggestion in l1_to_expand:
                try:
                    l2 = fetch_autocomplete(suggestion)
                    level2.extend(l2)
                    time.sleep(0.4)
                except BudgetExceededError as e:
                    print(f"[autocomplete] 🛑 {e}")
                    errors.append(str(e))
                    stopped_early = True
                    break

            seed_results["level2"] = list(set(level2))
            total_suggestions += len(seed_results["level2"])

        results[seed] = seed_results

        if stopped_early:
            break

    # ── Sauvegarde JSON ──────────────────────────────────────────────────────
    output = {
        "source": "amazon_autocomplete_fr_via_scrapingdog",
        "run_date": datetime.now().isoformat(),
        "seeds_queried": len(results),
        "total_suggestions": total_suggestions,
        "stopped_early": stopped_early,
        "errors": errors,
        "data": results,
    }
    with open(out_file, "w", encoding="utf-8") as f:
        json.dump(output, f, ensure_ascii=False, indent=2)

    print(f"[autocomplete] ✓ {len(results)} seeds total → {total_suggestions} suggestions → {out_file}")
    if stopped_early:
        print("[autocomplete] ⚠️ Arrêt anticipé — plafond crédits atteint")
    return results


def flatten_suggestions(results: dict) -> dict[str, int]:
    """
    Aplatit le dict résultat en {expression: score}.
    Les expressions niveau 2 (longue traîne) ont un score plus élevé
    car elles sont plus spécifiques = meilleure niche potentielle.
    """
    flat = {}
    for seed, data in results.items():
        for s in data.get("direct", []):
            flat[s] = flat.get(s, 0) + 8
        for s in data.get("livre", []):
            flat[s] = flat.get(s, 0) + 10  # bonus : requête avec "livre" = intention achat
        for s in data.get("level2", []):
            flat[s] = flat.get(s, 0) + 12  # bonus max : longue traîne = niche précise
    return flat


if __name__ == "__main__":
    test_seeds = ["jeûne intermittent", "santé mentale", "stoïcisme"]
    r = run(test_seeds, expand_level2=True)
    flat = flatten_suggestions(r)
    print(f"\nTop suggestions :")
    for expr, score in sorted(flat.items(), key=lambda x: x[1], reverse=True)[:15]:
        print(f"  {score:3} — {expr}")
