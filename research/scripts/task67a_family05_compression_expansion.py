"""
research/scripts/task67a_family05_compression_expansion.py
------------------------------------------------------------
Task 67B Step 2, Family 5: COMPRESSION -> EXPANSION (compression as a
PRECONDITION, not the act of expansion).

Question: does sitting in a compressed volatility state predict LATER
unusually large movement and/or directional persistence, evaluated at
horizons AFTER the compressed bar -- with NO requirement that expansion
has already begun? This is the deliberate complement to Family 3
(volatility/range EXPANSION), whose event condition was "expansion is
ALREADY HAPPENING NOW" (an established-quiet-baseline followed
IMMEDIATELY by a same-window ATR breakout). Family 5's event condition
never looks at a "recent/expansion" window at all -- only at whether the
bar currently sits in (or has been sitting in, or is trending toward) a
compressed state. All shared mechanics (dedup, horizon/MFE-MAE, matched
control, bootstrap, concentration, effect surface, economic
classification, verdict) are delegated to
research/task67a_lib/family_runner.py; this script owns only the event-
CONDITION logic for three broad definitions, plus the extra unsigned
"volatility-effect" analysis described below.

Exploratory, read-only, DEVELOPMENT-data-only phenomenon discovery -- NOT
a trading engine, NOT a backtest, NOT strategy freezing. Data access is
exclusively via research.task67a_lib.data_guard's STAGE1_DISCOVERY_GUARD
(DEVELOPMENT role only). talonx_quant/orpb_v1.py was never opened or
referenced while designing this. Per the brief, this family excludes the
first 30 minutes of RTH (reusing `screening_framework.
POST_OPENING_RANGE_UTC_HOUR`, the same 14:00 UTC cutoff Family 3 uses,
for the same rationale -- general/later-session compression, ORPB
territory out of scope) and requires a minimum lead time before session
close (reusing the ~15min min-lead pattern).

Definitions (each is a distinct construction of "currently compressed",
none of them require expansion to have started):

  A) persistent_compression_atr30_persist30: trailing 30m ATR proxy
     (`causal_atr_proxy`, as a fraction of price) in the bottom GLOBAL
     tertile, continuously, for the ENTIRE trailing 30 minutes -- not
     just at the current instant. This is a genuinely stronger
     requirement than "current 30m ATR proxy happens to average low"
     (a brief spike inside the window could still leave the mean low);
     `_persistently_compressed_mask` below checks every bar in the
     trailing window individually.

  B) relative_narrow_range_15v90: current 15m rolling high-low range,
     expressed as a PACE (range / window_minutes) and divided by the
     SAME symbol's own trailing 90m high-low range pace (i.e. the
     symbol's own "typical" recent range-per-minute) -- a per-symbol-
     normalized ratio, in the bottom GLOBAL tertile. This tests "is the
     recent window narrow relative to what THIS symbol has itself been
     doing lately", not an absolute $ range threshold (which would
     conflate a naturally-quiet symbol with a naturally-loud one).

  C) declining_compression_atr30_lag30: current causal 30m ATR proxy <
     the SAME measure evaluated ~30 minutes earlier (via `_value_at_
     offset`, a same-day causal lookback over a precomputed array), AND
     both values are below the GLOBAL median (as a fraction of price) --
     a genuine "compression is DEEPENING" signal (a declining trend),
     not merely "compression exists right now".

DIRECTION CONVENTION (documented per the brief -- compression itself has
no direction):
  - PRIMARY metric (volatility-effect, UNSIGNED): does compression
    predict an expanded absolute range LATER? Implemented via approach
    (ii) from the brief: `compute_volatility_effect` below computes its
    own simple absolute-forward-range statistic directly from raw bars
    -- (max(high) - min(low)) over each horizon window (bounded by
    session close, via `research_stats.forward_return_horizons`'s own
    favorable_excursion_high / adverse_excursion_low outputs, which
    already are exactly max(high)/min(low) over that bounded window,
    causal and never crossing session close), as a % of entry_price --
    for BOTH the deduplicated events AND their matched controls (the
    SAME matched-control population `run_family_definition` builds
    internally, reconstructed here via the same `sample_control_
    candidates` + `matched_control_sample` + `family_runner.
    build_control_events_from_pairs` calls, same match_keys, same
    seed). This was chosen over approach (i) (nominal-direction +
    abs() of forward_return_pct) because computing abs() correctly
    per matched PAIR (before differencing, not after averaging --
    abs(mean(diff)) != mean(diff of abs values)) would have required
    reaching into `family_runner.run_family_definition`'s internal
    per-pair merge anyway; recomputing the range statistic directly
    from bars is simpler, self-contained, and unambiguous. This choice
    is applied CONSISTENTLY across all three definitions.
    VOLATILITY_EFFECT_PRESENT iff, at the primary horizon (60m): the
    matched-control excess (event abs-range% minus paired-control
    abs-range%) is POSITIVE (events show MORE absolute movement than
    controls -- the hypothesis-aligned direction), its magnitude in bps
    is >= ROUND_TRIP_FRICTION_BPS (economically meaningful, same
    friction convention as the rest of Task 67A), AND its clustered
    (by symbol) bootstrap 95% CI excludes zero on the positive side
    (ci_low > 0 and ci_high > 0). Otherwise VOLATILITY_EFFECT_NOT_
    OBSERVED. See `_volatility_effect_flag` below.
  - SECONDARY metric (directional edge, SIGNED): the weak directional
    signal is the SIGN of `causal_trailing_return` over a trailing 15m
    window ending at the compressed bar (the most recent short-term
    drift direction observed AS OF the compressed bar -- not any
    forward-looking information). That sign is set as the event's
    `direction` and run through the STANDARD `run_family_definition`
    pipeline exactly as Families 1-3 do, giving the usual events.csv /
    horizon_metrics.csv / matched-control / bootstrap / verdict
    machinery "for free". DIRECTIONAL_EDGE_PRESENT iff, at the primary
    horizon: the SIGNED matched-control excess is POSITIVE (the weak
    recent-drift direction continues), its magnitude in bps is >=
    ROUND_TRIP_FRICTION_BPS, and its clustered bootstrap 95% CI
    excludes zero on the positive side. Otherwise DIRECTIONAL_EDGE_
    NOT_OBSERVED. See `_directional_edge_flag` below. This rule is
    deliberately the SAME shape as the volatility-effect rule above
    (positive excess, >= friction bps, CI excludes zero on the positive
    side) just applied to the signed rather than unsigned metric, for
    consistency.
  - Both flags are reported ADDITIONALLY to (not instead of) the
    standard PHENOMENON_PRESENT / WEAK_SIGNAL / PHENOMENON_NOT_OBSERVED
    / INSUFFICIENT_DATA verdict that `determine_verdict` produces for
    the SECONDARY (directional) analysis. It is an explicitly EXPECTED,
    useful possible outcome (per the brief) that a definition shows
    VOLATILITY_EFFECT_PRESENT while DIRECTIONAL_EDGE_NOT_OBSERVED --
    that is not treated as a failure anywhere in this script or in
    summary.md.
  - The SAME deduplicated event set (same compression condition, same
    dedup) is used for BOTH the primary and secondary analyses, for a
    direct, apples-to-apples comparison; events for which the weak
    directional signal is exactly zero (causal_trailing_return == 0,
    vanishingly rare on real float prices) are dropped from the
    candidate set entirely, matching Family 3's convention, so that
    every retained event has a well-defined `direction`.
"""
from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pandas as pd

