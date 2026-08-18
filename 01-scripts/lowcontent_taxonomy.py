"""lowcontent_taxonomy.py — chargement et lecture de la taxonomie low-content.

Même rôle que `fiction_taxonomy` : borner ce que le LLM a le droit de proposer, et servir
de source unique aux libellés. Un format inventé par le modèle serait invérifiable ; un
libellé recopié en dur côté JS se périmerait à la première v2.

Deux notions que la taxo porte et que le code ne devine pas :

- `norme: true` — le contenu est fixé par une règle EXTERNE (Code du travail, HACCP, ERP).
  Piège de lecture à ne jamais inverser : « normé » ne veut pas dire « difficile ». Le
  contenu étant imposé, la production est simple, d'où un `effort` de 1. C'est la
  CONFORMITÉ qui est exigeante — et c'est pour ça que le verdict doit citer la source
  réglementaire (E7) : un registre incomplet prend des avis à une étoile.

- `est_indie` rend `None` sur un éditeur inconnu, jamais `False`. Voir sa docstring : c'est
  la même famille d'invariant que `AutocompleteSignal.mesure` (§5.10).

Rend des copies profondes, comme `fiction_taxonomy` : un appelant qui modifierait le dict
rendu corromprait la taxonomie de tout le processus.
"""
import copy
import json
import re
import unicodedata
from pathlib import Path

_DATA = Path(__file__).resolve().parent.parent / "data"
_CACHE: dict[str, dict] = {}


def _plat(texte: str) -> str:
    """Casse et accents dépouillés — Amazon rend « noel » comme « noël », et les noms
    d'éditeurs arrivent dans toutes les casses possibles."""
    s = unicodedata.normalize("NFKD", texte or "")
    return "".join(c for c in s if not unicodedata.combining(c)).lower().strip()


def load_taxonomy(version: str = "fr_v1") -> dict:
    """Charge et met en cache la taxonomie. Rend une COPIE PROFONDE."""
    if version not in _CACHE:
        chemin = _DATA / f"lowcontent_taxonomy_{version}.json"
        if not chemin.exists():
            raise ValueError(f"taxonomie low-content introuvable : {chemin}")
        _CACHE[version] = json.loads(chemin.read_text(encoding="utf-8"))
    return copy.deepcopy(_CACHE[version])


def valid_formats(version: str = "fr_v1") -> list[str]:
    return sorted(load_taxonomy(version)["formats"])


def format_(cle: str, version: str = "fr_v1") -> dict:
    """Un format par sa clé. LÈVE si la clé est inconnue.

    Silencieux, ça ferait croire à l'auteur que sa contrainte de format est appliquée
    alors qu'elle serait ignorée — même règle que la taxonomie fiction. Les menus étant
    peuplés depuis cette taxo, une clé inconnue ne peut venir que d'une requête forgée."""
    formats = load_taxonomy(version)["formats"]
    if cle not in formats:
        raise ValueError(f"format low-content inconnu : « {cle} » "
                         f"(dispo : {sorted(formats)})")
    return formats[cle]


def est_norme(cle: str, version: str = "fr_v1") -> bool:
    """Le contenu est-il fixé par une règle externe ? Déclenche le risque
    `norme_a_verifier` (E4) et l'obligation de source réglementaire au verdict (E7)."""
    return bool(format_(cle, version)["norme"])


def est_editeur_traditionnel(publisher: str, version: str = "fr_v1") -> bool:
    """Éditeur installé (Hachette, Larousse, Exacompta, Quo Vadis…).

    Ces noms sont invisibles dans un simple comptage de résultats, et c'est précisément
    ce qui rend un rayon low-content trompeur : douze références, toutes de papetiers."""
    p = _plat(publisher)
    if not p:
        return False
    return any(e in p for e in load_taxonomy(version)["editeurs_traditionnels"])


def est_indie(publisher: str | None, version: str = "fr_v1") -> bool | None:
    """True = publié via KDP · False = éditeur installé · **None = inconnu**.

    `None` et jamais `False` sur un éditeur qu'on ne reconnaît pas. `False` voudrait dire
    « ce n'est pas de l'indie », donc « c'est un éditeur installé » — une conclusion que
    rien ne soutient. Le scoring exclut les `None` du dénominateur de `part_indie` au lieu
    de les compter contre la niche, et annonce leur nombre (`n_editeur_inconnu`).

    C'est la même famille d'invariant que `AutocompleteSignal.mesure` : une absence de
    mesure ne se convertit pas en mesure défavorable (§5.10)."""
    p = _plat(publisher)
    if not p:
        return None
    taxo = load_taxonomy(version)
    if any(m in p for m in taxo["marqueurs_indie"]):
        return True
    if any(e in p for e in taxo["editeurs_traditionnels"]):
        return False
    return None


def est_saisonnier(texte: str, version: str = "fr_v1") -> bool:
    """Le texte porte-t-il un marqueur de saison ?

    Comparaison sur des MOTS ENTIERS, pas des sous-chaînes : « paques » sortirait sinon
    de « paquets », et un faux positif écarte une niche valable AVANT tout appel payant —
    donc sans que rien en aval ne puisse le rattraper."""
    p = _plat(texte)
    if not p:
        return False
    for marqueur in load_taxonomy(version)["saisonnalite"]:
        m = _plat(marqueur)
        if re.search(r"(?<!\w)" + re.escape(m) + r"(?!\w)", p):
            return True
    return False
