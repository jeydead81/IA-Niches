"""
reddit_fr.py
------------
Collecte des signaux Reddit France.
Mode dégradé actif (RSS public) — pas besoin de client_id / client_secret.
Si les credentials Reddit sont présents dans .env, bascule en mode API complet (plus de données).
Coût : 0 crédit Scrapingdog.
"""

import json
import os
import time
from datetime import datetime
from pathlib import Path

import feedparser
import requests
from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent.parent
RAW_DIR = BASE_DIR / "02-veille-hebdo" / "raw-data"
load_dotenv(BASE_DIR / ".env")

REDDIT_CLIENT_ID = os.getenv("REDDIT_CLIENT_ID", "")
REDDIT_CLIENT_SECRET = os.getenv("REDDIT_CLIENT_SECRET", "")
REDDIT_USER_AGENT = os.getenv("REDDIT_USER_AGENT", "kdp-scout/1.0")

# Subreddits FR confirmés actifs avec RSS public
# Vérifiés : flux RSS accessible et contenu en français
SUBREDDITS_FR = [
    "france",               # ~2M membres, actualité générale FR
    "HistoireFrance",       # Histoire France
    "psychologie",          # Psychologie FR
    "developpementpersonnel",  # Dev perso FR
    "finances_perso",       # Finance personnelle FR
    "philosophie",          # Philosophie FR (contenu FR et EN mélangé)
    "livres",               # Livres FR
    "sante",                # Santé FR
]

SUBREDDITS_EN = []  # supprimés — génèrent des mots-clés anglais inutiles


def _fetch_rss(subreddit: str, limit: int = 25) -> list[dict]:
    """Fetch via flux RSS public (mode dégradé)."""
    url = f"https://www.reddit.com/r/{subreddit}/hot.rss?limit={limit}"
    try:
        feed = feedparser.parse(url)
        posts = []
        for entry in feed.entries[:limit]:
            posts.append({
                "title": entry.get("title", ""),
                "summary": entry.get("summary", "")[:300],
                "link": entry.get("link", ""),
                "published": entry.get("published", ""),
            })
        return posts
    except Exception as e:
        print(f"[reddit_fr] ⚠️ RSS {subreddit} : {e}")
        return []


def _fetch_api(subreddit: str, limit: int = 25) -> list[dict]:
    """Fetch via API Reddit officielle (mode complet si credentials dispo)."""
    try:
        import praw
        reddit = praw.Reddit(
            client_id=REDDIT_CLIENT_ID,
            client_secret=REDDIT_CLIENT_SECRET,
            user_agent=REDDIT_USER_AGENT,
        )
        sub = reddit.subreddit(subreddit)
        posts = []
        for post in sub.hot(limit=limit):
            posts.append({
                "title": post.title,
                "score": post.score,
                "num_comments": post.num_comments,
                "url": post.url,
                "created_utc": post.created_utc,
            })
        return posts
    except Exception as e:
        print(f"[reddit_fr] ⚠️ API {subreddit} : {e}")
        return []