from research.task67a_lib.data_guard import DataRole, get_stage1_guard
from research.task67a_lib.family_runner import build_control_events_from_pairs, run_family_definition
from research.task67a_lib.research_stats import (
    DEFAULT_SEED,
    bootstrap_ci_clustered,
    forward_return_horizons,
    matched_control_sample,
)
from research.task67a_lib.screening_framework import (
    ONE_WAY_FRICTION_BPS,
    POST_OPENING_RANGE_UTC_HOUR,
    ROUND_TRIP_FRICTION_BPS,
    add_bar_features,
    causal_atr_proxy,
    causal_trailing_return,
    classify_economic_magnitude,
    sample_control_candidates,
    session_close_timestamp_utc,
)

ROOT = Path(__file__).resolve().parents[2]
OUT_DIR = ROOT / "results/task67a_phenomenon_discovery/family_05_compression_expansion"
FAMILY_ID = "family_05_compression_expansion"
FAMILY_SEED_OFFSET = 500  # DEFAULT_SEED + this, then +1/+2/+3 per definition (100/200/300/600 already used by families 1/2/3/6)
DIR_WINDOW_MINUTES = 15  # weak directional signal window, uniform across all 3 definitions
PRIMARY_HORIZON_MINUTES = 60  # matches family_runner's own default


# ---------------------------------------------------------------------
# Generic causal helpers (own copies -- family scripts are self-contained
# by convention here; do not import from task67a_family03_range_expansion.py)
# ---------------------------------------------------------------------

def _min_lead_filter(bars_feat: pd.DataFrame, min_lead_minutes: float = 15.0) -> np.ndarray:
    close_ts = bars_feat["trading_day"] + pd.Timedelta(hours=20)
    return ((close_ts - bars_feat["timestamp"]) >= pd.Timedelta(minutes=min_lead_minutes)).to_numpy()


def _post_opening_range_filter(bars_feat: pd.DataFrame) -> np.ndarray:
    """True where the bar is at/after 14:00 UTC (30 minutes after the
    13:30 UTC RTH open) -- excludes the first-30-minutes-of-RTH opening-
    range window per the brief (ORPB territory, out of scope here). Uses
    `screening_framework.POST_OPENING_RANGE_UTC_HOUR` directly rather
    than redefining the cutoff."""
    t = pd.to_datetime(bars_feat["timestamp"])
    minutes_of_day = t.dt.hour * 60 + t.dt.minute
    return (minutes_of_day >= POST_OPENING_RANGE_UTC_HOUR * 60).to_numpy()


def _value_at_offset(
    bars_feat: pd.DataFrame, values: np.ndarray, offset_minutes: float,
    *, symbol_col: str = "symbol", time_col: str = "timestamp", day_col: str = "trading_day",
) -> np.ndarray:
    """Generic causal same-day lookback over an ARBITRARY precomputed
    array (row-aligned with `bars_feat`): for each bar t, returns
    `values` at the most recent same-day bar at or before
    (t - offset_minutes); NaN if no such bar exists yet. Same algorithm
    as `screening_framework.causal_price_at_offset` (per-symbol
    searchsorted, same-day-only), generalized because this family needs
    to look up a PRECOMPUTED TRAILING-ATR VALUE at a past offset, not a
    price -- own copy, adapted from Family 3's helper of the same shape
    (not imported; family scripts are self-contained by convention)."""
    n = len(bars_feat)
    out = np.full(n, np.nan, dtype=float)
    times = pd.to_datetime(bars_feat[time_col])
    if getattr(times.dt, "tz", None) is not None:
        times = times.dt.tz_convert("UTC").dt.tz_localize(None)
    times_ns = times.to_numpy(dtype="datetime64[ns]")
    days = bars_feat[day_col].to_numpy()
    values = np.asarray(values, dtype=float)
    target_times = times_ns - np.timedelta64(int(round(offset_minutes * 60)), "s")

    for symbol, idx in bars_feat.groupby(symbol_col, sort=False).indices.items():
        idx = np.asarray(idx)
        sym_times = times_ns[idx]
        sym_days = days[idx]
        sym_values = values[idx]
        sym_targets = target_times[idx]
        pos = np.searchsorted(sym_times, sym_targets, side="right") - 1
        valid = pos >= 0
        pos_clipped = np.clip(pos, 0, len(idx) - 1)
        same_day = np.zeros(len(idx), dtype=bool)
        same_day[valid] = sym_days[pos_clipped[valid]] == sym_days[valid]
        ok = valid & same_day
        result = np.full(len(idx), np.nan, dtype=float)
        result[ok] = sym_values[pos_clipped[ok]]
        out[idx] = result
    return out


