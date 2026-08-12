"""
tests/test_quant_indicators.py
------------------------------------
Tests talonx_quant.indicators.compute_indicators against a real
RollingBarBuffer + pandas_ta call (no mocking of the indicator math
itself) -- the ATR/bar_true_range fields added for the analyst-review
risk/reward and movement-confirmation filters are new enough (and
mechanical enough to get subtly wrong) to warrant exercising the real
pandas_ta accessor rather than only testing strategy.py's pure functions
against a hand-built IndicatorSnapshot.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from talonx_quant.buffer import RollingBarBuffer
from talonx_quant.config import QuantConfig


def _seed_buffer(bar_count: int, *, last_high: float | None = None, last_low: float | None = None, last_close: float | None = None) -> RollingBarBuffer:
    """
    Seeds a buffer with `bar_count` bars of mild, deterministic price
    movement (so RSI/MACD/ATR all have real, non-degenerate history), then
    optionally overrides the LAST bar's high/low/close -- lets a test
    control the final bar's true range precisely while keeping everything
    upstream realistic.
    """
    buf = RollingBarBuffer(max_bars_per_symbol=bar_count + 5)
    start = datetime(2026, 8, 1, 9, 30, tzinfo=timezone.utc)
    price = 100.0
    for i in range(bar_count):
        price += 0.1 if i % 2 == 0 else -0.05  # mild deterministic drift
        high, low, close = price + 0.5, price - 0.5, price
        if i == bar_count - 1:
            high = last_high if last_high is not None else high
            low = last_low if last_low is not None else low
            close = last_close if last_close is not None else close
        buf.add_bar(
            symbol="AAPL", timestamp=start + timedelta(minutes=i),
            open_=price, high=high, low=low, close=close, volume=1000.0 + i,
        )
    return buf


@pytest.fixture
def config() -> QuantConfig:
    return QuantConfig()


def test_compute_indicators_returns_none_below_min_bars(config):
    from talonx_quant.indicators import compute_indicators

    buf = _seed_buffer(config.min_bars_required - 1)
    df = buf.get_dataframe("AAPL")

    assert compute_indicators(df, config) is None


def test_compute_indicators_returns_atr_once_warmed_up(config):
    from talonx_quant.indicators import compute_indicators

    buf = _seed_buffer(config.min_bars_required)
    df = buf.get_dataframe("AAPL")

    snapshot = compute_indicators(df, config)

    assert snapshot is not None
    assert snapshot.atr is not None
    assert snapshot.atr > 0


def test_bar_true_range_matches_manual_formula(config):
    from talonx_quant.indicators import compute_indicators

    # Force the final bar's high/low far from the prior close so the
    # true-range formula's max() picks a specific, hand-checkable branch.
    buf = _seed_buffer(config.min_bars_required, last_high=150.0, last_low=140.0, last_close=145.0)
    df = buf.get_dataframe("AAPL")
    prev_close = float(df.iloc[-2]["close"])

    snapshot = compute_indicators(df, config)

    expected = max(150.0 - 140.0, abs(150.0 - prev_close), abs(140.0 - prev_close))
    assert snapshot.bar_true_range == pytest.approx(expected)


def test_bar_true_range_none_prev_close_is_used_correctly_for_gap_up(config):
    from talonx_quant.indicators import compute_indicators

    # A gap-up bar: high/low are both ABOVE the prior close, so the
    # |high - prev_close| branch should dominate over high-low.
    buf = _seed_buffer(config.min_bars_required, last_high=200.0, last_low=199.0, last_close=199.5)
    df = buf.get_dataframe("AAPL")
    prev_close = float(df.iloc[-2]["close"])

    snapshot = compute_indicators(df, config)

    assert snapshot.bar_true_range == pytest.approx(abs(200.0 - prev_close))


def test_indicator_snapshot_fields_are_all_present(config):
    from talonx_quant.indicators import compute_indicators

    buf = _seed_buffer(config.min_bars_required)
    df = buf.get_dataframe("AAPL")

    snapshot = compute_indicators(df, config)

    # Regression guard: every field IndicatorSnapshot declares must be
    # populated (not silently dropped) once there's enough warmed-up
    # history -- both the pre-existing indicators and the new ATR ones.
    assert snapshot.rsi is not None
    assert snapshot.macd is not None
    assert snapshot.sma_fast is not None
    assert snapshot.sma_slow is not None
    assert snapshot.volume_surge_ratio is not None
    assert snapshot.atr is not None
    assert snapshot.bar_true_range is not None
