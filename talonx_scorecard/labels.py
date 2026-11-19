"""Excess-return labels, rank dates and purged segment membership (pre-registration: Labels, Sample, Metrics)."""
from __future__ import annotations

import numpy as np
import pandas as pd

from . import config as C


def excess_return(adj_close: pd.DataFrame, spy: pd.Series, h: int) -> pd.DataFrame:
    """Stock adjusted return minus SPY return over [t, t+h] sessions. NaN when t+h falls past the last session.

    ``adj_close``: sessions x symbols (split/dividend adjusted). ``spy``: same session index.
    """
    if not adj_close.index.equals(spy.index):
        raise ValueError("adj_close and spy must share the same session index")
    fwd = adj_close.shift(-h) / adj_close - 1.0
    spy_fwd = spy.shift(-h) / spy - 1.0
    return fwd.sub(spy_fwd, axis=0)


def label_available(adj_close: pd.DataFrame, spy: pd.Series, h: int) -> pd.DataFrame:
    """True where a label could be computed (price at t and t+h for the stock and for SPY). Computes NO return.

    Data gate 2 uses this so coverage can be checked before any outcome exists.
    """
    if not adj_close.index.equals(spy.index):
        raise ValueError("adj_close and spy must share the same session index")
    ok_spy = (spy.notna() & spy.shift(-h).notna()).to_numpy()
    ok = adj_close.notna() & adj_close.shift(-h).notna()
    return ok.mul(ok_spy, axis=0).astype(bool)


def rank_dates(sessions: pd.DatetimeIndex, horizon: str) -> pd.DatetimeIndex:
    """1D: every session. Others: the last session of each ISO week (the Friday close, or earlier if closed)."""
    sessions = pd.DatetimeIndex(sessions).sort_values()
    if horizon in C.RANK_DAILY:
        return sessions
    iso = sessions.isocalendar()
    wk = pd.Series(sessions, index=pd.MultiIndex.from_arrays([iso["year"].to_numpy(), iso["week"].to_numpy()]))
    return pd.DatetimeIndex(wk.groupby(level=[0, 1]).max().sort_values().to_numpy())


def segment_rank_dates(sessions: pd.DatetimeIndex, horizon: str, segment: str) -> pd.DatetimeIndex:
    """Rank dates of a segment whose label window [t, t+h] ends strictly before the NEXT segment's first session.

    The gap is purged, not shifted. HOLDOUT is last, so its windows only have to exist inside the sample.
    """
    if segment not in C.SEGMENTS:
        raise ValueError(f"unknown segment {segment!r}")
    sessions = pd.DatetimeIndex(sessions).sort_values()
    h = C.HORIZONS[horizon]
    lo, hi = (pd.Timestamp(x) for x in C.SEGMENTS[segment])
    cand = rank_dates(sessions, horizon)
    cand = cand[(cand >= lo) & (cand <= hi)]
    pos = {d: i for i, d in enumerate(sessions)}
    idx = np.array([pos[d] for d in cand])
    nxt = C.SEGMENT_ORDER.index(segment) + 1
    if nxt < len(C.SEGMENT_ORDER):
        next_start = pd.Timestamp(C.SEGMENTS[C.SEGMENT_ORDER[nxt]][0])
        limit = int(sessions.searchsorted(next_start))      # index of next segment's first session
        keep = idx + h < limit
    else:
        keep = idx + h < len(sessions)
    return cand[keep]
