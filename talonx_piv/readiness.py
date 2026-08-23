"""Reusable, causal per-symbol/session market-data readiness validation."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import date, datetime, time, timedelta
from zoneinfo import ZoneInfo

ET = ZoneInfo("America/New_York")
OPEN = time(9, 30)
READY_AT = time(10, 0)


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
