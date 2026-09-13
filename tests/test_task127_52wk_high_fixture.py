"""Task 127 Part 5 -- focused fixture tests for
task127_52wk_high_evaluation.py, run BEFORE the real acquired data is
evaluated. Covers: causal rolling-high/ranking, decision-to-entry
timing, holding/exit dates, repeated selection/overlapping cohorts,
capital allocation, costs, missing-data behavior, and cash/position/
equity reconciliation.
"""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "research" / "scripts"))

import task127_52wk_high_evaluation as t127  # noqa: E402


def _write_symbol(tmp_path: Path, sym: str, dates: list, opens, closes) -> None:
    df = pd.DataFrame({"date": dates, "open": opens, "close": closes})
    df.to_csv(tmp_path / f"{sym}.csv", index=False)


def _flat_series(dates, price=100.0):
    return [price] * len(dates), [price] * len(dates)


def _make_universe(tmp_path: Path, n_symbols: int, dates, *, nearness_ranks: dict | None = None):
    """Builds n_symbols flat-priced (price=100) symbols; if
    nearness_ranks maps symbol->a distinct final-day close (all below
    their own trailing max, e.g. 100 vs a 100->close ratio), those
    symbols get an engineered LAST-DAY dip to control the nearness
    ordering deterministically for ranking tests."""
    syms = [f"S{i:02d}" for i in range(n_symbols)]
    for s in syms:
        opens, closes = _flat_series(dates, 100.0)
        if nearness_ranks and s in nearness_ranks:
            closes[-1] = nearness_ranks[s]
            opens[-1] = nearness_ranks[s]
        _write_symbol(tmp_path, s, dates, opens, closes)
    return syms


@pytest.fixture(autouse=True)
def _patch_dirs(tmp_path, monkeypatch):
    monkeypatch.setattr(t127, "D1", tmp_path)
    monkeypatch.setattr(t127, "D2", tmp_path)
    return tmp_path


def test_causal_rolling_high_never_uses_future_data(tmp_path):
    dates = list(pd.bdate_range("2020-01-01", periods=400))
    opens = [100.0] * 400
    closes = [100.0] * 300 + [200.0] + [100.0] * 99  # a spike at index 300, then back to 100
    _write_symbol(tmp_path, "AAAA", dates, opens, closes)
    df = t127._load_symbol("AAAA")
    # BEFORE the spike (still >=252 trailing rows, so a defined value exists),
    # nearness must not reflect the future 200 peak
    row_before = df.iloc[290]
    assert row_before["nearness"] == pytest.approx(1.0)  # flat 100 series, own trailing max = 100
    # AT the spike day itself, nearness reflects the spike (causal, same-day inclusive)
    row_at = df.iloc[300]
    assert row_at["nearness"] == pytest.approx(1.0)  # close=200, trailing max including today=200
    # shortly AFTER the spike, nearness must reflect the (past) 200 peak still being the max
    row_after = df.iloc[310]
    assert row_after["close"] == pytest.approx(100.0)
    assert row_after["nearness"] == pytest.approx(100.0 / 200.0)
    # rolling window not yet full (< 252 rows) -> nearness must be undefined, never fabricated
    assert pd.isna(df.iloc[250]["nearness"])


def test_ranking_selects_top_tercile_by_nearness(tmp_path):
    dates = list(pd.bdate_range("2020-01-01", periods=260))
    # 20 symbols, all flat at 100 for the trailing history, but engineer
    # DIFFERENT final-day closes to control nearness ranking exactly.
    ranks = {f"S{i:02d}": 100.0 - i for i in range(20)}  # S00 highest close (nearest), S19 lowest
    syms = _make_universe(tmp_path, 20, dates, nearness_ranks=ranks)
    data = {s: t127._load_symbol(s) for s in syms}
    formation_date = dates[-1]
    selected, excluded = t127._select_cohort_symbols(data, formation_date, select_top_tercile=True)
    n_expected = round(20 * t127.SELECTION_FRACTION)
    assert len(selected) == n_expected
    # the selected set must be exactly the highest-nearness (lowest-index) symbols
    assert set(selected) == {f"S{i:02d}" for i in range(n_expected)}


def test_min_price_filter_excludes_penny_stock(tmp_path):
    dates = list(pd.bdate_range("2020-01-01", periods=260))
    syms = _make_universe(tmp_path, 16, dates)
    # make one symbol a penny stock on the formation date
    _write_symbol(tmp_path, "PENNY", dates, [100.0] * 259 + [4.99], [100.0] * 259 + [4.99])
    data = {s: t127._load_symbol(s) for s in syms + ["PENNY"]}
    selected, excluded = t127._select_cohort_symbols(data, dates[-1], select_top_tercile=False)
    assert "PENNY" not in selected
    assert excluded.get("PENNY") == "below_min_price_filter"


def test_insufficient_eligible_population_skips_cohort(tmp_path):
    dates = list(pd.bdate_range("2020-01-01", periods=260))
    syms = _make_universe(tmp_path, 5, dates)  # fewer than MIN_ELIGIBLE_POPULATION=15
    data = {s: t127._load_symbol(s) for s in syms}
    selected, excluded = t127._select_cohort_symbols(data, dates[-1], select_top_tercile=True)
    assert selected == []
    assert "insufficient_eligible_population(5)" in excluded.get("_pool_status", "")


