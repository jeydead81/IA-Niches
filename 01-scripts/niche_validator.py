"""niche_validator.py — confronte les niches proposées par l'ideator à l'autocomplete
Amazon.fr (canal gratuit). Principe : si, en tapant un angle (la niche ou l'un de ses
satellite_keywords), Amazon AUTO-COMPLÈTE avec des suggestions réelles, c'est la preuve
qu'il y a une demande de recherche. Sinon, l'angle est probablement mort.

Gratuit (endpoint direct completion.amazon.fr). L'appel réseau (`fetch`) est injectable
pour les tests ; un léger `pause` espace les requêtes pour ne pas se faire soft-bloquer.
"""
import time

from amazon_autocomplete import fetch_suggestions
from models import NicheCandidate, NicheValidation


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
    return NicheValidation(
        niche=candidate.niche,
        requete_amazon=candidate.requete_amazon,
        categorie=candidate.categorie,
        satellite_keywords=candidate.satellite_keywords,
        amazon_suggestions=uniq[:10],
        demand_score=len(uniq),
        queries_hit=hits,
        validated=hits > 0,
    )


def validate_niches(candidates: list[NicheCandidate], fetch=None, pause: float = 0.4,
                    max_queries: int = 4) -> list[NicheValidation]:
    """Valide une liste de niches et les trie par demande décroissante (les mieux
    auto-complétées par Amazon en tête)."""
    fetch = fetch or fetch_suggestions
    out = [validate_niche(c, fetch, max_queries=max_queries, pause=pause) for c in candidates]
    out.sort(key=lambda v: (v.validated, v.demand_score), reverse=True)
    return out