def _global_percentile_cutoff(
    bars_feat: pd.DataFrame, values: np.ndarray, quantile: float,
    *, normalize_by_price: bool = True, min_valid: int = 30,
) -> float | None:
    """Computes a GLOBAL (whole-dataset) quantile cutpoint for `values`
    (optionally expressed as a fraction of `close`, same rationale as
    `add_bar_features`'s `vol_bucket` / Family 3's `_global_low_tertile_
    mask` -- global cutpoints so a bucket means the same thing across
    symbols/days), generalized to an arbitrary `quantile` (1/3 for a
    bottom-tertile cutoff, 0.5 for a median) rather than hardcoding
    tertiles only. Returns None (caller should then produce an
    all-False mask) if fewer than `min_valid` finite values exist."""
    values = np.asarray(values, dtype=float)
    if normalize_by_price:
        price = bars_feat["close"].to_numpy(dtype=float)
        with np.errstate(divide="ignore", invalid="ignore"):
            ref = values / price
    else:
        ref = values
    valid = ref[~np.isnan(ref)]
    if len(valid) < min_valid:
        return None
    return float(np.quantile(valid, quantile))


def _below_cutoff_mask(
    bars_feat: pd.DataFrame, values: np.ndarray, cutoff: float | None,
    *, normalize_by_price: bool = True,
) -> np.ndarray:
    """True where `values` (same optional price-normalization as
    `_global_percentile_cutoff`) is <= `cutoff`. All-False if `cutoff`
    is None (insufficient global data to have established a cutoff) or
    where `values` itself is NaN (same-day warmup)."""
    if cutoff is None:
        return np.zeros(len(bars_feat), dtype=bool)
    values = np.asarray(values, dtype=float)
    if normalize_by_price:
        price = bars_feat["close"].to_numpy(dtype=float)
        with np.errstate(divide="ignore", invalid="ignore"):
            ref = values / price
    else:
        ref = values
    mask = np.zeros(len(bars_feat), dtype=bool)
    valid = ~np.isnan(ref)
    mask[valid] = ref[valid] <= cutoff
    return mask


def _persistently_compressed_mask(
    bars_feat: pd.DataFrame, compressed_now: np.ndarray, persist_minutes: float,
    *, symbol_col: str = "symbol", time_col: str = "timestamp", day_col: str = "trading_day",
) -> np.ndarray:
    """True at bar t iff `compressed_now` has been True at EVERY same-day
    bar in the trailing window (t - persist_minutes, t] (inclusive of t
    itself) -- a genuinely stronger "has been sitting in compression"
    check than merely averaging a longer window, since a single non-
    compressed bar anywhere inside the window disqualifies it. Same
    per-symbol searchsorted + cumulative-sum-of-violations algorithm,
    and the SAME warmup convention, as `causal_atr_proxy`: False only
    when there is NO same-day bar at all before the current one (bar 0
    of a session); for bars with SOME but less than a full
    `persist_minutes` of same-day history, the check is applied over
    whatever same-day bars are available so far (a fully-compressed
    partial window still counts) -- requiring a literal, complete
    `persist_minutes` of elapsed duration would need extra bookkeeping
    none of the sibling causal_* helpers in this codebase do either.
    O(n) per symbol, not O(n * window)."""
    n = len(bars_feat)
    out = np.zeros(n, dtype=bool)
    times = pd.to_datetime(bars_feat[time_col])
    if getattr(times.dt, "tz", None) is not None:
        times = times.dt.tz_convert("UTC").dt.tz_localize(None)
    times_ns = times.to_numpy(dtype="datetime64[ns]")
    days = bars_feat[day_col].to_numpy()
    comp = np.asarray(compressed_now, dtype=bool)
    noncomp = (~comp).astype(float)

    for symbol, idx in bars_feat.groupby(symbol_col, sort=False).indices.items():
        idx = np.asarray(idx)
        sym_times = times_ns[idx]
        sym_days = days[idx]
        sym_noncomp = noncomp[idx]
        sym_comp = comp[idx]
        window_start = sym_times - np.timedelta64(int(round(persist_minutes * 60)), "s")
        lo = np.searchsorted(sym_times, window_start, side="left")
        cum = np.concatenate([[0.0], np.cumsum(sym_noncomp)])
        result = np.zeros(len(idx), dtype=bool)
        for i in range(len(idx)):
            if lo[i] >= i:
                continue  # insufficient same-day warmup for a full persist window
            if sym_days[lo[i]] != sym_days[i]:
                continue  # window would reach into prior session -> invalid
            if not sym_comp[i]:
                continue
            count_noncompressed = cum[i + 1] - cum[lo[i]]
            result[i] = count_noncompressed == 0
        out[idx] = result
    return out


def _causal_trailing_hl_range(
    bars_feat: pd.DataFrame, window_minutes: float,
    *, symbol_col: str = "symbol", time_col: str = "timestamp",
    high_col: str = "high", low_col: str = "low", day_col: str = "trading_day",
) -> np.ndarray:
    """Causal trailing max(high) - min(low) over `window_minutes`, ending
    at each bar t, restricted to the SAME (symbol, trading_day) group --
    genuine rolling intrabar range (not the per-bar-range MEAN that
    `causal_atr_proxy` computes), used by definition B for "how wide has
    price actually traveled recently". NaN until `window_minutes` of
    same-day history has elapsed since that day's first bar (own warmup
    convention, computed explicitly here since pandas' time-based
    `.rolling()` returns a value from `min_periods=1` on, not NaN during
    genuine warmup). Grouped by (symbol, trading_day) rather than symbol
    alone so the trailing window can never reach across the overnight
    gap into a prior session, regardless of window size."""
    out = pd.Series(np.nan, index=bars_feat.index, dtype=float)
    first_bar_time = bars_feat.groupby([symbol_col, day_col])[time_col].transform("min")
    elapsed = pd.to_datetime(bars_feat[time_col]) - pd.to_datetime(first_bar_time)
    enough_history = (elapsed >= pd.Timedelta(minutes=window_minutes)).to_numpy()

    for _, g in bars_feat.groupby([symbol_col, day_col], sort=False):
        g_sorted = g.sort_values(time_col)
        roll_high = g_sorted.rolling(f"{window_minutes}min", on=time_col, min_periods=1)[high_col].max()
        roll_low = g_sorted.rolling(f"{window_minutes}min", on=time_col, min_periods=1)[low_col].min()
        out.loc[g_sorted.index] = (roll_high - roll_low).to_numpy()

    result = out.to_numpy(dtype=float).copy()
    result[~enough_history] = np.nan
    return result


