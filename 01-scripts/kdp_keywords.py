"""kdp_keywords.py — les 7 mots-clés backend que l'auteur saisit dans KDP à la publication.

L'angle du module : les concurrents (Publisher Rocket, KDSPY…) génèrent des mots-clés puis
affichent un volume ESTIMÉ. Nous disposons déjà d'un canal gratuit et factuel — l'autocomplete
Amazon.fr — donc on ne devine pas : on demande au LLM ~22 candidats, on les SONDE tous pour
0 $, et un mot-clé qu'Amazon ne complète pas ne monte pas dans les 7.

Les contraintes de KDP sont vérifiées CÔTÉ CODE, jamais seulement demandées au prompt : un
modèle les oublie sous pression, exactement comme il oubliait la taxonomie dans
fiction_ideator."""
import os
import re
import unicodedata

from dotenv import load_dotenv

from models import MotsClesKDP, ScoredNiche

DEFAULT_MODEL = os.getenv("KDP_KEYWORDS_MODEL", "claude-sonnet-5")

# Contrainte dure d'Amazon : au-delà, la fin de l'expression est tronquée EN SILENCE.
LIMITE_CARACTERES = 50
N_EMPLACEMENTS = 7

# Proscrits par les conditions KDP, ou sans valeur parce qu'Amazon les indexe déjà de
# toute façon (le format, la boutique). Un emplacement gaspillé sur « livre » est un
# emplacement de moins sur une vraie requête — et il n'y en a que sept.
TERMES_INTERDITS = frozenset({
    "livre", "livres", "ebook", "ebooks", "kindle", "broche", "broché", "roman gratuit",
    "gratuit", "gratuite", "promo", "promotion", "solde", "soldes",       # prix / offre
    "meilleur", "meilleure", "meilleurs", "top", "numero 1", "numéro 1",  # superlatifs
    "nouveau", "nouvelle", "nouveaute", "nouveauté", "2024", "2025", "2026",  # temporel
    "amazon", "bestseller", "best seller",
})


def _normalise(s: str) -> str:
    """Casse, espaces multiples et accents dépouillés — sert à comparer, jamais à afficher."""
    plat = unicodedata.normalize("NFKD", s or "")
    plat = "".join(c for c in plat if not unicodedata.combining(c))
    return " ".join(plat.split()).casefold()


def _mots(s: str) -> set[str]:
    return {m for m in re.split(r"[^\w]+", _normalise(s)) if len(m) > 2}


def nettoyer_candidats(candidats, titre: str = "") -> tuple[list[str], list[tuple[str, str]]]:
    """Applique les règles KDP. Rend (gardés, [(rejeté, motif)]).

    Les rejets sortent AVEC leur motif : un mot-clé écarté en silence est une décision
    invisible pour l'auteur, qui ne peut ni la comprendre ni la contester (CLAUDE.md §10)."""
    mots_titre = _mots(titre)
    gardes: list[str] = []
    rejets: list[tuple[str, str]] = []
    vus: set[str] = set()

    for brut in candidats or []:
        if not isinstance(brut, str):
            continue
        k = " ".join(brut.split())
        if not k:
            continue
        norme = _normalise(k)

        if norme in vus:
            rejets.append((k, "doublon"))
            continue
        if len(k) > LIMITE_CARACTERES:
            rejets.append((k, f"{len(k)} caractères — la limite KDP est de "
                              f"{LIMITE_CARACTERES}, Amazon tronquerait la fin"))
            continue

        interdit = next((t for t in TERMES_INTERDITS if t in norme), None)
        if interdit:
            rejets.append((k, f"terme proscrit ou déjà indexé par Amazon : « {interdit} »"))
            continue

        # Tous les mots significatifs déjà dans le titre -> l'emplacement n'apporterait rien.
        significatifs = _mots(k)
        if mots_titre and significatifs and significatifs <= mots_titre:
            rejets.append((k, "déjà présent dans le titre — Amazon l'indexe déjà"))
            continue

        vus.add(norme)
        gardes.append(k)

    return gardes, rejets
