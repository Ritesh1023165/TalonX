"""
TASK 123 -- corrected-causality overnight-attention diagnostic.

Fixes Task 122's timing defect: a trigger built from session S's FINAL
daily volume cannot be acted on at S's own close (final volume is only
known once S is essentially over). Two explicitly separate tracks:

  TRACK A -- DAILY-DATA ASSOCIATION DIAGNOSTIC (non-actionable). Final
  volume on session S selects observations whose REFERENCE return is
  S.close -> next_XNYS_session.open. This is a conditional historical-
  return study, not an executable strategy or an achievable paper fill.

  TRACK B -- ACTIONABLE PRE-CLOSE CANDIDATE (feasibility + bounded test
  if existing intraday data supports it). Decision uses ONLY information
  available at a fixed pre-close cutoff; entry occurs after a stated
  delay at a subsequent OBSERVED price, explicitly labelled a reference
  fill, not a claimed executable quote.

Reuses `talonx_v2.calendar.next_session_strictly_after` (the SAME frozen
XNYS session-arithmetic module V2 uses) for calendar-correct next-session
pairing -- never "the next available row in the CSV."
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

OUT = RESEARCH_ROOT / "results" / "task123_overnight_diagnostic"
OUT.mkdir(parents=True, exist_ok=True)

# ---------------------------------------------------------------------
# Frozen parameters (Part 2) -- fixed BEFORE any return was inspected.
# ---------------------------------------------------------------------
VOLUME_LOOKBACK_SESSIONS = 20
TRIGGER_MULTIPLE_PRIMARY = 2.0
TRIGGER_MULTIPLE_SENSITIVITY = 2.5          # exact, not "e.g. 3x"
COST_BPS_ROUND_TRIP = 5.0                    # same convention as Tasks 120-122
MATERIALITY_BAND_BPS = 10.0                  # modeled 5bps + one more assumed-friction unit (Task 121B's own logic)
EXTREME_RETURN_EXCLUSION_ABS = 0.50          # |gross overnight return| > 50% -> data-quality exclusion, reported not silently dropped
BOOTSTRAP_REPS = 5000
BOOTSTRAP_SEED = 123123                      # predeclared, distinct from every prior task's seed

ACTIVE_COVERED_38 = [
    "AAPL", "ABCL", "ABT", "ACHR", "ADC", "AFL", "AGNC", "AMAT", "AMD", "AVGO", "BAC", "BLK",
    "C", "CSCO", "CVX", "DELL", "GOOGL", "IBM", "INTC", "JNJ", "JPM", "KO", "MA", "MCD", "MSFT",
    "MSTR", "NUE", "NVDA", "ORCL", "PG", "PYPL", "STX", "TSLA", "UNH", "V", "VRT", "WMT", "ADP",
]
# NOTE: 38 names, precedence d1 (task95g_daily) then d2 (task107a_prices) -- see _load_symbol.

DAILY_DIR_1 = RELEASE_ROOT / "results/task95g_broad_cross_sectional/_daily"    # precedence: checked first
DAILY_DIR_2 = RELEASE_ROOT / "results/task107a_form4_feasibility/_prices"      # fallback: only if not in DIR_1


def _load_symbol_daily(sym: str) -> tuple[pd.DataFrame | None, str]:
    """Loads one symbol's daily bars, explicit source precedence: DAILY_DIR_1
    first, DAILY_DIR_2 only if the symbol is absent from DIR_1. Empirically,
    for the configured universe, no symbol exists in both (checked and
    reported in TASK123_OVERNIGHT_ATTENTION_RESULTS.md) -- precedence is
    stated for completeness, not because a real conflict was resolved."""
    p1 = DAILY_DIR_1 / f"{sym}.csv"
    p2 = DAILY_DIR_2 / f"{sym}.csv"
    if p1.exists():
        df = pd.read_csv(p1, usecols=["date", "open", "high", "low", "close", "volume"], parse_dates=["date"])
        return df, str(p1)
    if p2.exists():
        df = pd.read_csv(p2, usecols=["date", "open", "high", "low", "close", "volume"], parse_dates=["date"])
        return df, str(p2)
    return None, "DATA_UNAVAILABLE"


def compute_track_a_symbol(sym: str) -> tuple[pd.DataFrame, dict]:
    """Returns (eligible_observations_df, exclusion_counts) for one symbol.
    eligible_observations_df columns: symbol, date, is_trigger,
    gross_return, net_return."""
    df, source = _load_symbol_daily(sym)
    exclusions = {"symbol": sym, "source": source, "no_data": df is None,
                 "duplicates": 0, "out_of_order": 0, "non_positive": 0, "negative_volume": 0,
                 "insufficient_trailing_history": 0, "missing_next_session": 0,
                 "extreme_return_excluded": 0, "eligible": 0, "triggers": 0}
    if df is None:
        return pd.DataFrame(columns=["symbol", "date", "is_trigger", "is_trigger_sensitivity_2_5x",
                                     "gross_return", "net_return"]), exclusions

    df = df.sort_values("date").reset_index(drop=True)
    exclusions["duplicates"] = int(df["date"].duplicated().sum())
    df = df.drop_duplicates(subset="date", keep="last").reset_index(drop=True)
    exclusions["out_of_order"] = int((df["date"].diff().dt.days < 0).sum())
    df = df.sort_values("date").reset_index(drop=True)  # re-sort defensively after dedup
    non_pos = ((df[["open", "high", "low", "close"]] <= 0).any(axis=1))
    neg_vol = (df["volume"] < 0)
    exclusions["non_positive"] = int(non_pos.sum())
    exclusions["negative_volume"] = int(neg_vol.sum())
    df = df[~non_pos & ~neg_vol].reset_index(drop=True)

    dates = df["date"].dt.date.tolist()
    volumes = df["volume"].to_numpy()
    closes = df["close"].to_numpy()
    opens = df["open"].to_numpy()

    rows = []
    for i in range(len(df)):
        if i < VOLUME_LOOKBACK_SESSIONS:
            exclusions["insufficient_trailing_history"] += 1
            continue
        trailing_avg = volumes[i - VOLUME_LOOKBACK_SESSIONS:i].mean()  # sessions [i-20, i-1] -- EXCLUDES session i itself
        is_trigger = bool(volumes[i] >= TRIGGER_MULTIPLE_PRIMARY * trailing_avg)
        is_trigger_sens = bool(volumes[i] >= TRIGGER_MULTIPLE_SENSITIVITY * trailing_avg)

        expected_next = next_session_strictly_after(dates[i])
        if i + 1 >= len(df) or dates[i + 1] != expected_next:
            exclusions["missing_next_session"] += 1
            continue

        gross_ret = opens[i + 1] / closes[i] - 1.0
        if abs(gross_ret) > EXTREME_RETURN_EXCLUSION_ABS:
            exclusions["extreme_return_excluded"] += 1
            continue

        net_ret = gross_ret - COST_BPS_ROUND_TRIP / 10_000.0
        exclusions["eligible"] += 1
        if is_trigger:
            exclusions["triggers"] += 1
        rows.append({"symbol": sym, "date": dates[i], "is_trigger": is_trigger,
                    "is_trigger_sensitivity_2_5x": is_trigger_sens,
                    "gross_return": gross_ret, "net_return": net_ret})
    cols = ["symbol", "date", "is_trigger", "is_trigger_sensitivity_2_5x", "gross_return", "net_return"]
    return (pd.DataFrame(rows, columns=cols) if not rows else pd.DataFrame(rows)), exclusions


def _date_block_bootstrap(obs: pd.DataFrame, *, trigger_col: str = "is_trigger") -> dict:
    """Preserves trigger/control overlap: resamples DISTINCT DATES with
    replacement (captures common cross-sectional market-shock correlation
    on shared dates), then computes BOTH the trigger-population mean and
    the full (unconditional/control) population mean from the SAME
    resampled date-multiset each replicate, and records their difference.
    Efficient O(n_dates) per replicate via precomputed per-date sums."""
    obs = obs.copy()
    obs["_trig_return"] = obs["net_return"].where(obs[trigger_col], other=np.nan)
    by_date = obs.groupby("date").agg(
        total_sum=("net_return", "sum"), total_n=("net_return", "size"),
        trig_sum=("_trig_return", lambda s: s.dropna().sum()),
        trig_n=(trigger_col, "sum"),
    )
    dates = by_date.index.to_numpy()
    total_sum = by_date["total_sum"].to_numpy()
    total_n = by_date["total_n"].to_numpy()
    trig_sum = by_date["trig_sum"].to_numpy()
    trig_n = by_date["trig_n"].to_numpy()

    rng = np.random.default_rng(BOOTSTRAP_SEED)
    n_dates = len(dates)
    diffs, trig_means, ctrl_means = [], [], []
    for _ in range(BOOTSTRAP_REPS):
        idx = rng.integers(0, n_dates, size=n_dates)
        s_total, n_total = total_sum[idx].sum(), total_n[idx].sum()
        s_trig, n_trig = trig_sum[idx].sum(), trig_n[idx].sum()
        if n_total == 0 or n_trig == 0:
            continue
        ctrl_mean = s_total / n_total
        trig_mean = s_trig / n_trig
        trig_means.append(trig_mean)
        ctrl_means.append(ctrl_mean)
        diffs.append(trig_mean - ctrl_mean)

    def _ci(vals):
        if not vals:
            return None
        return [float(np.percentile(vals, 2.5)), float(np.percentile(vals, 97.5))]

    return {
        "n_dates": n_dates, "n_reps_used": len(diffs),
        "trigger_mean_ci_pct": [round(100 * c, 4) for c in _ci(trig_means)] if trig_means else None,
        "control_mean_ci_pct": [round(100 * c, 4) for c in _ci(ctrl_means)] if ctrl_means else None,
        "incremental_diff_ci_pct": [round(100 * c, 4) for c in _ci(diffs)] if diffs else None,
        "method": "date-block bootstrap, joint resampling of trigger+control from the SAME resampled "
                 f"date multiset, {BOOTSTRAP_REPS} reps, seed {BOOTSTRAP_SEED}, 95% percentile CI",
    }


def run_track_a() -> dict:
    all_obs = []
    exclusions_by_symbol = {}
    for sym in ACTIVE_COVERED_38:
        obs, exc = compute_track_a_symbol(sym)
        exclusions_by_symbol[sym] = exc
        if len(obs):
            all_obs.append(obs)
    obs_df = pd.concat(all_obs, ignore_index=True) if all_obs else pd.DataFrame()

    n_eligible = len(obs_df)
    n_triggers = int(obs_df["is_trigger"].sum()) if n_eligible else 0
    trig = obs_df[obs_df["is_trigger"]] if n_eligible else obs_df
    ctrl = obs_df  # unconditional -- ALL eligible observations, same symbols/dates

    def _stats(s: pd.Series) -> dict:
        if len(s) == 0:
            return {"n": 0}
        return {
            "n": int(len(s)), "mean_pct": round(100 * s.mean(), 4), "median_pct": round(100 * s.median(), 4),
            "win_rate": round(float((s > 0).mean()), 4),
            "worst_5pct_mean_pct": round(100 * s.nsmallest(max(1, len(s) // 20)).mean(), 4),
        }

    trig_gross = _stats(trig["gross_return"]) if n_eligible else {"n": 0}
    trig_net = _stats(trig["net_return"]) if n_eligible else {"n": 0}
    ctrl_gross = _stats(ctrl["gross_return"]) if n_eligible else {"n": 0}
    ctrl_net = _stats(ctrl["net_return"]) if n_eligible else {"n": 0}

    by_issuer_trig_n = trig["symbol"].value_counts().to_dict() if n_eligible else {}
    top_issuer = max(by_issuer_trig_n, key=by_issuer_trig_n.get) if by_issuer_trig_n else None
    drop_top1 = None
    if top_issuer:
        no_top = trig[trig["symbol"] != top_issuer]["net_return"]
        drop_top1 = {"top_issuer": top_issuer, "top_issuer_n": by_issuer_trig_n[top_issuer],
                    "mean_all_pct": trig_net["mean_pct"], "mean_excl_top_pct":
                    round(100 * no_top.mean(), 4) if len(no_top) else None}

    # sensitivity 2: stricter trigger multiple (2.5x), same population/window
    trig_25 = obs_df[obs_df["is_trigger_sensitivity_2_5x"]] if n_eligible else obs_df
    trig_25_net = _stats(trig_25["net_return"]) if n_eligible else {"n": 0}

    bootstrap = _date_block_bootstrap(obs_df) if n_eligible else None

    exclusions_totals = {}
    for exc in exclusions_by_symbol.values():
        for k, v in exc.items():
            if isinstance(v, (int, float)):
                exclusions_totals[k] = exclusions_totals.get(k, 0) + v

    n_by_month = trig.assign(month=pd.to_datetime(trig["date"]).dt.to_period("M").astype(str)) \
        .groupby("month").size().to_dict() if n_eligible else {}

    result = {
        "track": "A_daily_association_diagnostic",
        "label": "NON-ACTIONABLE -- conditional historical-return study using session S's own "
                 "final volume; NOT an executable alert or achievable paper fill (Part 1 correction).",
        "universe": {"active_covered_n": len(ACTIVE_COVERED_38), "symbols": ACTIVE_COVERED_38},
        "trigger_definition": f"volume[S] >= {TRIGGER_MULTIPLE_PRIMARY}x mean(volume[S-20..S-1]) "
                              "(trailing 20 sessions, EXCLUDING S)",
        "return_definition": "gross = open[next_XNYS_session]/close[S] - 1; next session via "
                             "talonx_v2.calendar.next_session_strictly_after (never 'next available row')",
        "cost_convention": {"round_trip_bps": COST_BPS_ROUND_TRIP,
                           "note": "applied ONCE: net_return = gross_return - cost_bps/10000"},
        "materiality_band_bps": MATERIALITY_BAND_BPS,
        "exclusion_counts_total": exclusions_totals,
        "exclusion_counts_by_symbol": exclusions_by_symbol,
        "n_eligible_observations": n_eligible, "n_triggers": n_triggers,
        "trigger_gross_return": trig_gross, "trigger_net_return": trig_net,
        "control_unconditional_gross_return": ctrl_gross, "control_unconditional_net_return": ctrl_net,
        "incremental_diff_net_pct_mean": round(trig_net["mean_pct"] - ctrl_net["mean_pct"], 4) if n_triggers else None,
        "by_issuer_trigger_counts": by_issuer_trig_n,
        "sensitivity_drop_top1_issuer": drop_top1,
        "sensitivity_stricter_trigger_2_5x": trig_25_net,
        "trigger_counts_by_month": n_by_month,
        "uncertainty": bootstrap,
    }
    out_path = OUT / "track_a_association_summary.json"
    out_path.write_text(json.dumps(result, indent=2, default=str))
    return result


# =======================================================================
# TRACK B -- actionable pre-close candidate: feasibility + bounded test
# (only if existing intraday data supports it -- Part 5).
# =======================================================================
INTRADAY_DIR = RELEASE_ROOT / "results/task93_alpha_foundation/_canonical_data"
TRACK_B_SYMBOLS = ["AAPL", "AMAT", "AMD", "AVGO", "CSCO", "GOOGL", "INTC", "MSFT", "NVDA", "PYPL", "STX", "TSLA"]
TRACK_B_WINDOW = ("2025-01-24", "2025-08-14")  # common coverage across all 12 candidates -- no cherry-picking

# Frozen BEFORE any Track B return was computed (Part 5):
REGULAR_SESSION_OPEN_UTC = "14:30:00"     # 09:30 ET
DECISION_CUTOFF_UTC = "20:50:00"          # 15:50 ET -- 10 min before the 16:00 ET close
ALERT_DELAY_MINUTES = 2                   # decision->order-submission latency, fixed, not searched
ENTRY_OBSERVATION_UTC = "20:52:00"        # DECISION_CUTOFF_UTC + ALERT_DELAY_MINUTES, fixed


def _session_date_index(df: pd.DataFrame) -> pd.DataFrame:
    df = df.copy()
    df["ts"] = pd.to_datetime(df["timestamp"], utc=True)
    df["session_date"] = df["ts"].dt.date
    return df


def compute_track_b_symbol(sym: str) -> tuple[pd.DataFrame, dict]:
    p = INTRADAY_DIR / f"{sym}.csv"
    exc = {"symbol": sym, "no_data": not p.exists(), "missing_cutoff_bar": 0, "missing_entry_bar": 0,
          "missing_next_open_bar": 0, "insufficient_trailing_history": 0, "missing_next_session": 0,
          "extreme_return_excluded": 0, "eligible": 0, "triggers": 0}
    if not p.exists():
        return pd.DataFrame(), exc

    raw = pd.read_csv(p, parse_dates=["timestamp"])
    raw = _session_date_index(raw)
    lo, hi = pd.Timestamp(TRACK_B_WINDOW[0], tz="UTC"), pd.Timestamp(TRACK_B_WINDOW[1], tz="UTC") + pd.Timedelta(days=1)
    raw = raw[(raw["ts"] >= lo) & (raw["ts"] < hi)]

    session_dates = sorted(raw["session_date"].unique())
    # per-session cumulative volume from REGULAR OPEN through the decision cutoff (inclusive) -- never later
    cum_vol_by_cutoff: dict = {}
    cutoff_price: dict = {}
    entry_price: dict = {}
    next_open_price: dict = {}
    for d in session_dates:
        day = raw[raw["session_date"] == d]
        # the day's own opening bar is recorded UNCONDITIONALLY -- a later
        # session's own cutoff-window sparsity (if any) must never suppress
        # its role as some EARLIER session's next-open reference price.
        open_bar = day[day["ts"].dt.strftime("%H:%M:%S") == REGULAR_SESSION_OPEN_UTC]
        next_open_price[d] = float(open_bar["open"].iloc[0]) if len(open_bar) else None

        reg = day[(day["ts"].dt.strftime("%H:%M:%S") >= REGULAR_SESSION_OPEN_UTC)
                 & (day["ts"].dt.strftime("%H:%M:%S") <= DECISION_CUTOFF_UTC)]
        if len(reg) == 0:
            continue
        cum_vol_by_cutoff[d] = reg["volume"].sum()
        cutoff_bar = day[day["ts"].dt.strftime("%H:%M:%S") == DECISION_CUTOFF_UTC]
        cutoff_price[d] = float(cutoff_bar["close"].iloc[0]) if len(cutoff_bar) else None
        entry_bar = day[day["ts"].dt.strftime("%H:%M:%S") == ENTRY_OBSERVATION_UTC]
        entry_price[d] = float(entry_bar["close"].iloc[0]) if len(entry_bar) else None

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


def run_track_b() -> dict:
    all_obs, exclusions = [], {}
    for sym in TRACK_B_SYMBOLS:
        obs, exc = compute_track_b_symbol(sym)
        exclusions[sym] = exc
        if len(obs):
            all_obs.append(obs)
    obs_df = pd.concat(all_obs, ignore_index=True) if all_obs else pd.DataFrame()
    n_eligible = len(obs_df)
    n_triggers = int(obs_df["is_trigger"].sum()) if n_eligible else 0

    result = {
        "track": "B_actionable_preclose_candidate",
        "label": "Feasibility + bounded reference-fill test. Entry/exit prices are REFERENCE FILLS "
                 "(observed subsequent prices), NOT claimed executable quotes.",
        "contract": {
            "universe": TRACK_B_SYMBOLS, "window": TRACK_B_WINDOW,
            "regular_session_open_utc": REGULAR_SESSION_OPEN_UTC,
            "decision_cutoff_utc": DECISION_CUTOFF_UTC,
            "reference_volume_measure": "cumulative volume from regular-session open through the decision "
                                        "cutoff (same-time-of-day normalization), vs. trailing 20-session "
                                        "average of the SAME same-time-of-day cumulative metric",
            "alert_delay_minutes": ALERT_DELAY_MINUTES, "entry_observation_utc": ENTRY_OBSERVATION_UTC,
            "exit": "next XNYS session's regular-open 1-min bar (reference fill)",
            "cost_bps_round_trip": COST_BPS_ROUND_TRIP,
        },
        "exclusion_counts_by_symbol": exclusions,
        "n_eligible_observations": n_eligible, "n_triggers": n_triggers,
    }
    if n_eligible:
        trig = obs_df[obs_df["is_trigger"]]
        ctrl = obs_df
        result["trigger_net_return_mean_pct"] = round(100 * trig["net_return"].mean(), 4) if len(trig) else None
        result["control_net_return_mean_pct"] = round(100 * ctrl["net_return"].mean(), 4)
        result["incremental_diff_pct"] = (round(100 * (trig["net_return"].mean() - ctrl["net_return"].mean()), 4)
                                          if len(trig) else None)
        result["uncertainty"] = _date_block_bootstrap(obs_df) if len(trig) else None
        result["trade_table"] = obs_df.to_dict(orient="records")
    out_path = OUT / "track_b_actionable_summary.json"
    out_path.write_text(json.dumps(result, indent=2, default=str))
    return result


if __name__ == "__main__":
    r = run_track_a()
    print(json.dumps({k: v for k, v in r.items() if k not in
                      ("exclusion_counts_by_symbol", "by_issuer_trigger_counts", "trigger_counts_by_month")},
                     indent=2, default=str))
    print("\n\n=== TRACK B ===")
    rb = run_track_b()
    print(json.dumps({k: v for k, v in rb.items() if k not in ("exclusion_counts_by_symbol", "trade_table")},
                     indent=2, default=str))
