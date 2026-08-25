"""
research/scripts/task67a_family02_structural_pullback.py
-------------------------------------------------------------
Task 67B Step 2, Family 2: STRUCTURAL PULLBACK.

Question: after a strong directional move followed by a controlled
retracement that preserves broader structure, does continuation occur
more than in matched controls? This script owns the event-CONDITION
logic for three broad definitions; all shared mechanics (dedup,
horizon/MFE-MAE, matched control, bootstrap, concentration, effect
surface, economic classification, verdict) are delegated to
research/task67a_lib/family_runner.py.

Exploratory, read-only, DEVELOPMENT-data-only phenomenon discovery -- NOT
a trading engine, NOT a backtest, NOT strategy freezing. Data access is
exclusively via research.task67a_lib.data_guard's STAGE1_DISCOVERY_GUARD
(DEVELOPMENT role only).

All three definitions are deliberately simple two-timestamp comparisons
(no full state-machine / no true peak-detection): a "prior move" measured
between two lookback offsets, and a "retracement" measured between the
more recent of those offsets and now. This is a direct, causal
approximation of "strong move, then shallow giveback" using only
`causal_price_at_offset` (and, for definition B, `causal_session_vwap`).

Definitions (see results/.../family_02_structural_pullback/spec.md):
  A) strong_move90_shallow_retrace20: prior move over t-90m..t-20m
     >= 0.6% in magnitude; retracement over t-20m..t (now) is OPPOSITE in
     sign (a genuine pullback, not a continued extension) and its
     magnitude is <= 50% of the prior move's magnitude ("shallow
     giveback" -- structure preserved).
  B) pullback_toward_vwap_holds: prior move over t-60m..t-15m >= 0.5% in
     magnitude, moving away from the causal session VWAP; price has since
     pulled back from the t-15m extreme but has NOT crossed back through
     VWAP (VWAP held as a structural reference level).
  C) strong_move45_shallow_retrace10: same shape as (A) at a coarser/
     faster timeframe -- prior move over t-45m..t-10m >= 0.4%, retracement
     over t-10m..t <= 60% of the prior move's magnitude.

Direction: sign of the prior move (this family bets on CONTINUATION after
the shallow pullback, not on the pullback itself reversing further).
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
    causal_session_vwap,
)

ROOT = Path(__file__).resolve().parents[2]
OUT_DIR = ROOT / "results/task67a_phenomenon_discovery/family_02_structural_pullback"
FAMILY_ID = "family_02_structural_pullback"
FAMILY_SEED_OFFSET = 200


def _min_lead_filter(bars_feat: pd.DataFrame, min_lead_minutes: float = 15.0) -> np.ndarray:
    close_ts = bars_feat["trading_day"] + pd.Timedelta(hours=20)
    return ((close_ts - bars_feat["timestamp"]) >= pd.Timedelta(minutes=min_lead_minutes)).to_numpy()


def _events_from_mask(bars_feat: pd.DataFrame, mask: np.ndarray, direction: np.ndarray) -> pd.DataFrame:
    cand = bars_feat.loc[mask, [
        "symbol", "timestamp", "close", "trailing_vol_60m", "time_of_day_bucket", "vol_bucket", "trading_day",
    ]].rename(columns={"close": "entry_price"}).copy()
    cand["direction"] = direction[mask]
    return cand


def _strong_move_shallow_retrace(
    bars_feat: pd.DataFrame, *, base_minutes: float, retrace_minutes: float,
    move_threshold: float, giveback_ratio_max: float,
) -> pd.DataFrame:
    p0 = causal_price_at_offset(bars_feat, 0)
    p_retrace = causal_price_at_offset(bars_feat, retrace_minutes)
    p_base = causal_price_at_offset(bars_feat, base_minutes)
    with np.errstate(divide="ignore", invalid="ignore"):
        prior_move = (p_retrace - p_base) / p_base
        giveback = (p0 - p_retrace) / p_retrace
    sign_move = np.sign(prior_move)
    sign_giveback = np.sign(giveback)
    mask = (
        (np.abs(prior_move) >= move_threshold)
        & (sign_move != 0)
        & (sign_giveback == -sign_move)  # genuine pullback, not further extension
        & (np.abs(giveback) <= giveback_ratio_max * np.abs(prior_move))
        & _min_lead_filter(bars_feat)
    )
    direction = np.where(sign_move > 0, 1, -1)
    return _events_from_mask(bars_feat, mask, direction)


def definition_a_strong_move90_shallow_retrace20(bars_feat: pd.DataFrame) -> pd.DataFrame:
    return _strong_move_shallow_retrace(
        bars_feat, base_minutes=90, retrace_minutes=20, move_threshold=0.006, giveback_ratio_max=0.5,
    )


def definition_c_strong_move45_shallow_retrace10(bars_feat: pd.DataFrame) -> pd.DataFrame:
    return _strong_move_shallow_retrace(
        bars_feat, base_minutes=45, retrace_minutes=10, move_threshold=0.004, giveback_ratio_max=0.6,
    )


def definition_b_pullback_toward_vwap_holds(
    bars_feat: pd.DataFrame, *, base_minutes: float = 60, retrace_minutes: float = 15, move_threshold: float = 0.005,
) -> pd.DataFrame:
    p0 = causal_price_at_offset(bars_feat, 0)
    p_retrace = causal_price_at_offset(bars_feat, retrace_minutes)
    p_base = causal_price_at_offset(bars_feat, base_minutes)
    vwap_now = causal_session_vwap(bars_feat)
    with np.errstate(divide="ignore", invalid="ignore"):
        prior_move = (p_retrace - p_base) / p_base
    sign_move = np.sign(prior_move)

    up_ok = (
        (sign_move > 0) & (p_retrace > vwap_now) & (p0 >= vwap_now) & (p0 < p_retrace)
    )
    down_ok = (
        (sign_move < 0) & (p_retrace < vwap_now) & (p0 <= vwap_now) & (p0 > p_retrace)
    )
    mask = (
        (np.abs(prior_move) >= move_threshold)
        & (up_ok | down_ok)
        & _min_lead_filter(bars_feat)
        & ~np.isnan(vwap_now)
    )
    direction = np.where(sign_move > 0, 1, -1)
    return _events_from_mask(bars_feat, mask, direction)


DEFINITIONS = [
    {
        "name": "strong_move90_shallow_retrace20",
        "builder": definition_a_strong_move90_shallow_retrace20,
        "dedup_group_keys": ["symbol"],
        "dedup_min_gap_minutes": 60,
        "description": (
            "Prior move over t-90m..t-20m has |return| >= 0.6%; retracement over t-20m..t (now) is OPPOSITE "
            "in sign (genuine pullback, not a continued extension) and its magnitude is <= 50% of the prior "
            "move's magnitude (shallow giveback, structure preserved). Direction = sign of the prior move "
            "(tests continuation after the pullback)."
        ),
    },
    {
        "name": "pullback_toward_vwap_holds",
        "builder": definition_b_pullback_toward_vwap_holds,
        "dedup_group_keys": ["symbol"],
        "dedup_min_gap_minutes": 45,
        "description": (
            "Prior move over t-60m..t-15m has |return| >= 0.5%, moving away from the causal session VWAP; "
            "price has since pulled back from the t-15m extreme toward VWAP but has NOT crossed back through "
            "it (VWAP held as a structural reference level). Direction = sign of the prior move."
        ),
    },
    {
        "name": "strong_move45_shallow_retrace10",
        "builder": definition_c_strong_move45_shallow_retrace10,
        "dedup_group_keys": ["symbol"],
        "dedup_min_gap_minutes": 30,
        "description": (
            "Coarser/faster-timeframe variant of definition A: prior move over t-45m..t-10m has |return| "
            ">= 0.4%; retracement over t-10m..t is opposite in sign and its magnitude is <= 60% of the prior "
            "move's magnitude. Direction = sign of the prior move."
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
        print(f"[family02] {name}: raw={result['n_raw_events']} dedup={result['n_dedup_events']} "
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
            "After a strong directional move followed by a controlled retracement that preserves broader "
            "structure, does continuation occur more than in matched controls?"
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
        "# Family 2 -- Structural Pullback -- Stage 1 Screening Summary",
        "",
        "Question: after a strong directional move followed by a controlled retracement that preserves "
        "broader structure, does continuation occur more than in matched controls?",
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
    print(f"[family02] wrote outputs to {OUT_DIR}")


if __name__ == "__main__":
    main()
