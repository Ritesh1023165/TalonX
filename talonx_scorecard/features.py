"""Feature construction (pre-registration: Labels and features). Pure functions, no network, no outcomes.

Price features F1-F4 are computed from split/dividend-adjusted closes. F5-F12 need the SEC stage and are supplied as
``raw`` frames (sessions x symbols), already point-in-time (each value usable only from its public time).
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from . import config as C


def raw_price_features(adj_close: pd.DataFrame) -> dict[str, pd.DataFrame]:
    """F1 5d return; F2 21d return skipping the last 5; F3 12m return skipping the last month; F4 60d volatility."""
    c = adj_close
    daily = c.pct_change(fill_method=None)
    return {
        "F1": c / c.shift(5) - 1.0,
        "F2": c.shift(5) / c.shift(26) - 1.0,
        "F3": c.shift(21) / c.shift(252) - 1.0,
        "F4": daily.rolling(60, min_periods=60).std(),
    }


def _rank_winsor(x: pd.Series) -> pd.Series:
    """Cross-sectional rank to (0, 1], then winsorise at the 1st and 99th percentile of the ranks (as written)."""
    r = x.rank(pct=True)
    if r.notna().sum() < 2:
        return r
    lo, hi = r.quantile(C.WINSOR[0]), r.quantile(C.WINSOR[1])
    return r.clip(lo, hi)


def signed_scores(raw: dict[str, pd.DataFrame], universe_row: pd.Series, date: pd.Timestamp) -> pd.DataFrame:
    """symbols x 12 matrix of signed scores in [0, 1] for one rank date (higher = more bullish).

    Names outside the universe are excluded. A name missing MORE than C.MAX_MISSING_FEATURES features is dropped from
    the date; remaining gaps are filled with 0.5.
    """
    names = universe_row.index[universe_row.to_numpy(dtype=bool)]
    cols = {}
    for f in C.FEATURES:
        if f.id in raw and date in raw[f.id].index:
            x = raw[f.id].loc[date].reindex(names)
        else:
            x = pd.Series(np.nan, index=names)
        r = _rank_winsor(x.replace([np.inf, -np.inf], np.nan))
        cols[f.id] = r if f.sign > 0 else 1.0 - r
    m = pd.DataFrame(cols, index=names)
    keep = m.isna().sum(axis=1) <= C.MAX_MISSING_FEATURES
    return m[keep].fillna(C.MISSING_FILL)
