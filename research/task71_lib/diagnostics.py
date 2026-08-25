"""Task71 -- shared cell-level diagnostics: cost sensitivity, PF, bootstrap
CI (clustered by symbol AND by day), concentration, friction absorption.
Bootstrap is computed once on gross returns and cost-shifted arithmetically
(a valid simplification since cost is a deterministic per-trade shift, not
a random variable -- shifting a bootstrap distribution by a constant shifts
its CI by exactly that constant); profit factor is recomputed per cost
level directly (cost changes which trades are winners/losers, so PF is NOT
a simple shift)."""
from __future__ import annotations

import numpy as np
import pandas as pd

from research.task67a_lib.research_stats import bootstrap_ci_clustered, concentration_metrics

COST_LEVELS_BPS = (0, 5, 10, 15, 20)
PRIMARY_COST_BPS = 10


def net_return(gross_return_pct: pd.Series, cost_bps: float) -> pd.Series:
    return gross_return_pct - (cost_bps / 100.0)  # gross_return_pct already in percent; cost_bps/100 = pct


def profit_factor(net_ret: pd.Series) -> float:
    pos, neg = net_ret[net_ret > 0], net_ret[net_ret <= 0]
    if neg.sum() == 0:
        return float("inf") if pos.sum() > 0 else float("nan")
    return float(pos.sum() / abs(neg.sum()))


def cost_sensitivity_table(trades: pd.DataFrame, return_col: str = "gross_return_pct") -> pd.DataFrame:
    rows = []
    for bps in COST_LEVELS_BPS:
        net = net_return(trades[return_col], bps)
        rows.append({
            "cost_bps": bps, "expectancy_pct": float(net.mean()), "total_return_pct": float(net.sum()),
            "profit_factor": profit_factor(net), "win_rate": float((net > 0).mean()),
        })
    return pd.DataFrame(rows)


def friction_absorption_ratio(gross_expectancy_pct: float, assumed_round_trip_bps: float = PRIMARY_COST_BPS) -> float:
    if assumed_round_trip_bps == 0:
        return float("nan")
    return abs(gross_expectancy_pct) / (assumed_round_trip_bps / 100.0)


def cell_summary(trades: pd.DataFrame, symbol_col: str = "symbol", day_col: str = "trading_day", return_col: str = "gross_return_pct") -> dict:
    """Full diagnostic bundle for one (family, direction, param, horizon)
    cell's trade set. `trades` must already be filtered to data_ready rows
    for exactly this cell."""
    n = len(trades)
    if n == 0:
        return {"n_trades": 0, "insufficient_n": True}
    net10 = net_return(trades[return_col], PRIMARY_COST_BPS)
    result = {
        "n_trades": n,
        "n_symbols": int(trades[symbol_col].nunique()),
        "n_days": int(trades[day_col].nunique()),
        "gross_expectancy_pct": float(trades[return_col].mean()),
        "net_expectancy_10bps_pct": float(net10.mean()),
        "profit_factor_10bps": profit_factor(net10),
        "friction_absorption_ratio": friction_absorption_ratio(float(trades[return_col].mean())),
    }
    cost_table = cost_sensitivity_table(trades, return_col)
    result["cost_sensitivity"] = cost_table.to_dict(orient="records")

    if n >= 5:
        boot_symbol = bootstrap_ci_clustered(trades[return_col].to_numpy(), trades[symbol_col].to_numpy(), n_resamples=2000)
        boot_day = bootstrap_ci_clustered(trades[return_col].to_numpy(), trades[day_col].to_numpy(), n_resamples=2000)
        result["bootstrap_gross_by_symbol"] = boot_symbol.as_dict()
        result["bootstrap_gross_by_day"] = boot_day.as_dict()
        # "Weaker" = the interpretation offering LESS evidence of a nonzero effect,
        # i.e. the one with the lower (more zero-or-negative-inclusive) ci_low.
        weaker = boot_symbol if (boot_symbol.ci_low or 0) < (boot_day.ci_low or 0) else boot_day
        result["weaker_cluster_interpretation"] = "by_symbol" if weaker is boot_symbol else "by_day"

        conc = concentration_metrics(trades.assign(_ret=trades[return_col]), value_col="_ret", symbol_col=symbol_col, day_col=day_col)
        result["top1_symbol_share"] = conc.get("top1_symbol_share")
        result["top3_symbol_share"] = conc.get("top3_symbol_share")
        result["top1_day_share"] = conc.get("best_day_share")
    else:
        result["insufficient_n_for_bootstrap"] = True
    return result
