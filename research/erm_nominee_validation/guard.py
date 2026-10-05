"""ERM nominee validation plumbing -- fail-closed guard (acquisition AND load layers).

Delegates to the immutable EVENT_RESPONSE_MAP_V1 LockedRangeGuard (EXCLUDED_2024; FUTURE_CONFIRMATION_2025_ONWARD),
which has no transition method. A release for validation additionally requires a hypothesis/window-scoped
authorisation record AND a separately reviewed guard transition; NEITHER exists in this implementation, so every
protected acquisition or load raises. Nothing here writes guard state.
"""
from __future__ import annotations

import json
from datetime import date
from pathlib import Path

from research.common.locked_range_guard import EVENT_RESPONSE_MAP_V1, HoldoutViolation, LockedRangeGuard
from research.erm_nominee_validation.config import HYPOTHESIS, ValidationConfig

RELEASE_RECORD = Path("results/erm_nominee_validation/GUARD_RELEASE_AUTHORISATION.json")   # never created here


class GuardReleaseNotAuthorised(HoldoutViolation):
    """Protected validation data requested without an explicit, scoped release."""


class ValidationGuard:
    def __init__(self, config: ValidationConfig, root: Path | None = None):
        self.config = config
        self.root = root or Path(__file__).resolve().parents[2]
        self.frozen = LockedRangeGuard(EVENT_RESPONSE_MAP_V1)            # read-only use: check_range / check_frame

    def release_authorised(self) -> bool:
        """True only for an explicit record naming this hypothesis, window and config hash. Even then the frozen
        LockedRangeGuard (no transition method) still refuses; a reviewed guard transition is a separate task."""
        p = self.root / RELEASE_RECORD
        if not p.exists():
            return False
        r = json.loads(p.read_text())
        return (r.get("hypothesis") == HYPOTHESIS and r.get("window_id") == self.config.window_id
                and r.get("config_hash") == self.config.config_hash() and r.get("owner_go") is True)

    def check_acquisition(self, start: date, end: date, what: str) -> None:
        """Before ANY request (price or metadata) covering [start, end] (start None = history)."""
        try:
            self.frozen.check_range(start or date(1993, 1, 1), end, layer="DOWNLOAD")
        except HoldoutViolation as e:
            raise GuardReleaseNotAuthorised(f"acquisition refused ({what}): {e}; release_authorised="
                                            f"{self.release_authorised()} -- guard release is disabled") from None

    def check_load(self, df, what: str, ts_col: str = "timestamp") -> None:
        """After loading ANY frame: the whole span and every interior row."""
        try:
            self.frozen.check_frame(df, layer="LOAD", ts_col=ts_col)
        except HoldoutViolation as e:
            raise GuardReleaseNotAuthorised(f"load refused ({what}): {e} -- guard release is disabled") from None


def check_authorisation_scope(auth: dict | None, config: ValidationConfig) -> None:
    """Shared scope check (used by every guard implementation): an explicit owner GO record naming THIS hypothesis,
    window and configuration hash. Missing / wrong-window / wrong-hypothesis / wrong-config / no GO -> refused."""
    if not auth:
        raise GuardReleaseNotAuthorised("no release authorisation record")
    if auth.get("hypothesis") != HYPOTHESIS:
        raise GuardReleaseNotAuthorised(f"authorisation is for hypothesis {auth.get('hypothesis')!r}")
    if auth.get("window_id") != config.window_id:
        raise GuardReleaseNotAuthorised(f"authorisation is for window {auth.get('window_id')!r}, not {config.window_id!r}")
    if auth.get("config_hash") != config.config_hash():
        raise GuardReleaseNotAuthorised("authorisation config hash does not match this configuration")
    if auth.get("owner_go") is not True:
        raise GuardReleaseNotAuthorised("authorisation lacks an explicit owner GO")


def _authorise(self, auth: dict | None) -> None:
    """PRODUCTION: scope must match AND a reviewed guard transition must exist. None exists in this implementation,
    so a correctly scoped record is still refused (fail closed)."""
    check_authorisation_scope(auth, self.config)
    raise GuardReleaseNotAuthorised("scoped authorisation present, but no reviewed guard transition exists -- "
                                    "guard release is disabled in this implementation")


def _frame_guard(self):
    """Guard passed to the frozen data.load LOAD layer: the immutable EVENT_RESPONSE_MAP_V1 LockedRangeGuard."""
    return self.frozen


ValidationGuard.authorise = _authorise
ValidationGuard.frame_guard = _frame_guard
