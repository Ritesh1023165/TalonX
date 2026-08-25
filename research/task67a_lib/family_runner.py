"""
research/task67a_lib/family_runner.py
--------------------------------------
Shared, FAMILY-AGNOSTIC orchestration for Task 67B Step 2 (families 1-3:
multi-hour trend persistence, structural pullback, volatility/range
expansion). Each family script (research/scripts/task67a_family0{1,2,3}_
*.py) builds its own boolean event-CONDITION masks off `add_bar_features`
output and calls `run_family_definition` here for the shared mechanics:
de-duplication, forward-horizon + MFE/MAE application, matched-control
construction and time-paired excess computation, clustered bootstrap CIs,
concentration, broad effect-surface stability check, economic
classification, data-sufficiency labeling, and verdict determination --
all composed from already-tested `research_stats.py` /
`screening_framework.py` primitives (imported, never reimplemented).

This module never defines an event CONDITION itself (no RSI/trend/
pullback/range logic here) and never writes files -- it returns plain
dict/DataFrame results; the calling family script decides how to combine
~3 definitions' results into one family-level events.csv /
horizon_metrics.csv / etc. and how to render spec.md / summary.md.
"""
from __future__ import annotations

from dataclasses import asdict
from typing import Sequence

import numpy as np
import pandas as pd

from research.task67a_lib.research_stats import (
    DEFAULT_SEED,
    bootstrap_ci_clustered,
    concentration_metrics,
    dedup_events,
    effect_surface,
    matched_control_sample,
)
from research.task67a_lib.screening_framework import (
    DEFAULT_HORIZONS_MINUTES,
    ROUND_TRIP_FRICTION_BPS,
    VerdictInputs,
    classify_economic_magnitude,
    compute_event_horizon_and_mfe_mae,
    data_sufficiency_label,
    determine_verdict,
    sample_control_candidates,
)

TOTAL_TRADING_DAYS = 62
TOTAL_SYMBOLS = 35

#: Thresholds used by every family/definition's VerdictInputs construction
#: below (documented once here rather than re-derived per family so the
#: taxonomy is applied consistently -- see each threshold's inline comment
#: for rationale). None of these are per-family-tuned; they are broad,
#: round, and set BEFORE looking at any family's results.
MIN_COMMON_SUPPORT_PER_SIDE = 10  # matched_control_support needs >=10 events AND >=10 controls in common support
TEMPORAL_BREADTH_FRACTION = 0.20  # >=20% of the 62-day DEVELOPMENT window
SYMBOL_BREADTH_FRACTION = 0.20  # >=20% of the 35-symbol universe
CONCENTRATION_SHARE_LIMIT = 0.40  # matches data_sufficiency_label's own concentration flag
MFE_MAE_ASYMMETRY_RATIO_BAND = (0.8, 1.2)  # outside this band on |mfe|/|mae| counts as "asymmetric"
COHERENT_DIRECTION_MIN_AGREEMENT = 0.75  # >=75% of horizons must share the primary horizon's excess sign


def _direction_sign(direction) -> int:
    return -1 if direction in (-1, "short", "SHORT") else 1


def _effect_surface_instability(surface: pd.DataFrame, *, min_n: int = 5) -> tuple[bool, str]:
    """Broad instability heuristic for `research_stats.effect_surface`
    output: flags EFFECT_SURFACE_INSTABILITY if either (a) fewer than half
    of the adequately-populated cells (n >= min_n) share the OVERALL
    (population-weighted) sign, or (b) one populated cell's |mean| is more
    than 3x the median |mean| of the other populated cells (an isolated
    spike driving the aggregate rather than a broadly-shared effect).
    Deliberately coarse -- this is a sanity check against "found on one
    exact bucket combination", not a search for the best bucket."""
    valid = surface[(surface["n"] >= min_n) & surface["mean"].notna()]
    if len(valid) < 2:
        return False, f"Only {len(valid)} populated cell(s) with n>={min_n}; too few to assess stability, not flagged."
    weights = valid["n"].to_numpy(dtype=float)
    means = valid["mean"].to_numpy(dtype=float)
    overall = float(np.average(means, weights=weights))
    overall_sign = np.sign(overall) if overall != 0 else 1.0
    same_sign_frac = float((np.sign(means) == overall_sign).mean())
    abs_means = np.abs(means)
    median_abs = float(np.median(abs_means))
    max_abs = float(np.max(abs_means))
    isolated_spike = median_abs > 0 and max_abs > 3 * median_abs
    unstable = same_sign_frac < 0.5 or isolated_spike
    reason = (
        f"{len(valid)} populated cells (n>={min_n}): same_sign_frac={same_sign_frac:.2f} "
        f"(overall sign={'+' if overall_sign > 0 else '-'}), max|mean|/median|mean|="
        f"{(max_abs / median_abs if median_abs > 0 else float('nan')):.2f}."
    )
    return unstable, reason


