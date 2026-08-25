"""Task72 -- holdout guard tests: blocks Task70-consumed 2024 blocks and
Task71's own development range; permits only exactly-locked ranges."""
from __future__ import annotations

import pytest

from research.task72_residual_momentum.holdout_guard import (
    HoldoutViolationError, LockedRangeGuard, guard_not_reused_or_contaminated,
)

VALIDATION_RANGE = ("2024-04-01", "2024-05-31")
REPLICATION_RANGE = ("2024-10-21", "2024-12-20")


def test_blocks_task70_consumed_blocks():
    with pytest.raises(HoldoutViolationError):
        guard_not_reused_or_contaminated("2024-02-15", "2024-02-20")
    with pytest.raises(HoldoutViolationError):
        guard_not_reused_or_contaminated("2024-09-10", "2024-09-15")


def test_blocks_task71_development_range():
    with pytest.raises(HoldoutViolationError):
        guard_not_reused_or_contaminated("2025-06-01", "2025-06-10")


def test_permits_locked_ranges_only():
    guard = LockedRangeGuard([VALIDATION_RANGE, REPLICATION_RANGE])
    guard.check(*VALIDATION_RANGE)
    guard.check(*REPLICATION_RANGE)
    assert guard.checks_performed == 2
    with pytest.raises(HoldoutViolationError):
        guard.check("2024-06-01", "2024-06-30")


def test_permits_clean_range_that_does_not_overlap_anything():
    guard_not_reused_or_contaminated("2024-04-01", "2024-05-31")
    guard_not_reused_or_contaminated("2024-10-21", "2024-12-20")
