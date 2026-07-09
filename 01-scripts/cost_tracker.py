"""cost_tracker.py — coût réel d'un run : appels DataForSEO ($) + tokens LLM (usage Anthropic).
Remplace l'ancien credits_tracker (Scrapingdog, mort). Brique de facturation en crédits."""
from datetime import date

from search_providers import COST_PER_CALL_USD

# $/million de tokens (input, output). Sonnet 5 : tarif intro jusqu'au 31/08/2026, puis standard.
_LLM_PRICES = {
    "claude-sonnet-5": {"in": 2.0, "out": 10.0, "in_std": 3.0, "out_std": 15.0,
                        "intro_until": date(2026, 8, 31)},
    "claude-opus-4-8": {"in": 5.0, "out": 25.0},
    "claude-fable-5": {"in": 10.0, "out": 50.0},
    "claude-haiku-4-5": {"in": 1.0, "out": 5.0},
}


def dataforseo_cost_usd(n_calls: int, priority: int) -> float:
    return n_calls * COST_PER_CALL_USD.get(priority, 0.003)


def llm_cost_usd(model: str, in_tok: int, out_tok: int, today: date | None = None) -> float:
    p = _LLM_PRICES.get(model)
    if not p:
        return 0.0
    today = today or date.today()
    if "intro_until" in p and today > p["intro_until"]:
        p_in, p_out = p["in_std"], p["out_std"]
    else:
        p_in, p_out = p["in"], p["out"]
    return (in_tok * p_in + out_tok * p_out) / 1_000_000


class CostTracker:
    def __init__(self, today: date | None = None):
        self.today = today
        self._df: list[tuple[int, int]] = []      # (n_calls, priority)
        self._llm: list[tuple[str, int, int]] = []  # (model, in, out)

    def add_dataforseo(self, n_calls: int, priority: int) -> None:
        if n_calls:
            self._df.append((n_calls, priority))

    def add_llm(self, model: str, in_tok: int, out_tok: int) -> None:
        self._llm.append((model, in_tok or 0, out_tok or 0))

    def total_usd(self) -> float:
        df = sum(dataforseo_cost_usd(n, p) for n, p in self._df)
        llm = sum(llm_cost_usd(m, i, o, self.today) for m, i, o in self._llm)
        return df + llm

    def breakdown(self) -> dict:
        df = sum(dataforseo_cost_usd(n, p) for n, p in self._df)
        llm = sum(llm_cost_usd(m, i, o, self.today) for m, i, o in self._llm)
        return {
            "usd": round(df + llm, 4),
            "dataforseo_usd": round(df, 4),
            "llm_usd": round(llm, 4),
            "dataforseo_calls": sum(n for n, _ in self._df),
            "llm_tokens_in": sum(i for _, i, _ in self._llm),
            "llm_tokens_out": sum(o for _, _, o in self._llm),
        }
