"""amazon_product.py — récupère le BSR (classement des ventes) d'une fiche produit
amazon.fr en la scrappant DIRECTEMENT (gratuit, validé live depuis l'IP utilisateur).
Le parsing est pur et testé ; l'I/O réseau est injectable."""
import re

import util
from marketplace import ACTIF
from models import BsrInfo

# Bloc "Classement des meilleures ventes" (borné à 4000 car sur texte NETTOYÉ des
# balises, pour ne pas gaspiller le budget de caractères sur du bruit DOM/tracking)
_BLOCK = re.compile(r"Classement des meilleures ventes.{0,4000}", re.I | re.S)
# rang principal : "N en Livres" (catégorie racine)
_MAIN = re.compile(r"([\d][\d\s. \xa0]{0,14}?)\s*en\s+Livres(?!\s+\w)", re.I)  # lookahead : « Livres » = le RAYON, pas « Livres electroniques de ... » (ebooks)
# sous-catégories : "N en <NomCatégorie>". Le nom s'arrête avant le rang suivant, avant un
# qualificatif "(Livres)", ou avant le bruit RÉEL qui suit le bloc sur une fiche amazon.fr :
# « Commentaires client » et le CSS « .ask-product-docs-expander-content { ». Mesuré sur 29
# extraits réels (tests/fixtures/bsr_scrape_fr_reel.json) — des `BsrInfo.raw` déjà débalisés
# et TRONQUÉS à 300 caractères, pas le HTML complet des fiches : la branche `$` et ce qui suit
# la liste sur une page entière n'y sont pas exercés. Sur ces extraits, le plafond de 50 et
# une branche `\s{2,}` morte — les espaces sont normalisés AVANT — perdaient 11
# sous-catégories sur 75 et en polluaient 7. 80 couvre le plus long nom observé (58).
_SUB = re.compile(
    r"([\d][\d\s. \xa0]{0,14}?)\s*en\s+([A-Za-zÀ-ÿ][^\d(]{2,80}?)"
    r"(?=\s+\d|\s*\(|\s+Commentaires client|\s+\.[a-z-]+\s*\{|$)",
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
    r = util.http_get(ACTIF.url_fiche(asin))
    status = getattr(r, "status_code", None)
    if status == 200:
        return r.text
    print(f"[bsr] HTTP {status} pour {asin} (fiche bloquée ?)")
    return None


class BsrIndisponible(RuntimeError):
    """La fiche n'a pas été LUE (statut non-200, blocage). Rien n'est su de son classement."""


def fetch_bsr_strict(asin: str, fetch_html=None) -> BsrInfo | None:
    """Comme `fetch_bsr`, mais LÈVE quand la fiche n'est pas lue ; `None` veut alors dire
    « fiche lue, sans classement Livres ».

    C'est le défaut de `resolve_bsrs`, et de lui seul : `fetch_bsr` avalait un 503 en `None`,
    que `resolve_bsrs` écrivait 3 jours dans le cache MUTUALISÉ comme absence de classement
    — pour tous les comptes. Même partage que `fetch_json_strict` / `_default_fetch_json`
    côté autocomplete. `launcher` et `demo_free` gardent `fetch_bsr` et son `None`.

    Trou connu, NON couvert : une page de captcha servie en 200 se parse en `None` et reste
    lue comme une absence. Aucun discriminant n'est codé faute de capture HTML réelle d'un
    captcha amazon.fr ; en inventer un reviendrait à deviner la forme du blocage."""
    fetch_html = fetch_html or _default_fetch_html
    html = fetch_html(asin)
    if not html:
        raise BsrIndisponible(f"fiche {asin} non lue")
    info = parse_bsr(html)
    if info:
        info.asin = asin
    return info


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
