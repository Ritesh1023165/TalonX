"""
research/scripts/task67a_family06_opening_later.py
---------------------------------------------------------
Task 67B Step 2, Family 6: OPENING INFORMATION -> LATER-SESSION
CONTINUATION.

Question: does what happens in the first 30 minutes of RTH (13:30-14:00
UTC) carry information about the LATER session, when used PURELY AS A
SIGNAL (not traded itself)? All shared mechanics (dedup, horizon/MFE-MAE,
matched control, bootstrap, concentration, effect surface, economic
classification, verdict) are delegated to
research/task67a_lib/family_runner.py.

Exploratory, read-only, DEVELOPMENT-data-only phenomenon discovery -- NOT
a trading engine, NOT a backtest, NOT strategy freezing. Universe data
access is exclusively via research.task67a_lib.data_guard's
STAGE1_DISCOVERY_GUARD (DEVELOPMENT role only). The SPY benchmark CSV
(data/historical_1m/task67a_benchmarks/SPY.csv, used only by definition
B) is NOT covered by DataSplitGuard -- only the DEVELOPMENT role was ever
materialized for it, so a direct `pd.read_csv` on that path is not a
data-discipline violation (see the brief's point 7).

THIS IS NOT ORPB: talonx_quant/orpb_v1.py was never opened or referenced
while designing this family. The opening 13:30-14:00 UTC window here
produces a NUMBER (a signal value: opening return, opening relative
strength, or opening relative volume) that CONDITIONS a LATER entry --
the opening window itself is never traded, and the actual event/decision
timestamp is always placed strictly AFTER the window (at the first bar
at/after 14:00 UTC, which is exactly 14:00 UTC on every day this
DEVELOPMENT dataset has continuous 1-minute coverage; on the rare day
with a data gap exactly at 14:00 the decision bar is instead the very
next available bar -- a fixed, documented, symbol/day-independent rule,
not a per-event choice). Forward horizons (15/30/60/120m) are measured
FROM that 14:00 UTC decision point into the later session, per the brief.

## The three definitions

All three definitions share one shape: compute a per-(symbol, trading_day)
signal from ONLY the bars inside [13:30, 14:00) UTC (see
`_opening_window_agg` -- restricted with an explicit boolean window mask,
never a causal-lookback helper that could silently reach further back),
then join that signal onto the DECISION bar (first bar at/after 14:00 UTC
for that symbol/day, see `_decision_bars`) and apply a condition + a
direction rule there. The signal computation for a given (symbol, day)
never depends on the later-session bars used to compute forward returns.

  A) `opening_return_magnitude`: signal = that symbol's own 13:30->14:00
     UTC opening-to-close return of the window (window's first bar's OPEN
     print vs. its last bar's CLOSE print -- i.e. what actually printed
     during the opening 30 minutes, not a close-to-close proxy).
     Condition: |signal| >= the GLOBAL top-tertile cutoff of |signal|
     across every (symbol, day) in the dataset (documented choice: top
     ~33% by absolute opening-30m move -- broad, not a fine-tuned
     percentile). Direction = sign(signal). Tests whether STRONG opens (in
     either direction) continue (momentum) or mean-revert (reversal) later
     in the session -- the excess sign is reported however it actually
     comes out, not assumed to be continuation going in.

  B) `opening_relative_strength_vs_spy`: signal = that symbol's own
     opening-30m return MINUS SPY's own opening-30m return on the SAME
     trading day (both computed by the exact same `_opening_window_agg`
     helper -- SPY is just another "symbol" for this purpose). Simple raw
     relative-strength signal over the same fixed window -- deliberately
     SIMPLER than a beta-adjusted approach (no beta estimation, no
     rolling-window regression); this is a documented simplification given
     the time budget, not an attempt at Family 4's fuller machinery
     (Family 4 does not exist yet in this repo; this family was designed
     without reading or depending on it). Condition: |signal| >= global
     top-tertile cutoff of |signal|. Direction = sign(signal). Tests
     whether it is RELATIVE (vs. SPY) rather than ABSOLUTE opening
     strength that carries continuation information -- summary.md compares
     this definition's results against definition A's side by side.

  C) `opening_relative_volume`: signal = that symbol's own opening-30m
     CUMULATIVE VOLUME divided by that SAME symbol's LEAVE-ONE-DAY-OUT
     MEDIAN opening-30m volume (median computed from all OTHER DEVELOPMENT
     days for that symbol, excluding the day being scored -- the more
     defensible of the two options the brief offered, preferred here
     since the time budget allowed it; see `_leave_one_day_out_median`).
     Condition: relative_volume >= the GLOBAL top-tertile cutoff of
     relative_volume across the dataset (unusually high opening
     participation; not an absolute threshold since "typical" volume
     varies hugely across this 35-symbol universe). Volume has no inherent
     sign, so direction = sign of that SAME day's opening-30m return
     (definition A's own signal) -- an explicitly documented
     simplification that conflates volume-MAGNITUDE (the condition) with
     direction-SOURCE (borrowed from A); the test this becomes is "does a
     HIGH-VOLUME opening move, in the direction it moved, continue later".

## Data-quality guard

A (symbol, day) is only eligible if its opening window has
>= `OPENING_WINDOW_MIN_BARS` (20 of the nominal 30) one-minute bars
present -- a sparse/gappy opening window's signal is not trustworthy
enough to condition an entry on, mirroring the min-lead/warmup style
guards Families 1-3 use elsewhere in this screen.

## Effect-surface stability check axis (deviation from Families 1-3)

`run_family_definition`'s default `effect_surface_param_cols` is
`("trailing_vol_60m", "minutes_of_day")` -- appropriate for Families 1-3,
whose events fire at many different times of day. Family 6's decision
timestamp is, by construction, the SAME fixed clock time (14:00 UTC, or
the next available bar on a gap day) for every single event, so
`minutes_of_day` is degenerate here: constant (or near-constant) across
the whole event set. `research_stats.effect_surface` bins each param
column via `pd.qcut`; a constant column collapses to zero populated
quantile bins (all rows land in a `NaN` category, which `groupby`'s
`observed=True` then drops entirely), silently producing an EMPTY effect-
surface DataFrame -- confirmed by direct testing, not assumed. Rather
than resurrect a fake `minutes_of_day` axis for a family that has none by
design, this family calls `run_family_definition` with
`effect_surface_param_cols=("trailing_vol_60m",)` (single-axis stability
check over the causal trailing-60m volatility proxy only). This is a
targeted use of an existing, already-exposed `run_family_definition`
keyword argument -- no change to `family_runner.py` or
`research_stats.py` themselves (both remain untouched, byte-identical to
the protected baseline).

## De-duplication

`group_keys=["symbol"]`, `min_gap_minutes=1200` (~20 hours). Because the
decision timestamp is a FIXED clock time (14:00 UTC) shared by every
event, there is naturally at most one candidate event per symbol per day
already -- dedup here is mostly a formality/safety net (a 1200-minute gap
is far longer than one trading day's session, so it cannot accidentally
merge two genuinely distinct days into one cluster; it exists only to
collapse the pathological case of two candidate rows landing on the exact
same symbol/day, e.g. if a future definition change ever produced more
than one decision bar per day), unlike Families 1-3/5 where the same
condition could legitimately retrigger on many adjacent bars.
"""
from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pandas as pd

