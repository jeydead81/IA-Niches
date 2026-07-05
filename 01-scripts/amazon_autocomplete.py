"""amazon_autocomplete.py — suggestions amazon.fr en DIRECT (gratuit, 0 crédit).
Endpoint public completion.amazon.fr. Sert à valider qu'une niche est réellement
cherchée, découvrir des satellites, et fournir un proxy de volume (nb de suggestions).
I/O réseau injectable pour les tests."""
from urllib.parse import urlencode

import util

_BASE = "https://completion.amazon.fr/api/2017/suggestions"
_MID_FR = "A13V1IB3VIYZZH"  # marketplace ID amazon.fr


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


def _default_fetch_json(prefix: str) -> dict:
    import json
    r = util.http_get(_build_url(prefix), timeout=15)
    if getattr(r, "status_code", None) != 200:
        return {}
    try:
        return json.loads(r.text)
    except Exception:
        return {}


def fetch_suggestions(prefix: str, fetch_json=None) -> list[str]:
    """Retourne les suggestions amazon.fr pour `prefix`. `fetch_json(prefix)->dict`
    injectable ; par défaut appelle l'endpoint direct."""
    fetch_json = fetch_json or _default_fetch_json
    return parse_suggestions(fetch_json(prefix))