def build_control_events_from_pairs(
    pairs: pd.DataFrame,
    events_idx: pd.DataFrame,
    control_reset: pd.DataFrame,
    combined: pd.DataFrame,
) -> pd.DataFrame:
    """From `matched_control_sample`'s `nearest_time_pairs` (whose
    treatment_index/control_index are row-label indices into `combined`,
    the df actually passed to matched_control_sample), reconstructs a
    "control events" table with the SAME direction as its matched
    treatment event (a control bar has no direction of its own -- it
    borrows its paired event's, so the excess computation below is a
    like-for-like, direction-consistent comparison), entry_price = the
    control bar's own close, risk_per_unit = the control bar's own
    trailing_vol_60m. `events_idx`/`control_reset` must be the same
    frames (with `_pos` integer-position columns) used to build
    `combined`.
    """
    if pairs.empty:
        return pd.DataFrame(columns=[
            "event_id", "paired_event_id", "symbol", "timestamp", "entry_price",
            "direction", "risk_per_unit", "abs_time_diff_minutes",
        ])
    ev_pos = combined.loc[pairs["treatment_index"], "_pos"].to_numpy()
    ctrl_pos = combined.loc[pairs["control_index"], "_pos"].to_numpy()
    matched_events = events_idx.iloc[ev_pos].reset_index(drop=True)
    matched_controls = control_reset.iloc[ctrl_pos].reset_index(drop=True)
    return pd.DataFrame({
        "event_id": [f"ctrl_{i:06d}" for i in range(len(matched_controls))],
        "paired_event_id": matched_events["event_id"].to_numpy(),
        "symbol": matched_controls["symbol"].to_numpy(),
        "timestamp": matched_controls["timestamp"].to_numpy(),
        "entry_price": matched_controls["close"].to_numpy(dtype=float),
        "direction": matched_events["direction"].to_numpy(),
        "risk_per_unit": matched_controls["trailing_vol_60m"].fillna(0.0).to_numpy(dtype=float),
        "abs_time_diff_minutes": pairs["abs_time_diff_minutes"].to_numpy(),
    })


