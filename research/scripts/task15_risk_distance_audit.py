"""
Task 15 -- Risk-Distance & Cost-to-Risk Diagnostic Audit.

DIAGNOSTIC ONLY. Reads the already-completed Task 13B (0bps) and Task 14
(5/10/20bps) trade ledgers -- no replay, no strategy changes. Explains why
the corrected 0.20% ATR-threshold result collapses under transaction costs
by decomposing each trade's risk distance and cost-to-risk ratio.

Deterministic (no randomness used anywhere in this script).
"""
import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd

REPO = Path("c:/workspace/TalonX")
sys.path.insert(0, str(REPO))

from talonx_quant.session import get_session  # noqa: E402
from zoneinfo import ZoneInfo
import datetime as _dt

_ET = ZoneInfo("America/New_York")

OUT = REPO / "results" / "task15_risk_distance_audit"
OUT.mkdir(parents=True, exist_ok=True)

RAW_DATA_DIR = REPO / "data" / "historical_1m" / "task7b_alpaca_long_history"

SCENARIO_FILES = {
    "0bps": REPO / "results" / "task13b_atr_020_fixed" / "task13b_020_trades.csv",
    "5bps": REPO / "results" / "task14_cost_005" / "task14_005_trades.csv",
    "10bps": REPO / "results" / "task14_cost_010" / "task14_010_trades.csv",
    "20bps": REPO / "results" / "task14_cost_020" / "task14_020_trades.csv",
}

EXPECTED_TOTAL_R = {"0bps": 75.97580943135327, "5bps": -21.41375894722095,
                     "10bps": -118.80332732578688, "20bps": -313.58246408292257}

ATR_STOP_MULTIPLIER = 1.5  # frozen production default (talonx_quant.config.QuantConfig.atr_stop_multiplier) -- read-only reference here, never changed

RISK_PCT_BUCKETS = [
    ("<0.01%", 0, 0.01), ("0.01-0.025%", 0.01, 0.025), ("0.025-0.05%", 0.025, 0.05),
    ("0.05-0.075%", 0.05, 0.075), ("0.075-0.10%", 0.075, 0.10), ("0.10-0.15%", 0.10, 0.15),
    ("0.15-0.20%", 0.15, 0.20), (">=0.20%", 0.20, np.inf),
]

COST_RISK_BUCKETS = [
    ("<0.10R", 0, 0.10), ("0.10-0.25R", 0.10, 0.25), ("0.25-0.50R", 0.25, 0.50),
    ("0.50-1R", 0.50, 1.0), ("1-2R", 1.0, 2.0), ("2-5R", 2.0, 5.0),
    ("5-10R", 5.0, 10.0), (">10R", 10.0, np.inf),
]

RISK_CUTOFFS = [0.025, 0.05, 0.075, 0.10]
COSTRISK_CUTOFFS = [0.25, 0.5, 1.0, 2.0]


# ------------------------------------------------------------------
# 1. Integrity + load
# ------------------------------------------------------------------

def verify_integrity():
    problems = []
    for label, path in SCENARIO_FILES.items():
        if not path.exists():
            problems.append(f"{label}: missing {path}")
            continue
        df = pd.read_csv(path)
        if len(df) != 181:
            problems.append(f"{label}: {len(df)} trades, expected 181")
        total = df["net_R"].sum()
        if abs(total - EXPECTED_TOTAL_R[label]) > 1e-6:
            problems.append(f"{label}: total_r {total} != expected {EXPECTED_TOTAL_R[label]}")
    from talonx_backtest.reproducibility import get_dataset_hash, get_git_commit, get_working_tree_dirty
    dh = get_dataset_hash(str(RAW_DATA_DIR))
    if dh != "5e5412a960bf":
        problems.append(f"dataset_hash mismatch: {dh}")
    return problems, dict(git_commit=get_git_commit(), working_tree_dirty=get_working_tree_dirty(), dataset_hash=dh)


