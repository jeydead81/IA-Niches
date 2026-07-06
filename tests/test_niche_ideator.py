from niche_ideator import build_user_prompt, generate_niches, SYSTEM_PROMPT
from models import NicheCandidate


# ── Client Anthropic factice (aucun réseau) ───────────────────────────────────
class _FakeToolUse:
    type = "tool_use"

    def __init__(self, input):
        self.input = input


class _FakeResp:
    def __init__(self, content):
        self.content = content


class _FakeMessages:
    def __init__(self, outer):
        self._outer = outer

    def create(self, **kwargs):
        self._outer.captured = kwargs
        return _FakeResp([_FakeToolUse(self._outer.payload)])


class FakeClient:
    def __init__(self, payload):
        self.payload = payload
        self.captured = {}
        self.messages = _FakeMessages(self)


_PAYLOAD = {"niches": [
    {"niche": "tarot", "requete_amazon": "tarot",
     "satellite_keywords": ["tarot débutant", "tarot de marseille"],
     "rationale": "Univers ésotérique très cherché, evergreen.", "categorie": "ésotérisme",
     "risques": []},
    {"niche": "jeûne intermittent", "requete_amazon": "jeûne intermittent",
     "satellite_keywords": ["jeûne 16/8"],
     "rationale": "Santé grand public, evergreen.", "categorie": "santé",
     "risques": []},
]}


def test_build_user_prompt_seed_mode_contains_seed_and_count():
    p = build_user_prompt("ésotérisme", None, 12)
    assert "ésotérisme" in p
    assert "12" in p


def test_build_user_prompt_scratch_mode_uses_signals():
    p = build_user_prompt(None, {"jeûne intermittent": 5, "microbiote": 3}, 10)
    assert "jeûne intermittent" in p
    assert "graine" in p.lower()  # indique le mode "à partir de rien"


def test_system_prompt_encodes_key_constraints():
    low = SYSTEM_PROMPT.lower()
    assert "evergreen" in low or "saisonnier" in low
    assert "livre" in low
    assert "impartial" in low or "aucun domaine" in low  # aucun biais de domaine
    assert "pharmac" not in low             # l'angle pharmacien a été retiré
    assert "musulmane" in low or "exclusions" in low  # exclusions §4.4


def test_generate_niches_returns_validated_candidates():
    fake = FakeClient(_PAYLOAD)
    out = generate_niches(seed="ésotérisme", n=2, client=fake)
    assert len(out) == 2
    assert all(isinstance(x, NicheCandidate) for x in out)
    assert out[0].niche == "tarot"
    assert out[1].niche == "jeûne intermittent"


def test_generate_niches_wires_prompt_and_tool_choice():
    fake = FakeClient(_PAYLOAD)
    generate_niches(seed="ésotérisme", n=2, model="claude-sonnet-5", client=fake)
    kw = fake.captured
    assert kw["model"] == "claude-sonnet-5"
    assert kw["tool_choice"] == {"type": "tool", "name": "proposer_niches"}
    assert "ésotérisme" in kw["messages"][0]["content"]


def test_generate_niches_empty_when_no_tool_use():
    class NoTool(FakeClient):
        pass
    fake = NoTool(_PAYLOAD)
    # remplace la réponse par un contenu sans tool_use
    fake.messages.create = lambda **kw: _FakeResp([])
    assert generate_niches(seed="x", client=fake) == []
