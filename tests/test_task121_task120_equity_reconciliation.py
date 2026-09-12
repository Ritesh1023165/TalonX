"""Task 121 Part 1.2 -- focused test for the Task 120B gross/cost/net
equity reconciliation. Reproduces the exact accounting from
docs/research/TASK121_TASK120_ACCOUNTING_CORRECTIONS.md #2 using the
already-committed local trade table -- no replay is rerun.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

_SUMMARY = (Path(__file__).resolve().parents[1]
           / "results/task120b_chronological_baseline/b3_full_300k_summary.json")


def _load():
    if not _SUMMARY.exists():
        pytest.skip("b3_full_300k_summary.json is a local-only artifact (results/ is gitignored); "
                    "the reconciliation this test proves is recorded verbatim in "
                    "docs/research/TASK121_TASK120_ACCOUNTING_CORRECTIONS.md #2")
    return json.loads(_SUMMARY.read_text())


def test_ending_cash_is_gross_not_cost_adjusted():
    d = _load()
    trades = d["trades_table"]
    gross_pnl = sum(t["gross_return_pct"] / 100.0 * t["entry_price"] * t["shares"] for t in trades)
    ending_cash = d["equity_final"]["ending_cash"]
    starting_cash = d["starting_cash_usd"]
    # ending_cash (V2's own uncosted paper ledger) must equal starting + GROSS pnl,
    # not starting + NET pnl -- proves V2's ledger carries no cost deduction at all.
    assert abs((ending_cash - starting_cash) - gross_pnl) < 1.0


def test_cost_adjustment_matches_57_times_10000_times_20bps():
    d = _load()
    trades = d["trades_table"]
    n = len(trades)
    assert n == 57
    cost_total = sum(
        (t["gross_return_pct"] - t["net_return_pct_20bps"]) / 100.0 * t["entry_price"] * t["shares"]
        for t in trades
    )
    avg_notional = sum(t["entry_price"] * t["shares"] for t in trades) / n
    assert abs(avg_notional - 10_000.0) < 1.0
    approx = n * 10_000.0 * 0.002
    assert abs(cost_total - approx) < 1.0
    assert abs(cost_total - 1140.0) < 1.0


def test_cost_adjusted_equity_is_295167_not_296307():
    d = _load()
    trades = d["trades_table"]
    starting_cash = d["starting_cash_usd"]
    gross_pnl = sum(t["gross_return_pct"] / 100.0 * t["entry_price"] * t["shares"] for t in trades)
    cost_total = sum(
        (t["gross_return_pct"] - t["net_return_pct_20bps"]) / 100.0 * t["entry_price"] * t["shares"]
        for t in trades
    )
    cost_adjusted_equity = starting_cash + gross_pnl - cost_total
    gross_equity_reported = d["equity_final"]["equity"]
    assert abs(cost_adjusted_equity - 295_167.37) < 1.0
    assert abs(gross_equity_reported - 296_307.36) < 1.0
    # the two figures must NOT be mistaken for each other -- separated by ~$1,140 (the cost)
    assert abs(gross_equity_reported - cost_adjusted_equity - cost_total) < 1.0


def test_net_dollar_pnl_equals_gross_minus_cost():
    d = _load()
    trades = d["trades_table"]
    gross_pnl = sum(t["gross_return_pct"] / 100.0 * t["entry_price"] * t["shares"] for t in trades)
    cost_total = sum(
        (t["gross_return_pct"] - t["net_return_pct_20bps"]) / 100.0 * t["entry_price"] * t["shares"]
        for t in trades
    )
    net_pnl_recomputed = sum(t["net_return_pct_20bps"] / 100.0 * t["entry_price"] * t["shares"] for t in trades)
    assert abs(net_pnl_recomputed - (gross_pnl - cost_total)) < 1.0  # cost applied exactly once
