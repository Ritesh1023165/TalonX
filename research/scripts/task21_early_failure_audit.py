"""
Task 21 -- Early Failure Separability Audit.

DIAGNOSTIC SEPARABILITY STUDY ONLY. Determines whether IMMEDIATE_FAILURE
trades (Task 20) can be distinguished, using ONLY bars available from entry
through a pre-registered early horizon, from trades that eventually become
DEEP_RETRACE_WINNER. No rule is created, no threshold is optimized, no
strategy logic changes.

Strict information-time discipline: for horizon T, only bars with elapsed
minutes <= T (and <= the trade's own exit, i.e. before it closed) are used.
Final holding time / exit reason / future MFE-MAE never enter the feature
set -- they are used only as retrospective labels for comparison.

Deterministic. Logistic regression via sklearn (unregularized), AUC via
sklearn, with Benjamini-Hochberg FDR correction applied across the
pre-registered horizon x feature grid before highlighting any p-value.
"""
import json
import sys
import warnings
from pathlib import Path

import numpy as np
import pandas as pd
from scipy import stats as sstats
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import roc_auc_score
from sklearn.model_selection import StratifiedKFold

warnings.filterwarnings("ignore", category=FutureWarning)

REPO = Path("c:/workspace/TalonX")
sys.path.insert(0, str(REPO))

OUT = REPO / "results" / "task21_early_failure_audit"
OUT.mkdir(parents=True, exist_ok=True)

RAW_DATA_DIR = REPO / "data" / "historical_1m" / "task7b_alpaca_long_history"
TASK20_PATHS = REPO / "results" / "task20_excursion_audit" / "task20_trade_paths.csv"

EXPECTED_TOTAL_R_0 = 75.97580943135327
EXPECTED_TOTAL_R_5 = -21.41375894722095
EXPECTED_EXIT_COUNTS = {"STOP": 139, "TARGET": 16, "END_OF_SESSION": 26}
EXPECTED_PATH_COUNTS = {"IMMEDIATE_FAILURE": 41, "DEEP_RETRACE_WINNER": 35}

HORIZONS = [1, 2, 3, 5, 10]  # minutes, pre-registered -- not adjusted after seeing results

_raw_cache: dict[str, pd.DataFrame] = {}


def raw_bars(symbol: str) -> pd.DataFrame:
    if symbol not in _raw_cache:
        df = pd.read_csv(RAW_DATA_DIR / f"{symbol}.csv", parse_dates=["timestamp"])
        df["timestamp"] = pd.to_datetime(df["timestamp"], utc=True)
        _raw_cache[symbol] = df.set_index("timestamp").sort_index()
    return _raw_cache[symbol]


def build_r_series(row) -> pd.DataFrame | None:
    """Full entry-to-exit bar series in direction-adjusted R terms, plus
    per-bar volume -- built ONCE per trade; horizon slicing happens
    downstream by filtering on elapsed minutes, never by looking past a
    trade's own exit."""
    bars = raw_bars(row.symbol)
    window = bars.loc[row.entry_timestamp:row.exit_timestamp]
    if window.empty:
        return None
    entry = row.entry_price
    risk = row.risk_dollars_per_share
    if row.direction == "bullish":
        high_R = (window["high"] - entry) / risk
        low_R = (window["low"] - entry) / risk
        close_R = (window["close"] - entry) / risk
    else:
        high_R = (entry - window["low"]) / risk
        low_R = (entry - window["high"]) / risk
        close_R = (entry - window["close"]) / risk
    out = pd.DataFrame({"high_R": high_R, "low_R": low_R, "close_R": close_R, "volume": window["volume"]})
    out["minutes"] = (out.index - row.entry_timestamp).total_seconds() / 60.0
    return out


