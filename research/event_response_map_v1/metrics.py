"""EVENT_RESPONSE_MAP_V1 C5-C8 -- per-cell metrics, SCREEN_PASS rule and trial ledger (locked before any data)."""
from __future__ import annotations

import numpy as np
import pandas as pd

from research.common.research_stats import DEFAULT_SEED, bootstrap_ci_clustered
from research.event_response_map_v1.events import EVENT_TYPES, HORIZONS, NON_NOMINATABLE

COST_BPS = {"L1": 30, "L2": 20, "L3": 12}
DIRECTIONS = ("LONG", "SHORT")
YEARS = (2019, 2020, 2021, 2022, 2023)
MIN_N, MIN_DATES = 300, 150
COST_MULTIPLE = 2.0
MIN_STABLE_YEARS = 4
MIN_YEAR_N = 20
TOP_K = (1, 3, 5)
N_RESAMPLES, CI_LEVEL = 10_000, 0.95
MAX_MISSING_EXIT_RATE = 0.02                 # LOCK REV 2 (R3): > 2 % missing exits -> cannot be SCREEN_PASS
# R3 non-gating bound sensitivity: value assigned to a missing exit, by scenario and direction (gross, as return)
MISSING_EXIT_BOUNDS = {"BOUND_LONG_MINUS100_SHORT_0": {"LONG": -1.0, "SHORT": 0.0},
                       "BOUND_MIRROR_LONG_0_SHORT_MINUS100": {"LONG": 0.0, "SHORT": -1.0}}
assert DEFAULT_SEED == 670067


def cells() -> list[tuple[str, str, str, str]]:
    return [(e, d, h, b) for e in EVENT_TYPES for d in DIRECTIONS for h in HORIZONS for b in COST_BPS]


def _sign(x: float) -> int:
    return 1 if x > 0 else (-1 if x < 0 else 0)


def cell_metrics(obs: pd.DataFrame, direction: str, bucket: str, *, n_resamples: int = N_RESAMPLES) -> dict:
    """obs: rows of ONE (event_type, horizon, bucket) with ret_raw / ret_spy_rel / ret_sector_rel (LONG gross).
    The SHORT direction is the sign-flipped series (RESEARCH_SHORT_REFERENCE). Rows with missing_exit=True (R3)
    are excluded from every metric and counted in missing_exit_rate = missing / (valid + missing)."""
    if "missing_exit" in obs.columns:
        miss_mask = obs["missing_exit"].fillna(False).astype(bool).to_numpy()
        n_missing = int(miss_mask.sum())
        obs = obs.loc[~miss_mask]
    else:
        n_missing = 0
    s = 1.0 if direction == "LONG" else -1.0
    x = s * obs["ret_sector_rel"].to_numpy(dtype=float)
    n = len(x)
    m = {"n": n, "distinct_dates": int(obs["entry_date"].nunique()), "distinct_symbols": int(obs["symbol"].nunique()),
         "cost_bps": COST_BPS[bucket], "n_missing_exit": n_missing,
         "missing_exit_rate": (n_missing / (n + n_missing)) if (n + n_missing) else 0.0}
    if n == 0:
        return m
    m.update({
        "mean_raw": float(s * obs["ret_raw"].mean()), "median_raw": float(s * obs["ret_raw"].median()),
        "mean_spy_relative": float(s * obs["ret_spy_rel"].mean()),
        "mean_sector_relative": float(x.mean()), "median_sector_relative": float(np.median(x)),
        "mean_sector_relative_net": float(x.mean() - COST_BPS[bucket] / 1e4),
        "hit_rate": float((x > 0).mean()), "dispersion_sd": float(x.std(ddof=1)) if n > 1 else None,
    })
    ci = bootstrap_ci_clustered(x, obs["entry_date"].astype(str).to_numpy(), n_resamples=n_resamples,
                                ci_level=CI_LEVEL, seed=DEFAULT_SEED)
    m.update({"ci_low": ci.ci_low, "ci_high": ci.ci_high, "ci_insufficient_n": ci.insufficient_n})
    order = np.sort(x)[::-1]                              # largest in the cell's direction first
    for k in TOP_K:
        m[f"mean_without_top{k}"] = float(order[k:].mean()) if n > k else None
    years = pd.to_datetime(obs["entry_date"]).dt.year.to_numpy()
    overall = _sign(x.mean())
    per_year, stable = {}, 0
    for y in YEARS:
        xy = x[years == y]
        per_year[str(y)] = {"n": int(len(xy)), "mean": float(xy.mean()) if len(xy) else None}
        if len(xy) >= MIN_YEAR_N and overall != 0 and _sign(xy.mean()) == overall:
            stable += 1
    m["per_year"], m["stable_years"] = per_year, stable
    if m["missing_exit_rate"] <= MAX_MISSING_EXIT_RATE:   # R3 bounds only for cells that remain eligible
        m["missing_exit_bounds"] = {}
        for name, fill in MISSING_EXIT_BOUNDS.items():
            xb = np.concatenate([x, np.full(n_missing, fill[direction])])
            mb = float(xb.mean())
            m["missing_exit_bounds"][name] = {"mean_sector_relative": mb,
                                              "mean_ge_2x_cost": mb >= COST_MULTIPLE * COST_BPS[bucket] / 1e4,
                                              "sign_unchanged": _sign(mb) == _sign(float(x.mean()))}
    m["suspect_adjustment_n"] = int(obs.get("suspect_adjustment", pd.Series(dtype=bool)).sum())
    if m["suspect_adjustment_n"]:
        keep = ~obs["suspect_adjustment"].to_numpy(dtype=bool)
        m["sensitivity_mean_sector_relative_ex_suspect"] = float(x[keep].mean()) if keep.any() else None
    return m


