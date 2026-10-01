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
assert DEFAULT_SEED == 670067


def cells() -> list[tuple[str, str, str, str]]:
    return [(e, d, h, b) for e in EVENT_TYPES for d in DIRECTIONS for h in HORIZONS for b in COST_BPS]


def _sign(x: float) -> int:
    return 1 if x > 0 else (-1 if x < 0 else 0)


def cell_metrics(obs: pd.DataFrame, direction: str, bucket: str, *, n_resamples: int = N_RESAMPLES) -> dict:
    """obs: rows of ONE (event_type, horizon, bucket) with ret_raw / ret_spy_rel / ret_sector_rel (LONG gross).
    The SHORT direction is the sign-flipped series (RESEARCH_SHORT_REFERENCE)."""
    s = 1.0 if direction == "LONG" else -1.0
    x = s * obs["ret_sector_rel"].to_numpy(dtype=float)
    n = len(x)
    m = {"n": n, "distinct_dates": int(obs["entry_date"].nunique()), "distinct_symbols": int(obs["symbol"].nunique()),
         "cost_bps": COST_BPS[bucket]}
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
    }
    passed = all(c.values())
    return {"criteria": c, "SCREEN_PASS": passed,
            "nominatable": passed and event_type not in NON_NOMINATABLE,
            "label": ("CONTROL" if event_type == "NO_EVENT" else
                      "KNOWN_UNSUPPORTED_BASELINE" if event_type == "FORM4_CLUSTER" else "DISCOVERY")}


def evaluate(obs: pd.DataFrame, *, n_resamples: int = N_RESAMPLES) -> list[dict]:
    """Every cell in the locked grid is evaluated and ledgered (empty cells included, n=0)."""
    ledger = []
    for e, d, h, b in cells():
        sub = obs[(obs["event_type"] == e) & (obs["horizon"] == h) & (obs["bucket"] == b)]
        m = cell_metrics(sub, d, b, n_resamples=n_resamples)
        ledger.append({"cell": f"{e}|{d}|{h}|{b}", "event_type": e, "direction": d, "horizon": h, "bucket": b,
                       "metrics": m, "screen": screen(m, e)})
    return ledger
