"""Task 79E -- explicit, inactive-by-default experimental research
authorisation. Distinct from `decision_contract.StrategyApprovalStatus` --
granting this permission NEVER sets `strategy_approval_status=APPROVED`
anywhere; a strategy remains UNVALIDATED regardless. This module answers a
different question: "has an operator explicitly, narrowly, and
verifiably authorised ONE experiment to generate an alert/shadow record
(and optionally a bounded PAPER order) for an otherwise-ineligible
UNVALIDATED strategy, today, for these symbols only?"

Strict parsing throughout: every field is type-checked exactly (a JSON
string `"false"` is never coerced truthy; `bool` is checked BEFORE `int`
since `bool` is an `int` subclass in Python; every numeric limit must be
finite and strictly positive). ANY missing/malformed/unrecognised field,
any binding mismatch (wrong strategy/version/runtime/config/account/date/
session), or an expired window causes `load_experimental_authorization` to
return `None` (fail closed -- "no permission"), never a partially-trusted
object.

No default configuration file is ever created by this module, and no
example bundled with this task is active (`{"enabled": false, ...}` only)
-- see `results/task79e_experimental_authorization/inactive_configuration_example.json`.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import json
import math
from pathlib import Path
from typing import Any


def _is_strict_bool(value: Any) -> bool:
    return isinstance(value, bool)


def _is_finite_positive_number(value: Any) -> bool:
    if isinstance(value, bool):  # bool is an int subclass -- exclude explicitly
        return False
    if not isinstance(value, (int, float)):
        return False
    return math.isfinite(value) and value > 0


def _is_nonempty_str(value: Any) -> bool:
    return isinstance(value, str) and bool(value.strip())


def _parse_aware_datetime(value: Any) -> datetime | None:
    if not isinstance(value, str):
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return None  # timezone-naive is rejected outright -- never silently assumed UTC/local
    return parsed


@dataclass(frozen=True)
class ExperimentalPaperPermission:
    enabled: bool
    account_id_binding: str
    max_quantity_per_entry: float
    max_reference_notional_budget: float
    max_entry_count: int
    max_concurrent_exposure: int


@dataclass(frozen=True)
class ExperimentalAuthorization:
    experiment_id: str
    operator_acknowledged_unvalidated: bool
    strategy_id: str
    strategy_version: str
    runtime_sha: str
    config_hash: str
    allowed_symbols: frozenset[str]
    trading_date_et: str
    session_scope: str
    activated_at: datetime
    expires_at: datetime
    paper: ExperimentalPaperPermission | None

    def permits_entry(
        self, *, symbol: str, trading_date_et: str, strategy_id: str, strategy_version: str,
        runtime_sha: str, config_hash: str, now: datetime, session_scope: str | None = None,
    ) -> tuple[bool, str]:
        """Re-checked EVERY time a caller wants to know if a NEW experimental
        entry may be considered right now -- never cached as a single
        boolean checked once at startup. `now` must be timezone-aware.

        Task 79E-R1: `session_scope` is REQUIRED in practice (both real
        callers -- decision_engine.py and lifecycle.py -- always pass the
        fixed "REGULAR" scope identifying the live natural-strategy decision
        path, never the isolated PIV_LIFECYCLE_PROBE lifecycle or a
        rehearsal/test session). Kept optional here (default None) only so
        this stays a pure, narrowly-scoped addition -- None never matches a
        real (non-empty-string) `self.session_scope`, so an old caller that
        forgets to pass it fails closed rather than silently skipping the
        check."""
        if now.tzinfo is None:
            return False, "NOW_NOT_TIMEZONE_AWARE"
        if not self.operator_acknowledged_unvalidated:
            return False, "OPERATOR_DID_NOT_ACKNOWLEDGE_UNVALIDATED"
        if symbol.upper() not in self.allowed_symbols:
            return False, "SYMBOL_NOT_IN_ALLOWED_SET"
        if trading_date_et != self.trading_date_et:
            return False, "WRONG_TRADING_DATE"
        if session_scope != self.session_scope:
            return False, "WRONG_SESSION_SCOPE"
        if strategy_id != self.strategy_id:
            return False, "WRONG_STRATEGY_ID"
        if strategy_version != self.strategy_version:
            return False, "WRONG_STRATEGY_VERSION"
        if runtime_sha != self.runtime_sha:
            return False, "WRONG_RUNTIME_SHA"
        if config_hash != self.config_hash:
            return False, "WRONG_CONFIG_HASH"
        if now < self.activated_at:
            return False, "PERMISSION_NOT_YET_ACTIVE"
        if now >= self.expires_at:
            return False, "PERMISSION_EXPIRED"
        return True, "EXPERIMENTAL_ENTRY_PERMITTED"

    def permits_paper_execution(
        self, *, symbol: str, trading_date_et: str, strategy_id: str, strategy_version: str,
        runtime_sha: str, config_hash: str, now: datetime, account_id: str, session_scope: str | None = None,
    ) -> tuple[bool, str]:
        """A SEPARATE, additionally-required check -- entry permission alone
        never authorises a broker order. Re-checks entry permission first
        (do not duplicate expiry/identity logic), then the PAPER-specific
        binding."""
        entry_ok, entry_reason = self.permits_entry(
            symbol=symbol, trading_date_et=trading_date_et, strategy_id=strategy_id,
            strategy_version=strategy_version, runtime_sha=runtime_sha, config_hash=config_hash, now=now,
            session_scope=session_scope,
        )
        if not entry_ok:
            return False, entry_reason
        if self.paper is None or not self.paper.enabled:
            return False, "EXPERIMENTAL_PAPER_EXECUTION_NOT_ENABLED"
        if account_id != self.paper.account_id_binding:
            return False, "WRONG_PAPER_ACCOUNT"
        return True, "EXPERIMENTAL_PAPER_EXECUTION_PERMITTED"


class ExperimentalAuthorizationError(ValueError):
    pass


def load_experimental_authorization(path: Path) -> ExperimentalAuthorization | None:
    """Fail-closed on every ambiguous case -- returns None (no permission)
    rather than raise, exactly matching `execution_settings
    .load_paper_entry_settings`'s own established posture, so a caller can
    treat "file missing" and "file malformed" identically without a
    try/except at every call site."""
    if not path.exists():
        return None
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    if not isinstance(raw, dict):
        return None
    if not _is_strict_bool(raw.get("enabled")):
        return None
    if raw["enabled"] is not True:
        return None  # explicit False, or any non-bool already rejected above -- either way: disabled

    required_str_fields = (
        "experiment_id", "strategy_id", "strategy_version", "runtime_sha", "config_hash",
        "trading_date_et", "session_scope",
    )
    for field_name in required_str_fields:
        if not _is_nonempty_str(raw.get(field_name)):
            return None

    if not _is_strict_bool(raw.get("operator_acknowledged_unvalidated")) or raw["operator_acknowledged_unvalidated"] is not True:
        return None

    symbols = raw.get("allowed_symbols")
    if not isinstance(symbols, list) or not symbols or not all(_is_nonempty_str(s) for s in symbols):
        return None
    allowed_symbols = frozenset(s.upper() for s in symbols)

    activated_at = _parse_aware_datetime(raw.get("activated_at"))
    expires_at = _parse_aware_datetime(raw.get("expires_at"))
    if activated_at is None or expires_at is None or expires_at <= activated_at:
        return None

    paper_raw = raw.get("paper")
    paper: ExperimentalPaperPermission | None = None
    if paper_raw is not None:
        if not isinstance(paper_raw, dict):
            return None
        if not _is_strict_bool(paper_raw.get("enabled")):
            return None
        if paper_raw["enabled"] is True:
            if not _is_nonempty_str(paper_raw.get("account_id_binding")):
                return None
            for limit_field in ("max_quantity_per_entry", "max_reference_notional_budget"):
                if not _is_finite_positive_number(paper_raw.get(limit_field)):
                    return None
            for count_field in ("max_entry_count", "max_concurrent_exposure"):
                value = paper_raw.get(count_field)
                if not _is_finite_positive_number(value) or int(value) != value:
                    return None
            paper = ExperimentalPaperPermission(
                enabled=True, account_id_binding=paper_raw["account_id_binding"],
                max_quantity_per_entry=float(paper_raw["max_quantity_per_entry"]),
                max_reference_notional_budget=float(paper_raw["max_reference_notional_budget"]),
                max_entry_count=int(paper_raw["max_entry_count"]),
                max_concurrent_exposure=int(paper_raw["max_concurrent_exposure"]),
            )
        else:
            paper = ExperimentalPaperPermission(
                enabled=False, account_id_binding="", max_quantity_per_entry=0.0,
                max_reference_notional_budget=0.0, max_entry_count=0, max_concurrent_exposure=0,
            )

    return ExperimentalAuthorization(
        experiment_id=raw["experiment_id"], operator_acknowledged_unvalidated=True,
        strategy_id=raw["strategy_id"], strategy_version=raw["strategy_version"],
        runtime_sha=raw["runtime_sha"], config_hash=raw["config_hash"],
        allowed_symbols=allowed_symbols, trading_date_et=raw["trading_date_et"],
        session_scope=raw["session_scope"], activated_at=activated_at, expires_at=expires_at,
        paper=paper,
    )
