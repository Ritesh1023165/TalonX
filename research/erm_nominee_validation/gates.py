"""ERM nominee validation plumbing -- primary metric, gates G1-G4 and verdict precedence (r8 §3, §7). Pure functions.

pair_gross = -ret_sector_rel (the frozen SHORT sector-relative gross: -(r_stock - r_ETF) over entry open -> H10 close
on ALL bars); pair_net = pair_gross - stock_cost - etf_cost (round-trip totals, decimal). Estimator: the frozen
research_stats.bootstrap_ci_clustered (group = entry date as ISO string, 10,000 resamples, 95 %, seed 670067) on events
sorted by (entry date, symbol). No rounding before comparison. Costs and the floor decision must be passed explicitly.
"""
from __future__ import annotations

import numpy as np

from research.common.research_stats import DEFAULT_SEED, bootstrap_ci_clustered

N_RESAMPLES, CI_LEVEL, TOP_K = 10_000, 0.95, 5
MAX_MISSING_EXIT_RATE = 0.02
PASS_LABEL = "PASS_STATISTICAL_PROXY_PRE_BORROW"      # maps to the scheme's PASS; never "validated profitability"
assert DEFAULT_SEED == 670067


def pair_net(obs, stock_cost: float, etf_cost: float):
    """obs: frozen outcome rows (H10, this cell) incl. missing_exit rows. Returns (values, entry_dates, n_missing)
    for the valid rows, sorted by (entry_date, symbol)."""
    o = obs.copy()
    o["_d"] = o["entry_date"].astype(str)
    miss = o["missing_exit"].fillna(False).astype(bool)
    v = o.loc[~miss].sort_values(["_d", "symbol"], kind="mergesort")
    x = (-v["ret_sector_rel"].to_numpy(dtype=float)) - stock_cost - etf_cost
    return x, v["_d"].to_numpy(), int(miss.sum())


def gates(x: np.ndarray, groups: np.ndarray, n_missing: int) -> dict:
    n = len(x)
    g = {"n_valid": n, "distinct_dates": int(len(set(groups))), "n_missing_exit": n_missing,
         "missing_exit_rate": (n_missing / (n + n_missing)) if (n + n_missing) else 0.0,
         "mean": float(x.mean()) if n else None, "ci_low": None, "ci_high": None, "ci_withheld": True,
         "mean_without_top5": None}
    if n:
        ci = bootstrap_ci_clustered(x, groups, n_resamples=N_RESAMPLES, ci_level=CI_LEVEL, seed=DEFAULT_SEED)
        g.update(ci_low=ci.ci_low, ci_high=ci.ci_high, ci_withheld=bool(ci.insufficient_n))
    if n > TOP_K:
        g["mean_without_top5"] = float(np.sort(x)[::-1][TOP_K:].mean())
    g["G1"] = bool(n and g["mean"] > 0)
    g["G2"] = bool(not g["ci_withheld"] and g["ci_low"] is not None and g["ci_low"] > 0)
    g["G3"] = bool(g["mean_without_top5"] is not None and g["mean_without_top5"] > 0)
    g["G4"] = bool(g["missing_exit_rate"] <= MAX_MISSING_EXIT_RATE)
    return g


def verdict(g: dict, floor_adopted: bool | None, floor: dict) -> tuple[str, str]:
    """First match wins (r8 §7). RUN_INVALID (step 0) is decided by the runner, not here."""
    if floor_adopted is None:
        raise ValueError("OWNER_DECISION_PENDING: min_sample_floor_adopted")
    if not g["G4"]:
        return "FAIL", "STEP1_G4_MISSING_EXITS"
    if floor_adopted and (g["n_valid"] < floor["n_valid"] or g["distinct_dates"] < floor["distinct_dates"]):
        return "INCONCLUSIVE", "STEP2_SAMPLE_FLOOR"
    if g["n_valid"] == 0:
        return "INCONCLUSIVE", "STEP2P_N_ZERO"
    if g["mean"] <= 0 or (not g["ci_withheld"] and g["ci_high"] is not None and g["ci_high"] < 0):
        return "FAIL", "STEP3_MEAN_LE_0_OR_CI_HIGH_LT_0"
    if g["G1"] and g["G2"] and g["G3"] and g["G4"]:
        return PASS_LABEL, "STEP4_ALL_GATES"
    return "INCONCLUSIVE", "STEP5_OTHERWISE"


def scheme(label: str) -> str:
    """Mapping to the PASS / FAIL / INCONCLUSIVE scheme."""
    return "PASS" if label == PASS_LABEL else label


def sensitivities(x_primary: np.ndarray, groups: np.ndarray, etf_primary: float, etf_alts=(0.0, 0.0012, 0.0020)) -> dict:
    """Descriptive only (never gating): constant ETF-cost shifts of the primary pair_net."""
    out = {}
    for c in etf_alts:
        y = x_primary + etf_primary - c
        ci = bootstrap_ci_clustered(y, groups, n_resamples=N_RESAMPLES, ci_level=CI_LEVEL, seed=DEFAULT_SEED) if len(y) else None
        out[f"etf_{round(c * 1e4)}bps"] = {"mean": float(y.mean()) if len(y) else None,
                                           "ci_low": ci.ci_low if ci else None, "ci_high": ci.ci_high if ci else None}
    return out
