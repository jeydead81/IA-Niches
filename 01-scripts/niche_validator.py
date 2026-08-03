"""niche_validator.py — confronte les niches proposées par l'ideator à l'autocomplete
Amazon.fr (canal gratuit). Principe : si, en tapant un angle (la niche ou l'un de ses
satellite_keywords), Amazon AUTO-COMPLÈTE avec des suggestions réelles, c'est la preuve
qu'il y a une demande de recherche. Sinon, l'angle est probablement mort.

Gratuit (endpoint direct completion.amazon.fr). L'appel réseau (`fetch`) est injectable
pour les tests ; un léger `pause` espace les requêtes pour ne pas se faire soft-bloquer.
"""
import re
import time
import unicodedata

from amazon_autocomplete import fetch_suggestions
from models import NicheCandidate, NicheValidation

# Une intention est dite « dominante » quand le même mot revient dans au moins cette part
# des suggestions. La moitié est un seuil volontairement haut : en dessous, on décrirait du
# bruit de longue traîne comme une figure imposée.
SEUIL_DOMINANCE = 0.5
# En dessous de ce nombre de suggestions, « la moitié » ne veut rien dire.
MIN_SUGGESTIONS_DOMINANCE = 4

# Mots qui trahissent une intention d'INFORMATION et non d'achat. Quelqu'un qui cherche
# « résumé de X » ou « avis sur X » veut l'information, pas le livre : une niche peut avoir
# beaucoup de demande apparente et un public qui n'achètera jamais rien.
#
# « occasion » et « pdf gratuit » ont été volontairement ÉCARTÉS de cette liste. Décision de
# Baptiste, argument retenu : un acheteur d'occasion reste un acheteur, simplement sensible
# au prix — il peut basculer sur du neuf à peine plus cher. Le classer avec les intentions
# non marchandes fausserait le signal.
MARQUEURS_INFORMATIONNELS = frozenset({
    "avis", "critique", "critiques", "resume", "resumes", "definition", "signification",
    "explication", "explications", "citations", "citation", "wikipedia", "biographie",
    "analyse", "commentaire", "commentaires",
})

# Mots vides : ils reviennent partout et ne désignent aucune intention.
_VIDES = frozenset({
    "de", "du", "des", "la", "le", "les", "un", "une", "et", "en", "au", "aux", "pour",
    "sur", "dans", "avec", "par", "sans", "chez", "a", "l", "d",
})


def _plat(texte: str) -> str:
    """Casse et accents dépouillés — « Résumé » et « resume » sont le même mot, et
    l'autocomplete rend les deux formes."""
    s = unicodedata.normalize("NFKD", texte or "")
    return "".join(c for c in s if not unicodedata.combining(c)).lower()


def _mots(texte: str) -> list[str]:
    return [m for m in re.split(r"[^\w]+", _plat(texte)) if m and m not in _VIDES]


def lire_suggestions(suggestions, requete: str) -> dict:
    """Lit le CONTENU des suggestions, pas seulement leur nombre.

    Le compte (`demand_score`) sature vite : mesuré sur 30 niches, 16 dépassaient le
    plafond du scoring. Il dit « il y a de la demande », jamais « quelle demande ». Or les
    suggestions sont déjà collectées, gratuites, et personne ne les lisait.

    Deux lectures, rendues comme des DRAPEAUX et non comme des points de score — ajouter
    silencieusement au score serait un jugement déguisé en mesure (même règle que la
    fourchette de prix) :

    - `terme_dominant` : un mot ABSENT de la requête qui revient dans au moins la moitié des
      suggestions. L'intention de recherche est concentrée dessus, typiquement un auteur ou
      un titre qui tient le rayon. On le nomme sans prétendre savoir ce que c'est : décider
      qu'un mot est un nom propre demanderait un dictionnaire, la répétition se mesure.
    - `intention_informationnelle` : la traîne parle de résumés, d'avis, de citations. Ces
      gens veulent l'information, pas le livre.

    Zéro suggestion ne conclut RIEN : ce n'est pas un rayon sain, c'est une absence de
    mesure."""
    lues = list(suggestions or [])
    mots_requete = set(_mots(requete))
    marqueurs = sorted({m for s in lues for m in _mots(s)
                        if m in MARQUEURS_INFORMATIONNELS})

    dominant, part = None, 0.0
    if len(lues) >= MIN_SUGGESTIONS_DOMINANCE:
        compte: dict[str, int] = {}
        for s in lues:
            # Un mot compte UNE fois par suggestion : répété dans la même complétion, il ne
            # prouve pas que plusieurs personnes le cherchent.
            for m in set(_mots(s)) - mots_requete:
                compte[m] = compte.get(m, 0) + 1
        if compte:
            mot, n = max(compte.items(), key=lambda kv: (kv[1], -len(kv[0])))
            if n / len(lues) >= SEUIL_DOMINANCE:
                dominant, part = mot, round(n / len(lues), 2)

    return {"terme_dominant": dominant, "part_dominante": part,
            "intention_informationnelle": bool(marqueurs),
            "marqueurs_informationnels": marqueurs,
            "suggestions_lues": len(lues)}



def validate_niche(candidate: NicheCandidate, fetch, max_queries: int = 4,
                   pause: float = 0.0) -> NicheValidation:
    """Teste la niche + ses satellites contre l'autocomplete. Agrège les suggestions
    réelles renvoyées par Amazon (dédupliquées) et compte combien de requêtes 'prennent'."""
    # On teste la requête COURTE réelle (requete_amazon) d'abord — l'autocomplete est
    # préfixe, un libellé long ne se complète pas. Puis les satellites courts.
    head = candidate.requete_amazon or candidate.niche
    ordered = [head] + list(candidate.satellite_keywords)
    qseen: set[str] = set()
    queries: list[str] = []
    for q in ordered:
        k = q.lower().strip()
        if k and k not in qseen:
            qseen.add(k)
            queries.append(q)
    queries = queries[:max_queries]
    seen: set[str] = set()
    uniq: list[str] = []
    hits = 0
    for j, q in enumerate(queries):
        suggestions = fetch(q)
        if suggestions:
            hits += 1
            for item in suggestions:
                k = item.lower().strip()
                if k and k not in seen:
                    seen.add(k)
                    uniq.append(item)
        if pause and j < len(queries) - 1:
            time.sleep(pause)
    lecture = lire_suggestions(uniq, head)
    return NicheValidation(
        niche=candidate.niche,
        requete_amazon=candidate.requete_amazon,
        categorie=candidate.categorie,
        satellite_keywords=candidate.satellite_keywords,
        amazon_suggestions=uniq[:10],
        demand_score=len(uniq),
        queries_hit=hits,
        validated=hits > 0,
        terme_dominant=lecture["terme_dominant"],
        part_dominante=lecture["part_dominante"],
        intention_informationnelle=lecture["intention_informationnelle"],
        marqueurs_informationnels=lecture["marqueurs_informationnels"],
    )


def validate_niches(candidates: list[NicheCandidate], fetch=None, pause: float = 0.4,
                    max_queries: int = 4) -> list[NicheValidation]:
    """Valide une liste de niches et les trie par demande décroissante (les mieux
    auto-complétées par Amazon en tête)."""
    fetch = fetch or fetch_suggestions
    out = [validate_niche(c, fetch, max_queries=max_queries, pause=pause) for c in candidates]
    out.sort(key=lambda v: (v.validated, v.demand_score), reverse=True)
    return out