def _extract_keywords_from_posts(posts: list[dict]) -> list[str]:
    """Extrait les mots-clés pertinents des titres de posts — français uniquement."""
    from collections import Counter
    import re

    stopwords_fr = {
        "le", "la", "les", "un", "une", "des", "de", "du", "en", "et", "est",
        "que", "qui", "pour", "sur", "dans", "par", "avec", "je", "tu", "il",
        "elle", "nous", "vous", "ils", "elles", "mais", "ou", "donc", "car",
        "ni", "pas", "plus", "se", "sa", "son", "ses", "mon", "ma", "mes",
        "tout", "tous", "bien", "très", "cette", "cet", "ce", "leur", "leurs",
        "après", "avant", "même", "aussi", "lors", "comme", "fait", "faire",
        "être", "avoir", "depuis", "selon", "face", "sans", "sous", "vers",
        "contre", "dont", "comment", "quand", "quel", "quelle", "quels",
        "quelques", "entre", "chez", "autre", "autres", "alors", "déjà",
        "encore", "toujours", "jamais", "peut", "faut", "doit", "veux", "font",
    }

    # Mots anglais courants à exclure explicitement (pollution Reddit EN)
    english_common = {
        "from", "that", "this", "with", "have", "they", "been", "will", "when",
        "what", "your", "here", "there", "some", "more", "also", "just", "like",
        "than", "then", "them", "their", "into", "about", "would", "could",
        "should", "over", "time", "back", "only", "make", "know", "need",
        "even", "well", "much", "many", "very", "most", "long", "good", "does",
        "think", "still", "look", "want", "come", "year", "years", "people",
        "life", "work", "study", "best", "help", "feel", "find", "take", "last",
        "first", "each", "same", "high", "open", "next", "keep", "left", "move",
        "live", "give", "post", "line", "used", "word", "part", "down", "side",
        "free", "real", "full", "away", "came", "show", "mean", "hand", "both",
        "news", "read", "body", "stop", "done", "tell", "game", "love", "sure",
        "less", "hold", "true", "ever", "able", "days", "look", "book", "data",
        "reddit", "thread", "comment", "comments", "upvotes", "karma",
    }

    # Détection heuristique du français : au moins un accent ou un mot de liaison FR commun
    fr_markers = {"est", "les", "des", "pas", "dans", "pour", "avec", "sur", "qui",
                  "que", "une", "son", "ses", "mais", "très", "tout", "aussi"}

    word_freq: Counter = Counter()
    for post in posts:
        title = post.get("title", "").lower()
        words_in_title = set(re.findall(r"\b[a-z]{2,}\b", title))
        has_accents = bool(re.search(r"[àâçéèêëîïôùûüæœ]", title))
        is_probably_french = has_accents or bool(words_in_title & fr_markers)

        if not is_probably_french:
            continue  # Skip les posts anglais

        words = re.findall(r"\b[a-zàâçéèêëîïôùûüæœ]{4,}\b", title)
        for w in words:
            if w not in stopwords_fr and w not in english_common:
                word_freq[w] += 1

    return [kw for kw, _ in word_freq.most_common(50)]


def run(output_dir: Path = None) -> dict:
    """
    Lance la collecte Reddit FR (mode dégradé RSS ou mode API si credentials dispo).
    Retourne un dict {keyword: score_signal}
    """
    if output_dir is None:
        date_str = datetime.now().strftime("%Y-%m-%d")
        output_dir = RAW_DIR / date_str
    output_dir.mkdir(parents=True, exist_ok=True)

    use_api = bool(REDDIT_CLIENT_ID and REDDIT_CLIENT_SECRET)
    mode = "API officielle" if use_api else "RSS dégradé"
    print(f"[reddit_fr] Mode : {mode}")

    all_posts = []
    errors = []
    subs = SUBREDDITS_FR + SUBREDDITS_EN

    for sub in subs:
        if use_api:
            posts = _fetch_api(sub, limit=20)
        else:
            posts = _fetch_rss(sub, limit=20)
        all_posts.extend(posts)
        time.sleep(1)  # respect rate limit Reddit

    keywords = _extract_keywords_from_posts(all_posts)

    # Score simple : rang dans le top 50
    results = {kw: max(1, 50 - i) for i, kw in enumerate(keywords)}

    output = {
        "source": "reddit_fr",
        "mode": mode,
        "run_date": datetime.now().isoformat(),
        "errors": errors,
        "posts_collected": len(all_posts),
        "keywords_count": len(results),
        "data": results,
    }
    out_file = output_dir / "reddit_fr.json"
    with open(out_file, "w", encoding="utf-8") as f:
        json.dump(output, f, ensure_ascii=False, indent=2)

    print(f"[reddit_fr] ✓ {len(results)} mots-clés extraits ({len(all_posts)} posts) → {out_file}")
    if not use_api:
        print("[reddit_fr] ⚠️ Mode RSS dégradé — données limitées (pas de score/commentaires)")
    return results


if __name__ == "__main__":
    run()
