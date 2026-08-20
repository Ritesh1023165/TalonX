"""
Task 19 -- Exit-Path & Stop-Out Anatomy Audit.

DIAGNOSTIC ONLY. Explains why ~77% of trades exit STOP while a small
TARGET/EOD population carries almost all gross edge, and tests whether
STOP vs TARGET/EOD is associated with stable PRE-ENTRY characteristics.
Built from Task 17's feature table + Task 16's fill-movement table -- no
replay.

Strict pre-entry/post-entry discipline: only pre-entry fields are used as
candidate predictors (Section 3). Post-entry fields (holding time, MFE,
MAE) are used ONLY for descriptive anatomy (Sections 14-16), never as
model inputs.

Deterministic. Logistic regression via sklearn (unregularized, penalty=
None) with a hand-computed Hessian-based covariance for Wald p-values,
since statsmodels is not installed.
"""
import json
import sys
from pathlib import Path
from datetime import time as dtime
from zoneinfo import ZoneInfo

import numpy as np
import pandas as pd
from scipy import stats as sstats
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import roc_auc_score

REPO = Path("c:/workspace/TalonX")
sys.path.insert(0, str(REPO))

OUT = REPO / "results" / "task19_exit_path_audit"
OUT.mkdir(parents=True, exist_ok=True)

RAW_DATA_DIR = REPO / "data" / "historical_1m" / "task7b_alpaca_long_history"
TASK17_FEATURES = REPO / "results" / "task17_gross_edge_audit" / "task17_trade_features.csv"
TASK16_GEOMETRY = REPO / "results" / "task16_entry_risk_audit" / "task16_trade_geometry.csv"

EXPECTED_TOTAL_R_0 = 75.97580943135327
EXPECTED_TOTAL_R_5 = -21.41375894722095

_ET = ZoneInfo("America/New_York")
_FIRST_30M_START, _FIRST_30M_END, _LAST_HOUR_START, _REGULAR_END = (
    dtime(9, 30), dtime(10, 0), dtime(15, 0), dtime(16, 0))


def time_of_day_bucket(ts) -> str:
    local = ts.astimezone(_ET).time()
    if local < _FIRST_30M_START:
        return "premarket"
    if local < _FIRST_30M_END:
        return "OPENING"
    if local < _LAST_HOUR_START:
        return "MIDDAY"
    if local < _REGULAR_END:
        return "LATE_SESSION"
    return "after_hours"


def corr_pair(x: pd.Series, y: pd.Series) -> dict:
    valid = pd.concat([x, y], axis=1).dropna()
    if len(valid) < 8:
        return dict(n=len(valid), spearman_r=None, spearman_p=None)
    s = sstats.spearmanr(valid.iloc[:, 0], valid.iloc[:, 1])
    return dict(n=len(valid), spearman_r=s.statistic, spearman_p=s.pvalue)


def classify_stability(signs, ns, sig_dummy=None) -> str:
    valid = [s for s, n in zip(signs, ns) if s is not None and n >= 5]
    if len(valid) < 3:
        return "INSUFFICIENT_SAMPLE"
    pos = [1 if v > 0 else (-1 if v < 0 else 0) for v in valid]
    if all(v == pos[0] and v != 0 for v in pos):
        return "STABLE" if max(abs(v) for v in valid) > 0.2 else "WEAK"
    if len(set(pos)) > 1 and 0 not in pos:
        return "CONTRADICTORY"
    return "REGIME_DEPENDENT"


def block(g: pd.DataFrame, r_col: str) -> dict:
    r = g[r_col].dropna()
    total = r.sum() if len(r) else None
    avg = r.mean() if len(r) else None
    med = r.median() if len(r) else None
    return dict(trades=len(g), total_r=total, avg_r=avg, median_r=med)


