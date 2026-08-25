"""
research/scripts/task67a_family03_range_expansion.py
---------------------------------------------------------
Task 67B Step 2, Family 3: VOLATILITY / RANGE EXPANSION.

Question: does an established intraday range followed by genuine
volatility/range expansion lead to abnormal subsequent directional
movement? This script owns the event-CONDITION logic for three broad
definitions; all shared mechanics (dedup, horizon/MFE-MAE, matched
control, bootstrap, concentration, effect surface, economic
classification, verdict) are delegated to
research/task67a_lib/family_runner.py.

Exploratory, read-only, DEVELOPMENT-data-only phenomenon discovery -- NOT
a trading engine, NOT a backtest, NOT strategy freezing. Data access is
exclusively via research.task67a_lib.data_guard's STAGE1_DISCOVERY_GUARD
(DEVELOPMENT role only).

Per the brief, this family explicitly tests LATER-session/general-session
compression -> expansion and EXCLUDES the first 30 minutes of RTH
(opening-range territory is ORPB_V1's domain -- talonx_quant/orpb_v1.py
was never opened or referenced while designing this; the exclusion here
is defined independently via `screening_framework.POST_OPENING_RANGE_
UTC_HOUR`, the same 14:00 UTC cutoff already documented there for exactly
this purpose).

Definitions all follow the same shape: an "established" trailing-ATR
measure over a base window, evaluated STRICTLY BEFORE a subsequent
"recent" (expansion) window begins (via the new `_value_at_offset` helper
below -- see its docstring for why this avoids the established measure
being self-diluted by the very expansion it's supposed to precede), then
require the recent window's ATR to exceed some multiple K of the
(lagged) established ATR, with "established" additionally required to be
in the bottom global tertile (a genuinely quiet base, not just "less
active than right now").

  A) compression60_expansion15_2x: established = 60m trailing ATR proxy,
     evaluated 15m before now (i.e. as of the start of the recent
     window); must be in the bottom global tertile. Recent = 15m trailing
     ATR proxy (ending now) >= 2.0x the lagged established value.
  B) compression90_expansion10_2.5x: established = 90m ATR, evaluated 10m
     before now, bottom tertile. Recent = 10m ATR >= 2.5x established.
  C) compression45_expansion20_1.75x: established = 45m ATR, evaluated
     20m before now, bottom tertile. Recent = 20m ATR >= 1.75x
     established.

Direction: sign of `causal_trailing_return` over the recent/expansion
window itself (the direction the breakout is currently moving) -- this
family tests whether that breakout direction continues, not the opening-
range-breakout logic ORPB_V1 implements.
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
    ROUND_TRIP_FRICTION_BPS,
    ONE_WAY_FRICTION_BPS,
    POST_OPENING_RANGE_UTC_HOUR,
    add_bar_features,
    causal_atr_proxy,
    causal_trailing_return,
)

ROOT = Path(__file__).resolve().parents[2]
OUT_DIR = ROOT / "results/task67a_phenomenon_discovery/family_03_range_expansion"
FAMILY_ID = "family_03_range_expansion"
FAMILY_SEED_OFFSET = 300


def _min_lead_filter(bars_feat: pd.DataFrame, min_lead_minutes: float = 15.0) -> np.ndarray:
    close_ts = bars_feat["trading_day"] + pd.Timedelta(hours=20)
    return ((close_ts - bars_feat["timestamp"]) >= pd.Timedelta(minutes=min_lead_minutes)).to_numpy()


def _post_opening_range_filter(bars_feat: pd.DataFrame) -> np.ndarray:
    """True where the bar is at/after 14:00 UTC (30 minutes after the
    13:30 UTC RTH open) -- excludes the first-30-minutes-of-RTH
    opening-range window per the brief (ORPB territory, out of scope
    here). Uses `screening_framework.POST_OPENING_RANGE_UTC_HOUR`
    directly rather than redefining the cutoff."""
    t = pd.to_datetime(bars_feat["timestamp"])
    minutes_of_day = t.dt.hour * 60 + t.dt.minute
    return (minutes_of_day >= POST_OPENING_RANGE_UTC_HOUR * 60).to_numpy()


def _value_at_offset(
    bars_feat: pd.DataFrame, values: np.ndarray, offset_minutes: float,
    *, symbol_col: str = "symbol", time_col: str = "timestamp", day_col: str = "trading_day",
) -> np.ndarray:
    """Generic causal same-day lookback over an ARBITRARY precomputed
    array (row-aligned with `bars_feat`), not just price: for each bar t,
    returns `values` at the most recent same-day bar at or before
    (t - offset_minutes); NaN if no such bar exists yet. Same algorithm
    as `screening_framework.causal_price_at_offset` (per-symbol
    searchsorted, same-day-only), generalized because this family needs
    to look up a PRECOMPUTED TRAILING-ATR VALUE at a past offset, not a
    price.

    Why this matters for Family 3 specifically: if "established" ATR were
    simply evaluated AT the current bar t (i.e. causal_atr_proxy's own
    output, unshifted), its trailing window would itself already include
    part of the very expansion burst being detected (the two windows
    overlap at the tail), diluting the "established was quiet BEFORE the
    burst" claim by exactly however much the recent window overlaps the
    base window. Evaluating established at (t - recent_window_minutes)
    instead means the established window ends right where the recent
    (expansion) window begins -- no overlap, no self-dilution.
    """
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


def _global_low_tertile_mask(bars_feat: pd.DataFrame, established: np.ndarray) -> np.ndarray:
    """True where `established` (a price-scale ATR value, e.g. absolute
    $ range) expressed AS A FRACTION OF PRICE falls in the bottom global
    (whole-dataset) tertile -- same style/rationale as `add_bar_features`'
    own `vol_bucket` (global cutpoints so the bucket means the same thing
    across symbols/days), computed fresh here because `established` is
    this family's own LAGGED value, not `add_bar_features`'
    unlagged `trailing_vol_60m`."""
    price = bars_feat["close"].to_numpy(dtype=float)
    with np.errstate(divide="ignore", invalid="ignore"):
        pct = established / price
    mask = np.zeros(len(bars_feat), dtype=bool)
    valid = ~np.isnan(pct)
    if valid.sum() < 30:
        return mask
    try:
        bucketed = pd.qcut(pct[valid], q=3, duplicates="drop")
    except ValueError:
        return mask
    # pd.qcut on a bare numpy array (not a Series) returns a Categorical
    # directly -- it has `.codes`, not the Series-accessor `.cat.codes`.
    codes = np.asarray(bucketed.codes)
    low_code = 0
    idx = np.where(valid)[0]
    mask[idx[codes == low_code]] = True
    return mask


def _events_from_mask(bars_feat: pd.DataFrame, mask: np.ndarray, direction: np.ndarray) -> pd.DataFrame:
    cand = bars_feat.loc[mask, [
        "symbol", "timestamp", "close", "trailing_vol_60m", "time_of_day_bucket", "vol_bucket", "trading_day",
    ]].rename(columns={"close": "entry_price"}).copy()
    cand["direction"] = direction[mask]
    return cand


def _compression_expansion(
    bars_feat: pd.DataFrame, *, base_minutes: float, recent_minutes: float, expansion_multiple: float,
) -> pd.DataFrame:
    established_unlagged = causal_atr_proxy(bars_feat, window_minutes=base_minutes)
    established = _value_at_offset(bars_feat, established_unlagged, offset_minutes=recent_minutes)
    compressed_mask = _global_low_tertile_mask(bars_feat, established)
    recent = causal_atr_proxy(bars_feat, window_minutes=recent_minutes)
    with np.errstate(divide="ignore", invalid="ignore"):
        ratio = recent / established
    ret_recent = causal_trailing_return(bars_feat, recent_minutes)
    sign = np.sign(ret_recent)
    mask = (
        compressed_mask
        & (ratio >= expansion_multiple)
        & (sign != 0)
        & _post_opening_range_filter(bars_feat)
        & _min_lead_filter(bars_feat)
    )
    direction = np.where(sign > 0, 1, -1)
    return _events_from_mask(bars_feat, mask, direction)


def definition_a_compression60_expansion15(bars_feat: pd.DataFrame) -> pd.DataFrame:
    return _compression_expansion(bars_feat, base_minutes=60, recent_minutes=15, expansion_multiple=2.0)


def definition_b_compression90_expansion10(bars_feat: pd.DataFrame) -> pd.DataFrame:
    return _compression_expansion(bars_feat, base_minutes=90, recent_minutes=10, expansion_multiple=2.5)


def definition_c_compression45_expansion20(bars_feat: pd.DataFrame) -> pd.DataFrame:
    return _compression_expansion(bars_feat, base_minutes=45, recent_minutes=20, expansion_multiple=1.75)


DEFINITIONS = [
    {
        "name": "compression60_expansion15_2x",
        "builder": definition_a_compression60_expansion15,
        "dedup_group_keys": ["symbol"],
        "dedup_min_gap_minutes": 30,
        "description": (
            "Established = 60m trailing ATR proxy, evaluated 15m before now (bottom global tertile as a "
            "fraction of price). Recent = 15m trailing ATR proxy (ending now) >= 2.0x the lagged established "
            "value. Direction = sign of the 15m trailing return (breakout direction). Excludes first 30m of RTH."
        ),
    },
    {
        "name": "compression90_expansion10_2.5x",
        "builder": definition_b_compression90_expansion10,
        "dedup_group_keys": ["symbol"],
        "dedup_min_gap_minutes": 20,
        "description": (
            "Established = 90m trailing ATR proxy, evaluated 10m before now (bottom global tertile). Recent = "
            "10m trailing ATR proxy >= 2.5x the lagged established value. Direction = sign of the 10m trailing "
            "return. Excludes first 30m of RTH."
        ),
    },
    {
        "name": "compression45_expansion20_1.75x",
        "builder": definition_c_compression45_expansion20,
        "dedup_group_keys": ["symbol"],
        "dedup_min_gap_minutes": 30,
        "description": (
            "Established = 45m trailing ATR proxy, evaluated 20m before now (bottom global tertile). Recent = "
            "20m trailing ATR proxy >= 1.75x the lagged established value. Direction = sign of the 20m trailing "
            "return. Excludes first 30m of RTH."
        ),
    },
]


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
        result = run_family_definition(
            bars=bars, bars_feat=bars_feat, candidate_events=cand,
            definition_name=name, dedup_group_keys=spec["dedup_group_keys"],
            dedup_min_gap_minutes=spec["dedup_min_gap_minutes"], seed=seed,
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
        print(f"[family03] {name}: raw={result['n_raw_events']} dedup={result['n_dedup_events']} "
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

    summary = {
        "family": FAMILY_ID,
        "question": (
            "Does an established intraday range followed by genuine volatility/range expansion lead to "
            "abnormal subsequent directional movement? (later-session/general-session only; first 30m of RTH "
            "explicitly excluded, ORPB territory)."
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
        "total_raw_events": int(sum(d["n_raw_events"] for d in definitions_summary.values())),
        "total_dedup_events": int(sum(d["n_dedup_events"] for d in definitions_summary.values())),
    }
    (OUT_DIR / "summary.json").write_text(json.dumps(summary, indent=2, default=str), encoding="utf-8")

    md_lines = [
        "# Family 3 -- Volatility / Range Expansion -- Stage 1 Screening Summary",
        "",
        "Question: does an established intraday range followed by genuine volatility/range expansion lead to "
        "abnormal subsequent directional movement? (later-session/general-session only; first 30m of RTH "
        "explicitly excluded -- ORPB territory, out of scope.)",
        "",
        f"Data: DEVELOPMENT role, 35 symbols, 62 trading days (2026-05-15..2026-08-14). "
        f"Friction assumption: {ONE_WAY_FRICTION_BPS}bps one-way / {ROUND_TRIP_FRICTION_BPS}bps round-trip.",
        "",
        f"**Family rollup:** {rollup_text}",
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
    print(f"[family03] wrote outputs to {OUT_DIR}")


if __name__ == "__main__":
    main()
