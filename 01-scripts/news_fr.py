"""
news_fr.py
----------
Collecte des signaux Google News France via RSS.
Scrape les articles récents par catégorie et extrait les mots-clés.
Coût : 0 crédit Scrapingdog.
"""

import json
import re
import time
from collections import Counter
from datetime import datetime
from pathlib import Path
from urllib.parse import quote

import feedparser

BASE_DIR = Path(__file__).resolve().parent.parent
RAW_DIR = BASE_DIR / "02-veille-hebdo" / "raw-data"

# Requêtes thématiques pour Google News FR
NEWS_QUERIES = [
    "santé bien-être",
    "nutrition alimentation",
    "psychologie développement personnel",
    "histoire france",
    "sciences découvertes",
    "société tendances",
    "finance investissement",
    "intelligence artificielle",
    "environnement écologie",
    "médecine traitement",
]

STOPWORDS_FR = {
    "le", "la", "les", "un", "une", "des", "de", "du", "en", "et", "est",
    "que", "qui", "pour", "sur", "dans", "par", "avec", "au", "aux",
    "mais", "ou", "donc", "car", "ni", "or", "pas", "plus", "se", "sa",
    "son", "ses", "mon", "ma", "mes", "tout", "tous", "bien", "très",
    "cette", "cet", "ce", "il", "elle", "ils", "elles", "nous", "vous",
    "leur", "leurs", "après", "avant", "entre", "même", "aussi", "lors",
    "plus", "moins", "comme", "fait", "faire", "être", "avoir", "depuis",
    "selon", "face", "sans", "sous", "vers", "contre", "lors", "dont",
}


def _fetch_google_news_rss(query: str, limit: int = 20) -> list[dict]:
    """Fetch via Google News RSS."""
    encoded = quote(query)
    url = f"https://news.google.com/rss/search?q={encoded}&hl=fr&gl=FR&ceid=FR:fr"
    try:
        feed = feedparser.parse(url)
        articles = []
        for entry in feed.entries[:limit]:
            articles.append({
                "title": entry.get("title", ""),
                "summary": entry.get("summary", "")[:200],
                "published": entry.get("published", ""),
                "source": entry.get("source", {}).get("title", ""),
            })
        return articles
    except Exception as e:
        print(f"[news_fr] ⚠️ Google News RSS '{query}' : {e}")
        return []


def _extract_keywords(articles: list[dict]) -> Counter:
    """Extrait les mots-clés des titres d'articles."""
    word_freq: Counter = Counter()
    for article in articles:
        title = article.get("title", "").lower()
        # Supprime la source (après " - ")
        title = title.split(" - ")[0].strip()
        words = re.findall(r"\b[a-zàâçéèêëîïôùûüæœ]{4,}\b", title)
        for w in words:
            if w not in STOPWORDS_FR:
                word_freq[w] += 1
    return word_freq


def run(output_dir: Path = None) -> dict:
    """
    Lance la collecte Google News FR.
    Retourne un dict {keyword: score_signal} (fréquence dans les titres récents)
    """
    if output_dir is None:
        date_str = datetime.now().strftime("%Y-%m-%d")
        output_dir = RAW_DIR / date_str
    output_dir.mkdir(parents=True, exist_ok=True)

    all_articles = []
    errors = []

    for query in NEWS_QUERIES:
        articles = _fetch_google_news_rss(query, limit=20)
        all_articles.extend(articles)
        time.sleep(1)

    word_freq = _extract_keywords(all_articles)
    results = {kw: count for kw, count in word_freq.most_common(60)}

    output = {
        "source": "google_news_fr",
        "run_date": datetime.now().isoformat(),
        "errors": errors,
        "articles_collected": len(all_articles),
        "keywords_count": len(results),
        "data": results,
    }
    out_file = output_dir / "news_fr.json"
    with open(out_file, "w", encoding="utf-8") as f:
        json.dump(output, f, ensure_ascii=False, indent=2)

    print(f"[news_fr] ✓ {len(results)} mots-clés extraits ({len(all_articles)} articles) → {out_file}")
    return results


if __name__ == "__main__":
    run()