def horizon_features(series: pd.DataFrame, T: int, signal_bar_volume: float, entry_bar_volume: float,
                      pre_entry_volume_surge: float) -> dict | None:
    """Features computable using ONLY bars with minutes <= T. Returns None
    if the trade already exited strictly before T (excluded from that
    horizon's comparison -- see Section 10/11 survival logic, handled by
    the caller, not here)."""
    win = series[series.minutes <= T]
    if win.empty:
        return None
    last_close_R = float(win.close_R.iloc[-1])
    running_mfe = float(win.high_R.cummax().iloc[-1])
    running_mae = float(win.low_R.cummin().iloc[-1])
    distance_to_stop_R = last_close_R + 1.0  # stop is always exactly -1R by construction
    fraction_initial_risk_remaining = distance_to_stop_R  # identical under this normalization -- reported separately per spec
    range_since_entry_R = running_mfe - running_mae
    clv = (last_close_R - running_mae) / range_since_entry_R if range_since_entry_R > 1e-9 else None

    # per-bar direction-adjusted returns (close-to-close, entry as bar 0)
    closes = pd.concat([pd.Series([0.0]), win.close_R.reset_index(drop=True)])
    bar_returns = closes.diff().dropna().to_numpy()
    favorable_bars = int((bar_returns > 0).sum())
    adverse_bars = int((bar_returns < 0).sum())
    flat_bars = int((bar_returns == 0).sum())

    def max_streak(mask: np.ndarray) -> int:
        best = cur = 0
        for m in mask:
            cur = cur + 1 if m else 0
            best = max(best, cur)
        return best
    consecutive_adverse = max_streak(bar_returns < 0)
    consecutive_favorable = max_streak(bar_returns > 0)

    net_move = abs(last_close_R)
    sum_abs_moves = float(np.sum(np.abs(bar_returns)))
    path_efficiency = net_move / sum_abs_moves if sum_abs_moves > 1e-9 else None

    cum_volume = float(win.volume.sum())
    avg_bar_volume = cum_volume / len(win)
    vol_vs_signal_bar = avg_bar_volume / signal_bar_volume if signal_bar_volume else None
    vol_vs_entry_bar = avg_bar_volume / entry_bar_volume if entry_bar_volume else None

    return dict(
        n_bars=len(win), current_R=last_close_R, running_MFE_R=running_mfe, running_MAE_R=running_mae,
        distance_to_stop_R=distance_to_stop_R, fraction_initial_risk_remaining=fraction_initial_risk_remaining,
        range_since_entry_R=range_since_entry_R, close_location_value=clv,
        favorable_bars=favorable_bars, adverse_bars=adverse_bars, flat_bars=flat_bars,
        consecutive_adverse_bars=consecutive_adverse, consecutive_favorable_bars=consecutive_favorable,
        path_efficiency=path_efficiency, cum_volume_since_entry=cum_volume, avg_post_entry_bar_volume=avg_bar_volume,
        volume_vs_signal_bar=vol_vs_signal_bar, volume_vs_entry_bar=vol_vs_entry_bar,
        volume_vs_pre_entry_baseline=pre_entry_volume_surge,  # pre-entry field, passed through unchanged
    )


def signal_and_entry_bar_volume(symbol: str, signal_ts, entry_ts) -> tuple[float | None, float | None]:
    bars = raw_bars(symbol)
    try:
        sv = float(bars.loc[signal_ts, "volume"]) if signal_ts in bars.index else None
    except KeyError:
        sv = None
    try:
        ev = float(bars.loc[entry_ts, "volume"]) if entry_ts in bars.index else None
    except KeyError:
        ev = None
    return sv, ev


def compare_groups(a: pd.Series, b: pd.Series) -> dict:
    a, b = a.dropna(), b.dropna()
    if len(a) < 3 or len(b) < 3:
        return dict(n_a=len(a), n_b=len(b), median_a=None, median_b=None, p25_a=None, p75_a=None,
                    p25_b=None, p75_b=None, cohens_d=None, mannwhitney_p=None)
    pooled_sd = np.sqrt(((len(a) - 1) * a.var() + (len(b) - 1) * b.var()) / (len(a) + len(b) - 2))
    d = (a.mean() - b.mean()) / pooled_sd if pooled_sd > 0 else None
    u = sstats.mannwhitneyu(a, b, alternative="two-sided")
    return dict(n_a=len(a), n_b=len(b), median_a=a.median(), median_b=b.median(),
                p25_a=a.quantile(0.25), p75_a=a.quantile(0.75), p25_b=b.quantile(0.25), p75_b=b.quantile(0.75),
                cohens_d=d, mannwhitney_p=u.pvalue)