def _events_from_mask(bars_feat: pd.DataFrame, mask: np.ndarray, direction: np.ndarray) -> pd.DataFrame:
    cand = bars_feat.loc[mask, [
        "symbol", "timestamp", "close", "trailing_vol_60m", "time_of_day_bucket", "vol_bucket", "trading_day",
    ]].rename(columns={"close": "entry_price"}).copy()
    cand["direction"] = direction[mask]
    return cand


def _weak_direction_sign(bars_feat: pd.DataFrame, window_minutes: float = DIR_WINDOW_MINUTES) -> np.ndarray:
    """The SECONDARY, weak directional signal (see module docstring):
    sign of the trailing `window_minutes` return ending at the bar,
    causal, same-day only -- the most recent short-term drift direction
    observed AS OF the (possibly compressed) bar."""
    ret = causal_trailing_return(bars_feat, window_minutes)
    return np.sign(ret)


# ---------------------------------------------------------------------
# Definition A: persistent compression (bottom-tertile ATR held for the
# ENTIRE trailing 30 minutes, not just at the current instant)
# ---------------------------------------------------------------------

def definition_a_persistent_compression(
    bars_feat: pd.DataFrame, *, atr_window: float = 30, persist_minutes: float = 30,
) -> pd.DataFrame:
    atr = causal_atr_proxy(bars_feat, window_minutes=atr_window)
    cutoff = _global_percentile_cutoff(bars_feat, atr, quantile=1.0 / 3.0)
    compressed_now = _below_cutoff_mask(bars_feat, atr, cutoff)
    persistent = _persistently_compressed_mask(bars_feat, compressed_now, persist_minutes)
    sign = _weak_direction_sign(bars_feat)
    mask = persistent & (sign != 0) & _post_opening_range_filter(bars_feat) & _min_lead_filter(bars_feat)
    direction = np.where(sign > 0, 1, -1)
    return _events_from_mask(bars_feat, mask, direction)


# ---------------------------------------------------------------------
# Definition B: recent range narrow relative to the SAME symbol's own
# trailing longer-window typical range (per-symbol-normalized ratio)
# ---------------------------------------------------------------------

def definition_b_relative_narrow_range(
    bars_feat: pd.DataFrame, *, short_window: float = 15, long_window: float = 90,
) -> pd.DataFrame:
    short_range = _causal_trailing_hl_range(bars_feat, short_window)
    long_range = _causal_trailing_hl_range(bars_feat, long_window)
    with np.errstate(divide="ignore", invalid="ignore"):
        pace_short = short_range / short_window
        pace_long = long_range / long_window
        ratio = pace_short / pace_long
    cutoff = _global_percentile_cutoff(bars_feat, ratio, quantile=1.0 / 3.0, normalize_by_price=False)
    narrow = _below_cutoff_mask(bars_feat, ratio, cutoff, normalize_by_price=False)
    sign = _weak_direction_sign(bars_feat)
    mask = narrow & (sign != 0) & _post_opening_range_filter(bars_feat) & _min_lead_filter(bars_feat)
    direction = np.where(sign > 0, 1, -1)
    return _events_from_mask(bars_feat, mask, direction)


# ---------------------------------------------------------------------
# Definition C: declining/contracting trailing volatility TREND
# (compression is DEEPENING, not merely present)
# ---------------------------------------------------------------------

def definition_c_declining_compression(
    bars_feat: pd.DataFrame, *, atr_window: float = 30, lag_minutes: float = 30,
) -> pd.DataFrame:
    atr_now = causal_atr_proxy(bars_feat, window_minutes=atr_window)
    atr_prior = _value_at_offset(bars_feat, atr_now, offset_minutes=lag_minutes)
    median_cutoff = _global_percentile_cutoff(bars_feat, atr_now, quantile=0.5)
    now_below_median = _below_cutoff_mask(bars_feat, atr_now, median_cutoff)
    prior_below_median = _below_cutoff_mask(bars_feat, atr_prior, median_cutoff)
    declining = atr_now < atr_prior
    sign = _weak_direction_sign(bars_feat)
    mask = (
        declining & now_below_median & prior_below_median & (sign != 0)
        & _post_opening_range_filter(bars_feat) & _min_lead_filter(bars_feat)
    )
    direction = np.where(sign > 0, 1, -1)
    return _events_from_mask(bars_feat, mask, direction)


DEFINITIONS = [
    {
        "name": "persistent_compression_atr30_persist30",
        "builder": definition_a_persistent_compression,
        "dedup_group_keys": ["symbol"],
        "dedup_min_gap_minutes": 30,
        "description": (
            "Trailing 30m ATR proxy (bottom global tertile as a fraction of price) held CONTINUOUSLY for the "
            "entire trailing 30 minutes (every bar in the window individually below the tertile cutoff, not just "
            "the window average). No requirement that expansion has begun. Direction (secondary/weak signal) = "
            "sign of the 15m trailing return as of the compressed bar. Excludes first 30m of RTH."
        ),
    },
    {
        "name": "relative_narrow_range_15v90",
        "builder": definition_b_relative_narrow_range,
        "dedup_group_keys": ["symbol"],
        "dedup_min_gap_minutes": 30,
        "description": (
            "Current 15m rolling high-low range pace (range/15) divided by the SAME symbol's own trailing 90m "
            "high-low range pace (range/90) -- a per-symbol-normalized ratio -- in the bottom global tertile. "
            "Tests whether the recent window is narrow relative to what THIS symbol itself has typically been "
            "doing, not an absolute range threshold. Direction (secondary/weak signal) = sign of the 15m trailing "
            "return. Excludes first 30m of RTH."
        ),
    },
    {
        "name": "declining_compression_atr30_lag30",
        "builder": definition_c_declining_compression,
        "dedup_group_keys": ["symbol"],
        "dedup_min_gap_minutes": 30,
        "description": (
            "Current causal 30m ATR proxy < the same measure evaluated ~30 minutes earlier (same-day causal "
            "lookback), AND both values below the global median as a fraction of price -- compression is "
            "DEEPENING, not merely present. Direction (secondary/weak signal) = sign of the 15m trailing return. "
            "Excludes first 30m of RTH."
        ),
    },
]


