"""Task 99A -- experimental paper execution boundary. Focused areas:
experimental BUY, SELL closes long only, no short order, paper execution
boundary (isolated DB, no real capital), idempotency, EOD flatten, stop/target.
TEST_FIXTURE_ONLY -- NOT ALPHA EVIDENCE.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from talonx_signals.experimental_paper import ExperimentalPaperEngine

T0 = datetime(2026, 8, 7, 15, 0, tzinfo=timezone.utc)


@pytest.fixture
def eng(tmp_path):
    e = ExperimentalPaperEngine(db_path=tmp_path / "experimental_paper.db",
                                allocation_usd=2500.0, spread_bps=5.0, initial_cash=100_000.0)
    yield e
    e.close()


def test_open_long_creates_a_paper_buy(eng):
    t = eng.open_long("AAPL", 100.0, stop=98.0, target=104.0, now=T0,
                      setup="macd_bullish_cross", setup_score=1, risk_reward_ratio=1.1, atr_pct=0.12)
    assert t is not None
    assert t["side"] == "BUY"
    assert t["profile"] == "EXPERIMENTAL_RELAXED_V1"
    assert t["trade_id"].startswith("X")
    assert t["quantity"] == pytest.approx(2500.0 / t["entry"])
    assert t["entry"] > 100.0  # BUY crosses half the spread
    assert t["admitted_by"].startswith("multiple:")
    assert len(eng.open_positions()) == 1


def test_second_buy_while_long_is_ignored_no_pyramiding(eng):
    eng.open_long("AAPL", 100.0, now=T0)
    again = eng.open_long("AAPL", 101.0, now=T0 + timedelta(minutes=5))
    assert again is None
    assert len(eng.open_positions()) == 1


def test_sell_closes_an_existing_long_only(eng):
    eng.open_long("AAPL", 100.0, stop=98.0, target=104.0, now=T0)
    exit_trade = eng.close_long("AAPL", 103.0, exit_reason="signal_exit", now=T0 + timedelta(minutes=30))
    assert exit_trade["side"] == "SELL"
    assert exit_trade["exit"] < 103.0  # SELL crosses half the spread
    assert exit_trade["gross_pnl"] > 0
    assert exit_trade["net_pnl"] < exit_trade["gross_pnl"]  # friction
    assert exit_trade["r_multiple"] is not None
    assert eng.open_positions() == []


def test_sell_on_a_flat_symbol_never_opens_a_short(eng):
    result = eng.close_long("AAPL", 95.0, exit_reason="signal_exit", now=T0)
    assert result is None
    assert eng.open_positions() == []
    # and no negative / short position exists anywhere
    for pos in eng.open_positions():
        assert pos["shares"] > 0


def test_all_positions_are_strictly_long(eng):
    eng.open_long("AAPL", 100.0, now=T0)
    eng.open_long("MSFT", 50.0, now=T0)
    for pos in eng.open_positions():
        assert pos["shares"] > 0


def test_stop_and_target_exits(tmp_path):
    e = ExperimentalPaperEngine(db_path=tmp_path / "p.db")
    e.open_long("AAPL", 100.0, stop=98.0, target=104.0, now=T0)
    assert e.check_exits("AAPL", 103.0, now=T0 + timedelta(minutes=1)) is None
    hit = e.check_exits("AAPL", 97.5, now=T0 + timedelta(minutes=2))
    assert hit is not None and hit["exit_reason"] == "stop_loss"
    assert e.open_positions() == []
    e.close()


def test_eod_flatten(eng):
    eng.open_long("AAPL", 100.0, stop=98.0, target=110.0, now=T0)
    eng.open_long("MSFT", 50.0, stop=49.0, target=55.0, now=T0)
    exits = eng.flatten_all({"AAPL": 101.0, "MSFT": 49.5}, now=T0 + timedelta(hours=5))
    assert len(exits) == 2
    assert all(x["exit_reason"] == "eod_flatten" for x in exits)
    assert eng.open_positions() == []


def test_isolated_db_path_is_not_the_control_paper_db(tmp_path):
    e = ExperimentalPaperEngine(db_path=tmp_path / "experimental_paper.db")
    resolved = Path(e.store.path).resolve()
    control = (Path.home() / ".talonx" / "paper_trading.db").resolve()
    assert resolved != control
    assert "experimental" in str(resolved).lower() or str(resolved).startswith(str(tmp_path))
    e.close()


def test_no_real_capital_surface(eng):
    """The engine exposes no broker/account/live fields -- it is a local
    SQLite simulation only."""
    for attr in ("broker", "api_key", "account_id", "live", "real_capital", "submit_order"):
        assert not hasattr(eng, attr)


def test_restart_reopens_the_same_ledger(tmp_path):
    p = tmp_path / "experimental_paper.db"
    e1 = ExperimentalPaperEngine(db_path=p)
    e1.open_long("AAPL", 100.0, now=T0)
    e1.close()
    e2 = ExperimentalPaperEngine(db_path=p)
    assert len(e2.open_positions()) == 1
    e2.close()
