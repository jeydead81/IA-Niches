from amazon_autocomplete import parse_suggestions, fetch_suggestions

# Format réel observé le 2026-07-05
FIXTURE = {"suggestions": [
    {"value": "tarot"},
    {"value": "tarot divinatoire"},
    {"value": "tarot de marseille"},
    {"value": ""},          # vide → ignoré
]}


def test_parse_suggestions_filters_empty():
    out = parse_suggestions(FIXTURE)
    assert out == ["tarot", "tarot divinatoire", "tarot de marseille"]


def test_parse_suggestions_bad_payload():
    assert parse_suggestions({}) == []
    assert parse_suggestions({"suggestions": None}) == []


def test_fetch_suggestions_uses_injected_json():
    out = fetch_suggestions("tarot", fetch_json=lambda prefix: FIXTURE)
    assert "tarot divinatoire" in out