# ---------------------------------------------------------------------
# PRIMARY analysis: unsigned volatility-effect (approach (ii) from the
# brief -- own absolute-forward-range statistic computed directly from
# bars, for both events and their matched controls)
# ---------------------------------------------------------------------

def _abs_range_metrics(bars: pd.DataFrame, events: pd.DataFrame, horizons_minutes) -> pd.DataFrame:
    """For each event, the UNSIGNED (max(high) - min(low)) / entry_price
    * 100 over each horizon window, bounded by that event's own trading
    day's RTH close -- reuses `research_stats.forward_return_horizons`'s
    own `favorable_excursion_high` / `adverse_excursion_low` (which are
    already exactly max(high)/min(low) over the causally-bounded window)
    rather than re-deriving the window logic. No direction involved."""
    rows: list[dict] = []
    bars_by_symbol = {sym: g.sort_values("timestamp") for sym, g in bars.groupby("symbol", sort=False)}
    for _, ev in events.iterrows():
        sym = ev["symbol"]
        sym_bars = bars_by_symbol.get(sym)
        if sym_bars is None or sym_bars.empty:
            continue
        entry_ts = pd.Timestamp(ev["timestamp"])
        entry_price = float(ev["entry_price"])
        close_ts = session_close_timestamp_utc(entry_ts)
        results = forward_return_horizons(
            sym_bars, entry_timestamp=entry_ts, entry_price=entry_price,
            horizons_minutes=list(horizons_minutes), session_close_timestamp=close_ts, time_col="timestamp",
        )
        for r in results:
            fh, al = r["favorable_excursion_high"], r["adverse_excursion_low"]
            abs_range_pct = ((fh - al) / entry_price * 100.0) if (fh is not None and al is not None) else None
            rows.append({
                "event_id": ev["event_id"], "symbol": sym, "timestamp": entry_ts,
                "horizon_label": r["horizon_label"], "horizon_minutes": r["horizon_minutes"],
                "bars_observed": r["bars_observed"], "abs_range_pct": abs_range_pct,
                "bounded_by_session_close": r["bounded_by_session_close"],
            })
    return pd.DataFrame(rows)


def compute_volatility_effect(
    bars: pd.DataFrame, bars_feat: pd.DataFrame, events: pd.DataFrame,
    *, horizons_minutes=(15, 30, 60, 120), primary_horizon_minutes: int = PRIMARY_HORIZON_MINUTES,
    seed: int = DEFAULT_SEED, control_stride_minutes: int = 20, control_exclusion_buffer_minutes: float = 60.0,
    control_warmup_minutes: float = 90.0, control_min_lead_minutes: float = 15.0,
    match_keys=("symbol", "time_of_day_bucket", "vol_bucket"), econ_friction_bps: float = ROUND_TRIP_FRICTION_BPS,
) -> dict:
    """Mirrors `family_runner.run_family_definition`'s matched-control
    machinery (same `sample_control_candidates` + `matched_control_
    sample` + `build_control_events_from_pairs` calls, same match_keys)
    but measures the UNSIGNED absolute-range statistic instead of the
    direction-signed forward return -- this is the PRIMARY, unsigned
    "does compression predict expanded absolute movement" test (see
    module docstring's DIRECTION CONVENTION section)."""
    if events.empty:
        return {
            "per_horizon": {}, "economic_classification": "INSUFFICIENT_DATA",
            "volatility_effect_flag": "VOLATILITY_EFFECT_NOT_OBSERVED",
            "abs_range_pct_median_max_horizon": None,
            "reason": "Zero deduplicated events -- volatility-effect analysis skipped.",
        }

    control_pool = sample_control_candidates(
        bars_feat, events, stride_minutes=control_stride_minutes,
        exclusion_buffer_minutes=control_exclusion_buffer_minutes,
        warmup_minutes=control_warmup_minutes, min_lead_minutes=control_min_lead_minutes, seed=seed,
    )
    events_idx = events.reset_index(drop=True).copy()
    events_idx["_pos"] = np.arange(len(events_idx))
    control_reset = control_pool.reset_index(drop=True).copy()
    control_reset["_pos"] = np.arange(len(control_reset))

    combined = pd.concat([
        events_idx[["symbol", "timestamp", "time_of_day_bucket", "vol_bucket"]].assign(_grp="EVENT", _pos=events_idx["_pos"]),
        control_reset[["symbol", "timestamp", "time_of_day_bucket", "vol_bucket"]].assign(_grp="CONTROL", _pos=control_reset["_pos"]),
    ], ignore_index=True)
    mc = matched_control_sample(
        combined, treatment_col="_grp", treatment_label="EVENT", control_label="CONTROL",
        match_keys=list(match_keys), time_col="timestamp", seed=seed,
    )
    pairs = mc["nearest_time_pairs"]
    control_events = build_control_events_from_pairs(pairs, events_idx, control_reset, combined)

    ev_abs = _abs_range_metrics(bars, events_idx, horizons_minutes)
    ctrl_abs = _abs_range_metrics(bars, control_events, horizons_minutes) if len(control_events) else pd.DataFrame()

    per_horizon: dict = {}
    for h in horizons_minutes:
        label = f"{h}m"
        ev_h = ev_abs[ev_abs["horizon_minutes"] == h]
        raw_mean = float(ev_h["abs_range_pct"].mean()) if len(ev_h) and ev_h["abs_range_pct"].notna().any() else None
        merged = pd.DataFrame()
        control_mean = None
        excess_mean = None
        boot = None
        if len(ctrl_abs) and len(control_events):
            paired_map = control_events.set_index("event_id")["paired_event_id"]
            ctrl_h = ctrl_abs[ctrl_abs["horizon_minutes"] == h].copy()
            ctrl_h["paired_event_id"] = ctrl_h["event_id"].map(paired_map)
            merged = ev_h.merge(ctrl_h, left_on="event_id", right_on="paired_event_id", suffixes=("_ev", "_ctrl"))
            merged = merged.dropna(subset=["abs_range_pct_ev", "abs_range_pct_ctrl"])
            if len(merged):
                diffs = (merged["abs_range_pct_ev"] - merged["abs_range_pct_ctrl"]).to_numpy(dtype=float)
                symbols_for_diff = merged["symbol_ev"].to_numpy()
                control_mean = float(ctrl_h["abs_range_pct"].mean()) if ctrl_h["abs_range_pct"].notna().any() else None
                excess_mean = float(np.mean(diffs))
                # Offset well clear of family_runner's own seed+h scheme (h in 15/30/60/120) to keep this
                # bootstrap's resamples independent of the secondary (signed) analysis's per-horizon bootstraps.
                boot = bootstrap_ci_clustered(diffs, symbols_for_diff, seed=seed + 10_000 + h)
        per_horizon[label] = {
            "horizon_minutes": h, "n_events": int(len(ev_h)), "n_matched_pairs": int(len(merged)),
            "raw_mean_abs_range_pct": raw_mean, "matched_control_mean_abs_range_pct": control_mean,
            "excess_mean_abs_range_pct": excess_mean,
            "excess_bootstrap_clustered": boot.as_dict() if boot is not None else None,
        }

    max_h = max(horizons_minutes)
    ev_max = ev_abs[ev_abs["horizon_minutes"] == max_h]
    abs_range_median_max_h = float(ev_max["abs_range_pct"].median()) if len(ev_max) and ev_max["abs_range_pct"].notna().any() else None
    excess_primary = per_horizon.get(f"{primary_horizon_minutes}m", {}).get("excess_mean_abs_range_pct")
    econ_class = classify_economic_magnitude(excess_primary, abs_range_median_max_h, round_trip_friction_bps=econ_friction_bps)

    flag = _volatility_effect_flag(per_horizon, primary_horizon_minutes, econ_friction_bps)
    return {
        "per_horizon": per_horizon, "economic_classification": econ_class,
        "volatility_effect_flag": flag, "abs_range_pct_median_max_horizon": abs_range_median_max_h,
        "n_events": int(len(events_idx)), "n_control_pairs_primary_horizon": per_horizon.get(f"{primary_horizon_minutes}m", {}).get("n_matched_pairs"),
    }