from research.task67a_lib.data_guard import DataRole, get_stage1_guard
from research.task67a_lib.family_runner import run_family_definition
from research.task67a_lib.research_stats import DEFAULT_SEED
from research.task67a_lib.screening_framework import (
    ONE_WAY_FRICTION_BPS,
    POST_OPENING_RANGE_UTC_HOUR,
    ROUND_TRIP_FRICTION_BPS,
    RTH_OPEN_UTC_HOUR,
    RTH_OPEN_UTC_MINUTE,
    add_bar_features,
    add_trading_day,
)

ROOT = Path(__file__).resolve().parents[2]
OUT_DIR = ROOT / "results/task67a_phenomenon_discovery/family_06_opening_later"
SPY_BENCHMARK_CSV = ROOT / "data/historical_1m/task67a_benchmarks/SPY.csv"
FAMILY_ID = "family_06_opening_later"
FAMILY_SEED_OFFSET = 600

#: Minimum number of 1-minute bars required inside the [13:30, 14:00) UTC
#: window for a (symbol, day)'s opening signal to be trusted -- out of a
#: nominal 30. Broad, round, chosen before looking at any result.
OPENING_WINDOW_MIN_BARS = 20

#: "Top tertile" cutoff quantile used by every definition's condition
#: (documented once here): the top ~33% of the relevant |signal| (or,
#: for definition C, plain signal since volume ratios are already
#: non-negative) distribution, computed GLOBALLY across every (symbol,
#: day) in the dataset -- broad, not a fine-tuned percentile.
SIGNAL_TOP_TERTILE_QUANTILE = 2.0 / 3.0

