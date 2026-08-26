"""Task74 -- blocks ALL of calendar year 2024 (this task is DEVELOPMENT
ONLY; both the reserved-validation 2024-06-01..09-02 block and the
reserved-replication 2024-10-21..12-20 block must remain untouched by
this task's own code). Same pattern as research/task71_lib/holdout_guard.py.
"""
from __future__ import annotations

from datetime import date, datetime

import pandas as pd

BLOCKED_YEAR = 2024


class HoldoutProtectionError(ValueError):
    pass


def _as_date(value) -> date:
    if isinstance(value, date) and not isinstance(value, datetime):
        return value
    return pd.Timestamp(value).date()


def guard_date_range(start, end) -> None:
    start_d, end_d = _as_date(start), _as_date(end)
    if start_d.year <= BLOCKED_YEAR <= end_d.year:
        raise HoldoutProtectionError(
            f"Task74 requested a date range [{start_d}, {end_d}] touching {BLOCKED_YEAR} -- "
            "this task is DEVELOPMENT ONLY; all of 2024 (including the reserved "
            "validation/replication blocks) is protected."
        )


def guard_path_or_label(value: str) -> None:
    if str(BLOCKED_YEAR) in str(value):
        raise HoldoutProtectionError(f"Task74 requested a path/label containing '{BLOCKED_YEAR}': {value!r} -- blocked.")


class DevelopmentOnlyGuard:
    def __init__(self) -> None:
        self.checks_performed = 0

    def check(self, start, end) -> None:
        guard_date_range(start, end)
        self.checks_performed += 1
