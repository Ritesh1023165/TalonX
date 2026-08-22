"""
Task 20 -- Trade Excursion & Reversal Anatomy.

DIAGNOSTIC ONLY. Walks raw 1-minute bars from entry to exit for all 181
trades, converts every bar to direction-adjusted R units using each
trade's ORIGINAL initial risk (risk_dollars_per_share, the same
denominator gross_R itself uses), and characterizes post-entry path
behavior: excursion landmarks, STOP reversal anatomy, winner retracement,
breakeven crossings, and descriptive path-shape classes.

No stop/target/trailing logic is altered or simulated -- this only reads
raw historical bars for trades that already happened and recomputes
running MFE/MAE from them.

Deterministic, no randomness.
"""
import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd

REPO = Path("c:/workspace/TalonX")
sys.path.insert(0, str(REPO))

OUT = REPO / "results" / "task20_excursion_audit"
OUT.mkdir(parents=True, exist_ok=True)

RAW_DATA_DIR = REPO / "data" / "historical_1m" / "task7b_alpaca_long_history"
TASK15_TABLE = REPO / "results" / "task15_risk_distance_audit" / "task15_trade_risk.csv"
TASK17_FEATURES = REPO / "results" / "task17_gross_edge_audit" / "task17_trade_features.csv"

EXPECTED_TOTAL_R_0 = 75.97580943135327
EXPECTED_TOTAL_R_5 = -21.41375894722095
EXPECTED_EXIT_COUNTS = {"STOP": 139, "TARGET": 16, "END_OF_SESSION": 26}

LANDMARKS = [0.25, 0.50, 0.75, 1.00, 1.50, 2.00, 3.00]

_raw_cache: dict[str, pd.DataFrame] = {}


def raw_bars(symbol: str) -> pd.DataFrame:
    if symbol not in _raw_cache:
        df = pd.read_csv(RAW_DATA_DIR / f"{symbol}.csv", parse_dates=["timestamp"])
        df["timestamp"] = pd.to_datetime(df["timestamp"], utc=True)
        _raw_cache[symbol] = df.set_index("timestamp").sort_index()
    return _raw_cache[symbol]


def walk_trade(row) -> dict | None:
    """Returns per-bar high_R/low_R series (favorable/adverse, direction-
    adjusted) plus landmark crossings for one trade. None if no bars found
    (should not happen -- every trade's own entry/exit bars exist by
    construction of the original backtest)."""
    bars = raw_bars(row.symbol)
    window = bars.loc[row.entry_timestamp:row.exit_timestamp]
    if window.empty:
        return None

    entry = row.entry_price
    risk = row.risk_dollars_per_share
    if row.direction == "bullish":
        high_R = (window["high"] - entry) / risk
        low_R = (window["low"] - entry) / risk
    else:
        high_R = (entry - window["low"]) / risk
        low_R = (entry - window["high"]) / risk

    running_mfe = high_R.cummax()
    running_mae = low_R.cummin()
    minutes = (window.index - row.entry_timestamp).total_seconds() / 60.0

    landmarks = {}
    for level in LANDMARKS:
        hit = running_mfe >= level
        if hit.any():
            idx = hit.idxmax()  # first True
            pos = window.index.get_loc(idx)
            landmarks[level] = dict(
                reached=True, time_to_level_min=float(minutes[pos]),
                bar_pos=int(pos), timestamp=str(idx),
            )
        else:
            landmarks[level] = dict(reached=False, time_to_level_min=None, bar_pos=None, timestamp=None)

    max_mfe = float(running_mfe.iloc[-1])
    max_mae = float(running_mae.iloc[-1])
    peak_mfe_pos = int(np.argmax(running_mfe.to_numpy()))
    time_to_peak_mfe_min = float(minutes[peak_mfe_pos])
    time_from_peak_to_exit_min = float(minutes[-1] - minutes[peak_mfe_pos])

    return dict(
        n_bars=len(window), max_mfe=max_mfe, max_mae=max_mae,
        time_to_peak_mfe_min=time_to_peak_mfe_min, time_from_peak_to_exit_min=time_from_peak_to_exit_min,
        landmarks=landmarks, high_R=high_R, low_R=low_R, minutes=minutes, index=window.index,
    )


def post_landmark_retracement(walk: dict, level: float) -> dict:
    lm = walk["landmarks"][level]
    if not lm["reached"]:
        return dict(crossed=False, retracement_R=None, crossed_breakeven_after=None, post_landmark_min_R=None)
    pos = lm["bar_pos"]
    post_min = float(walk["low_R"].iloc[pos:].min())
    return dict(crossed=True, retracement_R=level - post_min, crossed_breakeven_after=bool(post_min <= 0),
                post_landmark_min_R=post_min)


