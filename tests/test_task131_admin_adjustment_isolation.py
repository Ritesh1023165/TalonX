"""
Task 131 Remediation Directive 5 -- an administrative ledger adjustment
(e.g. the SPCX stranded-position migration) must never be counted as a
trading outcome in win rate / profit factor / net expectancy / trade
counts, while remaining fully visible (never silently discarded).
"""
from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

import pytest

from talonx_ops.paper_performance import (
    ADMINISTRATIVE_ADJUSTMENT_EXIT_REASON_PREFIX,
    build_paper_performance,
)

from tests.test_task119_paper_performance import _empty_home, _mk_paper_db, _mk_v2_db

NOW = datetime(2026, 9, 13, 20, 0, 0, tzinfo=timezone.utc)


def test_administrative_closure_excluded_from_trade_counts_and_pnl_check(tmp_path):
    assert ADMINISTRATIVE_ADJUSTMENT_EXIT_REASON_PREFIX == "administrative_"
    home = _empty_home(tmp_path, "home")
    exp = _empty_home(tmp_path, "exp")
    _mk_paper_db(home / "paper_trading.db", initial_balance=10_000, current_cash=10_000)
    _mk_paper_db(
        exp / "experimental_paper.db", initial_balance=100_000, current_cash=99_675.53378397295,
        total_realized_pnl_usd=-324.4662160270568, win_count=0, loss_count=4,
        trade_history=[
            # a normal, real closed trade
            ("VRT", "BUY", 274.55852115631103, 9.105526899952618, 2500.0, None, None, None, None,
             None, 97500.0, "2026-09-09T15:03:34.471751+00:00"),
            ("VRT", "SELL", 251.0872125, 9.105526899952618, 2500.0, 274.55852115631103,
             -213.71863234713055, -8.548745293885235, "confirmed_bearish", 161416.528249,
             99786.28136765287, "2026-09-11T07:53:51-04:00"),
            # the administrative SPCX closure -- BUY row omitted (the
            # migration only ever inserts a SELL for an already-open
            # position), zero realized P&L, distinctly tagged.
            ("SPCX", "SELL", 148.2276, 16.865960067130683, 2500.0, 148.2276, 0.0, 0.0,
             "administrative_force_close_task131", 242352.015372, 99675.53378397295,
             "2026-09-13T14:48:57+00:00"),
        ],
    )
    _mk_v2_db(tmp_path / "v2_lane.db", cash=300_000)

    out = build_paper_performance(home=home, exp_home=exp, v2_db=tmp_path / "v2_lane.db",
                                   now=NOW, check_processes=False)
    e = out["lanes"]["experimental"]

    # the real trade is still fully present
    symbols_in_closed = {ct["symbol"] for ct in e["closed_trades"]}
    assert symbols_in_closed == {"VRT"}
    assert "SPCX" not in symbols_in_closed

    # trade counts exclude the administrative row
    assert e["trade_counts"]["exits_campaign_to_date"] == 1

    # the P&L cross-check sums only the real trade's own realized P&L
    assert e["realized_pnl"]["row_sum_cross_check"] == pytest.approx(-213.71863234713055)

    # never silently discarded -- reported explicitly, separately
    admin = e["administrative_adjustments"]
    assert len(admin) == 1
    assert admin[0]["symbol"] == "SPCX"
    assert admin[0]["exit_reason"] == "administrative_force_close_task131"
    assert admin[0]["realized_pnl_usd"] == 0.0


def test_no_administrative_rows_yields_an_empty_list_not_missing_key(tmp_path):
    home = _empty_home(tmp_path, "home")
    exp = _empty_home(tmp_path, "exp")
    _mk_paper_db(home / "paper_trading.db", initial_balance=10_000, current_cash=10_000)
    _mk_paper_db(exp / "experimental_paper.db", initial_balance=100_000, current_cash=100_000)
    _mk_v2_db(tmp_path / "v2_lane.db", cash=300_000)
    out = build_paper_performance(home=home, exp_home=exp, v2_db=tmp_path / "v2_lane.db",
                                   now=NOW, check_processes=False)
    assert out["lanes"]["experimental"]["administrative_adjustments"] == []
    assert out["lanes"]["original"]["administrative_adjustments"] == []