def build_master_table() -> pd.DataFrame:
    base_cols = ["trade_id", "symbol", "direction", "session", "signal_timestamp", "entry_timestamp",
                 "entry_price", "stop_price", "target_price", "atr", "exit_timestamp", "exit_price",
                 "exit_reason", "holding_seconds", "gross_R"]
    zero = pd.read_csv(SCENARIO_FILES["0bps"], parse_dates=["signal_timestamp", "entry_timestamp", "exit_timestamp"])
    master = zero[base_cols + ["net_R", "gross_pnl", "net_pnl"]].rename(
        columns={"net_R": "net_R_0bps", "net_pnl": "net_pnl_0bps"}).drop(columns=["gross_pnl"])
    # gross_pnl is cost-invariant -- keep one copy from 0bps
    master["gross_pnl"] = zero["gross_pnl"]

    for label in ["5bps", "10bps", "20bps"]:
        df = pd.read_csv(SCENARIO_FILES[label], parse_dates=["entry_timestamp"])
        sub = df[["trade_id", "net_R", "net_pnl"]].rename(
            columns={"net_R": f"net_R_{label}", "net_pnl": f"net_pnl_{label}"})
        master = master.merge(sub, on="trade_id", how="left")

    for c in ["signal_timestamp", "entry_timestamp", "exit_timestamp"]:
        master[c] = pd.to_datetime(master[c], utc=True)

    master["risk_dollars_per_share"] = (master.entry_price - master.stop_price).abs()
    master["risk_pct"] = master["risk_dollars_per_share"] / master["entry_price"] * 100

    master["entry_session"] = master["entry_timestamp"].apply(get_session)
    master["entry_et_time"] = master["entry_timestamp"].apply(lambda t: t.astimezone(_ET).time())
    master["is_closing_auction_boundary"] = master["entry_et_time"] == _dt.time(16, 0)

    def session_bucket(row):
        if row.entry_session == "pre_market":
            return "PREMARKET"
        if row.entry_session == "regular":
            return "REGULAR"
        if row.is_closing_auction_boundary:
            return "CLOSING_AUCTION_BOUNDARY_16:00ET"
        return "POST_MARKET_CLOSED"
    master["session_bucket"] = master.apply(session_bucket, axis=1)

    for label in ["5bps", "10bps", "20bps"]:
        master[f"cost_dollars_per_share_{label}"] = master["gross_pnl"] - master[f"net_pnl_{label}"]
        master[f"cost_to_risk_{label}"] = master[f"cost_dollars_per_share_{label}"] / master["risk_dollars_per_share"]

    # Root-cause geometry decomposition -- see module docstring / summary.md
    # for the reasoning: compares the trade's ACTUAL risk distance to what
    # it would be if the stop were freshly anchored to the real entry price
    # (entry +/- 1.5xATR, the exact formula _finalize_fill_geometry uses
    # when it DOES re-anchor) using the trade's own stored ATR.
    def intended_risk(row):
        return ATR_STOP_MULTIPLIER * row.atr if pd.notna(row.atr) else np.nan
    master["intended_risk_from_entry_dollars"] = master.apply(intended_risk, axis=1)
    master["intended_risk_from_entry_pct"] = master["intended_risk_from_entry_dollars"] / master["entry_price"] * 100
    master["erosion_ratio"] = master["risk_dollars_per_share"] / master["intended_risk_from_entry_dollars"]

    return master


def classify_mechanism(row, small_atr_pct_threshold: float, erosion_low_threshold: float) -> str:
    if pd.isna(row.intended_risk_from_entry_pct) or pd.isna(row.erosion_ratio):
        return "OTHER"
    small_atr = row.intended_risk_from_entry_pct < small_atr_pct_threshold
    eroded = row.erosion_ratio < erosion_low_threshold
    if small_atr and eroded:
        return "BOTH"
    if small_atr:
        return "SMALL_ATR"
    if eroded:
        return "FILL_NEAR_STOP"
    return "OTHER"


