"""
research/task67a_lib/screening_framework.py
---------------------------------------------
Shared, FAMILY-AGNOSTIC event-screening glue for Task 67A Stage 1 Phase A
(families 1-3: multi-hour trend persistence, structural pullback,
volatility/range expansion). Builds on research_stats.py (which is purely
statistical/generic) by adding the market-data-shaped plumbing every
family script needs: causal trailing-window features computed off raw
OHLCV bars, RTH session-close bounding, time-of-day/volatility bucketing
for matched-control stratification, and the horizon/MFE-MAE application
loop over an event table.

Nothing here is specific to any one family's event DEFINITION -- each
family script (research/scripts/task67a_family0{1,2,3}_*.py) owns its own
condition logic and calls into this module for the shared mechanics.

Causality discipline (see tests/test_task67a_screening_framework.py):
  - every "causal_*" function here computes a value for bar t using ONLY
    bars at or before t (and, where documented, restricted to the SAME
    trading day as t -- this repo's 1-minute bars span extended hours
    within one UTC calendar date per session, roughly 08:00-23:59 UTC, so
    "same trading day" == "same bars['timestamp'].dt.date"). A trailing
    window is never silently satisfied by reaching back across the
    overnight gap into the PRIOR session -- that would misrepresent an
    8+ hour-old price as "60 minutes ago". Where a same-day reference bar
    does not exist yet (e.g. near session open), the result is NaN, not a
    leaked/wrapped value.
  - forward-looking functions (compute_event_horizon_and_mfe_mae) only
    ever look at bars AT OR AFTER an event's already-frozen timestamp,
    and never past that day's RTH close (see RTH_CLOSE_UTC below),
    matching research_stats.forward_return_horizons's own
    session_close_timestamp bounding.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Sequence

import numpy as np
import pandas as pd

from research.task67a_lib.research_stats import compute_mfe_mae, forward_return_horizons


def _naive_utc_ns(series: pd.Series) -> np.ndarray:
    """Converts a (possibly tz-aware) datetime-like Series to a
    `datetime64[ns]` numpy array of naive UTC instants. `Series.to_numpy()`
    on a tz-aware datetime column returns an `object` array of Timestamps
    (numpy has no tz-aware datetime64 dtype), which breaks numpy
    arithmetic/searchsorted against `timedelta64` -- every function here
    that does vectorized time arithmetic goes through this helper first."""
    dt = pd.to_datetime(series)
    if getattr(dt.dt, "tz", None) is not None:
        dt = dt.dt.tz_convert("UTC").dt.tz_localize(None)
    return dt.to_numpy(dtype="datetime64[ns]")

# ---------------------------------------------------------------------
# Session constants
# ---------------------------------------------------------------------

#: US equity RTH close, in UTC, for the EDT-offset (UTC-4) window this
#: dataset was downloaded in (2026-05-15..2026-08-14 is entirely within
#: US Eastern Daylight Time). 16:00 ET + 4h = 20:00 UTC.
RTH_CLOSE_UTC_HOUR = 20

#: US equity RTH open, in UTC, same DST assumption. 9:30 ET + 4h = 13:30 UTC.
RTH_OPEN_UTC_HOUR = 13
RTH_OPEN_UTC_MINUTE = 30

#: Families 1-3 must exclude the first 30 minutes of RTH (that is
#: ORPB-style opening-range territory, out of scope here per the brief).
#: 13:30 + 30m = 14:00 UTC.
POST_OPENING_RANGE_UTC_HOUR = 14


def session_close_timestamp_utc(ts: pd.Timestamp) -> pd.Timestamp:
    """Returns the RTH-close (20:00:00 UTC) timestamp for `ts`'s own UTC
    calendar date. `ts` must be UTC tz-aware. This dataset's sessions
    never cross a UTC midnight boundary (extended hours run ~08:00 to
    23:59 UTC within one date), so "ts's UTC date" and "ts's trading day"
    are the same thing here -- see module docstring."""
    ts = pd.Timestamp(ts)
    day = ts.normalize()
    return day + pd.Timedelta(hours=RTH_CLOSE_UTC_HOUR)


def add_trading_day(bars: pd.DataFrame, time_col: str = "timestamp") -> pd.DataFrame:
    """Returns a COPY of `bars` with a `trading_day` column (the UTC
    calendar date of each bar, as a `datetime64[ns]` normalized
    timestamp -- comparable/groupable, unlike a raw `date` object). See
    module docstring for why UTC-date == trading-day for this dataset."""
    out = bars.copy()
    out["trading_day"] = pd.to_datetime(out[time_col]).dt.normalize()
    return out


# ---------------------------------------------------------------------
# Causal trailing-window primitives
# ---------------------------------------------------------------------

def causal_price_at_offset(
    bars: pd.DataFrame,
    offset_minutes: float,
    *,
    symbol_col: str = "symbol",
    time_col: str = "timestamp",
    price_col: str = "close",
    day_col: str = "trading_day",
) -> np.ndarray:
    """For every row t in `bars`, returns the price of the most recent bar
    at or before (t - offset_minutes), restricted to bars sharing t's
    `day_col` value (never reaches into a prior session) and t's
    `symbol_col` value. NaN where no such same-day bar exists yet
    (typically the first `offset_minutes` of each session).

    `offset_minutes=0` returns `bars[price_col]` itself (the reference
    bar IS t). Vectorized via `searchsorted` per symbol -- O(n log n)
    per symbol, not a Python-level loop over rows.

    Requires `bars` to already have a `day_col` column -- call
    `add_trading_day` first if it doesn't.
    """
    if day_col not in bars.columns:
        raise ValueError(f"bars is missing {day_col!r}; call add_trading_day(bars) first.")
    n = len(bars)
    out = np.full(n, np.nan, dtype=float)
    times = pd.to_datetime(bars[time_col]).to_numpy()
    prices = bars[price_col].to_numpy(dtype=float)
    days = bars[day_col].to_numpy()
    target_times = times - np.timedelta64(int(round(offset_minutes * 60)), "s")

    for symbol, idx in bars.groupby(symbol_col, sort=False).indices.items():
        idx = np.asarray(idx)
        # idx is already in the group's row order; bars are assumed
        # globally sorted by [symbol, timestamp] (load_ohlcv_directory's
        # contract) so idx is time-ascending within the symbol already.
        sym_times = times[idx]
        sym_days = days[idx]
        sym_prices = prices[idx]
        sym_targets = target_times[idx]
        # position of the last bar with sym_times <= target, per row
        pos = np.searchsorted(sym_times, sym_targets, side="right") - 1
        valid = pos >= 0
        pos_clipped = np.clip(pos, 0, len(idx) - 1)
        same_day = np.zeros(len(idx), dtype=bool)
        same_day[valid] = sym_days[pos_clipped[valid]] == sym_days[valid]
        ok = valid & same_day
        result = np.full(len(idx), np.nan, dtype=float)
        result[ok] = sym_prices[pos_clipped[ok]]
        out[idx] = result

    return out


def causal_trailing_return(
    bars: pd.DataFrame,
    window_minutes: float,
    **kwargs,
) -> np.ndarray:
    """Trailing pct return over `window_minutes`, ending at each bar t:
    (price_t - price_{t-window}) / price_{t-window}, using
    `causal_price_at_offset` for the reference price (same-day only, NaN
    during warmup). `**kwargs` forwarded to `causal_price_at_offset`
    (symbol_col/time_col/price_col/day_col)."""
    price_col = kwargs.get("price_col", "close")
    ref = causal_price_at_offset(bars, window_minutes, **kwargs)
    now = bars[price_col].to_numpy(dtype=float)
    with np.errstate(divide="ignore", invalid="ignore"):
        ret = (now - ref) / ref
    return ret


def causal_atr_proxy(
    bars: pd.DataFrame,
    window_minutes: int = 30,
    *,
    symbol_col: str = "symbol",
    time_col: str = "timestamp",
    high_col: str = "high",
    low_col: str = "low",
    day_col: str = "trading_day",
) -> np.ndarray:
    """Simple causal volatility-scale proxy: mean per-bar (high-low)
    range over the trailing `window_minutes`, same-day only, time-based
    (not positional -- robust to bar-count gaps). Used as `risk_per_unit`
    for MFE/MAE R-multiples when a family has no more specific risk
    definition. NaN during same-day warmup."""
    if day_col not in bars.columns:
        raise ValueError(f"bars is missing {day_col!r}; call add_trading_day(bars) first.")
    n = len(bars)
    out = np.full(n, np.nan, dtype=float)
    times = pd.to_datetime(bars[time_col]).to_numpy()
    bar_range = (bars[high_col] - bars[low_col]).to_numpy(dtype=float)
    days = bars[day_col].to_numpy()

    for symbol, idx in bars.groupby(symbol_col, sort=False).indices.items():
        idx = np.asarray(idx)
        sym_times = times[idx]
        sym_days = days[idx]
        sym_range = bar_range[idx]
        window_start = sym_times - np.timedelta64(int(window_minutes * 60), "s")
        lo = np.searchsorted(sym_times, window_start, side="left")
        hi = np.arange(len(idx)) + 1  # inclusive of the bar itself
        result = np.full(len(idx), np.nan, dtype=float)
        cum = np.concatenate([[0.0], np.cumsum(sym_range)])
        for i in range(len(idx)):
            if sym_days[lo[i]] != sym_days[i]:
                continue  # window would reach into prior session -> invalid
            count = hi[i] - lo[i]
            if count <= 0:
                continue
            result[i] = (cum[hi[i]] - cum[lo[i]]) / count
        out[idx] = result

    return out


def causal_session_vwap(
    bars: pd.DataFrame,
    *,
    symbol_col: str = "symbol",
    time_col: str = "timestamp",
    close_col: str = "close",
    volume_col: str = "volume",
    day_col: str = "trading_day",
) -> np.ndarray:
    """Causal (expanding, not future-looking) intraday VWAP: for bar t,
    sum(close*volume) / sum(volume) over all bars in the SAME trading day
    up to and including t. NaN if cumulative volume is 0."""
    if day_col not in bars.columns:
        raise ValueError(f"bars is missing {day_col!r}; call add_trading_day(bars) first.")
    pv = (bars[close_col] * bars[volume_col]).to_numpy(dtype=float)
    vol = bars[volume_col].to_numpy(dtype=float)
    out = np.full(len(bars), np.nan, dtype=float)
    for _, idx in bars.groupby([symbol_col, day_col], sort=False).indices.items():
        idx = np.asarray(idx)
        cum_pv = np.cumsum(pv[idx])
        cum_vol = np.cumsum(vol[idx])
        with np.errstate(divide="ignore", invalid="ignore"):
            out[idx] = np.where(cum_vol > 0, cum_pv / cum_vol, np.nan)
    return out


def time_of_day_bucket(ts_series: pd.Series) -> pd.Series:
    """Coarse UTC-hour bucket used ONLY for matched-control stratification
    (broad enough that a real economic effect shouldn't hinge on it):
      PRE_MARKET   : before 13:30 UTC (RTH open)
      OPEN_HOUR    : 13:30-14:30 UTC (first hour of RTH; NOTE families 1-3
                     may still separately exclude the first 30m for their
                     own event-definition purposes -- this bucket exists
                     for control matching, not as an event-eligibility
                     filter)
      MIDDAY       : 14:30-18:00 UTC
      LATE_SESSION : 18:00-20:00 UTC (final ~2h of RTH)
      AFTER_HOURS  : 20:00 UTC onward
    """
    t = pd.to_datetime(ts_series)
    minutes_of_day = t.dt.hour * 60 + t.dt.minute
    bins = [-1, 13 * 60 + 30, 14 * 60 + 30, 18 * 60, 20 * 60, 24 * 60]
    labels = ["PRE_MARKET", "OPEN_HOUR", "MIDDAY", "LATE_SESSION", "AFTER_HOURS"]
    return pd.cut(minutes_of_day, bins=bins, labels=labels, right=False).astype(str)


def add_bar_features(bars: pd.DataFrame) -> pd.DataFrame:
    """Returns a COPY of `bars` (assumed already sorted by [symbol,
    timestamp], as `load_ohlcv_directory` guarantees) with the columns
    every family/control-matching step in this phase needs:
      - trading_day
      - time_of_day_bucket
      - trailing_vol_60m: causal trailing-60m ATR-style range proxy
        (see causal_atr_proxy), used as BOTH a volatility-bucketing
        feature and a default risk_per_unit for MFE/MAE R-multiples.
      - vol_bucket: LOW/MID/HIGH tertile of trailing_vol_60m AS A
        FRACTION OF PRICE (trailing_vol_60m / close), computed with
        GLOBAL (whole-dataset) tertile cutpoints so the bucket means the
        same thing across symbols/days -- used for matched-control
        stratification, never as part of an event's defining condition.
    """
    out = add_trading_day(bars)
    out["time_of_day_bucket"] = time_of_day_bucket(out["timestamp"])
    out["trailing_vol_60m"] = causal_atr_proxy(out, window_minutes=60)
    vol_pct = out["trailing_vol_60m"] / out["close"]
    valid = vol_pct.notna()
    out["vol_bucket"] = "UNKNOWN"
    if valid.sum() >= 30:
        out.loc[valid, "vol_bucket"] = pd.qcut(
            vol_pct[valid], q=3, labels=["LOW", "MID", "HIGH"], duplicates="drop"
        ).astype(str)
    return out


# ---------------------------------------------------------------------
# Forward horizon + MFE/MAE application over an event table
# ---------------------------------------------------------------------

DEFAULT_HORIZONS_MINUTES: Sequence[int] = (15, 30, 60, 120)


def compute_event_horizon_and_mfe_mae(
    bars: pd.DataFrame,
    events: pd.DataFrame,
    *,
    horizons_minutes: Sequence[int] = DEFAULT_HORIZONS_MINUTES,
    event_id_col: str = "event_id",
    symbol_col: str = "symbol",
    time_col: str = "timestamp",
    entry_price_col: str = "entry_price",
    direction_col: str = "direction",
    risk_col: str = "risk_per_unit",
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Applies `research_stats.forward_return_horizons` and
    `research_stats.compute_mfe_mae` to every row of `events`, causally
    bounded at each event's own trading day's RTH close (never crosses
    session close, per `session_close_timestamp_utc`).

    Direction-aware: for a "short" event (`direction_col == -1` or
    `"short"`), forward_close_return_pct and MFE/MAE are sign-flipped so
    "favorable" consistently means "in the event's own predicted
    direction" regardless of long/short -- callers doing a raw pooled
    mean of `forward_return_signed_pct` therefore get a coherent
    "conditional edge in the direction the phenomenon predicts", not a
    number that partially cancels itself out across longs and shorts.

    Returns (horizon_metrics_df, mfe_mae_df):
      - horizon_metrics_df: one row per (event_id, horizon) --
        event_id, symbol, timestamp, horizon_label, horizon_minutes,
        bars_observed, forward_return_pct (direction-adjusted),
        forward_return_signed_pct (alias, direction-adjusted -- kept as
        two columns for spec/CSV-consumer convenience),
        favorable_excursion_pct, adverse_excursion_pct (direction-
        adjusted, always >= 0 for a real move in favor/against),
        bounded_by_session_close.
      - mfe_mae_df: one row per event_id -- mfe_price, mae_price, mfe_R,
        mae_R, bar_count, computed over [event timestamp, bounded end of
        the LARGEST requested horizon] (so MFE/MAE reflects the same
        window the longest horizon's forward return does).

    Events for which the bars slice is empty (e.g. entry at/after
    session close) are skipped with a warning row omitted from output --
    callers should compare `len(events)` against the returned frames'
    unique event_id count to detect this.
    """
    horizon_rows: list[dict] = []
    mfe_rows: list[dict] = []
    max_horizon = max(horizons_minutes)

    bars_by_symbol = {sym: g.sort_values(time_col) for sym, g in bars.groupby(symbol_col, sort=False)}

    for _, ev in events.iterrows():
        sym = ev[symbol_col]
        sym_bars = bars_by_symbol.get(sym)
        if sym_bars is None or sym_bars.empty:
            continue
        entry_ts = pd.Timestamp(ev[time_col])
        entry_price = float(ev[entry_price_col])
        direction_raw = ev[direction_col]
        is_short = direction_raw in (-1, "short", "SHORT")
        sign = -1.0 if is_short else 1.0
        close_ts = session_close_timestamp_utc(entry_ts)
        risk = float(ev[risk_col]) if risk_col in ev and pd.notna(ev[risk_col]) else 0.0

        results = forward_return_horizons(
            sym_bars,
            entry_timestamp=entry_ts,
            entry_price=entry_price,
            horizons_minutes=list(horizons_minutes),
            session_close_timestamp=close_ts,
            time_col=time_col,
        )
        for r in results:
            fwd = r["forward_close_return_pct"]
            fwd_adj = fwd * sign if fwd is not None else None
            fav_high = r["favorable_excursion_high"]
            adv_low = r["adverse_excursion_low"]
            if fav_high is not None and adv_low is not None:
                if is_short:
                    favorable_pct = (entry_price - adv_low) / entry_price * 100.0
                    adverse_pct = (fav_high - entry_price) / entry_price * 100.0
                else:
                    favorable_pct = (fav_high - entry_price) / entry_price * 100.0
                    adverse_pct = (entry_price - adv_low) / entry_price * 100.0
            else:
                favorable_pct = None
                adverse_pct = None
            horizon_rows.append({
                "event_id": ev[event_id_col],
                "symbol": sym,
                "timestamp": entry_ts,
                "direction": direction_raw,
                "horizon_label": r["horizon_label"],
                "horizon_minutes": r["horizon_minutes"],
                "bars_observed": r["bars_observed"],
                "forward_return_pct": fwd,
                "forward_return_signed_pct": fwd_adj,
                "favorable_excursion_pct": favorable_pct,
                "adverse_excursion_pct": adverse_pct,
                "bounded_by_session_close": r["bounded_by_session_close"],
            })

        raw_end = min(entry_ts + pd.Timedelta(minutes=max_horizon), close_ts)
        window_mask = (sym_bars[time_col] >= entry_ts) & (sym_bars[time_col] <= raw_end)
        if window_mask.any():
            try:
                mm = compute_mfe_mae(
                    sym_bars, entry_timestamp=entry_ts, exit_timestamp=raw_end,
                    entry_price=entry_price, risk_per_unit=risk,
                    direction="short" if is_short else "long", time_col=time_col,
                )
                mfe_rows.append({"event_id": ev[event_id_col], "symbol": sym, "timestamp": entry_ts, **mm})
            except ValueError:
                pass

    return pd.DataFrame(horizon_rows), pd.DataFrame(mfe_rows)


# ---------------------------------------------------------------------
# Matched-control candidate pool construction
# ---------------------------------------------------------------------

def sample_control_candidates(
    bars_feat: pd.DataFrame,
    events: pd.DataFrame,
    *,
    stride_minutes: int = 20,
    exclusion_buffer_minutes: float = 60.0,
    warmup_minutes: float = 90.0,
    min_lead_minutes: float = 15.0,
    symbol_col: str = "symbol",
    time_col: str = "timestamp",
    seed: int = 0,
    max_candidates: int = 40_000,
) -> pd.DataFrame:
    """Builds a candidate CONTROL population: bars strided every
    `stride_minutes` per (symbol, trading_day), EXCLUDING any candidate
    within `exclusion_buffer_minutes` of any qualifying event for this
    same family/definition on the same symbol (so controls are genuinely
    "did not satisfy the phenomenon condition around this time", not just
    "wasn't the exact minute picked as the representative event"), and
    excluding the first `warmup_minutes` of each session (features like
    trailing_vol_60m/60m trailing return are NaN there anyway) and the
    last `min_lead_minutes` before RTH close (need at least a little
    forward room to be a meaningful control, mirroring event
    entries needing the same).

    Returns a copy of the candidate rows from `bars_feat` (all its
    feature columns preserved) plus nothing else added -- caller tags
    these as the "control" side of a `treatment_col` before calling
    `research_stats.matched_control_sample`.

    `max_candidates`: if the strided pool before exclusion still exceeds
    this, a seeded deterministic subsample is taken (keeps
    `matched_control_sample`'s O(candidates_in_stratum * events_in_stratum)
    pairing tractable) -- see `research_stats.matched_control_sample`'s
    docstring for why unbounded candidate pools are a performance risk
    there.
    """
    day_open = pd.Timedelta(hours=8)  # data starts ~08:00 UTC per symbol/day
    rows = []
    for (sym, day), g in bars_feat.groupby([symbol_col, "trading_day"], sort=False):
        g = g.sort_values(time_col)
        session_start = day + day_open
        close_ts = session_close_timestamp_utc(day)
        eligible_start = session_start + pd.Timedelta(minutes=warmup_minutes)
        eligible_end = close_ts - pd.Timedelta(minutes=min_lead_minutes)
        window = g[(g[time_col] >= eligible_start) & (g[time_col] <= eligible_end)]
        if window.empty:
            continue
        strided = window.iloc[:: max(1, int(round(stride_minutes)))]
        rows.append(strided)
    if not rows:
        return bars_feat.iloc[0:0].copy()
    pool = pd.concat(rows, ignore_index=False)

    if len(events):
        ev_by_symbol = {sym: pd.to_datetime(g[time_col]).to_numpy() for sym, g in events.groupby(symbol_col)}
        buffer_ns = int(exclusion_buffer_minutes * 60 * 1e9)
        keep_mask = np.ones(len(pool), dtype=bool)
        pool_symbols = pool[symbol_col].to_numpy()
        pool_times = pd.to_datetime(pool[time_col]).to_numpy()
        for sym, ev_times in ev_by_symbol.items():
            sym_mask = pool_symbols == sym
            if not sym_mask.any():
                continue
            idxs = np.where(sym_mask)[0]
            t = pool_times[idxs].astype("datetime64[ns]").astype(np.int64)
            e = ev_times.astype("datetime64[ns]").astype(np.int64)
            # For each candidate, distance to nearest event time.
            order = np.argsort(e)
            e_sorted = e[order]
            pos = np.searchsorted(e_sorted, t)
            pos_lo = np.clip(pos - 1, 0, len(e_sorted) - 1)
            pos_hi = np.clip(pos, 0, len(e_sorted) - 1)
            dist = np.minimum(np.abs(t - e_sorted[pos_lo]), np.abs(t - e_sorted[pos_hi]))
            too_close = dist <= buffer_ns
            keep_mask[idxs[too_close]] = False
        pool = pool.loc[keep_mask]

    if len(pool) > max_candidates:
        rng = np.random.default_rng(seed)
        chosen = rng.choice(len(pool), size=max_candidates, replace=False)
        pool = pool.iloc[np.sort(chosen)]

    return pool.copy()


# ---------------------------------------------------------------------
# Economic magnitude classification
# ---------------------------------------------------------------------

#: Conservative, explicitly-stated friction assumption for these liquid
#: large/mega-cap US equities: ~4bps one-way spread+slippage + ~1bp
#: commissions/fees = ~5bps one-way, ~10bps round-trip. This is a
#: deliberately conservative (i.e. generous-to-friction, not
#: generous-to-the-phenomenon) reference: real execution on names like
#: AAPL/MSFT/NVDA is often tighter, but a raw discovery screen should not
#: flatter itself with an optimistic cost assumption.
ONE_WAY_FRICTION_BPS = 5.0
ROUND_TRIP_FRICTION_BPS = 2 * ONE_WAY_FRICTION_BPS  # 10 bps


def classify_economic_magnitude(
    excess_forward_return_pct: float | None,
    mfe_pct_median: float | None,
    *,
    round_trip_friction_bps: float = ROUND_TRIP_FRICTION_BPS,
) -> str:
    """Classifies a family/definition's magnitude as one of
    ECONOMICALLY_TOO_SMALL / POTENTIALLY_TRADEABLE / STRONG_EFFECT by
    comparing the matched-control EXCESS forward return (bps) and the
    median MFE (bps, an upper bound on a hypothetical perfect exit -- NOT
    claimed as harvestable) against `round_trip_friction_bps` (default
    10bps, see ROUND_TRIP_FRICTION_BPS docstring above).

      ECONOMICALLY_TOO_SMALL: excess effect magnitude < friction (an
        average conditional edge that doesn't even cover round-trip
        costs before any consideration of imperfect entries/exits).
      POTENTIALLY_TRADEABLE: excess effect magnitude >= friction but
        < 2x friction, OR MFE upper bound is < 2x friction (edge exists
        but is thin relative to a realistic cost base -- would need a
        materially better-than-median exit to be worth engineering).
      STRONG_EFFECT: excess effect magnitude >= 2x friction AND MFE
        upper bound >= 2x friction.

    Returns "INSUFFICIENT_DATA" if either input is None.
    """
    if excess_forward_return_pct is None or mfe_pct_median is None:
        return "INSUFFICIENT_DATA"
    excess_bps = abs(excess_forward_return_pct) * 100.0
    mfe_bps = abs(mfe_pct_median) * 100.0
    friction = round_trip_friction_bps
    if excess_bps < friction:
        return "ECONOMICALLY_TOO_SMALL"
    if excess_bps < 2 * friction or mfe_bps < 2 * friction:
        return "POTENTIALLY_TRADEABLE"
    return "STRONG_EFFECT"


# ---------------------------------------------------------------------
# Data sufficiency labeling
# ---------------------------------------------------------------------

def data_sufficiency_label(
    *,
    n_events: int,
    n_symbols: int,
    n_days: int,
    total_trading_days: int = 62,
    total_symbols: int = 35,
    top1_symbol_share: float | None = None,
    best_day_share: float | None = None,
) -> str:
    """Judges ADEQUATE / LIMITED / SEVERELY_LIMITED against the ACTUAL
    DEVELOPMENT window (~62 trading days, 35 symbols) rather than a fixed
    external threshold like "60 days" -- see brief. Heuristic (documented
    here, not tuned per family):
      ADEQUATE: n_events >= 100 AND n_symbols >= 40% of universe (14)
        AND n_days >= 30% of window (19), AND no concentration flag.
      SEVERELY_LIMITED: n_events < 30 OR n_symbols < 5 OR n_days < 5.
      LIMITED: everything else (some structure/breadth, but short of
        ADEQUATE's bar, or ADEQUATE's breadth met but concentration is
        high -- see below).
    A concentration flag (top1_symbol_share or best_day_share > 0.40)
    downgrades an otherwise-ADEQUATE result to LIMITED: breadth in
    aggregate counts doesn't mean much if 40%+ of the positive effect
    comes from one symbol or one day.
    """
    if n_events < 30 or n_symbols < 5 or n_days < 5:
        return "SEVERELY_LIMITED"
    symbol_frac = n_symbols / total_symbols
    day_frac = n_days / total_trading_days
    concentrated = (top1_symbol_share is not None and top1_symbol_share > 0.40) or (
        best_day_share is not None and best_day_share > 0.40
    )
    if n_events >= 100 and symbol_frac >= 0.40 and day_frac >= 0.30 and not concentrated:
        return "ADEQUATE"
    return "LIMITED"


# ---------------------------------------------------------------------
# Verdict taxonomy
# ---------------------------------------------------------------------

@dataclass
class VerdictInputs:
    """One definition's evidence, boiled down to the booleans/labels the
    verdict checklist in the brief actually asks for. A family script
    populates one of these per definition, then `determine_verdict` maps
    it to the taxonomy. Keeping this as an explicit small struct (rather
    than passing a dict of raw numbers into a rules function) makes the
    per-definition judgment calls a script author has to make (e.g. "is
    the effect surface stable?") visible in the code, not buried in a
    threshold."""

    coherent_direction: bool  # sign of excess effect agrees across horizons
    matched_control_support: bool  # common_support_counts non-trivial (both sides)
    nontrivial_economic_scale: bool  # classification != ECONOMICALLY_TOO_SMALL
    adequate_event_count: bool  # data_sufficiency_label in {ADEQUATE, LIMITED}
    temporal_breadth: bool  # events span a meaningful fraction of days
    symbol_breadth: bool  # events span a meaningful fraction of symbols
    stable_effect_surface: bool  # NOT a single-cell spike (effect_surface check)
    asymmetric_mfe_mae: bool  # MFE and MAE are not ~equal (directional edge, not noise)
    concentration_low: bool  # not dominated by 1-2 symbols/days
    excess_ci_excludes_zero: bool  # clustered bootstrap CI for excess doesn't straddle 0
    data_sufficiency: str  # "ADEQUATE" / "LIMITED" / "SEVERELY_LIMITED"


def determine_verdict(v: VerdictInputs) -> tuple[str, str]:
    """Maps a `VerdictInputs` to (verdict, reasoning) per the brief's
    taxonomy: PHENOMENON_PRESENT / WEAK_SIGNAL / PHENOMENON_NOT_OBSERVED /
    INSUFFICIENT_DATA.
    """
    if v.data_sufficiency == "SEVERELY_LIMITED":
        return "INSUFFICIENT_DATA", (
            "Event count/breadth too low (SEVERELY_LIMITED) to fairly assess this definition "
            "regardless of the point estimates observed."
        )

    early_kill_checks = [
        not v.coherent_direction,
        not v.nontrivial_economic_scale,
        not v.stable_effect_surface,
        not v.asymmetric_mfe_mae,
        not v.concentration_low,
        not v.excess_ci_excludes_zero,
    ]
    n_failed = sum(early_kill_checks)

    strong_checks = [
        v.coherent_direction,
        v.matched_control_support,
        v.nontrivial_economic_scale,
        v.adequate_event_count,
        v.temporal_breadth,
        v.symbol_breadth,
        v.stable_effect_surface,
        v.excess_ci_excludes_zero,
    ]

    if n_failed >= 4:
        return "PHENOMENON_NOT_OBSERVED", (
            f"{n_failed}/6 early-kill checks failed (near-zero/incoherent excess effect, "
            "unstable effect surface, non-asymmetric MFE/MAE, high concentration, or a "
            "clustered-bootstrap CI for excess that straddles zero) -- most of the early-kill "
            "checklist holds, so this definition is treated as PHENOMENON_NOT_OBSERVED rather "
            "than cherry-picked into a weaker positive verdict."
        )

    if all(strong_checks):
        return "PHENOMENON_PRESENT", (
            "Coherent direction across horizons, matched-control support present, non-trivial "
            "economic scale, adequate event count/breadth (temporal AND symbol), stable effect "
            "surface, and the clustered-bootstrap CI for excess excludes zero."
        )

    return "WEAK_SIGNAL", (
        f"Some structure present ({6 - n_failed}/6 early-kill checks passed) but "
        f"{sum(not c for c in strong_checks)}/{len(strong_checks)} PHENOMENON_PRESENT "
        "requirements unmet -- breadth, magnitude, or certainty is too weak for a strong claim, "
        "but not weak enough to call this a clean non-observation."
    )