def _positive_excess_ci_excludes_zero(excess: float | None, boot: dict | None, friction_bps: float) -> bool:
    if excess is None or boot is None or boot.get("insufficient_n") or boot.get("ci_low") is None:
        return False
    lo, hi = boot["ci_low"], boot["ci_high"]
    ci_positive = lo is not None and hi is not None and lo > 0 and hi > 0
    magnitude_ok = abs(excess) * 100.0 >= friction_bps
    return bool(excess > 0 and magnitude_ok and ci_positive)


def _volatility_effect_flag(per_horizon: dict, primary_horizon_minutes: int, friction_bps: float) -> str:
    ph = per_horizon.get(f"{primary_horizon_minutes}m", {})
    excess = ph.get("excess_mean_abs_range_pct")
    boot = ph.get("excess_bootstrap_clustered")
    return "VOLATILITY_EFFECT_PRESENT" if _positive_excess_ci_excludes_zero(excess, boot, friction_bps) else "VOLATILITY_EFFECT_NOT_OBSERVED"


def _directional_edge_flag(secondary_result: dict, primary_horizon_minutes: int, friction_bps: float) -> str:
    ph = secondary_result.get("per_horizon", {}).get(f"{primary_horizon_minutes}m", {})
    excess = ph.get("excess_mean_pct")
    boot = ph.get("excess_bootstrap_clustered")
    return "DIRECTIONAL_EDGE_PRESENT" if _positive_excess_ci_excludes_zero(excess, boot, friction_bps) else "DIRECTIONAL_EDGE_NOT_OBSERVED"


