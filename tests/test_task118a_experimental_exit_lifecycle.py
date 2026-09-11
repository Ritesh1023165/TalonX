"""Task 118A Priority 1 -- the exit lifecycle wiring itself
(ExperimentalLane._maybe_check_exit / _record_experimental_exit, called
from consume()'s market:stream branch). engine.check_exits/close_long's
own dollar-level stop/target math is already covered by
test_task99a_experimental_paper.py::test_stop_and_target_exits -- this
file focuses on what was previously MISSING: the wiring that actually
invokes it live, independent of entry signals, with staleness/atomicity/
idempotency/no-external-send guarantees. TEST_FIXTURE_ONLY -- NOT ALPHA
EVIDENCE.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from talonx_signals.config import ExperimentalConfig
from talonx_signals.dispatcher import ExperimentalDispatcher, NullSender
from talonx_signals.run import ExperimentalLane, _EXIT_TICK_MAX_AGE_SECONDS

T0 = datetime(2026, 9, 9, 15, 3, 34, tzinfo=timezone.utc)


class _SpySender(NullSender):
    """Records every attempted send -- proves the exit path never reaches
    for the transport, not merely that NullSender happens to be a no-op."""

    def __init__(self):
        super().__init__()
        self.calls: list = []

    async def send(self, text, **kwargs):  # pragma: no cover - only hit on failure
        self.calls.append((text, kwargs))
        return await super().send(text, **kwargs)


@pytest.fixture
def lane(tmp_path):
    cfg = ExperimentalConfig(state_dir=tmp_path / "experimental")
    lane = ExperimentalLane(cfg)
    spy = _SpySender()
    lane.dispatcher = ExperimentalDispatcher(store=lane.alert_store, sender=spy,
                                             enable_external_send=False)
    lane._spy_sender = spy
    yield lane
    lane.paper.close()


def _open(lane, symbol="VRT", entry=274.5585, stop=273.6548, target=296.5033, now=T0):
    trade = lane.paper.open_long(symbol, entry, stop=stop, target=target, now=now,
                                 setup="macd_bullish_cross", setup_score=1,
                                 risk_reward_ratio=1.2, atr_pct=0.3)
    assert trade is not None
    lane.alert_store.record_trade(trade)
    return trade


# --------------------------------------------------------------------------- #
# 1. Stop and target exits under the existing (dollar-anchored) policy
# --------------------------------------------------------------------------- #
def test_stop_exit_closes_position_and_updates_display_log(lane):
    _open(lane)
    tick_ts = T0 + timedelta(hours=1)
    lane._maybe_check_exit("VRT", 247.65, tick_ts, now=tick_ts)
    assert lane.paper.store.get_position("VRT") is None
    row = lane.alert_store._conn.execute(
        "SELECT exit, exit_reason, closed_at, net_pnl FROM experimental_trades WHERE symbol='VRT'"
    ).fetchone()
    assert row[0] == pytest.approx(247.65 * (1 - 0.00025))  # SELL-side spread applied, not the raw tick
    assert row[1] == "stop_loss"
    assert row[2] is not None
    assert row[3] is not None and row[3] < 0


def test_target_exit_closes_position(lane):
    _open(lane, symbol="ABT", entry=100.0, stop=98.0, target=104.0)
    tick_ts = T0 + timedelta(hours=1)
    lane._maybe_check_exit("ABT", 105.0, tick_ts, now=tick_ts)
    assert lane.paper.store.get_position("ABT") is None
    row = lane.alert_store._conn.execute(
        "SELECT exit_reason FROM experimental_trades WHERE symbol='ABT'"
    ).fetchone()
    assert row[0] == "target_exit"


def test_price_between_stop_and_target_does_not_exit(lane):
    _open(lane)
    tick_ts = T0 + timedelta(minutes=5)
    lane._maybe_check_exit("VRT", 275.0, tick_ts, now=tick_ts)
    assert lane.paper.store.get_position("VRT") is not None


# --------------------------------------------------------------------------- #
# 2/3. Exit without a fresh entry candidate; entry rejection never blocks it
# --------------------------------------------------------------------------- #
def test_exit_fires_from_a_bare_market_tick_no_candidate_involved(lane):
    _open(lane)
    # No handle_message/_maybe_open_experimental call anywhere in this test --
    # only the market-tick exit path is exercised.
    tick_ts = T0 + timedelta(hours=1)
    lane._maybe_check_exit("VRT", 247.65, tick_ts, now=tick_ts)
    assert lane.paper.store.get_position("VRT") is None


def test_entry_rejection_on_the_same_symbol_does_not_block_the_exit(lane):
    _open(lane)
    tick_ts = T0 + timedelta(hours=1)
    # A REJECTED-gate message for VRT (the kind handle_message() turns into
    # an informational-only DirectionalAlert) is unrelated code and must
    # never gate _maybe_check_exit -- called directly, proving no shared
    # lockout state exists between the two paths.
    import asyncio
    asyncio.run(lane.handle_message(
        "talonx:quant:rejected",
        {"ticker": "VRT", "reason": "LOW_CONFLUENCE", "price": 247.65,
         "bar_timestamp": tick_ts.isoformat(), "session": "regular"},
    ))
    lane._maybe_check_exit("VRT", 247.65, tick_ts, now=tick_ts)
    assert lane.paper.store.get_position("VRT") is None


# --------------------------------------------------------------------------- #
# 4. Missing/stale/invalid prices -> explicit skip, never an invented fill
# --------------------------------------------------------------------------- #
def test_stale_tick_is_skipped_not_filled(lane):
    _open(lane)
    tick_ts = T0 + timedelta(hours=1)
    evaluated_at = tick_ts + timedelta(seconds=_EXIT_TICK_MAX_AGE_SECONDS + 60)
    lane._maybe_check_exit("VRT", 247.65, tick_ts, now=evaluated_at)
    assert lane.paper.store.get_position("VRT") is not None  # stale -- never filled


def test_a_tick_within_the_freshness_window_still_fills(lane):
    _open(lane)
    tick_ts = T0 + timedelta(hours=1)
    evaluated_at = tick_ts + timedelta(seconds=_EXIT_TICK_MAX_AGE_SECONDS - 5)
    lane._maybe_check_exit("VRT", 247.65, tick_ts, now=evaluated_at)
    assert lane.paper.store.get_position("VRT") is None


def test_none_or_non_positive_price_is_skipped(lane):
    _open(lane)
    tick_ts = T0 + timedelta(hours=1)
    lane._maybe_check_exit("VRT", None, tick_ts, now=tick_ts)
    lane._maybe_check_exit("VRT", 0.0, tick_ts, now=tick_ts)
    lane._maybe_check_exit("VRT", -5.0, tick_ts, now=tick_ts)
    assert lane.paper.store.get_position("VRT") is not None


def test_missing_price_never_marks_the_display_row_exited(lane):
    _open(lane)
    tick_ts = T0 + timedelta(hours=1)
    lane._maybe_check_exit("VRT", None, tick_ts, now=tick_ts)
    row = lane.alert_store._conn.execute(
        "SELECT exit FROM experimental_trades WHERE symbol='VRT'"
    ).fetchone()
    assert row[0] is None  # UNKNOWN/pending stays pending -- never coerced to a fill


# --------------------------------------------------------------------------- #
# 5. Restart / repeated-tick idempotency
# --------------------------------------------------------------------------- #
def test_repeated_ticks_after_close_never_double_exit(lane):
    _open(lane)
    t1 = T0 + timedelta(hours=1)
    lane._maybe_check_exit("VRT", 247.65, t1, now=t1)
    cash_after_first = lane.paper.store.get_portfolio_summary()["current_cash"]
    trades_after_first = len(lane.paper.store.get_trade_history())
    # Two more ticks at the same (or a different) price for the now-flat symbol:
    t2 = t1 + timedelta(minutes=1)
    t3 = t1 + timedelta(minutes=2)
    lane._maybe_check_exit("VRT", 247.65, t2, now=t2)
    lane._maybe_check_exit("VRT", 240.00, t3, now=t3)
    assert lane.paper.store.get_portfolio_summary()["current_cash"] == cash_after_first
    assert len(lane.paper.store.get_trade_history()) == trades_after_first


def test_restart_reopens_the_same_ledger_position_survives(tmp_path):
    cfg = ExperimentalConfig(state_dir=tmp_path / "experimental")
    lane1 = ExperimentalLane(cfg)
    _open(lane1)
    lane1.paper.close()

    lane2 = ExperimentalLane(cfg)
    assert lane2.paper.store.get_position("VRT") is not None
    tick_ts = T0 + timedelta(hours=1)
    lane2._maybe_check_exit("VRT", 247.65, tick_ts, now=tick_ts)
    assert lane2.paper.store.get_position("VRT") is None
    lane2.paper.close()


# --------------------------------------------------------------------------- #
# 6. Existing overdue positions -- established gap/fill policy, never backdated
# --------------------------------------------------------------------------- #
def test_overdue_position_fills_at_the_next_valid_tick_price_not_the_stop_price(lane):
    """A reference price well past the stop (as VRT/BLSH's last known
    2026-09-10 price already was) must fill at THAT tick's actual price
    (spread-adjusted), never at the stop level itself and never backdated
    to when the breach first happened -- the same convention
    talonx_paper.consumer already uses for a live gap-through."""
    _open(lane, entry=274.5585, stop=273.6548, target=296.5033)
    next_valid_tick_time = T0 + timedelta(days=2, hours=4)  # e.g. next session's first tick
    lane._maybe_check_exit("VRT", 247.65, next_valid_tick_time, now=next_valid_tick_time)
    row = lane.alert_store._conn.execute(
        "SELECT exit, closed_at FROM experimental_trades WHERE symbol='VRT'"
    ).fetchone()
    fill, closed_at = row
    assert fill != pytest.approx(273.6548)          # not the stop price
    assert fill == pytest.approx(247.65 * 0.99975)    # the actual observed tick, spread-adjusted
    assert closed_at == next_valid_tick_time.isoformat()  # real observation time, not backdated


# --------------------------------------------------------------------------- #
# 7. Ledger / cash reconciliation
# --------------------------------------------------------------------------- #
def test_cash_and_position_reconcile_after_exit(lane):
    trade = _open(lane)
    cash_before = lane.paper.store.get_portfolio_summary()["current_cash"]
    tick_ts = T0 + timedelta(hours=1)
    lane._maybe_check_exit("VRT", 247.65, tick_ts, now=tick_ts)
    summary = lane.paper.store.get_portfolio_summary()
    proceeds = trade["quantity"] * (247.65 * 0.99975)
    assert summary["current_cash"] == pytest.approx(cash_before + proceeds, rel=1e-6)
    assert lane.paper.store.get_position("VRT") is None
    history = lane.paper.store.get_trade_history()
    assert any(h["order_type"] == "SELL" and h["ticker"] == "VRT" for h in history)


def test_display_log_row_with_no_open_match_is_never_fabricated(lane):
    """If the exit fires with no corresponding open display-log row (e.g.
    the row was already reconciled by an earlier run), the authoritative
    ledger transition still happens; the display log is left alone rather
    than inventing a row for it."""
    _open(lane)
    lane.alert_store._conn.execute("DELETE FROM experimental_trades WHERE symbol='VRT'")
    lane.alert_store._conn.commit()
    tick_ts = T0 + timedelta(hours=1)
    lane._maybe_check_exit("VRT", 247.65, tick_ts, now=tick_ts)
    assert lane.paper.store.get_position("VRT") is None  # ledger still closed correctly
    row = lane.alert_store._conn.execute(
        "SELECT COUNT(*) FROM experimental_trades WHERE symbol='VRT'"
    ).fetchone()
    assert row[0] == 0  # no row was fabricated


# --------------------------------------------------------------------------- #
# 8. Experimental external-send prohibition
# --------------------------------------------------------------------------- #
def test_exit_never_calls_the_sender(lane):
    _open(lane)
    tick_ts = T0 + timedelta(hours=1)
    lane._maybe_check_exit("VRT", 247.65, tick_ts, now=tick_ts)
    assert lane._spy_sender.calls == []


def test_exit_path_makes_no_dispatcher_call_at_all(lane, monkeypatch):
    _open(lane)
    called = {"n": 0}

    async def _boom(*a, **k):
        called["n"] += 1
        raise AssertionError("dispatcher must not be invoked by the exit path")

    monkeypatch.setattr(lane.dispatcher, "dispatch_trade", _boom)
    tick_ts = T0 + timedelta(hours=1)
    lane._maybe_check_exit("VRT", 247.65, tick_ts, now=tick_ts)
    assert called["n"] == 0
