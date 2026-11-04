"""Metrics and gates G1-G5 and the per-horizon decision table (pre-registration: Metrics and gates, Decision table)."""
from __future__ import annotations

import numpy as np
import pandas as pd

from . import config as C

# Newey-West lag = horizon length in rank dates (1D ranks daily, the rest weekly).
NW_LAG = {"1D": 1, "1W": 1, "1M": 4, "3M": 13}
Z95 = 1.6448536269514722


def newey_west_se(x: np.ndarray, lag: int) -> float:
    """Standard error of the mean with a Bartlett-kernel long-run variance."""
    x = np.asarray(x, float)
    x = x[~np.isnan(x)]
    n = len(x)
    if n < 3:
        return float("nan")
    d = x - x.mean()
    lrv = float(d @ d) / n
    for l in range(1, min(lag, n - 1) + 1):
        lrv += 2.0 * (1.0 - l / (lag + 1.0)) * float(d[l:] @ d[:-l]) / n
    return float(np.sqrt(max(lrv, 0.0) / n))


def spearman(a: np.ndarray, b: np.ndarray) -> float:
    a, b = pd.Series(a).rank().to_numpy(), pd.Series(b).rank().to_numpy()
    if a.std() == 0 or b.std() == 0:
        return float("nan")
    return float(np.corrcoef(a, b)[0, 1])


def ece(prob: np.ndarray, outcome: np.ndarray, bins: int = 10) -> float:
    """Expected calibration error with equal-count bins."""
    if len(prob) == 0:
        return float("nan")
    o = np.argsort(prob, kind="stable")
    p, y = prob[o], outcome[o].astype(float)
    err, n = 0.0, len(p)
    for chunk in np.array_split(np.arange(n), bins):
        if len(chunk):
            err += len(chunk) / n * abs(p[chunk].mean() - y[chunk].mean())
    return float(err)


def gates(per_date: pd.DataFrame, pooled: dict, horizon: str) -> dict:
    """per_date: index = rank date; columns ic, top, bottom (mean excess return of each decile).
    pooled: bull_hits, bull_n, bear_hits, bear_n, prob (array), outcome (array)."""
    ic = per_date["ic"].dropna()
    mean_ic = float(ic.mean()) if len(ic) else float("nan")
    se = newey_west_se(ic.to_numpy(), NW_LAG[horizon])
    lower = mean_ic - Z95 * se if np.isfinite(se) else float("nan")
    top, bot = float(per_date["top"].mean()), float(per_date["bottom"].mean())
    months = ic.groupby([ic.index.year, ic.index.month]).mean()
    pos_share = float((months > 0).mean()) if len(months) else float("nan")
    half = len(ic) // 2
    h1, h2 = (float(ic.iloc[:half].mean()), float(ic.iloc[half:].mean())) if half else (float("nan"), float("nan"))
    bull = pooled["bull_hits"] / pooled["bull_n"] if pooled["bull_n"] else float("nan")
    bear = pooled["bear_hits"] / pooled["bear_n"] if pooled["bear_n"] else float("nan")
    cal = ece(pooled["prob"], pooled["outcome"])
    res = {
        "mean_ic": mean_ic, "ic_se_nw": se, "ic_lower95": lower, "n_rank_dates": int(len(ic)),
        "top_excess": top, "bottom_excess": bot, "months": int(len(months)), "positive_month_share": pos_share,
        "ic_half1": h1, "ic_half2": h2, "bull_hit": bull, "bear_hit": bear, "ece": cal,
    }
    res["G1"] = bool(mean_ic > C.G1_MIN_IC and lower > 0)
    res["G2"] = bool(top - C.COST_BULL_BPS / 1e4 > 0)
    res["G3"] = bool(bot * 1e4 < C.G3_MAX_BEAR_EXCESS_BPS)
    res["G4"] = bool(pos_share >= C.G4_MIN_POSITIVE_MONTH_SHARE and h1 > 0 and h2 > 0)
    res["G5"] = bool(bull >= C.G5_MIN_BULL_HIT and bear <= C.G5_MAX_BEAR_HIT and cal <= C.G5_MAX_CAL_ERROR)
    return res


def decide(g: dict, horizon: str) -> tuple[str, str]:
    """(outcome, note). Implements the pre-registered table. One cell the table does not define is resolved conservatively and flagged:
    G1, G4 pass, exactly one of G2/G3 passes, G5 fails -> FAIL_NO_VALUE (no view)."""
    g1, g2, g3, g4, g5 = (g[k] for k in ("G1", "G2", "G3", "G4", "G5"))
    if not g1:
        return "FAIL", ""
    if not g4:
        return "FAIL_UNSTABLE", "G1 passes, G4 fails"
    if not g2 and not g3:
        return "FAIL_NO_VALUE", ""
    if g2 and g3:
        if g5:
            return ("PROVISIONAL", "both sides") if horizon == "3M" else ("PASS", "")
        return "PASS_RANK_ONLY", ""
    side = "Bullish" if g2 else "Bearish"
    if g5:
        return ("PROVISIONAL", f"{side} side only") if horizon == "3M" else ("PASS_ONE_SIDED", f"{side} side only")
    return "FAIL_NO_VALUE", f"UNDEFINED CELL in the pre-registration (one side passes, G5 fails); resolved conservatively; {side} side only passed G2/G3"


PASSING = {"PASS", "PASS_ONE_SIDED", "PASS_RANK_ONLY", "PROVISIONAL"}


def programme_outcome(outcomes: dict[str, str], holdout_ic: dict[str, float], train_ic: dict[str, float]) -> dict:
    passing = [h for h, o in outcomes.items() if o in PASSING]
    # The audit is called for only "before anything goes forward", i.e. when at least one horizon passes.
    audit = bool(passing) and (
        passing == ["1D"]                                                              # only H-1D passes: likely leak
        or len(passing) == len(outcomes)                                               # every horizon passes
        or any(holdout_ic.get(h, -1) > train_ic.get(h, 1e9) for h in outcomes))        # HOLDOUT IC above TRAIN IC anywhere
    if not passing:
        action = "CLOSE_SCORECARD_LANE"
    elif passing == ["1D"]:
        action = "LEAKAGE_AUDIT_THEN_FORWARD_1D_ONLY_IF_CLEAN"
    else:
        action = "START_FORWARD_FOR_PASSING_HORIZONS"
    return {"passing": passing, "leakage_audit_required": audit, "action": action}
