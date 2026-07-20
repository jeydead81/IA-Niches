"""fiction_taxonomy.py — chargement + validation de la taxonomie fiction versionnée.
Le classifieur ne sortira QUE des clés de cette taxo (+ un champ libre `other`).
Le rayon (kindle/papier) et le marketplace sont des paramètres : un node absent
(`null`) bascule le couple sous-genre × rayon en mode « rayon requête ».

SOURCE DE VÉRITÉ UNIQUE : les filtres de rayon vivent dans le JSON versionné, jamais en
dur ici — sinon une taxo v2 qui corrige ou ajoute un rayon serait silencieusement ignorée
et les appels SERP partiraient sur le mauvais rayon sans erreur."""
import copy
import json
from functools import lru_cache
from pathlib import Path

_DATA = Path(__file__).resolve().parent.parent / "data"


@lru_cache(maxsize=4)
def load_taxonomy(version: str = "fr_v1") -> dict:
    p = _DATA / f"fiction_taxonomy_{version}.json"
    if not p.exists():
        raise FileNotFoundError(f"taxonomie introuvable : {p}")
    return json.loads(p.read_text(encoding="utf-8"))


def _filtres(version: str = "fr_v1") -> dict:
    return load_taxonomy(version).get("filtres_rayon") or {}


def _labels(version: str = "fr_v1") -> dict:
    return load_taxonomy(version).get("labels_rayon") or {}


def sous_genre(cle: str, version: str = "fr_v1") -> dict:
    """Copie du sous-genre : la taxonomie est en cache, on ne rend jamais l'objet vivant
    (un appelant qui le mutait corromprait le cache pour tout le process)."""
    sgs = load_taxonomy(version)["sous_genres"]
    if cle not in sgs:
        raise KeyError(f"sous-genre inconnu : {cle} (dispo : {sorted(sgs)})")
    return copy.deepcopy(sgs[cle])


def node_for(cle: str, rayon: str = "kindle", version: str = "fr_v1") -> str | None:
    """Browse node du sous-genre pour ce rayon. None -> mode « rayon requête »."""
    if rayon not in _filtres(version):
        raise ValueError(f"rayon inconnu : {rayon}")
    return sous_genre(cle, version).get(f"node_{rayon}")


def search_param_for(rayon: str, version: str = "fr_v1") -> str:
    """Filtre de rayon Amazon (`search_param`), lu dans la taxonomie versionnée."""
    filtres = _filtres(version)
    if rayon not in filtres:
        raise ValueError(f"rayon inconnu : {rayon} (dispo : {sorted(filtres)})")
    return filtres[rayon]


def label_rayon(rayon: str, version: str = "fr_v1") -> str:
    """Libellé Amazon du rayon (`EnrichedBook.bsr_rayon`), lu dans la taxonomie versionnée.

    FictionNiche.rayon vaut "kindle"/"papier" (paramètre interne) alors que le BSR d'une
    fiche produit porte le libellé Amazon "Boutique Kindle"/"Livres" (bsr_rayon). Un
    appelant qui passerait niche.rayon tel quel à EnrichedBook.est_payant_dans() obtiendrait
    False pour TOUS les livres -> niche déclarée morte sans la moindre erreur (piège M5)."""
    labels = _labels(version)
    if rayon not in labels:
        raise ValueError(f"rayon inconnu : {rayon} (dispo : {sorted(labels)})")
    return labels[rayon]


def valid_keys(cle: str, version: str = "fr_v1") -> tuple[list[str], list[str]]:
    """(tropes, décors) autorisés pour ce sous-genre — contraint la sortie du classifieur."""
    sg = sous_genre(cle, version)
    return list(sg["tropes"]), list(sg["decors"])
