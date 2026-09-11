"""
Task 22 Step 1 -- freeze the exact Task 21 model family.

Task 21 fit a small, pre-specified 3-feature logistic model
(current_R, running_MAE_R, consecutive_adverse_bars) independently at
each of 5 pre-registered horizons, but never persisted the fitted
coefficients/standardization parameters to disk -- only AUC/CV-AUC
summary numbers. This script re-derives those exact parameters by
refitting on the SAME Task 21 discovery-period feature table
(task21_early_features.csv) with the SAME code path (unregularized
sklearn LogisticRegression on standardized features), then freezes the
result. This is bookkeeping/extraction of an already-completed fit, not
new research -- no new data, no new features, no threshold search.

T=10 is excluded from the frozen family: Task 21 itself could not fit a
stable model there (only 4 positive cases survived to that horizon).
"""
import hashlib
import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import roc_auc_score

REPO = Path("c:/workspace/TalonX")
sys.path.insert(0, str(REPO))

TASK21_FEATURES = REPO / "results" / "task21_early_failure_audit" / "task21_early_features.csv"
OUT = REPO / "docs" / "research" / "task21_frozen_early_failure_spec.json"

MODEL_FEATURES = ["current_R", "running_MAE_R", "consecutive_adverse_bars"]
FROZEN_HORIZONS = [1, 2, 3, 5]  # T=10 excluded -- underpowered in Task 21 (n_pos=4)


def sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()[:16]