if __name__ == "__main__":
    problems, fingerprints = verify_integrity()
    print("=== Section 1: Integrity ===")
    print(json.dumps(fingerprints, indent=2))
    if problems:
        for p in problems:
            print("FAIL:", p)
        raise SystemExit("Integrity check failed -- stopping per task policy.")
    print("OK -- all 4 scenarios match expected baseline, dataset hash confirmed.\n")

    master = build_master_table()
    print(f"Master table: {len(master)} trades, {master.shape[1]} columns")

    # --- root-cause classification thresholds, fixed BEFORE looking at
    # profitability: small_atr uses the LOWEST of the task's own Section-11
    # diagnostic cutoffs (0.10% intended risk from ATR alone); erosion uses
    # a round "lost more than 20% of the intended buffer" bar. Neither is
    # tuned to reproduce any particular trade count.
    SMALL_ATR_PCT_THRESHOLD = 0.10
    EROSION_LOW_THRESHOLD = 0.80
    master["mechanism"] = master.apply(
        lambda r: classify_mechanism(r, SMALL_ATR_PCT_THRESHOLD, EROSION_LOW_THRESHOLD), axis=1)

    master.to_csv(OUT / "task15_trade_risk.csv", index=False)
    print("wrote task15_trade_risk.csv")

    # ------------------------------------------------------------------
    # Section 3: risk-distance distribution + buckets
    # ------------------------------------------------------------------
    def pct_stats(s: pd.Series) -> dict:
        qs = [0, 0.01, 0.05, 0.10, 0.25, 0.50, 0.75, 0.90, 0.95, 0.99, 1.0]
        labels = ["min", "P1", "P5", "P10", "P25", "median", "P75", "P90", "P95", "P99", "max"]
        return {lab: float(s.quantile(q)) for lab, q in zip(labels, qs)}

    risk_pct_stats = pct_stats(master["risk_pct"])
    risk_dollars_stats = pct_stats(master["risk_dollars_per_share"])
    print("\n=== Section 3: risk_pct percentiles ===")
    print(json.dumps(risk_pct_stats, indent=2))

    def bucket_label(value, buckets):
        for label, lo, hi in buckets:
            if lo <= value < hi:
                return label
        return buckets[-1][0]

    master["risk_pct_bucket"] = master["risk_pct"].apply(lambda v: bucket_label(v, RISK_PCT_BUCKETS))

    def block_metrics(g: pd.DataFrame, r_col: str) -> dict:
        r = g[r_col].dropna()
        wins = r[r > 0]
        losses = r[r < 0]
        total = r.sum() if len(r) else None
        expectancy = r.mean() if len(r) else None
        gp = wins.sum() if len(wins) else 0.0
        gl = abs(losses.sum()) if len(losses) else 0.0
        pf = (gp / gl) if gl > 0 else (np.inf if gp > 0 else None)
        return dict(total_r=total, expectancy=expectancy, profit_factor=pf)

    bucket_rows = []
    bucket_order = [b[0] for b in RISK_PCT_BUCKETS]
    for label in bucket_order:
        g = master[master.risk_pct_bucket == label]
        if g.empty:
            bucket_rows.append(dict(risk_pct_bucket=label, trades=0))
            continue
        row = dict(risk_pct_bucket=label, trades=len(g), pct_of_trades=len(g) / len(master) * 100)
        for scen in ["0bps", "5bps", "10bps", "20bps"]:
            m = block_metrics(g, f"net_R_{scen}")
            row[f"total_r_{scen}"] = m["total_r"]
            if scen in ("0bps", "5bps"):
                row[f"expectancy_{scen}"] = m["expectancy"]
                row[f"profit_factor_{scen}"] = m["profit_factor"]
        row["stop_count"] = (g.exit_reason == "STOP").sum()
        row["target_count"] = (g.exit_reason == "TARGET").sum()
        row["eod_count"] = g.exit_reason.isin(["END_OF_SESSION", "DATA_END"]).sum()
        row["symbols"] = ",".join(sorted(g.symbol.unique()))
        row["sessions"] = ",".join(sorted(g.entry_session.unique()))
        bucket_rows.append(row)
    pd.DataFrame(bucket_rows).to_csv(OUT / "task15_risk_buckets.csv", index=False)
    print("wrote task15_risk_buckets.csv")

    # ------------------------------------------------------------------
    # Section 4: cost-to-risk distribution + buckets
    # ------------------------------------------------------------------
    cost_to_risk_long = []
    for scen in ["5bps", "10bps", "20bps"]:
        for _, row in master.iterrows():
            cost_to_risk_long.append(dict(
                trade_id=row.trade_id, symbol=row.symbol, scenario=scen,
                cost_dollars_per_share=row[f"cost_dollars_per_share_{scen}"],
                risk_dollars_per_share=row.risk_dollars_per_share,
                cost_to_risk=row[f"cost_to_risk_{scen}"],
            ))
    cost_to_risk_df = pd.DataFrame(cost_to_risk_long)
    cost_to_risk_df.to_csv(OUT / "task15_cost_to_risk.csv", index=False)
    print("wrote task15_cost_to_risk.csv")

    print("\n=== Section 4: cost_to_risk percentiles ===")
    ctr_stats = {}
    for scen in ["5bps", "10bps", "20bps"]:
        s = master[f"cost_to_risk_{scen}"]
        ctr_stats[scen] = pct_stats(s)
        print(scen, json.dumps(ctr_stats[scen], indent=2))

    ctr_bucket_rows = []
    for scen in ["5bps", "10bps", "20bps"]:
        col = f"cost_to_risk_{scen}"
        master[f"cost_to_risk_bucket_{scen}"] = master[col].apply(lambda v: bucket_label(v, COST_RISK_BUCKETS))
        for label, lo, hi in COST_RISK_BUCKETS:
            g = master[master[f"cost_to_risk_bucket_{scen}"] == label]
            if g.empty:
                ctr_bucket_rows.append(dict(scenario=scen, cost_to_risk_bucket=label, trades=0))
                continue
            row = dict(scenario=scen, cost_to_risk_bucket=label, trades=len(g),
                       symbols=",".join(sorted(g.symbol.unique())), sessions=",".join(sorted(g.entry_session.unique())),
                       gross_r=g["gross_R"].sum(), net_r=g[f"net_R_{scen}"].sum(),
                       expectancy=g[f"net_R_{scen}"].mean(),
                       stop_count=(g.exit_reason == "STOP").sum(), target_count=(g.exit_reason == "TARGET").sum(),
                       eod_count=g.exit_reason.isin(["END_OF_SESSION", "DATA_END"]).sum())
            ctr_bucket_rows.append(row)
    pd.DataFrame(ctr_bucket_rows).to_csv(OUT / "task15_cost_to_risk_buckets.csv", index=False)
    print("wrote task15_cost_to_risk_buckets.csv")

    # ------------------------------------------------------------------
    # Section 5: fragile trade cluster (derived independently, @5bps)
    # ------------------------------------------------------------------
    thresholds = [0.5, 1, 2, 5]
    print("\n=== Section 5: fragile cluster counts @5bps (independently derived) ===")
    cluster_counts = {}
    for th in thresholds:
        n = (master["cost_to_risk_5bps"] >= th).sum()
        cluster_counts[f">={th}"] = int(n)
        print(f"cost_to_risk_5bps >= {th}: {n} trades")
    # nesting check
    nested_ok = all(
        set(master[master.cost_to_risk_5bps >= thresholds[i + 1]].trade_id)
        <= set(master[master.cost_to_risk_5bps >= thresholds[i]].trade_id)
        for i in range(len(thresholds) - 1)
    )
    print("thresholds properly nested:", nested_ok)

    fragile = master[master.cost_to_risk_5bps >= 1.0].sort_values("cost_to_risk_5bps", ascending=False)
    fragile_cols = ["trade_id", "symbol", "entry_timestamp", "entry_session", "direction", "entry_price",
                     "stop_price", "risk_pct", "atr", "cost_to_risk_5bps", "cost_to_risk_10bps", "cost_to_risk_20bps",
                     "net_R_0bps", "net_R_5bps", "net_R_10bps", "net_R_20bps", "exit_reason", "mechanism"]
    fragile[fragile_cols].to_csv(OUT / "task15_fragile_trades.csv", index=False)
    print(f"wrote task15_fragile_trades.csv ({len(fragile)} trades with cost_to_risk_5bps >= 1.0)")

    # ------------------------------------------------------------------
    # Section 6: STX 2026-07-30 deep reconstruction
    # ------------------------------------------------------------------
    stx_row = master[master.trade_id == "STX-2026-07-30 22:29:00+00:00"]
    print("\n=== Section 6: STX 2026-07-30 22:29 reconstruction ===")
    stx_detail = {}
    if not stx_row.empty:
        r = stx_row.iloc[0]
        raw = pd.read_csv(RAW_DATA_DIR / "STX.csv", parse_dates=["timestamp"])
        raw["timestamp"] = pd.to_datetime(raw["timestamp"], utc=True)
        sig_bar = raw[raw.timestamp == r.signal_timestamp]
        stx_detail = dict(
            signal_timestamp=str(r.signal_timestamp), entry_timestamp=str(r.entry_timestamp),
            signal_close=float(sig_bar.close.iloc[0]) if len(sig_bar) else None,
            entry_price=float(r.entry_price), stop_price=float(r.stop_price), target_price=float(r.target_price),
            atr=float(r.atr), risk_dollars_per_share=float(r.risk_dollars_per_share), risk_pct=float(r.risk_pct),
            intended_risk_from_entry_dollars=float(r.intended_risk_from_entry_dollars),
            erosion_ratio=float(r.erosion_ratio),
            cost_dollars_5bps=float(r.cost_dollars_per_share_5bps), cost_to_risk_5bps=float(r.cost_to_risk_5bps),
            cost_to_risk_10bps=float(r.cost_to_risk_10bps), cost_to_risk_20bps=float(r.cost_to_risk_20bps),
            exit_reason=r.exit_reason, session=r.entry_session, mechanism=r.mechanism,
            gap_minutes=(r.entry_timestamp - r.signal_timestamp).total_seconds() / 60.0,
        )
        print(json.dumps(stx_detail, indent=2, default=str))
    else:
        print("STX trade not found in master table!")

    # ------------------------------------------------------------------
    # Section 7: root-cause decomposition summary
    # ------------------------------------------------------------------
    print("\n=== Section 7: mechanism counts ===")
    mech_counts = master.mechanism.value_counts().to_dict()
    print(mech_counts)
    mech_rows = []
    for mech, g in master.groupby("mechanism"):
        row = dict(mechanism=mech, trades=len(g))
        for scen in ["0bps", "5bps", "10bps", "20bps"]:
            row[f"total_r_{scen}"] = g[f"net_R_{scen}"].sum()
        mech_rows.append(row)
    pd.DataFrame(mech_rows).to_csv(OUT / "task15_root_cause.csv", index=False)
    print("wrote task15_root_cause.csv")

    # ------------------------------------------------------------------
    # Section 8: symbol analysis
    # ------------------------------------------------------------------
    sym_rows = []
    for sym, g in master.groupby("symbol"):
        row = dict(
            symbol=sym, trades=len(g), median_risk_pct=g.risk_pct.median(), p10_risk_pct=g.risk_pct.quantile(0.10),
            min_risk_pct=g.risk_pct.min(),
            trades_lt_0_10pct=(g.risk_pct < 0.10).sum(), trades_lt_0_05pct=(g.risk_pct < 0.05).sum(),
            trades_lt_0_025pct=(g.risk_pct < 0.025).sum(),
            median_cost_to_risk_5bps=g.cost_to_risk_5bps.median(), p95_cost_to_risk_5bps=g.cost_to_risk_5bps.quantile(0.95),
            total_r_0bps=g.net_R_0bps.sum(), total_r_5bps=g.net_R_5bps.sum(),
        )
        sym_rows.append(row)
    pd.DataFrame(sym_rows).sort_values("trades", ascending=False).to_csv(OUT / "task15_symbol_analysis.csv", index=False)
    print("wrote task15_symbol_analysis.csv")

    # ------------------------------------------------------------------
    # Section 9: session analysis
    # ------------------------------------------------------------------
    sess_rows = []
    for bucket, g in master.groupby("session_bucket"):
        row = dict(
            session_bucket=bucket, trades=len(g), median_risk_pct=g.risk_pct.median(),
            p10_risk_pct=g.risk_pct.quantile(0.10),
            trades_costrisk5bps_ge1=(g.cost_to_risk_5bps >= 1.0).sum(),
            total_r_0bps=g.net_R_0bps.sum(), total_r_5bps=g.net_R_5bps.sum(),
        )
        sess_rows.append(row)
    pd.DataFrame(sess_rows).to_csv(OUT / "task15_session_analysis.csv", index=False)
    print("wrote task15_session_analysis.csv")

    # ------------------------------------------------------------------
    # Section 10: exit-path analysis
    # ------------------------------------------------------------------
    exit_rows = []
    for reason, g in master.groupby("exit_reason"):
        row = dict(
            exit_reason=reason, trades=len(g), median_risk_pct=g.risk_pct.median(),
            median_cost_to_risk_5bps=g.cost_to_risk_5bps.median(),
            total_r_0bps=g.net_R_0bps.sum(), total_r_5bps=g.net_R_5bps.sum(),
        )
        exit_rows.append(row)
    pd.DataFrame(exit_rows).to_csv(OUT / "task15_exit_analysis.csv", index=False)
    print("wrote task15_exit_analysis.csv")

    # ------------------------------------------------------------------
    # Section 11: risk_pct cutoff diagnostics (ANALYSIS ONLY)
    # ------------------------------------------------------------------
    def dd_from_ordered(g: pd.DataFrame, r_col: str) -> float | None:
        ordered = g.dropna(subset=["exit_timestamp", r_col]).sort_values("exit_timestamp")
        if ordered.empty:
            return None
        cum = ordered[r_col].cumsum()
        peak = cum.cummax()
        return float((cum - peak).min())

    cutoff_rows = []
    for cutoff in RISK_CUTOFFS:
        retained = master[master.risk_pct >= cutoff]
        excluded = master[master.risk_pct < cutoff]
        row = dict(cutoff_risk_pct=cutoff, trades_retained=len(retained), trades_excluded=len(excluded))
        for scen in ["0bps", "5bps", "10bps"]:
            row[f"total_r_{scen}"] = retained[f"net_R_{scen}"].sum()
        m = block_metrics(retained, "net_R_5bps")
        row["expectancy_5bps"] = m["expectancy"]
        row["profit_factor_5bps"] = m["profit_factor"]
        row["max_dd_5bps"] = dd_from_ordered(retained, "net_R_5bps")
        cutoff_rows.append(row)
    pd.DataFrame(cutoff_rows).to_csv(OUT / "task15_risk_cutoff_diagnostics.csv", index=False)
    print("wrote task15_risk_cutoff_diagnostics.csv")

    # ------------------------------------------------------------------
    # Section 12: cost-to-risk cutoff diagnostics (ANALYSIS ONLY, @5bps)
    # ------------------------------------------------------------------
    cr_cutoff_rows = []
    for cutoff in COSTRISK_CUTOFFS:
        retained = master[master.cost_to_risk_5bps <= cutoff]
        excluded = master[master.cost_to_risk_5bps > cutoff]
        row = dict(cutoff_cost_to_risk_5bps=cutoff, trades_retained=len(retained), trades_excluded=len(excluded))
        for scen in ["0bps", "5bps", "10bps"]:
            row[f"total_r_{scen}"] = retained[f"net_R_{scen}"].sum()
        m = block_metrics(retained, "net_R_5bps")
        row["expectancy_5bps"] = m["expectancy"]
        row["profit_factor_5bps"] = m["profit_factor"]
        row["max_dd_5bps"] = dd_from_ordered(retained, "net_R_5bps")
        cr_cutoff_rows.append(row)
    pd.DataFrame(cr_cutoff_rows).to_csv(OUT / "task15_costrisk_cutoff_diagnostics.csv", index=False)
    print("wrote task15_costrisk_cutoff_diagnostics.csv")

    # ------------------------------------------------------------------
    # Section 13: concentration
    # ------------------------------------------------------------------
    master["deterioration_0_to_5"] = master["net_R_0bps"] - master["net_R_5bps"]
    by_deterioration = master.sort_values("deterioration_0_to_5", ascending=False)
    total_deterioration = master["deterioration_0_to_5"].sum()
    total_5bps = master["net_R_5bps"].sum()

    conc_rows = []
    for n in [1, 3, 5]:
        worst_n = by_deterioration.head(n)
        conc_rows.append(dict(
            group=f"worst_{n}_cost_fragile_trades", trades=n,
            deterioration_contribution=worst_n["deterioration_0_to_5"].sum(),
            pct_of_total_0_to_5_deterioration=worst_n["deterioration_0_to_5"].sum() / total_deterioration * 100,
            total_5bps_r_excluding_group=total_5bps - worst_n["net_R_5bps"].sum(),
        ))
    ge1 = master[master.cost_to_risk_5bps >= 1.0]
    conc_rows.append(dict(
        group="all_trades_costrisk5bps_ge1", trades=len(ge1),
        deterioration_contribution=ge1["deterioration_0_to_5"].sum(),
        pct_of_total_0_to_5_deterioration=ge1["deterioration_0_to_5"].sum() / total_deterioration * 100,
        total_5bps_r_excluding_group=total_5bps - ge1["net_R_5bps"].sum(),
    ))
    conc_rows.append(dict(group="ALL_TRADES_reference", trades=len(master),
                           deterioration_contribution=total_deterioration,
                           pct_of_total_0_to_5_deterioration=100.0, total_5bps_r_excluding_group=None))
    pd.DataFrame(conc_rows).to_csv(OUT / "task15_concentration.csv", index=False)
    print("wrote task15_concentration.csv")
    print(f"total 0->5bps deterioration: {total_deterioration:.2f}R, total 5bps R (all trades): {total_5bps:.2f}")

    # ------------------------------------------------------------------
    # Section 14: correlations
    # ------------------------------------------------------------------
    from scipy import stats as sstats
    corr_rows = []
    for xcol, xlabel in [("risk_pct", "risk_pct"), ("cost_to_risk_5bps", "cost_to_risk_5bps")]:
        x = master[xcol]
        y = master["deterioration_0_to_5"]
        pear = sstats.pearsonr(x, y)
        spear = sstats.spearmanr(x, y)
        corr_rows.append(dict(x=xlabel, y="deterioration_0_to_5bps",
                               pearson_r=pear.statistic, pearson_p=pear.pvalue,
                               spearman_r=spear.statistic, spearman_p=spear.pvalue, n=len(x)))
    pd.DataFrame(corr_rows).to_csv(OUT / "task15_correlations.csv", index=False)
    print("\n=== Section 14: correlations ===")
    print(pd.DataFrame(corr_rows).to_string(index=False))

    # ------------------------------------------------------------------
    # Persist everything needed for the write-up
    # ------------------------------------------------------------------
    diag = dict(
        fingerprints=fingerprints, risk_pct_stats=risk_pct_stats, risk_dollars_stats=risk_dollars_stats,
        cost_to_risk_stats=ctr_stats, fragile_cluster_counts_5bps=cluster_counts,
        nested_ok=bool(nested_ok), mechanism_counts=mech_counts, stx_detail=stx_detail,
        total_deterioration_0_to_5=float(total_deterioration), total_5bps_r=float(total_5bps),
        small_atr_pct_threshold=SMALL_ATR_PCT_THRESHOLD, erosion_low_threshold=EROSION_LOW_THRESHOLD,
    )
    (OUT / "_diag_scratch.json").write_text(json.dumps(diag, indent=2, default=str))
    print("\nwrote _diag_scratch.json (intermediate, for report assembly)")
