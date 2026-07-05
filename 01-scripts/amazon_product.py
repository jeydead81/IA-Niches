"""amazon_product.py — récupère le BSR (classement des ventes) d'une fiche produit
amazon.fr en la scrappant DIRECTEMENT (gratuit, validé live depuis l'IP utilisateur).
Le parsing est pur et testé ; l'I/O réseau est injectable."""
import re

import util
from models import BsrInfo

# Bloc "Classement des meilleures ventes" (on borne à 1500 car pour rester local)
_BLOCK = re.compile(r"Classement des meilleures ventes.{0,1500}", re.I | re.S)
# rang principal : "N en Livres" (catégorie racine)
_MAIN = re.compile(r"([\d][\d\s. \xa0]{0,14}?)\s*en\s+Livres\b", re.I)
# sous-catégories : "N en <NomCatégorie>"
_SUB = re.compile(
    r"([\d][\d\s. \xa0]{0,14}?)\s*en\s+([A-Za-zÀ-ÿ][^\d(]{2,50}?)(?=\s{2,}|\s+\d|$)",
    re.I,
)


def _strip_tags(html: str) -> str:
    return re.sub(r"<[^>]+>", " ", html)


def _to_int(s: str) -> int | None:
    digits = re.sub(r"[^\d]", "", s or "")
    return int(digits) if digits else None


def parse_bsr(html: str) -> BsrInfo | None:
    """Extrait le rang Livres + sous-catégories du bloc BSR. None si absent."""
    m = _BLOCK.search(html)
    if not m:
        return None
    text = re.sub(r"\s+", " ", _strip_tags(m.group(0)))
    main = _MAIN.search(text)
    rank_livres = _to_int(main.group(1)) if main else None
    if rank_livres is None:
        return None
    subs: list[dict] = []
    for sm in _SUB.finditer(text):
        cat = sm.group(2).strip(" .:,")
        if cat.lower() == "livres" or "voir les" in cat.lower():
            continue  # catégorie racine ou lien "Voir les 100 premiers"
        rank = _to_int(sm.group(1))
        if rank and cat:
            subs.append({"category": cat, "rank": rank})
    return BsrInfo(rank_livres=rank_livres, subcategories=subs[:5], raw=text[:300])


def _default_fetch_html(asin: str) -> str | None:
    r = util.http_get(f"https://www.amazon.fr/dp/{asin}")
    return r.text if getattr(r, "status_code", None) == 200 else None


def fetch_bsr(asin: str, fetch_html=None) -> BsrInfo | None:
    """Récupère et parse le BSR d'un ASIN. `fetch_html(asin)->str|None` injectable."""
    fetch_html = fetch_html or _default_fetch_html
    html = fetch_html(asin)
    if not html:
        return None
    info = parse_bsr(html)
    if info:
        info.asin = asin
    return info
