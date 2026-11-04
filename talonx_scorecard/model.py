"""EQ and RIDGE composites, isotonic calibration, and the per-segment evaluation loop. One scoring path for all of them."""
from __future__ import annotations

import numpy as np
import pandas as pd
from sklearn.isotonic import IsotonicRegression
from sklearn.linear_model import Ridge

from . import config as C
from . import labels, metrics
from .features import signed_scores

FIDS = [f.id for f in C.FEATURES]


def build_cube(raw: dict, universe: pd.DataFrame, dates) -> dict:
    """date -> (names x 12) signed score matrix. Same function the live scorecard uses (features.signed_scores)."""
    return {d: signed_scores(raw, universe.loc[d], d) for d in dates}


def _label_row(excess: pd.DataFrame, d, names) -> pd.Series:
    return excess.loc[d].reindex(names) if d in excess.index else pd.Series(np.nan, index=names)


def fit_ridge(cube: dict, excess: pd.DataFrame, dates) -> pd.Series:
    """Ridge (alpha fixed) on TRAIN. Target = the label ranked 0-1 within each date (outlier-robust, matches the rank-IC objective)."""
    xs, ys = [], []
    for d in dates:
        x = cube[d]
        y = _label_row(excess, d, x.index).rank(pct=True)
        ok = y.notna()
        if ok.sum() >= 30:
            xs.append(x[ok].to_numpy()); ys.append(y[ok].to_numpy() - 0.5)
    if not xs:
        raise ValueError("no TRAIN rows to fit")
    m = Ridge(alpha=C.RIDGE_ALPHA, fit_intercept=True).fit(np.vstack(xs), np.concatenate(ys))
    return pd.Series(m.coef_, index=FIDS)


def composite(x: pd.DataFrame, weights: pd.Series | None) -> pd.Series:
    return x.mean(axis=1) if weights is None else x.mul(weights.reindex(x.columns), axis=1).sum(axis=1)


def fit_calibration(cube: dict, excess: pd.DataFrame, dates, weights: pd.Series | None) -> IsotonicRegression:
    """Isotonic map from within-date composite percentile to P(beat SPY), fitted once on TRAIN."""
    r, o = [], []
    for d in dates:
        x = cube[d]
        y = _label_row(excess, d, x.index)
        ok = y.notna()
        if ok.sum() >= 30:
            r.append(composite(x, weights).rank(pct=True)[ok].to_numpy()); o.append((y[ok] > 0).to_numpy(float))
    iso = IsotonicRegression(y_min=0.0, y_max=1.0, increasing=True, out_of_bounds="clip")
    return iso.fit(np.concatenate(r), np.concatenate(o))


def evaluate(cube: dict, excess: pd.DataFrame, dates, weights: pd.Series | None, iso: IsotonicRegression, horizon: str,
             min_names: int = 30) -> tuple[pd.DataFrame, dict]:
    """Per-date IC and decile returns plus pooled hit counts and calibrated probabilities for one segment."""
    rows, bh, bn, rh, rn, probs, outs = [], 0, 0, 0, 0, [], []
    for d in dates:
        x = cube[d]
        if len(x) < min_names:
            continue
        comp = composite(x, weights)
        rk = comp.rank(pct=True)
        y = _label_row(excess, d, x.index)
        ok = y.notna()
        if ok.sum() < min_names:
            continue
        yy, cc, rr = y[ok], comp[ok], rk[ok]
        top, bot = yy[rr >= 1.0 - C.DECILE], yy[rr <= C.DECILE]
        rows.append((d, metrics.spearman(cc.to_numpy(), yy.to_numpy()), float(top.mean()), float(bot.mean()), len(top), len(bot)))
        bh += int((top > 0).sum()); bn += len(top); rh += int((bot > 0).sum()); rn += len(bot)
        probs.append(iso.predict(rr.to_numpy())); outs.append((yy > 0).to_numpy(float))
    per = pd.DataFrame(rows, columns=["date", "ic", "top", "bottom", "n_top", "n_bot"]).set_index("date")
    pooled = {"bull_hits": bh, "bull_n": bn, "bear_hits": rh, "bear_n": rn,
              "prob": np.concatenate(probs) if probs else np.array([]), "outcome": np.concatenate(outs) if outs else np.array([])}
    return per, pooled


def segment_dates(sessions, horizon: str, segment: str):
    return labels.segment_rank_dates(sessions, horizon, segment)
