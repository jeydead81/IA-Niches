from fiction_ideator import generate_trios, build_user_prompt
from models import FictionNiche


def test_prompt_contient_la_taxonomie_du_sous_genre():
    p = build_user_prompt("cosy_mystery", n=3, rayon="kindle")
    assert "cosy_mystery" in p and "enquetrice_amatrice" in p and "village_breton" in p
    assert "mafia" not in p


def test_generate_trios_contraint_et_usage():
    class _Usage:
        input_tokens = 700
        output_tokens = 900

    class _Block:
        type = "tool_use"
        input = {"trios": [
            {"tropes": ["animal_compagnon", "petite_communaute"], "decor": "village_breton",
             "query": "cosy mystery chat village breton", "rationale": "r"},
            {"tropes": ["mafia"], "decor": "campus",
             "query": "x", "rationale": "r"}]}

    class _Resp:
        content = [_Block()]
        usage = _Usage()

    class _Client:
        class messages:
            @staticmethod
            def create(**kw):
                assert kw["tool_choice"]["type"] == "tool"
                return _Resp()

    seen = {}
    trios = generate_trios("cosy_mystery", n=2, client=_Client(),
                           on_usage=lambda i, o, m: seen.update(i=i, o=o))
    assert len(trios) == 1
    t = trios[0]
    assert isinstance(t, FictionNiche)
    assert t.sous_genre == "cosy_mystery" and t.decor == "village_breton"
    assert set(t.tropes) <= {"animal_compagnon", "petite_communaute"}
    assert t.rayon == "kindle" and t.marketplace == "fr"
    assert seen == {"i": 700, "o": 900}