def screen(m: dict, event_type: str) -> dict:
    """SCREEN_PASS = all six criteria. Means are in the cell's direction, so a mirrored LONG/SHORT pair can pass at
    most once (the 390 cells are 195 independent sign tests)."""
    c = {
        "n_ge_300": m.get("n", 0) >= MIN_N,
        "dates_ge_150": m.get("distinct_dates", 0) >= MIN_DATES,
        "mean_ge_2x_cost": m.get("mean_sector_relative", -1) >= COST_MULTIPLE * m["cost_bps"] / 1e4,
        "ci_excludes_zero": m.get("ci_low") is not None and (m["ci_low"] > 0 or m["ci_high"] < 0)
                            and _sign(m["ci_low"]) == _sign(m.get("mean_sector_relative", 0)),
        "sign_stable_4_of_5": m.get("stable_years", 0) >= MIN_STABLE_YEARS,
        "top5_removal_keeps_sign": m.get("mean_without_top5") is not None
                                   and _sign(m["mean_without_top5"]) == _sign(m.get("mean_sector_relative", 0)) != 0,
        "missing_exit_rate_le_2pct": m.get("missing_exit_rate", 0.0) <= MAX_MISSING_EXIT_RATE,
    }
    passed = all(c.values())
    return {"criteria": c, "SCREEN_PASS": passed,
            "nominatable": passed and event_type not in NON_NOMINATABLE,
            "label": ("CONTROL" if event_type == "NO_EVENT" else
                      "KNOWN_UNSUPPORTED_BASELINE" if event_type == "FORM4_CLUSTER" else "DISCOVERY")}


def classify(ledger: list[dict]) -> dict:
    """LOCK REV 2 (R2) null calibration: ANY NO_EVENT cell SCREEN_PASS -> MAP_MISCALIBRATED and NO candidate may be
    nominated until it is explained (every cell's nominatable is forced False). Mutates and returns the summary."""
    k = sum(1 for c in ledger if c["event_type"] == "NO_EVENT" and c["screen"]["SCREEN_PASS"])
    mis = k > 0
    if mis:
        for c in ledger:
            c["screen"]["nominatable"] = False
            c["screen"]["nomination_blocked"] = "MAP_MISCALIBRATED"
    return {"no_event_screen_pass": k,
            "no_event_cells": sum(1 for c in ledger if c["event_type"] == "NO_EVENT"),
            "classification": "MAP_MISCALIBRATED" if mis else "NULL_CALIBRATION_CLEAN",
            "nomination_allowed": not mis,
            "screen_pass_total": sum(1 for c in ledger if c["screen"]["SCREEN_PASS"]),
            "nominatable_cells": sum(1 for c in ledger if c["screen"]["nominatable"])}


def evaluate(obs: pd.DataFrame, *, n_resamples: int = N_RESAMPLES) -> list[dict]:
    """Every cell in the locked grid is evaluated and ledgered (empty cells included, n=0)."""
    ledger = []
    for e, d, h, b in cells():
        sub = obs[(obs["event_type"] == e) & (obs["horizon"] == h) & (obs["bucket"] == b)]
        m = cell_metrics(sub, d, b, n_resamples=n_resamples)
        ledger.append({"cell": f"{e}|{d}|{h}|{b}", "event_type": e, "direction": d, "horizon": h, "bucket": b,
                       "metrics": m, "screen": screen(m, e)})
    return ledger
