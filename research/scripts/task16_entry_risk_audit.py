"""
Task 16 -- Entry Risk Preservation & Cost Viability Audit.

DIAGNOSTIC ONLY. Builds directly on Task 15's per-trade risk table (no
replay) to evaluate two hypothetical, NOT-implemented entry-sanity rules:
Rule A (risk_preservation_ratio floor) and Rule B (cost_to_risk ceiling).

Deterministic, no randomness.
"""
import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd

REPO = Path("c:/workspace/TalonX")
sys.path.insert(0, str(REPO))

OUT = REPO / "results" / "task16_entry_risk_audit"
OUT.mkdir(parents=True, exist_ok=True)

RAW_DATA_DIR = REPO / "data" / "historical_1m" / "task7b_alpaca_long_history"
TASK15_TABLE = REPO / "results" / "task15_risk_distance_audit" / "task15_trade_risk.csv"

EXPECTED_TOTAL_R = {"0bps": 75.97580943135327, "5bps": -21.41375894722095,
                     "10bps": -118.80332732578688, "20bps": -313.58246408292257}

PRESERVATION_BUCKETS = [
    ("<10%", -np.inf, 10), ("10-25%", 10, 25), ("25-50%", 25, 50), ("50-75%", 50, 75),
    ("75-90%", 75, 90), ("90-100%", 90, 100), (">100%", 100, np.inf),
]
COSTRISK_BUCKETS_T16 = [
    ("<0.10R", 0, 0.10), ("0.10-0.25R", 0.10, 0.25), ("0.25-0.50R", 0.25, 0.50),
    ("0.50-1R", 0.50, 1.0), ("1-2R", 1.0, 2.0), (">2R", 2.0, np.inf),
]
RULE_A_CUTOFFS = [10, 25, 50, 75]   # % preservation floor
RULE_B_CUTOFFS = [0.25, 0.50, 1.00, 2.00]  # cost_to_risk_5bps ceiling


def bucket_label(value, buckets):
    for label, lo, hi in buckets:
        if lo <= value < hi:
            return label
    return buckets[-1][0]


def pct_stats(s: pd.Series) -> dict:
    qs = [0, 0.01, 0.05, 0.10, 0.25, 0.50, 0.75, 0.90, 0.95, 0.99, 1.0]
    labels = ["min", "P1", "P5", "P10", "P25", "median", "P75", "P90", "P95", "P99", "max"]
    return {lab: float(s.quantile(q)) for lab, q in zip(labels, qs)}


def block(g: pd.DataFrame, r_col: str) -> dict:
    r = g[r_col].dropna()
    wins, losses = r[r > 0], r[r < 0]
    total = r.sum() if len(r) else None
    expectancy = r.mean() if len(r) else None
    gp = wins.sum() if len(wins) else 0.0
    gl = abs(losses.sum()) if len(losses) else 0.0
    pf = (gp / gl) if gl > 0 else (np.inf if gp > 0 else None)
    return dict(total_r=total, expectancy=expectancy, profit_factor=pf, trades=len(g),
                wins=len(wins), losses=len(losses))


_raw_cache = {}


def signal_bar_close(symbol: str, ts) -> float | None:
    if symbol not in _raw_cache:
        df = pd.read_csv(RAW_DATA_DIR / f"{symbol}.csv", parse_dates=["timestamp"])
        df["timestamp"] = pd.to_datetime(df["timestamp"], utc=True)
        _raw_cache[symbol] = df.set_index("timestamp")["close"]
    s = _raw_cache[symbol]
    try:
        v = s.loc[ts]
        return float(v.iloc[0]) if isinstance(v, pd.Series) else float(v)
    except KeyError:
        return None