def classify_path(row, walk: dict) -> str:
    max_mfe = walk["max_mfe"]
    is_stop = row.exit_reason == "STOP"
    is_winner_exit = row.exit_reason in ("TARGET", "END_OF_SESSION")
    final_positive = row.gross_R > 0

    if is_stop:
        if max_mfe < 0.25:
            return "IMMEDIATE_FAILURE"
        if max_mfe < 1.0:
            return "SMALL_FAVORABLE_THEN_STOP"
        return "LARGE_FAVORABLE_THEN_REVERSAL"
    if is_winner_exit and final_positive:
        r05 = post_landmark_retracement(walk, 0.50)
        crossed_be_after_05 = r05["crossed_breakeven_after"] if r05["crossed"] else False
        if crossed_be_after_05:
            return "DEEP_RETRACE_WINNER"
        median_holding_placeholder = None  # duration split applied after aggregation, see main()
        return "MONOTONIC_WINNER"  # SLOW_TREND_WINNER split applied post-hoc by holding-time median
    return "OTHER"


def block(g: pd.DataFrame, r_col: str) -> dict:
    r = g[r_col].dropna()
    return dict(trades=len(g), total_r=r.sum() if len(r) else None, avg_r=r.mean() if len(r) else None)


if __name__ == "__main__":
    print("=== Section 2: Integrity ===")
    base = pd.read_csv(TASK15_TABLE, parse_dates=["entry_timestamp", "exit_timestamp"])
    for c in ["entry_timestamp", "exit_timestamp"]:
        base[c] = pd.to_datetime(base[c], utc=True)
    t17 = pd.read_csv(TASK17_FEATURES)[["trade_id", "subperiod"]]
    df = base.merge(t17, on="trade_id", how="left")

    problems = []
    if len(df) != 181:
        problems.append(f"{len(df)} trades, expected 181")
    if abs(df["net_R_0bps"].sum() - EXPECTED_TOTAL_R_0) > 1e-6:
        problems.append(f"0bps total {df['net_R_0bps'].sum()} != {EXPECTED_TOTAL_R_0}")
    if abs(df["net_R_5bps"].sum() - EXPECTED_TOTAL_R_5) > 1e-6:
        problems.append(f"5bps total {df['net_R_5bps'].sum()} != {EXPECTED_TOTAL_R_5}")
    exit_counts = df.exit_reason.value_counts().to_dict()
    for k, v in EXPECTED_EXIT_COUNTS.items():
        if exit_counts.get(k) != v:
            problems.append(f"exit_reason {k}: {exit_counts.get(k)} != expected {v}")
    from talonx_backtest.reproducibility import get_dataset_hash, get_git_commit
    dh = get_dataset_hash(str(RAW_DATA_DIR))
    if dh != "5e5412a960bf":
        problems.append(f"dataset_hash mismatch: {dh}")
    if problems:
        for p in problems:
            print("FAIL:", p)
        raise SystemExit("Integrity check failed.")
    print(f"OK -- 181 trades, exit_counts={exit_counts}, dataset_hash={dh}, git_commit={get_git_commit()}")
    # NOTE: task15_trade_risk.csv already carries its own `gross_R` column
    # (identical to net_R_0bps by definition -- 0bps has no cost) -- use it
    # directly rather than renaming net_R_0bps, which would create a
    # duplicate `gross_R` column and make row.gross_R ambiguous.

    # ------------------------------------------------------------------
    # Section 3/4: walk every trade, build landmark table
    # ------------------------------------------------------------------
    print("\nWalking raw bars for all 181 trades...")
    walks = {}
    landmark_rows = []
    path_rows = []
    missing = []
    for _, row in df.iterrows():
        w = walk_trade(row)
        if w is None:
            missing.append(row.trade_id)
            continue
        walks[row.trade_id] = w
        lrow = dict(trade_id=row.trade_id, symbol=row.symbol, direction=row.direction,
                    exit_reason=row.exit_reason, max_mfe=w["max_mfe"], max_mae=w["max_mae"],
                    time_to_peak_mfe_min=w["time_to_peak_mfe_min"],
                    time_from_peak_to_exit_min=w["time_from_peak_to_exit_min"],
                    final_R_gross=row.gross_R, n_bars=w["n_bars"])
        for level in LANDMARKS:
            lm = w["landmarks"][level]
            lrow[f"reaches_{level}R"] = lm["reached"]
            lrow[f"time_to_{level}R_min"] = lm["time_to_level_min"]
        landmark_rows.append(lrow)
    if missing:
        raise SystemExit(f"FAIL: no raw bars found for {len(missing)} trades: {missing}")
    landmark_df = pd.DataFrame(landmark_rows)
    landmark_df.to_csv(OUT / "task20_excursion_landmarks.csv", index=False)
    print(f"wrote task20_excursion_landmarks.csv ({len(landmark_df)} trades walked, "
          f"{sum(w['n_bars'] for w in walks.values())} total bars)")

    # path table (trade-level summary, no full bar series -- that would be huge)
    df["max_mfe"] = df.trade_id.map(lambda t: walks[t]["max_mfe"])
    df["max_mae"] = df.trade_id.map(lambda t: walks[t]["max_mae"])
    df["time_to_peak_mfe_min"] = df.trade_id.map(lambda t: walks[t]["time_to_peak_mfe_min"])
    df["time_from_peak_to_exit_min"] = df.trade_id.map(lambda t: walks[t]["time_from_peak_to_exit_min"])
    df["path_class_raw"] = df.apply(lambda r: classify_path(r, walks[r.trade_id]), axis=1)
    # SLOW_TREND_WINNER split: MONOTONIC_WINNER trades with holding time above the
    # population median holding time become SLOW_TREND_WINNER (transparent, fixed
    # AFTER classification, not tuned to any P&L outcome)
    median_holding = df["holding_seconds"].median()
    def finalize_class(row):
        if row.path_class_raw == "MONOTONIC_WINNER" and row.holding_seconds > median_holding:
            return "SLOW_TREND_WINNER"
        return row.path_class_raw
    df["path_class"] = df.apply(finalize_class, axis=1)
    df.drop(columns=["path_class_raw"]).to_csv(OUT / "task20_trade_paths.csv", index=False)
    print("wrote task20_trade_paths.csv")
    print("\npath class counts:", df.path_class.value_counts().to_dict())

    # ------------------------------------------------------------------
    # Section 5: exit-class excursion comparison
    # ------------------------------------------------------------------
    print("\n=== Section 5: exit-class excursion comparison ===")
    ec_rows = []
    for reason, g in df.groupby("exit_reason"):
        row = dict(exit_reason=reason, trades=len(g), median_mfe=g.max_mfe.median(),
                    p25_mfe=g.max_mfe.quantile(0.25), p75_mfe=g.max_mfe.quantile(0.75),
                    median_mae=g.max_mae.median())
        lg = landmark_df[landmark_df.trade_id.isin(g.trade_id)]
        for level in [0.5, 1.0]:
            times = lg.loc[lg[f"reaches_{level}R"], f"time_to_{level}R_min"]
            row[f"pct_reaching_{level}R"] = lg[f"reaches_{level}R"].mean() * 100
            row[f"median_time_to_{level}R_min"] = times.median() if len(times) else None
        for level in LANDMARKS:
            row[f"pct_reaching_{level}R"] = lg[f"reaches_{level}R"].mean() * 100
        ec_rows.append(row)
    ec_df = pd.DataFrame(ec_rows)
    ec_df.to_csv(OUT / "task20_exit_excursion.csv", index=False)
    print(ec_df[["exit_reason", "trades", "median_mfe", "p25_mfe", "p75_mfe", "median_mae"]].to_string(index=False))

    # ------------------------------------------------------------------
    # Section 6: STOP reversal anatomy
    # ------------------------------------------------------------------
    print("\n=== Section 6: STOP reversal anatomy ===")
    stops = df[df.exit_reason == "STOP"].copy()

    def reversal_bucket(mfe):
        if mfe < 0.25:
            return "A_never_reaches_0.25R"
        if mfe < 0.50:
            return "B_reaches_0.25_lt_0.5R"
        if mfe < 1.00:
            return "C_reaches_0.5_lt_1R"
        if mfe < 2.00:
            return "D_reaches_1_lt_2R"
        return "E_reaches_ge_2R"
    stops["reversal_bucket"] = stops.max_mfe.apply(reversal_bucket)
    rev_rows = []
    bucket_order = ["A_never_reaches_0.25R", "B_reaches_0.25_lt_0.5R", "C_reaches_0.5_lt_1R",
                     "D_reaches_1_lt_2R", "E_reaches_ge_2R"]
    for b in bucket_order:
        g = stops[stops.reversal_bucket == b]
        if g.empty:
            rev_rows.append(dict(reversal_bucket=b, trades=0))
            continue
        rev_rows.append(dict(
            reversal_bucket=b, trades=len(g), pct_of_stops=len(g) / len(stops) * 100,
            symbols=",".join(sorted(g.symbol.unique())), sessions=",".join(sorted(g.entry_session.unique())),
            median_holding_min=g.holding_seconds.median() / 60,
            median_time_to_mfe_min=g.time_to_peak_mfe_min.median(),
            median_time_mfe_to_stop_min=g.time_from_peak_to_exit_min.median(),
        ))
    pd.DataFrame(rev_rows).to_csv(OUT / "task20_stop_reversal.csv", index=False)
    print(pd.DataFrame(rev_rows).to_string(index=False))

    # ------------------------------------------------------------------
    # Section 7: favorable-then-stop population
    # ------------------------------------------------------------------
    print("\n=== Section 7: favorable-then-stop population ===")
    ftl_rows = []
    for level in [0.5, 1.0, 2.0]:
        g = stops[stops.max_mfe >= level]
        if g.empty:
            ftl_rows.append(dict(level=level, trades=0))
            continue
        reversal_mag = g.max_mfe - g.final_R_gross if "final_R_gross" in g.columns else (g.max_mfe - (-1.0))
        ftl_rows.append(dict(
            level=level, trades=len(g), gross_contribution=g.gross_R.sum(), r5bps_contribution=g.net_R_5bps.sum(),
            median_mfe=g.max_mfe.median(), median_time_to_mfe_min=g.time_to_peak_mfe_min.median(),
            median_reversal_magnitude_R=(g.max_mfe - g.gross_R).median(),
            median_time_mfe_to_stop_min=g.time_from_peak_to_exit_min.median(),
        ))
    ftl_df = pd.DataFrame(ftl_rows)
    ftl_df.to_csv(OUT / "task20_favorable_then_stop.csv", index=False)
    print(ftl_df.to_string(index=False))

    # ------------------------------------------------------------------
    # Section 8: winner retracement -- CRITICAL
    # ------------------------------------------------------------------
    print("\n=== Section 8: winner retracement ===")
    winners = df[(df.exit_reason.isin(["TARGET", "END_OF_SESSION"])) & (df.gross_R > 0)].copy()
    wr_rows = []
    for level in [0.25, 0.50, 1.00]:
        retr_vals = []
        crossed_be = []
        for _, row in winners.iterrows():
            r = post_landmark_retracement(walks[row.trade_id], level)
            if r["crossed"]:
                retr_vals.append(r["retracement_R"])
                crossed_be.append(r["crossed_breakeven_after"])
        if retr_vals:
            wr_rows.append(dict(
                level=level, winners_reaching_level=len(retr_vals),
                pct_of_winners=len(retr_vals) / len(winners) * 100,
                median_retracement_R=float(np.median(retr_vals)), p75_retracement_R=float(np.quantile(retr_vals, 0.75)),
                max_retracement_R=float(np.max(retr_vals)),
                pct_crossing_back_through_breakeven=float(np.mean(crossed_be) * 100),
            ))
        else:
            wr_rows.append(dict(level=level, winners_reaching_level=0))
    wr_df = pd.DataFrame(wr_rows)
    wr_df.to_csv(OUT / "task20_winner_retracement.csv", index=False)
    print(wr_df.to_string(index=False))

    # ------------------------------------------------------------------
    # Section 9: breakeven crossing analysis (all exit classes)
    # ------------------------------------------------------------------
    print("\n=== Section 9: breakeven crossings ===")
    bc_rows = []
    for level in [0.5, 1.0]:
        for reason, g in df.groupby("exit_reason"):
            crossed_flags = []
            for _, row in g.iterrows():
                r = post_landmark_retracement(walks[row.trade_id], level)
                if r["crossed"]:
                    crossed_flags.append(r["crossed_breakeven_after"])
            n_reached = len(crossed_flags)
            n_crossed_be = sum(crossed_flags)
            bc_rows.append(dict(level=level, exit_reason=reason, trades_reaching_level=n_reached,
                                 trades_crossing_back_through_breakeven=n_crossed_be,
                                 pct_crossing_back=(n_crossed_be / n_reached * 100) if n_reached else None))
    bc_df = pd.DataFrame(bc_rows)
    bc_df.to_csv(OUT / "task20_breakeven_crossings.csv", index=False)
    print(bc_df.to_string(index=False))

    # ------------------------------------------------------------------
    # Section 10: path shape classes summary
    # ------------------------------------------------------------------
    pc_rows = []
    for cls, g in df.groupby("path_class"):
        pc_rows.append(dict(path_class=cls, trades=len(g), pct_of_book=len(g) / len(df) * 100,
                             gross_r=g.gross_R.sum(), r5bps=g.net_R_5bps.sum(),
                             median_holding_min=g.holding_seconds.median() / 60, median_mfe=g.max_mfe.median()))
    pd.DataFrame(pc_rows).sort_values("trades", ascending=False).to_csv(OUT / "task20_path_classes.csv", index=False)
    print("\n=== Section 10: path classes ===")
    print(pd.DataFrame(pc_rows).sort_values("trades", ascending=False).to_string(index=False))

    # ------------------------------------------------------------------
    # Section 11/12: symbol / session analysis
    # ------------------------------------------------------------------
    sym_rows = []
    for sym, g in df.groupby("symbol"):
        gs = g[g.exit_reason == "STOP"]
        sym_rows.append(dict(
            symbol=sym, trades=len(g), stop_trades=len(gs),
            stop_median_mfe=gs.max_mfe.median() if len(gs) else None,
            stop_pct_reaching_0_5R=(gs.max_mfe >= 0.5).mean() * 100 if len(gs) else None,
            stop_pct_reaching_1R=(gs.max_mfe >= 1.0).mean() * 100 if len(gs) else None,
        ))
    pd.DataFrame(sym_rows).sort_values("trades", ascending=False).to_csv(OUT / "task20_symbol_analysis.csv", index=False)
    print("\n=== Section 11: symbol analysis ===")
    print(pd.DataFrame(sym_rows).sort_values("trades", ascending=False).to_string(index=False))

    sess_rows = []
    for bucket, g in df.groupby("session_bucket"):
        gs = g[g.exit_reason == "STOP"]
        sess_rows.append(dict(
            session_bucket=bucket, trades=len(g), stop_trades=len(gs),
            stop_median_mfe=gs.max_mfe.median() if len(gs) else None,
            stop_pct_reaching_0_5R=(gs.max_mfe >= 0.5).mean() * 100 if len(gs) else None,
        ))
    pd.DataFrame(sess_rows).to_csv(OUT / "task20_session_analysis.csv", index=False)
    print("\n=== Section 12: session analysis ===")
    print(pd.DataFrame(sess_rows).to_string(index=False))

    # ------------------------------------------------------------------
    # Section 13: temporal stability
    # ------------------------------------------------------------------
    sub_rows = []
    for name, g in df.groupby("subperiod"):
        gs = g[g.exit_reason == "STOP"]
        sub_rows.append(dict(
            subperiod=name, trades=len(g), stop_trades=len(gs),
            stop_pct_reaching_0_5R=(gs.max_mfe >= 0.5).mean() * 100 if len(gs) else None,
            stop_pct_reaching_1R=(gs.max_mfe >= 1.0).mean() * 100 if len(gs) else None,
        ))
    sub_df = pd.DataFrame(sub_rows)
    sub_df.to_csv(OUT / "task20_subperiod_analysis.csv", index=False)
    print("\n=== Section 13: subperiod stability ===")
    print(sub_df.to_string(index=False))

    # ------------------------------------------------------------------
    # Section 14: cost interaction by path class
    # ------------------------------------------------------------------
    cost_rows = []
    for cls, g in df.groupby("path_class"):
        cost_rows.append(dict(path_class=cls, trades=len(g), gross_r=g.gross_R.sum(), r5bps=g.net_R_5bps.sum(),
                               deterioration=g.gross_R.sum() - g.net_R_5bps.sum()))
    cost_df = pd.DataFrame(cost_rows).sort_values("deterioration", ascending=False)
    cost_df.to_csv(OUT / "task20_cost_path_analysis.csv", index=False)
    print("\n=== Section 14: cost by path class ===")
    print(cost_df.to_string(index=False))

    diag = dict(
        exit_counts=exit_counts, path_class_counts=df.path_class.value_counts().to_dict(),
        median_holding_seconds=float(median_holding),
        stop_reaching_0_5R_pct=(stops.max_mfe >= 0.5).mean() * 100,
        stop_reaching_1R_pct=(stops.max_mfe >= 1.0).mean() * 100,
        stop_reaching_2R_pct=(stops.max_mfe >= 2.0).mean() * 100,
    )
    (OUT / "_diag_scratch.json").write_text(json.dumps(diag, indent=2, default=str))
    print("\nAll sections complete.")
