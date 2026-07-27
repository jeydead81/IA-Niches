"""fiction_serp_provider.py — reconstitue le « rayon » d'une niche fiction.
SERP contrainte au browse node (ou à la requête si le sous-genre n'a pas de rayon),
puis enrichissement BATCHÉ des n_top premiers ASIN, avec cache inter-runs et coût mesuré."""
from fiction_books import parse_enriched_book
from fiction_taxonomy import node_for, search_param_for
from models import EnrichedBook, FictionNiche, FictionShelf

BOOK_TTL_S = 7 * 24 * 3600


def search_param_for_niche(niche: FictionNiche, version: str = "fr_v1") -> str:
    """Contrainte de rayon : le browse node si le sous-genre en a un, sinon le filtre
    de rayon (mode « rayon requête »)."""
    node = node_for(niche.sous_genre, niche.rayon, version)
    return f"rh=n:{node}" if node else search_param_for(niche.rayon, version)


def fetch_fiction_shelf(niche: FictionNiche, provider, n_top: int = 12, depth: int = 30,
                        cache=None, cost=None, version: str = "fr_v1",
                        progress=None) -> FictionShelf:
    """SERP contrainte -> n_top premiers ASIN (dédupliqués) -> EnrichedBook (cache + coût).
    Rend un FictionShelf qui porte asins_demandes/n_echecs : un ASIN qui ne s'enrichit pas
    est COMPTÉ, jamais droppé en silence — un rayon amputé se lirait en aval comme « niche
    déserte = place à prendre », faux signal interdit par CLAUDE.md §10.

    n_top=12 par défaut (-40% de coût ASIN vs 20) : le signal concurrentiel de M5 (depth,
    openness, saturation_trio) est porté par les tout premiers résultats, les ASIN 13-20
    coûtent 0,024 $ chacun pour peu d'apport. Compromis assumé : `price_band` et
    `series_share` deviennent plus bruités sur 12 livres que sur 20 (échantillon plus
    petit) — passer `n_top=20` niche par niche si ce bruit devient gênant."""
    sp = search_param_for_niche(niche, version)
    sr = provider.search(niche.query, depth=depth, search_param=sp)
    if cost is not None:
        cost.add_dataforseo(1, getattr(provider, "priority", 2))
    # dict.fromkeys préserve l'ordre en dédupliquant : une SERP qui répète un ASIN ne doit
    # ni le facturer deux fois, ni le rendre deux fois, ni écraser sa position par la
    # DERNIÈRE occurrence au lieu de la première.
    asins = list(dict.fromkeys(o.asin for o in sr.organic if o.asin))[:n_top]
    loc = getattr(provider, "location_code", 2250)

    books: dict = {}
    misses: list[str] = []
    for a in asins:
        cached = cache.get_book(a, loc) if cache else None
        if cached is not None:
            books[a] = cached
        else:
            misses.append(a)

    if misses:
        raw = provider.product_raw_batch(misses)
        if cost is not None:
            cost.add_dataforseo(len(misses), getattr(provider, "priority", 2))
        for a in misses:
            b = parse_enriched_book(raw.get(a) or {})
            if b is not None:
                books[a] = b
                if cache:
                    cache.set_book(a, loc, b, BOOK_TTL_S)

    out: list[EnrichedBook] = []
    for i, a in enumerate(asins, 1):
        b = books.get(a)
        if b is not None:
            b.serp_position = i          # la position dépend du run, pas du cache
            out.append(b)

    n_echecs = len(asins) - len(out)
    if n_echecs and progress:
        progress(f"⚠ {n_echecs}/{len(asins)} ASIN non enrichis (payload absent ou "
                 f"inexploitable) — rayon incomplet, ne pas lire comme une niche déserte.")
    return FictionShelf(niche=niche, search_param=sp, books=out,
                        asins_demandes=len(asins), n_echecs=n_echecs)
