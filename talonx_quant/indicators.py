"""
talonx_quant.indicators
---------------------------
Computes RSI, MACD, moving average crossover inputs, volume surge ratio,
and ATR (14-period, plus this bar's own true range) for a symbol's
buffered OHLCV DataFrame, via pandas_ta.

KNOWN COMPATIBILITY CAVEAT: pandas_ta (as of its last released version)
references `numpy.NaN`, which was removed in NumPy 2.0 -- importing
pandas_ta against numpy>=2.0 raises `AttributeError: module 'numpy' has
no attribute 'NaN'`. If you hit that on `pip install`, either pin
`numpy<2` in your environment, or patch pandas_ta locally (add
`numpy.NaN = numpy.nan` before importing it, e.g. at the top of this
module) -- both are common workarounds until upstream releases a fix.
This module does NOT apply that patch automatically; it's left visible
here so you know exactly where to add it if needed.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass

import pandas as pd

from talonx_quant.config import QuantConfig

logger = logging.getLogger("talonx_quant.indicators")


@dataclass(frozen=True)
class IndicatorSnapshot:
    """Latest + previous-bar values needed for both threshold and crossover checks."""
    price: float
    bar_timestamp: pd.Timestamp

    rsi: float | None
    rsi_prev: float | None

    macd: float | None
    macd_signal_line: float | None
    macd_prev: float | None
    macd_signal_line_prev: float | None

    sma_fast: float | None
    sma_slow: float | None
    sma_fast_prev: float | None
    sma_slow_prev: float | None

    volume: float | None
    volume_avg: float | None
    volume_surge_ratio: float | None

    # Analyst-review addition: 14-period ATR (a smoothed AVERAGE true
    # range) alongside this specific bar's OWN true range -- the two are
    # deliberately separate fields. strategy.py compares them
    # (bar_true_range >= atr_move_multiplier * atr) to confirm a signal's
    # triggering bar represents a real move, not routine noise; atr alone
    # also feeds the risk/reward filter's reward-side calculation.
    atr: float | None
    bar_true_range: float | None


def compute_indicators(df: pd.DataFrame, config: QuantConfig) -> IndicatorSnapshot | None:
    """
    Returns None if there isn't enough buffered history yet
    (config.min_bars_required) or if the computed indicators don't have
    at least 2 valid (non-NaN) trailing values -- both RSI/MACD/SMA need
    a warm-up period before they're meaningful, and crossover detection
    specifically needs a "previous" value as well as a "current" one.
    """
    if len(df) < config.min_bars_required:
        return None

    import pandas_ta as ta  # noqa: F401 -- imported for its df.ta accessor side effect

    rsi_series = df.ta.rsi(length=config.rsi_period)
    macd_df = df.ta.macd(
        fast=config.macd_fast, slow=config.macd_slow, signal=config.macd_signal
    )
    sma_fast_series = df.ta.sma(length=config.ma_fast_period)
    sma_slow_series = df.ta.sma(length=config.ma_slow_period)
    volume_avg_series = df["volume"].rolling(window=config.volume_avg_period).mean()
    atr_series = df.ta.atr(length=config.atr_period)

    if macd_df is None or rsi_series is None:
        logger.warning("pandas_ta returned None for RSI/MACD -- insufficient data or version mismatch")
        return None

    macd_col = f"MACD_{config.macd_fast}_{config.macd_slow}_{config.macd_signal}"
    macd_signal_col = f"MACDs_{config.macd_fast}_{config.macd_slow}_{config.macd_signal}"
    if macd_col not in macd_df.columns or macd_signal_col not in macd_df.columns:
        logger.warning(
            "Expected MACD columns not found (got %s) -- pandas_ta column "
            "naming may have changed; check installed version", list(macd_df.columns),
        )
        return None

    def _last_two(series: pd.Series) -> tuple[float | None, float | None]:
        valid = series.dropna()
        if len(valid) < 2:
            return (None, None)
        return (float(valid.iloc[-1]), float(valid.iloc[-2]))

    rsi_latest, rsi_prev = _last_two(rsi_series)
    macd_latest, macd_prev = _last_two(macd_df[macd_col])
    macd_signal_latest, macd_signal_prev = _last_two(macd_df[macd_signal_col])
    sma_fast_latest, sma_fast_prev = _last_two(sma_fast_series)
    sma_slow_latest, sma_slow_prev = _last_two(sma_slow_series)
    volume_avg_latest, _ = _last_two(volume_avg_series)
    atr_latest = None if atr_series is None else _last_two(atr_series)[0]

    latest_row = df.iloc[-1]
    volume_latest = float(latest_row["volume"]) if pd.notna(latest_row["volume"]) else None
    volume_surge_ratio = None
    if volume_latest is not None and volume_avg_latest and volume_avg_latest > 0:
        volume_surge_ratio = volume_latest / volume_avg_latest

    # This specific bar's true range -- max(high-low, |high-prev_close|,
    # |low-prev_close|), the SAME formula ATR itself averages over
    # atr_period bars. Needs a previous close, so it's None on the very
    # first bar of the buffer (never happens in practice -- min_bars_required
    # is always > 1).
    bar_true_range = None
    if len(df) >= 2:
        high, low, close = latest_row["high"], latest_row["low"], latest_row["close"]
        prev_close = df.iloc[-2]["close"]
        if pd.notna(high) and pd.notna(low) and pd.notna(close) and pd.notna(prev_close):
            bar_true_range = max(
                float(high) - float(low),
                abs(float(high) - float(prev_close)),
                abs(float(low) - float(prev_close)),
            )

    return IndicatorSnapshot(
        price=float(latest_row["close"]),
        bar_timestamp=df.index[-1],
        rsi=rsi_latest,
        rsi_prev=rsi_prev,
        macd=macd_latest,
        macd_signal_line=macd_signal_latest,
        macd_prev=macd_prev,
        macd_signal_line_prev=macd_signal_prev,
        sma_fast=sma_fast_latest,
        sma_slow=sma_slow_latest,
        sma_fast_prev=sma_fast_prev,
        sma_slow_prev=sma_slow_prev,
        volume=volume_latest,
        volume_avg=volume_avg_latest,
        volume_surge_ratio=volume_surge_ratio,
        atr=atr_latest,
        bar_true_range=bar_true_range,
    )
