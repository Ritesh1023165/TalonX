"""
talonx_quant.indicators
---------------------------
Computes RSI, MACD, moving average crossover inputs, volume surge ratio,
and ATR (14-period, plus this bar's own true range) for a symbol's
buffered OHLCV DataFrame, via pandas_ta.

DEPENDENCY NOTE (2026-08-16 quant audit): older pandas_ta releases
(<=0.3.14b0) reference `numpy.NaN`, which was removed in NumPy 2.0 --
importing pandas_ta against numpy>=2.0 raised
`AttributeError: module 'numpy' has no attribute 'NaN'` unless a
developer manually patched it before import (`numpy.NaN = numpy.nan`).
Fixed at the dependency level, not a runtime patch here: talonx_quant's
requirements.txt now floors on `pandas_ta>=0.4.71b0` (the pandas-ta.dev
fork, which dropped the `numpy.NaN` reference) with an explicit
`numpy>=2.0,<3.0` pin -- relying on every developer remembering a manual
monkeypatch before `pip install` is fragile and was flagged as a DevOps
risk; a correct dependency floor makes the whole class of failure
unreachable instead.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import timezone
from zoneinfo import ZoneInfo

import pandas as pd

from talonx_quant.config import QuantConfig

logger = logging.getLogger("talonx_quant.indicators")

_ET = ZoneInfo("America/New_York")


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

    # Dual Volume Baselines: the volume-surge baseline is restricted to
    # the trailing contiguous run of bars sharing the LATEST bar's
    # session tag, so a regular-session bar's volume is never compared
    # against a 20-bar window still mostly full of thin pre-market
    # volume (or vice versa) -- the instant the session changes, this
    # baseline goes back to None (a fresh warm-up) until enough
    # same-session bars accumulate, rather than blending two
    # structurally different liquidity regimes into one average.
    # RSI/MACD/SMA above are deliberately NOT restricted this way.
    session_tail = _same_session_tail(df)
    volume_avg_series = session_tail["volume"].rolling(window=config.volume_avg_period).mean()
    dollar_volume_series = (
        session_tail["volume"] * session_tail["close"]
    ).rolling(window=config.volume_avg_period).mean()

    # ATR is deliberately CONTINUOUS across the session boundary (2026-08-16
    # quant audit, P1) -- NOT session-restricted the way the volume
    # baseline above is. An earlier version reset ATR's window to the
    # same-session tail too, which meant the first handful of bars after
    # the regular-session open computed ATR (and bar_true_range's
    # "previous close") from only 1-3 new bars -- a 09:30-09:45 opening
    # range that typically runs 3-5x wider than midday, giving a wildly
    # unstable, artificially inflated baseline right when the ATR-move
    # gate and structural R:R's risk distance most need a STABLE read.
    # Volatility itself doesn't reset at a session boundary the way
    # LIQUIDITY does (pre-market volume is thin because of low
    # participation, not because true price range resets to zero), so a
    # rolling ATR that spans the boundary is the more accurate model.
    atr_series = df.ta.atr(length=config.atr_period) if len(df) > config.atr_period else None

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
    # atr_period bars. Continuous across the session boundary, same as
    # atr_series above -- previous close is simply the prior row in the
    # full buffer, not session-restricted. None only on the very first
    # bar of the buffer overall (no previous close exists at all yet).
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


@dataclass(frozen=True)
class VolatilityRegimeSnapshot:
    """Task 40 (multi-timeframe volatility regime STATE -- see
    docs/research/TALONX_RESEARCH_LEDGER.md Task 39/40 entries):
    observability-only readings of ATR(atr_period) on two coarser
    timeframes (15-minute, 60-minute), alongside the SAME 1-minute
    ATR(14)/price >= min_atr_pct gate this does NOT touch or replace.

    Deliberately NOT wired into any eligibility decision -- there is no
    PASS/FAIL field here on purpose. `ready_15m`/`ready_60m` report
    warm-up state honestly (True only once that leg's ATR is actually
    computable); `atr_pct_15m`/`atr_pct_60m` can independently be None
    even when `ready` is True, if the leg's own latest close is
    missing/non-positive (see `_regime_leg_atr`'s zero/invalid-price
    handling) -- warm-up and price-validity are kept as separate
    concerns, never conflated into one boolean."""
    atr_15m: float | None
    atr_pct_15m: float | None
    ready_15m: bool
    atr_60m: float | None
    atr_pct_60m: float | None
    ready_60m: bool
    as_of: pd.Timestamp


def _regime_leg_atr(df: pd.DataFrame | None, atr_period: int) -> tuple[float | None, float | None, bool]:
    """One leg (one timeframe) of a VolatilityRegimeSnapshot. Reuses the
    EXACT same `df.ta.atr(length=atr_period)` call compute_indicators
    already uses for the 1-minute case -- no second ATR formula.
    `df` is expected already closed-bar-only (whatever RollingBarBuffer
    it came from only ever holds finalized HtfBarAggregator buckets), so
    this never needs its own causality check.

    Denominator (documented, single convention for BOTH timeframes):
    this leg's OWN latest buffered bar's close -- not the primary
    1-minute snapshot's price. Each timeframe is normalized against its
    own most recent reading, avoiding a subtle cross-buffer staleness
    coupling (e.g. a 15m leg whose own last close is meaningfully older
    than the freshest 1-minute tick).

    `ready` is strictly about WARM-UP (enough bars for a real ATR
    value) -- kept separate from price validity: a leg can be `ready`
    with `atr_pct=None` if its latest close happens to be missing,
    zero, or negative (defensive; not expected in real data)."""
    if df is None or len(df) <= atr_period:
        return None, None, False
    atr_series = df.ta.atr(length=atr_period)
    if atr_series is None:
        return None, None, False
    valid = atr_series.dropna()
    if valid.empty:
        return None, None, False
    atr = float(valid.iloc[-1])
    price = df["close"].iloc[-1]
    atr_pct = None
    if price is not None and pd.notna(price) and price > 0:
        atr_pct = atr / float(price) * 100
    return atr, atr_pct, True


def compute_volatility_regime(
    df_15m: pd.DataFrame | None, df_60m: pd.DataFrame | None, atr_period: int, as_of: pd.Timestamp,
) -> VolatilityRegimeSnapshot:
    """Task 40: the ONE authoritative calculation path for both the
    15-minute leg (reusing the existing 15m HTF buffer's dataframe
    unchanged) and the 60-minute leg (a new, equally-causal buffer) --
    called identically by talonx_backtest.engine and talonx_quant.consumer
    so live and backtest can never independently drift. Observability
    only: callers must not use this to gate signal eligibility (Task 40
    scope; see min_atr_pct, unchanged, for the only currently-active
    volatility gate)."""
    atr_15m, atr_pct_15m, ready_15m = _regime_leg_atr(df_15m, atr_period)
    atr_60m, atr_pct_60m, ready_60m = _regime_leg_atr(df_60m, atr_period)
    return VolatilityRegimeSnapshot(
        atr_15m=atr_15m, atr_pct_15m=atr_pct_15m, ready_15m=ready_15m,
        atr_60m=atr_60m, atr_pct_60m=atr_pct_60m, ready_60m=ready_60m, as_of=as_of,
    )


# ------------------------------------------------------------------
# Task 42: shadow-only regime ELIGIBILITY evaluator -- Contract B
# (SLOW_REGIME_WITH_FAST_CONFIRMATION), calibrated in Task 41 against
# the Task 38 35-symbol/30-day sample's own measured ATR% distributions
# (60m aggregate median, 15m aggregate P25) -- NOT searched/swept, and
# explicitly NOT permanent production constants. `PROVISIONAL_` prefix
# is deliberate: these are research calibration values for shadow
# comparison only, expected to be revisited (or replaced by a properly
# owner-reviewed constant) before ever gating a real signal. See
# docs/research/TALONX_RESEARCH_LEDGER.md Task 41/42 entries.
#
# min_atr_pct (talonx_quant.consumer._fails_min_volatility) remains the
# ONLY currently-active volatility gate -- evaluate_regime below is
# observability-only and must never be consulted by any eligibility
# decision (see that requirement enforced by
# tests/test_regime_eligibility_evaluator.py's before/after proof).
# ------------------------------------------------------------------

PROVISIONAL_REGIME_15M_THRESHOLD_PCT = 0.329
PROVISIONAL_REGIME_60M_THRESHOLD_PCT = 0.839

REGIME_ELIGIBLE = "REGIME_ELIGIBLE"
REGIME_STATE_NOT_READY = "REGIME_STATE_NOT_READY"
REGIME_15M_BELOW_THRESHOLD = "REGIME_15M_BELOW_THRESHOLD"
REGIME_60M_BELOW_THRESHOLD = "REGIME_60M_BELOW_THRESHOLD"
REGIME_BOTH_BELOW_THRESHOLD = "REGIME_BOTH_BELOW_THRESHOLD"


@dataclass(frozen=True)
class RegimeEligibilityResult:
    """Task 42: the OUTPUT of evaluate_regime -- a pure, deterministic
    read of a VolatilityRegimeSnapshot against the Contract B thresholds
    above. Shadow/telemetry only; `eligible` here is NEVER consulted by
    any gate/signal-generation code path (see the module-level note
    above)."""
    eligible: bool
    ready: bool
    reason: str
    atr_pct_15m: float | None
    atr_pct_60m: float | None
    threshold_15m: float
    threshold_60m: float
    as_of: pd.Timestamp


def evaluate_regime(snapshot: VolatilityRegimeSnapshot) -> RegimeEligibilityResult:
    """Task 42: the ONE authoritative Contract B evaluator, called
    identically by talonx_backtest.engine and talonx_quant.consumer for
    shadow telemetry only.

    `ready` here means "this evaluation could actually be performed" --
    stricter than snapshot.ready_15m/ready_60m alone (which are pure
    warm-up flags, see Task 40): a leg can be warm-up-ready yet still
    have atr_pct=None (the zero/negative/NaN-price edge case
    _regime_leg_atr already handles) -- if that happens, the evaluation
    genuinely cannot be determined, so `ready=False` here too, same
    REGIME_STATE_NOT_READY reason, and `eligible` is always False in
    that state -- NEVER a fabricated True/False. 60m is the binding
    (Contract B) leg conceptually, but this function requires BOTH legs
    determinable before evaluating either threshold -- there is no
    15m-only fallback path (per Task 42's explicit instruction)."""
    determinable = (
        snapshot.ready_15m and snapshot.ready_60m
        and snapshot.atr_pct_15m is not None and snapshot.atr_pct_60m is not None
    )
    if not determinable:
        return RegimeEligibilityResult(
            eligible=False, ready=False, reason=REGIME_STATE_NOT_READY,
            atr_pct_15m=snapshot.atr_pct_15m, atr_pct_60m=snapshot.atr_pct_60m,
            threshold_15m=PROVISIONAL_REGIME_15M_THRESHOLD_PCT,
            threshold_60m=PROVISIONAL_REGIME_60M_THRESHOLD_PCT, as_of=snapshot.as_of,
        )

    below_15m = snapshot.atr_pct_15m < PROVISIONAL_REGIME_15M_THRESHOLD_PCT
    below_60m = snapshot.atr_pct_60m < PROVISIONAL_REGIME_60M_THRESHOLD_PCT
    if below_15m and below_60m:
        reason = REGIME_BOTH_BELOW_THRESHOLD
    elif below_15m:
        reason = REGIME_15M_BELOW_THRESHOLD
    elif below_60m:
        reason = REGIME_60M_BELOW_THRESHOLD
    else:
        reason = REGIME_ELIGIBLE

    return RegimeEligibilityResult(
        eligible=(reason == REGIME_ELIGIBLE), ready=True, reason=reason,
        atr_pct_15m=snapshot.atr_pct_15m, atr_pct_60m=snapshot.atr_pct_60m,
        threshold_15m=PROVISIONAL_REGIME_15M_THRESHOLD_PCT,
        threshold_60m=PROVISIONAL_REGIME_60M_THRESHOLD_PCT, as_of=snapshot.as_of,
    )


REGIME_SHADOW_BOTH_PASS = "BOTH_PASS"
REGIME_SHADOW_BOTH_FAIL = "BOTH_FAIL"
REGIME_SHADOW_OLD_FAIL_NEW_PASS = "OLD_FAIL_NEW_PASS"
REGIME_SHADOW_OLD_PASS_NEW_FAIL = "OLD_PASS_NEW_FAIL"
REGIME_SHADOW_NEW_NOT_READY = "NEW_NOT_READY"


def classify_regime_shadow_disagreement(old_passes: bool, regime_result: RegimeEligibilityResult) -> str:
    """Task 42: compares the EXISTING, unchanged min_atr_pct decision
    (`old_passes` -- the same `not fails_volatility` value the live
    reject-or-continue branch already uses) against the new shadow-only
    Contract B evaluator's result. Pure classification, consulted by
    nothing except telemetry -- never influences `old_passes` or any
    signal/trade decision. NEW_NOT_READY takes priority: an
    undetermined new-gate read is not a real agree/disagree signal."""
    if not regime_result.ready:
        return REGIME_SHADOW_NEW_NOT_READY
    if old_passes and regime_result.eligible:
        return REGIME_SHADOW_BOTH_PASS
    if old_passes and not regime_result.eligible:
        return REGIME_SHADOW_OLD_PASS_NEW_FAIL
    if not old_passes and regime_result.eligible:
        return REGIME_SHADOW_OLD_FAIL_NEW_PASS
    return REGIME_SHADOW_BOTH_FAIL


@dataclass(frozen=True)
class DailyPivots:
    """Classic floor-trader pivot levels (P, R1, S1) from the most
    recently COMPLETED regular-trading-hours session -- the basis for
    Structural R:R Calculation (strategy.py's _structural_risk_reward):
    reward is measured to `resistance`/`support`, not a second, unrelated
    ATR multiple."""
    pivot: float
    resistance: float
    support: float


def _et_date(timestamp) -> object:
    """The America/New_York calendar date a (tz-aware or naive-assumed-UTC)
    bar timestamp falls on -- pivots are a per-CALENDAR-DAY concept, so
    grouping by this (not the raw UTC date, which can shift a late-session
    bar onto the wrong day) is what correctly separates one session's bars
    from the next."""
    if timestamp.tzinfo is None:
        timestamp = timestamp.replace(tzinfo=timezone.utc)
    return timestamp.astimezone(_ET).date()


def compute_daily_pivots(df_htf: pd.DataFrame | None, current_timestamp) -> "DailyPivots | None":
    """
    Computes P/R1/S1 from the high/low/close of the most recently
    COMPLETED regular-session's worth of bars in the 15-min HTF buffer
    (see consumer.py's buffer_htf) -- deliberately NOT the 1-min primary
    buffer, which is far too small (max_bars_per_symbol, ~200 bars/~3.3h)
    to ever hold a full prior session; the HTF buffer's ~2-trading-day
    capacity (htf_max_bars) comfortably does.

    Returns None (fail-closed, same "insufficient data -> no signal"
    posture as every other warm-up gate in this module) until at least
    one full prior regular session is present -- e.g. the first session
    after a cold start, or a df_htf built without buffer.py's session
    tagging (a hand-built test fixture with no `session` column).
    """
    if df_htf is None or df_htf.empty or "session" not in df_htf.columns:
        return None
    regular = df_htf[df_htf["session"] == "regular"]
    if regular.empty:
        return None

    current_date = _et_date(current_timestamp)
    session_dates = regular.index.map(_et_date)
    prior_dates = sorted({d for d in session_dates if d < current_date})
    if not prior_dates:
        return None

    last_session = regular[session_dates == prior_dates[-1]]
    if last_session.empty:
        return None

    high = float(last_session["high"].max())
    low = float(last_session["low"].min())
    close = float(last_session["close"].iloc[-1])
    pivot = (high + low + close) / 3.0
    return DailyPivots(
        pivot=pivot,
        resistance=(2 * pivot) - low,
        support=(2 * pivot) - high,
    )
