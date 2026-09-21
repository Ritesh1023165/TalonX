"""Reusable, causal per-symbol/session market-data readiness validation."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import date, datetime, time, timedelta
import json
import os
from pathlib import Path
from zoneinfo import ZoneInfo

ET = ZoneInfo("America/New_York")
OPEN = time(9, 30)
READY_AT = time(10, 0)
STATE_SCHEMA_VERSION = 1
_VALID_STATUSES = ("READY", "DATA_NOT_READY", "PENDING")


class ReadinessStateError(Exception):
    """Raised by load_readiness_state on malformed JSON -- the caller must
    treat this as INVALID (fail closed), never as if no state existed."""


def save_readiness_state(path: Path, state: dict) -> None:
    """Atomic write: temp file + os.replace, so a crash mid-write never
    leaves a half-written, corrupt state file behind."""
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(json.dumps(state, indent=2, sort_keys=True), encoding="utf-8")
    os.replace(tmp, path)


def load_readiness_state(path: Path) -> dict | None:
    """None if the file doesn't exist (MISSING). Raises ReadinessStateError
    on malformed JSON (INVALID) -- callers must not conflate the two."""
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ReadinessStateError(str(exc)) from exc


@dataclass(frozen=True)
class RestoreOutcome:
    """Per-restore-attempt result, for SESSION_READINESS_STATE_* telemetry.
    Exactly one of missing/invalid/stale/ok is True for the whole-state
    outcome; invalid_symbols additionally lists any per-symbol entries
    that were individually rejected (and therefore restored as if no
    state existed for that symbol) even when the overall state was
    otherwise valid."""
    restored_symbols: tuple[str, ...] = ()
    missing: bool = False
    invalid: bool = False
    stale: bool = False
    invalid_symbols: tuple[str, ...] = ()

    @property
    def ok(self) -> bool:
        return not (self.missing or self.invalid or self.stale)


@dataclass(frozen=True)
class ReadinessTelemetry:
    symbol: str
    session: str
    status: str
    evaluated_at: str
    expected_minutes: int
    observed_minutes: int
    missing_minutes: tuple[str, ...]
    missing_5m_buckets: tuple[str, ...]
    reason: str
    synthetic_data_used: bool = False

    def to_dict(self) -> dict[str, object]:
        row = asdict(self)
        row["missing_minutes"] = list(self.missing_minutes)
        row["missing_5m_buckets"] = list(self.missing_5m_buckets)
        return row


class SessionReadinessValidator:
    """Fail closed for incomplete opening data without coupling to alpha logic."""

    def __init__(self) -> None:
        self._observed: dict[tuple[str, date], set[datetime]] = {}
        self._final: dict[tuple[str, date], ReadinessTelemetry] = {}

    @staticmethod
    def expected_timestamps(session: date) -> tuple[datetime, ...]:
        start = datetime.combine(session, OPEN, ET)
        return tuple(start + timedelta(minutes=i) for i in range(30))

    @staticmethod
    def _normalize(timestamp: datetime) -> datetime:
        if timestamp.tzinfo is None:
            raise ValueError("market-data timestamps must be timezone-aware")
        return timestamp.astimezone(ET).replace(second=0, microsecond=0)

    def observe(self, symbol: str, session: date, timestamp: datetime) -> None:
        key = (symbol.upper(), session)
        if key in self._final:
            return
        ts = self._normalize(timestamp)
        if ts.date() == session and OPEN <= ts.time() < READY_AT:
            self._observed.setdefault(key, set()).add(ts)

    def evaluate(self, symbol: str, session: date, evaluated_at: datetime) -> ReadinessTelemetry:
        key = (symbol.upper(), session)
        if key in self._final:
            return self._final[key]
        now = self._normalize(evaluated_at)
        expected = self.expected_timestamps(session)
        observed = self._observed.get(key, set()) & set(expected)
        missing = tuple(ts.strftime("%Y-%m-%d %H:%M %Z") for ts in expected if ts not in observed)
        if now < datetime.combine(session, READY_AT, ET):
            return ReadinessTelemetry(
                key[0], session.isoformat(), "PENDING", now.isoformat(), 30,
                len(observed), missing, (), "AWAITING_COMPLETED_09_59_BAR",
            )
        missing_buckets = []
        for offset in range(0, 30, 5):
            bucket = expected[offset : offset + 5]
            if any(ts not in observed for ts in bucket):
                missing_buckets.append(f"{bucket[0].strftime('%H:%M')}-{bucket[-1].strftime('%H:%M')}")
        ready = not missing
        result = ReadinessTelemetry(
            key[0], session.isoformat(), "READY" if ready else "DATA_NOT_READY",
            now.isoformat(), 30, len(observed), missing, tuple(missing_buckets),
            "COMPLETE_OPENING_DATA" if ready else "MISSING_REQUIRED_OPENING_MINUTES",
        )
        self._final[key] = result
        return result

    def strategy_eligible(self, symbol: str, session: date) -> bool:
        record = self._final.get((symbol.upper(), session))
        return bool(record and record.status == "READY")

    def to_state(self, session: date) -> dict:
        """Serialize this session's readiness state for persistence.
        Finalized (READY/DATA_NOT_READY) decisions and raw pre-finalization
        observations are both included, scoped strictly to `session` --
        never another date. See module docstring / save_readiness_state."""
        finalized = {
            symbol: telemetry.to_dict()
            for (symbol, sess), telemetry in self._final.items() if sess == session
        }
        observed = {
            symbol: sorted(ts.isoformat() for ts in timestamps)
            for (symbol, sess), timestamps in self._observed.items()
            if sess == session and (symbol, sess) not in self._final
        }
        return {
            "schema_version": STATE_SCHEMA_VERSION, "session_date": session.isoformat(),
            "finalized": finalized, "observed": observed,
        }

    def _telemetry_from_row(self, row: object, session: date) -> ReadinessTelemetry:
        if not isinstance(row, dict):
            raise ValueError("readiness state row is not an object")
        status = row["status"]
        if status not in _VALID_STATUSES:
            raise ValueError(f"unknown status {status!r}")
        if row.get("synthetic_data_used"):
            # The validator contract never produces synthetic data -- a
            # persisted row claiming otherwise is itself corrupt, not a
            # legitimate state to restore.
            raise ValueError("synthetic_data_used=true is never valid")
        if row.get("session") != session.isoformat():
            raise ValueError("session field does not match the session being restored")
        return ReadinessTelemetry(
            symbol=str(row["symbol"]).upper(), session=row["session"], status=status,
            evaluated_at=str(row["evaluated_at"]), expected_minutes=int(row["expected_minutes"]),
            observed_minutes=int(row["observed_minutes"]), missing_minutes=tuple(row["missing_minutes"]),
            missing_5m_buckets=tuple(row["missing_5m_buckets"]), reason=str(row["reason"]),
            synthetic_data_used=False,
        )

    def restore_state(self, state: dict | None, session: date) -> RestoreOutcome:
        """Fail-closed restoration for `session` only. A whole-state problem
        (missing file, bad schema/session, non-dict finalized/observed
        blocks) restores nothing. A per-symbol problem within an otherwise
        valid state rejects only that symbol -- it is never treated as
        READY, and normal live observation continues for it going forward.
        Idempotent: safe to call more than once with the same state."""
        if state is None:
            return RestoreOutcome(missing=True)
        if not isinstance(state, dict) or state.get("schema_version") != STATE_SCHEMA_VERSION:
            return RestoreOutcome(invalid=True)
        try:
            persisted_session = date.fromisoformat(str(state.get("session_date")))
        except (TypeError, ValueError):
            return RestoreOutcome(invalid=True)
        if persisted_session != session:
            return RestoreOutcome(stale=True)

        finalized = state.get("finalized")
        observed = state.get("observed")
        if not isinstance(finalized, dict) or not isinstance(observed, dict):
            return RestoreOutcome(invalid=True)

        restored: list[str] = []
        invalid_symbols: list[str] = []
        for symbol, row in finalized.items():
            try:
                telemetry = self._telemetry_from_row(row, session)
            except (KeyError, TypeError, ValueError):
                invalid_symbols.append(str(symbol).upper())
                continue
            self._final[(symbol.upper(), session)] = telemetry
            restored.append(symbol.upper())

        for symbol, timestamps in observed.items():
            key = (str(symbol).upper(), session)
            if key in self._final:
                continue
            try:
                parsed = {self._normalize(datetime.fromisoformat(str(ts))) for ts in timestamps}
            except (TypeError, ValueError):
                invalid_symbols.append(str(symbol).upper())
                continue
            if parsed:
                self._observed.setdefault(key, set()).update(parsed)
                restored.append(key[0])

        return RestoreOutcome(restored_symbols=tuple(sorted(set(restored))), invalid_symbols=tuple(invalid_symbols))
