"""Task 83 §2 -- the comparison identity.

Every comparable unit of work, from either pipeline, is projected onto ONE
record shape with exactly these fields:

    pipeline          "ORIGINAL" | "PIV"
    session_id        the emitting pipeline's own session id (never shared)
    trading_date      America/New_York calendar date (YYYY-MM-DD)
    stage             warmup | quant | brain | core | dispatch | telegram
                      | readiness | freshness | decision | shadow
                      | lifecycle | reconciliation | eod
    symbol            uppercased ticker, or "" for stage-level aggregates
    event_time        ISO-8601 UTC -- when the pipeline recorded it
    source_bar_time   ISO-8601 -- the market bar the work was derived from
                      (None where the source does not carry it; see the
                      unresolved IEX receipt-vs-source-time question)
    decision_id       the PIV decision id / Original alert id, or None
    decision_outcome  the decision / outcome label (BUY, HOLD, REJECTED...)
    reason_codes      tuple of reason-code strings, order-normalised
    execution_class   NONE | SIMULATED_PAPER | PIV_SHADOW | PIV_PAPER
                      | EXPERIMENTAL -- keeps simulated / shadow / paper /
                      experimental outcomes from ever being merged
    payload_fingerprint  stable hash of the identity-bearing payload fields

Alignment (alignment.py) keys strictly on
(trading_date, stage, symbol) and NEVER crosses trading dates, sessions,
or symbols.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
import hashlib
import json
from typing import Any
from zoneinfo import ZoneInfo

ET = ZoneInfo("America/New_York")

PIPELINE_ORIGINAL = "ORIGINAL"
PIPELINE_PIV = "PIV"

# execution classes -- deliberately disjoint; never summed together
EXEC_NONE = "NONE"
EXEC_SIMULATED_PAPER = "SIMULATED_PAPER"   # Original's local paper engine
EXEC_PIV_SHADOW = "PIV_SHADOW"             # PIV shadow ledger (no broker)
EXEC_PIV_PAPER = "PIV_PAPER"               # PIV PAPER lifecycle (Alpaca paper)
EXEC_EXPERIMENTAL = "EXPERIMENTAL"         # experimental-authorised PIV activity
EXECUTION_CLASSES = (
    EXEC_NONE, EXEC_SIMULATED_PAPER, EXEC_PIV_SHADOW, EXEC_PIV_PAPER, EXEC_EXPERIMENTAL,
)

STAGES = (
    "warmup", "quant", "brain", "core", "dispatch", "telegram",
    "readiness", "freshness", "decision", "shadow", "lifecycle",
    "reconciliation", "eod",
)

# payload fields that are pure transport noise -- excluded from the
# fingerprint so a re-read / re-delivery of the same logical record hashes
# identically (this is what makes restart dedup exact).
_FINGERPRINT_EXCLUDE = frozenset({
    "timestamp", "event_time", "received_at", "detected_at_utc", "_id",
    "runtime_start_utc", "age_seconds", "last_update",
})


def trading_date_for(timestamp_iso: str) -> str:
    """America/New_York calendar date of a UTC ISO timestamp -- the single
    canonical bucket used everywhere so 2026-08-24 and 2026-08-25 activity
    can never be aligned against each other."""
    dt = datetime.fromisoformat(timestamp_iso)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(ET).date().isoformat()


def payload_fingerprint(payload: dict[str, Any]) -> str:
    """Deterministic sha256[:16] over the identity-bearing payload,
    excluding transport-noise fields. Sorted keys, compact separators --
    stable across processes and Python runs."""
    cleaned = {k: v for k, v in sorted(payload.items()) if k not in _FINGERPRINT_EXCLUDE}
    blob = json.dumps(cleaned, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()[:16]


@dataclass(frozen=True)
class ComparisonRecord:
    pipeline: str
    session_id: str | None
    trading_date: str
    stage: str
    symbol: str
    event_time: str | None
    source_bar_time: str | None
    decision_id: str | None
    decision_outcome: str | None
    reason_codes: tuple[str, ...]
    execution_class: str
    payload_fingerprint: str
    # provenance -- which source file / channel this projection came from
    source: str = ""

    def dedup_key(self) -> str:
        """Stable identity for restart-safe dedup: pipeline + scope +
        fingerprint. A late re-delivery of the same logical record maps to
        the same key and is recorded once."""
        return "|".join((
            self.pipeline, self.session_id or "-", self.trading_date, self.stage,
            self.symbol or "-", self.decision_id or "-", self.payload_fingerprint,
        ))

    def alignment_key(self) -> tuple[str, str, str]:
        return (self.trading_date, self.stage, self.symbol)

    def to_dict(self) -> dict[str, Any]:
        return {
            "pipeline": self.pipeline,
            "session_id": self.session_id,
            "trading_date": self.trading_date,
            "stage": self.stage,
            "symbol": self.symbol,
            "event_time": self.event_time,
            "source_bar_time": self.source_bar_time,
            "decision_id": self.decision_id,
            "decision_outcome": self.decision_outcome,
            "reason_codes": list(self.reason_codes),
            "execution_class": self.execution_class,
            "payload_fingerprint": self.payload_fingerprint,
            "source": self.source,
            "_id": self.dedup_key(),
        }

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "ComparisonRecord":
        return cls(
            pipeline=d["pipeline"],
            session_id=d.get("session_id"),
            trading_date=d["trading_date"],
            stage=d["stage"],
            symbol=d.get("symbol") or "",
            event_time=d.get("event_time"),
            source_bar_time=d.get("source_bar_time"),
            decision_id=d.get("decision_id"),
            decision_outcome=d.get("decision_outcome"),
            reason_codes=tuple(d.get("reason_codes") or ()),
            execution_class=d.get("execution_class", EXEC_NONE),
            payload_fingerprint=d["payload_fingerprint"],
            source=d.get("source", ""),
        )


def make_record(
    *,
    pipeline: str,
    stage: str,
    symbol: str | None,
    event_time: str | None,
    session_id: str | None,
    trading_date: str | None = None,
    source_bar_time: str | None = None,
    decision_id: str | None = None,
    decision_outcome: str | None = None,
    reason_codes: Any = (),
    execution_class: str = EXEC_NONE,
    source: str = "",
    fingerprint_payload: dict[str, Any] | None = None,
) -> ComparisonRecord:
    """Build a ComparisonRecord, deriving trading_date from event_time when
    not supplied and normalising reason-code order."""
    if trading_date is None:
        if not event_time:
            raise ValueError("make_record needs trading_date or event_time")
        trading_date = trading_date_for(event_time)
    codes = tuple(sorted(str(c) for c in (reason_codes or ())))
    # The fingerprint captures the WORK, not who did it -- ``pipeline`` and
    # ``session_id`` are deliberately excluded so an Original record and a
    # PIV record that represent the same decision hash identically (and
    # therefore compare as agreement, not divergence).
    fp_src = dict(fingerprint_payload or {})
    fp_src.setdefault("stage", stage)
    fp_src.setdefault("symbol", (symbol or "").upper())
    fp_src.setdefault("decision_id", decision_id)
    fp_src.setdefault("decision_outcome", decision_outcome)
    fp_src.setdefault("reason_codes", list(codes))
    fp_src.setdefault("execution_class", execution_class)
    if source_bar_time is not None:
        fp_src.setdefault("source_bar_time", source_bar_time)
    return ComparisonRecord(
        pipeline=pipeline,
        session_id=session_id,
        trading_date=trading_date,
        stage=stage,
        symbol=(symbol or "").upper(),
        event_time=event_time,
        source_bar_time=source_bar_time,
        decision_id=decision_id,
        decision_outcome=decision_outcome,
        reason_codes=codes,
        execution_class=execution_class if execution_class in EXECUTION_CLASSES else EXEC_NONE,
        payload_fingerprint=payload_fingerprint(fp_src),
        source=source,
    )
