"""cost_tracker.py — coût réel d'un run : appels DataForSEO ($) + tokens LLM (usage Anthropic).
Remplace l'ancien credits_tracker (Scrapingdog, mort). Brique de facturation en crédits."""
import os
from datetime import date

from search_providers import COST_PER_CALL_USD

# Plafond de coût PAR RUN. Distinct de PLAFOND_ANALYSES_MENSUEL, qui compte des runs :
# les bornes de volume (MAX_RECHERCHES…) bornent ce qui est DEMANDÉ, jamais ce qui est
# DÉPENSÉ. Un run borné à 6 niches paie quand même 6 SERP + le batch ASIN + les tokens.
# 0,60 $ = ~7x un scout non-fiction serveur (0,084 $) et ~1,5x un run fiction 8 trios
# (0,409 $) : assez haut pour ne jamais couper un run nominal, assez bas pour qu'une
# boucle qui dérape s'arrête avant de coûter un abonnement.
PLAFOND_USD_PAR_RUN_DEFAUT = 0.60


class PlafondCoutAtteint(RuntimeError):
    """Levée ENTRE deux phases payantes, jamais au milieu d'une. L'orchestrateur
    l'attrape et clôture le run sur un rapport partiel (§5.29) : ce qui a été mesuré est
    rendu, ce qui ne l'a pas été est annoncé comme non traité — jamais comme mesuré."""


def _plafond_par_defaut() -> float:
    """Une saisie fautive retombe sur le défaut plutôt que de faire planter tous les
    runs — même posture que _plafond_analyses_mensuel côté serveur."""
    try:
        return float(os.getenv("PLAFOND_USD_PAR_RUN", "") or PLAFOND_USD_PAR_RUN_DEFAUT)
    except ValueError:
        return PLAFOND_USD_PAR_RUN_DEFAUT

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
    def __init__(self, today: date | None = None, plafond_usd: float | None = -1.0):
        # -1.0 = sentinelle « non précisé » → on lit l'environnement. `None` explicite
        # signifie « aucun plafond » : c'est le comportement historique, que les runs CLI
        # et les tests existants doivent pouvoir garder mot pour mot.
        self.plafond_usd = _plafond_par_defaut() if plafond_usd == -1.0 else plafond_usd
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

    @property
    def plafond_atteint(self) -> bool:
        return self.plafond_usd is not None and self.total_usd() >= self.plafond_usd

    def verifier(self, cout_prevu: float = 0.0) -> None:
        """À appeler AVANT chaque phase payante, jamais après : vérifier après coup
        signalerait un dépassement déjà payé.

        `cout_prevu` rend le plafond PRÉDICTIF là où le tarif est connu d'avance — une
        SERP DataForSEO vaut 0,003 $ (`COST_PER_CALL_USD`), donc rien n'oblige à la payer
        pour découvrir qu'elle faisait franchir la ligne. Sans lui, le plafond n'est
        qu'un constat a posteriori et se dépasse toujours d'une phase. Il reste à 0 pour
        les postes dont le prix ne s'annonce pas (tokens LLM) : là, le plafond est un
        constat, et le dépassement est borné par la taille d'un lot."""
        if self.plafond_usd is None:
            return
        if self.total_usd() + cout_prevu >= self.plafond_usd:
            raise PlafondCoutAtteint(
                f"plafond de coût atteint : {self.total_usd():.4g} $ dépensés sur un "
                f"plafond de {self.plafond_usd:.4g} $ (PLAFOND_USD_PAR_RUN)")

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
