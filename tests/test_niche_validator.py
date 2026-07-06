from niche_validator import validate_niche, validate_niches
from models import NicheCandidate


def _cand(niche, sats=None, requete=None):
    return NicheCandidate(niche=niche, requete_amazon=requete or niche,
                          satellite_keywords=sats or [], rationale="r", categorie="c")


def test_validate_niche_flags_and_dedupes():
    # Amazon auto-complète tout ce qui contient "tarot", rien d'autre
    def fake(q):
        return ["tarot débutant", "tarot de marseille"] if "tarot" in q.lower() else []

    v = validate_niche(_cand("tarot", ["tarot débutant"]), fake)
    assert v.validated is True
    assert v.queries_hit == 2                 # "tarot" ET "tarot débutant" prennent
    assert v.demand_score == 2                # suggestions dédupliquées
    assert "tarot de marseille" in v.amazon_suggestions


def test_validate_niche_not_validated_when_amazon_silent():
    v = validate_niche(_cand("angleinexistantxyz", ["autre angle mort"]), lambda q: [])
    assert v.validated is False
    assert v.demand_score == 0
    assert v.queries_hit == 0
    assert v.amazon_suggestions == []


def test_validate_niches_sorts_validated_and_strong_first():
    def fake(q):
        if "fort" in q:
            return ["a", "b", "c"]
        if "faible" in q:
            return ["x"]
        return []

    out = validate_niches([_cand("faible"), _cand("nul"), _cand("fort")],
                          fetch=fake, pause=0)
    assert [v.niche for v in out] == ["fort", "faible", "nul"]
    assert out[0].demand_score == 3
    assert out[-1].validated is False


def test_validate_niche_respects_max_queries():
    calls = []

    def fake(q):
        calls.append(q)
        return ["s"]

    validate_niche(_cand("n", ["a", "b", "c", "d", "e"]), fake, max_queries=3)
    assert len(calls) == 3                     # niche + 2 satellites seulement
