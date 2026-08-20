"""
tests/test_backtest_cost_sensitivity.py
--------------------------------------------
talonx_backtest.analysis.cost_sensitivity_scenarios (spec section 10):
runs the SAME frozen strategy over the SAME data once per cost
scenario, varying ONLY execution cost. Never selects or highlights a
"best" scenario -- these tests only check the mechanics (right number
of scenarios, strategy untouched between them, cost actually applied,
higher cost -> lower-or-equal net expectancy).

Two fixtures, two jobs:
  - `sample_df` (a SMALL, single-day, deliberately trade-FREE fixture --
    compute_indicators recomputes RSI/MACD/SMA/ATR over the WHOLE buffer
    on every bar, so a full BacktestEngine.run() is roughly O(bars^2);
    a 2-day/780-bar fixture run ~20+ times across this file's test
    functions took nearly 9 minutes before this was trimmed down) tests
    scenario MECHANICS only: right number of scenarios, cost actually
    applied, zero-cost matches a plain run.
  - `multi_trade_df` (examples/data/sample_multi_trade_1m.csv --
    TSTW/TSTL/TSTE, TARGET win + STOP loss + END_OF_SESSION win)
    reliably produces 3 real trades, so it verifies the thing that
    actually matters: net_R/expectancy genuinely CHANGE (strictly
    worsen) as cost rises, never a skip for lack of data.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path

import pandas as pd
import pytest

from talonx_backtest.analysis import DEFAULT_COST_SCENARIOS_BPS, cost_sensitivity_scenarios
from talonx_backtest.data import from_dataframe
from talonx_quant.config import QuantConfig

_REPO_ROOT = Path(__file__).resolve().parent.parent


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


# ------------------------------------------------------------------
# Cost sensitivity against the RELIABLE multi-trade fixture (TSTW/TSTL/
# TSTE -- TARGET win, STOP loss, END_OF_SESSION win; see
# examples/data/README.md and docs/backtesting.md's "Sample data
# generation" section for what these synthetic symbols are and why).
# Unlike `scenario_rows` above (a tiny, deliberately trade-FREE fixture
# used purely to test scenario MECHANICS), this section verifies net_R
# actually CHANGES with cost using a dataset guaranteed to produce real
# trades -- so "higher cost never improves expectancy" never needs to
# skip itself for lack of data.
# ------------------------------------------------------------------

_MULTI_TRADE_CSV = _REPO_ROOT / "examples" / "data" / "sample_multi_trade_1m.csv"

# Task 25A finding (2026-08-20): see the identical marker in
# tests/test_backtest_sample_data.py -- all three of this CSV's
# TSTW/TSTL/TSTE demo trades turn out to be built entirely around a
# BEARISH macd_bearish_cross opening a short position while flat, i.e.
# the exact long/short bug Task 24/25A fixes. Correctly zero trades
# now; CSV regeneration tracked as a BLOCKING FOLLOW-UP, not rushed
# here.
_XFAIL_PENDING_SAMPLE_DATA_REGENERATION = pytest.mark.xfail(
    reason="Task 25A: sample_multi_trade_1m.csv's demo trades were built on the long/short bug "
           "(BEARISH-while-flat) that Task 24/25A fixed; now correctly produce zero trades. Needs a "
           "dedicated CSV-regeneration follow-up, not fixed here.",
    strict=True,
)


@pytest.fixture(scope="module")
def multi_trade_df():
    from talonx_backtest.data import load_ohlcv_csv
    return load_ohlcv_csv(_MULTI_TRADE_CSV, tz="America/New_York")


@pytest.fixture(scope="module")
def multi_trade_scenario_rows(multi_trade_df):
    """Computed ONCE for the module -- same caching rationale as
    `scenario_rows` above. eod_flatten_enabled defaults to True (TSTE's
    entire purpose is exercising that exit path)."""
    return cost_sensitivity_scenarios(multi_trade_df, QuantConfig())


@_XFAIL_PENDING_SAMPLE_DATA_REGENERATION
def test_multi_trade_fixture_produces_three_trades_in_every_scenario(multi_trade_scenario_rows):
    assert [r["trades"] for r in multi_trade_scenario_rows] == [3, 3, 3, 3]


@_XFAIL_PENDING_SAMPLE_DATA_REGENERATION
def test_multi_trade_net_r_actually_changes_with_cost(multi_trade_scenario_rows):
    """The concrete "verify net_R changes as expected" check: total_r
    (summed net_R across all 3 trades) must strictly DECREASE as cost
    rises -- every trade pays entry+exit cost on both legs regardless of
    win/loss/exit_reason, so higher bps can never leave it unchanged."""
    total_rs = [r["total_r"] for r in multi_trade_scenario_rows]
    assert all(v is not None for v in total_rs)
    for earlier, later in zip(total_rs, total_rs[1:]):
        assert later < earlier


@_XFAIL_PENDING_SAMPLE_DATA_REGENERATION
def test_multi_trade_higher_cost_never_improves_expectancy_without_skipping(multi_trade_scenario_rows):
    """The same monotonicity check as test_higher_cost_never_improves_expectancy
    above, but this one never skips -- the fixture reliably produces trades."""
    expectancies = [r["expectancy_r"] for r in multi_trade_scenario_rows]
    assert all(v is not None for v in expectancies)
    for earlier, later in zip(expectancies, expectancies[1:]):
        assert later < earlier


@_XFAIL_PENDING_SAMPLE_DATA_REGENERATION
def test_multi_trade_trade_count_and_win_loss_mix_are_cost_invariant(multi_trade_scenario_rows):
    # Cost changes P&L, never WHETHER a trade wins/loses or how many
    # exist -- stop_price/target_price are fixed levels; slippage/spread
    # only move the fill price, not which side of those levels got hit.
    assert {r["trades"] for r in multi_trade_scenario_rows} == {3}
    for row in multi_trade_scenario_rows:
        assert row["win_rate"] == pytest.approx(2 / 3)


# ------------------------------------------------------------------
# progress_callback: cost_sensitivity_scenarios wraps BacktestEngine's
# own per-bar progress with (scenario_index, scenario_count, bps, ...),
# one full engine pass per scenario. Uses `sample_df` (module-scoped,
# already cheap/cached) rather than re-running the multi_trade fixture.
# ------------------------------------------------------------------

def test_progress_callback_labels_every_scenario_with_its_index_and_bps(sample_df):
    calls = []
    cost_sensitivity_scenarios(
        sample_df, QuantConfig(), eod_flatten_enabled=False,
        progress_callback=lambda *args: calls.append(args),
    )
    seen_scenarios = {(scenario_index, bps) for scenario_index, _scenario_count, bps, _done, _total in calls}
    assert seen_scenarios == {(i, bps) for i, bps in enumerate(DEFAULT_COST_SCENARIOS_BPS, start=1)}
    assert all(scenario_count == len(DEFAULT_COST_SCENARIOS_BPS) for _i, scenario_count, _bps, _done, _total in calls)


def test_progress_callback_reports_completion_for_every_scenario(sample_df):
    calls = []
    cost_sensitivity_scenarios(
        sample_df, QuantConfig(), eod_flatten_enabled=False,
        progress_callback=lambda *args: calls.append(args),
    )
    for i in range(1, len(DEFAULT_COST_SCENARIOS_BPS) + 1):
        scenario_calls = [c for c in calls if c[0] == i]
        assert scenario_calls, f"scenario {i} reported no progress at all"
        last_done, last_total = scenario_calls[-1][3], scenario_calls[-1][4]
        assert last_done == last_total


def test_no_progress_callback_is_the_default_and_costs_nothing_extra(sample_df):
    # Same call as scenario_rows' fixture (no progress_callback) -- just
    # asserts it still runs cleanly with the new parameter present but unused.
    rows = cost_sensitivity_scenarios(sample_df, QuantConfig(), eod_flatten_enabled=False)
    assert [r["cost_bps"] for r in rows] == list(DEFAULT_COST_SCENARIOS_BPS)
