"""Task74 -- holdout guard blocks ALL of 2024 (development-only task)."""
from __future__ import annotations

import pytest

from research.task74_alpha_discovery_v2.holdout_guard import (
    DevelopmentOnlyGuard, HoldoutProtectionError, guard_date_range, guard_path_or_label,
)


def test_blocks_any_2024_range():
    with pytest.raises(HoldoutProtectionError):
        guard_date_range("2024-06-01", "2024-09-02")
    with pytest.raises(HoldoutProtectionError):
        guard_date_range("2024-10-21", "2024-12-20")


def test_permits_2025_2026_development_range():
    guard_date_range("2025-02-03", "2025-03-14")
    guard_date_range("2026-05-15", "2026-08-14")


def test_blocks_2024_labeled_path():
    with pytest.raises(HoldoutProtectionError):
        guard_path_or_label("task74_development_2024q2")


def test_guard_object_tracks_checks():
    guard = DevelopmentOnlyGuard()
    guard.check("2025-02-03", "2025-03-14")
    guard.check("2026-05-15", "2026-08-14")
    assert guard.checks_performed == 2
    with pytest.raises(HoldoutProtectionError):
        guard.check("2024-01-01", "2024-01-31")
