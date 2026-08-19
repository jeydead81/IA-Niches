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
from functools import lru_cache
from pathlib import Path

_FICHIER = Path(__file__).resolve().parent.parent / "data" / "exclusions_ip.md"
_CACHE: list[str] | None = None


# Toutes les formes d'apostrophe ramenees a une seule. L'apostrophe TYPOGRAPHIQUE U+2019
# est la forme officielle des marques qui en portent une -- « Pat'Patrouille »,
# « T'choupi », « McDonald's » -- et c'est celle qu'Amazon rend dans ses completions. Ne
# pas la normaliser, c'est laisser passer la graphie la PLUS courante de ces marques-la.
_APOSTROPHES = {"\u2019": "'", "\u2018": "'", "\u02bc": "'", "`": "'", "\u00b4": "'"}


def _plat(texte: str) -> str:
    """Casse, accents et apostrophes unifies. « Pokémon » et « pokemon » sont la meme
    marque, et c'est l'orthographe accentuee qui domine dans les completions Amazon."""
    t = texte or ""
    for a, b in _APOSTROPHES.items():
        t = t.replace(a, b)
    s = unicodedata.normalize("NFKD", t)
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


# Determinants qu'une entree peut porter et qu'une requete reelle omet presque toujours :
# la liste dit « les minions », les gens tapent « coloriage minions ». On accepte donc
# l'entree AVEC ou SANS son determinant, plutot que de dupliquer chaque entree -- une
# duplication s'oublie a la premiere franchise ajoutee.
_DETERMINANTS = ("les ", "le ", "la ", "l'", "the ")

# Entre deux mots d'une marque, les gens ecrivent une espace, un trait d'union, une
# apostrophe, ou rien du tout : « pat patrouille », « pat-patrouille », « pat'patrouille »,
# « patpatrouille ». Les quatre designent la meme marque et doivent toutes tomber.
# La VIRGULE en fait partie : « Moi, moche et mechant » s'ecrit avec, la liste sans.
# Le `'s` possessif anglais aussi (« gabby's dollhouse ») -- il separe deux mots de la
# marque sans en faire partie.
_SEPARATEUR = r"(?:'s)?[\s\-'._,]*"

# Pluriel francais tolere sur CHAQUE mot : « pokemons », « legos », « stars wars ».
# Applique par mot et non seulement a la fin, parce que la marque n'est pas toujours en
# derniere position dans la forme mutee.
_PLURIEL = r"s?"


@lru_cache(maxsize=2048)
def _motif(terme: str) -> "re.Pattern":
    r"""Compile un terme en motif tolerant aux mutations.

    Les bornes `(?<!\w)` / `(?!\w)` restent : c'est ce qui empeche « om » de sortir de
    « bonhomme » et « cm2 » d'un « cahier de vacances CM2 ». On elargit ce qu'il y a ENTRE
    les mots, jamais ce qui delimite le terme."""
    noyau = terme
    for det in _DETERMINANTS:
        if noyau.startswith(det):
            # `(?:les\s+)?` : l'entree matche avec ET sans son determinant.
            reste = noyau[len(det):]
            prefixe = "(?:" + re.escape(det.strip()) + r"\s*)?"
            return re.compile(r"(?<!\w)" + prefixe + _corps(reste) + r"(?!\w)")
    return re.compile(r"(?<!\w)" + _corps(noyau) + r"(?!\w)")


# Mots de LIAISON internes, que les requetes reelles avalent : la liste dit « sam le
# pompier » et « olympique de marseille », les gens tapent « sam pompier » et « olympique
# marseille ». Les rendre optionnels A L'INTERIEUR du terme couvre la classe entiere, la
# ou ajouter chaque variante a la main s'oublierait a la franchise suivante.
_LIAISONS = {"le", "la", "les", "de", "du", "des", "d", "l", "of", "the", "et", "and", "a"}


def _mot(m: str) -> str:
    """Un mot du terme, tolerant au pluriel DANS LES DEUX SENS.

    La liste porte « les minions » et « les schtroumpfs » ; les gens ecrivent « minion »
    et « schtroumpf ». Un `s?` ajoute ne couvre qu'un sens : il faut aussi pouvoir RETIRER
    le pluriel de l'entree. On matche donc le radical, suivi d'un `s` optionnel.

    Le radical n'est ampute que si le mot fait plus de trois lettres : sans ce garde,
    « cars » deviendrait « car » et « bus » deviendrait « bu ' -- des radicaux trop courts
    pour rester des marques."""
    radical = m[:-1] if len(m) > 3 and m.endswith("s") else m
    return re.escape(radical) + _PLURIEL


def _corps(terme: str) -> str:
    """Les mots du terme, relies par un separateur libre, chacun pluralisable, les mots de
    liaison rendus optionnels."""
    mots = [m for m in re.split(r"[\s\-'._,]+", terme) if m]
    if not mots:
        return re.escape(terme)
    morceaux = []
    for i, m in enumerate(mots):
        # Un mot de liaison n'est optionnel qu'AU MILIEU : en tete ou en queue il porte le
        # sens (« the beatles », « pat patrouille »).
        if 0 < i < len(mots) - 1 and m in _LIAISONS:
            morceaux.append("(?:" + re.escape(m) + _SEPARATEUR + ")?")
        else:
            morceaux.append(_mot(m) + (_SEPARATEUR if i < len(mots) - 1 else ""))
    return "".join(morceaux)


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
        if _motif(t).search(p):
            return t
    return None


def _champs(objet) -> str:
    """Concatène ce qui peut porter une marque : le libellé, la requête, les satellites.

    Les satellites comptent autant que la requête principale : ils finissent dans les
    mots-clés backend KDP, donc sur la fiche produit — c'est-à-dire à l'endroit exact que
    l'algorithme de conformité d'Amazon regarde."""
    if isinstance(objet, str):
        return objet
    # `requete` couvre les `Suggestion` de l'arbre d'autocomplete, `requete_amazon` les
    # niches. Sans le premier, le filtre rendait silencieusement TOUT sur les suggestions
    # brutes -- c'est-a-dire exactement la ou il doit mordre le plus, avant l'appel LLM.
    morceaux = [getattr(objet, "niche", "") or "",
                getattr(objet, "requete", "") or "",
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