_OPENING_START_MINUTES = RTH_OPEN_UTC_HOUR * 60 + RTH_OPEN_UTC_MINUTE  # 13:30 UTC = 810
_OPENING_END_MINUTES = POST_OPENING_RANGE_UTC_HOUR * 60  # 14:00 UTC = 840


def _minutes_of_day(ts_series: pd.Series) -> pd.Series:
    t = pd.to_datetime(ts_series)
    return t.dt.hour * 60 + t.dt.minute


def _opening_window_mask(bars: pd.DataFrame) -> np.ndarray:
    """True where the bar falls in [13:30, 14:00) UTC -- the opening
    30-minute INFORMATION window. Never includes 14:00 UTC itself (that
    is the decision timestamp, computed separately by `_decision_bars`),
    and never includes anything before 13:30 UTC."""
    mod = _minutes_of_day(bars["timestamp"])
    return ((mod >= _OPENING_START_MINUTES) & (mod < _OPENING_END_MINUTES)).to_numpy()


def _opening_window_agg(bars_with_day: pd.DataFrame) -> pd.DataFrame:
    """For each (symbol, trading_day), aggregates ONLY the bars inside
    [13:30, 14:00) UTC into: window_open (first bar's own open print),
    window_close (last bar's own close print), opening_return
    ((window_close - window_open) / window_open), window_volume (sum of
    volume over the window), n_bars (count of window bars -- used by
    callers to apply `OPENING_WINDOW_MIN_BARS`). Requires `trading_day`
    already present (call `add_trading_day` first if needed). Computes
    this from a strictly time-windowed slice, not a causal-lookback
    helper, so it structurally cannot read a bar at/after 14:00 UTC or
    before 13:30 UTC."""
    win_mask = _opening_window_mask(bars_with_day)
    window = bars_with_day.loc[win_mask, ["symbol", "trading_day", "timestamp", "open", "close", "volume"]]
    window = window.sort_values(["symbol", "trading_day", "timestamp"])
    grouped = window.groupby(["symbol", "trading_day"], sort=False)
    agg = grouped.agg(
        window_open=("open", "first"),
        window_close=("close", "last"),
        window_volume=("volume", "sum"),
        n_bars=("close", "size"),
    ).reset_index()
    with np.errstate(divide="ignore", invalid="ignore"):
        agg["opening_return"] = (agg["window_close"] - agg["window_open"]) / agg["window_open"]
    return agg


def _decision_bars(bars_feat: pd.DataFrame) -> pd.DataFrame:
    """For each (symbol, trading_day), returns the single row that is the
    FIRST bar at or after 14:00 UTC (the decision timestamp -- exactly
    14:00 UTC whenever this dataset has continuous 1-minute coverage
    there; the next available bar on a rare gap day). Preserves every
    `bars_feat` column (entry_price, trailing_vol_60m, time_of_day_bucket,
    vol_bucket, trading_day all sourced straight from here, per the
    shared pipeline's contract)."""
    mod = _minutes_of_day(bars_feat["timestamp"])
    post = bars_feat.loc[(mod >= _OPENING_END_MINUTES).to_numpy()].copy()
    post = post.sort_values(["symbol", "trading_day", "timestamp"])
    return post.groupby(["symbol", "trading_day"], as_index=False, sort=False).first()


def _leave_one_day_out_median(values: np.ndarray) -> np.ndarray:
    """For each position i, the median of `values` EXCLUDING position i
    (i.e. a per-symbol "typical opening volume computed from all OTHER
    days" -- the more defensible of the two normalization options the
    brief offered for definition C). O(n^2) but n is ~62 trading days per
    symbol, so this is trivially cheap (35 symbols x ~62^2 <= ~135k
    scalar ops total)."""
    n = len(values)
    out = np.full(n, np.nan, dtype=float)
    for i in range(n):
        other = np.delete(values, i)
        out[i] = float(np.median(other)) if len(other) else np.nan
    return out


