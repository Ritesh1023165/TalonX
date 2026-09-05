"""Task 83 §2 / Task 83-R1 §3 -- the comparison identity.

Every comparable unit of work, from either pipeline, is projected onto ONE
record shape:

    pipeline          "ORIGINAL" | "PIV"
    session_id        the emitting pipeline's OWN session id, verbatim
                      (PIV stamps one; Original does not -> None). Never
                      shared or invented.
    run_scope         the scope alignment partitions on. For PIV this IS
                      session_id. For Original it is a COLLECTOR-DERIVED
                      run scope (from verified runtime metadata/bindings,
                      prefixed "orig:") or the sentinel "UNSCOPED" when no
                      usable run identity is available -- in which case
                      event-level agreement is NOT asserted.
    record_kind       "EVENT" | "AGGREGATE". Aggregates (rolled-up
                      counters) are compared as aggregate values under an
                      explicit aggregate key and are never collapsed with
                      individual events.
    trading_date      America/New_York calendar date (YYYY-MM-DD)
    stage             warmup|quant|brain|core|dispatch|telegram|readiness
                      |freshness|decision|shadow|lifecycle|reconciliation|eod
    symbol            uppercased ticker, or "" for stage-level aggregates
    event_time        ISO-8601 UTC -- when the pipeline recorded it
    source_bar_time   ISO-8601 -- the market bar the work derived from
                      (None where the source does not carry it -- see the
                      unresolved IEX receipt-vs-source-time question)
    decision_id       the PIV decision id / Original alert id, or None
    event_identity    the STABLE per-event identity alignment keys on:
                      decision_id when present, else a documented causal
                      identity "causal:<fingerprint>" (stage + symbol +
                      source_bar_time + outcome + payload all fold into
                      the fingerprint), or "agg:<name>" for aggregates.
    decision_outcome  the decision / outcome label
    reason_codes      tuple of reason-code strings, order-normalised
    execution_class   NONE|SIMULATED_PAPER|PIV_SHADOW|PIV_PAPER|EXPERIMENTAL
    payload_fingerprint  stable hash of the identity-bearing payload

Alignment keys on (trading_date, stage, symbol, event_identity) WITHIN one
run_scope pairing; it never crosses trading dates, PIV sessions, symbols,
or (for events) distinct event identities.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import hashlib
import json
from typing import Any
from zoneinfo import ZoneInfo

ET = ZoneInfo("America/New_York")

PIPELINE_ORIGINAL = "ORIGINAL"
PIPELINE_PIV = "PIV"

# run-scope sentinels
UNSCOPED = "UNSCOPED"
ORIGINAL_SCOPE_PREFIX = "orig:"

# record kinds
KIND_EVENT = "EVENT"
KIND_AGGREGATE = "AGGREGATE"

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
    "runtime_start_utc", "age_seconds", "last_update", "generated_at",
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
    event_identity: str = ""
    run_scope: str | None = None
    record_kind: str = KIND_EVENT
    aggregate_name: str | None = None
    aggregate_value: float | None = None
    # provenance -- which source file / channel this projection came from
    source: str = ""

    def dedup_key(self) -> str:
        """Stable identity for restart-safe dedup. A late re-delivery of
        the SAME logical record maps to the same key and is recorded once;
        a genuinely different event (different decision_id / causal
        identity / run scope) gets its own key and stays distinct."""
        return "|".join((
            self.pipeline, self.record_kind, self.run_scope or "-", self.trading_date,
            self.stage, self.symbol or "-", self.event_identity or "-", self.payload_fingerprint,
        ))

    def alignment_key(self) -> tuple[str, str, str, str]:
        return (self.trading_date, self.stage, self.symbol, self.event_identity)

    def to_dict(self) -> dict[str, Any]:
        return {
            "pipeline": self.pipeline,
            "session_id": self.session_id,
            "run_scope": self.run_scope,
            "record_kind": self.record_kind,
            "trading_date": self.trading_date,
            "stage": self.stage,
            "symbol": self.symbol,
            "event_time": self.event_time,
            "source_bar_time": self.source_bar_time,
            "decision_id": self.decision_id,
            "event_identity": self.event_identity,
            "decision_outcome": self.decision_outcome,
            "reason_codes": list(self.reason_codes),
            "execution_class": self.execution_class,
            "aggregate_name": self.aggregate_name,
            "aggregate_value": self.aggregate_value,
            "payload_fingerprint": self.payload_fingerprint,
            "source": self.source,
            "_id": self.dedup_key(),
        }

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "ComparisonRecord":
        return cls(
            pipeline=d["pipeline"],
            session_id=d.get("session_id"),
            run_scope=d.get("run_scope"),
            record_kind=d.get("record_kind", KIND_EVENT),
            trading_date=d["trading_date"],
            stage=d["stage"],
            symbol=d.get("symbol") or "",
            event_time=d.get("event_time"),
            source_bar_time=d.get("source_bar_time"),
            decision_id=d.get("decision_id"),
            event_identity=d.get("event_identity") or "",
            decision_outcome=d.get("decision_outcome"),
            reason_codes=tuple(d.get("reason_codes") or ()),
            execution_class=d.get("execution_class", EXEC_NONE),
            aggregate_name=d.get("aggregate_name"),
            aggregate_value=d.get("aggregate_value"),
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
    run_scope: str | None = None,
    source_bar_time: str | None = None,
    decision_id: str | None = None,
    decision_outcome: str | None = None,
    reason_codes: Any = (),
    execution_class: str = EXEC_NONE,
    source: str = "",
    record_kind: str = KIND_EVENT,
    aggregate_name: str | None = None,
    aggregate_value: float | None = None,
    event_identity: str | None = None,
    fingerprint_payload: dict[str, Any] | None = None,
) -> ComparisonRecord:
    """Build a ComparisonRecord, deriving trading_date from event_time when
    not supplied, normalising reason-code order, and computing a stable
    ``event_identity`` (decision_id > explicit > causal fingerprint >
    aggregate name)."""
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
    fp = payload_fingerprint(fp_src)

    if record_kind == KIND_AGGREGATE:
        eid = f"agg:{aggregate_name}"
    elif decision_id:
        eid = str(decision_id)
    elif event_identity:
        eid = event_identity
    else:
        # documented causal identity: the payload fingerprint already folds
        # in stage + symbol + source_bar_time + outcome + reason codes.
        eid = f"causal:{fp}"

    # PIV run_scope IS its session id; a caller may override (Original).
    resolved_scope = run_scope if run_scope is not None else session_id

    return ComparisonRecord(
        pipeline=pipeline,
        session_id=session_id,
        run_scope=resolved_scope,
        record_kind=record_kind,
        trading_date=trading_date,
        stage=stage,
        symbol=(symbol or "").upper(),
        event_time=event_time,
        source_bar_time=source_bar_time,
        decision_id=decision_id,
        event_identity=eid,
        decision_outcome=decision_outcome,
        reason_codes=codes,
        execution_class=execution_class if execution_class in EXECUTION_CLASSES else EXEC_NONE,
        aggregate_name=aggregate_name,
        aggregate_value=aggregate_value,
        payload_fingerprint=fp,
        source=source,
    )
