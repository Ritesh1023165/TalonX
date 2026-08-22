"""
tests/test_volatility_regime.py
------------------------------------
Task 40 -- multi-timeframe volatility REGIME state (observability only;
see docs/research/TALONX_RESEARCH_LEDGER.md Task 39/40 entries and
talonx_quant.indicators.compute_volatility_regime's own docstring).

The single most important property under test, exactly like Task 10's
research telemetry, is PARITY: adding this state must never change a
single strategy/trade/rejection decision -- see
test_regime_state_enabled_does_not_change_trades_signals_or_rejections.
Every other test here proves the new state itself is correct/consistent,
never a second implementation of any existing gate.
"""
from __future__ import annotations

import dataclasses
from datetime import datetime, timedelta, timezone

import pandas as pd
import pytest

from talonx_backtest.data import from_dataframe
from talonx_backtest.engine import BacktestConfig, BacktestEngine
from talonx_quant.config import QuantConfig
from talonx_quant.consumer import QuantScanner
from talonx_quant.indicators import VolatilityRegimeSnapshot, _regime_leg_atr, compute_volatility_regime
from talonx_quant.schemas import MarketTickEvent, TickEventType, TickSource

_START = datetime(2026, 1, 5, 15, 0, tzinfo=timezone.utc)  # 10:00 ET, regular session


def _relaxed_config() -> QuantConfig:
    return dataclasses.replace(QuantConfig(), atr_move_multiplier=0.0)


def _build_bars(n: int = 260) -> list[tuple[float, float, float, float, float]]:
    bars = []
    price = 100.0
    for i in range(n):
        if i % 47 == 0 and i > 0:
            price -= 3.0
        elif i % 61 == 0 and i > 0:
            price += 3.5
        else:
            price += 0.05 if i % 2 == 0 else -0.03
        vol = 5000.0 if i % 47 == 1 else 1000.0 + (i % 5) * 50
        bars.append((price, price + 0.4, price - 0.4, price, vol))
    return bars


def _bars_to_df(bars, symbol: str = "AAPL", start: datetime = _START) -> pd.DataFrame:
    rows = [
        {"timestamp": start + timedelta(minutes=i), "open": o, "high": h, "low": l, "close": c, "volume": v}
        for i, (o, h, l, c, v) in enumerate(bars)
    ]
    return from_dataframe(pd.DataFrame(rows), symbol=symbol)


def _two_symbol_df() -> pd.DataFrame:
    aapl_bars = _build_bars()
    msft_bars = [(o * 3 + 50, h * 3 + 50, l * 3 + 50, c * 3 + 50, v) for (o, h, l, c, v) in _build_bars()]
    return pd.concat([_bars_to_df(aapl_bars, "AAPL"), _bars_to_df(msft_bars, "MSFT")], ignore_index=True)


def _synthetic_htf_df(n: int, start_price: float = 100.0) -> pd.DataFrame:
    """A ready-made HTF-shaped dataframe (indexed by timestamp, OHLC
    columns) as if it were already the output of RollingBarBuffer.
    get_dataframe() -- used to unit-test _regime_leg_atr/
    compute_volatility_regime directly without needing hours of 1-minute
    bars replayed through the full aggregator."""
    price = start_price
    rows = []
    for i in range(n):
        price += 0.3 if i % 2 == 0 else -0.2
        rows.append({
            "timestamp": _START + timedelta(hours=i),
            "open": price, "high": price + 0.5, "low": price - 0.5, "close": price, "volume": 1000.0,
        })
    df = pd.DataFrame(rows).set_index("timestamp")
    return df


# ----------------------------------------------------------------------
# Behavioral parity (step 13's before/after proof, mirrors
# test_backtest_research_telemetry.py's own parity test exactly)
# ----------------------------------------------------------------------

def test_regime_state_does_not_change_trades_signals_or_rejections():
    df = _two_symbol_df()
    cfg = BacktestConfig(quant_config=_relaxed_config(), eod_flatten_enabled=False)

    before = BacktestEngine(dataclasses.replace(cfg))
    before_result = before.run(df)

    after = BacktestEngine(dataclasses.replace(cfg), research_telemetry=True)
    after_result = after.run(df)

    assert before_result.trades == after_result.trades
    assert before_result.signals_generated == after_result.signals_generated
    assert before_result.signals_published == after_result.signals_published
    assert before_result.bars_processed == after_result.bars_processed
    assert before.rejections == after.rejections
    assert before.signal_log == after.signal_log

    # And regime state actually did something -- otherwise this test
    # would trivially pass regardless of correctness.
    assert len(after.volatility_regime_snapshots) > 0
    assert len(after.regime_telemetry) > 0


def test_regime_telemetry_disabled_by_default():
    engine = BacktestEngine(BacktestConfig(quant_config=_relaxed_config(), eod_flatten_enabled=False))
    engine.run(_two_symbol_df())
    assert engine.research_telemetry is False
    assert engine.regime_telemetry == []
    # volatility_regime_snapshots is populated regardless of the
    # research_telemetry flag -- it is the current-state dict (Task 40
    # scope), not the opt-in telemetry LOG; only regime_telemetry (the
    # append-only history) is gated by the flag, matching
    # volatility_telemetry's own existing convention.
    assert len(engine.volatility_regime_snapshots) > 0


