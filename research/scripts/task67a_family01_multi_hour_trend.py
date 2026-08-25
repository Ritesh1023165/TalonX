"""
research/scripts/task67a_family01_multi_hour_trend.py
--------------------------------------------------------
Task 67B Step 2, Family 1: MULTI-HOUR TREND PERSISTENCE.

Question: do stocks already exhibiting sustained multi-hour directional
structure have systematically different future return/path behavior than
matched controls? This script owns the event-CONDITION logic for three
broad definitions; all shared mechanics (dedup, horizon/MFE-MAE, matched
control, bootstrap, concentration, effect surface, economic
classification, verdict) are delegated to
research/task67a_lib/family_runner.py.

This is exploratory, read-only, DEVELOPMENT-data-only phenomenon
discovery -- NOT a trading engine, NOT a backtest, NOT strategy freezing.
Data access is exclusively via research.task67a_lib.data_guard's
STAGE1_DISCOVERY_GUARD (DEVELOPMENT role only).

Definitions (see results/.../family_01_multi_hour_trend/spec.md for the
full write-up):
  A) trend60_slope_consistent: |60m trailing return| >= 0.4% AND all
     three 20m sub-windows composing it agree in sign with the 60m trend.
  B) trend90_subwindow_agreement: |90m trailing return| >= 0.5% AND at
     least 5 of 6 constituent 15m sub-windows agree in sign with the 90m
     trend.
  C) multiwindow_agreement_30_60_90: 30m, 60m, and 90m trailing returns
     (causal_trailing_return) all share the same sign, with |90m return|
     >= 0.4%.

Direction: the sign of the defining trailing return (long if positive,
short if negative) -- this family tests CONTINUATION of an already-
observed trend, not a reversal/pullback (that is Family 2's scope).
No pullback/reclaim entry logic is implemented here per the brief.
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
    add_bar_features,
    causal_price_at_offset,
    causal_trailing_return,
    session_close_timestamp_utc,
)

ROOT = Path(__file__).resolve().parents[2]
OUT_DIR = ROOT / "results/task67a_phenomenon_discovery/family_01_multi_hour_trend"
FAMILY_ID = "family_01_multi_hour_trend"
FAMILY_SEED_OFFSET = 100  # DEFAULT_SEED + this, then +1/+2/+3 per definition, keeps bootstraps decorrelated across families/defs


def _min_lead_filter(bars_feat: pd.DataFrame, min_lead_minutes: float = 15.0) -> np.ndarray:
    """Boolean mask: True where the bar has at least `min_lead_minutes`
    of same-day room before RTH close (a light eligibility filter so
    events aren't dominated by near-close bars that barely get measured;
    compute_event_horizon_and_mfe_mae still causally bounds everything at
    session close regardless)."""
    close_ts = bars_feat["trading_day"] + pd.Timedelta(hours=20)
    return (close_ts - bars_feat["timestamp"]) >= pd.Timedelta(minutes=min_lead_minutes)


def _events_from_mask(bars_feat: pd.DataFrame, mask: np.ndarray, direction: np.ndarray) -> pd.DataFrame:
    cand = bars_feat.loc[mask, [
        "symbol", "timestamp", "close", "trailing_vol_60m", "time_of_day_bucket", "vol_bucket", "trading_day",
    ]].rename(columns={"close": "entry_price"}).copy()
    cand["direction"] = direction[mask]
    return cand


def definition_a_trend60_slope_consistent(bars_feat: pd.DataFrame, *, threshold: float = 0.004) -> pd.DataFrame:
    p0 = causal_price_at_offset(bars_feat, 0)
    p20 = causal_price_at_offset(bars_feat, 20)
    p40 = causal_price_at_offset(bars_feat, 40)
    p60 = causal_price_at_offset(bars_feat, 60)
    with np.errstate(divide="ignore", invalid="ignore"):
        ret60 = (p0 - p60) / p60
        sub1 = (p0 - p20) / p20
        sub2 = (p20 - p40) / p40
        sub3 = (p40 - p60) / p60
    sign60 = np.sign(ret60)
    mask = (
        (np.abs(ret60) >= threshold)
        & (sign60 != 0)
        & (np.sign(sub1) == sign60)
        & (np.sign(sub2) == sign60)
        & (np.sign(sub3) == sign60)
        & _min_lead_filter(bars_feat).to_numpy()
    )
    direction = np.where(sign60 > 0, 1, -1)
    return _events_from_mask(bars_feat, mask, direction)


def definition_b_trend90_subwindow_agreement(
    bars_feat: pd.DataFrame, *, threshold: float = 0.005, min_agree: int = 5,
) -> pd.DataFrame:
    offsets = [0, 15, 30, 45, 60, 75, 90]
    prices = {m: causal_price_at_offset(bars_feat, m) for m in offsets}
    with np.errstate(divide="ignore", invalid="ignore"):
        ret90 = (prices[0] - prices[90]) / prices[90]
    sign90 = np.sign(ret90)
    agree_count = np.zeros(len(bars_feat), dtype=float)
    for k in range(6):
        near, far = offsets[k], offsets[k + 1]
        with np.errstate(divide="ignore", invalid="ignore"):
            sub = (prices[near] - prices[far]) / prices[far]
        agree_count += (np.sign(sub) == sign90).astype(float)
    mask = (
        (np.abs(ret90) >= threshold)
        & (sign90 != 0)
        & (agree_count >= min_agree)
        & _min_lead_filter(bars_feat).to_numpy()
    )
    direction = np.where(sign90 > 0, 1, -1)
    return _events_from_mask(bars_feat, mask, direction)


def definition_c_multiwindow_agreement_30_60_90(bars_feat: pd.DataFrame, *, threshold: float = 0.004) -> pd.DataFrame:
    ret30 = causal_trailing_return(bars_feat, 30)
    ret60 = causal_trailing_return(bars_feat, 60)
    ret90 = causal_trailing_return(bars_feat, 90)
    sign90 = np.sign(ret90)
    mask = (
        (np.abs(ret90) >= threshold)
        & (sign90 != 0)
        & (np.sign(ret30) == sign90)
        & (np.sign(ret60) == sign90)
        & _min_lead_filter(bars_feat).to_numpy()
    )
    direction = np.where(sign90 > 0, 1, -1)
    return _events_from_mask(bars_feat, mask, direction)


DEFINITIONS = [
    {
        "name": "trend60_slope_consistent",
        "builder": definition_a_trend60_slope_consistent,
        "dedup_group_keys": ["symbol"],
        "dedup_min_gap_minutes": 60,
        "description": (
            "|60m trailing return (causal_trailing_return-equivalent via causal_price_at_offset)| >= 0.4% "
            "AND all three constituent 20m sub-windows (0-20m, 20-40m, 40-60m ago) agree in sign with the "
            "60m trend. Direction = sign of the 60m return."
        ),
    },
    {
        "name": "trend90_subwindow_agreement",
        "builder": definition_b_trend90_subwindow_agreement,
        "dedup_group_keys": ["symbol"],
        "dedup_min_gap_minutes": 90,
        "description": (
            "|90m trailing return| >= 0.5% AND at least 5 of the 6 constituent 15m sub-windows agree in "
            "sign with the 90m trend. Direction = sign of the 90m return."
        ),
    },
    {
        "name": "multiwindow_agreement_30_60_90",
        "builder": definition_c_multiwindow_agreement_30_60_90,
        "dedup_group_keys": ["symbol"],
        "dedup_min_gap_minutes": 90,
        "description": (
            "30m, 60m, and 90m trailing returns (causal_trailing_return) all share the same sign, with "
            "|90m return| >= 0.4%. Direction = shared sign."
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
        print(f"[family01] {name}: raw={result['n_raw_events']} dedup={result['n_dedup_events']} "
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
    family_rollup = (
        "PHENOMENON_PRESENT" if any(v == "PHENOMENON_PRESENT" for v in verdicts) and
        not all(v == "PHENOMENON_PRESENT" for v in verdicts) else None
    )
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
            "Do stocks already exhibiting sustained multi-hour directional structure have systematically "
            "different future return/path behavior than matched controls?"
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
        "# Family 1 -- Multi-Hour Trend Persistence -- Stage 1 Screening Summary",
        "",
        "Question: do stocks already exhibiting sustained multi-hour directional structure have "
        "systematically different future return/path behavior than matched controls?",
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
    print(f"[family01] wrote outputs to {OUT_DIR}")


if __name__ == "__main__":
    main()
