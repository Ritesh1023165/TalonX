"""
TASK 125 Part 5 -- ONE frozen evaluation of Task 123 Track B's actionable
pre-close contract over the extended, feed-verified SIP dataset acquired
by task125_acquire_intraday.py / merged by task125_merge_and_validate.py.

Reuses task123_overnight_diagnostic.py's per-symbol transformation
(compute_track_b_symbol) and uncertainty method (_date_block_bootstrap)
UNCHANGED -- only the INPUT DIRECTORY and WINDOW differ per cohort. No
strategy parameter is touched. This is a fixed-cutoff, per-session
reduction over 1-min bars -- the same vectorized/per-session pandas
transformation Task 123 already used, not a QuantScanner replay.

Cohorts (frozen in docs/research/TASK125_FROZEN_EXTENSION_PROTOCOL.md,
BEFORE this script was run against real returns):
  A. Original 12 symbols, expanded window (2023-01-01 warmup-adjusted -> 2025-08-14), verified SIP.
  B. Added cohort (BABA, SHOP, SPCX), SAME expanded window, SAME SIP source.
  C. Combined A+B population -- SECONDARY, per the frozen protocol.
  D. Original 12 symbols, ORIGINAL Task 123 sub-window (2025-01-24 -> 2025-08-14),
     using this task's own verified-SIP data -- isolates feed-related
     differences from Task 123's original (legacy-file) result.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd

RELEASE_ROOT = Path("C:/workspace/TalonX")
sys.path.insert(0, str(RELEASE_ROOT))
RESEARCH_ROOT = Path(__file__).resolve().parents[2]

from talonx_v2.calendar import next_session_strictly_after  # noqa: E402

# Reuse Task 123's frozen constants + bootstrap UNCHANGED (same module, same file).
sys.path.insert(0, str(RESEARCH_ROOT / "research" / "scripts"))
from task123_overnight_diagnostic import (  # noqa: E402
    VOLUME_LOOKBACK_SESSIONS, TRIGGER_MULTIPLE_PRIMARY, COST_BPS_ROUND_TRIP,
    MATERIALITY_BAND_BPS, EXTREME_RETURN_EXCLUSION_ABS, REGULAR_SESSION_OPEN_UTC,
    DECISION_CUTOFF_UTC, ALERT_DELAY_MINUTES, ENTRY_OBSERVATION_UTC,
    _date_block_bootstrap,
)

OUT = RESEARCH_ROOT / "results" / "task125_intraday_extension"
MERGED = OUT / "_merged"
LEGACY_DIR = RELEASE_ROOT / "results/task93_alpha_foundation/_canonical_data"  # Cohort D-legacy comparison only

SYMBOLS_ORIGINAL_12 = ["AAPL", "AMAT", "AMD", "AVGO", "CSCO", "GOOGL", "INTC", "MSFT", "NVDA", "PYPL", "STX", "TSLA"]
SYMBOLS_ADDED = ["BABA", "SHOP", "SPCX"]

EXPANDED_WINDOW = ("2022-12-01", "2025-08-14")  # acquisition range; eligibility naturally warms up ~20 sessions in
ORIGINAL_SUBWINDOW = ("2025-01-24", "2025-08-14")  # Task 123's own original Track B window


def _session_date_index(df: pd.DataFrame) -> pd.DataFrame:
    df = df.copy()
    df["ts"] = pd.to_datetime(df["timestamp"], utc=True)
    df["session_date"] = df["ts"].dt.date
    return df


def compute_symbol(sym: str, *, data_dir: Path, window: tuple[str, str]) -> tuple[pd.DataFrame, dict]:
    """Identical logic to task123_overnight_diagnostic.compute_track_b_symbol,
    parameterized by data_dir/window so the SAME transformation can be run
    against this task's newly acquired SIP data for any cohort/window."""
    p = data_dir / f"{sym}.csv"
    exc = {"symbol": sym, "no_data": not p.exists(), "missing_cutoff_bar": 0, "missing_entry_bar": 0,
          "missing_next_open_bar": 0, "insufficient_trailing_history": 0, "missing_next_session": 0,
          "extreme_return_excluded": 0, "eligible": 0, "triggers": 0}
    if not p.exists():
        return pd.DataFrame(), exc

    raw = pd.read_csv(p, parse_dates=["timestamp"])
    raw = _session_date_index(raw)
    lo, hi = pd.Timestamp(window[0], tz="UTC"), pd.Timestamp(window[1], tz="UTC") + pd.Timedelta(days=1)
    raw = raw[(raw["ts"] >= lo) & (raw["ts"] < hi)]
    if len(raw) == 0:
        exc["no_data"] = True
        return pd.DataFrame(), exc

    # ONE vectorized pass over the whole frame instead of re-filtering it
    # per session date (the naive per-date boolean mask was O(n_dates *
    # n_rows) -- with ~700 dates x ~500k rows/symbol that is ~350M row
    # comparisons per symbol, the actual bottleneck on the expanded
    # window). time-of-day string is computed once; open/entry bars are
    # located by an indexed lookup, and the cutoff-window cumulative
    # volume is a single groupby().sum() over a boolean-masked slice.
    hms = raw["ts"].dt.strftime("%H:%M:%S")
    reg_mask = (hms >= REGULAR_SESSION_OPEN_UTC) & (hms <= DECISION_CUTOFF_UTC)
    cum_vol_by_cutoff = raw.loc[reg_mask].groupby("session_date")["volume"].sum().to_dict()

    open_bars = raw.loc[hms == REGULAR_SESSION_OPEN_UTC].drop_duplicates("session_date", keep="first")
    next_open_price = dict(zip(open_bars["session_date"], open_bars["open"].astype(float)))

    entry_bars = raw.loc[hms == ENTRY_OBSERVATION_UTC].drop_duplicates("session_date", keep="first")
    entry_price = dict(zip(entry_bars["session_date"], entry_bars["close"].astype(float)))

    session_dates = sorted(raw["session_date"].unique())

    rows = []
    for i, d in enumerate(session_dates):
        if d not in cum_vol_by_cutoff:
            continue
        if i < VOLUME_LOOKBACK_SESSIONS:
            exc["insufficient_trailing_history"] += 1
            continue
        trailing_vals = [cum_vol_by_cutoff[session_dates[j]] for j in range(i - VOLUME_LOOKBACK_SESSIONS, i)
                         if session_dates[j] in cum_vol_by_cutoff]
        if len(trailing_vals) < VOLUME_LOOKBACK_SESSIONS:
            exc["insufficient_trailing_history"] += 1
            continue
        trailing_avg = sum(trailing_vals) / len(trailing_vals)
        is_trigger = cum_vol_by_cutoff[d] >= TRIGGER_MULTIPLE_PRIMARY * trailing_avg

        entry_px = entry_price.get(d)
        if entry_px is None:
            exc["missing_entry_bar"] += 1
            continue

        expected_next = next_session_strictly_after(d)
        if expected_next not in next_open_price or next_open_price[expected_next] is None:
            exc["missing_next_session"] += 1
            continue

        gross_ret = next_open_price[expected_next] / entry_px - 1.0
        if abs(gross_ret) > EXTREME_RETURN_EXCLUSION_ABS:
            exc["extreme_return_excluded"] += 1
            continue
        net_ret = gross_ret - COST_BPS_ROUND_TRIP / 10_000.0
        exc["eligible"] += 1
        if is_trigger:
            exc["triggers"] += 1
        rows.append({"symbol": sym, "date": d, "is_trigger": bool(is_trigger),
                    "gross_return": gross_ret, "net_return": net_ret,
                    "entry_price_reference_fill": entry_px, "exit_price_reference_fill": next_open_price[expected_next]})

    cols = ["symbol", "date", "is_trigger", "gross_return", "net_return",
           "entry_price_reference_fill", "exit_price_reference_fill"]
    return (pd.DataFrame(rows, columns=cols) if not rows else pd.DataFrame(rows)), exc