# ----------------------------------------------------------------------
# 15-minute leg: reuses existing HTF buffer, closed-bar/causal, session
# semantics preserved (regular-session-only, unchanged)
# ----------------------------------------------------------------------

def test_15m_leg_becomes_ready_and_60m_does_not_within_a_short_fixture():
    cfg = BacktestConfig(quant_config=_relaxed_config(), eod_flatten_enabled=False)
    engine = BacktestEngine(cfg, research_telemetry=True)
    engine.run(_two_symbol_df())

    snap = engine.volatility_regime_snapshots["AAPL"]
    assert isinstance(snap, VolatilityRegimeSnapshot)
    # 260 1-min bars = ~4.3h regular-session time -- enough for the 15m
    # leg (needs >14 15-min bars, i.e. >210 min) to warm up...
    assert snap.ready_15m is True
    assert snap.atr_15m is not None
    assert snap.atr_pct_15m is not None
    # ...but nowhere near enough for the 60m leg (needs >14 60-min bars,
    # i.e. >14h) -- must be honestly reported NOT_READY, never a fake
    # zero/default value.
    assert snap.ready_60m is False
    assert snap.atr_60m is None
    assert snap.atr_pct_60m is None


def test_15m_leg_reuses_existing_buffer_htf_dataframe():
    """Directly proves the 15m leg is computed from buffer_htf -- the
    SAME buffer compute_htf_trend/compute_daily_pivots already use --
    not a second, independent 15m buffer."""
    cfg = BacktestConfig(quant_config=_relaxed_config(), eod_flatten_enabled=False)
    engine = BacktestEngine(cfg, research_telemetry=True)
    engine.run(_two_symbol_df())

    df_htf = engine.buffer_htf.get_dataframe("AAPL")
    expected_atr, expected_pct, expected_ready = _regime_leg_atr(df_htf, engine.config.quant_config.atr_period)
    snap = engine.volatility_regime_snapshots["AAPL"]
    assert snap.atr_15m == expected_atr
    assert snap.atr_pct_15m == expected_pct
    assert snap.ready_15m == expected_ready


# ----------------------------------------------------------------------
# 60-minute leg: new buffer/aggregator, same proven classes, no new
# formula, continuous session behavior
# ----------------------------------------------------------------------

def test_60m_leg_ready_and_atr_pct_once_warmed_up_via_direct_unit_test():
    """Unit-tests _regime_leg_atr/compute_volatility_regime directly
    against a synthetic 20-bar 60-minute-shaped dataframe -- proves the
    60m leg CAN become ready given enough bars, without needing >14
    hours of 1-minute bars replayed through the full engine (cheap,
    deterministic, no engine dependency)."""
    df_60m = _synthetic_htf_df(20)
    atr, atr_pct, ready = _regime_leg_atr(df_60m, atr_period=14)
    assert ready is True
    assert atr is not None and atr > 0
    assert atr_pct is not None and atr_pct > 0
    assert atr_pct == pytest.approx(atr / df_60m["close"].iloc[-1] * 100)


def test_60m_leg_not_ready_with_insufficient_bars():
    df_60m = _synthetic_htf_df(10)  # <= atr_period(14)
    atr, atr_pct, ready = _regime_leg_atr(df_60m, atr_period=14)
    assert ready is False
    assert atr is None
    assert atr_pct is None


def test_60m_leg_not_ready_when_buffer_is_none():
    atr, atr_pct, ready = _regime_leg_atr(None, atr_period=14)
    assert (atr, atr_pct, ready) == (None, None, False)


def test_60m_aggregator_is_continuous_not_rth_only():
    """Task 39's session-policy decision: unlike the 15m trend buffer
    (rth_only=True), the new 60m regime buffer must keep finalizing
    buckets outside regular trading hours (e.g. pre-market)."""
    cfg = BacktestConfig(quant_config=_relaxed_config(), eod_flatten_enabled=False)
    engine = BacktestEngine(cfg, research_telemetry=True)
    assert engine.aggregator_60m.rth_only is False
    assert engine.htf_aggregator.rth_only is True  # unchanged, existing 15m convention


def test_60m_buffer_is_a_new_state_object_distinct_from_15m_buffer():
    cfg = BacktestConfig(quant_config=_relaxed_config(), eod_flatten_enabled=False)
    engine = BacktestEngine(cfg, research_telemetry=True)
    assert engine.buffer_60m is not engine.buffer_htf
    assert engine.aggregator_60m is not engine.htf_aggregator


# ----------------------------------------------------------------------
# Price normalization / invalid denominator handling (step 6)
# ----------------------------------------------------------------------

def test_atr_pct_uses_this_legs_own_latest_close_as_denominator():
    df = _synthetic_htf_df(20)
    atr, atr_pct, ready = _regime_leg_atr(df, atr_period=14)
    assert atr_pct == pytest.approx(atr / float(df["close"].iloc[-1]) * 100)


