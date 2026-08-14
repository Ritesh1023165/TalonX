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

    # Pre-market liquidity gate input: mean(volume x close) over the same
    # trailing window as volume_avg -- "average dollar volume per minute"
    # for a symbol whose buffer is 1-min bars. None during warm-up, same
    # as every other rolling-window field here.
    dollar_volume_avg: float | None

    # Analyst-review addition: 14-period ATR (a smoothed AVERAGE true
    # range) alongside this specific bar's OWN true range -- the two are
    # deliberately separate fields. strategy.py compares them
    # (bar_true_range >= atr_move_multiplier * atr) to confirm a signal's
    # triggering bar represents a real move, not routine noise; atr alone
    # also feeds the risk/reward filter's reward-side calculation.
    atr: float | None
    bar_true_range: float | None


def _same_session_tail(df: pd.DataFrame) -> pd.DataFrame:
    """The trailing contiguous run of rows sharing the LAST row's
    `session` tag -- e.g. if the buffer holds pre-market bars followed
    by regular-session bars, this returns only the regular-session tail.
    Falls back to the full frame if there's no `session` column at all
    (a df built without buffer.py's tagging, e.g. a hand-built test
    fixture) or the column is empty/unpopulated."""
    if "session" not in df.columns or df.empty:
        return df
    sessions = df["session"]
    latest = sessions.iloc[-1]
    if pd.isna(latest):
        return df
    same = sessions == latest
    start = len(df) - 1
    while start > 0 and same.iloc[start - 1]:
        start -= 1
    return df.iloc[start:]


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
    dollar_volume_series = (df["volume"] * df["close"]).rolling(window=config.volume_avg_period).mean()

    # Session-aware ATR reset (Requirement 3): ATR/bar_true_range are
    # recomputed from scratch on every call (no persistent running
    # state to explicitly "reset"), so restricting their INPUT to the
    # trailing contiguous run of bars sharing the latest bar's session
    # tag achieves the same effect -- the instant the regular session
    # opens, pre-market bars fall out of the window on their own, and
    # ATR/bar_true_range go back to None (a fresh warm-up) until enough
    # regular-session bars accumulate, rather than blending the thin
    # pre-market range into the post-open baseline. RSI/MACD/SMA above
    # are deliberately NOT restricted this way -- only the ATR-based
    # movement-confirmation/risk-reward inputs need the reset.
    atr_df = _same_session_tail(df)
    # Guard BEFORE calling .ta.atr(), not after: pandas_ta's atr() does
    # NOT return a NaN-filled Series when given fewer than length+1 rows
    # (the behavior compute_indicators previously relied on) -- it
    # silently returns the INPUT DATAFRAME unchanged instead. That never
    # surfaced before this function's own len(df) < min_bars_required
    # gate above always guaranteed df (the full buffer) had 120+ rows by
    # the time any pandas_ta call ran on it -- but atr_df is a
    # session-restricted SUBSET that can be far shorter right at a
    # session transition (confirmed live: crashed talonx_quant in a
    # reconnect loop for 40+ consecutive attempts at market close, when
    # the newest bars' session flips and _same_session_tail narrows to
    # just a handful of them). _last_two() then called float() on a
    # one-row DataFrame slice (a Series, not a scalar), raising
    # "float() argument must be a string or a real number, not 'Series'".
    atr_series = atr_df.ta.atr(length=config.atr_period) if len(atr_df) > config.atr_period else None

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
    dollar_volume_avg_latest, _ = _last_two(dollar_volume_series)
    atr_latest = None if atr_series is None else _last_two(atr_series)[0]

    latest_row = df.iloc[-1]
    volume_latest = float(latest_row["volume"]) if pd.notna(latest_row["volume"]) else None
    volume_surge_ratio = None
    if volume_latest is not None and volume_avg_latest and volume_avg_latest > 0:
        volume_surge_ratio = volume_latest / volume_avg_latest

    # This specific bar's true range -- max(high-low, |high-prev_close|,
    # |low-prev_close|), the SAME formula ATR itself averages over
    # atr_period bars. Needs a previous close FROM THE SAME SESSION
    # (see atr_df above) -- None on the first bar of a session (e.g. the
    # regular-session open right after a pre-market run), same as the
    # first bar of the buffer overall.
    bar_true_range = None
    if len(atr_df) >= 2:
        high, low, close = latest_row["high"], latest_row["low"], latest_row["close"]
        prev_close = atr_df.iloc[-2]["close"]
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
        dollar_volume_avg=dollar_volume_avg_latest,
        atr=atr_latest,
        bar_true_range=bar_true_range,
    )


def compute_htf_trend(df_htf: pd.DataFrame | None, period: int) -> float | None:
    """SMA(period) of the higher-timeframe buffer's close column -- None
    if the HTF buffer doesn't have `period` bars yet (warm-up), same
    tolerant posture as compute_indicators' own min_bars_required check.
    Deliberately separate from compute_indicators: the HTF buffer is a
    second, independently-sized RollingBarBuffer (see consumer.py), not
    part of the primary 1-min df this function's sibling operates on."""
    if df_htf is None or len(df_htf) < period:
        return None
    sma = df_htf["close"].rolling(window=period).mean()
    valid = sma.dropna()
    if valid.empty:
        return None
    return float(valid.iloc[-1])