def run_family_definition(
    *,
    bars: pd.DataFrame,
    bars_feat: pd.DataFrame,
    candidate_events: pd.DataFrame,
    definition_name: str,
    dedup_group_keys: Sequence[str],
    dedup_min_gap_minutes: float,
    horizons_minutes: Sequence[int] = DEFAULT_HORIZONS_MINUTES,
    primary_horizon_minutes: int = 60,
    control_stride_minutes: int = 20,
    control_exclusion_buffer_minutes: float = 60.0,
    control_warmup_minutes: float = 90.0,
    control_min_lead_minutes: float = 15.0,
    match_keys: Sequence[str] = ("symbol", "time_of_day_bucket", "vol_bucket"),
    effect_surface_param_cols: Sequence[str] = ("trailing_vol_60m", "minutes_of_day"),
    seed: int = DEFAULT_SEED,
    econ_friction_bps: float = ROUND_TRIP_FRICTION_BPS,
) -> dict:
    """Runs the full shared screening pipeline for ONE definition of ONE
    family. `candidate_events` (the RAW, un-deduplicated candidate table,
    one row per bar satisfying the definition's condition) must have
    columns: symbol, timestamp, entry_price, direction, trading_day,
    time_of_day_bucket, vol_bucket, trailing_vol_60m (all sourced straight
    off `bars_feat`, i.e. the row-set the family script's boolean
    condition mask selected). Returns a dict with every DataFrame/scalar a
    family script needs to assemble its combined per-family CSVs and
    summary.json -- see module docstring; nothing is written to disk here.
    """
    n_raw = len(candidate_events)
    result: dict = {"definition_name": definition_name, "n_raw_events": n_raw}

    if n_raw == 0:
        empty = pd.DataFrame()
        vi = VerdictInputs(
            coherent_direction=False, matched_control_support=False, nontrivial_economic_scale=False,
            adequate_event_count=False, temporal_breadth=False, symbol_breadth=False,
            stable_effect_surface=False, asymmetric_mfe_mae=False, concentration_low=True,
            excess_ci_excludes_zero=False, data_sufficiency="SEVERELY_LIMITED",
        )
        verdict, reasoning = determine_verdict(vi)
        result.update(
            n_dedup_events=0, n_symbols=0, n_days=0, events_df=empty, horizon_metrics_df=empty,
            control_metrics_df=empty, mfe_mae_df=empty, concentration={"insufficient_n": True, "n_rows": 0},
            effect_surface_df=empty, per_horizon={}, economic_classification="INSUFFICIENT_DATA",
            data_sufficiency="SEVERELY_LIMITED", verdict=verdict, verdict_reasoning=reasoning,
            verdict_inputs=asdict(vi), main_weakness="Zero raw candidate events fired for this definition.",
        )
        return result

    deduped = dedup_events(
        candidate_events.reset_index(drop=True), group_keys=list(dedup_group_keys),
        time_col="timestamp", min_gap_minutes=dedup_min_gap_minutes,
    )
    deduped["_cluster_size"] = deduped.groupby(list(dedup_group_keys) + ["_cluster_id"])["_cluster_id"].transform("size")
    events = deduped[deduped["_cluster_representative"]].copy().reset_index(drop=True)
    events["event_id"] = [f"{definition_name}_{i:06d}" for i in range(len(events))]
    events["risk_per_unit"] = events["trailing_vol_60m"].fillna(0.0)
    n_dedup = len(events)
    n_symbols = int(events["symbol"].nunique())
    n_days = int(events["trading_day"].nunique())
    result.update(n_dedup_events=n_dedup, n_symbols=n_symbols, n_days=n_days)

    horizon_metrics, mfe_mae = compute_event_horizon_and_mfe_mae(
        bars, events, horizons_minutes=horizons_minutes,
        entry_price_col="entry_price", direction_col="direction", risk_col="risk_per_unit",
    )
    result["events_df"] = events
    result["horizon_metrics_df"] = horizon_metrics
    result["mfe_mae_df"] = mfe_mae

    control_pool = sample_control_candidates(
        bars_feat, events, stride_minutes=control_stride_minutes,
        exclusion_buffer_minutes=control_exclusion_buffer_minutes,
        warmup_minutes=control_warmup_minutes, min_lead_minutes=control_min_lead_minutes,
        seed=seed,
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
    common_support = mc["common_support_counts"]

    control_events = build_control_events_from_pairs(pairs, events_idx, control_reset, combined)
    if len(control_events):
        control_horizon_metrics, control_mfe_mae = compute_event_horizon_and_mfe_mae(
            bars, control_events, horizons_minutes=horizons_minutes,
            entry_price_col="entry_price", direction_col="direction", risk_col="risk_per_unit",
        )
    else:
        control_horizon_metrics, control_mfe_mae = pd.DataFrame(), pd.DataFrame()
    result["control_metrics_df"] = control_horizon_metrics

    per_horizon: dict = {}
    for h in horizons_minutes:
        label = f"{h}m"
        ev_h = horizon_metrics[horizon_metrics["horizon_minutes"] == h]
        raw_mean = float(ev_h["forward_return_signed_pct"].mean()) if ev_h["forward_return_signed_pct"].notna().any() else None
        raw_median = float(ev_h["forward_return_signed_pct"].median()) if ev_h["forward_return_signed_pct"].notna().any() else None
        pos_freq = float((ev_h["forward_return_signed_pct"] > 0).mean()) if ev_h["forward_return_signed_pct"].notna().any() else None

        ctrl_h = control_horizon_metrics[control_horizon_metrics["horizon_minutes"] == h] if len(control_horizon_metrics) else pd.DataFrame()
        merged = pd.DataFrame()
        control_mean = None
        excess_mean = None
        boot = None
        if len(ctrl_h) and len(control_events):
            paired_map = control_events.set_index("event_id")["paired_event_id"]
            ctrl_h = ctrl_h.copy()
            ctrl_h["paired_event_id"] = ctrl_h["event_id"].map(paired_map)
            merged = ev_h.merge(
                ctrl_h, left_on="event_id", right_on="paired_event_id", suffixes=("_ev", "_ctrl"),
            )
            merged = merged.dropna(subset=["forward_return_signed_pct_ev", "forward_return_signed_pct_ctrl"])
            if len(merged):
                diffs = (merged["forward_return_signed_pct_ev"] - merged["forward_return_signed_pct_ctrl"]).to_numpy(dtype=float)
                symbols_for_diff = merged["symbol_ev"].to_numpy()
                control_mean = float(ctrl_h["forward_return_signed_pct"].mean()) if ctrl_h["forward_return_signed_pct"].notna().any() else None
                excess_mean = float(np.mean(diffs))
                boot = bootstrap_ci_clustered(diffs, symbols_for_diff, seed=seed + h)

        per_horizon[label] = {
            "horizon_minutes": h,
            "n_events": int(len(ev_h)),
            "n_matched_pairs": int(len(merged)),
            "raw_mean_pct": raw_mean,
            "raw_median_pct": raw_median,
            "positive_return_freq": pos_freq,
            "matched_control_mean_pct": control_mean,
            "excess_mean_pct": excess_mean,
            "excess_bootstrap_clustered": boot.as_dict() if boot is not None else None,
        }
    result["per_horizon"] = per_horizon

    primary_label = f"{primary_horizon_minutes}m"
    max_h = max(horizons_minutes)
    max_label = f"{max_h}m"
    ev_max = horizon_metrics[horizon_metrics["horizon_minutes"] == max_h]
    mfe_pct_median = float(ev_max["favorable_excursion_pct"].median()) if len(ev_max) and ev_max["favorable_excursion_pct"].notna().any() else None
    mae_pct_median = float(ev_max["adverse_excursion_pct"].median()) if len(ev_max) and ev_max["adverse_excursion_pct"].notna().any() else None

    excess_primary = per_horizon.get(primary_label, {}).get("excess_mean_pct")
    econ_class = classify_economic_magnitude(excess_primary, mfe_pct_median, round_trip_friction_bps=econ_friction_bps)
    result["economic_classification"] = econ_class
    result["mfe_pct_median"] = mfe_pct_median
    result["mae_pct_median"] = mae_pct_median

    ev_primary_day = horizon_metrics[horizon_metrics["horizon_minutes"] == primary_horizon_minutes].merge(
        events[["event_id", "trading_day"]], on="event_id", how="left",
    )
    concentration = concentration_metrics(
        ev_primary_day, value_col="forward_return_signed_pct", symbol_col="symbol", day_col="trading_day",
    )
    result["concentration"] = concentration

    events_for_surface = events.copy()
    events_for_surface["minutes_of_day"] = (
        pd.to_datetime(events_for_surface["timestamp"]).dt.hour * 60
        + pd.to_datetime(events_for_surface["timestamp"]).dt.minute
    )
    surface_cols = ["event_id"] + [
        c for c in effect_surface_param_cols
        if c in events_for_surface.columns and c not in horizon_metrics.columns
    ]
    surface_input = horizon_metrics[horizon_metrics["horizon_minutes"] == primary_horizon_minutes].merge(
        events_for_surface[surface_cols], on="event_id", how="left",
    )
    surface_df = effect_surface(surface_input, list(effect_surface_param_cols), "forward_return_signed_pct")
    result["effect_surface_df"] = surface_df
    instability, instability_reason = _effect_surface_instability(surface_df)
    result["effect_surface_instability"] = instability
    result["effect_surface_instability_reason"] = instability_reason

    top1_share = concentration.get("top1_symbol_share") if not concentration.get("insufficient_n") else None
    best_day_share = concentration.get("best_day_share") if not concentration.get("insufficient_n") else None
    data_suff = data_sufficiency_label(
        n_events=n_dedup, n_symbols=n_symbols, n_days=n_days,
        total_trading_days=TOTAL_TRADING_DAYS, total_symbols=TOTAL_SYMBOLS,
        top1_symbol_share=top1_share, best_day_share=best_day_share,
    )
    result["data_sufficiency"] = data_suff

    # --- VerdictInputs ---
    excess_by_h = {h: per_horizon[f"{h}m"]["excess_mean_pct"] for h in horizons_minutes}
    valid_excess = {h: v for h, v in excess_by_h.items() if v is not None and v != 0}
    if excess_primary is not None and excess_primary != 0 and valid_excess:
        primary_sign = np.sign(excess_primary)
        agree_frac = float(np.mean([np.sign(v) == primary_sign for v in valid_excess.values()]))
        coherent_direction = agree_frac >= COHERENT_DIRECTION_MIN_AGREEMENT
    else:
        coherent_direction = False

    matched_control_support = (
        common_support["treatment_in_common_support"] >= MIN_COMMON_SUPPORT_PER_SIDE
        and common_support["control_in_common_support"] >= MIN_COMMON_SUPPORT_PER_SIDE
    )
    nontrivial_economic_scale = econ_class in ("POTENTIALLY_TRADEABLE", "STRONG_EFFECT")
    adequate_event_count = data_suff in ("ADEQUATE", "LIMITED")
    temporal_breadth = n_days >= TEMPORAL_BREADTH_FRACTION * TOTAL_TRADING_DAYS
    symbol_breadth = n_symbols >= SYMBOL_BREADTH_FRACTION * TOTAL_SYMBOLS
    stable_effect_surface = not instability

    if mfe_pct_median is not None and mae_pct_median is not None and mae_pct_median != 0:
        ratio = abs(mfe_pct_median) / abs(mae_pct_median) if mae_pct_median != 0 else None
        asymmetric_mfe_mae = ratio is not None and not (MFE_MAE_ASYMMETRY_RATIO_BAND[0] <= ratio <= MFE_MAE_ASYMMETRY_RATIO_BAND[1])
    else:
        asymmetric_mfe_mae = False

    if concentration.get("insufficient_n"):
        concentration_low = True
    else:
        concentration_low = not (
            (top1_share is not None and top1_share > CONCENTRATION_SHARE_LIMIT)
            or (best_day_share is not None and best_day_share > CONCENTRATION_SHARE_LIMIT)
        )

    boot_primary = per_horizon.get(primary_label, {}).get("excess_bootstrap_clustered")
    if boot_primary and not boot_primary.get("insufficient_n") and boot_primary.get("ci_low") is not None:
        lo, hi = boot_primary["ci_low"], boot_primary["ci_high"]
        excess_ci_excludes_zero = (lo > 0 and hi > 0) or (lo < 0 and hi < 0)
    else:
        excess_ci_excludes_zero = False

    vi = VerdictInputs(
        coherent_direction=coherent_direction,
        matched_control_support=matched_control_support,
        nontrivial_economic_scale=nontrivial_economic_scale,
        adequate_event_count=adequate_event_count,
        temporal_breadth=temporal_breadth,
        symbol_breadth=symbol_breadth,
        stable_effect_surface=stable_effect_surface,
        asymmetric_mfe_mae=asymmetric_mfe_mae,
        concentration_low=concentration_low,
        excess_ci_excludes_zero=excess_ci_excludes_zero,
        data_sufficiency=data_suff,
    )
    verdict, reasoning = determine_verdict(vi)
    result["verdict"] = verdict
    result["verdict_reasoning"] = reasoning
    result["verdict_inputs"] = asdict(vi)

    failed = [k for k, v in asdict(vi).items() if k != "data_sufficiency" and v is False]
    result["main_weakness"] = (
        ("Checks failing: " + ", ".join(failed)) if failed else "No individual checklist items failed."
    )

    return result
