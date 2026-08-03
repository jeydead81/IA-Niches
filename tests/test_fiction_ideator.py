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


# ── Trios composés par l'auteur (contraintes) ───────────────────────────────────────

from fiction_ideator import ContraintesTrio, contraintes_impossibles   # noqa: E402
import pytest                                                          # noqa: E402


def _client_qui_capture(payload, vu):
    class _Block:
        type = "tool_use"
        input = payload

    class _Resp:
        content = [_Block()]
        usage = None

    class _Client:
        class messages:
            @staticmethod
            def create(**kw):
                vu.update(kw)
                return _Resp()
    return _Client()


def test_les_contraintes_de_l_auteur_arrivent_dans_le_prompt():
    """L'auteur compose son trio par menus déroulants ; l'IA ne doit plus proposer
    librement mais COMBINER sous ces contraintes. Sans les injecter dans le prompt, les
    menus ne serviraient à rien."""
    p = build_user_prompt("cosy_mystery", n=3, rayon="kindle",
                          contraintes=ContraintesTrio(tropes=["animal_compagnon"],
                                                      decor="village_breton",
                                                      libre="thermalisme"))
    assert "animal_compagnon" in p and "village_breton" in p
    assert "thermalisme" in p
    assert "IMPOS" in p.upper() or "impose" in p.lower()


def test_un_trope_impose_se_retrouve_dans_chaque_trio():
    """Si l'auteur a fixé un trope, un trio qui ne le porte pas ne répond pas à sa demande :
    l'écarter est plus honnête que de lui rendre autre chose que ce qu'il a demandé."""
    vu = {}
    payload = {"trios": [
        {"tropes": ["animal_compagnon", "petite_communaute"], "decor": "village_breton",
         "query": "q1", "rationale": "r"},
        {"tropes": ["petite_communaute"], "decor": "village_breton",     # trope imposé absent
         "query": "q2", "rationale": "r"}]}
    out = generate_trios("cosy_mystery", n=5, client=_client_qui_capture(payload, vu),
                         contraintes=ContraintesTrio(tropes=["animal_compagnon"]))
    assert len(out) == 1 and "animal_compagnon" in out[0].tropes


def test_un_decor_impose_se_retrouve_dans_chaque_trio():
    vu = {}
    payload = {"trios": [
        {"tropes": ["animal_compagnon"], "decor": "village_breton", "query": "q1", "rationale": "r"},
        {"tropes": ["animal_compagnon"], "decor": "campus", "query": "q2", "rationale": "r"}]}
    out = generate_trios("cosy_mystery", n=5, client=_client_qui_capture(payload, vu),
                         contraintes=ContraintesTrio(decor="village_breton"))
    assert len(out) == 1 and out[0].decor == "village_breton"


def test_sans_contrainte_le_comportement_est_inchange():
    """Le mode « propose-moi des trios » doit continuer à fonctionner exactement comme
    avant : les contraintes sont un ajout, pas un remplacement."""
    vu = {}
    payload = {"trios": [
        {"tropes": ["animal_compagnon"], "decor": "village_breton", "query": "q", "rationale": "r"}]}
    assert len(generate_trios("cosy_mystery", n=5,
                              client=_client_qui_capture(payload, vu))) == 1


def test_des_contraintes_sans_trio_plausible_se_disent(tmp_path):
    """LE piège à éviter. Si les contraintes de l'auteur ne laissent aucune combinaison
    crédible, l'IA rend une liste vide — qui se lirait « ce marché est mort ». Or rien n'a
    été mesuré : c'est une impossibilité de COMPOSITION, pas un verdict de marché."""
    vu = {}
    out = generate_trios("cosy_mystery", n=5, client=_client_qui_capture({"trios": []}, vu),
                         contraintes=ContraintesTrio(tropes=["animal_compagnon"],
                                                     decor="village_breton"))
    assert out == []
    assert contraintes_impossibles(out, ContraintesTrio(tropes=["animal_compagnon"])) is True
    assert contraintes_impossibles(out, ContraintesTrio()) is False


def test_un_trope_inconnu_dans_les_contraintes_est_refuse():
    """Les menus viennent de la taxonomie, donc une clé inconnue ne peut venir que d'une
    requête forgée à la main. On refuse explicitement plutôt que de l'ignorer en silence —
    sinon l'auteur croirait sa contrainte appliquée."""
    with pytest.raises(ValueError):
        build_user_prompt("cosy_mystery", n=3,
                          contraintes=ContraintesTrio(tropes=["mafia"]))
