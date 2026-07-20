"""fiction_taxonomy.py — chargement + validation de la taxonomie fiction versionnée.
Le classifieur ne sortira QUE des clés de cette taxo (+ un champ libre `other`).
Le rayon (kindle/papier) et le marketplace sont des paramètres : un node absent
(`null`) bascule le couple sous-genre × rayon en mode « rayon requête »."""
import json
from functools import lru_cache
from pathlib import Path

_DATA = Path(__file__).resolve().parent.parent / "data"
_FILTRES = {"kindle": "i=digital-text", "papier": "i=stripbooks"}


@lru_cache(maxsize=4)
def load_taxonomy(version: str = "fr_v1") -> dict:
    p = _DATA / f"fiction_taxonomy_{version}.json"
    if not p.exists():
        raise FileNotFoundError(f"taxonomie introuvable : {p}")
    return json.loads(p.read_text(encoding="utf-8"))


def sous_genre(cle: str, version: str = "fr_v1") -> dict:
    sgs = load_taxonomy(version)["sous_genres"]
    if cle not in sgs:
        raise KeyError(f"sous-genre inconnu : {cle} (dispo : {sorted(sgs)})")
    return sgs[cle]


def node_for(cle: str, rayon: str = "kindle", version: str = "fr_v1") -> str | None:
    """Browse node du sous-genre pour ce rayon. None -> mode « rayon requête »."""
    if rayon not in _FILTRES:
        raise ValueError(f"rayon inconnu : {rayon}")
    return sous_genre(cle, version).get(f"node_{rayon}")


def search_param_for(rayon: str) -> str:
    if rayon not in _FILTRES:
        raise ValueError(f"rayon inconnu : {rayon} (dispo : {sorted(_FILTRES)})")
    return _FILTRES[rayon]


def valid_keys(cle: str, version: str = "fr_v1") -> tuple[list[str], list[str]]:
    """(tropes, décors) autorisés pour ce sous-genre — contraint la sortie du classifieur."""
    sg = sous_genre(cle, version)
    return list(sg["tropes"]), list(sg["decors"])