if __name__ == "__main__":
    print("=== Section 2: Integrity ===")
    t17 = pd.read_csv(TASK17_FEATURES, parse_dates=["signal_timestamp", "entry_timestamp"])
    for c in ["signal_timestamp", "entry_timestamp"]:
        t17[c] = pd.to_datetime(t17[c], utc=True)
    t16 = pd.read_csv(TASK16_GEOMETRY)[["trade_id", "fill_move_pct", "fill_move_adverse_pct",
                                          "signal_to_fill_min", "cost_to_risk_5bps", "risk_preservation_ratio_pct"]]
    df = t17.merge(t16, on="trade_id", how="left", suffixes=("", "_t16"))

    problems = []
    if len(df) != 181:
        problems.append(f"{len(df)} trades, expected 181")
    if abs(df["gross_R"].sum() - EXPECTED_TOTAL_R_0) > 1e-6:
        problems.append(f"0bps total {df['gross_R'].sum()} != {EXPECTED_TOTAL_R_0}")
    if abs(df["net_R_5bps"].sum() - EXPECTED_TOTAL_R_5) > 1e-6:
        problems.append(f"5bps total {df['net_R_5bps'].sum()} != {EXPECTED_TOTAL_R_5}")
    from talonx_backtest.reproducibility import get_dataset_hash, get_git_commit
    dh = get_dataset_hash(str(RAW_DATA_DIR))
    if dh != "5e5412a960bf":
        problems.append(f"dataset_hash mismatch: {dh}")
    exit_counts = df.exit_reason.value_counts().to_dict()
    print("exit_reason counts:", exit_counts)
    if problems:
        for p in problems:
            print("FAIL:", p)
        raise SystemExit("Integrity check failed.")
    print(f"OK -- 181 trades, dataset_hash={dh}, git_commit={get_git_commit()}")

    df["time_of_day"] = df["entry_timestamp"].apply(time_of_day_bucket)
    df["fill_move_adverse_over_atr"] = df["fill_move_adverse_pct"] / df["atr_pct"]
    df["is_stop"] = (df.exit_reason == "STOP").astype(int)

    # ------------------------------------------------------------------
    # Section 4: exit-class baseline
    # ------------------------------------------------------------------
    baseline_rows = []
    for reason, g in df.groupby("exit_reason"):
        b0 = block(g, "gross_R")
        b5 = block(g, "net_R_5bps")
        baseline_rows.append(dict(
            exit_reason=reason, count=len(g), pct_of_trades=len(g) / len(df) * 100,
            gross_total_r=b0["total_r"], r5bps_total=b5["total_r"], avg_r_gross=b0["avg_r"],
            median_r_gross=b0["median_r"], symbols=",".join(sorted(g.symbol.unique())),
            directions=g.direction.value_counts().to_dict(), sessions=g.entry_session.value_counts().to_dict(),
            subperiods=g.subperiod.value_counts().to_dict(),
        ))
    pd.DataFrame(baseline_rows).to_csv(OUT / "task19_exit_baseline.csv", index=False)
    print("wrote task19_exit_baseline.csv")

    # ------------------------------------------------------------------
    # Section 5: pre-entry feature comparison across STOP/TARGET/EOD
    # ------------------------------------------------------------------
    PREENTRY_CONTINUOUS = ["atr_pct", "risk_pct", "risk_preservation_ratio_pct", "volume_surge_ratio",
                            "screening_rr", "execution_rr", "signal_to_fill_min", "fill_move_adverse_pct",
                            "fill_move_adverse_over_atr"]
    cmp_rows = []
    for col in PREENTRY_CONTINUOUS:
        row = dict(variable=col)
        for reason in ["STOP", "TARGET", "END_OF_SESSION"]:
            s = df.loc[df.exit_reason == reason, col].dropna()
            row[f"{reason}_n"] = len(s)
            row[f"{reason}_mean"] = s.mean() if len(s) else None
            row[f"{reason}_median"] = s.median() if len(s) else None
            row[f"{reason}_p25"] = s.quantile(0.25) if len(s) else None
            row[f"{reason}_p75"] = s.quantile(0.75) if len(s) else None
        # effect size: STOP vs (TARGET+EOD) -- Cohen's d
        stop_v = df.loc[df.exit_reason == "STOP", col].dropna()
        nonstop_v = df.loc[df.exit_reason != "STOP", col].dropna()
        if len(stop_v) > 1 and len(nonstop_v) > 1:
            pooled_sd = np.sqrt(((len(stop_v) - 1) * stop_v.var() + (len(nonstop_v) - 1) * nonstop_v.var()) /
                                 (len(stop_v) + len(nonstop_v) - 2))
            row["cohens_d_stop_vs_nonstop"] = (stop_v.mean() - nonstop_v.mean()) / pooled_sd if pooled_sd > 0 else None
            u = sstats.mannwhitneyu(stop_v, nonstop_v, alternative="two-sided")
            row["mannwhitney_p"] = u.pvalue
        cmp_rows.append(row)
    pd.DataFrame(cmp_rows).to_csv(OUT / "task19_preentry_comparison.csv", index=False)
    print("wrote task19_preentry_comparison.csv")

    # categorical
    cat_rows = []
    for col in ["symbol", "direction", "entry_session", "subperiod"]:
        for val, g in df.groupby(col):
            n = len(g)
            cat_rows.append(dict(variable=col, value=val, trades=n,
                                  stop_rate=(g.exit_reason == "STOP").mean(),
                                  target_rate=(g.exit_reason == "TARGET").mean(),
                                  eod_rate=(g.exit_reason == "END_OF_SESSION").mean()))
    pd.DataFrame(cat_rows).to_csv(OUT / "task19_preentry_comparison_categorical.csv", index=False)
    print("wrote task19_preentry_comparison_categorical.csv (supplementary)")

    # ------------------------------------------------------------------
    # Section 6: STOP vs non-STOP descriptive logistic model (pre-entry only)
    # ------------------------------------------------------------------
    print("\n=== Section 6: STOP logistic model ===")
    model_df = df.dropna(subset=["atr_pct", "volume_surge_ratio", "screening_rr", "signal_to_fill_min",
                                  "risk_preservation_ratio_pct", "symbol", "direction", "session_bucket", "subperiod"]).copy()
    cont_feats = ["atr_pct", "volume_surge_ratio", "screening_rr", "signal_to_fill_min", "risk_preservation_ratio_pct"]
    Xc = model_df[cont_feats].to_numpy(dtype=float)
    # standardize continuous features for interpretable, comparable coefficients
    Xc_mean, Xc_std = Xc.mean(axis=0), Xc.std(axis=0)
    Xc_z = (Xc - Xc_mean) / Xc_std
    cat_dummies = pd.get_dummies(model_df[["symbol", "session_bucket", "direction", "subperiod"]], drop_first=True)
    X = np.column_stack([Xc_z, cat_dummies.to_numpy(dtype=float)])
    names = cont_feats + cat_dummies.columns.tolist()
    y = model_df["is_stop"].to_numpy()

    clf = LogisticRegression(penalty=None, max_iter=2000)
    clf.fit(X, y)
    p_hat = clf.predict_proba(X)[:, 1]
    auc = roc_auc_score(y, p_hat)

    # Hessian-based covariance (standard MLE logistic SEs)
    Xd = np.column_stack([np.ones(len(X)), X])
    W = np.diag(p_hat * (1 - p_hat))
    hessian = Xd.T @ W @ Xd
    cov = np.linalg.pinv(hessian)
    se = np.sqrt(np.clip(np.diag(cov), 0, None))
    coefs_full = np.concatenate([[clf.intercept_[0]], clf.coef_[0]])
    z = coefs_full / se
    p_vals = 2 * (1 - sstats.norm.cdf(np.abs(z)))
    stop_model_df = pd.DataFrame(dict(term=["intercept"] + names, coef=coefs_full, se=se, z=z, p=p_vals))
    stop_model_df["auc"] = auc
    stop_model_df["n"] = len(y)
    stop_model_df["stop_rate"] = y.mean()
    stop_model_df["model"] = "full_with_categorical_dummies"

    # Robustness check: the full model above has 19 parameters for n=179,
    # including sparse categories (AAPL/MSFT/GOOGL: 1-3 trades each) that
    # perfectly predict their outcome -- visible in the huge intercept/
    # session SEs (~6153) above, a classic quasi-separation symptom. Refit
    # a small, continuous-features-only model as the task instructs
    # ("prefer a small interpretable model") to see whether the same
    # continuous effects hold without categorical-dummy instability.
    clf2 = LogisticRegression(penalty=None, max_iter=2000)
    clf2.fit(Xc_z, y)
    p_hat2 = clf2.predict_proba(Xc_z)[:, 1]
    auc2 = roc_auc_score(y, p_hat2)
    Xd2 = np.column_stack([np.ones(len(Xc_z)), Xc_z])
    W2 = np.diag(p_hat2 * (1 - p_hat2))
    hessian2 = Xd2.T @ W2 @ Xd2
    cov2 = np.linalg.pinv(hessian2)
    se2 = np.sqrt(np.clip(np.diag(cov2), 0, None))
    coefs2 = np.concatenate([[clf2.intercept_[0]], clf2.coef_[0]])
    z2 = coefs2 / se2
    p2 = 2 * (1 - sstats.norm.cdf(np.abs(z2)))
    reduced_df = pd.DataFrame(dict(term=["intercept"] + cont_feats, coef=coefs2, se=se2, z=z2, p=p2))
    reduced_df["auc"] = auc2
    reduced_df["n"] = len(y)
    reduced_df["stop_rate"] = y.mean()
    reduced_df["model"] = "reduced_continuous_only"
    print("\n--- reduced (continuous-only) model, robustness check ---")
    print(reduced_df.to_string(index=False))
    print(f"reduced-model AUC = {auc2:.4f} (vs full model AUC = {auc:.4f} -- the full model's higher AUC is "
          f"driven by memorizing tiny sparse symbol categories, not genuine continuous-feature power)")

    pd.concat([stop_model_df, reduced_df], ignore_index=True).to_csv(OUT / "task19_stop_model.csv", index=False)
    print(f"\nAUC = {auc:.4f}, n = {len(y)}, stop_rate = {y.mean():.4f}")

    # ------------------------------------------------------------------
    # Section 7: TARGET vs EOD (pre-entry features)
    # ------------------------------------------------------------------
    print("\n=== Section 7: TARGET vs EOD ===")
    tv_rows = []
    for col in PREENTRY_CONTINUOUS:
        t_v = df.loc[df.exit_reason == "TARGET", col].dropna()
        e_v = df.loc[df.exit_reason == "END_OF_SESSION", col].dropna()
        if len(t_v) > 2 and len(e_v) > 2:
            u = sstats.mannwhitneyu(t_v, e_v, alternative="two-sided")
            tv_rows.append(dict(variable=col, target_median=t_v.median(), eod_median=e_v.median(),
                                 target_n=len(t_v), eod_n=len(e_v), mannwhitney_p=u.pvalue))
    pd.DataFrame(tv_rows).to_csv(OUT / "task19_target_vs_eod.csv", index=False)
    print("wrote task19_target_vs_eod.csv (supplementary)")

    # ------------------------------------------------------------------
    # Section 8: symbol control -- CRITICAL
    # ------------------------------------------------------------------
    print("\n=== Section 8: STOP rate by symbol ===")
    sym_rows = []
    for sym, g in df.groupby("symbol"):
        b0 = block(g, "gross_R")
        b5 = block(g, "net_R_5bps")
        sym_rows.append(dict(symbol=sym, trades=len(g), stop_pct=(g.exit_reason == "STOP").mean() * 100,
                              target_pct=(g.exit_reason == "TARGET").mean() * 100,
                              eod_pct=(g.exit_reason == "END_OF_SESSION").mean() * 100,
                              gross_r=b0["total_r"], r5bps=b5["total_r"]))
    sym_df = pd.DataFrame(sym_rows).sort_values("trades", ascending=False)
    sym_df.to_csv(OUT / "task19_symbol_exit_rates.csv", index=False)
    print(sym_df.to_string(index=False))
    overall_stop_rate = (df.exit_reason == "STOP").mean() * 100
    print(f"Overall STOP rate: {overall_stop_rate:.1f}%")

    # ------------------------------------------------------------------
    # Section 9: symbol-adjusted feature analysis (spot-check top features)
    # ------------------------------------------------------------------
    print("\n=== Section 9: symbol-adjusted (demeaned) checks ===")
    adj_rows = []
    for col in ["atr_pct", "volume_surge_ratio", "risk_preservation_ratio_pct", "fill_move_adverse_pct"]:
        raw = corr_pair(df[col], df["is_stop"])
        demeaned_x = df[col] - df.groupby("symbol")[col].transform("mean")
        demeaned_y = df["is_stop"] - df.groupby("symbol")["is_stop"].transform("mean")
        adj = corr_pair(demeaned_x, demeaned_y)
        adj_rows.append(dict(variable=col, raw_spearman=raw["spearman_r"], raw_p=raw["spearman_p"],
                              symbol_demeaned_spearman=adj["spearman_r"], symbol_demeaned_p=adj["spearman_p"]))
        print(col, raw, "-> demeaned:", adj)
    pd.DataFrame(adj_rows).to_csv(OUT / "task19_symbol_adjusted.csv", index=False)
    print("wrote task19_symbol_adjusted.csv (supplementary)")

    # ------------------------------------------------------------------
    # Section 10: temporal stability of STOP-rate + LOO
    # ------------------------------------------------------------------
    print("\n=== Section 10/11: subperiod composition + LOO ===")
    sub_rows = []
    for name, g in df.groupby("subperiod"):
        sub_rows.append(dict(subperiod=name, trades=len(g), stop_pct=(g.exit_reason == "STOP").mean() * 100,
                              target_pct=(g.exit_reason == "TARGET").mean() * 100,
                              eod_pct=(g.exit_reason == "END_OF_SESSION").mean() * 100,
                              gross_r=g.gross_R.sum(), r5bps=g.net_R_5bps.sum()))
    sub_df = pd.DataFrame(sub_rows)
    sub_df.to_csv(OUT / "task19_subperiod_exit_rates.csv", index=False)
    print(sub_df.to_string(index=False))

    loo_rows = []
    period_names = sub_df.subperiod.tolist()
    for held_out in period_names:
        others = df[df.subperiod != held_out]
        held = df[df.subperiod == held_out]
        for col in ["atr_pct", "volume_surge_ratio", "fill_move_adverse_pct", "risk_preservation_ratio_pct"]:
            o = corr_pair(others[col], others["is_stop"])
            h = corr_pair(held[col], held["is_stop"])
            same_dir = None
            if o["spearman_r"] is not None and h["spearman_r"] is not None:
                same_dir = (o["spearman_r"] > 0) == (h["spearman_r"] > 0)
            loo_rows.append(dict(held_out_period=held_out, variable=col, other3_spearman=o["spearman_r"],
                                  other3_n=o["n"], held_out_spearman=h["spearman_r"], held_out_n=h["n"],
                                  same_direction=same_dir))
    loo_df = pd.DataFrame(loo_rows)
    loo_df.to_csv(OUT / "task19_leave_one_period_out.csv", index=False)
    print("wrote task19_leave_one_period_out.csv (supplementary)")

    # ------------------------------------------------------------------
    # Section 12: time-of-day / session exit rates
    # ------------------------------------------------------------------
    tod_rows = []
    for bucket, g in df.groupby("time_of_day"):
        tod_rows.append(dict(time_of_day=bucket, trades=len(g), stop_pct=(g.exit_reason == "STOP").mean() * 100,
                              target_pct=(g.exit_reason == "TARGET").mean() * 100,
                              eod_pct=(g.exit_reason == "END_OF_SESSION").mean() * 100,
                              gross_r=g.gross_R.sum()))
    for bucket, g in df.groupby("session_bucket"):
        tod_rows.append(dict(time_of_day=f"session:{bucket}", trades=len(g), stop_pct=(g.exit_reason == "STOP").mean() * 100,
                              target_pct=(g.exit_reason == "TARGET").mean() * 100,
                              eod_pct=(g.exit_reason == "END_OF_SESSION").mean() * 100,
                              gross_r=g.gross_R.sum()))
    pd.DataFrame(tod_rows).to_csv(OUT / "task19_timeofday_exit_rates.csv", index=False)
    print("wrote task19_timeofday_exit_rates.csv")

    # ------------------------------------------------------------------
    # Section 13: signal->fill movement vs exit class
    # ------------------------------------------------------------------
    fm_rows = []
    for reason, g in df.groupby("exit_reason"):
        fm_rows.append(dict(exit_reason=reason, trades=len(g),
                             median_fill_move_adverse_pct=g.fill_move_adverse_pct.median(),
                             median_fill_move_adverse_over_atr=g.fill_move_adverse_over_atr.median(),
                             median_signal_to_fill_min=g.signal_to_fill_min.median()))
    c1 = corr_pair(df["fill_move_adverse_pct"], df["is_stop"])
    c2 = corr_pair(df["fill_move_adverse_over_atr"], df["is_stop"])
    fm_rows.append(dict(exit_reason="SPEARMAN_vs_is_stop", trades=c1["n"],
                         median_fill_move_adverse_pct=c1["spearman_r"],
                         median_fill_move_adverse_over_atr=c2["spearman_r"], median_signal_to_fill_min=None))
    pd.DataFrame(fm_rows).to_csv(OUT / "task19_fill_movement.csv", index=False)
    print("\n=== Section 13: fill movement vs exit class ===")
    print(pd.DataFrame(fm_rows).to_string(index=False))

    # ------------------------------------------------------------------
    # Section 14/15/16: excursion anatomy, stop speed, cost-by-speed (POST-ENTRY, descriptive only)
    # ------------------------------------------------------------------
    stops = df[df.exit_reason == "STOP"].copy()
    stops["holding_min"] = stops["holding_seconds"] / 60.0

    def excursion_class(row):
        # mfe_r >0 for bullish/bearish alike is favorable excursion in R terms
        if row.mfe_r is None or pd.isna(row.mfe_r):
            return "UNKNOWN"
        if row.mfe_r <= 0.1:
            return "A_near_immediate_stop"
        if row.mfe_r >= 0.5:
            return "C_meaningful_favorable_move_then_stop"
        return "B_modest_favorable_move_then_stop"
    stops["excursion_class"] = stops.apply(excursion_class, axis=1)
    anatomy_rows = []
    for cls, g in stops.groupby("excursion_class"):
        anatomy_rows.append(dict(excursion_class=cls, trades=len(g), pct_of_stops=len(g) / len(stops) * 100,
                                  median_mfe_r=g.mfe_r.median(), median_holding_min=g.holding_min.median(),
                                  gross_r=g.gross_R.sum(), r5bps=g.net_R_5bps.sum()))
    pd.DataFrame(anatomy_rows).to_csv(OUT / "task19_stop_anatomy.csv", index=False)
    print("\n=== Section 14: STOP excursion anatomy ===")
    print(pd.DataFrame(anatomy_rows).to_string(index=False))

    speed_buckets = [("<2min", 0, 2), ("2-5min", 2, 5), ("5-15min", 5, 15), ("15-60min", 15, 60), (">60min", 60, np.inf)]
    def speed_label(m):
        for label, lo, hi in speed_buckets:
            if lo <= m < hi:
                return label
        return speed_buckets[-1][0]
    stops["speed_bucket"] = stops["holding_min"].apply(speed_label)
    speed_rows = []
    for label, _, _ in speed_buckets:
        g = stops[stops.speed_bucket == label]
        if g.empty:
            speed_rows.append(dict(speed_bucket=label, trades=0))
            continue
        speed_rows.append(dict(speed_bucket=label, trades=len(g), symbols=",".join(sorted(g.symbol.unique())),
                                sessions=",".join(sorted(g.entry_session.unique())), median_mfe_r=g.mfe_r.median(),
                                median_atr_pct=g.atr_pct.median(), median_volume_surge=g.volume_surge_ratio.median()))
    pd.DataFrame(speed_rows).to_csv(OUT / "task19_stop_speed.csv", index=False)
    print("\n=== Section 15: STOP speed ===")
    print(pd.DataFrame(speed_rows).to_string(index=False))
    immediate_pct = (stops.speed_bucket == "<2min").mean() * 100
    print(f"Fraction of STOPs that are <2min ('immediate failed entry'): {immediate_pct:.1f}%")

    cost_speed_rows = []
    for label, _, _ in speed_buckets:
        g = stops[stops.speed_bucket == label]
        if g.empty:
            continue
        cost_speed_rows.append(dict(speed_bucket=label, trades=len(g), gross_r=g.gross_R.sum(),
                                     r5bps=g.net_R_5bps.sum(), deterioration=g.gross_R.sum() - g.net_R_5bps.sum(),
                                     deterioration_per_trade=(g.gross_R.sum() - g.net_R_5bps.sum()) / len(g)))
    pd.DataFrame(cost_speed_rows).to_csv(OUT / "task19_cost_by_stop_speed.csv", index=False)
    print("\n=== Section 16: cost deterioration by STOP speed ===")
    print(pd.DataFrame(cost_speed_rows).to_string(index=False))

    # ------------------------------------------------------------------
    # Section 17: R:R revisit -- does RR predict exit path (not realized R)?
    # ------------------------------------------------------------------
    print("\n=== Section 17: R:R vs exit path ===")
    rr_rows = []
    for col in ["screening_rr", "execution_rr"]:
        row = dict(variable=col)
        groups = [df.loc[df.exit_reason == r, col].dropna() for r in ["STOP", "TARGET", "END_OF_SESSION"]]
        row["STOP_median"], row["TARGET_median"], row["EOD_median"] = [g.median() if len(g) else None for g in groups]
        if all(len(g) > 2 for g in groups):
            kw = sstats.kruskal(*groups)
            row["kruskal_wallis_p"] = kw.pvalue
        c = corr_pair(df[col], df["is_stop"])
        row["spearman_vs_is_stop"] = c["spearman_r"]
        row["spearman_vs_is_stop_p"] = c["spearman_p"]
        rr_rows.append(row)
    pd.DataFrame(rr_rows).to_csv(OUT / "task19_rr_exit_analysis.csv", index=False)
    print(pd.DataFrame(rr_rows).to_string(index=False))

    # ------------------------------------------------------------------
    # Section 18: confluence check
    # ------------------------------------------------------------------
    confluence_unique = sorted(df.confluence_score.dropna().unique().tolist())
    print(f"\n=== Section 18: confluence_score unique values = {confluence_unique} ===")

    # ------------------------------------------------------------------
    # Section 21: OOS candidates
    # ------------------------------------------------------------------
    oos_rows = []
    for col in ["atr_pct", "volume_surge_ratio", "fill_move_adverse_pct", "risk_preservation_ratio_pct"]:
        loo_sub = loo_df[loo_df.variable == col]
        n_same = loo_sub.same_direction.sum() if loo_sub.same_direction.notna().any() else 0
        n_valid = loo_sub.same_direction.notna().sum()
        raw = corr_pair(df[col], df["is_stop"])
        demeaned_row = [r for r in adj_rows if r["variable"] == col][0]
        label = "CANDIDATE_FOR_OOS_VALIDATION" if (n_valid > 0 and n_same == n_valid and
                                                    demeaned_row["symbol_demeaned_p"] is not None and
                                                    demeaned_row["symbol_demeaned_p"] < 0.10) else "NOT_A_CANDIDATE"
        oos_rows.append(dict(variable=col, raw_spearman_vs_is_stop=raw["spearman_r"], raw_p=raw["spearman_p"],
                              symbol_demeaned_spearman=demeaned_row["symbol_demeaned_spearman"],
                              symbol_demeaned_p=demeaned_row["symbol_demeaned_p"],
                              loo_same_direction_count=f"{n_same}/{n_valid}", label=label))
    pd.DataFrame(oos_rows).to_csv(OUT / "task19_oos_candidates.csv", index=False)
    print("\n=== Section 21: OOS candidates ===")
    print(pd.DataFrame(oos_rows).to_string(index=False))

    diag = dict(
        exit_counts=exit_counts, overall_stop_rate=overall_stop_rate, auc=auc,
        confluence_unique_values=confluence_unique, immediate_stop_pct=immediate_pct,
    )
    (OUT / "_diag_scratch.json").write_text(json.dumps(diag, indent=2, default=str))
    print("\nAll sections complete.")