def _events_from_merged(merged: pd.DataFrame) -> pd.DataFrame:
    """`merged` must have a boolean `_fires` column and an integer
    (+1/-1) `_direction` column already applied (condition AND
    direction != 0). Builds the candidate_events table
    `run_family_definition` requires, sourced entirely off the decision
    bar's own `bars_feat` columns."""
    sel = merged.loc[merged["_fires"]]
    cand = sel[[
        "symbol", "timestamp", "close", "trailing_vol_60m", "time_of_day_bucket", "vol_bucket", "trading_day",
    ]].rename(columns={"close": "entry_price"}).copy()
    cand["direction"] = sel["_direction"].astype(int).to_numpy()
    return cand.reset_index(drop=True)


def definition_a_opening_return_magnitude(bars_feat: pd.DataFrame) -> pd.DataFrame:
    agg = _opening_window_agg(bars_feat)
    agg = agg[agg["n_bars"] >= OPENING_WINDOW_MIN_BARS].copy()
    if agg.empty:
        return pd.DataFrame(columns=["symbol", "timestamp", "entry_price", "direction", "trading_day"])
    abs_signal = agg["opening_return"].abs()
    valid = abs_signal.notna()
    cutoff = abs_signal[valid].quantile(SIGNAL_TOP_TERTILE_QUANTILE) if valid.any() else np.inf
    agg["_direction"] = np.sign(agg["opening_return"]).astype(int)
    agg["_fires"] = valid.to_numpy() & (abs_signal >= cutoff).to_numpy() & (agg["_direction"] != 0).to_numpy()

    decision = _decision_bars(bars_feat)
    merged = decision.merge(agg[["symbol", "trading_day", "_fires", "_direction"]], on=["symbol", "trading_day"], how="inner")
    return _events_from_merged(merged)


def definition_b_opening_relative_strength(bars_feat: pd.DataFrame, spy_bars_with_day: pd.DataFrame) -> pd.DataFrame:
    agg = _opening_window_agg(bars_feat)
    agg = agg[agg["n_bars"] >= OPENING_WINDOW_MIN_BARS].copy()
    spy_agg = _opening_window_agg(spy_bars_with_day)
    spy_agg = spy_agg[spy_agg["n_bars"] >= OPENING_WINDOW_MIN_BARS][["trading_day", "opening_return"]]
    spy_agg = spy_agg.rename(columns={"opening_return": "spy_opening_return"})
    if agg.empty or spy_agg.empty:
        return pd.DataFrame(columns=["symbol", "timestamp", "entry_price", "direction", "trading_day"])

    merged_signal = agg.merge(spy_agg, on="trading_day", how="inner")
    merged_signal["_signal"] = merged_signal["opening_return"] - merged_signal["spy_opening_return"]
    abs_signal = merged_signal["_signal"].abs()
    valid = abs_signal.notna()
    cutoff = abs_signal[valid].quantile(SIGNAL_TOP_TERTILE_QUANTILE) if valid.any() else np.inf
    merged_signal["_direction"] = np.sign(merged_signal["_signal"]).astype(int)
    merged_signal["_fires"] = valid.to_numpy() & (abs_signal >= cutoff).to_numpy() & (merged_signal["_direction"] != 0).to_numpy()

    decision = _decision_bars(bars_feat)
    merged = decision.merge(
        merged_signal[["symbol", "trading_day", "_fires", "_direction"]], on=["symbol", "trading_day"], how="inner",
    )
    return _events_from_merged(merged)


def definition_c_opening_relative_volume(bars_feat: pd.DataFrame) -> pd.DataFrame:
    agg = _opening_window_agg(bars_feat)
    agg = agg[agg["n_bars"] >= OPENING_WINDOW_MIN_BARS].copy()
    if agg.empty:
        return pd.DataFrame(columns=["symbol", "timestamp", "entry_price", "direction", "trading_day"])
    agg = agg.sort_values(["symbol", "trading_day"]).reset_index(drop=True)
    agg["_typical_volume"] = agg.groupby("symbol", sort=False)["window_volume"].transform(
        lambda s: _leave_one_day_out_median(s.to_numpy(dtype=float))
    )
    with np.errstate(divide="ignore", invalid="ignore"):
        agg["_relative_volume"] = agg["window_volume"] / agg["_typical_volume"]
    valid = agg["_relative_volume"].notna() & np.isfinite(agg["_relative_volume"])
    cutoff = agg.loc[valid, "_relative_volume"].quantile(SIGNAL_TOP_TERTILE_QUANTILE) if valid.any() else np.inf
    agg["_direction"] = np.sign(agg["opening_return"]).astype(int)
    agg["_fires"] = (
        valid.to_numpy() & (agg["_relative_volume"] >= cutoff).to_numpy() & (agg["_direction"] != 0).to_numpy()
    )

    decision = _decision_bars(bars_feat)
    merged = decision.merge(agg[["symbol", "trading_day", "_fires", "_direction"]], on=["symbol", "trading_day"], how="inner")
    return _events_from_merged(merged)


