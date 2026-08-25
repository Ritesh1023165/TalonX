"""Task71 Part 22 -- structural enforcement that Task71 code can never
touch calendar year 2024 (Task70's consumed holdout blocks, plus all
remaining clean 2024 territory). Raises immediately, before any file I/O,
on any 2024 date."""
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
    """Raises HoldoutProtectionError if [start, end] touches any part of
    calendar year 2024."""
    start_d, end_d = _as_date(start), _as_date(end)
    if start_d.year <= BLOCKED_YEAR <= end_d.year:
        raise HoldoutProtectionError(
            f"Task71 requested a date range [{start_d}, {end_d}] touching {BLOCKED_YEAR} -- "
            "calendar year 2024 is protected holdout territory (Task70 consumed part of it, "
            "the rest must remain untouched for a future task's fresh holdout audit)."
        )


def guard_path_or_label(value: str) -> None:
    """Defensive string check for a data directory name / label that
    might encode a 2024 date (e.g. 'task71_development_2024q1')."""
    if str(BLOCKED_YEAR) in str(value):
        raise HoldoutProtectionError(
            f"Task71 requested a path/label containing '{BLOCKED_YEAR}': {value!r} -- blocked."
        )


class DevelopmentOnlyGuard:
    """Wraps a data-loading call site: call `.check(start, end)` before
    touching any file path derived from a caller-supplied date range."""

    def __init__(self) -> None:
        self.checks_performed = 0

    def check(self, start, end) -> None:
        guard_date_range(start, end)
        self.checks_performed += 1
