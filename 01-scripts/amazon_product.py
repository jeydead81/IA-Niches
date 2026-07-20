"""amazon_product.py — récupère le BSR (classement des ventes) d'une fiche produit
amazon.fr en la scrappant DIRECTEMENT (gratuit, validé live depuis l'IP utilisateur).
Le parsing est pur et testé ; l'I/O réseau est injectable."""
import re

import util
from models import BsrInfo

# Bloc "Classement des meilleures ventes" (borné à 4000 car sur texte NETTOYÉ des
# balises, pour ne pas gaspiller le budget de caractères sur du bruit DOM/tracking)
_BLOCK = re.compile(r"Classement des meilleures ventes.{0,4000}", re.I | re.S)
# rang principal : "N en Livres" (catégorie racine)
_MAIN = re.compile(r"([\d][\d\s. \xa0]{0,14}?)\s*en\s+Livres(?!\s+\w)", re.I)  # lookahead : « Livres » = le RAYON, pas « Livres electroniques de ... » (ebooks)
# sous-catégories : "N en <NomCatégorie>" — s'arrête avant une parenthèse pour ne
# pas avaler un qualificatif du type "(Livres)" tout en gardant le nom de la catégorie
_SUB = re.compile(
    r"([\d][\d\s. \xa0]{0,14}?)\s*en\s+([A-Za-zÀ-ÿ][^\d(]{2,50}?)(?=\s{2,}|\s+\d|\s*\(|$)",
    re.I,
)


def _strip_tags(html: str) -> str:
    return re.sub(r"<[^>]+>", " ", html)


def _to_int(s: str) -> int | None:
    digits = re.sub(r"[^\d]", "", s or "")
    return int(digits) if digits else None


def parse_bsr(html: str) -> BsrInfo | None:
    """Extrait le rang Livres + sous-catégories du bloc BSR. None si absent."""
    # On nettoie les balises et espaces sur la page ENTIÈRE d'abord, pour que le
    # budget de caractères du bloc ne soit pas gaspillé par du bruit DOM/tracking
    # (spans imbriqués, liens de tracking, etc.) présent dans le HTML brut.
    cleaned = re.sub(r"\s+", " ", _strip_tags(html))
    m = _BLOCK.search(cleaned)
    if not m:
        return None
    text = m.group(0)
    main = _MAIN.search(text)
    rank_livres = _to_int(main.group(1)) if main else None
    if rank_livres is None:
        return None
    subs: list[dict] = []
    for sm in _SUB.finditer(text):
        cat = sm.group(2).strip(" .,:;")
        # supprime un connecteur final isolé du type " et" / " and" laissé par le lookahead
        cat = re.sub(r"\s+(?:et|and)$", "", cat, flags=re.I).strip(" .,:;")
        if cat.lower() == "livres" or "voir les" in cat.lower():
            continue  # catégorie racine ou lien "Voir les 100 premiers"
        rank = _to_int(sm.group(1))
        if rank and cat:
            subs.append({"category": cat, "rank": rank})
    return BsrInfo(rank_livres=rank_livres, subcategories=subs[:5], raw=text[:300])


def _default_fetch_html(asin: str) -> str | None:
    r = util.http_get(f"https://www.amazon.fr/dp/{asin}")
    status = getattr(r, "status_code", None)
    if status == 200:
        return r.text
    print(f"[bsr] HTTP {status} pour {asin} (fiche bloquée ?)")
    return None


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
