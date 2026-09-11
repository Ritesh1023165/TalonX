"""
Task 17 -- Gross Edge Attribution & Stability Audit.

DIAGNOSTIC ONLY. Builds a master per-trade feature table from Task 13B
(0bps trades.csv, for confluence/RR/volume/trend/MFE-MAE fields) + Task 15's
risk-geometry table (risk_pct, preservation ratio, session bucket) -- no
replay. Identifies where GROSS edge comes from and whether any winner/loser
characteristic is stable across chronological subperiods.

Deterministic, no randomness.
"""
import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd
from scipy import stats as sstats

REPO = Path("c:/workspace/TalonX")
sys.path.insert(0, str(REPO))

OUT = REPO / "results" / "task17_gross_edge_audit"
OUT.mkdir(parents=True, exist_ok=True)

RAW_DATA_DIR = REPO / "data" / "historical_1m" / "task7b_alpaca_long_history"
TASK13B_TRADES = REPO / "results" / "task13b_atr_020_fixed" / "task13b_020_trades.csv"
TASK15_TABLE = REPO / "results" / "task15_risk_distance_audit" / "task15_trade_risk.csv"
TASK14_5BPS = REPO / "results" / "task14_cost_005" / "task14_005_trades.csv"
TASK14_10BPS = REPO / "results" / "task14_cost_010" / "task14_010_trades.csv"

EXPECTED_TOTAL_R_0 = 75.97580943135327
EXPECTED_TOTAL_R_5 = -21.41375894722095

SUBPERIODS = [
    ("Aug-Oct 2025", "2025-08-15", "2025-10-31 23:59:59"),
    ("Nov 2025-Jan 2026", "2025-11-01", "2026-01-31 23:59:59"),
    ("Feb-Apr 2026", "2026-02-01", "2026-04-30 23:59:59"),
    ("May-Aug 2026", "2026-05-01", "2026-08-14 23:59:59"),
]


def block(g: pd.DataFrame, r_col: str) -> dict:
    r = g[r_col].dropna()
    wins, losses = r[r > 0], r[r < 0]
    total = r.sum() if len(r) else None
    expectancy = r.mean() if len(r) else None
    gp = wins.sum() if len(wins) else 0.0
    gl = abs(losses.sum()) if len(losses) else 0.0
    pf = (gp / gl) if gl > 0 else (np.inf if gp > 0 else None)
    win_rate = len(wins) / len(r) if len(r) else None
    return dict(trades=len(g), total_r=total, expectancy=expectancy, profit_factor=pf,
                win_rate=win_rate, wins=len(wins), losses=len(losses))


def continuous_compare(df: pd.DataFrame, col: str, group_col="outcome") -> dict:
    out = {}
    for grp in ["WINNER", "LOSER"]:
        s = df.loc[df[group_col] == grp, col].dropna()
        out[grp] = dict(count=len(s), mean=s.mean() if len(s) else None, median=s.median() if len(s) else None,
                         P25=s.quantile(0.25) if len(s) else None, P75=s.quantile(0.75) if len(s) else None)
    return out


