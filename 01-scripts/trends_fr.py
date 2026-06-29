"""
trends_fr.py
------------
Collecte des tendances Google Trends France.
Retourne un dict de mots-clés avec leurs scores de tendance (30j + 12 mois).
Coût : 0 crédit Scrapingdog.
"""

import json
import time
import warnings
from datetime import datetime
from pathlib import Path

warnings.filterwarnings("ignore", category=FutureWarning)

from pytrends.request import TrendReq


BASE_DIR = Path(__file__).resolve().parent.parent
RAW_DIR = BASE_DIR / "02-veille-hebdo" / "raw-data"

# Catégories livres / sujets à surveiller pour Amazon.fr KDP
SEED_KEYWORDS = [
    # Santé / médical / bien-être (avantage pharmacien)
    "santé naturelle", "médecine douce", "microbiote intestinal", "jeûne intermittent",
    "sommeil", "stress burnout", "méditation pleine conscience", "nutrition",
    "compléments alimentaires", "pharmacologie",
    # Développement personnel
    "développement personnel", "productivité", "intelligence émotionnelle",
    "stoïcisme", "habits", "discipline",
    # Histoire / sciences
    "histoire france", "seconde guerre mondiale", "philosophie", "psychologie",
    "biographie", "neurosciences",
    # Société / culture
    "cryptomonnaie", "intelligence artificielle", "décroissance", "minimalisme",
    "finance personnelle", "investissement immobilier",
]

TIMEFRAMES = {
    "30j": "today 1-m",
    "12mois": "today 12-m",
}


def run(output_dir: Path = None) -> dict:
    """
    Lance la collecte Google Trends FR.
    Retourne un dict {keyword: {"score_30j": int, "score_12m": int, "tendance": str}}
    """
    if output_dir is None:
        date_str = datetime.now().strftime("%Y-%m-%d")
        output_dir = RAW_DIR / date_str
    output_dir.mkdir(parents=True, exist_ok=True)

    pytrends = TrendReq(hl="fr-FR", tz=60, geo="FR")

    results = {}
    errors = []

    for i in range(0, len(SEED_KEYWORDS), 5):
        batch = SEED_KEYWORDS[i: i + 5]
        for timeframe_key, timeframe_val in TIMEFRAMES.items():
            try:
                pytrends.build_payload(batch, cat=0, timeframe=timeframe_val, geo="FR")
                df = pytrends.interest_over_time()
                if df.empty:
                    continue
                for kw in batch:
                    if kw not in df.columns:
                        continue
                    score = int(df[kw].mean())
                    if kw not in results:
                        results[kw] = {"score_30j": 0, "score_12m": 0}
                    if timeframe_key == "30j":
                        results[kw]["score_30j"] = score
                    else:
                        results[kw]["score_12m"] = score
            except Exception as e:
                errors.append(f"Batch {batch} / {timeframe_key} : {e}")
                # 429 = rate limit Google Trends → pause longue avant de continuer
                if "429" in str(e):
                    print(f"[trends_fr] 429 détecté — pause 30s avant prochain batch...")
                    time.sleep(30)
        # Délai inter-batch augmenté pour éviter le 429
        time.sleep(8)

    # Calcul tendance (croissance vs stabilité vs déclin)
    for kw, data in results.items():
        s30 = data.get("score_30j", 0)
        s12 = data.get("score_12m", 0)
        if s12 == 0:
            data["tendance"] = "inconnu"
        elif s30 > s12 * 1.3:
            data["tendance"] = "montante"
        elif s30 < s12 * 0.7:
            data["tendance"] = "déclinante"
        else:
            data["tendance"] = "stable"

    # Sauvegarde JSON brut
    output = {
        "source": "google_trends_fr",
        "run_date": datetime.now().isoformat(),
        "errors": errors,
        "keywords_count": len(results),
        "data": results,
    }
    out_file = output_dir / "trends_fr.json"
    with open(out_file, "w", encoding="utf-8") as f:
        json.dump(output, f, ensure_ascii=False, indent=2)

    if errors:
        print(f"[trends_fr] ⚠️ {len(errors)} erreur(s) : {errors}")
    print(f"[trends_fr] ✓ {len(results)} mots-clés collectés → {out_file}")
    return results


if __name__ == "__main__":
    run()
