"""Durées de cache — le levier d'économie le plus direct du produit.

Le cache est MUTUALISÉ entre tous les comptes (`cache.py:1`) : deux clients qui analysent
le même rayon ne le paient qu'une fois. Allonger sa durée multiplie mécaniquement cet
effet, et c'est gratuit — au sens propre.

Ce que ça coûte en échange : de la fraîcheur. Un BSR de 15 jours a bougé. Mais le produit
ne prétend pas mesurer un classement à la journée : il compare des ORDRES DE GRANDEUR
(sous 10 000, sous 50 000, au-dessus de 50 000). Un rayon ne change pas de tranche en deux
semaines. C'est ce qui rend l'arbitrage soutenable.

Ces durées vivent dans QUATRE fichiers différents. Ce test les tient ensemble : sans lui,
en allonger trois sur quatre passerait inaperçu.
"""
import re
from pathlib import Path

import pytest

RACINE = Path(__file__).resolve().parent.parent
JOURS = 24 * 3600
TTL_COMMUN_J = 30      # 15 jusqu'au 2026-10-05, 30 sur décision de Baptiste


def _const(fichier: str, nom: str) -> float:
    src = (RACINE / fichier).read_text(encoding="utf-8")
    m = re.search(rf"^{nom}\s*=\s*(\d+)\s*\*\s*24\s*\*\s*3600", src, re.M)
    assert m, f"{nom} introuvable dans {fichier}"
    return int(m.group(1))


@pytest.mark.parametrize("fichier,nom", [
    ("01-scripts/cache.py", "BOOK_TTL_S"),
    ("01-scripts/cache.py", "AUTOCOMPLETE_TTL_S"),
    ("01-scripts/bsr_source.py", "BSR_TTL_S"),
    ("01-scripts/autocomplete_expand.py", "AUTOCOMPLETE_TTL_S"),
])
def test_les_caches_courants_tiennent_30_jours(fichier, nom):
    assert _const(fichier, nom) == TTL_COMMUN_J


@pytest.mark.parametrize("module", ["scout_master", "lowcontent_master"])
def test_le_cache_de_serp_tient_30_jours(module):
    assert _const(f"01-scripts/{module}.py", "_SEARCH_TTL_S") == TTL_COMMUN_J


def test_la_classification_garde_ses_30_JOURS():
    """Elle n'est PAS ramenée à 15 : ce serait une régression déguisée en harmonisation.

    Sa clé porte déjà tout ce qui peut invalider le résultat — ASIN, version de taxonomie,
    modèle, SHA1 du prompt système, empreinte des champs (§5.14). Une quatrième de
    couverture ne change pas, et le seul événement qui rend sa lecture caduque est un
    changement de prompt ou de taxo, que la clé capte déjà. La raccourcir ferait re-payer
    le poste LLM DOMINANT du scout fiction pour rien."""
    assert _const("01-scripts/cache.py", "CLASSIFICATION_TTL_S") == 30