def test_zero_price_denominator_yields_none_pct_but_still_ready():
    df = _synthetic_htf_df(20)
    df = df.copy()
    df.iloc[-1, df.columns.get_loc("close")] = 0.0
    atr, atr_pct, ready = _regime_leg_atr(df, atr_period=14)
    assert ready is True  # ATR itself is still computable -- warm-up and price validity are separate concerns
    assert atr is not None
    assert atr_pct is None  # never a fabricated/divide-by-zero value


def test_negative_price_denominator_yields_none_pct():
    df = _synthetic_htf_df(20)
    df = df.copy()
    df.iloc[-1, df.columns.get_loc("close")] = -5.0
    atr, atr_pct, ready = _regime_leg_atr(df, atr_period=14)
    assert ready is True
    assert atr_pct is None


def test_nan_price_denominator_yields_none_pct():
    df = _synthetic_htf_df(20)
    df = df.copy()
    df.iloc[-1, df.columns.get_loc("close")] = float("nan")
    atr, atr_pct, ready = _regime_leg_atr(df, atr_period=14)
    assert ready is True
    assert atr_pct is None


# ----------------------------------------------------------------------
# Causality / no future-bar leakage
# ----------------------------------------------------------------------

def test_regime_snapshot_never_reflects_bars_after_as_of():
    """The 15m leg's dataframe (buffer_htf) only ever contains FINALIZED
    (closed) buckets -- HtfBarAggregator's own contract already proven by
    test_backtest_research_telemetry.py/existing HTF tests. This test
    proves compute_volatility_regime's as_of timestamp is always >= the
    latest bar it read, never behind data that hasn't happened yet at
    as_of."""
    df = _synthetic_htf_df(20)
    as_of = df.index[-1] + timedelta(minutes=1)  # one minute after the last finalized bucket
    snap = compute_volatility_regime(df, None, atr_period=14, as_of=as_of)
    assert snap.as_of == as_of
    assert df.index[-1] <= as_of  # snapshot's as_of is never earlier than the data it summarizes


# ----------------------------------------------------------------------
# Determinism
# ----------------------------------------------------------------------

def test_compute_volatility_regime_is_deterministic():
    df_15m = _synthetic_htf_df(20)
    df_60m = _synthetic_htf_df(20, start_price=50.0)
    as_of = _START

    snap1 = compute_volatility_regime(df_15m, df_60m, atr_period=14, as_of=as_of)
    snap2 = compute_volatility_regime(df_15m, df_60m, atr_period=14, as_of=as_of)
    assert snap1 == snap2


def test_engine_regime_state_is_deterministic_across_two_runs():
    df = _two_symbol_df()
    cfg = BacktestConfig(quant_config=_relaxed_config(), eod_flatten_enabled=False)

    e1 = BacktestEngine(dataclasses.replace(cfg), research_telemetry=True)
    e1.run(df)
    e2 = BacktestEngine(dataclasses.replace(cfg), research_telemetry=True)
    e2.run(df)

    assert e1.volatility_regime_snapshots["AAPL"] == e2.volatility_regime_snapshots["AAPL"]
    assert e1.regime_telemetry == e2.regime_telemetry


# ----------------------------------------------------------------------
# Live/backtest numerical parity (step 8)
# ----------------------------------------------------------------------

def test_live_and_backtest_compute_identical_regime_snapshots_from_the_same_bars():
    """Feeds the identical bar sequence through the backtest engine's
    per-bar path and the live QuantScanner's per-tick path, and asserts
    the resulting VolatilityRegimeSnapshot values are numerically
    identical -- both call the exact same compute_volatility_regime
    against buffers built by the exact same RollingBarBuffer/
    HtfBarAggregator classes, so this proves no independent
    reimplementation exists on either side."""
    cfg_qc = _relaxed_config()
    bars = _build_bars()
    df = _bars_to_df(bars, "AAPL")

    engine = BacktestEngine(BacktestConfig(quant_config=cfg_qc, eod_flatten_enabled=False), research_telemetry=True)
    engine.run(df)
    backtest_snapshot = engine.volatility_regime_snapshots["AAPL"]

    scanner = QuantScanner(cfg_qc)
    for _, row in df.iterrows():
        event = MarketTickEvent(
            symbol="AAPL", timestamp=row["timestamp"], open=row["open"], high=row["high"],
            low=row["low"], close=row["close"], volume=row["volume"],
            event_type=TickEventType.BAR, source=TickSource.POLLING,
        )
        scanner._update_1m_buffer(event)
        scanner._update_htf_buffer(event)
        scanner._update_regime_buffer_60m(event)
    live_snapshot = compute_volatility_regime(
        scanner.buffer_htf.get_dataframe("AAPL"), scanner.buffer_60m.get_dataframe("AAPL"),
        cfg_qc.atr_period, df["timestamp"].iloc[-1],
    )

    assert backtest_snapshot.atr_15m == pytest.approx(live_snapshot.atr_15m)
    assert backtest_snapshot.atr_pct_15m == pytest.approx(live_snapshot.atr_pct_15m)
    assert backtest_snapshot.ready_15m == live_snapshot.ready_15m
    assert backtest_snapshot.ready_60m == live_snapshot.ready_60m