if __name__ == "__main__":
    print("=== Section 2: Integrity ===")
    t13b = pd.read_csv(TASK13B_TRADES, parse_dates=["signal_timestamp", "entry_timestamp", "exit_timestamp"])
    for c in ["signal_timestamp", "entry_timestamp", "exit_timestamp"]:
        t13b[c] = pd.to_datetime(t13b[c], utc=True)
    problems = []
    if len(t13b) != 181:
        problems.append(f"{len(t13b)} trades, expected 181")
    if abs(t13b["net_R"].sum() - EXPECTED_TOTAL_R_0) > 1e-6:
        problems.append(f"0bps total {t13b['net_R'].sum()} != {EXPECTED_TOTAL_R_0}")
    from talonx_backtest.reproducibility import get_dataset_hash, get_git_commit
    dh = get_dataset_hash(str(RAW_DATA_DIR))
    if dh != "5e5412a960bf":
        problems.append(f"dataset_hash mismatch: {dh}")
    if problems:
        for p in problems:
            print("FAIL:", p)
        raise SystemExit("Integrity check failed.")
    print(f"OK -- 181 trades, 0bps total {t13b['net_R'].sum():.2f}, dataset_hash={dh}, git_commit={get_git_commit()}")

    t15 = pd.read_csv(TASK15_TABLE, parse_dates=["signal_timestamp", "entry_timestamp"])
    b5 = pd.read_csv(TASK14_5BPS)[["trade_id", "net_R"]].rename(columns={"net_R": "net_R_5bps"})
    b10 = pd.read_csv(TASK14_10BPS)[["trade_id", "net_R"]].rename(columns={"net_R": "net_R_10bps"})
    if abs(b5["net_R_5bps"].sum() - EXPECTED_TOTAL_R_5) > 1e-6:
        raise SystemExit(f"5bps total mismatch: {b5['net_R_5bps'].sum()}")

    df = t13b.merge(t15[["trade_id", "risk_pct", "erosion_ratio", "entry_session", "session_bucket",
                          "intended_risk_from_entry_pct"]], on="trade_id", how="left")
    df = df.merge(b5, on="trade_id", how="left").merge(b10, on="trade_id", how="left")
    df = df.rename(columns={"net_R": "gross_R_check", "erosion_ratio": "risk_preservation_ratio"})
    df["signal_to_fill_min"] = (df["entry_timestamp"] - df["signal_timestamp"]).dt.total_seconds() / 60.0
    df["atr_pct"] = df["atr"] / df["entry_price"] * 100
    df["month"] = df["entry_timestamp"].dt.strftime("%Y-%m")

    def subperiod_of(ts):
        for name, start, end in SUBPERIODS:
            if pd.Timestamp(start, tz="UTC") <= ts <= pd.Timestamp(end, tz="UTC"):
                return name
        return "OUTSIDE_RANGE"
    df["subperiod"] = df["entry_timestamp"].apply(subperiod_of)

    # ------------------------------------------------------------------
    # Section 3: WINNER/LOSER/BREAKEVEN (0bps == gross_R)
    # ------------------------------------------------------------------
    df["outcome"] = np.select([df.gross_R > 0, df.gross_R < 0], ["WINNER", "LOSER"], default="BREAKEVEN")
    print("\nOutcome counts:", df.outcome.value_counts().to_dict())

    # ------------------------------------------------------------------
    # Section 15: cost-margin reconciliation
    # ------------------------------------------------------------------
    df["cost_R_5bps"] = df["gross_R"] - df["net_R_5bps"]
    df["gross_edge_margin_5bps"] = df["gross_R"] - df["cost_R_5bps"]
    recon_diff = (df["gross_edge_margin_5bps"] - df["net_R_5bps"]).abs().max()
    print(f"cost-margin reconciliation max diff vs net_R_5bps: {recon_diff:.2e}")

    feature_cols = [
        "trade_id", "symbol", "direction", "entry_session", "session_bucket", "month", "subperiod",
        "signal_timestamp", "entry_timestamp", "signal_to_fill_min", "atr", "atr_pct", "risk_pct",
        "risk_preservation_ratio", "volume_surge_ratio", "confluence_score", "screening_rr", "execution_rr",
        "trend_alignment", "holding_seconds", "exit_reason", "mfe_r", "mae_r", "gross_R", "net_R_5bps",
        "net_R_10bps", "outcome",
    ]
    df[feature_cols].to_csv(OUT / "task17_trade_features.csv", index=False)
    print("wrote task17_trade_features.csv")

    # ------------------------------------------------------------------
    # Section 5: winner vs loser comparison
    # ------------------------------------------------------------------
    continuous_vars = ["atr_pct", "risk_pct", "risk_preservation_ratio", "volume_surge_ratio",
                        "screening_rr", "execution_rr", "signal_to_fill_min", "holding_seconds", "mfe_r", "mae_r"]
    wl_rows = []
    for col in continuous_vars:
        cmp = continuous_compare(df, col)
        wl_rows.append(dict(variable=col, kind="continuous",
                             winner_n=cmp["WINNER"]["count"], winner_mean=cmp["WINNER"]["mean"],
                             winner_median=cmp["WINNER"]["median"], winner_p25=cmp["WINNER"]["P25"], winner_p75=cmp["WINNER"]["P75"],
                             loser_n=cmp["LOSER"]["count"], loser_mean=cmp["LOSER"]["mean"],
                             loser_median=cmp["LOSER"]["median"], loser_p25=cmp["LOSER"]["P25"], loser_p75=cmp["LOSER"]["P75"]))
    categorical_vars = ["symbol", "direction", "entry_session", "exit_reason", "subperiod"]
    for col in categorical_vars:
        for val, g in df.groupby(col):
            b = block(g, "gross_R")
            b5v = block(g, "net_R_5bps")
            wl_rows.append(dict(variable=col, kind=f"categorical:{val}", winner_n=b["wins"], loser_n=b["losses"],
                                 winner_mean=b["win_rate"], winner_median=b["total_r"], winner_p25=b["expectancy"],
                                 winner_p75=b5v["expectancy"]))
    pd.DataFrame(wl_rows).to_csv(OUT / "task17_winner_loser_comparison.csv", index=False)
    print("wrote task17_winner_loser_comparison.csv")

    # ------------------------------------------------------------------
    # Section 6: symbol attribution
    # ------------------------------------------------------------------
    total_pos = df.loc[df.gross_R > 0, "gross_R"].sum()
    total_neg = df.loc[df.gross_R < 0, "gross_R"].sum()
    sym_rows = []
    for sym, g in df.groupby("symbol"):
        b0 = block(g, "gross_R")
        b5v = block(g, "net_R_5bps")
        pos = g.loc[g.gross_R > 0, "gross_R"].sum()
        neg = g.loc[g.gross_R < 0, "gross_R"].sum()
        sym_rows.append(dict(
            symbol=sym, trades=b0["trades"], win_rate=b0["win_rate"], gross_r=b0["total_r"],
            gross_expectancy=b0["expectancy"], r5bps=b5v["total_r"], expectancy_5bps=b5v["expectancy"],
            pf_gross=b0["profit_factor"], share_of_gross_positive_r=pos / total_pos if total_pos else None,
            share_of_gross_losses=neg / total_neg if total_neg else None,
        ))
    pd.DataFrame(sym_rows).sort_values("trades", ascending=False).to_csv(OUT / "task17_symbol_attribution.csv", index=False)
    print("wrote task17_symbol_attribution.csv")

    # ------------------------------------------------------------------
    # Section 7: concentration (attribution views only)
    # ------------------------------------------------------------------
    conc_rows = []
    b0_all = block(df, "gross_R")
    b5_all = block(df, "net_R_5bps")
    conc_rows.append(dict(view="ALL_TRADES", trades=b0_all["trades"], gross_r=b0_all["total_r"], r5bps=b5_all["total_r"]))
    by_r = df.sort_values("gross_R", ascending=False)
    for n in [1, 3, 5]:
        rest = df[~df.trade_id.isin(by_r.head(n).trade_id)]
        b0 = block(rest, "gross_R")
        b5v = block(rest, "net_R_5bps")
        conc_rows.append(dict(view=f"EXCLUDING_TOP_{n}_WINNER", trades=b0["trades"], gross_r=b0["total_r"], r5bps=b5v["total_r"]))
    for combo_name, symbols in [("EXCLUDING_STX", ["STX"]), ("EXCLUDING_AMD", ["AMD"]), ("EXCLUDING_PYPL", ["PYPL"]),
                                 ("EXCLUDING_STX_AMD", ["STX", "AMD"]), ("EXCLUDING_STX_AMD_PYPL", ["STX", "AMD", "PYPL"])]:
        rest = df[~df.symbol.isin(symbols)]
        b0 = block(rest, "gross_R")
        b5v = block(rest, "net_R_5bps")
        conc_rows.append(dict(view=combo_name, trades=b0["trades"], gross_r=b0["total_r"], r5bps=b5v["total_r"]))
    pd.DataFrame(conc_rows).to_csv(OUT / "task17_concentration.csv", index=False)
    print("wrote task17_concentration.csv")

    # ------------------------------------------------------------------
    # Section 8: confluence check
    # ------------------------------------------------------------------
    confluence_unique = sorted(df.confluence_score.dropna().unique().tolist())
    print(f"\n=== Section 8: confluence_score unique values = {confluence_unique} ===")

    # ------------------------------------------------------------------
    # Section 9: R:R attribution
    # ------------------------------------------------------------------
    rr_rows = []
    for col in ["screening_rr", "execution_rr"]:
        cmp = continuous_compare(df, col)
        s_gross = sstats.spearmanr(df[col].dropna(), df.loc[df[col].notna(), "gross_R"])
        s_5bps = sstats.spearmanr(df[col].dropna(), df.loc[df[col].notna(), "net_R_5bps"])
        rr_rows.append(dict(variable=col, winner_median=cmp["WINNER"]["median"], loser_median=cmp["LOSER"]["median"],
                             winner_mean=cmp["WINNER"]["mean"], loser_mean=cmp["LOSER"]["mean"],
                             spearman_vs_gross_R=s_gross.statistic, spearman_vs_gross_R_p=s_gross.pvalue,
                             spearman_vs_5bps_R=s_5bps.statistic, spearman_vs_5bps_R_p=s_5bps.pvalue))
    pd.DataFrame(rr_rows).to_csv(OUT / "task17_rr_analysis.csv", index=False)
    print("wrote task17_rr_analysis.csv")
    print(pd.DataFrame(rr_rows).to_string(index=False))

    # ------------------------------------------------------------------
    # Section 10: volatility/risk attribution
    # ------------------------------------------------------------------
    vol_rows = []
    for col in ["atr_pct", "risk_pct", "risk_preservation_ratio"]:
        s_gross = sstats.spearmanr(df[col].dropna(), df.loc[df[col].notna(), "gross_R"])
        s_5bps = sstats.spearmanr(df[col].dropna(), df.loc[df[col].notna(), "net_R_5bps"])
        cmp = continuous_compare(df, col)
        vol_rows.append(dict(variable=col, winner_median=cmp["WINNER"]["median"], loser_median=cmp["LOSER"]["median"],
                              spearman_vs_gross_R=s_gross.statistic, spearman_vs_gross_R_p=s_gross.pvalue,
                              spearman_vs_5bps_R=s_5bps.statistic, spearman_vs_5bps_R_p=s_5bps.pvalue))
    pd.DataFrame(vol_rows).to_csv(OUT / "task17_volatility_analysis.csv", index=False)
    print("wrote task17_volatility_analysis.csv")

    # ------------------------------------------------------------------
    # Section 11: volume attribution (quantile buckets, not thresholds)
    # ------------------------------------------------------------------
    df["volume_quartile"] = pd.qcut(df["volume_surge_ratio"], 4, labels=["Q1_lowest", "Q2", "Q3", "Q4_highest"])
    vq_rows = []
    for q, g in df.groupby("volume_quartile", observed=True):
        b0 = block(g, "gross_R")
        b5v = block(g, "net_R_5bps")
        vq_rows.append(dict(volume_quartile=str(q), trades=b0["trades"], win_rate=b0["win_rate"],
                             gross_expectancy=b0["expectancy"], expectancy_5bps=b5v["expectancy"],
                             range_min=g.volume_surge_ratio.min(), range_max=g.volume_surge_ratio.max()))
    pd.DataFrame(vq_rows).to_csv(OUT / "task17_volume_analysis.csv", index=False)
    print("wrote task17_volume_analysis.csv")

    # ------------------------------------------------------------------
    # Section 12: exit / holding-time attribution
    # ------------------------------------------------------------------
    df["holding_quartile"] = pd.qcut(df["holding_seconds"].rank(method="first"), 4, labels=["Q1_shortest", "Q2", "Q3", "Q4_longest"])
    eh_rows = []
    for reason, g in df.groupby("exit_reason"):
        b0 = block(g, "gross_R")
        b5v = block(g, "net_R_5bps")
        eh_rows.append(dict(group_type="exit_reason", group=reason, trades=b0["trades"],
                             gross_expectancy=b0["expectancy"], expectancy_5bps=b5v["expectancy"]))
    for q, g in df.groupby("holding_quartile", observed=True):
        b0 = block(g, "gross_R")
        b5v = block(g, "net_R_5bps")
        eh_rows.append(dict(group_type="holding_quartile", group=str(q), trades=b0["trades"],
                             gross_expectancy=b0["expectancy"], expectancy_5bps=b5v["expectancy"],
                             median_holding_min=g.holding_seconds.median() / 60))
    pd.DataFrame(eh_rows).to_csv(OUT / "task17_exit_holding_analysis.csv", index=False)
    print("wrote task17_exit_holding_analysis.csv")

    # ------------------------------------------------------------------
    # Section 13: temporal stability of key relationships
    # ------------------------------------------------------------------
    print("\n=== Section 13: subperiod trade counts ===")
    print(df.subperiod.value_counts())
    sub_rows = []
    for name, _, _ in SUBPERIODS:
        g = df[df.subperiod == name]
        b0 = block(g, "gross_R")
        b5v = block(g, "net_R_5bps")
        row = dict(subperiod=name, trades=b0["trades"], win_rate=b0["win_rate"],
                   gross_r=b0["total_r"], gross_expectancy=b0["expectancy"],
                   r5bps=b5v["total_r"], expectancy_5bps=b5v["expectancy"])
        for col in ["screening_rr", "volume_surge_ratio", "atr_pct", "risk_pct"]:
            valid = g[[col, "gross_R"]].dropna()
            if len(valid) >= 5:
                sc = sstats.spearmanr(valid[col], valid["gross_R"])
                row[f"spearman_{col}_vs_gross"] = sc.statistic
                row[f"spearman_{col}_vs_gross_p"] = sc.pvalue
                row[f"spearman_{col}_n"] = len(valid)
            else:
                row[f"spearman_{col}_vs_gross"] = None
                row[f"spearman_{col}_vs_gross_p"] = None
                row[f"spearman_{col}_n"] = len(valid)
        stx_share = g.loc[g.symbol == "STX", "gross_R"].sum()
        row["stx_gross_r"] = stx_share
        row["stx_trades"] = (g.symbol == "STX").sum()
        sub_rows.append(row)
    sub_df = pd.DataFrame(sub_rows)
    sub_df.to_csv(OUT / "task17_subperiod_analysis.csv", index=False)
    print("wrote task17_subperiod_analysis.csv")

    def classify_stability(signs: list, pvals: list, ns: list, sig_level=0.10) -> str:
        valid = [(s, p, n) for s, p, n in zip(signs, pvals, ns) if s is not None and n >= 5]
        if len(valid) < 3:
            return "INSUFFICIENT_SAMPLE"
        pos_signs = [1 if s > 0 else (-1 if s < 0 else 0) for s, p, n in valid]
        if all(x == pos_signs[0] and x != 0 for x in pos_signs):
            any_sig = any(p < sig_level for s, p, n in valid)
            return "STABLE" if any_sig else "WEAK"
        if len(set(pos_signs)) > 1 and 0 not in pos_signs:
            return "CONTRADICTORY"
        return "REGIME_DEPENDENT"

    stability_rows = []
    for col in ["screening_rr", "volume_surge_ratio", "atr_pct", "risk_pct"]:
        signs = sub_df[f"spearman_{col}_vs_gross"].tolist()
        pvals = sub_df[f"spearman_{col}_vs_gross_p"].tolist()
        ns = sub_df[f"spearman_{col}_n"].tolist()
        cls = classify_stability(signs, pvals, ns)
        stability_rows.append(dict(relationship=f"{col} vs gross_R", per_period_spearman=signs,
                                    per_period_p=pvals, per_period_n=ns, classification=cls))
        print(f"{col} vs gross_R: {signs} -> {cls}")

    # ------------------------------------------------------------------
    # Section 14: leave-one-period-out check
    # ------------------------------------------------------------------
    print("\n=== Section 14: leave-one-period-out ===")
    loo_rows = []
    period_names = [s[0] for s in SUBPERIODS]
    for held_out in period_names:
        others = df[df.subperiod != held_out]
        held = df[df.subperiod == held_out]
        for col in ["screening_rr", "volume_surge_ratio", "atr_pct", "risk_pct"]:
            o_valid = others[[col, "gross_R"]].dropna()
            h_valid = held[[col, "gross_R"]].dropna()
            if len(o_valid) < 5 or len(h_valid) < 5:
                loo_rows.append(dict(held_out_period=held_out, variable=col, other3_spearman=None,
                                      held_out_spearman=None, same_direction=None, note="insufficient sample"))
                continue
            o_corr = sstats.spearmanr(o_valid[col], o_valid["gross_R"])
            h_corr = sstats.spearmanr(h_valid[col], h_valid["gross_R"])
            same_dir = (o_corr.statistic > 0) == (h_corr.statistic > 0)
            loo_rows.append(dict(held_out_period=held_out, variable=col, other3_spearman=o_corr.statistic,
                                  other3_n=len(o_valid), held_out_spearman=h_corr.statistic, held_out_n=len(h_valid),
                                  same_direction=same_dir))
    loo_df = pd.DataFrame(loo_rows)
    loo_df.to_csv(OUT / "task17_leave_one_period_out.csv", index=False)
    print("wrote task17_leave_one_period_out.csv")
    print(loo_df.to_string(index=False))

    # ------------------------------------------------------------------
    # Section 15 (output): cost-margin population
    # ------------------------------------------------------------------
    df["survives_5bps"] = df["net_R_5bps"] > 0
    cm_rows = []
    for label, g in [("5bps_net_R>0", df[df.survives_5bps]), ("5bps_net_R<=0", df[~df.survives_5bps])]:
        row = dict(group=label, trades=len(g))
        for col in ["gross_R", "atr_pct", "risk_pct", "screening_rr", "execution_rr", "volume_surge_ratio"]:
            row[f"{col}_median"] = g[col].median()
            row[f"{col}_mean"] = g[col].mean()
        cm_rows.append(row)
    pd.DataFrame(cm_rows).to_csv(OUT / "task17_cost_margin.csv", index=False)
    print("wrote task17_cost_margin.csv")
    print(f"\ntrades surviving 5bps: {df.survives_5bps.sum()} / {len(df)} "
          f"({df.survives_5bps.sum()/len(df)*100:.1f}%)")

    diag = dict(
        outcome_counts=df.outcome.value_counts().to_dict(),
        confluence_unique_values=confluence_unique,
        cost_margin_reconciliation_max_diff=float(recon_diff),
        stability_classifications={r["relationship"]: r["classification"] for r in stability_rows},
        symbol_totals={row["symbol"]: row["gross_r"] for row in sym_rows},
        trades_surviving_5bps=int(df.survives_5bps.sum()), total_trades=len(df),
    )
    (OUT / "_diag_scratch.json").write_text(json.dumps(diag, indent=2, default=str))
    print("\nAll sections complete.")
