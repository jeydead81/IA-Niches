"""bsr_source.py — résout le BSR d'une liste d'ASIN, avec dédup + cache + choix de source.
Source (env BSR_SOURCE) : 'scrape' (gratuit, IP résidentielle, défaut local) ou 'dataforseo'
(batché, fiable, serveur). fetch_bsr_fn injectable (tests hors-ligne + fallback scrape par ASIN)."""
import os
import time

from amazon_product import fetch_bsr as _scrape_bsr

BSR_TTL_S = 3 * 24 * 3600      # 3 jours : le classement bouge, mais réutilisable court terme


def resolve_bsrs(asins, *, source=None, provider=None, fetch_bsr_fn=None, cache=None,
                 location: int = 2250, bsr_priority: int = 2, cost=None,
                 bsr_pause: float = 0.4) -> dict:
    """Retour : {asin: BsrInfo|None}. Dédup, cache (par ASIN), et comptage coût pour DataForSEO."""
    uniq = list(dict.fromkeys(a for a in asins if a))
    out: dict = {}
    misses: list[str] = []
    for a in uniq:
        c = cache.get_bsr(a, location) if cache else None
        if c is not None:
            out[a] = c
        else:
            misses.append(a)

    if misses:
        source = source or os.getenv("BSR_SOURCE", "scrape")
        if fetch_bsr_fn is not None or source == "scrape":
            fn = fetch_bsr_fn or _scrape_bsr
            for a in misses:
                out[a] = fn(a)
                if bsr_pause and fetch_bsr_fn is None:
                    time.sleep(bsr_pause)
        elif source == "dataforseo":
            if provider is None:
                raise ValueError("source=dataforseo requiert un provider")
            batch = provider.product_info_batch(misses)
            out.update(batch)
            if cost is not None:
                cost.add_dataforseo(len(misses), getattr(provider, "priority", bsr_priority))
        else:
            raise ValueError(f"BSR_SOURCE inconnu : {source}")

        if cache:
            for a in misses:
                if out.get(a) is not None:
                    cache.set_bsr(a, location, out[a], BSR_TTL_S)
    return out
