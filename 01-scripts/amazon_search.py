"""
amazon_search.py
----------------
Analyse concurrentielle approfondie via Amazon.fr Search (Scrapingdog API).
Priorité 2 : utilisé UNIQUEMENT sur les 10-20 niches finalistes.
Extrait BSR, prix, reviews, sponsorisés, etc.

Garde-fous appliqués :
- Garde-fou 1 : plafond MAX_CREDITS_PER_RUN (via credits_tracker)
- Garde-fou 2 : retry max 1, délai 5s
- Garde-fou 4 : log CSV en temps réel
"""

import json
import re
import time
from datetime import datetime
from pathlib import Path

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

# URL correcte Scrapingdog pour Amazon search (paramètre type=search)
SEARCH_URL = "https://api.scrapingdog.com/amazon"


def _is_sponsored(product: dict) -> bool:
    """
    Détecte si un produit est sponsorisé.
    Vérifie le champ is_sponsored, puis cherche dans les labels.
    """
    if product.get("is_sponsored") is True:
        return True
    sponsored_label = str(product.get("sponsored_label", "")).lower()
    if "sponsor" in sponsored_label:
        return True
    badge = str(product.get("badge", "")).lower()
    if "sponsor" in badge:
        return True
    return False


def _parse_bsr(bsr_raw) -> int | None:
    """Extrait le BSR numérique depuis une chaîne ou un entier."""
    if bsr_raw is None:
        return None
    if isinstance(bsr_raw, int):
        return bsr_raw
    # Ex : "#1,234 in Livres" → 1234
    match = re.search(r"[\d,]+", str(bsr_raw).replace("\xa0", ""))
    if match:
        return int(match.group().replace(",", "").replace(" ", ""))
    return None


def fetch_search(keyword: str, page: int = 1) -> dict:
    """
    Appelle Amazon.fr search via Scrapingdog.
    Retourne un dict avec listes 'organic' et 'sponsored'.
    Coût : 1 crédit.
    """
    check_budget(1)

    params = {
        "api_key": SCRAPINGDOG_API_KEY,
        "domain": "amazon.fr",
        "query": keyword,
        "page": page,
        "type": "search",
    }

    for attempt in range(MAX_RETRIES_PER_REQUEST + 1):
        try:
            resp = requests.get(SEARCH_URL, params=params, timeout=30)
            if resp.status_code == 200:
                # Debug : afficher les premiers caractères si la réponse semble vide
                raw = resp.text.strip()
                if not raw:
                    raise ValueError("Réponse vide de Scrapingdog")
                if not raw.startswith("{") and not raw.startswith("["):
                    print(f"[search] ⚠️ Réponse non-JSON pour '{keyword}' : {raw[:200]}")
                    raise ValueError(f"Réponse non-JSON : {raw[:100]}")
                data = resp.json()
                log_request("search", keyword, 1, True)

                # Normalisation des résultats
                products = data.get("products", data.get("results", []))
                organic = []
                sponsored = []

                for i, p in enumerate(products):
                    item = {
                        "position": i + 1,
                        "title": p.get("title", p.get("name", "")),
                        "author": p.get("author", p.get("brand", "")),
                        "price": p.get("price", p.get("current_price", "")),
                        "rating": p.get("rating", p.get("stars", "")),
                        "reviews_count": p.get("reviews_count", p.get("reviews", 0)),
                        "bsr_raw": p.get("bestseller_rank", p.get("bsr", "")),
                        "bsr": _parse_bsr(p.get("bestseller_rank", p.get("bsr", ""))),
                        "pages": p.get("pages", ""),
                        "date": p.get("date", p.get("publication_date", "")),
                        "badge": p.get("badge", ""),
                        "asin": p.get("asin", ""),
                        "url": p.get("url", p.get("product_url", "")),
                        "is_sponsored_raw": p.get("is_sponsored", False),
                    }
                    if _is_sponsored(p):
                        item["sponsored_reason"] = "badge/field"
                        sponsored.append(item)
                    else:
                        organic.append(item)

                return {
                    "keyword": keyword,
                    "total_results": data.get("total_results", data.get("results_count", "")),
                    "organic": organic,
                    "sponsored": sponsored,
                    "organic_count": len(organic),
                    "sponsored_count": len(sponsored),
                }
            else:
                print(f"[search] HTTP {resp.status_code} pour '{keyword}' (tentative {attempt+1})")
                if attempt < MAX_RETRIES_PER_REQUEST:
                    time.sleep(RETRY_DELAY_SECONDS)
        except requests.RequestException as e:
            print(f"[search] Erreur réseau '{keyword}' (tentative {attempt+1}) : {e}")
            if attempt < MAX_RETRIES_PER_REQUEST:
                time.sleep(RETRY_DELAY_SECONDS)
        except (ValueError, Exception) as e:
            print(f"[search] Erreur parsing '{keyword}' (tentative {attempt+1}) : {e}")
            if attempt < MAX_RETRIES_PER_REQUEST:
                time.sleep(RETRY_DELAY_SECONDS)

    log_request("search", keyword, 1, False)
    return {"keyword": keyword, "organic": [], "sponsored": [], "error": "Echec après retries"}


