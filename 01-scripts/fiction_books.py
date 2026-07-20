"""fiction_books.py — mappe un payload ASIN DataForSEO réel vers EnrichedBook.
Parsing PUR (aucun réseau), testé sur les fixtures live du spike M0/M1.
Les chemins de champs viennent des payloads observés, pas d'une supposition."""
import re

from pydantic import ValidationError

from models import EnrichedBook
from search_providers import _to_float, parse_bsr_rank

_SERIE_KEY = re.compile(r"^livre\s+(\d+)\s+sur\s+(\d+)$", re.I)
# amazon.fr écrit « t. 1 » (avec point) bien plus souvent que « t1 » ; et « vol » sans point
# est un mot courant en polar (« Vol 714 pour Sydney ») -> point obligatoire pour vol.
_SERIE_TITLE = re.compile(r"\b(?:tome|livre|volume)\s*\d+|\b(?:vol|t)\.\s*\d+|\bt\s*\d+|#\d+", re.I)
_BSR_KEY = "meilleures ventes"


def _series_hint_from_title(title: str) -> bool:
    """Repli heuristique quand la clé structurée « Livre N sur M » est absente."""
    return bool(_SERIE_TITLE.search(title or ""))


def _details(item: dict) -> dict:
    out: dict = {}
    pi = item.get("product_information")
    if not isinstance(pi, list):
        # forme atypique observée (dict isolé au lieu d'une liste de sections) : aucune
        # section exploitable plutôt qu'un crash.
        return out
    for sec in pi:
        if not isinstance(sec, dict):
            continue
        b = sec.get("body")
        if isinstance(b, dict):
            out.update(b)
    return out


def _text(v) -> str | None:
    """Force str(...)/None sur un champ censé être du texte : Amazon peut rendre un type
    inattendu (liste, dict) pour un détail nominalement textuel -> on caste plutôt que
    de laisser pydantic lever."""
    return None if v is None else str(v)


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
    try:
        return EnrichedBook(
            asin=asin,
            title=title,
            author=item.get("author"),
            price=_to_float(item.get("price_from")),
            reviews_count=rating.get("votes_count"),
            rating=rating.get("value"),
            bsr=rang,
            bsr_rayon=rayon,
            bsr_gratuit=gratuit,
            publication_date=_text(pick("date de publication")),
            publisher=_text(pick("diteur")),
            langue=_text(pick("langue")),
            serie_tome=tome,
            serie_total=total,
            series_hint=_series_hint_from_title(title),
            serp_position=serp_position,
        )
    except ValidationError:
        # docstring : "None si le payload est inexploitable" -> un livre atypique ne doit
        # jamais tuer le run (fetch_fiction_shelf n'a pas de filet de sécurité).
        return None