def _load_spy_benchmark() -> pd.DataFrame:
    """Loads the SPY benchmark 1-minute OHLCV CSV directly (NOT via
    DataSplitGuard -- see module docstring for why that is fine here:
    only the DEVELOPMENT role was ever materialized for this benchmark
    path, so there is no VALIDATION/REPLICATION data this could
    accidentally expose)."""
    df = pd.read_csv(SPY_BENCHMARK_CSV)
    df["timestamp"] = pd.to_datetime(df["timestamp"], utc=True)
    return add_trading_day(df)


DEFINITION_SPECS = [
    {
        "key": "opening_return_magnitude",
        "dedup_min_gap_minutes": 1200,
        "description": (
            "Signal = symbol's own 13:30->14:00 UTC opening-to-close return of the opening window. Condition: "
            "|signal| >= global top-tertile cutoff of |signal| across the dataset. Direction = sign(signal). "
            "Decision timestamp = first bar at/after 14:00 UTC. Tests continuation vs. mean-reversion of a "
            "strong ABSOLUTE opening move into the later session."
        ),
    },
    {
        "key": "opening_relative_strength_vs_spy",
        "dedup_min_gap_minutes": 1200,
        "description": (
            "Signal = symbol's opening-30m return MINUS SPY's opening-30m return, same day (simple raw relative "
            "strength, deliberately simpler than a beta-adjusted approach). Condition: |signal| >= global "
            "top-tertile cutoff of |signal|. Direction = sign(signal). Decision timestamp = first bar at/after "
            "14:00 UTC. Tests whether RELATIVE (vs. SPY), not absolute, opening strength carries continuation "
            "information -- compare against definition A in summary.md."
        ),
    },
    {
        "key": "opening_relative_volume",
        "dedup_min_gap_minutes": 1200,
        "description": (
            "Signal = symbol's opening-30m cumulative volume / that symbol's leave-one-day-out median opening-30m "
            "volume (median computed from all OTHER DEVELOPMENT days for that symbol). Condition: "
            "relative_volume >= global top-tertile cutoff. Direction = sign of that SAME day's opening-30m return "
            "(definition A's signal) -- an explicitly documented simplification conflating volume-magnitude "
            "(condition) with direction-source (borrowed from A). Decision timestamp = first bar at/after 14:00 UTC."
        ),
    },
]