def compute_bsr_stats(organic_results: list[dict]) -> dict:
    """
    Calcule les statistiques BSR sur les résultats organiques.
    Applique les critères Baptiste (section 4.1).
    """
    bsr_values = [p["bsr"] for p in organic_results if p.get("bsr") is not None]
    if not bsr_values:
        return {"bsr_list": [], "bsr_top5_avg": None, "bsr_best": None, "bsr_worst_top10": None, "criteres_ok": False}

    top5_bsr = sorted(bsr_values)[:5]
    top10_bsr = sorted(bsr_values)[:10]

    bsr_best = min(bsr_values)
    bsr_top5_avg = int(sum(top5_bsr) / len(top5_bsr))
    bsr_worst_top10 = max(top10_bsr) if top10_bsr else None

    # Critères Baptiste (section 4.1)
    crit_1 = bsr_best < 10_000
    crit_2 = bsr_top5_avg < 50_000
    crit_3 = bsr_worst_top10 is not None and bsr_worst_top10 > 50_000

    return {
        "bsr_list": bsr_values,
        "bsr_top5_avg": bsr_top5_avg,
        "bsr_best": bsr_best,
        "bsr_worst_top10": bsr_worst_top10,
        "critere_1_best_lt_10k": crit_1,
        "critere_2_top5_avg_lt_50k": crit_2,
        "critere_3_worst_gt_50k": crit_3,
        "criteres_ok": crit_1 and crit_2 and crit_3,
    }


def run(keywords: list[str], output_dir: Path = None) -> dict:
    """
    Lance l'analyse search pour les mots-clés finalistes.
    Retourne dict {keyword: {organic, sponsored, bsr_stats}}.
    """
    if output_dir is None:
        date_str = datetime.now().strftime("%Y-%m-%d")
        output_dir = RAW_DIR / date_str
    output_dir.mkdir(parents=True, exist_ok=True)

    results = {}
    errors = []
    stopped_early = False

    for kw in keywords:
        try:
            search_data = fetch_search(kw)
            search_data["bsr_stats"] = compute_bsr_stats(search_data.get("organic", []))
            results[kw] = search_data
            time.sleep(1)
        except BudgetExceededError as e:
            print(f"[search] 🛑 {e}")
            errors.append(str(e))
            stopped_early = True
            break
        except Exception as e:
            errors.append(f"{kw} : {e}")

    output = {
        "source": "amazon_search_fr",
        "run_date": datetime.now().isoformat(),
        "keywords_queried": len(results),
        "stopped_early": stopped_early,
        "errors": errors,
        "data": results,
    }
    out_file = output_dir / "amazon_search.json"
    with open(out_file, "w", encoding="utf-8") as f:
        json.dump(output, f, ensure_ascii=False, indent=2)

    print(f"[search] ✓ {len(results)}/{len(keywords)} niches analysées → {out_file}")
    if stopped_early:
        print("[search] ⚠️ Plafond crédits atteint — rapport partiel généré")
    return results


if __name__ == "__main__":
    test_kws = ["stoïcisme livre", "jeûne intermittent guide"]
    run(test_kws)
