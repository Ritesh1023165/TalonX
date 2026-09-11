"""
Task 18 -- Volume Relationship Confounding Audit.

DIAGNOSTIC ONLY. Tests whether Task 17's negative volume_surge_ratio-vs-
gross_R relationship survives controlling for symbol, session, regime,
holding time, exit type, and direction. Built entirely from Task 17's
trade-feature table -- no replay.

Deterministic, no randomness. OLS with HC3 robust errors implemented by
hand (numpy/scipy) since statsmodels is not installed in this environment.
"""
import json
import sys
from pathlib import Path
from datetime import time as dtime
from zoneinfo import ZoneInfo

import numpy as np
import pandas as pd
from scipy import stats as sstats

REPO = Path("c:/workspace/TalonX")
sys.path.insert(0, str(REPO))

OUT = REPO / "results" / "task18_volume_confounding"
OUT.mkdir(parents=True, exist_ok=True)

RAW_DATA_DIR = REPO / "data" / "historical_1m" / "task7b_alpaca_long_history"
TASK17_FEATURES = REPO / "results" / "task17_gross_edge_audit" / "task17_trade_features.csv"

EXPECTED_TOTAL_R_0 = 75.97580943135327
EXPECTED_TOTAL_R_5 = -21.41375894722095

_ET = ZoneInfo("America/New_York")
# Reused verbatim from talonx_backtest.analysis._time_of_day_bucket's own
# boundaries (09:30/10:00/15:00/16:00 ET) -- not invented here.
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
    if len(valid) < 3:
        return dict(n=len(valid), pearson_r=None, pearson_p=None, spearman_r=None, spearman_p=None)
    p = sstats.pearsonr(valid.iloc[:, 0], valid.iloc[:, 1])
    s = sstats.spearmanr(valid.iloc[:, 0], valid.iloc[:, 1])
    return dict(n=len(valid), pearson_r=p.statistic, pearson_p=p.pvalue, spearman_r=s.statistic, spearman_p=s.pvalue)


def classify_relationship(spearman_r, p, n, sig=0.10, flat_band=0.05) -> str:
    if n < 8:
        return "INSUFFICIENT_SAMPLE"
    if spearman_r is None:
        return "INSUFFICIENT_SAMPLE"
    if abs(spearman_r) < flat_band:
        return "FLAT"
    return "NEGATIVE" if spearman_r < 0 else "POSITIVE"


def block(g: pd.DataFrame, r_col: str) -> dict:
    r = g[r_col].dropna()
    wins, losses = r[r > 0], r[r < 0]
    total = r.sum() if len(r) else None
    expectancy = r.mean() if len(r) else None
    win_rate = len(wins) / len(r) if len(r) else None
    return dict(trades=len(g), total_r=total, expectancy=expectancy, win_rate=win_rate)


# ------------------------------------------------------------------
# OLS with HC3 robust errors -- hand-rolled (no statsmodels installed)
# ------------------------------------------------------------------

def ols_hc3(y: np.ndarray, X: np.ndarray, names: list[str]) -> pd.DataFrame:
    n, k = X.shape
    XtX_inv = np.linalg.pinv(X.T @ X)
    beta = XtX_inv @ X.T @ y
    resid = y - X @ beta
    H = X @ XtX_inv @ X.T
    h = np.clip(np.diag(H), 0, 1 - 1e-10)
    meat = X * (resid[:, None] ** 2 / (1 - h[:, None]) ** 2)
    cov = XtX_inv @ (X.T @ meat) @ XtX_inv
    se = np.sqrt(np.clip(np.diag(cov), 0, None))
    t_stat = beta / se
    df = max(n - k, 1)
    p = 2 * (1 - sstats.t.cdf(np.abs(t_stat), df))
    ci_lo = beta - 1.96 * se
    ci_hi = beta + 1.96 * se
    r2 = 1 - (resid ** 2).sum() / ((y - y.mean()) ** 2).sum()
    return pd.DataFrame(dict(term=names, coef=beta, se=se, t=t_stat, p=p, ci_lo=ci_lo, ci_hi=ci_hi)), r2, n


def build_design(df: pd.DataFrame, cont_cols: list[str], cat_cols: list[str]) -> tuple[np.ndarray, list[str]]:
    n = len(df)
    cols = [np.ones(n)]
    names = ["intercept"]
    for c in cont_cols:
        v = df[c].to_numpy(dtype=float)
        cols.append(v)
        names.append(c)
    for c in cat_cols:
        dummies = pd.get_dummies(df[c], prefix=c, drop_first=True)
        for col in dummies.columns:
            cols.append(dummies[col].to_numpy(dtype=float))
            names.append(col)
    return np.column_stack(cols), names


