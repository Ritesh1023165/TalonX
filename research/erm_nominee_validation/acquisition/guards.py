"""Acquisition-layer guards: every request is checked as (content_from, content_to, category) BEFORE it is built.

DevelopmentAcquisitionGuard (DEV only)
  * dated categories        -> the frozen EVENT_RESPONSE_MAP_V1 LockedRangeGuard.check_range (2024 and 2025-01-02+
                               refused); nothing is added or relaxed
  * broad endpoints and     -> refused unless the caller lists the category in `authorised_broad`. The frozen
    post-period identity      development design used them (current asset list, SEC reference files, submissions JSON,
    renames                   the S&P CSV, identity-only renames in the frozen Task75-skipping post-2023 ranges); the
                              recorded-response replay authorises them because it serves ARCHIVED development bytes
                              only. The live smoke test authorises none of them.
  * frame guard             -> the frozen LockedRangeGuard (refuses any 2024+ bar row)
The validation-window guard (ReleasedGuard) lives in research/erm_nominee_validation/release.py.
"""
from __future__ import annotations

from datetime import date

from research.common.locked_range_guard import EVENT_RESPONSE_MAP_V1, HoldoutViolation, LockedRangeGuard
from research.erm_nominee_validation.acquisition.period import BROAD_ENDPOINTS, FROZEN_POST2023_RENAME_RANGES

EPOCH = date(1993, 1, 1)                     # EDGAR full-text era start: content_from None == "history"
POST_PERIOD_IDENTITY = ("identity_renames",)


class AcquisitionRefused(HoldoutViolation):
    """A request outside the authorised acquisition scope (raised BEFORE the request exists)."""


def norm(a, b):
    a = EPOCH if a is None else (a if isinstance(a, date) else date.fromisoformat(str(a)))
    b = b if isinstance(b, date) else date.fromisoformat(str(b))
    return a, b


class DevelopmentAcquisitionGuard:
    window_id = "DEV"

    def __init__(self, *, authorised_broad: tuple = (), frozen: LockedRangeGuard | None = None):
        bad = set(authorised_broad) - set(BROAD_ENDPOINTS) - set(POST_PERIOD_IDENTITY)
        if bad:
            raise ValueError(f"not a broad / identity-only category: {sorted(bad)}")
        self.authorised_broad = tuple(authorised_broad)
        self.frozen = frozen or LockedRangeGuard(EVENT_RESPONSE_MAP_V1)
        self.log: list = []

    def check_acquisition(self, start, end, category: str) -> None:
        a, b = norm(start, end)
        self.log.append((category, a.isoformat(), b.isoformat()))
        if category in BROAD_ENDPOINTS:
            if category not in self.authorised_broad:
                raise AcquisitionRefused(f"DEV: broad endpoint {category!r} not authorised for this run")
            return
        if category in POST_PERIOD_IDENTITY:
            if category not in self.authorised_broad:
                raise AcquisitionRefused("DEV: post-period identity renames not authorised for this run")
            if not any(a >= date.fromisoformat(x) and b <= date.fromisoformat(y) for x, y in FROZEN_POST2023_RENAME_RANGES):
                raise AcquisitionRefused(f"DEV: identity renames {a}..{b} outside the frozen Task75-skipping ranges")
            return
        try:
            self.frozen.check_range(a, b, layer="DOWNLOAD")
        except HoldoutViolation as e:
            raise AcquisitionRefused(f"DEV acquisition refused ({category}): {e}") from None

    def frame_guard(self):
        return self.frozen

    def authorise(self, auth) -> None:
        raise AcquisitionRefused("DEV is never a validation run")
