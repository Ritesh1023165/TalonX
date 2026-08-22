"""
tests/test_live_backtest_contract.py
------------------------------------------
Task 25A section 13 -- a permanent parity regression test. Feeds
logically equivalent alert/signal sequences to talonx_paper.decide_trade
(the actual live/paper position-decision function) and to the corrected
BacktestEngine's own position-transition logic, and asserts both land
on the exact same FLAT/LONG state sequence. If a future change ever
reintroduces a live/backtest divergence in this lifecycle, this test
is the first thing that should catch it.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pandas as pd
import pytest

import talonx_backtest.engine as engine_module
from talonx_backtest.engine import BacktestConfig, BacktestEngine
from talonx_core.schemas import AlertAction
from talonx_paper.engine import decide_trade
from talonx_quant.config import QuantConfig
from talonx_quant.schemas import QuantSignal, SignalDirection, SignalType

_DAY = datetime(2026, 1, 5, 15, 0, tzinfo=timezone.utc)
_BAR = {"open": 100.0, "high": 100.5, "low": 99.5, "close": 100.2, "volume": 1000.0}


def _signal(direction: SignalDirection, bar_timestamp: datetime) -> QuantSignal:
    signal_type = SignalType.MACD_BULLISH_CROSS if direction == SignalDirection.BULLISH else SignalType.MACD_BEARISH_CROSS
    price = 100.0
    stop, target = (price - 1.5, price + 10.0) if direction == SignalDirection.BULLISH else (price + 1.5, price - 10.0)
    return QuantSignal(
        ticker="AAAA", signal_type=signal_type, direction=direction, message="test",
        price=price, atr=1.0, confluence_score=3, risk_reward_ratio=5.0,
        volume_surge_ratio=5.0, trend_aligned=True,
        htf_sma_200=90.0 if direction == SignalDirection.BULLISH else None,
        stop_price=stop, target_price=target,
        # pivot_resistance widened to price+20 (was +10) -- pivot_support
        # (price-10) is now also a valid Task 35 structural stop anchor
        # for BULLISH candidates; the wider resistance keeps the
        # resulting structural R:R (2.0) clearing min_risk_reward_ratio
        # (1.5) at revalidation, same as the pre-Task-35 ATR-based R:R
        # did -- this file is about live/backtest position-state parity,
        # not R:R/geometry specifics.
        pivot_resistance=price + 20.0, pivot_support=price - 10.0,
        session="regular", bar_timestamp=bar_timestamp, signal_generated_at=bar_timestamp,
    )


def _paper_alert(direction: SignalDirection, price: float = 100.0):
    action = AlertAction.CONFIRMED_BULLISH if direction == SignalDirection.BULLISH else AlertAction.CONFIRMED_BEARISH
    return SimpleNamespace(action=action, ticker="AAAA", triggering_signal=SimpleNamespace(price=price))


def _paper_state_sequence(directions: list[SignalDirection]) -> list[str]:
    """Drives talonx_paper.decide_trade -- the actual live position
    decision function -- through `directions`, returning the FLAT/LONG
    state after each one."""
    position = None  # None == flat, matching talonx_paper.store's own convention
    states = []
    for direction in directions:
        decision = decide_trade(_paper_alert(direction), position)
        if decision.kind.value == "buy":
            position = {"shares": 1.0}
        elif decision.kind.value == "sell":
            position = None
        # IGNORED -> position unchanged
        states.append("LONG" if position is not None else "FLAT")
    return states


def _backtest_state_sequence(monkeypatch, directions: list[SignalDirection]) -> list[str]:
    """Drives the corrected BacktestEngine (Task 25A) through the same
    sequence -- one signal per two bars (schedule at bar N, fill at bar
    N+1's open, same next-bar convention as a live-eligible signal),
    returning the FLAT/LONG state observed after each signal's fill."""
    engine = BacktestEngine(BacktestConfig(quant_config=QuantConfig(), eod_flatten_enabled=False))
    states = []
    t = _DAY
    # cooldown_seconds defaults to 1200s (20 min) -- a talonx_quant-side
    # gate applied before ANY signal publishes, direction-agnostic and
    # identical live/backtest (Task 24 parity finding), but orthogonal
    # to what THIS contract test checks (lifecycle state transitions,
    # not timing). talonx_paper.decide_trade has no cooldown concept at
    # all -- it only ever sees signals that already cleared it -- so
    # each signal here is spaced out far enough to clear it too, for a
    # fair apples-to-apples comparison of the two decision layers.
    _COOLDOWN_CLEARANCE = timedelta(minutes=25)
    for direction in directions:
        ts = pd.Timestamp(t)

        def fake_compute_indicators(df_1m, qc, _ts=ts):
            return SimpleNamespace(atr=1.0, price=100.0, bar_timestamp=_ts)

        def fake_evaluate_signals(sym, snapshot, qc, htf_sma_200=None, daily_pivots=None, _d=direction, _ts=ts):
            return [_signal(_d, _ts.to_pydatetime())]

        monkeypatch.setattr(engine_module, "compute_indicators", fake_compute_indicators)
        monkeypatch.setattr(engine_module, "evaluate_signals", fake_evaluate_signals)
        candidates: list[QuantSignal] = []
        engine._process_symbol_bar("AAAA", ts, dict(_BAR), candidates)
        if candidates:
            engine._flush_throttle(candidates, ts)
        t += timedelta(minutes=1)

        # fill bar -- no new candidate this bar
        ts_fill = pd.Timestamp(t)
        monkeypatch.setattr(engine_module, "compute_indicators", lambda df_1m, qc, _ts=ts_fill: SimpleNamespace(atr=1.0, price=100.0, bar_timestamp=_ts))
        monkeypatch.setattr(engine_module, "evaluate_signals", lambda *a, **k: [])
        engine._process_symbol_bar("AAAA", ts_fill, dict(_BAR), [])
        t += _COOLDOWN_CLEARANCE

        states.append("LONG" if engine.simulator.has_open("AAAA") else "FLAT")
    return states


@pytest.mark.parametrize(
    "directions,expected",
    [
        pytest.param(
            [SignalDirection.BULLISH, SignalDirection.BEARISH],
            ["LONG", "FLAT"],
            id="sequence_1_flat_bullish_bearish",
        ),
        pytest.param(
            [SignalDirection.BEARISH],
            ["FLAT"],
            id="sequence_2_flat_bearish_only",
        ),
        pytest.param(
            [SignalDirection.BULLISH, SignalDirection.BULLISH, SignalDirection.BEARISH],
            ["LONG", "LONG", "FLAT"],
            id="sequence_3_flat_bullish_bullish_bearish",
        ),
    ],
)
def test_live_and_backtest_agree_on_position_state_sequence(monkeypatch, directions, expected):
    paper_states = _paper_state_sequence(directions)
    backtest_states = _backtest_state_sequence(monkeypatch, directions)

    assert paper_states == expected, f"talonx_paper diverged from the expected sequence: {paper_states}"
    assert backtest_states == expected, f"backtest diverged from the expected sequence: {backtest_states}"
    assert paper_states == backtest_states, "live and backtest disagree on position state"
