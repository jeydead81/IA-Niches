from datetime import date

from cost_tracker import CostTracker, llm_cost_usd, dataforseo_cost_usd


def test_dataforseo_cost():
    assert dataforseo_cost_usd(6, priority=2) == 6 * 0.003
    assert dataforseo_cost_usd(18, priority=1) == 18 * 0.0015


def test_llm_cost_sonnet_intro_vs_standard():
    intro = llm_cost_usd("claude-sonnet-5", 1_000_000, 1_000_000, today=date(2026, 7, 9))
    std = llm_cost_usd("claude-sonnet-5", 1_000_000, 1_000_000, today=date(2026, 9, 1))
    assert intro == 2.0 + 10.0
    assert std == 3.0 + 15.0


def test_tracker_aggregates():
    t = CostTracker(today=date(2026, 7, 9))
    t.add_dataforseo(2, priority=2)
    t.add_dataforseo(3, priority=1)
    t.add_llm("claude-sonnet-5", 1200, 1500)
    b = t.breakdown()
    assert b["dataforseo_calls"] == 5
    assert round(t.total_usd(), 6) == round(b["usd"], 6)
    assert b["usd"] > 0
