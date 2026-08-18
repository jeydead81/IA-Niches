"""ip_filter.py — écarte les niches portant une marque, une franchise ou un personnage.

Le seul filtre du dépôt dont l'enjeu est JURIDIQUE. Les autres garde-fous protègent un
chiffre ; celui-ci protège le compte KDP. Un cahier de coloriage sous marque n'est pas une
niche médiocre : c'est un retrait de publication, et répété, une fermeture de compte.

Il faut le dire au bon endroit : l'autocomplete en est PLEIN. « coloriage pat patrouille »
est exactement ce que les gens tapent, donc exactement ce que l'arbre remonte en premier —
avec un `n_enfants` élevé, c'est-à-dire tous les signes d'une excellente niche.

Deux raisons distinctes de le faire tourner CÔTÉ CODE et AVANT l'appel LLM :
- le prompt système demande déjà au modèle de ne pas proposer de marques, mais §4.2 est
  formel : ce qui n'est pas doublé en code est une intention, pas une règle ;
- filtrer avant l'appel évite de payer des tokens pour classer une niche qu'on jettera.

Chaque rejet sort avec son MOTIF. « rejeté » ne dit rien à l'auteur ; « pokemon » lui dit
quoi changer — et un rejet muet ferait passer un rayon filtré pour un rayon vide.
"""
import re
import unicodedata
from pathlib import Path

_FICHIER = Path(__file__).resolve().parent.parent / "data" / "exclusions_ip.md"
_CACHE: list[str] | None = None


def _plat(texte: str) -> str:
    """Casse et accents dépouillés. « Pokémon » et « pokemon » sont la même marque, et
    c'est l'orthographe accentuée qui domine dans les complétions Amazon."""
    s = unicodedata.normalize("NFKD", texte or "")
    return " ".join("".join(c for c in s if not unicodedata.combining(c)).lower().split())


def charger_termes(chemin: Path | None = None) -> list[str]:
    """Lit la liste depuis le fichier versionné, une entrée par ligne.

    En dur dans le .py, elle exigerait un commit de code pour ajouter une franchise. Elle
    va vivre — c'est Baptiste qui la fera vivre, et il doit pouvoir le faire sans toucher
    au code. Les commentaires `#` sont conservés dans le fichier parce qu'une entrée sans
    justification finit par être retirée par quelqu'un qui ne sait pas pourquoi elle
    était là."""
    global _CACHE
    if chemin is None and _CACHE is not None:
        return list(_CACHE)
    f = chemin or _FICHIER
    termes = []
    for ligne in f.read_text(encoding="utf-8").splitlines():
        t = _plat(ligne)
        if not t or ligne.lstrip().startswith("#"):
            continue
        termes.append(t)
    # dédup en conservant l'ordre de lecture (le fichier est groupé par thème)
    termes = list(dict.fromkeys(termes))
    if chemin is None:
        _CACHE = termes
    return list(termes)


def terme_ip(texte: str, termes: list[str] | None = None) -> str | None:
    """Rend le terme qui a déclenché, ou `None`.

    Comparaison sur des MOTS ENTIERS, jamais par sous-chaîne. C'est LE piège du module :
    par sous-chaîne, « om » (le club) sort de « coloriage bonhomme » et « cm2 » d'un
    « cahier de vacances CM2 ». Un faux positif écarte une niche valable EN SILENCE et
    avant toute mesure — rien en aval ne peut le rattraper, puisque la niche n'atteint
    jamais la phase payante."""
    p = _plat(texte)
    if not p:
        return None
    for t in (termes if termes is not None else charger_termes()):
        if re.search(r"(?<!\w)" + re.escape(t) + r"(?!\w)", p):
            return t
    return None


def _champs(objet) -> str:
    """Concatène ce qui peut porter une marque : le libellé, la requête, les satellites.

    Les satellites comptent autant que la requête principale : ils finissent dans les
    mots-clés backend KDP, donc sur la fiche produit — c'est-à-dire à l'endroit exact que
    l'algorithme de conformité d'Amazon regarde."""
    if isinstance(objet, str):
        return objet
    morceaux = [getattr(objet, "niche", "") or "",
                getattr(objet, "requete_amazon", "") or ""]
    morceaux += list(getattr(objet, "satellite_keywords", None) or [])
    return " ".join(m for m in morceaux if m)


def filtrer_ip(objets, termes: list[str] | None = None) -> tuple[list, list[tuple]]:
    """`(gardés, [(objet, terme), …])`.

    Accepte des chaînes nues aussi bien que des niches : le filtre tourne sur les
    suggestions BRUTES de l'arbre d'autocomplete, avant qu'aucun modèle n'existe — et
    c'est là qu'il coûte le moins cher, puisqu'il économise les tokens de classement."""
    termes = termes if termes is not None else charger_termes()
    gardes, rejets = [], []
    for o in objets or []:
        t = terme_ip(_champs(o), termes)
        if t:
            rejets.append((o, t))
        else:
            gardes.append(o)
    return gardes, rejets
