"""
tests/test_backtest_regression.py
--------------------------------------
Spec section 27 -- "The backtester must prove that the same historical
candle sequence produces the same strategy candidate signals as the live
strategy."

The live consumer's closed-bar path (consumer.py's _handle_market_tick)
is: buffer.add_bar -> compute_indicators -> compute_htf_trend/
compute_daily_pivots -> evaluate_signals. This test drives that EXACT
same sequence of calls directly ("the live pipeline"), bar by bar, over
a deterministic OHLCV fixture, and separately runs the identical bars
through BacktestEngine ("the backtester"). Because both routes call the
SAME talonx_quant functions (no reimplementation exists to diverge --
see engine.py's own module docstring), the two candidate-signal logs
must match exactly, in order, on every field a QuantSignal reports.
"""
from __future__ import annotations

import dataclasses
from datetime import datetime, timedelta, timezone

import pandas as pd
import pytest

from talonx_backtest.data import from_dataframe
from talonx_backtest.engine import BacktestConfig, BacktestEngine
from talonx_quant.aggregation import HtfBarAggregator
from talonx_quant.buffer import RollingBarBuffer
from talonx_quant.config import QuantConfig
from talonx_quant.indicators import compute_daily_pivots, compute_htf_trend, compute_indicators
from talonx_quant.strategy import evaluate_signals

_START = datetime(2026, 1, 5, 15, 0, tzinfo=timezone.utc)


def _relaxed_config() -> QuantConfig:
    return dataclasses.replace(QuantConfig(), atr_move_multiplier=0.0, min_atr_pct=0.0)


def _build_bars(n_warmup: int = 260) -> list[tuple[float, float, float, float, float]]:
    """Long enough to warm up BOTH the 1-min buffer (min_bars_required)
    and the 15-min HTF buffer across a session boundary (so
    compute_daily_pivots/compute_htf_trend produce real, non-None values
    at least some of the time -- exercising the trend gate's
    HTF-dependent path, not just the RSI/MACD/MA checks)."""
    bars = []
    price = 100.0
    for i in range(n_warmup):
        # a mix of small oscillation and a few deliberate swings so
        # RSI/MACD/MA crossovers actually fire more than once
        if i % 47 == 0 and i > 0:
            price -= 3.0
        elif i % 61 == 0 and i > 0:
            price += 3.5
        else:
            price += 0.05 if i % 2 == 0 else -0.03
        vol = 5000.0 if i % 47 == 1 else 1000.0 + (i % 5) * 50
        bars.append((price, price + 0.4, price - 0.4, price, vol))
    return bars


def _bars_to_df(bars, symbol: str = "AAPL") -> pd.DataFrame:
    rows = [
        {"timestamp": _START + timedelta(minutes=i), "open": o, "high": h, "low": l, "close": c, "volume": v}
        for i, (o, h, l, c, v) in enumerate(bars)
    ]
    return from_dataframe(pd.DataFrame(rows), symbol=symbol)


def _run_live_pipeline_directly(df: pd.DataFrame, config: QuantConfig, symbol: str = "AAPL") -> list[dict]:
    """Replays the exact live closed-bar sequence
    (consumer.py's own docstring: buffer.add_bar -> compute_indicators ->
    compute_htf_trend/compute_daily_pivots -> evaluate_signals) without
    going through BacktestEngine at all -- this IS "the live strategy",
    called directly, bar by bar."""
    buffer = RollingBarBuffer(config.max_bars_per_symbol)
    buffer_htf = RollingBarBuffer(config.htf_max_bars)
    htf_aggregator = HtfBarAggregator(config.htf_bar_interval_minutes, rth_only=config.rth_only_htf_sma)

    log: list[dict] = []
    for _, row in df.iterrows():
        timestamp = row["timestamp"]
        buffer.add_bar(
            symbol=symbol, timestamp=timestamp, open_=float(row["open"]), high=float(row["high"]),
            low=float(row["low"]), close=float(row["close"]), volume=float(row["volume"]),
        )
        finalized = htf_aggregator.update(
            symbol=symbol, timestamp=timestamp, open_=float(row["open"]), high=float(row["high"]),
            low=float(row["low"]), close=float(row["close"]), volume=float(row["volume"]),
        )
        if finalized is not None:
            buffer_htf.add_bar(
                symbol=symbol, timestamp=finalized["timestamp"], open_=finalized["open"],
                high=finalized["high"], low=finalized["low"], close=finalized["close"],
                volume=finalized["volume"],
            )

        snapshot = compute_indicators(buffer.get_dataframe(symbol), config)
        if snapshot is None:
            continue

        df_htf = buffer_htf.get_dataframe(symbol)
        htf_sma_200 = compute_htf_trend(df_htf, config.htf_sma_period)
        daily_pivots = compute_daily_pivots(df_htf, snapshot.bar_timestamp)
        signals = evaluate_signals(symbol, snapshot, config, htf_sma_200=htf_sma_200, daily_pivots=daily_pivots)
        for s in signals:
            log.append({
                "timestamp": timestamp, "ticker": symbol, "signal_type": s.signal_type.value,
                "direction": s.direction.value, "price": s.price, "rsi": s.rsi,
                "confluence_score": s.confluence_score, "risk_reward_ratio": s.risk_reward_ratio,
            })
    return log


def test_backtester_reproduces_the_exact_same_candidate_signals_as_the_live_pipeline():
    config = _relaxed_config()
    df = _bars_to_df(_build_bars())

    expected = _run_live_pipeline_directly(df, config)
    assert expected, "test fixture produced no candidates at all -- strengthen it"

    engine = BacktestEngine(BacktestConfig(quant_config=config, eod_flatten_enabled=False))
    engine.run(df)

    assert engine.signal_log == expected


def test_regression_fixture_covers_more_than_one_signal_type():
    """A fixture that only ever exercises one signal_type would be a
    weak regression proof -- confirm this one exercises at least two of
    strategy.py's six SignalTypes."""
    config = _relaxed_config()
    df = _bars_to_df(_build_bars())
    expected = _run_live_pipeline_directly(df, config)
    types_seen = {row["signal_type"] for row in expected}
    assert len(types_seen) >= 2, f"fixture only exercised {types_seen}"


def test_backtester_matches_live_pipeline_with_trend_gate_and_default_thresholds_enabled():
    """Same proof, but with the trend gate ENABLED and every threshold at
    its true production default (only atr_move_multiplier/min_atr_pct
    relaxed, matching the other regression test, so this isn't
    recalibrating the strategy -- it's exercising the trend-gate/HTF
    code path the other test disables)."""
    config = dataclasses.replace(QuantConfig(), atr_move_multiplier=0.0, min_atr_pct=0.0, trend_gate_enabled=True)
    df = _bars_to_df(_build_bars())

    expected = _run_live_pipeline_directly(df, config)
    engine = BacktestEngine(BacktestConfig(quant_config=config, eod_flatten_enabled=False))
    engine.run(df)

    assert engine.signal_log == expected
