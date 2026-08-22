"""fiction_serp_provider.py — reconstitue le « rayon » d'une niche fiction.
SERP contrainte au browse node (ou à la requête si le sous-genre n'a pas de rayon),
puis enrichissement BATCHÉ des n_top premiers ASIN, avec cache inter-runs et coût mesuré."""
from fiction_books import parse_enriched_book
from fiction_taxonomy import node_for, search_param_for
from marketplace import ACTIF
from models import EnrichedBook, FictionNiche, FictionShelf
from cache import BOOK_TTL_S

# TTL IMPORTE, jamais redefini. Il l'etait ici a 7 jours pendant que cache.py
# documentait 15 : deux constantes du meme nom dans deux modules, l'une testee et
# l'autre appliquee. C'est ce qui a permis au defaut de vivre -- et au test
# d'harmonisation de passer au vert en surveillant la constante morte.


def search_param_for_niche(niche: FictionNiche, version: str = "fr_v1") -> str:
    """Contrainte de rayon : le browse node si le sous-genre en a un, sinon le filtre
    de rayon (mode « rayon requête »)."""
    node = node_for(niche.sous_genre, niche.rayon, version)
    return f"rh=n:{node}" if node else search_param_for(niche.rayon, version)


def fetch_shelf_asins(niche: FictionNiche, provider, n_top: int = 12, depth: int = 30,
                      cost=None, version: str = "fr_v1") -> tuple[str, list[str]]:
    """Moitié SERP (rapide, pas de file d'attente) : SERP contrainte au rayon -> n_top
    premiers ASIN dédupliqués. AUCUN enrichissement ici — c'est cette moitié qu'on veut
    appeler N fois (une par niche) avant de payer UNE seule fois la file ASIN via
    `enrich_asins` (cf. M6-2 : la file DataForSEO met ~250 s quel que soit le nb d'ASIN).

    n_top=12 par défaut (-40% de coût ASIN vs 20) : le signal concurrentiel de M5 (depth,
    openness, saturation_trio) est porté par les tout premiers résultats, les ASIN 13-20
    coûtent 0,024 $ chacun pour peu d'apport."""
    sp = search_param_for_niche(niche, version)
    sr = provider.search(niche.query, depth=depth, search_param=sp)
    if cost is not None:
        cost.add_dataforseo(1, getattr(provider, "priority", 2))
    # dict.fromkeys préserve l'ordre en dédupliquant : une SERP qui répète un ASIN ne doit
    # ni le facturer deux fois, ni le rendre deux fois, ni écraser sa position par la
    # DERNIÈRE occurrence au lieu de la première.
    asins = list(dict.fromkeys(o.asin for o in sr.organic if o.asin))[:n_top]
    return sp, asins


def enrich_asins(asins: list[str], provider, cache=None, cost=None,
                 progress=None) -> dict[str, EnrichedBook]:
    """Moitié « lente » (LA file DataForSEO, ~250 s quel que soit le nb d'ASIN) : batch
    ASIN unique, cache inter-runs, coût mesuré. Rend un dict {asin: EnrichedBook} qui ne
    contient QUE les ASIN effectivement enrichis — un payload absent ou inexploitable est
    simplement absent du dict, jamais une entrée factice. Cette fonction ne connaît que le
    lot qu'on lui passe : c'est à l'appelant (fetch_fiction_shelf, ou l'orchestrateur M6-2
    qui reconstruit un rayon par niche depuis la table globale) de comparer aux ASIN
    demandés PAR NICHE pour compter les échecs — comptage impossible à faire ici sans
    connaître ce découpage."""
    loc = getattr(provider, "location_code", ACTIF.location_code)
    out: dict[str, EnrichedBook] = {}
    misses: list[str] = []
    for a in asins:
        cached = cache.get_book(a, loc) if cache else None
        if cached is not None:
            out[a] = cached
        else:
            misses.append(a)

    if misses:
        raw = provider.product_raw_batch(misses)
        if cost is not None:
            cost.add_dataforseo(len(misses), getattr(provider, "priority", 2))
        n_echecs = 0
        for a in misses:
            b = parse_enriched_book(raw.get(a) or {})
            if b is not None:
                out[a] = b
                if cache:
                    cache.set_book(a, loc, b, BOOK_TTL_S)
            else:
                n_echecs += 1
        if n_echecs and progress:
            progress(f"⚠ {n_echecs}/{len(misses)} ASIN non enrichis dans ce batch "
                     f"(payload absent ou inexploitable).")
    return out


def fetch_fiction_shelf(niche: FictionNiche, provider, n_top: int = 12, depth: int = 30,
                        cache=None, cost=None, version: str = "fr_v1",
                        progress=None) -> FictionShelf:
    """Contrat M2 inchangé pour les appelants existants (tests M2, build_validation_set) :
    devient la composition de `fetch_shelf_asins` (SERP) + `enrich_asins` (la file). Rend
    un FictionShelf qui porte asins_demandes/n_echecs : un ASIN qui ne s'enrichit pas est
    COMPTÉ, jamais droppé en silence — un rayon amputé se lirait en aval comme « niche
    déserte = place à prendre », faux signal interdit par CLAUDE.md §10."""
    sp, asins = fetch_shelf_asins(niche, provider, n_top=n_top, depth=depth, cost=cost,
                                  version=version)
    enriched = enrich_asins(asins, provider, cache=cache, cost=cost)

    out: list[EnrichedBook] = []
    for i, a in enumerate(asins, 1):
        b = enriched.get(a)
        if b is not None:
            b.serp_position = i          # la position dépend du run, pas du cache
            out.append(b)

    n_echecs = len(asins) - len(out)
    if n_echecs and progress:
        progress(f"⚠ {n_echecs}/{len(asins)} ASIN non enrichis (payload absent ou "
                 f"inexploitable) — rayon incomplet, ne pas lire comme une niche déserte.")
    return FictionShelf(niche=niche, search_param=sp, books=out,
                        asins_demandes=len(asins), n_echecs=n_echecs)
