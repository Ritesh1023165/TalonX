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
