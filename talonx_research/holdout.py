"""
Discovery / holdout window management (Task 115.D / R3).

A version is developed/tuned on the DISCOVERY window, then FROZEN
(immutable fingerprint), then evaluated on the HOLDOUT window.  The
validation runner must not tune on holdout -- this module only *splits*
and *records* windows; it never selects parameters.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from typing import Any

import pandas as pd

# The frozen chronological cut used for INSIDER_BUY_CLUSTER_V2 (Task 107B).
V2_HOLDOUT_CUTOFF = "2023-07-01"


@dataclass(frozen=True)
class Windows:
    validation_start: str
    validation_end: str
    holdout_cutoff: str

    @property
    def discovery(self) -> dict[str, str]:
        return {"start": self.validation_start, "end": self.holdout_cutoff}

    @property
    def holdout(self) -> dict[str, str]:
        return {"start": self.holdout_cutoff, "end": self.validation_end}

    def to_dict(self) -> dict[str, Any]:
        return {"validation": {"start": self.validation_start, "end": self.validation_end},
                "discovery": self.discovery, "holdout": self.holdout,
                "holdout_cutoff": self.holdout_cutoff,
                "note": "holdout evaluated only AFTER the version was frozen; "
                        "no parameter was tuned on holdout (R3)."}


def make_windows(start: str, end: str, holdout_cutoff: str = V2_HOLDOUT_CUTOFF) -> Windows:
    s, e = date.fromisoformat(start), date.fromisoformat(end)
    hc = date.fromisoformat(holdout_cutoff)
    if not (s < hc < e):
        # if the validation window is entirely after the frozen cutoff,
        # split it in half chronologically (still no tuning on the 2nd half).
        mid = s + (e - s) / 2
        hc = mid
    return Windows(start, end, hc.isoformat())


def split(df: pd.DataFrame, windows: Windows, *, date_col: str = "entry_session"):
    d = df.copy()
    d[date_col] = pd.to_datetime(d[date_col])
    cut = pd.Timestamp(windows.holdout_cutoff)
    return d[d[date_col] < cut].copy(), d[d[date_col] >= cut].copy()