def main() -> None:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    guard = get_stage1_guard()
    bars = guard.load_ohlcv(DataRole.DEVELOPMENT, symbols=None)
    bars_feat = add_bar_features(bars)
    spy_bars_with_day = _load_spy_benchmark()

    definitions = [
        {**DEFINITION_SPECS[0], "name": "opening_return_magnitude",
         "builder": lambda bf: definition_a_opening_return_magnitude(bf), "dedup_group_keys": ["symbol"]},
        {**DEFINITION_SPECS[1], "name": "opening_relative_strength_vs_spy",
         "builder": lambda bf: definition_b_opening_relative_strength(bf, spy_bars_with_day), "dedup_group_keys": ["symbol"]},
        {**DEFINITION_SPECS[2], "name": "opening_relative_volume",
         "builder": lambda bf: definition_c_opening_relative_volume(bf), "dedup_group_keys": ["symbol"]},
    ]

    all_events, all_horizon_metrics, all_control_metrics, all_mfe_mae = [], [], [], []
    definitions_summary = {}
    definitions_json = []

    for i, spec in enumerate(definitions):
        name = spec["name"]
        cand = spec["builder"](bars_feat)
        seed = DEFAULT_SEED + FAMILY_SEED_OFFSET + i
        result = run_family_definition(
            bars=bars, bars_feat=bars_feat, candidate_events=cand,
            definition_name=name, dedup_group_keys=spec["dedup_group_keys"],
            dedup_min_gap_minutes=spec["dedup_min_gap_minutes"], seed=seed,
            # minutes_of_day is degenerate (constant 14:00 UTC) for every
            # Family 6 event by construction -- see module docstring's
            # "Effect-surface stability check axis" section for why the
            # default two-axis surface would silently come back empty.
            effect_surface_param_cols=("trailing_vol_60m",),
        )

        events = result["events_df"].copy()
        if len(events):
            events["definition"] = name
            all_events.append(events)
        hm = result["horizon_metrics_df"].copy()
        if len(hm):
            hm["definition"] = name
            all_horizon_metrics.append(hm)
        cm = result["control_metrics_df"].copy()
        if len(cm):
            cm["definition"] = name
            all_control_metrics.append(cm)
        mm = result["mfe_mae_df"].copy()
        if len(mm):
            mm["definition"] = name
            all_mfe_mae.append(mm)

        definitions_summary[name] = {
            "description": spec["description"],
            "dedup_group_keys": spec["dedup_group_keys"],
            "dedup_min_gap_minutes": spec["dedup_min_gap_minutes"],
            "seed": seed,
            "n_raw_events": result["n_raw_events"],
            "n_dedup_events": result["n_dedup_events"],
            "n_symbols": result["n_symbols"],
            "n_days": result["n_days"],
            "per_horizon": result["per_horizon"],
            "mfe_pct_median": result.get("mfe_pct_median"),
            "mae_pct_median": result.get("mae_pct_median"),
            "concentration": result["concentration"],
            "effect_surface_instability": result["effect_surface_instability"],
            "effect_surface_instability_reason": result["effect_surface_instability_reason"],
            "economic_classification": result["economic_classification"],
            "data_sufficiency": result["data_sufficiency"],
            "verdict": result["verdict"],
            "verdict_reasoning": result["verdict_reasoning"],
            "verdict_inputs": result["verdict_inputs"],
            "main_weakness": result["main_weakness"],
        }
        definitions_json.append({
            "name": name,
            "description": spec["description"],
            "dedup_group_keys": spec["dedup_group_keys"],
            "dedup_min_gap_minutes": spec["dedup_min_gap_minutes"],
            "seed": seed,
        })
        print(f"[family06] {name}: raw={result['n_raw_events']} dedup={result['n_dedup_events']} "
              f"verdict={result['verdict']} econ={result['economic_classification']}")

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
        f"{sum(v=='PHENOMENON_PRESENT' for v in verdicts)}/3 PHENOMENON_PRESENT, "
        f"{sum(v=='WEAK_SIGNAL' for v in verdicts)}/3 WEAK_SIGNAL, "
        f"{sum(v=='PHENOMENON_NOT_OBSERVED' for v in verdicts)}/3 PHENOMENON_NOT_OBSERVED, "
        f"{sum(v=='INSUFFICIENT_DATA' for v in verdicts)}/3 INSUFFICIENT_DATA -- "
        "definitions are NOT averaged into one number; each is reported independently, per the brief."
    )

    # --- continuation-vs-reversal / relative-vs-absolute narrative, computed
    # programmatically off the primary (60m) horizon's excess sign so
    # summary.md's claim always matches whatever the numbers actually show. ---
    def _primary_excess(name: str):
        return definitions_summary.get(name, {}).get("per_horizon", {}).get("60m", {}).get("excess_mean_pct")

    excess_a = _primary_excess("opening_return_magnitude")
    excess_b = _primary_excess("opening_relative_strength_vs_spy")
    if excess_a is None:
        continuation_finding = "Definition A produced no usable 60m excess estimate; continuation-vs-reversal cannot be assessed."
    elif excess_a > 0:
        continuation_finding = (
            f"Definition A's 60m excess forward return is POSITIVE ({excess_a:.4f}%), i.e. strong opens tend to "
            "CONTINUE (momentum) into the later session, on this dataset/definition."
        )
    elif excess_a < 0:
        continuation_finding = (
            f"Definition A's 60m excess forward return is NEGATIVE ({excess_a:.4f}%), i.e. strong opens tend to "
            "MEAN-REVERT (reversal) into the later session, on this dataset/definition."
        )
    else:
        continuation_finding = "Definition A's 60m excess forward return is exactly zero -- no continuation or reversal signal."

    if excess_a is None or excess_b is None:
        relative_vs_absolute_finding = "One of definitions A/B lacks a usable 60m excess estimate; relative-vs-absolute comparison withheld."
    else:
        stronger = "B (relative-to-SPY)" if abs(excess_b) > abs(excess_a) else "A (absolute)"
        relative_vs_absolute_finding = (
            f"Definition A (absolute) 60m excess = {excess_a:.4f}%; Definition B (relative-to-SPY) 60m excess = "
            f"{excess_b:.4f}%. The larger-magnitude excess is definition {stronger}'s -- see summary.md's "
            "side-by-side table for the full horizon comparison and each definition's verdict/economic "
            "classification before drawing any conclusion about which (if either) is the cleaner effect."
        )

    summary = {
        "family": FAMILY_ID,
        "question": (
            "Does what happens in the first 30 minutes of RTH (13:30-14:00 UTC) carry information about the "
            "LATER session, when used purely as a signal (not traded itself)? The decision/entry timestamp is "
            "always placed strictly after the opening window (14:00 UTC)."
        ),
        "data": {
            "role": "DEVELOPMENT", "n_symbols_universe": 35, "n_trading_days": 62,
            "date_range": ["2026-05-15", "2026-08-14"],
        },
        "friction_assumption_bps": {
            "one_way": ONE_WAY_FRICTION_BPS, "round_trip": ROUND_TRIP_FRICTION_BPS,
        },
        "definitions": definitions_summary,
        "family_rollup": rollup_text,
        "continuation_vs_reversal_finding": continuation_finding,
        "relative_vs_absolute_finding": relative_vs_absolute_finding,
        "total_raw_events": int(sum(d["n_raw_events"] for d in definitions_summary.values())),
        "total_dedup_events": int(sum(d["n_dedup_events"] for d in definitions_summary.values())),
    }
    (OUT_DIR / "summary.json").write_text(json.dumps(summary, indent=2, default=str), encoding="utf-8")

    md_lines = [
        "# Family 6 -- Opening Information -> Later-Session Continuation -- Stage 1 Screening Summary",
        "",
        "Question: does what happens in the first 30 minutes of RTH (13:30-14:00 UTC) carry information about "
        "the LATER session, when used purely as a signal (not traded itself)? This is NOT ORPB -- the opening "
        "window is never traded; it only produces a number that conditions a decision placed strictly after it "
        "(14:00 UTC). Forward horizons (15/30/60/120m) are measured from that 14:00 UTC decision point.",
        "",
        f"Data: DEVELOPMENT role, 35 symbols, 62 trading days (2026-05-15..2026-08-14). Definition B additionally "
        f"uses the SPY benchmark CSV (data/historical_1m/task67a_benchmarks/SPY.csv), loaded directly since only "
        f"its DEVELOPMENT-range data was ever materialized. "
        f"Friction assumption: {ONE_WAY_FRICTION_BPS}bps one-way / {ROUND_TRIP_FRICTION_BPS}bps round-trip.",
        "",
        f"**Family rollup:** {rollup_text}",
        "",
        "## Continuation vs. mean-reversion (definition A)",
        "",
        continuation_finding,
        "",
        "## Relative (definition B) vs. absolute (definition A) opening strength",
        "",
        relative_vs_absolute_finding,
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
            f"- Economic classification: **{d['economic_classification']}**",
            f"- Data sufficiency: **{d['data_sufficiency']}**",
            f"- Effect surface instability flagged: {d['effect_surface_instability']} "
            f"({d['effect_surface_instability_reason']})",
            f"- MFE median (%, at max horizon): {d['mfe_pct_median']}; MAE median (%): {d['mae_pct_median']}",
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
        md_lines += [
            "",
            f"### VERDICT: **{d['verdict']}**",
            "",
            d["verdict_reasoning"],
            "",
            f"Main weakness: {d['main_weakness']}",
            "",
        ]
    (OUT_DIR / "summary.md").write_text("\n".join(md_lines), encoding="utf-8")
    print(f"[family06] wrote outputs to {OUT_DIR}")


if __name__ == "__main__":
    main()