if __name__ == "__main__":
    feat_df = pd.read_csv(TASK21_FEATURES)
    from talonx_backtest.reproducibility import get_dataset_hash, get_git_commit

    horizon_models = {}
    for T in FROZEN_HORIZONS:
        fT = feat_df[feat_df.horizon_min == T]
        sub = fT[fT.population.isin(["A_IMMEDIATE_FAILURE", "B_DEEP_RETRACE_WINNER"])].dropna(subset=MODEL_FEATURES)
        y = (sub.population == "A_IMMEDIATE_FAILURE").astype(int).to_numpy()
        X = sub[MODEL_FEATURES].to_numpy(dtype=float)
        mu, sd = X.mean(axis=0), X.std(axis=0)
        Xz = (X - mu) / sd
        clf = LogisticRegression(penalty=None, max_iter=2000)
        clf.fit(Xz, y)
        p_hat = clf.predict_proba(Xz)[:, 1]
        auc = roc_auc_score(y, p_hat)
        horizon_models[str(T)] = dict(
            horizon_minutes=T,
            n_discovery=int(len(sub)),
            n_immediate_failure=int(y.sum()),
            n_deep_retrace_winner=int(len(y) - y.sum()),
            standardization_mean=mu.tolist(),
            standardization_std=sd.tolist(),
            coefficients=clf.coef_[0].tolist(),
            intercept=float(clf.intercept_[0]),
            discovery_auc_insample=float(auc),
        )
        print(f"T={T}: n={len(sub)} coef={clf.coef_[0]} intercept={clf.intercept_[0]:.4f} AUC={auc:.4f}")

    spec = {
        "spec_name": "task21_frozen_early_failure_spec",
        "frozen_date_utc": "2026-08-20",
        "status": "FROZEN - do not modify for this OOS experiment; any change is a new hypothesis",
        "discovery_period": {"start": "2025-08-15", "end": "2026-08-14"},
        "oos_period": {"start": "2026-08-17", "note": "onward, as defined in Task 18's OOS protocol"},
        "source_artifacts": {
            "task20_excursion_audit_script_sha256_16": sha256_file(REPO / "research/scripts/task20_excursion_audit.py"),
            "task21_early_failure_audit_script_sha256_16": sha256_file(REPO / "research/scripts/task21_early_failure_audit.py"),
            "task20_trade_paths_csv_sha256_16": sha256_file(REPO / "results/task20_excursion_audit/task20_trade_paths.csv"),
            "task21_early_features_csv_sha256_16": sha256_file(TASK21_FEATURES),
        },
        "discovery_dataset_hash": get_dataset_hash(str(REPO / "data/historical_1m/task7b_alpaca_long_history")),
        "git_commit_at_freeze": get_git_commit(),
        "path_class_definitions": {
            "IMMEDIATE_FAILURE": "STOP exit with max running favorable excursion (MFE) < 0.25R over the full trade life -- Task 20 definition, unchanged",
            "DEEP_RETRACE_WINNER": "TARGET or profitable END_OF_SESSION exit that crossed back through breakeven (0R) at some point after first reaching +0.5R favorable excursion, then still finished positive -- Task 20 definition, unchanged",
        },
        "model_family": {
            "note": "Task 21 did not designate a single primary horizon -- all 5 pre-registered horizons were evaluated as a fixed family. T=10 is excluded here because Task 21 itself could not fit a stable model at that horizon (only 4 positive cases survived). The remaining 4 horizons (1/2/3/5 min) are frozen as co-equal family members -- OOS evaluation must report all 4 and interpret them jointly (multiple-testing-aware), never cherry-pick the best-performing one after seeing OOS results.",
            "model_type": "logistic regression, unregularized (penalty=None), scikit-learn",
            "label_definition": "IMMEDIATE_FAILURE = 1, DEEP_RETRACE_WINNER = 0",
            "input_features_exact_order": MODEL_FEATURES,
            "feature_formulas": {
                "current_R": "direction-adjusted (entry_price to bar_close) / risk_dollars_per_share, using the last bar's close at or before horizon T",
                "running_MAE_R": "cumulative minimum of direction-adjusted adverse excursion (bar low, direction-adjusted) / risk, from entry through horizon T (<=0 by construction)",
                "consecutive_adverse_bars": "longest run of consecutive close-to-close adverse bars (direction-adjusted) from entry through horizon T",
            },
            "direction_normalization": "bullish: high_R=(high-entry)/risk, low_R=(low-entry)/risk, close_R=(close-entry)/risk; bearish: high_R=(entry-low)/risk, low_R=(entry-high)/risk, close_R=(entry-close)/risk -- risk is always risk_dollars_per_share = abs(entry_price - stop_price), identical to the denominator gross_R itself uses",
            "preprocessing": "each feature standardized (z-score) using the DISCOVERY-period mean/std frozen below -- OOS features must be standardized with these SAME frozen mean/std values, never refit on OOS data",
            "classification_mapping": "predict_proba[:,1] >= 0.5 -> classified IMMEDIATE_FAILURE; < 0.5 -> classified DEEP_RETRACE_WINNER-like (no separate classification threshold was chosen in Task 21 beyond the standard 0.5 decision boundary; Task 21's false-protection analysis in section 10 used a DIFFERENT, purely descriptive single-feature median-midpoint threshold, NOT this model's output -- that descriptive threshold is recorded separately below and is not treated as a frozen model decision rule)",
        },
        "task21_descriptive_false_protection_thresholds": {
            "note": "Task 21 Section 10 used the single best-discriminating feature per horizon with a DESCRIPTIVE median-midpoint threshold -- NOT a fitted model, NOT optimized, reported for completeness only. Not part of the frozen logistic model family above.",
            "1": {"feature": "distance_to_stop_R", "threshold_descriptive_midpoint": 0.769325},
            "2": {"feature": "current_R", "threshold_descriptive_midpoint": -0.099016},
            "3": {"feature": "favorable_bars", "threshold_descriptive_midpoint": 1.5},
            "5": {"feature": "favorable_bars", "threshold_descriptive_midpoint": 2.25},
        },
        "horizon_models": horizon_models,
        "code_version_fingerprint": {
            "engine": "talonx_backtest (frozen production strategy, min_atr_pct=0.20%)",
            "feature_extraction_reused_from": "research/scripts/task21_early_failure_audit.py: build_r_series() + horizon_features()",
        },
    }

    OUT.parent.mkdir(parents=True, exist_ok=True)
    spec_json = json.dumps(spec, indent=2, sort_keys=False)
    frozen_spec_hash = hashlib.sha256(spec_json.encode()).hexdigest()[:16]
    spec["frozen_spec_hash"] = frozen_spec_hash
    OUT.write_text(json.dumps(spec, indent=2, sort_keys=False))
    print(f"\nwrote {OUT}")
    print(f"frozen_spec_hash = {frozen_spec_hash}")