def main() -> None:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    guard = get_stage1_guard()
    bars = guard.load_ohlcv(DataRole.DEVELOPMENT, symbols=None)
    bars_feat = add_bar_features(bars)

    all_events, all_horizon_metrics, all_control_metrics, all_mfe_mae = [], [], [], []
    definitions_summary = {}
    definitions_json = []

    for i, spec in enumerate(DEFINITIONS):
        name = spec["name"]
        cand = spec["builder"](bars_feat)
        seed = DEFAULT_SEED + FAMILY_SEED_OFFSET + i

        secondary = run_family_definition(
            bars=bars, bars_feat=bars_feat, candidate_events=cand,
            definition_name=name, dedup_group_keys=spec["dedup_group_keys"],
            dedup_min_gap_minutes=spec["dedup_min_gap_minutes"], seed=seed,
            primary_horizon_minutes=PRIMARY_HORIZON_MINUTES,
        )
        volatility = compute_volatility_effect(
            bars, bars_feat, secondary["events_df"], seed=seed, primary_horizon_minutes=PRIMARY_HORIZON_MINUTES,
        )
        directional_flag = _directional_edge_flag(secondary, PRIMARY_HORIZON_MINUTES, ROUND_TRIP_FRICTION_BPS)

        events = secondary["events_df"].copy()
        if len(events):
            events["definition"] = name
            all_events.append(events)
        hm = secondary["horizon_metrics_df"].copy()
        if len(hm):
            hm["definition"] = name
            all_horizon_metrics.append(hm)
        cm = secondary["control_metrics_df"].copy()
        if len(cm):
            cm["definition"] = name
            all_control_metrics.append(cm)
        mm = secondary["mfe_mae_df"].copy()
        if len(mm):
            mm["definition"] = name
            all_mfe_mae.append(mm)

        definitions_summary[name] = {
            "description": spec["description"],
            "dedup_group_keys": spec["dedup_group_keys"],
            "dedup_min_gap_minutes": spec["dedup_min_gap_minutes"],
            "seed": seed,
            "n_raw_events": secondary["n_raw_events"],
            "n_dedup_events": secondary["n_dedup_events"],
            "n_symbols": secondary["n_symbols"],
            "n_days": secondary["n_days"],
            "per_horizon": secondary["per_horizon"],
            "mfe_pct_median": secondary.get("mfe_pct_median"),
            "mae_pct_median": secondary.get("mae_pct_median"),
            "concentration": secondary["concentration"],
            "effect_surface_instability": secondary["effect_surface_instability"],
            "effect_surface_instability_reason": secondary["effect_surface_instability_reason"],
            "economic_classification": secondary["economic_classification"],
            "data_sufficiency": secondary["data_sufficiency"],
            "verdict": secondary["verdict"],
            "verdict_reasoning": secondary["verdict_reasoning"],
            "verdict_inputs": secondary["verdict_inputs"],
            "main_weakness": secondary["main_weakness"],
            "directional_edge_flag": directional_flag,
            "volatility_effect": {
                "per_horizon": volatility["per_horizon"],
                "economic_classification": volatility["economic_classification"],
                "abs_range_pct_median_max_horizon": volatility["abs_range_pct_median_max_horizon"],
                "flag": volatility["volatility_effect_flag"],
            },
        }
        definitions_json.append({
            "name": name, "description": spec["description"], "dedup_group_keys": spec["dedup_group_keys"],
            "dedup_min_gap_minutes": spec["dedup_min_gap_minutes"], "seed": seed,
        })
        print(
            f"[family05] {name}: raw={secondary['n_raw_events']} dedup={secondary['n_dedup_events']} "
            f"verdict={secondary['verdict']} directional={directional_flag} volatility={volatility['volatility_effect_flag']}"
        )

    events_df = pd.concat(all_events, ignore_index=True) if all_events else pd.DataFrame()
    horizon_df = pd.concat(all_horizon_metrics, ignore_index=True) if all_horizon_metrics else pd.DataFrame()
    control_df = pd.concat(all_control_metrics, ignore_index=True) if all_control_metrics else pd.DataFrame()
    mfe_mae_df = pd.concat(all_mfe_mae, ignore_index=True) if all_mfe_mae else pd.DataFrame()

    events_df.to_csv(OUT_DIR / "events.csv", index=False)
    horizon_df.to_csv(OUT_DIR / "horizon_metrics.csv", index=False)
    control_df.to_csv(OUT_DIR / "matched_control_metrics.csv", index=False)
    mfe_mae_df.to_csv(OUT_DIR / "mfe_mae.csv", index=False)

    (OUT_DIR / "definitions.json").write_text(json.dumps(definitions_json, indent=2), encoding="utf-8")
    (OUT_DIR / "concentration.json").write_text(
        json.dumps({name: d["concentration"] for name, d in definitions_summary.items()}, indent=2, default=str),
        encoding="utf-8",
    )

    verdicts = [d["verdict"] for d in definitions_summary.values()]
    rollup_text = (
        f"{sum(v == 'PHENOMENON_PRESENT' for v in verdicts)}/3 PHENOMENON_PRESENT, "
        f"{sum(v == 'WEAK_SIGNAL' for v in verdicts)}/3 WEAK_SIGNAL, "
        f"{sum(v == 'PHENOMENON_NOT_OBSERVED' for v in verdicts)}/3 PHENOMENON_NOT_OBSERVED, "
        f"{sum(v == 'INSUFFICIENT_DATA' for v in verdicts)}/3 INSUFFICIENT_DATA -- "
        "definitions are NOT averaged into one number; each is reported independently, per the brief. "
        "Standard verdicts are computed on the SECONDARY (signed/directional) analysis; the volatility-effect "
        "(primary/unsigned) and directional-edge flags are reported separately per definition below."
    )
    vol_flags = [d["volatility_effect"]["flag"] for d in definitions_summary.values()]
    dir_flags = [d["directional_edge_flag"] for d in definitions_summary.values()]
    flag_rollup_text = (
        f"Volatility-effect: {sum(f == 'VOLATILITY_EFFECT_PRESENT' for f in vol_flags)}/3 PRESENT, "
        f"{sum(f == 'VOLATILITY_EFFECT_NOT_OBSERVED' for f in vol_flags)}/3 NOT_OBSERVED. "
        f"Directional-edge: {sum(f == 'DIRECTIONAL_EDGE_PRESENT' for f in dir_flags)}/3 PRESENT, "
        f"{sum(f == 'DIRECTIONAL_EDGE_NOT_OBSERVED' for f in dir_flags)}/3 NOT_OBSERVED."
    )

    summary = {
        "family": FAMILY_ID,
        "question": (
            "Does sitting in a compressed volatility state predict LATER unusually large movement and/or "
            "directional persistence, evaluated at horizons AFTER the compressed bar -- with NO requirement "
            "that expansion has already begun? (later-session/general-session only; first 30m of RTH explicitly "
            "excluded, ORPB territory)."
        ),
        "data": {
            "role": "DEVELOPMENT", "n_symbols_universe": 35, "n_trading_days": 62,
            "date_range": ["2026-05-15", "2026-08-14"],
        },
        "friction_assumption_bps": {"one_way": ONE_WAY_FRICTION_BPS, "round_trip": ROUND_TRIP_FRICTION_BPS},
        "primary_horizon_minutes": PRIMARY_HORIZON_MINUTES,
        "direction_convention": (
            "PRIMARY (volatility-effect, unsigned): approach (ii) -- own absolute-forward-range statistic "
            "(max(high)-min(low) over each horizon window as % of entry_price) computed directly from bars for "
            "both events and matched controls; VOLATILITY_EFFECT_PRESENT iff the matched-control excess at the "
            "60m primary horizon is positive, its magnitude >= round-trip friction bps, and its clustered "
            "(by-symbol) bootstrap 95% CI excludes zero on the positive side. SECONDARY (directional edge, "
            "signed): weak directional signal = sign of the 15m trailing return ending at the compressed bar, "
            "run through the standard run_family_definition pipeline; DIRECTIONAL_EDGE_PRESENT uses the same "
            "positive/magnitude/CI rule applied to the signed excess. Both flags are additional to, not a "
            "replacement for, the standard PHENOMENON_PRESENT/WEAK_SIGNAL/PHENOMENON_NOT_OBSERVED/"
            "INSUFFICIENT_DATA verdict (computed on the secondary/signed analysis). VOLATILITY_EFFECT_PRESENT "
            "with DIRECTIONAL_EDGE_NOT_OBSERVED is an explicitly expected, valid possible outcome, not a failure."
        ),
        "definitions": definitions_summary,
        "family_rollup": rollup_text,
        "flag_rollup": flag_rollup_text,
        "total_raw_events": int(sum(d["n_raw_events"] for d in definitions_summary.values())),
        "total_dedup_events": int(sum(d["n_dedup_events"] for d in definitions_summary.values())),
    }
    (OUT_DIR / "summary.json").write_text(json.dumps(summary, indent=2, default=str), encoding="utf-8")

    md_lines = [
        "# Family 5 -- Compression -> Expansion (Precondition) -- Stage 1 Screening Summary",
        "",
        "Question: does sitting in a compressed volatility state predict LATER unusually large movement and/or "
        "directional persistence, evaluated at horizons AFTER the compressed bar -- with NO requirement that "
        "expansion has already begun? (later-session/general-session only; first 30m of RTH explicitly excluded "
        "-- ORPB territory, out of scope.)",
        "",
        f"Data: DEVELOPMENT role, 35 symbols, 62 trading days (2026-05-15..2026-08-14). "
        f"Friction assumption: {ONE_WAY_FRICTION_BPS}bps one-way / {ROUND_TRIP_FRICTION_BPS}bps round-trip. "
        f"Primary horizon: {PRIMARY_HORIZON_MINUTES}m.",
        "",
        "**Direction convention:** PRIMARY analysis is UNSIGNED (does compression predict expanded absolute "
        "movement?) -- own max(high)-min(low)-over-horizon statistic vs. matched controls. SECONDARY analysis is "
        "SIGNED (does a weak recent-drift-direction signal, sign of the 15m trailing return as of the compressed "
        "bar, predict the signed forward return?) -- run through the standard pipeline. Both are reported; "
        "VOLATILITY_EFFECT_PRESENT with DIRECTIONAL_EDGE_NOT_OBSERVED is an explicitly expected, valid outcome "
        "(compression can expand the range of outcomes without making the sign predictable), not a failure.",
        "",
        f"**Family rollup (standard verdict, secondary/signed analysis):** {rollup_text}",
        "",
        f"**Flag rollup:** {flag_rollup_text}",
        "",
    ]
    for name, d in definitions_summary.items():
        md_lines += [
            f"## Definition: `{name}`",
            "",
            d["description"],
            "",
            f"- Dedup: group_keys={d['dedup_group_keys']}, min_gap_minutes={d['dedup_min_gap_minutes']}",
            f"- Raw events: {d['n_raw_events']} -> Deduplicated events: {d['n_dedup_events']} "
            f"(symbols={d['n_symbols']}, days={d['n_days']})",
            f"- SECONDARY (signed) economic classification: **{d['economic_classification']}**",
            f"- Data sufficiency: **{d['data_sufficiency']}**",
            f"- Effect surface instability flagged: {d['effect_surface_instability']} "
            f"({d['effect_surface_instability_reason']})",
            f"- MFE median (%, at max horizon): {d['mfe_pct_median']}; MAE median (%): {d['mae_pct_median']}",
            "",
            "### Secondary (signed, directional) per-horizon results",
            "",
            "| Horizon | n events | n matched pairs | raw mean % | matched control mean % | excess mean % | excess 95% CI | positive freq |",
            "|---|---|---|---|---|---|---|---|",
        ]
        for h_label, h in d["per_horizon"].items():
            boot = h["excess_bootstrap_clustered"]
            ci = f"[{boot['ci_low']:.4f}, {boot['ci_high']:.4f}]" if boot and not boot.get("insufficient_n") and boot.get("ci_low") is not None else "n/a"
            md_lines.append(
                f"| {h_label} | {h['n_events']} | {h['n_matched_pairs']} | "
                f"{h['raw_mean_pct'] if h['raw_mean_pct'] is None else round(h['raw_mean_pct'], 4)} | "
                f"{h['matched_control_mean_pct'] if h['matched_control_mean_pct'] is None else round(h['matched_control_mean_pct'], 4)} | "
                f"{h['excess_mean_pct'] if h['excess_mean_pct'] is None else round(h['excess_mean_pct'], 4)} | "
                f"{ci} | "
                f"{h['positive_return_freq'] if h['positive_return_freq'] is None else round(h['positive_return_freq'], 3)} |"
            )
        vol = d["volatility_effect"]
        md_lines += [
            "",
            f"### Primary (unsigned, volatility-effect) per-horizon results -- economic classification: "
            f"**{vol['economic_classification']}**; abs-range median at max horizon: "
            f"{vol['abs_range_pct_median_max_horizon']}",
            "",
            "| Horizon | n events | n matched pairs | raw mean abs-range % | matched control mean abs-range % | excess mean abs-range % | excess 95% CI |",
            "|---|---|---|---|---|---|---|",
        ]
        for h_label, h in vol["per_horizon"].items():
            boot = h["excess_bootstrap_clustered"]
            ci = f"[{boot['ci_low']:.4f}, {boot['ci_high']:.4f}]" if boot and not boot.get("insufficient_n") and boot.get("ci_low") is not None else "n/a"
            md_lines.append(
                f"| {h_label} | {h['n_events']} | {h['n_matched_pairs']} | "
                f"{h['raw_mean_abs_range_pct'] if h['raw_mean_abs_range_pct'] is None else round(h['raw_mean_abs_range_pct'], 4)} | "
                f"{h['matched_control_mean_abs_range_pct'] if h['matched_control_mean_abs_range_pct'] is None else round(h['matched_control_mean_abs_range_pct'], 4)} | "
                f"{h['excess_mean_abs_range_pct'] if h['excess_mean_abs_range_pct'] is None else round(h['excess_mean_abs_range_pct'], 4)} | "
                f"{ci} |"
            )
        md_lines += [
            "",
            f"### VERDICT (standard taxonomy, secondary/signed analysis): **{d['verdict']}**",
            "",
            d["verdict_reasoning"],
            "",
            f"Main weakness: {d['main_weakness']}",
            "",
            f"### VOLATILITY_EFFECT flag: **{vol['flag']}**  |  DIRECTIONAL_EDGE flag: **{d['directional_edge_flag']}**",
            "",
        ]
    (OUT_DIR / "summary.md").write_text("\n".join(md_lines), encoding="utf-8")
    print(f"[family05] wrote outputs to {OUT_DIR}")


if __name__ == "__main__":
    main()
