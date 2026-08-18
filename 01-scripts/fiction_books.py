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
# amazon.fr ecrit le format en CLE et la pagination en VALEUR : {"Broche": "120 pages"}.
# Les deux se lisent donc du meme champ. \d avec separateurs de milliers francais (espace
# fine incluse) : "1 248 pages" est une ecriture reelle.
_PAGES = re.compile(r"([\d][\d\s  .]*)\s*pages?", re.I)
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

    # Format + pagination : la CLE porte le format ("Broche"), la VALEUR la pagination
    # ("120 pages"). On rend le libelle Amazon tel quel plutot qu'une cle normalisee --
    # c'est ce que l'auteur lit sur la fiche, et la grille de cout KDP s'y raccroche.
    format_papier = pages = None
    for kl, (k, v) in low.items():
        if any(f in kl for f in _FORMATS_PAPIER):
            format_papier = k
            m = _PAGES.search(str(v or ""))
            if m:
                pages = _bsr_to_int(m.group(1))     # gere les separateurs de milliers FR
            break

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
