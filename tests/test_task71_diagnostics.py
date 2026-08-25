"""Task71 -- diagnostics.cell_summary: cost sensitivity, PF, and the
weaker-cluster-interpretation selection logic."""
from __future__ import annotations

import numpy as np
import pandas as pd

from research.task71_lib.diagnostics import cell_summary, cost_sensitivity_table, friction_absorption_ratio, profit_factor


def test_profit_factor_all_wins_is_infinite_all_losses_is_zero():
    assert profit_factor(pd.Series([1.0, 2.0, 3.0])) == float("inf")
    assert profit_factor(pd.Series([-1.0, -2.0])) == 0.0


def test_cost_sensitivity_table_monotonically_decreases_expectancy():
    trades = pd.DataFrame({"gross_return_pct": [1.0, 0.5, -0.2, 0.8, -0.1]})
    table = cost_sensitivity_table(trades)
    expectancies = table.sort_values("cost_bps")["expectancy_pct"].tolist()
    assert expectancies == sorted(expectancies, reverse=True)  # strictly non-increasing as cost rises


def test_friction_absorption_ratio_scales_with_cost():
    assert friction_absorption_ratio(0.20, assumed_round_trip_bps=10) == 2.0
    assert friction_absorption_ratio(0.20, assumed_round_trip_bps=20) == 1.0


def test_weaker_cluster_interpretation_picks_the_more_skeptical_ci():
    # 20 symbols x 3 days each, all with a small but consistent positive return
    # EXCEPT one single day is a massive outlier -- this makes the day-clustered
    # CI much wider/more skeptical than the symbol-clustered one.
    rng = np.random.default_rng(0)
    rows = []
    for day in range(20):
        for symbol in range(10):
            ret = 0.1 + rng.normal(0, 0.02)
            if day == 0:
                ret += 5.0  # one day's cluster is a huge outlier
            rows.append({"symbol": f"S{symbol}", "trading_day": f"D{day}", "gross_return_pct": ret})
    trades = pd.DataFrame(rows)
    summary = cell_summary(trades)
    ci_low_symbol = summary["bootstrap_gross_by_symbol"]["ci_low"]
    ci_low_day = summary["bootstrap_gross_by_day"]["ci_low"]
    assert ci_low_day < ci_low_symbol  # day-clustering is the wider/weaker one here
    assert summary["weaker_cluster_interpretation"] == "by_day"
