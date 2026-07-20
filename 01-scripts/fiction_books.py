"""fiction_books.py — mappe un payload ASIN DataForSEO réel vers EnrichedBook.
Parsing PUR (aucun réseau), testé sur les fixtures live du spike M0/M1.
Les chemins de champs viennent des payloads observés, pas d'une supposition."""
import re

from models import EnrichedBook
from search_providers import parse_bsr_rank

_SERIE_KEY = re.compile(r"^livre\s+(\d+)\s+sur\s+(\d+)$", re.I)
_SERIE_TITLE = re.compile(r"\b(?:tome|livre|vol\.?|t)\s*\d+|#\d+", re.I)
_BSR_KEY = "meilleures ventes"


def _series_hint_from_title(title: str) -> bool:
    """Repli heuristique quand la clé structurée « Livre N sur M » est absente."""
    return bool(_SERIE_TITLE.search(title or ""))


def _details(item: dict) -> dict:
    out: dict = {}
    for sec in (item.get("product_information") or []):
        b = sec.get("body")
        if isinstance(b, dict):
            out.update(b)
    return out


def parse_enriched_book(result: dict, serp_position: int = 0) -> EnrichedBook | None:
    """Payload ASIN (advanced) -> EnrichedBook. None si le payload est inexploitable."""
    items = (result or {}).get("items") or []
    item = next((it for it in items if it.get("type") == "amazon_product_info"),
                items[0] if items else None)
    if not item:
        return None
    asin = (result or {}).get("asin") or item.get("data_asin")
    if not asin:
        return None
    det = _details(item)
    low = {k.lower(): (k, v) for k, v in det.items()}

    def pick(frag: str):
        for kl, (k, v) in low.items():
            if frag in kl:
                return v
        return None

    rang = rayon = None
    gratuit = False
    bsr_raw = pick(_BSR_KEY)
    if isinstance(bsr_raw, str):
        rang, rayon, gratuit = parse_bsr_rank(bsr_raw)

    tome = total = None
    for k in det:
        m = _SERIE_KEY.match(k.strip())
        if m:
            tome, total = int(m.group(1)), int(m.group(2))
            break

    rating = item.get("rating") if isinstance(item.get("rating"), dict) else {}
    title = item.get("title") or ""
    return EnrichedBook(
        asin=asin,
        title=title,
        author=item.get("author"),
        price=item.get("price_from"),
        reviews_count=rating.get("votes_count"),
        rating=rating.get("value"),
        bsr=rang,
        bsr_rayon=rayon,
        bsr_gratuit=gratuit,
        publication_date=pick("date de publication"),
        publisher=pick("diteur"),
        langue=pick("langue"),
        serie_tome=tome,
        serie_total=total,
        series_hint=_series_hint_from_title(title),
        serp_position=serp_position,
    )
