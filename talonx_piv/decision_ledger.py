"""Task 77I Stage 1/2 -- durable, per-decision record.

Deliberately separate from `events.py`'s append-only `piv_events.jsonl`
(37 broad operational event types, immutable once written) -- a decision
record needs MUTABLE per-decision status fields (notification_status,
shadow_status, execution_status all change over time as later components
process the same decision_id) and to be efficiently re-readable by
decision_id, neither of which an append-only log is a good fit for. Instead
this reuses the exact `_load`/`_save` full-file-JSON-rewrite pattern already
established by `lifecycle.py::LifecycleState` and `eod_lifecycle.py`'s own
state file -- the same architecture, not a new one.

Idempotent by construction: `record()` is a no-op (returns the existing
record unchanged) if `decision.decision_id` has already been recorded --
this is what makes "duplicate event/restart does not create duplicate
internal work" true for every later consumer keyed off this ledger.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
import json
from pathlib import Path
from typing import Any

from .decision_contract import Decision

NOTIFICATION_STATUSES = ("NOT_APPLICABLE", "PENDING", "RETRY", "SENT", "FAILED", "UNCERTAIN")
SHADOW_STATUSES = ("NOT_APPLICABLE", "PENDING_FILL", "OPEN", "CLOSED", "UNRESOLVED")
EXECUTION_STATUSES = ("NOT_APPLICABLE", "PENDING", "SUBMITTED", "REJECTED", "FILLED", "SKIPPED")
EVIDENCE_CATEGORIES = ("natural", "observational", "test_probe")


@dataclass
class DecisionRecord:
    decision_id: str
    event_id: str
    session_id: str
    trading_date_et: str
    runtime_sha: str | None
    config_hash: str | None
    symbol: str
    timestamp: str
    market_view: str
    recommendation: str
    reason_codes: list[str]
    strategy_id: str | None
    strategy_version: str | None
    strategy_approval_status: str
    data_readiness: str
    data_provider: str | None
    entry_price: float | None
    stop_price: float | None
    target_price: float | None
    horizon: str | None
    paper_entry_enabled: bool
    evidence_category: str
    # decide()'s OWN ExecutionStatus (ENTRY_ELIGIBLE/ENTRY_BLOCKED_PAPER_DISABLED/
    # EXIT_ELIGIBLE/NO_ACTION), fixed at decision time -- distinct from
    # `execution_status` below, which is THIS ledger's own mutable field
    # tracking the later broker outcome (SUBMITTED/FILLED/REJECTED) over time.
    decision_execution_status: str = "NOT_APPLICABLE"
    notification_status: str = "NOT_APPLICABLE"
    shadow_status: str = "NOT_APPLICABLE"
    execution_status: str = "NOT_APPLICABLE"
    recorded_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class DecisionLedger:
    def __init__(self, state_path: Path | None) -> None:
        # None => in-memory only (never touches disk) -- lets pre-existing
        # DecisionEngine test construction sites keep working unchanged
        # (Task 76S precedent: PaperLifecycle's own fail-closed default for
        # an unsupplied PaperEntrySettings). Every REAL production caller
        # (cli.py::runtime()) always supplies a real path.
        self.state_path = state_path
        self.records: dict[str, dict[str, Any]] = self._load()

    def _load(self) -> dict[str, dict[str, Any]]:
        if self.state_path is None or not self.state_path.exists():
            return {}
        try:
            return json.loads(self.state_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return {}

    def _save(self) -> None:
        if self.state_path is None:
            return
        self.state_path.parent.mkdir(parents=True, exist_ok=True)
        self.state_path.write_text(json.dumps(self.records, sort_keys=True, indent=2), encoding="utf-8")

    def get(self, decision_id: str) -> dict[str, Any] | None:
        return self.records.get(decision_id)

    def record(
        self, decision: Decision, *, event_id: str, evidence_category: str,
        runtime_sha: str | None = None, config_hash: str | None = None, data_provider: str | None = None,
    ) -> dict[str, Any]:
        """If decision.decision_id has already been recorded, returns the
        EXISTING record unchanged (idempotent -- a restart or a duplicate
        upstream call must never create a second record for the same
        decision)."""
        existing = self.records.get(decision.decision_id)
        if existing is not None:
            return existing
        if evidence_category not in EVIDENCE_CATEGORIES:
            raise ValueError(f"unsupported evidence_category: {evidence_category}")
        record = DecisionRecord(
            decision_id=decision.decision_id, event_id=event_id, session_id=decision.session_id,
            trading_date_et=decision.trading_date_et, runtime_sha=runtime_sha, config_hash=config_hash,
            symbol=decision.ticker, timestamp=decision.timestamp, market_view=decision.market_view.value,
            recommendation=decision.recommendation.value, reason_codes=list(decision.reason_codes),
            strategy_id=decision.strategy_id, strategy_version=decision.strategy_version,
            strategy_approval_status=decision.strategy_approval_status.value,
            data_readiness=decision.data_readiness.value, data_provider=data_provider,
            entry_price=decision.entry_price, stop_price=decision.stop_price, target_price=decision.target_price,
            horizon=decision.horizon, paper_entry_enabled=decision.paper_entry_enabled,
            evidence_category=evidence_category, decision_execution_status=decision.execution_status.value,
        )
        self.records[decision.decision_id] = record.to_dict()
        self._save()
        return self.records[decision.decision_id]

    def update_status(
        self, decision_id: str, *, notification_status: str | None = None,
        shadow_status: str | None = None, execution_status: str | None = None,
    ) -> None:
        record = self.records.get(decision_id)
        if record is None:
            return  # nothing to update -- record() must be called first
        if notification_status is not None:
            assert notification_status in NOTIFICATION_STATUSES
            record["notification_status"] = notification_status
        if shadow_status is not None:
            assert shadow_status in SHADOW_STATUSES
            record["shadow_status"] = shadow_status
        if execution_status is not None:
            assert execution_status in EXECUTION_STATUSES
            record["execution_status"] = execution_status
        self._save()
