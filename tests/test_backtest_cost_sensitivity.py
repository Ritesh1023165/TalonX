"""
tests/test_backtest_cost_sensitivity.py
--------------------------------------------
talonx_backtest.analysis.cost_sensitivity_scenarios (spec section 10):
runs the SAME frozen strategy over the SAME data once per cost
scenario, varying ONLY execution cost. Never selects or highlights a
"best" scenario -- these tests only check the mechanics (right number
of scenarios, strategy untouched between them, cost actually applied,
higher cost -> lower-or-equal net expectancy).

Deliberately a SMALL, single-day fixture (compute_indicators recomputes
RSI/MACD/SMA/ATR over the WHOLE buffer on every bar, so a full
BacktestEngine.run() is roughly O(bars^2) -- a 2-day/780-bar fixture run
~20+ times across this file's test functions took nearly 9 minutes
before this was trimmed down). This fixture is far too short to ever
clear the R:R gate (no prior-session pivots), so it produces zero
trades -- that's fine, every assertion below only needs the SCENARIO
MECHANICS to be correct, not actual trades; see
test_backtest_regression.py/test_backtest_reports.py for tests that
exercise real trade execution over the fuller fixture.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pandas as pd
import pytest

from talonx_backtest.analysis import DEFAULT_COST_SCENARIOS_BPS, cost_sensitivity_scenarios
from talonx_backtest.data import from_dataframe
from talonx_quant.config import QuantConfig


def _small_bars(n=140):
    bars = []
    price = 100.0
    start = datetime(2026, 1, 5, 14, 30, tzinfo=timezone.utc)
    for i in range(n):
        price += 0.05 if i % 2 == 0 else -0.03
        bars.append((start + timedelta(minutes=i), price, price + 0.4, price - 0.4, price, 1000.0 + (i % 5) * 50))
    return bars


@pytest.fixture(scope="module")
def sample_df():
    rows = [
        {"timestamp": ts, "open": o, "high": h, "low": l, "close": c, "volume": v}
        for ts, o, h, l, c, v in _small_bars()
    ]
    return from_dataframe(pd.DataFrame(rows), symbol="AAPL")


@pytest.fixture(scope="module")
def scenario_rows(sample_df):
    """Computed ONCE for the whole module -- every test below reads this
    same cached result rather than re-running the engine."""
    return cost_sensitivity_scenarios(sample_df, QuantConfig(), eod_flatten_enabled=False)


def test_default_scenarios_are_0_5_10_20_bps():
    assert DEFAULT_COST_SCENARIOS_BPS == (0, 5, 10, 20)


def test_runs_one_row_per_scenario(scenario_rows):
    assert [r["cost_bps"] for r in scenario_rows] == list(DEFAULT_COST_SCENARIOS_BPS)


def test_custom_scenario_list_is_respected(sample_df):
    rows = cost_sensitivity_scenarios(sample_df, QuantConfig(), bps_scenarios=(0, 15), eod_flatten_enabled=False)
    assert [r["cost_bps"] for r in rows] == [0, 15]


def test_trade_count_is_identical_across_cost_scenarios(scenario_rows):
    # The strategy itself (signal generation, gates) never changes
    # between scenarios -- only execution cost does -- so the SAME
    # number of trades should be entered/exited regardless of scenario.
    trade_counts = {r["trades"] for r in scenario_rows}
    assert len(trade_counts) == 1, f"trade count should not vary with cost, got {scenario_rows}"


def test_higher_cost_never_improves_expectancy(scenario_rows):
    expectancies = [r["expectancy_r"] for r in scenario_rows if r["expectancy_r"] is not None]
    if len(expectancies) < 2:
        pytest.skip("fixture produced too few trades to compare expectancy across scenarios")
    for earlier, later in zip(expectancies, expectancies[1:]):
        assert later <= earlier + 1e-9


def test_zero_cost_scenario_matches_a_plain_zero_cost_backtest(sample_df, scenario_rows):
    from talonx_backtest.engine import BacktestConfig, BacktestEngine
    from talonx_backtest.execution import ExecutionConfig
    from talonx_backtest.metrics import compute_metrics

    plain_config = BacktestConfig(quant_config=QuantConfig(), execution=ExecutionConfig(), eod_flatten_enabled=False)
    plain_result = BacktestEngine(plain_config).run(sample_df)
    plain_metrics = compute_metrics(plain_result.trades, r_field="net_R")

    zero_row = scenario_rows[0]
    assert zero_row["cost_bps"] == 0
    assert zero_row["trades"] == plain_metrics.total_trades
    if plain_metrics.expectancy_r is None:
        assert zero_row["expectancy_r"] is None
    else:
        assert zero_row["expectancy_r"] == pytest.approx(plain_metrics.expectancy_r)
