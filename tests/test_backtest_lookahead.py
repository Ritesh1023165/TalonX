"""
tests/test_backtest_lookahead.py
-------------------------------------
Look-ahead-bias tests for talonx_backtest.engine (spec section 3): a
candidate signal generated off a given closed bar must NEVER depend on
any bar with a LATER timestamp -- the strategy must only ever see what
would genuinely have been available at that instant.

The most direct proof: run the SAME engine on two datasets that are
identical up to a cutoff timestamp and differ only in what happens
AFTER it. Every candidate/rejection recorded at or before the cutoff
must be byte-for-byte identical between the two runs -- if a later bar's
data ever leaked backward, truncating it would change the earlier
result.
"""
from __future__ import annotations

import dataclasses
from datetime import datetime, timedelta, timezone

import pandas as pd
import pytest

from talonx_backtest.data import from_dataframe
from talonx_backtest.engine import BacktestConfig, BacktestEngine
from talonx_quant.config import QuantConfig

_START = datetime(2026, 1, 5, 15, 0, tzinfo=timezone.utc)  # 10:00 ET (Jan -> EST), regular session


def _relaxed_config() -> QuantConfig:
    """Loosens only the gates that would otherwise require calibrating
    exact RSI/pivot values to exercise (atr-move gate, min-volatility
    floor, and the trend gate, which needs a full prior session of HTF
    data this short fixture doesn't build) -- RSI/MACD/MA thresholds
    themselves, confluence, and R:R are all left at production defaults.
    """
    return dataclasses.replace(
        QuantConfig(), atr_move_multiplier=0.0, min_atr_pct=0.0, trend_gate_enabled=False,
    )


def _build_bars() -> list[tuple[float, float, float, float, float]]:
    """150 bars of mild oscillating drift (warm-up), a 10-bar decline, a
    sharp volume-spiking recovery bar, then 5 more drifting bars --
    deliberately busy enough (MACD/MA crosses fire repeatedly once the
    buffer is warmed up) to give a look-ahead test many candidate
    timestamps to compare, not just one hand-picked bar."""
    bars = []
    price = 100.0
    for i in range(150):
        price += 0.05 if i % 2 == 0 else -0.03
        bars.append((price, price + 0.3, price - 0.3, price, 1000.0))
    for _ in range(10):
        price -= 1.5
        bars.append((price + 1.5, price + 1.6, price - 0.2, price, 1200.0))
    price += 4.0
    bars.append((price - 4.0, price + 0.5, price - 4.2, price, 6000.0))
    for _ in range(5):
        price += 0.2
        bars.append((price - 0.2, price + 0.5, price - 0.5, price, 1000.0))
    return bars


def _bars_to_df(bars: list[tuple[float, float, float, float, float]], symbol: str = "AAPL") -> pd.DataFrame:
    rows = []
    for i, (o, h, l, c, v) in enumerate(bars):
        rows.append({
            "timestamp": _START + timedelta(minutes=i), "open": o, "high": h, "low": l, "close": c, "volume": v,
        })
    return from_dataframe(pd.DataFrame(rows), symbol=symbol)


@pytest.fixture(scope="module")
def full_and_truncated_results():
    bars = _build_bars()
    cutoff_index = 140  # well inside the busy region, with candidates on both sides of it
    cutoff_ts = _START + timedelta(minutes=cutoff_index)

    full_df = _bars_to_df(bars)
    truncated_df = full_df[full_df["timestamp"] <= cutoff_ts].reset_index(drop=True)
    assert len(truncated_df) < len(full_df), "test fixture must actually have data AFTER the cutoff"

    cfg = BacktestConfig(quant_config=_relaxed_config(), eod_flatten_enabled=False)

    engine_full = BacktestEngine(dataclasses.replace(cfg))
    engine_full.run(full_df)

    engine_trunc = BacktestEngine(dataclasses.replace(cfg))
    engine_trunc.run(truncated_df)

    return cutoff_ts, engine_full, engine_trunc


def test_signal_log_up_to_cutoff_is_identical_with_or_without_future_data(full_and_truncated_results):
    cutoff_ts, engine_full, engine_trunc = full_and_truncated_results

    full_up_to_cutoff = [s for s in engine_full.signal_log if s["timestamp"] <= cutoff_ts]
    assert full_up_to_cutoff == engine_trunc.signal_log
    assert len(full_up_to_cutoff) > 0, "test fixture produced no candidates at all -- strengthen it"


def test_rejections_up_to_cutoff_are_identical_with_or_without_future_data(full_and_truncated_results):
    cutoff_ts, engine_full, engine_trunc = full_and_truncated_results

    full_up_to_cutoff = [r for r in engine_full.rejections if r.timestamp <= cutoff_ts]
    assert full_up_to_cutoff == engine_trunc.rejections


def test_a_specific_signals_own_reported_fields_are_stable_under_truncation(full_and_truncated_results):
    """Not just counts -- the actual price/RSI/confluence/R:R values
    attached to one specific candidate must be identical whether or not
    the dataset continues past it."""
    cutoff_ts, engine_full, engine_trunc = full_and_truncated_results
    assert engine_trunc.signal_log, "no candidates recorded in the truncated run"

    last_trunc_signal = engine_trunc.signal_log[-1]
    matching_full = [
        s for s in engine_full.signal_log
        if s["timestamp"] == last_trunc_signal["timestamp"] and s["ticker"] == last_trunc_signal["ticker"]
        and s["signal_type"] == last_trunc_signal["signal_type"]
    ]
    assert matching_full, "could not find the corresponding candidate in the full run"
    assert matching_full[0] == last_trunc_signal


def test_signals_generated_count_matches_up_to_cutoff(full_and_truncated_results):
    cutoff_ts, engine_full, engine_trunc = full_and_truncated_results
    full_count = sum(1 for s in engine_full.signal_log if s["timestamp"] <= cutoff_ts)
    assert full_count == engine_trunc.signals_generated
