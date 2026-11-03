"""The ONE scoring function used by backtest and live scorecard (pre-registration: Code identity).

EQ composite only here. RIDGE and calibration are added in the model stage; they plug in via ``weights``.
"""
from __future__ import annotations

import pandas as pd

from . import config as C
from .features import signed_scores


def score(panel: dict, date: pd.Timestamp, weights: pd.Series | None = None) -> pd.DataFrame:
    """panel: {'raw': {fid: sessions x symbols frame}, 'universe': bool frame}. Returns one row per scored symbol with
    ``composite``, ``rank`` (percentile 0-1 among scored names) and ``view`` (Bullish / Bearish / Neutral)."""
    sig = signed_scores(panel["raw"], panel["universe"].loc[date], date)
    if sig.empty:
        return pd.DataFrame(columns=["composite", "rank", "view"])
    if weights is None:
        comp = sig.mean(axis=1)                                   # EQ: equal weight, nothing fitted
    else:
        w = weights.reindex(sig.columns)
        if w.isna().any():
            raise ValueError("weights must cover all 12 features")
        comp = sig.mul(w, axis=1).sum(axis=1)
    rank = comp.rank(pct=True)
    view = pd.Series("Neutral", index=comp.index)
    view[rank >= 1.0 - C.DECILE] = "Bullish"
    view[rank <= C.DECILE] = "Bearish"
    return pd.DataFrame({"composite": comp, "rank": rank, "view": view}).sort_values("rank", ascending=False)
