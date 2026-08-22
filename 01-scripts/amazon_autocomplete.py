"""amazon_autocomplete.py — suggestions amazon.fr en DIRECT (gratuit, 0 crédit).
Endpoint public completion.amazon.fr. Sert à valider qu'une niche est réellement
cherchée, découvrir des satellites, et fournir un proxy de volume (nb de suggestions).
I/O réseau injectable pour les tests."""
import json
from urllib.parse import urlencode

import util
from marketplace import ACTIF

# Hôte et identifiant de la place de marché active (`marketplace.py`). Le nom `_MID_FR`
# est conservé : il est lu par des tests et par `demo_free.py`, et le renommer pour une
# généralisation que le dépôt ne sait pas encore faire (voir les six manques listés dans
# `marketplace.py`) donnerait l'illusion d'un support multi-marché.
_BASE = ACTIF.url_completion()
_MID_FR = ACTIF.marketplace_id


def _build_url(prefix: str) -> str:
    q = urlencode({"mid": _MID_FR, "alias": "aps", "prefix": prefix, "limit": 11})
    return f"{_BASE}?{q}"


def parse_suggestions(payload: dict) -> list[str]:
    """Extrait la liste des chaînes de suggestion depuis le JSON amazon."""
    if not isinstance(payload, dict):
        return []
    items = payload.get("suggestions") or []
    out = []
    for s in items:
        v = (s.get("value") or "").strip() if isinstance(s, dict) else ""
        if v:
            out.append(v)
    return out


class AutocompleteError(RuntimeError):
    """Échec de la sonde (réseau, HTTP, JSON) — à distinguer d'une absence de suggestions :
    « personne ne cherche ça » est une conclusion, « le réseau a toussé » n'en est pas une."""


def fetch_json_strict(prefix: str) -> dict:
    """Comme _default_fetch_json mais LÈVE au lieu d'avaler l'échec."""
    r = util.http_get(_build_url(prefix), timeout=15)
    status = getattr(r, "status_code", None)
    if status != 200:
        raise AutocompleteError(f"HTTP {status}")
    try:
        return json.loads(r.text)
    except Exception as e:
        raise AutocompleteError(f"JSON invalide : {e}") from e


def _default_fetch_json(prefix: str) -> dict:
    """Wrapper silencieux : le scout non-fiction (niche_validator) s'appuie sur ce
    comportement en production, il ne doit PAS lever — on avale l'échec ici seulement."""
    try:
        return fetch_json_strict(prefix)
    except AutocompleteError as e:
        print(f"[autocomplete] {e}")
        return {}


def fetch_suggestions(prefix: str, fetch_json=None) -> list[str]:
    """Retourne les suggestions amazon.fr pour `prefix`. `fetch_json(prefix)->dict`
    injectable ; par défaut appelle l'endpoint direct."""
    fetch_json = fetch_json or _default_fetch_json
    return parse_suggestions(fetch_json(prefix))
