"""Task72 Part 9/10 -- structural enforcement of the re-audited holdout
boundaries. Distinct from research/task71_lib/holdout_guard.py (which
blanket-blocked ALL of calendar 2024 for Task71's own protection) --
Task72's job is precisely to consume a slice of 2024, so this guard
instead blocks:
  (a) Task70's two already-consumed 2024 blocks (a different strategy's
      outcome was already computed there -- never re-touch, per the
      overnight task's explicit instruction),
  (b) Task71's own DEVELOPMENT range (2025-01-24 .. 2026-08-14), which is
      this candidate's OWN development data and therefore not a valid
      holdout for it,
and permits ONLY the two explicitly locked ranges (VALIDATION,
REPLICATION) once holdout_lock.json has been written -- enforced here by
requiring the caller to pass the locked ranges explicitly rather than by
reading a mutable file, so a code review can see exactly what is allowed
without trusting disk state at runtime.
"""
from __future__ import annotations

from datetime import date, datetime

import pandas as pd

TASK70_CONSUMED_BLOCKS = (
    (date(2024, 2, 1), date(2024, 3, 15)),
    (date(2024, 9, 3), date(2024, 10, 18)),
)
TASK71_DEVELOPMENT_RANGE = (date(2025, 1, 24), date(2026, 8, 14))


class HoldoutViolationError(ValueError):
    pass


def _as_date(value) -> date:
    if isinstance(value, date) and not isinstance(value, datetime):
        return value
    return pd.Timestamp(value).date()


def _overlaps(a_start: date, a_end: date, b_start: date, b_end: date) -> bool:
    return a_start <= b_end and b_start <= a_end


def guard_not_reused_or_contaminated(start, end) -> None:
    """Raises if [start, end] overlaps a Task70-consumed block or Task71's
    own development range. Does NOT by itself grant permission -- callers
    must separately confirm the range matches the exact locked
    VALIDATION/REPLICATION dates before computing any outcome."""
    s, e = _as_date(start), _as_date(end)
    for block_start, block_end in TASK70_CONSUMED_BLOCKS:
        if _overlaps(s, e, block_start, block_end):
            raise HoldoutViolationError(
                f"Requested range [{s}, {e}] overlaps a Task70-consumed block "
                f"[{block_start}, {block_end}] -- do not reuse."
            )
    dev_start, dev_end = TASK71_DEVELOPMENT_RANGE
    if _overlaps(s, e, dev_start, dev_end):
        raise HoldoutViolationError(
            f"Requested range [{s}, {e}] overlaps this candidate's OWN Task71 "
            f"DEVELOPMENT range [{dev_start}, {dev_end}] -- not a valid holdout."
        )


class LockedRangeGuard:
    """Wraps exactly the ranges recorded in holdout_lock.json. Constructed
    with the explicit locked (start, end) tuples; `.check(start, end)`
    raises unless the requested range matches one of them exactly (no
    partial/expanded access permitted past what was locked and committed
    before any outcome was computed)."""

    def __init__(self, locked_ranges: list[tuple]) -> None:
        self._locked = [(_as_date(s), _as_date(e)) for s, e in locked_ranges]
        self.checks_performed = 0

    def check(self, start, end) -> None:
        s, e = _as_date(start), _as_date(end)
        guard_not_reused_or_contaminated(s, e)
        if (s, e) not in self._locked:
            raise HoldoutViolationError(
                f"Requested range [{s}, {e}] is not one of the exact locked "
                f"ranges {self._locked} -- refusing to compute an outcome on an "
                "unlocked range."
            )
        self.checks_performed += 1
