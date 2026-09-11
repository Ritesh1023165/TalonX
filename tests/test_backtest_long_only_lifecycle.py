"""
tests/test_backtest_long_only_lifecycle.py
-----------------------------------------------
Task 25A -- deterministic state-machine coverage for the corrected
LONG_ONLY backtest lifecycle (see engine.py's module docstring and
results/task24_requirements_parity_audit/long_short_flow.md).

Hand-built QuantSignal candidates are injected bar-by-bar directly
through BacktestEngine's own private per-bar methods (_process_symbol_bar
/ _flush_throttle / _maybe_eod_flatten -- the exact sequence run()
itself uses per timestamp, minus run()'s own end-of-data finalization,
which would otherwise force-close every open position the instant a
single run() call ends and make "is it still open right now" assertions
impossible to observe). This is the same rationale
test_backtest_engine_state.py's own module docstring gives for its
hand-built-QuantSignal convention: it exercises the REAL gate pipeline
(blackout, US-closed-session, throttle, next-bar fill, EOD flatten)
without needing to hand-calibrate raw OHLCV to hit exact RSI/MACD/pivot
thresholds. No strategy/threshold/gate-ordering logic is touched here.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pandas as pd
import pytest

import talonx_backtest.engine as engine_module
from talonx_backtest.engine import BacktestConfig, BacktestEngine
from talonx_quant.config import QuantConfig
from talonx_quant.schemas import QuantSignal, SignalDirection, SignalType

_DAY = datetime(2026, 1, 5, tzinfo=timezone.utc)
_BAR = {"open": 100.0, "high": 100.5, "low": 99.5, "close": 100.2, "volume": 1000.0}


def _signal(
    ticker: str, direction: SignalDirection, bar_timestamp: datetime, session: str = "regular",
) -> QuantSignal:
    signal_type = SignalType.MACD_BULLISH_CROSS if direction == SignalDirection.BULLISH else SignalType.MACD_BEARISH_CROSS
    price = 100.0
    if direction == SignalDirection.BULLISH:
        stop, target = price - 1.5, price + 10.0
    else:
        stop, target = price + 1.5, price - 10.0
    return QuantSignal(
        ticker=ticker, signal_type=signal_type, direction=direction, message="test",
        price=price, atr=1.0, confluence_score=3, risk_reward_ratio=5.0,
        volume_surge_ratio=5.0, trend_aligned=True,
        # _trend_gate_applicable (talonx_quant/consumer.py) only applies
        # to BULLISH candidates -- htf_sma_200 must be non-None for a
        # BULLISH signal to clear HTF_DATA_UNAVAILABLE; irrelevant for
        # (never checked on) BEARISH.
        htf_sma_200=90.0 if direction == SignalDirection.BULLISH else None,
        stop_price=stop, target_price=target,
        # pivot_support(price-10) stays valid for BEARISH's target (this
        # fixture is used for both directions) and is ALSO now a valid
        # Task 35 structural stop anchor for BULLISH -- pivot_resistance
        # is widened to price+20 (was +10) so the resulting structural
        # R:R (reward 20 / risk 10 = 2.0) still clears min_risk_reward_
        # ratio(1.5) at _revalidate time, same as the pre-Task-35 ATR-
        # based R:R(6.67) did; this file is about long-only lifecycle
        # state transitions, not R:R/geometry specifics.
        pivot_resistance=price + 20.0, pivot_support=price - 10.0,
        session=session, bar_timestamp=bar_timestamp, signal_generated_at=bar_timestamp,
    )


def _engine(eod_flatten_enabled: bool = False) -> BacktestEngine:
    return BacktestEngine(BacktestConfig(quant_config=QuantConfig(), eod_flatten_enabled=eod_flatten_enabled))


def _step(monkeypatch, engine: BacktestEngine, symbol: str, timestamp: datetime, injected=(), bar: dict | None = None) -> None:
    """One full bar iteration, same sequence run() uses per timestamp
    (_process_symbol_bar -> _flush_throttle -> _maybe_eod_flatten), but
    WITHOUT run()'s own end-of-data finalization -- letting a test
    inspect "is it still open right now" state between bars, which
    run() itself never exposes (every run() call force-closes anything
    left open via _finalize_at_data_end the instant it returns).
    `bar` overrides the default flat OHLCV -- used to construct a bar
    whose high/low WOULD strike a stop/target, to prove ordering against
    a same-bar pending SIGNAL_EXIT (Task 25A.1 risk A)."""
    ts = pd.Timestamp(timestamp)
    injected = list(injected)
    bar = dict(bar) if bar is not None else dict(_BAR)

    def fake_compute_indicators(df_1m, qc):
        return SimpleNamespace(atr=1.0, price=100.0, bar_timestamp=ts)

    def fake_evaluate_signals(sym, snapshot, qc, htf_sma_200=None, daily_pivots=None):
        return injected

    monkeypatch.setattr(engine_module, "compute_indicators", fake_compute_indicators)
    monkeypatch.setattr(engine_module, "evaluate_signals", fake_evaluate_signals)

    candidates: list[QuantSignal] = []
    engine._process_symbol_bar(symbol, ts, bar, candidates)
    if candidates:
        engine._flush_throttle(candidates, ts)
    if engine.config.eod_flatten_enabled:
        engine._maybe_eod_flatten(ts)


# --- Core FLAT/LONG x BULLISH/BEARISH matrix -------------------------------

def test_flat_bullish_opens_long(monkeypatch):
    engine = _engine()
    t0 = _DAY.replace(hour=15, minute=0)
    _step(monkeypatch, engine, "AAAA", t0, injected=[_signal("AAAA", SignalDirection.BULLISH, t0)])
    _step(monkeypatch, engine, "AAAA", t0 + timedelta(minutes=1))  # fills at next bar's open

    assert engine.simulator.has_open("AAAA")
    assert engine.simulator.get_open("AAAA").direction == SignalDirection.BULLISH


def test_flat_bearish_stays_flat_and_is_recorded(monkeypatch):
    engine = _engine()
    t0 = _DAY.replace(hour=15, minute=0)
    _step(monkeypatch, engine, "AAAA", t0, injected=[_signal("AAAA", SignalDirection.BEARISH, t0)])

    assert not engine.simulator.has_open("AAAA")
    assert not engine.trades
    assert any(r.ticker == "AAAA" and r.reason == "NO_ACTIVE_POSITION" for r in engine.rejections)


def test_long_bullish_does_not_open_a_second_position(monkeypatch):
    engine = _engine()
    t0 = _DAY.replace(hour=15, minute=0)
    entry_signal = _signal("AAAA", SignalDirection.BULLISH, t0 - timedelta(minutes=1))
    engine.simulator.open_position(entry_signal, entry_timestamp=t0 - timedelta(minutes=1), entry_price_raw=100.0)
    engine._last_close["AAAA"] = 100.0

    _step(monkeypatch, engine, "AAAA", t0, injected=[_signal("AAAA", SignalDirection.BULLISH, t0)])
    _step(monkeypatch, engine, "AAAA", t0 + timedelta(minutes=1))

    assert engine.simulator.has_open("AAAA")
    assert engine.simulator.get_open("AAAA").entry_price_raw == 100.0  # original position untouched
    assert not engine.trades  # no exit/re-entry happened


def test_long_bearish_closes_via_signal_exit(monkeypatch):
    engine = _engine()
    t0 = _DAY.replace(hour=15, minute=0)
    entry_signal = _signal("AAAA", SignalDirection.BULLISH, t0 - timedelta(minutes=1))
    engine.simulator.open_position(entry_signal, entry_timestamp=t0 - timedelta(minutes=1), entry_price_raw=100.0)

    exit_signal = _signal("AAAA", SignalDirection.BEARISH, t0)
    _step(monkeypatch, engine, "AAAA", t0, injected=[exit_signal])
    _step(monkeypatch, engine, "AAAA", t0 + timedelta(minutes=1))  # fills at next bar's open

    assert not engine.simulator.has_open("AAAA")
    assert len(engine.trades) == 1
    trade = engine.trades[0]
    assert trade.exit_reason == "SIGNAL_EXIT"
    assert trade.exit_reason not in ("STOP", "TARGET", "END_OF_SESSION", "DATA_END")
    assert trade.exit_signal_type == SignalType.MACD_BEARISH_CROSS.value
    assert trade.exit_signal_direction == SignalDirection.BEARISH.value


def test_signal_exit_fills_at_next_bar_open_not_the_signal_bar(monkeypatch):
    """No-lookahead proof (Task 25A section 4): a BEARISH signal
    generated on bar N's close must not close the position at bar N's
    own price -- only at bar N+1's open. The position must still be
    open immediately after bar N is processed."""
    engine = _engine()
    t0 = _DAY.replace(hour=15, minute=0)
    entry_signal = _signal("AAAA", SignalDirection.BULLISH, t0 - timedelta(minutes=1))
    engine.simulator.open_position(entry_signal, entry_timestamp=t0 - timedelta(minutes=1), entry_price_raw=100.0)

    _step(monkeypatch, engine, "AAAA", t0, injected=[_signal("AAAA", SignalDirection.BEARISH, t0)])

    # bar N only scheduled the exit (via _flush_throttle) -- still open
    # at the end of bar N's own processing.
    assert engine.simulator.has_open("AAAA")
    assert not engine.trades

    t1 = t0 + timedelta(minutes=1)
    engine.buffer.add_bar(symbol="AAAA", timestamp=t1, open_=97.5, high=98.0, low=97.0, close=97.8, volume=1000.0, session="regular")
    # override the OPEN this bar fills at (distinct from bar N's close=100.2 and bar N+1's own close=97.8)
    _BAR_NEXT = {"open": 97.5, "high": 98.0, "low": 97.0, "close": 97.8, "volume": 1000.0}
    ts1 = pd.Timestamp(t1)

    def fake_compute_indicators(df_1m, qc):
        return SimpleNamespace(atr=1.0, price=97.8, bar_timestamp=ts1)

    def fake_evaluate_signals(sym, snapshot, qc, htf_sma_200=None, daily_pivots=None):
        return []

    monkeypatch.setattr(engine_module, "compute_indicators", fake_compute_indicators)
    monkeypatch.setattr(engine_module, "evaluate_signals", fake_evaluate_signals)
    engine._process_symbol_bar("AAAA", ts1, _BAR_NEXT, [])

    assert not engine.simulator.has_open("AAAA")
    assert len(engine.trades) == 1
    assert engine.trades[0].exit_price == 97.5  # bar N+1's OPEN, not bar N's close (100.2) or bar N+1's close (97.8)


# --- Closing blackout (15:30-16:00 ET) integration --------------------------

_BLACKOUT_BAR = _DAY.replace(hour=20, minute=45)  # 15:45 ET


def test_flat_bearish_during_closing_blackout_stays_flat(monkeypatch):
    engine = _engine()
    _step(monkeypatch, engine, "AAAA", _BLACKOUT_BAR, injected=[_signal("AAAA", SignalDirection.BEARISH, _BLACKOUT_BAR)])

    assert not engine.simulator.has_open("AAAA")
    assert not engine.trades
    assert any(r.ticker == "AAAA" and r.reason == "NO_ACTIVE_POSITION" for r in engine.rejections)
    assert not any(r.reason == "CLOSING_BLACKOUT" for r in engine.rejections)  # BEARISH is never blackout-blocked


def test_long_bearish_during_closing_blackout_still_exits(monkeypatch):
    engine = _engine()
    entry_signal = _signal("AAAA", SignalDirection.BULLISH, _BLACKOUT_BAR - timedelta(minutes=1))
    engine.simulator.open_position(entry_signal, entry_timestamp=_BLACKOUT_BAR - timedelta(minutes=1), entry_price_raw=100.0)

    _step(monkeypatch, engine, "AAAA", _BLACKOUT_BAR, injected=[_signal("AAAA", SignalDirection.BEARISH, _BLACKOUT_BAR)])
    _step(monkeypatch, engine, "AAAA", _BLACKOUT_BAR + timedelta(minutes=1))

    assert not engine.simulator.has_open("AAAA")
    assert len(engine.trades) == 1
    assert engine.trades[0].exit_reason == "SIGNAL_EXIT"


def test_flat_bullish_during_closing_blackout_is_blocked(monkeypatch):
    engine = _engine()
    _step(monkeypatch, engine, "AAAA", _BLACKOUT_BAR, injected=[_signal("AAAA", SignalDirection.BULLISH, _BLACKOUT_BAR)])
    _step(monkeypatch, engine, "AAAA", _BLACKOUT_BAR + timedelta(minutes=1))

    assert not engine.simulator.has_open("AAAA")
    assert not engine.trades
    assert any(r.ticker == "AAAA" and r.reason == "CLOSING_BLACKOUT" for r in engine.rejections)


# --- EOD flatten / post-flatten no-re-entry ---------------------------------

_FLATTEN_BAR = _DAY.replace(hour=20, minute=50)  # 15:50 ET


def test_long_position_is_flattened_at_1550(monkeypatch):
    engine = _engine(eod_flatten_enabled=True)
    entry_signal = _signal("AAAA", SignalDirection.BULLISH, _FLATTEN_BAR - timedelta(minutes=5))
    engine.simulator.open_position(entry_signal, entry_timestamp=_FLATTEN_BAR - timedelta(minutes=5), entry_price_raw=100.0)
    engine._last_close["AAAA"] = 100.0

    _step(monkeypatch, engine, "AAAA", _FLATTEN_BAR)

    assert not engine.simulator.has_open("AAAA")
    assert len(engine.trades) == 1
    assert engine.trades[0].exit_reason == "END_OF_SESSION"


def test_bullish_after_flatten_checkpoint_does_not_reopen(monkeypatch):
    """Task 24 finding: the once-per-day EOD-flatten guard alone did not
    prevent a NEW entry after that day's checkpoint. Task 25A closes
    this explicitly -- a BULLISH candidate scheduled from a bar AFTER
    the flatten checkpoint must not open a position that same date."""
    engine = _engine(eod_flatten_enabled=True)
    entry_signal = _signal("AAAA", SignalDirection.BULLISH, _FLATTEN_BAR - timedelta(minutes=5))
    engine.simulator.open_position(entry_signal, entry_timestamp=_FLATTEN_BAR - timedelta(minutes=5), entry_price_raw=100.0)
    engine._last_close["AAAA"] = 100.0

    _step(monkeypatch, engine, "AAAA", _FLATTEN_BAR)  # triggers the 15:50 flatten
    assert not engine.simulator.has_open("AAAA")
    assert engine.trades[0].exit_reason == "END_OF_SESSION"

    # 16:01 ET -- same date, past both the flatten checkpoint AND the
    # 15:30-16:00 ET closing blackout window (which would otherwise
    # block a BULLISH candidate on its own, masking this guard).
    after_flatten = _DAY.replace(hour=21, minute=1)
    _step(monkeypatch, engine, "AAAA", after_flatten, injected=[_signal("AAAA", SignalDirection.BULLISH, after_flatten)])
    _step(monkeypatch, engine, "AAAA", after_flatten + timedelta(minutes=1))  # would-be fill bar

    assert not engine.simulator.has_open("AAAA")
    assert len(engine.trades) == 1  # still just the one EOD-flatten trade -- no new entry
    assert any(r.ticker == "AAAA" and r.reason == "POST_EOD_FLATTEN_NO_NEW_ENTRY" for r in engine.rejections)


def test_bearish_after_flatten_checkpoint_stays_flat(monkeypatch):
    engine = _engine(eod_flatten_enabled=True)
    _step(monkeypatch, engine, "AAAA", _FLATTEN_BAR)  # nothing open; flatten checkpoint still marks the date

    after_flatten = _FLATTEN_BAR + timedelta(minutes=1)
    _step(monkeypatch, engine, "AAAA", after_flatten, injected=[_signal("AAAA", SignalDirection.BEARISH, after_flatten)])

    assert not engine.simulator.has_open("AAAA")
    assert not engine.trades
    assert any(r.ticker == "AAAA" and r.reason == "NO_ACTIVE_POSITION" for r in engine.rejections)


# --- US market closed-session parity (Task 24 P1) ---------------------------

_CLOSED_BAR = _DAY.replace(hour=8, minute=0)  # 03:00 ET -- outside 04:00-16:00 ET, closed


def test_closed_session_bullish_does_not_enter(monkeypatch):
    engine = _engine()
    _step(monkeypatch, engine, "AAAA", _CLOSED_BAR, injected=[_signal("AAAA", SignalDirection.BULLISH, _CLOSED_BAR, session="closed")])
    _step(monkeypatch, engine, "AAAA", _CLOSED_BAR + timedelta(minutes=1))

    assert not engine.simulator.has_open("AAAA")
    assert any(r.ticker == "AAAA" and r.reason == "US_MARKET_SESSION_CLOSED" for r in engine.rejections)


def test_closed_session_bearish_does_not_exit_an_open_long(monkeypatch):
    engine = _engine()
    entry_signal = _signal("AAAA", SignalDirection.BULLISH, _CLOSED_BAR - timedelta(minutes=1))
    engine.simulator.open_position(entry_signal, entry_timestamp=_CLOSED_BAR - timedelta(minutes=1), entry_price_raw=100.0)

    _step(monkeypatch, engine, "AAAA", _CLOSED_BAR, injected=[_signal("AAAA", SignalDirection.BEARISH, _CLOSED_BAR, session="closed")])
    _step(monkeypatch, engine, "AAAA", _CLOSED_BAR + timedelta(minutes=1))

    assert engine.simulator.has_open("AAAA")  # untouched -- closed-session signal never reaches the exit path
    assert not engine.trades
    assert any(r.ticker == "AAAA" and r.reason == "US_MARKET_SESSION_CLOSED" for r in engine.rejections)


# --- Task 25A.1 risk A: pending SIGNAL_EXIT vs same-bar STOP/TARGET ordering ---
# SIGNAL_EXIT executes at bar N+1's OPEN; that must win over anything bar
# N+1's own high/low would otherwise have struck later in the bar -- no
# hindsight, the position is gone before the stop/target check ever runs.

def test_pending_signal_exit_wins_over_a_stop_that_would_have_hit_later_in_the_bar(monkeypatch):
    engine = _engine()
    t0 = _DAY.replace(hour=15, minute=0)
    # long entered at 100.0 with stop=98.5 (from _signal's stop=price-1.5)
    entry_signal = _signal("AAAA", SignalDirection.BULLISH, t0 - timedelta(minutes=1))
    engine.simulator.open_position(entry_signal, entry_timestamp=t0 - timedelta(minutes=1), entry_price_raw=100.0)

    _step(monkeypatch, engine, "AAAA", t0, injected=[_signal("AAAA", SignalDirection.BEARISH, t0)])
    assert engine.simulator.has_open("AAAA")  # only scheduled so far

    # fill bar: opens at 99.0 (above the 98.5 stop) but LATER in the bar
    # trades all the way down through the stop (low=97.0) -- if STOP were
    # checked, it would fire; SIGNAL_EXIT must win instead.
    fill_bar = {"open": 99.0, "high": 99.2, "low": 97.0, "close": 97.5, "volume": 1000.0}
    _step(monkeypatch, engine, "AAAA", t0 + timedelta(minutes=1), bar=fill_bar)

    assert not engine.simulator.has_open("AAAA")
    assert len(engine.trades) == 1
    trade = engine.trades[0]
    assert trade.exit_reason == "SIGNAL_EXIT"
    assert trade.exit_price == 99.0  # the bar's OPEN, not the stop level (98.5) or the low (97.0)


def test_pending_signal_exit_wins_over_a_target_that_would_have_hit_later_in_the_bar(monkeypatch):
    engine = _engine()
    t0 = _DAY.replace(hour=15, minute=0)
    # long entered at 100.0 with target=110.0 (from _signal's target=price+10.0)
    entry_signal = _signal("AAAA", SignalDirection.BULLISH, t0 - timedelta(minutes=1))
    engine.simulator.open_position(entry_signal, entry_timestamp=t0 - timedelta(minutes=1), entry_price_raw=100.0)

    _step(monkeypatch, engine, "AAAA", t0, injected=[_signal("AAAA", SignalDirection.BEARISH, t0)])
    assert engine.simulator.has_open("AAAA")

    # fill bar: opens at 101.0 (below the 110.0 target) but LATER in the
    # bar trades all the way up through the target (high=111.0) -- if
    # TARGET were checked, it would fire; SIGNAL_EXIT must win instead.
    fill_bar = {"open": 101.0, "high": 111.0, "low": 100.8, "close": 105.0, "volume": 1000.0}
    _step(monkeypatch, engine, "AAAA", t0 + timedelta(minutes=1), bar=fill_bar)

    assert not engine.simulator.has_open("AAAA")
    assert len(engine.trades) == 1
    trade = engine.trades[0]
    assert trade.exit_reason == "SIGNAL_EXIT"
    assert trade.exit_price == 101.0  # the bar's OPEN, not the target level (110.0) or the high (111.0)


# --- Task 25A.1 risk B: duplicate/multiple bearish signals -------------------

def test_second_bearish_candidate_same_bar_does_not_overwrite_or_duplicate_the_pending_exit(monkeypatch):
    """Two BEARISH candidates for the same symbol fire on the same bar
    while long -- the existing intra-flush cooldown recheck (shared,
    unchanged machinery -- see test_backtest_engine_state.py's own
    test_throttle_intra_flush_cooldown_recheck_drops_a_second_candidate_for_the_same_ticker)
    must reject the second one before it ever reaches _pending_exit, so
    the trade closes exactly once with deterministic exit metadata."""
    engine = _engine()
    t0 = _DAY.replace(hour=15, minute=0)
    entry_signal = _signal("AAAA", SignalDirection.BULLISH, t0 - timedelta(minutes=1))
    engine.simulator.open_position(entry_signal, entry_timestamp=t0 - timedelta(minutes=1), entry_price_raw=100.0)

    first = _signal("AAAA", SignalDirection.BEARISH, t0)
    second = _signal("AAAA", SignalDirection.BEARISH, t0)
    _step(monkeypatch, engine, "AAAA", t0, injected=[first, second])

    # exactly one pending exit scheduled (a dict has one slot per
    # symbol by construction), and the second candidate was rejected by
    # the same intra-flush cooldown recheck that already protects
    # duplicate BULLISH candidates -- never silently overwritten.
    assert "AAAA" in engine._pending_exit
    assert engine.signals_published == 1
    assert any(r.ticker == "AAAA" and r.reason == "COOLDOWN" for r in engine.rejections)

    _step(monkeypatch, engine, "AAAA", t0 + timedelta(minutes=1))

    assert not engine.simulator.has_open("AAAA")
    assert len(engine.trades) == 1  # closed exactly once, no duplicate close
    assert engine.trades[0].exit_reason == "SIGNAL_EXIT"
    assert engine.trades[0].exit_signal_type == SignalType.MACD_BEARISH_CROSS.value


def test_bearish_candidate_after_exit_already_scheduled_does_not_duplicate(monkeypatch):
    """A second BEARISH candidate arriving on the bar the exit actually
    FILLS (after the pending exit from the prior bar has already closed
    the position) must never cause a second close of the same trade --
    whether it is rejected via COOLDOWN (still armed from the first
    signal, 20 minutes by default) or, once cooldown clears, via
    NO_ACTIVE_POSITION, exactly one Trade must ever exist."""
    engine = _engine()
    t0 = _DAY.replace(hour=15, minute=0)
    entry_signal = _signal("AAAA", SignalDirection.BULLISH, t0 - timedelta(minutes=1))
    engine.simulator.open_position(entry_signal, entry_timestamp=t0 - timedelta(minutes=1), entry_price_raw=100.0)

    _step(monkeypatch, engine, "AAAA", t0, injected=[_signal("AAAA", SignalDirection.BEARISH, t0)])
    t1 = t0 + timedelta(minutes=1)
    # a second BEARISH candidate arrives on the very bar the first exit
    # fills -- still within the first signal's cooldown window
    _step(monkeypatch, engine, "AAAA", t1, injected=[_signal("AAAA", SignalDirection.BEARISH, t1)])

    assert not engine.simulator.has_open("AAAA")
    assert len(engine.trades) == 1  # closed exactly once, no duplicate
    assert engine.trades[0].exit_reason == "SIGNAL_EXIT"
    assert any(r.ticker == "AAAA" and r.reason == "COOLDOWN" for r in engine.rejections)

    # once cooldown clears, a THIRD bearish candidate (still flat) hits
    # the other, intended no-op path -- still no duplicate.
    t2 = t1 + timedelta(minutes=25)
    _step(monkeypatch, engine, "AAAA", t2, injected=[_signal("AAAA", SignalDirection.BEARISH, t2)])
    assert len(engine.trades) == 1
    assert any(r.ticker == "AAAA" and r.reason == "NO_ACTIVE_POSITION" for r in engine.rejections)


# --- Task 25A.1 risk C: loss-lockout only reflects canonical long trades ----

def test_ignored_bearish_while_flat_does_not_arm_loss_lockout(monkeypatch):
    engine = _engine()
    t0 = _DAY.replace(hour=15, minute=0)
    _step(monkeypatch, engine, "AAAA", t0, injected=[_signal("AAAA", SignalDirection.BEARISH, t0)])

    assert not engine.trades
    assert not engine._is_loss_locked_out("AAAA", t0)


def test_losing_signal_exit_arms_loss_lockout_like_any_other_losing_close(monkeypatch):
    engine = _engine()
    t0 = _DAY.replace(hour=15, minute=0)
    entry_signal = _signal("AAAA", SignalDirection.BULLISH, t0 - timedelta(minutes=1))
    engine.simulator.open_position(entry_signal, entry_timestamp=t0 - timedelta(minutes=1), entry_price_raw=100.0)

    _step(monkeypatch, engine, "AAAA", t0, injected=[_signal("AAAA", SignalDirection.BEARISH, t0)])
    # fill bar opens BELOW entry (100.0) -- a losing SIGNAL_EXIT
    losing_fill_bar = {"open": 95.0, "high": 95.2, "low": 94.8, "close": 95.0, "volume": 1000.0}
    t1 = t0 + timedelta(minutes=1)
    _step(monkeypatch, engine, "AAAA", t1, bar=losing_fill_bar)

    assert engine.trades[0].exit_reason == "SIGNAL_EXIT"
    assert engine.trades[0].net_pnl < 0
    assert engine._is_loss_locked_out("AAAA", t1)


def test_profitable_signal_exit_does_not_arm_loss_lockout(monkeypatch):
    engine = _engine()
    t0 = _DAY.replace(hour=15, minute=0)
    entry_signal = _signal("AAAA", SignalDirection.BULLISH, t0 - timedelta(minutes=1))
    engine.simulator.open_position(entry_signal, entry_timestamp=t0 - timedelta(minutes=1), entry_price_raw=100.0)

    _step(monkeypatch, engine, "AAAA", t0, injected=[_signal("AAAA", SignalDirection.BEARISH, t0)])
    # fill bar opens ABOVE entry (100.0) -- a profitable SIGNAL_EXIT
    winning_fill_bar = {"open": 103.0, "high": 103.2, "low": 102.8, "close": 103.0, "volume": 1000.0}
    t1 = t0 + timedelta(minutes=1)
    _step(monkeypatch, engine, "AAAA", t1, bar=winning_fill_bar)

    assert engine.trades[0].exit_reason == "SIGNAL_EXIT"
    assert engine.trades[0].net_pnl > 0
    assert not engine._is_loss_locked_out("AAAA", t1)


def test_no_short_trades_can_exist_to_affect_loss_lockout(monkeypatch):
    """Structural confirmation, not just a behavioral one: with BEARISH
    signals never routed into _pending_entry/open_position (Task 25A's
    core fix), there is no code path left that could ever produce a
    losing SHORT trade to arm loss lockout from -- every trade's
    direction is BULLISH by construction."""
    engine = _engine()
    t0 = _DAY.replace(hour=15, minute=0)
    entry_signal = _signal("AAAA", SignalDirection.BULLISH, t0 - timedelta(minutes=1))
    engine.simulator.open_position(entry_signal, entry_timestamp=t0 - timedelta(minutes=1), entry_price_raw=100.0)

    _step(monkeypatch, engine, "AAAA", t0, injected=[_signal("AAAA", SignalDirection.BEARISH, t0)])
    _step(monkeypatch, engine, "AAAA", t0 + timedelta(minutes=1))

    assert all(t.direction == SignalDirection.BULLISH.value for t in engine.trades)