def _cohort_stats(s: pd.Series) -> dict:
    if len(s) == 0:
        return {"n": 0}
    return {
        "n": int(len(s)), "mean_pct": round(100 * s.mean(), 4), "median_pct": round(100 * s.median(), 4),
        "win_rate": round(float((s > 0).mean()), 4),
        "worst_5pct_mean_pct": round(100 * s.nsmallest(max(1, len(s) // 20)).mean(), 4),
    }


def run_cohort(name: str, symbols: list[str], *, data_dir: Path, window: tuple[str, str]) -> dict:
    all_obs, exclusions = [], {}
    for sym in symbols:
        obs, exc = compute_symbol(sym, data_dir=data_dir, window=window)
        exclusions[sym] = exc
        if len(obs):
            all_obs.append(obs)
    obs_df = pd.concat(all_obs, ignore_index=True) if all_obs else pd.DataFrame()
    n_eligible = len(obs_df)
    n_triggers = int(obs_df["is_trigger"].sum()) if n_eligible else 0

    result = {
        "cohort": name, "symbols": symbols, "window": window, "data_dir": str(data_dir),
        "exclusion_counts_by_symbol": exclusions,
        "n_eligible_observations": n_eligible, "n_triggers": n_triggers,
        "n_distinct_issuers_triggered": int(obs_df[obs_df["is_trigger"]]["symbol"].nunique()) if n_triggers else 0,
        "n_distinct_dates_triggered": int(obs_df[obs_df["is_trigger"]]["date"].nunique()) if n_triggers else 0,
    }
    if n_eligible:
        trig = obs_df[obs_df["is_trigger"]]
        ctrl = obs_df
        result["trigger_gross_return"] = _cohort_stats(trig["gross_return"])
        result["trigger_net_return"] = _cohort_stats(trig["net_return"])
        result["control_unconditional_gross_return"] = _cohort_stats(ctrl["gross_return"])
        result["control_unconditional_net_return"] = _cohort_stats(ctrl["net_return"])
        result["incremental_diff_net_pct_mean"] = (
            round(result["trigger_net_return"]["mean_pct"] - result["control_unconditional_net_return"]["mean_pct"], 4)
            if n_triggers else None)
        by_issuer = trig["symbol"].value_counts().to_dict() if n_triggers else {}
        result["by_issuer_trigger_counts"] = by_issuer
        if by_issuer:
            top = max(by_issuer, key=by_issuer.get)
            no_top = trig[trig["symbol"] != top]["net_return"]
            result["concentration_top1_issuer"] = {
                "issuer": top, "issuer_trigger_n": by_issuer[top],
                "share_of_triggers": round(by_issuer[top] / n_triggers, 4),
                "mean_net_pct_excl_top1": round(100 * no_top.mean(), 4) if len(no_top) else None,
            }
        if n_triggers:
            by_year = trig.assign(year=pd.to_datetime(trig["date"]).dt.year).groupby("year").agg(
                n=("net_return", "size"), mean_net_pct=("net_return", lambda s: round(100 * s.mean(), 4))
            ).to_dict(orient="index")
            result["trigger_by_year"] = {str(k): v for k, v in by_year.items()}
        result["uncertainty"] = _date_block_bootstrap(obs_df) if n_triggers else None
    exclusions_totals = {}
    for exc in exclusions.values():
        for k, v in exc.items():
            if isinstance(v, (int, float)):
                exclusions_totals[k] = exclusions_totals.get(k, 0) + v
    result["exclusion_counts_total"] = exclusions_totals
    return result


def main() -> int:
    cohorts = {}
    cohorts["A_original12_expanded"] = run_cohort(
        "A_original12_expanded", SYMBOLS_ORIGINAL_12, data_dir=MERGED, window=EXPANDED_WINDOW)
    cohorts["B_added_cohort"] = run_cohort(
        "B_added_cohort", SYMBOLS_ADDED, data_dir=MERGED, window=EXPANDED_WINDOW)
    cohorts["C_combined_secondary"] = run_cohort(
        "C_combined_secondary", SYMBOLS_ORIGINAL_12 + SYMBOLS_ADDED, data_dir=MERGED, window=EXPANDED_WINDOW)
    cohorts["D_original_subwindow_verified_sip"] = run_cohort(
        "D_original_subwindow_verified_sip", SYMBOLS_ORIGINAL_12, data_dir=MERGED, window=ORIGINAL_SUBWINDOW)

    out_path = OUT / "task125_evaluation_results.json"
    out_path.write_text(json.dumps(cohorts, indent=2, default=str))

    for name, r in cohorts.items():
        print(f"\n=== {name} ===")
        print(f"  eligible={r['n_eligible_observations']}  triggers={r['n_triggers']}  "
             f"issuers={r.get('n_distinct_issuers_triggered')}  dates={r.get('n_distinct_dates_triggered')}")
        if r["n_triggers"]:
            print(f"  trigger_net_mean={r['trigger_net_return']['mean_pct']}%  "
                 f"control_net_mean={r['control_unconditional_net_return']['mean_pct']}%  "
                 f"incremental={r['incremental_diff_net_pct_mean']}%")
            if r.get("uncertainty"):
                print(f"  incremental_95ci={r['uncertainty']['incremental_diff_ci_pct']}")
    print(f"\nwrote {out_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