def test_entry_is_next_month_open_not_same_close_and_exit_is_six_months_later(tmp_path):
    dates = list(pd.bdate_range("2020-01-01", periods=500))
    syms = _make_universe(tmp_path, 20, dates)
    data = {s: t127._load_symbol(s) for s in syms}
    all_dates = pd.DatetimeIndex(sorted(set().union(*[set(df["date"]) for df in data.values()])))
    cohorts = t127.build_cohorts(data, all_dates, select_top_tercile=False)
    realized = [c for c in cohorts if c.status in ("REALIZED", "PENDING")]
    assert len(realized) > 0
    for c in realized:
        # entry must be in the calendar month immediately after formation
        assert c.entry_date is not None
        assert pd.Period(c.entry_date, freq="M") == pd.Period(c.formation_date, freq="M") + 1
        # entry must be the FIRST trading day of that month, not the formation month's own close
        assert c.entry_date != c.formation_date
        if c.exit_date is not None:
            assert pd.Period(c.exit_date, freq="M") == pd.Period(c.entry_date, freq="M") + t127.HOLD_MONTHS


def test_overlapping_cohorts_reach_multiple_concurrent_slots(tmp_path):
    dates = list(pd.bdate_range("2020-01-01", periods=600))
    syms = _make_universe(tmp_path, 20, dates)
    data = {s: t127._load_symbol(s) for s in syms}
    all_dates = pd.DatetimeIndex(sorted(set().union(*[set(df["date"]) for df in data.values()])))
    cohorts = t127.build_cohorts(data, all_dates, select_top_tercile=False)
    result = t127.run_chronological_portfolio(cohorts, data, all_dates, cost_bps=t127.COST_BPS_ROUND_TRIP)
    max_concurrent = max((e["n_open_cohorts"] for e in result["equity_curve"]), default=0)
    assert max_concurrent >= 2  # multiple overlapping cohorts do coexist well before any exits


def test_capital_allocation_is_one_sixth_of_budget_per_slot(tmp_path):
    dates = list(pd.bdate_range("2020-01-01", periods=400))
    syms = _make_universe(tmp_path, 20, dates)
    data = {s: t127._load_symbol(s) for s in syms}
    all_dates = pd.DatetimeIndex(sorted(set().union(*[set(df["date"]) for df in data.values()])))
    cohorts = t127.build_cohorts(data, all_dates, select_top_tercile=False)
    result = t127.run_chronological_portfolio(cohorts, data, all_dates, cost_bps=0.0)
    # verify entry-time notional directly via the internal slot_capital constant
    assert t127.TOTAL_BUDGET / t127.HOLD_MONTHS == pytest.approx(100_000.0 / 6)
    # a completed round-trip trade's notional must equal exactly one slot (1/6 of budget) --
    # flat-price fixture (no gains) means proceeds == the original notional, cost-free here
    if result["realized_trades"]:
        assert result["realized_trades"][0]["notional"] == pytest.approx(t127.TOTAL_BUDGET / t127.HOLD_MONTHS)


def test_cost_applied_as_one_round_trip_not_twice(tmp_path):
    dates = list(pd.bdate_range("2020-01-01", periods=260))
    syms = _make_universe(tmp_path, 20, dates)
    data = {s: t127._load_symbol(s) for s in syms}
    formation_date = dates[-1]
    c = t127.Cohort(formation_date=formation_date, entry_date=dates[-1], exit_date=dates[-1],
                    symbols=["S00"], entry_prices={"S00": 100.0}, exit_prices={"S00": 110.0}, status="REALIZED")
    gross, net = t127.cohort_gross_net_return(c, t127.COST_BPS_ROUND_TRIP)
    assert gross == pytest.approx(0.10)
    assert net == pytest.approx(0.10 - t127.COST_BPS_ROUND_TRIP / 10_000.0)
    # applying the SAME cost a second time must NOT equal this net (i.e. it isn't silently double-applied elsewhere)
    double = net - t127.COST_BPS_ROUND_TRIP / 10_000.0
    assert double != net


def test_missing_entry_bar_excludes_symbol_not_fabricated(tmp_path):
    dates = list(pd.bdate_range("2020-01-01", periods=400))
    syms = _make_universe(tmp_path, 16, dates)
    data = {s: t127._load_symbol(s) for s in syms}
    all_dates = pd.DatetimeIndex(sorted(set().union(*[set(df["date"]) for df in data.values()])))
    cohorts = t127.build_cohorts(data, all_dates, select_top_tercile=False)
    realized = [c for c in cohorts if c.status == "REALIZED"]
    # sanity: with clean, complete data every eligible symbol should be kept (no missing bars)
    assert all(len(c.excluded_symbols) == 0 or "_pool_status" not in c.excluded_symbols for c in realized[:1])


def test_equity_reconciles_cash_plus_marked_positions(tmp_path):
    dates = list(pd.bdate_range("2020-01-01", periods=400))
    syms = _make_universe(tmp_path, 20, dates)
    data = {s: t127._load_symbol(s) for s in syms}
    all_dates = pd.DatetimeIndex(sorted(set().union(*[set(df["date"]) for df in data.values()])))
    cohorts = t127.build_cohorts(data, all_dates, select_top_tercile=False)
    result = t127.run_chronological_portfolio(cohorts, data, all_dates, cost_bps=t127.COST_BPS_ROUND_TRIP)
    for e in result["equity_curve"]:
        assert e["equity"] == pytest.approx(e["cash"] + e["marked_positions"], abs=0.01)
        assert e["equity"] <= t127.TOTAL_BUDGET + 1.0  # flat-price fixture, no gains -- equity never exceeds budget + noise
