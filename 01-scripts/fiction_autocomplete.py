"""fiction_autocomplete.py — sonde de demande GRATUITE pour une niche fiction.

Soft signal : le spike M0 §V3 a mesuré que les trios trope × décor précis ne remontent
rien dans l'autocomplete alors que les requêtes commerciales larges sont riches. Un 0 ne
veut donc PAS dire « niche morte » — d'où l'échelle à deux barreaux (le sous-genre est-il
lui-même cherché ?) et l'interdiction faite à M5 de gater sur ce seul score."""
import time

import requests

from amazon_autocomplete import AutocompleteError, fetch_json_strict, parse_suggestions
from fiction_taxonomy import sous_genre
from models import AutocompleteProbe, AutocompleteSignal, FictionNiche


def score_suggestions(requete: str, suggestions: list[str]) -> float:
    """Barème 0 / 0,5 / 1 calé sur les mesures live du spike (§V3)."""
    p = AutocompleteProbe(requete=requete, suggestions=suggestions)
    if len(p.extras) >= 2:
        return 1.0
    if p.extras or p.echo:
        return 0.5
    return 0.0


def _sonde(requete: str, fetch_json, pause: float) -> AutocompleteProbe:
    if pause:
        time.sleep(pause)
    try:
        return AutocompleteProbe(requete=requete,
                                 suggestions=parse_suggestions(fetch_json(requete)))
    except (AutocompleteError, requests.RequestException) as e:
        # util.http_get RE-LÈVE après ses retries : sans RequestException ici, un timeout
        # DNS tuerait le run au lieu de produire mesure=False. On ne l'attrape PAS dans
        # fetch_json_strict, sinon fetch_suggestions (scout non-fiction, en production)
        # rendrait une panne réseau comme « 0 suggestion » et invaliderait la niche.
        return AutocompleteProbe(requete=requete, echec=True,
                                 erreur=f"{type(e).__name__}: {e}")


def probe_niche(niche: FictionNiche, fetch_json=None, pause: float = 0.4,
                version: str = "fr_v1") -> AutocompleteSignal:
    """Sonde la requête du trio, puis — seulement si elle ne donne rien — la requête
    canonique du sous-genre, pour distinguer « trio trop précis » de « sous-genre fantôme »."""
    fetch_json = fetch_json or fetch_json_strict
    # FictionNiche.query a un défaut vide et n'est jamais vérifiée côté code : sans ce
    # garde, un trio dont le LLM a omis la requête décroche 1.0 (toute suggestion compte
    # comme « extra » puisqu'aucune ne peut être l'écho de "").
    if not niche.query.strip():
        return AutocompleteSignal(niche_query=niche.query)   # mesure=False par défaut

    p1 = _sonde(niche.query, fetch_json, pause)
    sig = AutocompleteSignal(niche_query=niche.query, probes=[p1])
    if p1.echec:
        return sig                      # mesure reste False : rien n'a été mesuré
    sig.mesure = True
    sig.score = score_suggestions(niche.query, p1.suggestions)
    if sig.score > 0:
        return sig                      # inutile de payer le contexte : le trio parle déjà

    large = (sous_genre(niche.sous_genre, version).get("query_fr") or "").strip()
    if not large:
        return sig                      # sous-genre sans requête canonique : rien à sonder
    if AutocompleteProbe._norm(large) == AutocompleteProbe._norm(niche.query):
        # le barreau 1 ÉTAIT la requête canonique et il a rendu 0 : le sous-genre vient
        # d'être mesuré à zéro. C'est l'alerte, pas une absence d'information.
        sig.sous_genre_cherche = False
        return sig
    p2 = _sonde(large, fetch_json, pause)
    sig.probes.append(p2)
    if not p2.echec:
        sig.sous_genre_cherche = score_suggestions(large, p2.suggestions) > 0
    return sig
