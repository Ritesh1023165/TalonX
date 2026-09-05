"""Task 77I Stage 2 -- durable, execution-independent notification outbox.

Reuses `talonx_piv.lifecycle.stable_id` (a stable sha256-derived id helper)
for a DEDUPLICATION key, and the existing `talonx_piv.telegram.sender`
adapter interface (a bare `Callable[[str], bool]`) as its send mechanism --
production code never gains a second, independent Telegram integration.

Classification (see `alert_delivery_contract.md`):
  - decision.recommendation == BUY            -> ACTIONABLE_BUY
  - decision.recommendation == SELL_TO_CLOSE  -> ACTIONABLE_SELL
  - NO_TRADE with reason STRATEGY_UNVALIDATED_NO_ACTIONABLE_BUY_PROMOTION
                                               -> WATCH_OBSERVATION_ONLY
                                                  (a bullish, otherwise-
                                                  eligible setup the
                                                  strategy is not approved
                                                  to act on -- genuinely
                                                  useful operator visibility
                                                  without ever promoting it
                                                  to an actionable BUY)
  - everything else (HOLD, bearish/neutral NO_TRADE, data-insufficient
    NO_TRADE) -> not alert-worthy at all -- `enqueue` returns None and no
    record, pending or otherwise, is created. This is what keeps a
    strategy that is bearish (or already holding, with no exit condition)
    every single tick from generating a notification every single tick.

Deduplication: the outbox key is derived from
(ticker, trading_date_et, classification, recommendation, reason_codes) --
deliberately NOT decision_id/timestamp -- so repeated identical evaluations
across many ticks (e.g. "still bullish but unvalidated" on every bar)
collapse into exactly one queued notification per distinct
(ticker, date, classification) combination, not one per tick.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
import json
from pathlib import Path
from typing import Any, Callable

from .decision_contract import Decision, Recommendation
from .lifecycle import stable_id

# Task 78I Stage 5: UNCERTAIN is included here (not a Task 77I original
# decision) -- discovered during the offline recovery rehearsal that a
# record left UNCERTAIN (the adapter raised, true delivery status unknown)
# was never retried by a later dispatch_pending() call, silently stuck in
# limbo forever (neither retried nor terminal). Since UNCERTAIN genuinely
# means "we do not know whether this was delivered," retrying it on the
# next dispatch_pending() call (bounded by the same max_attempts as PENDING/
# RETRY) is the safer choice than leaving it permanently unresolved --
# the outbox's own dedup key already means re-attempting a genuinely-
# already-delivered message is at worst a harmless duplicate send, never a
# lost one.
PENDING_STATUSES = ("PENDING", "RETRY", "UNCERTAIN")
TERMINAL_STATUSES = ("SENT", "FAILED")
ALL_STATUSES = PENDING_STATUSES + TERMINAL_STATUSES

CLASSIFICATION_ACTIONABLE_BUY = "ACTIONABLE_BUY"
CLASSIFICATION_ACTIONABLE_SELL = "ACTIONABLE_SELL"
CLASSIFICATION_WATCH = "WATCH_OBSERVATION_ONLY"
# Task 79E -- kept structurally distinct from CLASSIFICATION_ACTIONABLE_*:
# an experimental decision can NEVER collide with, or be deduplicated
# against, a validated-strategy actionable one (see _dedup_key below, which
# also folds in experimental_id).
CLASSIFICATION_EXPERIMENTAL_BUY = "EXPERIMENTAL_BUY"
CLASSIFICATION_EXPERIMENTAL_SELL = "EXPERIMENTAL_SELL_TO_CLOSE"

_UNVALIDATED_REASON = "STRATEGY_UNVALIDATED_NO_ACTIONABLE_BUY_PROMOTION"

EXPERIMENTAL_BANNER = "EXPERIMENTAL / UNVALIDATED / PAPER OR SHADOW ONLY / NO REAL CAPITAL"


def classify(decision: Decision) -> str | None:
    if decision.recommendation == Recommendation.EXPERIMENTAL_BUY:
        return CLASSIFICATION_EXPERIMENTAL_BUY
    if decision.recommendation == Recommendation.BUY:
        return CLASSIFICATION_ACTIONABLE_BUY
    if decision.recommendation == Recommendation.SELL_TO_CLOSE:
        return CLASSIFICATION_EXPERIMENTAL_SELL if decision.experimental else CLASSIFICATION_ACTIONABLE_SELL
    if _UNVALIDATED_REASON in decision.reason_codes:
        return CLASSIFICATION_WATCH
    return None


def _format_message(decision: Decision, classification: str) -> str:
    tag = f"[{classification}]"
    execution = decision.execution_status.value
    bits = [tag]
    if decision.experimental:
        # Task 79E -- REQUIRED prominent banner on every experimental
        # notification, verbatim.
        bits.append(EXPERIMENTAL_BANNER)
    else:
        bits.append("PAPER / NO REAL CAPITAL")
    bits += [
        decision.ticker, decision.recommendation.value,
        f"strategy_approval={decision.strategy_approval_status.value}", f"execution_status={execution}",
        f"reasons={','.join(decision.reason_codes)}",
        f"entry={decision.entry_price}", f"stop={decision.stop_price}", f"target={decision.target_price}",
        f"horizon={decision.horizon}",
    ]
    if decision.experimental:
        bits.append(f"experiment_id={decision.experimental_id}")
        bits.append(f"strategy_id={decision.strategy_id}")
        bits.append(f"strategy_version={decision.strategy_version}")
        # Honest, non-fabricated broker-execution status at the moment this
        # message was composed -- never claims "filled"/"sent" here (that
        # is recorded separately, keyed by decision_id, by lifecycle.py's
        # own apply_broker_update once/if it actually happens).
        broker_state = {
            "ENTRY_ELIGIBLE_EXPERIMENTAL_PAPER": "broker_execution=ENABLED_PENDING_SUBMISSION",
            "ENTRY_BLOCKED_EXPERIMENTAL_PAPER_NOT_PERMITTED": "broker_execution=SKIPPED_NOT_PERMITTED",
        }.get(execution, "broker_execution=NOT_APPLICABLE")
        bits.append(broker_state)
    return " | ".join(bits)


def _dedup_key(decision: Decision, classification: str) -> str:
    return stable_id(
        "notif", decision.ticker, decision.trading_date_et, classification,
        decision.recommendation.value, "|".join(sorted(decision.reason_codes)),
        # Task 79E: folded in so two DIFFERENT experiments (or the same
        # experiment across two different sessions/dates already covered by
        # trading_date_et) are never merged into one deduplicated alert --
        # None for every ordinary, non-experimental decision, preserving the
        # exact pre-existing dedup key for normal-mode notifications.
        decision.experimental_id or "",
    )


@dataclass
class NotificationRecord:
    notification_id: str
    dedup_key: str
    decision_id: str
    classification: str
    message: str
    status: str = "PENDING"
    attempts: int = 0
    max_attempts: int = 3
    last_attempt_time: str | None = None
    sent_time: str | None = None
    created_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class NotificationOutbox:
    def __init__(self, state_path: Path | None, send: Callable[[str], bool] | None) -> None:
        self.state_path = state_path
        self.send = send
        self.records: dict[str, dict[str, Any]] = self._load()
        self._by_dedup_key: dict[str, str] = {r["dedup_key"]: nid for nid, r in self.records.items()}

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

    def enqueue(self, decision: Decision) -> dict[str, Any] | None:
        classification = classify(decision)
        if classification is None:
            return None  # not alert-worthy -- no record created at all
        dedup_key = _dedup_key(decision, classification)
        existing_id = self._by_dedup_key.get(dedup_key)
        if existing_id is not None:
            return self.records[existing_id]  # already queued/sent today for this exact situation
        record = NotificationRecord(
            notification_id=dedup_key, dedup_key=dedup_key, decision_id=decision.decision_id,
            classification=classification, message=_format_message(decision, classification),
        )
        self.records[record.notification_id] = record.to_dict()
        self._by_dedup_key[dedup_key] = record.notification_id
        self._save()
        return self.records[record.notification_id]

    def dispatch_pending(self) -> dict[str, int]:
        """Independent dispatch step -- never called from inside enqueue()
        or from the decision path itself, so a Telegram outage here can
        never suppress decision recording or shadow tracking (they already
        happened before this is ever invoked)."""
        counts = {"sent": 0, "retry": 0, "failed": 0, "uncertain": 0, "skipped_no_adapter": 0}
        for record in self.records.values():
            if record["status"] not in PENDING_STATUSES:
                continue
            if record["attempts"] >= record["max_attempts"]:
                record["status"] = "FAILED"
                counts["failed"] += 1
                continue
            record["attempts"] += 1
            record["last_attempt_time"] = datetime.now(timezone.utc).isoformat()
            if self.send is None:
                # No adapter configured (e.g. no Telegram token/chat id) --
                # honestly recorded as FAILED, never fabricated as SENT.
                record["status"] = "FAILED"
                counts["skipped_no_adapter"] += 1
                continue
            try:
                ok = self.send(record["message"])
            except Exception:  # noqa: BLE001 -- an adapter exception means delivery is UNKNOWN, not
                # necessarily failed and never silently treated as delivered.
                ok = None
            if ok is True:
                record["status"] = "SENT"
                record["sent_time"] = datetime.now(timezone.utc).isoformat()
                counts["sent"] += 1
            elif ok is False:
                record["status"] = "RETRY" if record["attempts"] < record["max_attempts"] else "FAILED"
                counts["retry" if record["status"] == "RETRY" else "failed"] += 1
            else:
                record["status"] = "UNCERTAIN"
                counts["uncertain"] += 1
        self._save()
        return counts