if __name__ == "__main__":
    print("=== Section 2: Integrity ===")
    problems = []
    for label in ["0bps", "5bps", "10bps", "20bps"]:
        pass  # verified fully in Task 15; re-verify totals against the Task-15-derived table below
    if not TASK15_TABLE.exists():
        raise SystemExit(f"Task 15 table missing: {TASK15_TABLE} -- cannot proceed without it (no replay allowed).")
    df = pd.read_csv(TASK15_TABLE, parse_dates=["signal_timestamp", "entry_timestamp", "exit_timestamp"])
    if len(df) != 181:
        problems.append(f"{len(df)} trades, expected 181")
    for label, col in [("0bps", "net_R_0bps"), ("5bps", "net_R_5bps"), ("10bps", "net_R_10bps"), ("20bps", "net_R_20bps")]:
        total = df[col].sum()
        if abs(total - EXPECTED_TOTAL_R[label]) > 1e-6:
            problems.append(f"{label}: total {total} != expected {EXPECTED_TOTAL_R[label]}")
    from talonx_backtest.reproducibility import get_dataset_hash, get_git_commit
    dh = get_dataset_hash(str(RAW_DATA_DIR))
    if dh != "5e5412a960bf":
        problems.append(f"dataset_hash mismatch: {dh}")
    if problems:
        for p in problems:
            print("FAIL:", p)
        raise SystemExit("Integrity check failed.")
    print(f"OK -- {len(df)} trades match expected baseline, dataset_hash={dh}, git_commit={get_git_commit()}")

    # ------------------------------------------------------------------
    # Section 3: risk_preservation_ratio / risk_erosion_ratio
    # (== Task 15's erosion_ratio / (1 - erosion_ratio); same formula,
    # renamed per this task's own terminology -- fill_price IS entry_price
    # in this engine's Trade/OpenPosition model, see execution.py.)
    # ------------------------------------------------------------------
    df["fill_price"] = df["entry_price"]
    df["intended_risk"] = df["intended_risk_from_entry_dollars"]
    df["actual_fill_risk"] = df["risk_dollars_per_share"]
    df["risk_preservation_ratio_pct"] = df["erosion_ratio"] * 100.0
    df["risk_erosion_ratio_pct"] = (1 - df["erosion_ratio"]) * 100.0

    # fill movement from signal (Section 13)
    print("\nFetching signal-bar closes for fill-movement analysis (181 raw-bar lookups)...")
    df["signal_price"] = df.apply(lambda r: signal_bar_close(r.symbol, r.signal_timestamp), axis=1)
    df["fill_move_dollars"] = df["fill_price"] - df["signal_price"]
    df["fill_move_pct"] = df["fill_move_dollars"] / df["signal_price"] * 100
    direction_sign = df["direction"].map({"bullish": 1.0, "bearish": -1.0})
    # adverse = moved AGAINST the trade direction (toward the stop) between signal and fill
    df["fill_move_adverse_pct"] = -df["fill_move_pct"] * direction_sign
    df["signal_to_fill_min"] = (df["entry_timestamp"] - df["signal_timestamp"]).dt.total_seconds() / 60.0

    keep_cols = ["trade_id", "symbol", "direction", "signal_timestamp", "entry_timestamp", "entry_session",
                 "session_bucket", "atr", "signal_price", "fill_price", "stop_price", "target_price",
                 "risk_pct", "exit_reason", "net_R_0bps", "net_R_5bps", "net_R_10bps", "net_R_20bps",
                 "intended_risk", "actual_fill_risk", "risk_preservation_ratio_pct", "risk_erosion_ratio_pct",
                 "cost_to_risk_5bps", "cost_to_risk_10bps", "cost_to_risk_20bps",
                 "fill_move_dollars", "fill_move_pct", "fill_move_adverse_pct", "signal_to_fill_min", "mechanism"]
    df[keep_cols].to_csv(OUT / "task16_trade_geometry.csv", index=False)
    print("wrote task16_trade_geometry.csv")

    # ------------------------------------------------------------------
    # Section 4: preservation-ratio distribution + buckets
    # ------------------------------------------------------------------
    pres_stats = pct_stats(df["risk_preservation_ratio_pct"])
    print("\n=== Section 4: risk_preservation_ratio_pct percentiles ===")
    print(json.dumps(pres_stats, indent=2))

    df["preservation_bucket"] = df["risk_preservation_ratio_pct"].apply(lambda v: bucket_label(v, PRESERVATION_BUCKETS))
    pres_rows = []
    for label, _, _ in PRESERVATION_BUCKETS:
        g = df[df.preservation_bucket == label]
        if g.empty:
            pres_rows.append(dict(preservation_bucket=label, trades=0))
            continue
        row = dict(preservation_bucket=label, trades=len(g), symbols=",".join(sorted(g.symbol.unique())),
                   sessions=",".join(sorted(g.entry_session.unique())))
        for scen in ["0bps", "5bps", "10bps"]:
            b = block(g, f"net_R_{scen}")
            row[f"total_r_{scen}"] = b["total_r"]
            if scen != "10bps":
                row[f"expectancy_{scen}"] = b["expectancy"]
                row[f"profit_factor_{scen}"] = b["profit_factor"]
        row["stop_count"] = (g.exit_reason == "STOP").sum()
        row["target_count"] = (g.exit_reason == "TARGET").sum()
        row["eod_count"] = g.exit_reason.isin(["END_OF_SESSION", "DATA_END"]).sum()
        pres_rows.append(row)
    pd.DataFrame(pres_rows).to_csv(OUT / "task16_preservation_buckets.csv", index=False)
    print("wrote task16_preservation_buckets.csv")

    # ------------------------------------------------------------------
    # Section 5: cost-to-risk viability buckets (Task 16's own edges)
    # ------------------------------------------------------------------
    df["costrisk_bucket_5bps"] = df["cost_to_risk_5bps"].apply(lambda v: bucket_label(v, COSTRISK_BUCKETS_T16))
    cr_rows = []
    for label, _, _ in COSTRISK_BUCKETS_T16:
        g = df[df.costrisk_bucket_5bps == label]
        if g.empty:
            cr_rows.append(dict(costrisk_bucket_5bps=label, trades=0))
            continue
        row = dict(costrisk_bucket_5bps=label, trades=len(g), symbols=",".join(sorted(g.symbol.unique())),
                   sessions=",".join(sorted(g.entry_session.unique())))
        gross_r_proxy = g["net_R_0bps"].sum()  # 0bps net_R == gross_R (no cost at 0bps)
        row["gross_r"] = gross_r_proxy
        row["total_r_5bps"] = g["net_R_5bps"].sum()
        row["total_r_10bps"] = g["net_R_10bps"].sum()
        row["stop_count"] = (g.exit_reason == "STOP").sum()
        row["target_count"] = (g.exit_reason == "TARGET").sum()
        row["eod_count"] = g.exit_reason.isin(["END_OF_SESSION", "DATA_END"]).sum()
        cr_rows.append(row)
    pd.DataFrame(cr_rows).to_csv(OUT / "task16_costrisk_buckets.csv", index=False)
    print("wrote task16_costrisk_buckets.csv")

    # ------------------------------------------------------------------
    # Section 6: cross-tab preservation bucket x cost/risk bucket
    # ------------------------------------------------------------------
    cross = pd.crosstab(df["preservation_bucket"], df["costrisk_bucket_5bps"])
    cross = cross.reindex(index=[b[0] for b in PRESERVATION_BUCKETS],
                           columns=[b[0] for b in COSTRISK_BUCKETS_T16], fill_value=0)
    cross.to_csv(OUT / "task16_cross_tab.csv")
    print("\n=== Section 6: cross-tab ===")
    print(cross.to_string())

    # ------------------------------------------------------------------
    # Section 7 / 8: Rule A / Rule B diagnostics (ANALYSIS ONLY)
    # ------------------------------------------------------------------
    def dd_from_ordered(g: pd.DataFrame, r_col: str) -> float | None:
        ordered = g.dropna(subset=["exit_timestamp", r_col]).sort_values("exit_timestamp") if "exit_timestamp" in g.columns else g
        if ordered.empty:
            return None
        cum = ordered[r_col].cumsum()
        peak = cum.cummax()
        return float((cum - peak).min())

    # exit_timestamp not carried in df (dropped from keep_cols) -- reload for DD calc
    exit_ts = pd.read_csv(TASK15_TABLE, usecols=["trade_id", "exit_timestamp"], parse_dates=["exit_timestamp"])
    df = df.merge(exit_ts, on="trade_id", how="left")

    rule_a_rows = []
    for cutoff in RULE_A_CUTOFFS:
        retained = df[df.risk_preservation_ratio_pct >= cutoff]
        excluded = df[df.risk_preservation_ratio_pct < cutoff]
        row = dict(rule="A_preservation_floor", cutoff=f"{cutoff}%", trades_retained=len(retained), trades_excluded=len(excluded))
        for scen in ["0bps", "5bps", "10bps"]:
            row[f"total_r_{scen}"] = retained[f"net_R_{scen}"].sum()
        b = block(retained, "net_R_5bps")
        row["expectancy_5bps"] = b["expectancy"]
        row["profit_factor_5bps"] = b["profit_factor"]
        row["symbols_excluded"] = ",".join(sorted(excluded.symbol.unique())) if len(excluded) else ""
        row["sessions_excluded"] = ",".join(sorted(excluded.entry_session.unique())) if len(excluded) else ""
        rule_a_rows.append(row)
    pd.DataFrame(rule_a_rows).to_csv(OUT / "task16_rule_a_diagnostics.csv", index=False)
    print("wrote task16_rule_a_diagnostics.csv")

    rule_b_rows = []
    for cutoff in RULE_B_CUTOFFS:
        retained = df[df.cost_to_risk_5bps <= cutoff]
        excluded = df[df.cost_to_risk_5bps > cutoff]
        row = dict(rule="B_costrisk_ceiling", cutoff=f"{cutoff}R", trades_retained=len(retained), trades_excluded=len(excluded))
        for scen in ["0bps", "5bps", "10bps"]:
            row[f"total_r_{scen}"] = retained[f"net_R_{scen}"].sum()
        b = block(retained, "net_R_5bps")
        row["expectancy_5bps"] = b["expectancy"]
        row["profit_factor_5bps"] = b["profit_factor"]
        row["symbols_excluded"] = ",".join(sorted(excluded.symbol.unique())) if len(excluded) else ""
        row["sessions_excluded"] = ",".join(sorted(excluded.entry_session.unique())) if len(excluded) else ""
        rule_b_rows.append(row)
    pd.DataFrame(rule_b_rows).to_csv(OUT / "task16_rule_b_diagnostics.csv", index=False)
    print("wrote task16_rule_b_diagnostics.csv")

    # ------------------------------------------------------------------
    # Section 9: Rule A vs Rule B comparison
    # ------------------------------------------------------------------
    KNOWN_PATHOLOGICAL = {"STX-2026-07-30 22:29:00+00:00", "STX-2025-11-20 23:12:00+00:00"}
    comparison_rows = []
    for rule_label, cutoffs, col, op in [
        ("A_preservation_floor", RULE_A_CUTOFFS, "risk_preservation_ratio_pct", "lt"),
        ("B_costrisk_ceiling", RULE_B_CUTOFFS, "cost_to_risk_5bps", "gt"),
    ]:
        for cutoff in cutoffs:
            excluded = df[df[col] < cutoff] if op == "lt" else df[df[col] > cutoff]
            covers_pathological = KNOWN_PATHOLOGICAL <= set(excluded.trade_id)
            comparison_rows.append(dict(
                rule=rule_label, cutoff=cutoff, trades_excluded=len(excluded),
                covers_both_known_pathological_trades=covers_pathological,
                symbols_affected=",".join(sorted(excluded.symbol.unique())) if len(excluded) else "",
                sessions_affected=",".join(sorted(excluded.entry_session.unique())) if len(excluded) else "",
                excluded_0bps_r_removed=excluded.net_R_0bps.sum() if len(excluded) else 0.0,
                excluded_5bps_r_removed=excluded.net_R_5bps.sum() if len(excluded) else 0.0,
            ))
    pd.DataFrame(comparison_rows).to_csv(OUT / "task16_rule_comparison.csv", index=False)
    print("wrote task16_rule_comparison.csv")

    # ------------------------------------------------------------------
    # Section 10: CRITICAL broad-edge check
    # ------------------------------------------------------------------
    print("\n=== Section 10: broad-edge check (best-case tail exclusions) ===")
    broad_checks = {}
    for name, mask in [
        ("exclude_2_known_pathological", ~df.trade_id.isin(KNOWN_PATHOLOGICAL)),
        ("rule_b_costrisk_gt_1.0", df.cost_to_risk_5bps <= 1.0),
        ("rule_a_preservation_lt_10pct", df.risk_preservation_ratio_pct >= 10),
    ]:
        g = df[mask]
        b5 = block(g, "net_R_5bps")
        b10 = block(g, "net_R_10bps")
        broad_checks[name] = dict(
            trades=len(g), total_r_5bps=b5["total_r"], expectancy_5bps=b5["expectancy"],
            pf_5bps=b5["profit_factor"], total_r_10bps=b10["total_r"],
            positive_5bps_expectancy=bool(b5["expectancy"] and b5["expectancy"] > 0),
            pf_5bps_gt_1=bool(b5["profit_factor"] and b5["profit_factor"] > 1),
            positive_total_r_5bps=bool(b5["total_r"] and b5["total_r"] > 0),
        )
        print(name, json.dumps(broad_checks[name], indent=2))

    # ------------------------------------------------------------------
    # Section 11: symbol decomposition
    # ------------------------------------------------------------------
    sym_rows = []
    for sym, g in df.groupby("symbol"):
        sym_rows.append(dict(
            symbol=sym, trades=len(g), median_preservation_pct=g.risk_preservation_ratio_pct.median(),
            p10_preservation_pct=g.risk_preservation_ratio_pct.quantile(0.10),
            severely_eroded_lt50pct=(g.risk_preservation_ratio_pct < 50).sum(),
            median_cost_to_risk_5bps=g.cost_to_risk_5bps.median(),
            total_r_0bps=g.net_R_0bps.sum(), total_r_5bps=g.net_R_5bps.sum(),
        ))
    pd.DataFrame(sym_rows).sort_values("trades", ascending=False).to_csv(OUT / "task16_symbol_analysis.csv", index=False)
    print("wrote task16_symbol_analysis.csv")

    # ------------------------------------------------------------------
    # Section 12: session decomposition
    # ------------------------------------------------------------------
    sess_rows = []
    for bucket, g in df.groupby("session_bucket"):
        sess_rows.append(dict(
            session_bucket=bucket, trades=len(g), median_preservation_pct=g.risk_preservation_ratio_pct.median(),
            p10_preservation_pct=g.risk_preservation_ratio_pct.quantile(0.10),
            median_cost_to_risk_5bps=g.cost_to_risk_5bps.median(),
            total_r_0bps=g.net_R_0bps.sum(), total_r_5bps=g.net_R_5bps.sum(),
        ))
    pd.DataFrame(sess_rows).to_csv(OUT / "task16_session_analysis.csv", index=False)
    print("wrote task16_session_analysis.csv")

    # ------------------------------------------------------------------
    # Section 13: fill movement analysis
    # ------------------------------------------------------------------
    fm_stats = pct_stats(df["fill_move_adverse_pct"])
    delay_stats = pct_stats(df["signal_to_fill_min"])
    fm_rows = [
        dict(metric="fill_move_adverse_pct", **fm_stats),
        dict(metric="signal_to_fill_min", **delay_stats),
    ]
    # correlate adverse move with preservation ratio
    from scipy import stats as sstats
    corr = sstats.pearsonr(df["fill_move_adverse_pct"], df["risk_preservation_ratio_pct"])
    scorr = sstats.spearmanr(df["fill_move_adverse_pct"], df["risk_preservation_ratio_pct"])
    fm_rows.append(dict(metric="corr_adverse_move_vs_preservation",
                         min=corr.statistic, P1=corr.pvalue, P5=scorr.statistic, P10=scorr.pvalue,
                         P25=None, median=None, P75=None, P90=None, P95=None, P99=None, max=None))
    pd.DataFrame(fm_rows).to_csv(OUT / "task16_fill_movement.csv", index=False)
    print("wrote task16_fill_movement.csv")
    print(f"\nadverse-move vs preservation: pearson_r={corr.statistic:.4f} (p={corr.pvalue:.2e}), spearman_r={scorr.statistic:.4f}")

    diag = dict(
        pres_stats=pres_stats, broad_checks=broad_checks,
        known_pathological=sorted(KNOWN_PATHOLOGICAL),
        fill_move_adverse_stats=fm_stats, signal_to_fill_delay_stats=delay_stats,
        adverse_move_vs_preservation_pearson=float(corr.statistic), adverse_move_vs_preservation_spearman=float(scorr.statistic),
    )
    (OUT / "_diag_scratch.json").write_text(json.dumps(diag, indent=2, default=str))
    print("\nAll sections complete.")
