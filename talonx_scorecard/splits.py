"""Data gate 1: split-adjustment check on every known split in the sample.

An adjusted series is acceptable when its return across a split's ex-date looks like an ordinary day, not like the
unadjusted jump. For a split of ``ratio`` new shares per old share the unadjusted close return is ``1/ratio - 1``.
"""
from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np
import pandas as pd


@dataclass(frozen=True)
class Split:
    symbol: str
    ex_date: pd.Timestamp
    ratio: float          # new shares per old share: 2.0 for 2-for-1, 0.1 for 1-for-10 reverse


@dataclass
class SplitCheck:
    checked: int = 0
    passed: int = 0
    failures: list = field(default_factory=list)   # (symbol, ex_date, reason, adj_log_return)

    @property
    def ok(self) -> bool:
        return not self.failures


def check_split_adjustment(adj_close: pd.DataFrame, splits: list[Split]) -> SplitCheck:
    """Every split must be present in the data and adjusted. A split with no usable bars is a failure, not a skip."""
    out = SplitCheck()
    for sp in splits:
        out.checked += 1
        if sp.ratio <= 0 or abs(np.log(sp.ratio)) < 1e-9:
            out.failures.append((sp.symbol, sp.ex_date, "INVALID_RATIO", float("nan")))
            continue
        if sp.symbol not in adj_close.columns:
            out.failures.append((sp.symbol, sp.ex_date, "SYMBOL_MISSING", float("nan")))
            continue
        s = adj_close[sp.symbol].dropna()
        if sp.ex_date not in s.index:
            out.failures.append((sp.symbol, sp.ex_date, "EX_DATE_MISSING", float("nan")))
            continue
        i = s.index.get_loc(sp.ex_date)
        if i == 0:
            out.failures.append((sp.symbol, sp.ex_date, "NO_PRIOR_BAR", float("nan")))
            continue
        r = float(np.log(s.iloc[i] / s.iloc[i - 1]))
        unadjusted = float(np.log(1.0 / sp.ratio))
        if abs(r - unadjusted) < abs(r):             # closer to the raw split jump than to "no move"
            out.failures.append((sp.symbol, sp.ex_date, "NOT_ADJUSTED", r))
        else:
            out.passed += 1
    return out


def classify_splits(adj_close: pd.DataFrame, splits: list[Split], start: str, end: str, max_gap: int = 5,
                    universe: pd.DataFrame | None = None) -> list[tuple]:
    """Diagnostic classification of every split. Rows: (symbol, ex_date, status, ratio, adj_log_return, gap_sessions).

    Compares the last bar BEFORE the ex-date with the first bar ON OR AFTER it, so a missing ex-date bar is not itself a
    failure. Statuses: ADJUSTED, NOT_ADJUSTED, OUT_OF_SAMPLE, INVALID_RATIO, SYMBOL_MISSING, NO_PRIOR_BAR,
    NO_LATER_BAR, GAP_TOO_LONG (more than ``max_gap`` missing sessions between the two bars), and, when ``universe`` is given
    (Amendment 1), NOT_IN_UNIVERSE: the symbol was not in the tradable universe on the last session before or the first
    session on/after the ex-date. Such splits are reported but not counted by gate 1.
    """
    lo, hi = pd.Timestamp(start), pd.Timestamp(end)
    sessions = adj_close.index
    rows = []
    for sp in splits:
        def out(status, r=float("nan"), gap=-1):
            rows.append((sp.symbol, sp.ex_date, status, sp.ratio, r, gap))
        if not (lo <= sp.ex_date <= hi):
            out("OUT_OF_SAMPLE"); continue
        if sp.ratio <= 0 or abs(np.log(sp.ratio)) < 1e-9:
            out("INVALID_RATIO"); continue
        if universe is not None:
            in_uni = False
            if sp.symbol in universe.columns:
                u = universe[sp.symbol]
                b, a = u[u.index < sp.ex_date], u[u.index >= sp.ex_date]
                in_uni = bool((len(b) and b.iloc[-1]) or (len(a) and a.iloc[0]))
            if not in_uni:
                out("NOT_IN_UNIVERSE"); continue
        if sp.symbol not in adj_close.columns:
            out("SYMBOL_MISSING"); continue
        s = adj_close[sp.symbol].dropna()
        before, after = s[s.index < sp.ex_date], s[s.index >= sp.ex_date]
        if before.empty:
            out("NO_PRIOR_BAR"); continue
        if after.empty:
            out("NO_LATER_BAR"); continue
        gap = int(sessions.get_indexer([after.index[0]])[0] - sessions.get_indexer([before.index[-1]])[0]) - 1
        if gap > max_gap:
            out("GAP_TOO_LONG", gap=gap); continue
        r = float(np.log(after.iloc[0] / before.iloc[-1]))
        unadjusted = float(np.log(1.0 / sp.ratio))
        out("NOT_ADJUSTED" if abs(r - unadjusted) < abs(r) else "ADJUSTED", r, gap)
    return rows
