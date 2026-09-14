"""fiction_books.py — mappe un payload ASIN DataForSEO réel vers EnrichedBook.
Parsing PUR (aucun réseau), testé sur les fixtures live du spike M0/M1.
Les chemins de champs viennent des payloads observés, pas d'une supposition."""
import re

from pydantic import ValidationError

from models import EnrichedBook
from search_providers import _bsr_to_int, _to_float, parse_bsr_rank

_SERIE_KEY = re.compile(r"^livre\s+(\d+)\s+sur\s+(\d+)$", re.I)
# amazon.fr écrit « t. 1 » (avec point) bien plus souvent que « t1 » ; et « vol » sans point
# est un mot courant en polar (« Vol 714 pour Sydney ») -> point obligatoire pour vol.
_SERIE_TITLE = re.compile(r"\b(?:tome|livre|volume)\s*\d+|\b(?:vol|t)\.\s*\d+|\bt\s*\d+|#\d+", re.I)
# clé FR observée en majorité, "best sellers rank" en repli (parse_asin_bsr accepte déjà les deux)
_BSR_KEY = ("meilleures ventes", "best sellers rank")
# sous-catégorie : "RANG en CATÉGORIE", une par ligne, APRÈS la parenthèse fermante du rang
# principal. Le "(Livres)" qui qualifie parfois la catégorie (ex. "Jeux (Livres)") fait
# partie du libellé Amazon -> on ne s'arrête pas au premier "(".
# Pagination : amazon.fr l'ecrit sous « Nombre de pages de l'edition imprimee » :
# "335 pages" (8 captures sur 8, v2 du 2026-07-20, ebook Kindle compris). Le fragment
# "nombre de pages" n'a ni accent ni apostrophe, et « Page Flip » (Kindle) ne le capte pas.
# Une cle de FORMAT {"Broche": "120 pages"} n'a JAMAIS ete observee : elle venait d'une
# fixture fabriquee, et le parseur ecrit pour elle a rendu pages=None sur 185 fiches payees.
# Elle reste un simple repli. Separateurs de milliers francais (espace fine incluse).
_PAGES = re.compile(r"([\d][\d\s  .]*)\s*pages?", re.I)
_CLE_PAGES = "nombre de pages"
_FORMATS_PAPIER = ("broch", "reli", "poche", "album", "cartonn")


_SUBCAT_LINE = re.compile(r"^\s*([\d][\d\s.]*)\s*en\s+(.+?)\s*$")


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


def _parse_subcats(raw: str) -> list[dict]:
    """Sous-catégories BSR situées après la parenthèse fermante du rang principal (ex.
    « 1 597 en Livres ( Voir les 100 premiers en Livres )  6 en Enquêtes et humour » ->
    [{"rang": 6, "categorie": "Enquêtes et humour"}]). Une ligne qui ne matche pas le
    format attendu est ignorée plutôt que de produire une donnée douteuse ; si rien ne
    matche, on rend une liste vide."""
    if not isinstance(raw, str) or ")" not in raw:
        return []
    tail = raw.split(")", 1)[1]
    out: list[dict] = []
    for line in tail.split("\n"):
        m = _SUBCAT_LINE.match(line)
        if not m:
            continue
        rang = _bsr_to_int(m.group(1))
        categorie = m.group(2).strip(" .,;:")
        if rang and categorie:
            out.append({"rang": rang, "categorie": categorie})
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

    def pick(frag):
        fragments = (frag,) if isinstance(frag, str) else tuple(frag)
        for kl, (k, v) in low.items():
            if any(f in kl for f in fragments):
                return v
        return None

    rang = rayon = None
    gratuit = False
    subcats: list[dict] = []
    bsr_raw = pick(_BSR_KEY)
    if isinstance(bsr_raw, str):
        rang, rayon, gratuit = parse_bsr_rank(bsr_raw)
        subcats = _parse_subcats(bsr_raw)

    tome = total = None
    for k in det:
        m = _SERIE_KEY.match(k.strip())
        if m:
            tome, total = int(m.group(1)), int(m.group(2))
            break

    def _nb_pages(v) -> int | None:
        m = _PAGES.search(str(v or ""))
        return _bsr_to_int(m.group(1)) if m else None    # separateurs de milliers FR

    # Sur un ebook, c'est la pagination de l'edition IMPRIMEE : exactement la donnee dont
    # la redevance papier a besoin. Jamais estimee depuis l'epaisseur (ecart x2,1 mesure).
    pages = _nb_pages(pick(_CLE_PAGES))
    # `format_papier` : jamais observe dans les puces de detail amazon.fr (captures v2 du
    # 2026-07-20, fiche B0CF4P1N9S), consomme par aucun module ; la redevance ne depend que
    # du prix, des pages et de l'encre. Laisse a None faute de source reelle.
    format_papier = None
    for kl, (k, v) in low.items():
        if any(f in kl for f in _FORMATS_PAPIER):
            format_papier = k
            if pages is None:
                pages = _nb_pages(v)
            if pages is not None:
                break           # une cle de format SANS pagination ne clot pas la recherche

    rating = item.get("rating") if isinstance(item.get("rating"), dict) else {}
    # caster AVANT _series_hint_from_title : la regex lève un TypeError sur un non-str,
    # et le `except ValidationError` plus bas ne le rattraperait pas.
    title = _text(item.get("title")) or ""
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
            bsr_subcats=subcats,
            publication_date=_text(pick("date de publication")),
            publisher=_text(pick("diteur")),
            pages=pages,
            dimensions=_text(pick("dimensions")),
            format_papier=format_papier,
            langue=_text(pick("langue")),
            serie_tome=tome,
            serie_total=total,
            series_hint=_series_hint_from_title(title),
            serp_position=serp_position,
            blurb=_text(item.get("description")),
        )
    except ValidationError:
        # docstring : "None si le payload est inexploitable" -> un livre atypique ne doit
        # jamais tuer le run (fetch_fiction_shelf n'a pas de filet de sécurité).
        return None