if __name__ == "__main__":
    print("=== Section 2: Integrity ===")
    if not TASK17_FEATURES.exists():
        raise SystemExit(f"Task 17 features missing: {TASK17_FEATURES} -- cannot proceed without it (no replay allowed).")
    df = pd.read_csv(TASK17_FEATURES, parse_dates=["signal_timestamp", "entry_timestamp"])
    for c in ["signal_timestamp", "entry_timestamp"]:
        df[c] = pd.to_datetime(df[c], utc=True)
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
    if problems:
        for p in problems:
            print("FAIL:", p)
        raise SystemExit("Integrity check failed.")
    print(f"OK -- 181 trades, dataset_hash={dh}, git_commit={get_git_commit()}")

    df["time_of_day"] = df["entry_timestamp"].apply(time_of_day_bucket)

    # ------------------------------------------------------------------
    # Section 3: raw volume relationship (reproduce Task 17)
    # ------------------------------------------------------------------
    raw_gross = corr_pair(df["volume_surge_ratio"], df["gross_R"])
    raw_5bps = corr_pair(df["volume_surge_ratio"], df["net_R_5bps"])
    print("\n=== Section 3: raw relationship ===")
    print("vs gross_R:", raw_gross)
    print("vs 5bps_R:", raw_5bps)

    df["volume_quartile"] = pd.qcut(df["volume_surge_ratio"], 4, labels=["Q1_lowest", "Q2", "Q3", "Q4_highest"])
    raw_rows = []
    for q, g in df.groupby("volume_quartile", observed=True):
        b0 = block(g, "gross_R")
        b5 = block(g, "net_R_5bps")
        raw_rows.append(dict(volume_quartile=str(q), trades=b0["trades"], win_rate=b0["win_rate"],
                              gross_expectancy=b0["expectancy"], expectancy_5bps=b5["expectancy"],
                              range_min=g.volume_surge_ratio.min(), range_max=g.volume_surge_ratio.max()))
    raw_summary = dict(pearson_gross=raw_gross, spearman_gross=raw_gross, vs_5bps=raw_5bps)
    pd.DataFrame(raw_rows).to_csv(OUT / "task18_raw_volume.csv", index=False)
    print("wrote task18_raw_volume.csv")

    # ------------------------------------------------------------------
    # Section 4: within-symbol analysis -- CRITICAL
    # ------------------------------------------------------------------
    print("\n=== Section 4: within-symbol ===")
    ws_rows = []
    for sym, g in df.groupby("symbol"):
        c_gross = corr_pair(g["volume_surge_ratio"], g["gross_R"])
        c_5bps = corr_pair(g["volume_surge_ratio"], g["net_R_5bps"])
        cls = classify_relationship(c_gross["spearman_r"], c_gross["spearman_p"], c_gross["n"])
        ws_rows.append(dict(symbol=sym, trades=len(g), spearman_vs_gross=c_gross["spearman_r"],
                             spearman_vs_gross_p=c_gross["spearman_p"], spearman_vs_5bps=c_5bps["spearman_r"],
                             spearman_vs_5bps_p=c_5bps["spearman_p"], classification=cls))
        print(sym, len(g), c_gross["spearman_r"], cls)
    pd.DataFrame(ws_rows).sort_values("trades", ascending=False).to_csv(OUT / "task18_within_symbol.csv", index=False)
    print("wrote task18_within_symbol.csv")

    # pooled within-symbol (demeaned) correlation
    df["volume_demeaned_by_symbol"] = df["volume_surge_ratio"] - df.groupby("symbol")["volume_surge_ratio"].transform("mean")
    df["gross_R_demeaned_by_symbol"] = df["gross_R"] - df.groupby("symbol")["gross_R"].transform("mean")
    df["net5_demeaned_by_symbol"] = df["net_R_5bps"] - df.groupby("symbol")["net_R_5bps"].transform("mean")
    pooled_within_gross = corr_pair(df["volume_demeaned_by_symbol"], df["gross_R_demeaned_by_symbol"])
    pooled_within_5bps = corr_pair(df["volume_demeaned_by_symbol"], df["net5_demeaned_by_symbol"])
    print("pooled within-symbol (demeaned) vs gross_R:", pooled_within_gross)
    print("pooled within-symbol (demeaned) vs 5bps_R:", pooled_within_5bps)

    # ------------------------------------------------------------------
    # Section 5: symbol exclusion analysis
    # ------------------------------------------------------------------
    excl_rows = []
    for label, symbols in [("ALL_TRADES", []), ("EXCLUDING_STX", ["STX"]), ("EXCLUDING_AMD", ["AMD"]),
                            ("EXCLUDING_PYPL", ["PYPL"]), ("EXCLUDING_STX_AMD", ["STX", "AMD"]),
                            ("EXCLUDING_STX_AMD_PYPL", ["STX", "AMD", "PYPL"])]:
        g = df[~df.symbol.isin(symbols)] if symbols else df
        c_gross = corr_pair(g["volume_surge_ratio"], g["gross_R"])
        c_5bps = corr_pair(g["volume_surge_ratio"], g["net_R_5bps"])
        excl_rows.append(dict(view=label, trades=len(g), spearman_vs_gross=c_gross["spearman_r"],
                               spearman_vs_gross_p=c_gross["spearman_p"], spearman_vs_5bps=c_5bps["spearman_r"]))
    pd.DataFrame(excl_rows).to_csv(OUT / "task18_symbol_exclusions.csv", index=False)
    print("wrote task18_symbol_exclusions.csv")

    # ------------------------------------------------------------------
    # Section 6: session control
    # ------------------------------------------------------------------
    sess_rows = []
    for bucket, g in df.groupby("session_bucket"):
        c_gross = corr_pair(g["volume_surge_ratio"], g["gross_R"])
        b0 = block(g, "gross_R")
        b5 = block(g, "net_R_5bps")
        sess_rows.append(dict(session_bucket=bucket, trades=len(g), gross_expectancy=b0["expectancy"],
                               expectancy_5bps=b5["expectancy"], spearman_vs_gross=c_gross["spearman_r"],
                               spearman_vs_gross_p=c_gross["spearman_p"], spearman_n=c_gross["n"]))
    pd.DataFrame(sess_rows).to_csv(OUT / "task18_session_analysis.csv", index=False)
    print("wrote task18_session_analysis.csv")

    # ------------------------------------------------------------------
    # Section 7: time-of-day control (regular session only)
    # ------------------------------------------------------------------
    reg = df[df.entry_session == "regular"]
    tod_rows = []
    for bucket, g in reg.groupby("time_of_day"):
        c_gross = corr_pair(g["volume_surge_ratio"], g["gross_R"])
        b0 = block(g, "gross_R")
        b5 = block(g, "net_R_5bps")
        tod_rows.append(dict(time_of_day=bucket, trades=len(g), median_volume_surge=g.volume_surge_ratio.median(),
                              gross_expectancy=b0["expectancy"], expectancy_5bps=b5["expectancy"],
                              spearman_vs_gross=c_gross["spearman_r"], spearman_n=c_gross["n"]))
    pd.DataFrame(tod_rows).to_csv(OUT / "task18_timeofday.csv", index=False)
    print("wrote task18_timeofday.csv")

    # ------------------------------------------------------------------
    # Section 8: regime control (+ demeaned-by-subperiod pooled test)
    # ------------------------------------------------------------------
    regime_rows = []
    for name, g in df.groupby("subperiod"):
        c_gross = corr_pair(g["volume_surge_ratio"], g["gross_R"])
        regime_rows.append(dict(subperiod=name, trades=len(g), spearman_vs_gross=c_gross["spearman_r"],
                                 spearman_vs_gross_p=c_gross["spearman_p"]))
    df["volume_demeaned_by_subperiod"] = df["volume_surge_ratio"] - df.groupby("subperiod")["volume_surge_ratio"].transform("mean")
    df["gross_R_demeaned_by_subperiod"] = df["gross_R"] - df.groupby("subperiod")["gross_R"].transform("mean")
    pooled_within_regime = corr_pair(df["volume_demeaned_by_subperiod"], df["gross_R_demeaned_by_subperiod"])
    regime_rows.append(dict(subperiod="POOLED_DEMEANED_BY_SUBPERIOD", trades=len(df),
                             spearman_vs_gross=pooled_within_regime["spearman_r"],
                             spearman_vs_gross_p=pooled_within_regime["spearman_p"]))
    pd.DataFrame(regime_rows).to_csv(OUT / "task18_regime_analysis.csv", index=False)
    print("wrote task18_regime_analysis.csv")
    print("pooled within-subperiod (demeaned) vs gross_R:", pooled_within_regime)

    # ------------------------------------------------------------------
    # Section 9: holding-time control
    # ------------------------------------------------------------------
    holding_corr = corr_pair(df["volume_surge_ratio"], df["holding_seconds"])
    print(f"\n=== Section 9: volume vs holding_seconds: {holding_corr} ===")
    df["holding_quartile"] = pd.qcut(df["holding_seconds"].rank(method="first"), 4,
                                      labels=["Q1_shortest", "Q2", "Q3", "Q4_longest"])
    hold_rows = [dict(check="volume_vs_holding_seconds", spearman_r=holding_corr["spearman_r"],
                       spearman_p=holding_corr["spearman_p"], n=holding_corr["n"])]
    for q, g in df.groupby("holding_quartile", observed=True):
        c_gross = corr_pair(g["volume_surge_ratio"], g["gross_R"])
        b0 = block(g, "gross_R")
        hold_rows.append(dict(check=f"volume_vs_gross_within_{q}", spearman_r=c_gross["spearman_r"],
                               spearman_p=c_gross["spearman_p"], n=c_gross["n"],
                               median_holding_min=g.holding_seconds.median() / 60, gross_expectancy=b0["expectancy"]))
    pd.DataFrame(hold_rows).to_csv(OUT / "task18_holding_analysis.csv", index=False)
    print("wrote task18_holding_analysis.csv")

    # ------------------------------------------------------------------
    # Section 10: exit-type control
    # ------------------------------------------------------------------
    exit_rows = []
    for reason, g in df.groupby("exit_reason"):
        c_gross = corr_pair(g["volume_surge_ratio"], g["gross_R"])
        b0 = block(g, "gross_R")
        b5 = block(g, "net_R_5bps")
        exit_rows.append(dict(exit_reason=reason, trades=len(g), median_volume_surge=g.volume_surge_ratio.median(),
                               gross_expectancy=b0["expectancy"], expectancy_5bps=b5["expectancy"],
                               spearman_vs_gross=c_gross["spearman_r"], spearman_n=c_gross["n"]))
    pd.DataFrame(exit_rows).to_csv(OUT / "task18_exit_analysis.csv", index=False)
    print("wrote task18_exit_analysis.csv")

    # ------------------------------------------------------------------
    # Section 11: direction control
    # ------------------------------------------------------------------
    dir_rows = []
    for d, g in df.groupby("direction"):
        c_gross = corr_pair(g["volume_surge_ratio"], g["gross_R"])
        c_5bps = corr_pair(g["volume_surge_ratio"], g["net_R_5bps"])
        dir_rows.append(dict(direction=d, trades=len(g), spearman_vs_gross=c_gross["spearman_r"],
                              spearman_vs_gross_p=c_gross["spearman_p"], spearman_vs_5bps=c_5bps["spearman_r"]))
    pd.DataFrame(dir_rows).to_csv(OUT / "task18_direction_analysis.csv", index=False)
    print("wrote task18_direction_analysis.csv")

    # ------------------------------------------------------------------
    # Section 12: multivariate descriptive model (OLS + HC3)
    # ------------------------------------------------------------------
    print("\n=== Section 12: multivariate model ===")
    model_df = df.dropna(subset=["volume_surge_ratio", "gross_R", "net_R_5bps", "holding_seconds",
                                  "symbol", "session_bucket", "direction", "subperiod"]).copy()
    model_df["holding_hours"] = model_df["holding_seconds"] / 3600.0
    X, names = build_design(model_df, cont_cols=["volume_surge_ratio", "holding_hours"],
                             cat_cols=["symbol", "session_bucket", "direction", "subperiod"])
    mv_rows = []
    for target in ["gross_R", "net_R_5bps"]:
        y = model_df[target].to_numpy(dtype=float)
        coefs, r2, n = ols_hc3(y, X, names)
        coefs["target"] = target
        coefs["r_squared"] = r2
        coefs["n_obs"] = n
        mv_rows.append(coefs)
        vol_row = coefs[coefs.term == "volume_surge_ratio"].iloc[0]
        print(f"{target}: volume_surge_ratio coef={vol_row.coef:.4f} se={vol_row.se:.4f} "
              f"p={vol_row.p:.4f} CI=[{vol_row.ci_lo:.4f},{vol_row.ci_hi:.4f}] R2={r2:.4f} n={n}")
    mv_df = pd.concat(mv_rows, ignore_index=True)
    mv_df.to_csv(OUT / "task18_multivariate.csv", index=False)
    print("wrote task18_multivariate.csv")

    diag = dict(
        raw_gross=raw_gross, raw_5bps=raw_5bps,
        pooled_within_symbol_gross=pooled_within_gross, pooled_within_symbol_5bps=pooled_within_5bps,
        pooled_within_regime_gross=pooled_within_regime,
        volume_vs_holding=holding_corr,
        within_symbol_classifications={row["symbol"]: row["classification"] for row in ws_rows},
    )
    (OUT / "_diag_scratch.json").write_text(json.dumps(diag, indent=2, default=str))
    print("\nAll sections complete.")