def bh_fdr(pvals: list[float], alpha: float = 0.05) -> list[bool]:
    """Benjamini-Hochberg FDR correction. Returns significance flags at
    the given alpha, aligned to the input order."""
    idx = np.argsort(pvals)
    m = len(pvals)
    sorted_p = np.array(pvals)[idx]
    thresh = alpha * (np.arange(1, m + 1) / m)
    passed = sorted_p <= thresh
    if not passed.any():
        cutoff_rank = -1
    else:
        cutoff_rank = np.max(np.where(passed)[0])
    sig = np.zeros(m, dtype=bool)
    if cutoff_rank >= 0:
        sig[idx[:cutoff_rank + 1]] = True
    return sig.tolist()


if __name__ == "__main__":
    print("=== Section 2: Integrity ===")
    df = pd.read_csv(TASK20_PATHS, parse_dates=["signal_timestamp", "entry_timestamp", "exit_timestamp"])
    for c in ["signal_timestamp", "entry_timestamp", "exit_timestamp"]:
        df[c] = pd.to_datetime(df[c], utc=True)
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
    path_counts = df.path_class.value_counts().to_dict()
    for k, v in EXPECTED_PATH_COUNTS.items():
        if path_counts.get(k) != v:
            problems.append(f"path_class {k}: {path_counts.get(k)} != expected {v}")
    from talonx_backtest.reproducibility import get_dataset_hash, get_git_commit
    dh = get_dataset_hash(str(RAW_DATA_DIR))
    if dh != "5e5412a960bf":
        problems.append(f"dataset_hash mismatch: {dh}")
    if problems:
        for p in problems:
            print("FAIL:", p)
        raise SystemExit("Integrity check failed.")
    print(f"OK -- 181 trades, exit_counts={exit_counts}, path_counts(IF/DRW)="
          f"{path_counts.get('IMMEDIATE_FAILURE')}/{path_counts.get('DEEP_RETRACE_WINNER')}, "
          f"dataset_hash={dh}, git_commit={get_git_commit()}")

    # ------------------------------------------------------------------
    # Section 3: primary/secondary populations
    # ------------------------------------------------------------------
    df["population"] = "OTHER"
    df.loc[df.path_class == "IMMEDIATE_FAILURE", "population"] = "A_IMMEDIATE_FAILURE"
    df.loc[df.path_class == "DEEP_RETRACE_WINNER", "population"] = "B_DEEP_RETRACE_WINNER"
    df.loc[(df.exit_reason == "STOP") & (df.path_class != "IMMEDIATE_FAILURE"), "population"] = "C_other_STOP"
    df.loc[(df.exit_reason.isin(["TARGET", "END_OF_SESSION"])) & (df.gross_R > 0) &
           (df.path_class != "DEEP_RETRACE_WINNER"), "population"] = "D_other_winner"
    pop_counts = df.population.value_counts().to_dict()
    print("\nPopulation counts:", pop_counts)
    df[["trade_id", "symbol", "exit_reason", "path_class", "population", "gross_R", "net_R_5bps",
        "holding_seconds", "subperiod"]].to_csv(OUT / "task21_population_reconciliation.csv", index=False)
    print("wrote task21_population_reconciliation.csv")

    # ------------------------------------------------------------------
    # build R-series + pre-entry volume anchors for every trade once
    # ------------------------------------------------------------------
    print("\nBuilding entry-to-exit R series for all 181 trades...")
    series_map = {}
    signal_vol_map, entry_vol_map = {}, {}
    for _, row in df.iterrows():
        s = build_r_series(row)
        if s is None:
            raise SystemExit(f"FAIL: no bars found for {row.trade_id}")
        series_map[row.trade_id] = s
        sv, ev = signal_and_entry_bar_volume(row.symbol, row.signal_timestamp, row.entry_timestamp)
        signal_vol_map[row.trade_id] = sv
        entry_vol_map[row.trade_id] = ev
    print(f"built {len(series_map)} trade series")

    # pre-entry volume_surge_ratio (from Task 17's feature table, if present) -- optional enrichment
    t17_path = REPO / "results" / "task17_gross_edge_audit" / "task17_trade_features.csv"
    vol_surge_map = {}
    if t17_path.exists():
        t17 = pd.read_csv(t17_path)[["trade_id", "volume_surge_ratio"]]
        vol_surge_map = dict(zip(t17.trade_id, t17.volume_surge_ratio))

    # ------------------------------------------------------------------
    # Section 5/6/8: per-horizon feature extraction (all populations, for
    # survival bookkeeping) -- Section 10 needs survival for ALL 181
    # ------------------------------------------------------------------
    print("\n=== Section 10: fixed-horizon survival (all 181 trades) ===")
    survival_rows = []
    feature_records = []  # trade_id, horizon, population, <features>
    for _, row in df.iterrows():
        holding_min = row.holding_seconds / 60.0
        for T in HORIZONS:
            already_exited = holding_min < T
            survival_rows.append(dict(trade_id=row.trade_id, horizon_min=T, population=row.population,
                                       path_class=row.path_class, already_exited_before_horizon=already_exited,
                                       holding_min=holding_min))
            if already_exited:
                continue
            feat = horizon_features(series_map[row.trade_id], T, signal_vol_map[row.trade_id],
                                     entry_vol_map[row.trade_id], vol_surge_map.get(row.trade_id))
            if feat is None:
                continue
            feat.update(trade_id=row.trade_id, horizon_min=T, population=row.population,
                        path_class=row.path_class, symbol=row.symbol, subperiod=row.subperiod)
            feature_records.append(feat)
    survival_df = pd.DataFrame(survival_rows)
    surv_summary = survival_df.groupby(["horizon_min", "path_class"]).agg(
        already_exited=("already_exited_before_horizon", "sum"), still_alive=("already_exited_before_horizon",
                                                                                lambda s: (~s).sum())
    ).reset_index()
    surv_summary.to_csv(OUT / "task21_survival_by_horizon.csv", index=False)
    print(surv_summary[surv_summary.path_class.isin(["IMMEDIATE_FAILURE", "DEEP_RETRACE_WINNER"])].to_string(index=False))

    feat_df = pd.DataFrame(feature_records)
    feat_df.to_csv(OUT / "task21_early_features.csv", index=False)
    print(f"\nwrote task21_early_features.csv ({len(feat_df)} horizon-trade rows)")

    FEATURE_COLS = ["current_R", "running_MFE_R", "running_MAE_R", "distance_to_stop_R", "range_since_entry_R",
                     "close_location_value", "favorable_bars", "adverse_bars", "consecutive_adverse_bars",
                     "consecutive_favorable_bars", "path_efficiency", "avg_post_entry_bar_volume",
                     "volume_vs_signal_bar", "volume_vs_entry_bar"]

    # ------------------------------------------------------------------
    # Section 9: first-minute analysis (T=1)
    # ------------------------------------------------------------------
    print("\n=== Section 9: first-minute (T=1) IMMEDIATE_FAILURE vs DEEP_RETRACE_WINNER ===")
    f1 = feat_df[feat_df.horizon_min == 1]
    a1 = f1[f1.population == "A_IMMEDIATE_FAILURE"]
    b1 = f1[f1.population == "B_DEEP_RETRACE_WINNER"]
    fm_rows = []
    for col in FEATURE_COLS:
        cmp = compare_groups(a1[col], b1[col])
        cmp["feature"] = col
        fm_rows.append(cmp)
    fm_df = pd.DataFrame(fm_rows)[["feature", "n_a", "n_b", "median_a", "median_b", "p25_a", "p75_a",
                                    "p25_b", "p75_b", "cohens_d", "mannwhitney_p"]]
    fm_df.to_csv(OUT / "task21_first_minute.csv", index=False)
    print(fm_df.to_string(index=False))
    print(f"(a=IMMEDIATE_FAILURE survivors at T=1: n={len(a1)}, b=DEEP_RETRACE_WINNER survivors at T=1: n={len(b1)})")

    # ------------------------------------------------------------------
    # Section 11/12: conditional-survivor feature comparison at every horizon
    # ------------------------------------------------------------------
    print("\n=== Section 11/12: conditional-survivor feature comparison, all horizons ===")
    comp_rows = []
    for T in HORIZONS:
        fT = feat_df[feat_df.horizon_min == T]
        a = fT[fT.population == "A_IMMEDIATE_FAILURE"]
        b = fT[fT.population == "B_DEEP_RETRACE_WINNER"]
        for col in FEATURE_COLS:
            cmp = compare_groups(a[col], b[col])
            cmp.update(horizon_min=T, feature=col)
            comp_rows.append(cmp)
    comp_df = pd.DataFrame(comp_rows)
    # BH-FDR correction across the full pre-registered horizon x feature grid
    valid_p = comp_df["mannwhitney_p"].notna()
    comp_df["significant_fdr_0.05"] = False
    comp_df.loc[valid_p, "significant_fdr_0.05"] = bh_fdr(comp_df.loc[valid_p, "mannwhitney_p"].tolist(), 0.05)
    comp_df.to_csv(OUT / "task21_feature_comparison.csv", index=False)
    n_sig = comp_df["significant_fdr_0.05"].sum()
    print(f"features/horizons tested: {len(comp_df)}, significant after BH-FDR (alpha=0.05): {n_sig}")
    print(comp_df[comp_df["significant_fdr_0.05"]][["horizon_min", "feature", "n_a", "n_b", "median_a", "median_b",
                                                      "cohens_d", "mannwhitney_p"]].to_string(index=False))

    # ------------------------------------------------------------------
    # Section 13: simple logistic model per horizon (pre-specified small
    # feature set: current_R, running_MAE_R, consecutive_adverse_bars --
    # fixed BEFORE inspecting Section 12 results, not selected post-hoc)
    # ------------------------------------------------------------------
    print("\n=== Section 13: logistic model discrimination per horizon ===")
    MODEL_FEATURES = ["current_R", "running_MAE_R", "consecutive_adverse_bars"]
    model_rows = []
    for T in HORIZONS:
        fT = feat_df[feat_df.horizon_min == T]
        sub = fT[fT.population.isin(["A_IMMEDIATE_FAILURE", "B_DEEP_RETRACE_WINNER"])].dropna(subset=MODEL_FEATURES)
        y = (sub.population == "A_IMMEDIATE_FAILURE").astype(int).to_numpy()
        X = sub[MODEL_FEATURES].to_numpy(dtype=float)
        if len(sub) < 15 or y.sum() < 5 or (len(y) - y.sum()) < 5:
            model_rows.append(dict(horizon_min=T, n=len(sub), n_pos=int(y.sum()), auc=None, cv_auc_mean=None,
                                    cv_auc_std=None, note="insufficient sample for stable fit"))
            continue
        Xz = (X - X.mean(axis=0)) / X.std(axis=0)
        clf = LogisticRegression(penalty=None, max_iter=2000)
        clf.fit(Xz, y)
        p_hat = clf.predict_proba(Xz)[:, 1]
        auc = roc_auc_score(y, p_hat)

        n_splits = min(5, min(y.sum(), len(y) - y.sum()))
        cv_aucs = []
        if n_splits >= 2:
            skf = StratifiedKFold(n_splits=n_splits, shuffle=True, random_state=42)
            for tr_idx, te_idx in skf.split(Xz, y):
                if len(set(y[tr_idx])) < 2:
                    continue
                clf_cv = LogisticRegression(penalty=None, max_iter=2000)
                clf_cv.fit(Xz[tr_idx], y[tr_idx])
                if len(set(y[te_idx])) < 2:
                    continue
                p_te = clf_cv.predict_proba(Xz[te_idx])[:, 1]
                cv_aucs.append(roc_auc_score(y[te_idx], p_te))
        model_rows.append(dict(
            horizon_min=T, n=len(sub), n_pos=int(y.sum()), auc=auc,
            cv_auc_mean=float(np.mean(cv_aucs)) if cv_aucs else None,
            cv_auc_std=float(np.std(cv_aucs)) if cv_aucs else None,
            cv_folds=len(cv_aucs), note="",
        ))
    model_df = pd.DataFrame(model_rows)
    model_df.to_csv(OUT / "task21_models.csv", index=False)
    print(model_df.to_string(index=False))

    # ------------------------------------------------------------------
    # Section 14: leave-one-subperiod-out validation (T=5 as representative
    # mid-range horizon for the model; all horizons summarized in the csv)
    # ------------------------------------------------------------------
    print("\n=== Section 14: leave-one-subperiod-out ===")
    subperiods = sorted(df.subperiod.dropna().unique().tolist())
    loso_rows = []
    for T in HORIZONS:
        fT = feat_df[feat_df.horizon_min == T]
        sub = fT[fT.population.isin(["A_IMMEDIATE_FAILURE", "B_DEEP_RETRACE_WINNER"])].dropna(subset=MODEL_FEATURES)
        if len(sub) < 15:
            continue
        for held_out in subperiods:
            train = sub[sub.subperiod != held_out]
            test = sub[sub.subperiod == held_out]
            y_tr = (train.population == "A_IMMEDIATE_FAILURE").astype(int).to_numpy()
            y_te = (test.population == "A_IMMEDIATE_FAILURE").astype(int).to_numpy()
            if len(set(y_tr)) < 2 or len(set(y_te)) < 2 or len(test) < 4:
                loso_rows.append(dict(horizon_min=T, held_out_subperiod=held_out, n_train=len(train),
                                       n_test=len(test), auc=None, note="insufficient sample"))
                continue
            Xtr = train[MODEL_FEATURES].to_numpy(dtype=float)
            mu, sd = Xtr.mean(axis=0), Xtr.std(axis=0)
            Xtr_z = (Xtr - mu) / sd
            Xte_z = (test[MODEL_FEATURES].to_numpy(dtype=float) - mu) / sd
            clf = LogisticRegression(penalty=None, max_iter=2000)
            clf.fit(Xtr_z, y_tr)
            p_te = clf.predict_proba(Xte_z)[:, 1]
            loso_rows.append(dict(horizon_min=T, held_out_subperiod=held_out, n_train=len(train), n_test=len(test),
                                   auc=roc_auc_score(y_te, p_te), note=""))
    loso_df = pd.DataFrame(loso_rows)
    loso_df.to_csv(OUT / "task21_subperiod_validation.csv", index=False)
    print(loso_df.to_string(index=False))

    # ------------------------------------------------------------------
    # Section 15: leave-one-symbol-out (STX especially, plus other majors)
    # ------------------------------------------------------------------
    print("\n=== Section 15: leave-one-symbol-out ===")
    symbol_rows = []
    for T in HORIZONS:
        fT = feat_df[feat_df.horizon_min == T]
        sub = fT[fT.population.isin(["A_IMMEDIATE_FAILURE", "B_DEEP_RETRACE_WINNER"])].dropna(subset=MODEL_FEATURES)
        if len(sub) < 15:
            continue
        for sym in ["STX", "AMD", "PYPL", "TSLA", "NVDA"]:
            train = sub[sub.symbol != sym]
            test = sub[sub.symbol == sym]
            y_tr = (train.population == "A_IMMEDIATE_FAILURE").astype(int).to_numpy()
            y_te = (test.population == "A_IMMEDIATE_FAILURE").astype(int).to_numpy()
            if len(set(y_tr)) < 2 or len(set(y_te)) < 2 or len(test) < 4:
                symbol_rows.append(dict(horizon_min=T, held_out_symbol=sym, n_train=len(train), n_test=len(test),
                                         auc=None, note="insufficient sample"))
                continue
            Xtr = train[MODEL_FEATURES].to_numpy(dtype=float)
            mu, sd = Xtr.mean(axis=0), Xtr.std(axis=0)
            Xtr_z = (Xtr - mu) / sd
            Xte_z = (test[MODEL_FEATURES].to_numpy(dtype=float) - mu) / sd
            clf = LogisticRegression(penalty=None, max_iter=2000)
            clf.fit(Xtr_z, y_tr)
            p_te = clf.predict_proba(Xte_z)[:, 1]
            symbol_rows.append(dict(horizon_min=T, held_out_symbol=sym, n_train=len(train), n_test=len(test),
                                     auc=roc_auc_score(y_te, p_te), note=""))
    symbol_df = pd.DataFrame(symbol_rows)
    symbol_df.to_csv(OUT / "task21_symbol_validation.csv", index=False)
    print(symbol_df.to_string(index=False))

    # ------------------------------------------------------------------
    # Section 16: false-protection risk (mandatory)
    # ------------------------------------------------------------------
    print("\n=== Section 16: false-protection risk ===")
    fp_rows = []
    for T in HORIZONS:
        fT = feat_df[feat_df.horizon_min == T]
        a = fT[fT.population == "A_IMMEDIATE_FAILURE"]
        b = fT[fT.population == "B_DEEP_RETRACE_WINNER"]
        if a.empty or b.empty:
            continue
        # Use the single feature with the largest |Cohen's d| at this horizon (from Section 12 results,
        # decided from evidence already computed -- not re-optimized against this section's outcome)
        horizon_feats = comp_df[comp_df.horizon_min == T].dropna(subset=["cohens_d"])
        if horizon_feats.empty:
            continue
        best = horizon_feats.iloc[horizon_feats.cohens_d.abs().argmax()]
        feat_name = best["feature"]
        # threshold = midpoint between group medians (descriptive only, not optimized/searched)
        med_a, med_b = a[feat_name].median(), b[feat_name].median()
        threshold = (med_a + med_b) / 2
        flag_lower = med_a < med_b  # does IMMEDIATE_FAILURE sit below DEEP_RETRACE_WINNER on this feature?
        if flag_lower:
            a_flagged = (a[feat_name] < threshold).sum()
            b_flagged = (b[feat_name] < threshold).sum()
        else:
            a_flagged = (a[feat_name] > threshold).sum()
            b_flagged = (b[feat_name] > threshold).sum()
        fp_rows.append(dict(
            horizon_min=T, feature_used=feat_name, cohens_d=best["cohens_d"], threshold_descriptive_midpoint=threshold,
            immediate_failures_correctly_flagged=int(a_flagged), immediate_failures_total=len(a),
            immediate_failure_flag_rate=a_flagged / len(a),
            deep_retrace_winners_falsely_flagged=int(b_flagged), deep_retrace_winners_total=len(b),
            deep_retrace_winner_false_flag_rate=b_flagged / len(b),
        ))
    fp_df = pd.DataFrame(fp_rows)
    fp_df.to_csv(OUT / "task21_false_protection.csv", index=False)
    print(fp_df.to_string(index=False))

    # ------------------------------------------------------------------
    # Section 17: economic attribution
    # ------------------------------------------------------------------
    print("\n=== Section 17: economic attribution ===")
    econ_rows = []
    total_losses_0bps = df.loc[df.gross_R < 0, "gross_R"].sum()
    total_deterioration = (df["net_R_0bps"] - df["net_R_5bps"]).sum()
    for pop, g in df.groupby("population"):
        det = (g["net_R_0bps"] - g["net_R_5bps"]).sum()
        econ_rows.append(dict(
            population=pop, trades=len(g), gross_r=g.gross_R.sum(), r5bps=g.net_R_5bps.sum(),
            share_of_total_losses=(g.loc[g.gross_R < 0, "gross_R"].sum() / total_losses_0bps) if total_losses_0bps else None,
            share_of_0_to_5bps_deterioration=(det / total_deterioration) if total_deterioration else None,
        ))
    econ_df = pd.DataFrame(econ_rows)
    econ_df.to_csv(OUT / "task21_economic_attribution.csv", index=False)
    print(econ_df.to_string(index=False))

    diag = dict(
        pop_counts=pop_counts, n_sig_after_fdr=int(n_sig), model_summary=model_rows,
        exit_counts=exit_counts, path_counts={k: path_counts.get(k) for k in EXPECTED_PATH_COUNTS},
    )
    (OUT / "_diag_scratch.json").write_text(json.dumps(diag, indent=2, default=str))
    print("\nAll sections complete.")
