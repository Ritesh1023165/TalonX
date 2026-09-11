"""Task 87B FC_01 -- durable, transport-independent outbox for talonx_core's
decision-bearing outbound alerts (intraday ``talonx:alerts:dispatch`` and
long-term ``talonx:alerts:longterm``).

Why this exists (Task 86 / 87A forensic finding):
    2026-08-31 08:35 UTC -- Core generated an MCD long-term ``hold_quality``
    alert, persisted it (``ticker_state_long_term.last_alert_*``), called
    ``mark_alerted`` on the correlator, then attempted a single
    ``client.publish(...)`` which timed out during a transient Redis
    incident. There was no retry and ``mark_alerted`` had already run, so
    the alert was never re-emitted -- Dispatch received nothing and there
    was no record that fan-out was still owed.

Design (deliberately the smallest thing that works, mirroring the already
battle-tested ``talonx_piv.notification_outbox`` pattern -- persist-then-
publish, bounded backoff, restart-safe, idempotent, never fabricate a
delivered state):

  * ``enqueue`` writes a PENDING record to a JSON state file BEFORE any
    publish is attempted. Persistence of the alert therefore never implies
    fan-out completed -- the outbox record's own status is the single
    source of truth for "did Dispatch get this".
  * ``mark_published`` moves PENDING/RETRY/UNCERTAIN -> SENT, and is called
    ONLY after the publish callable actually returned success.
  * ``flush`` re-attempts every non-terminal record whose ``next_attempt_at``
    has passed, with jittered exponential backoff, up to ``max_attempts``
    then -> FAILED (still visible, never silently dropped).
  * The state file is reloaded on construction, so a process restart with
    pending work re-publishes it.
  * Every record carries a stable ``outbox_id`` derived from the alert's
    semantic identity (ticker, trading date, kind, action, correlated_at) --
    a retry / restart / replay re-publishes the SAME payload under the SAME
    id, and talonx_dispatch de-duplicates on it, so at-least-once transport
    never becomes an at-least-once user-facing alert.

This module performs NO strategy logic and changes NO alert policy: it only
governs the reliability of moving an already-decided alert onto Redis.
"""

from __future__ import annotations

import hashlib
import json
import logging
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Awaitable, Callable

from talonx_ingest.common.backoff import jittered_backoff_seconds

logger = logging.getLogger("talonx_core.alert_outbox")

KIND_INTRADAY = "intraday"
KIND_LONG_TERM = "long_term"

PENDING_STATUSES = ("PENDING", "RETRY", "UNCERTAIN")
TERMINAL_STATUSES = ("SENT", "FAILED")

# async publish(channel: str, payload: str) -> bool  (True == Redis accepted it)
PublishFn = Callable[[str, str], Awaitable[bool]]


def make_outbox_id(*, ticker: str, trading_date: str, kind: str, action: str, correlated_at: str) -> str:
    """Stable, deterministic id for one decision-bearing alert. Deliberately
    NOT a random uuid and NOT the wall-clock publish time -- the same alert
    re-enqueued after a restart / replay must hash to the same id so
    Dispatch collapses the duplicate. ``correlated_at`` (when Core decided
    the pair cleared the matrix) is the discriminator between two genuinely
    distinct alerts for the same ticker/day/action."""
    raw = "|".join(("alertoutbox", ticker, trading_date, kind, action, correlated_at))
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:32]


@dataclass
class AlertOutboxRecord:
    outbox_id: str
    channel: str
    payload: str
    kind: str
    ticker: str
    action: str
    status: str = "PENDING"
    attempts: int = 0
    max_attempts: int = 6
    created_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    last_attempt_at: str | None = None
    next_attempt_at: str | None = None
    sent_at: str | None = None
    last_error: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class AlertOutbox:
    def __init__(
        self,
        state_path: Path | str | None,
        publish: PublishFn | None,
        *,
        backoff_base_seconds: float = 1.0,
        backoff_max_seconds: float = 60.0,
    ) -> None:
        self.state_path = Path(state_path) if state_path is not None else None
        self._publish = publish
        self._backoff_base = backoff_base_seconds
        self._backoff_max = backoff_max_seconds
        self.records: dict[str, dict[str, Any]] = self._load()
        # In-process, transport-independent counters (FC_02 sibling posture):
        # readable even if Redis is unreachable.
        self._enqueued = 0
        self._delivered = 0
        self._retried = 0
        self._failed_permanently = 0
        self._duplicates_suppressed = 0

    # -- persistence ------------------------------------------------------
    def _load(self) -> dict[str, dict[str, Any]]:
        if self.state_path is None or not self.state_path.exists():
            return {}
        try:
            data = json.loads(self.state_path.read_text(encoding="utf-8"))
            return data if isinstance(data, dict) else {}
        except (OSError, json.JSONDecodeError):
            logger.warning("Alert outbox state file unreadable -- starting empty: %s", self.state_path)
            return {}

    def _save(self) -> None:
        if self.state_path is None:
            return
        try:
            self.state_path.parent.mkdir(parents=True, exist_ok=True)
            tmp = self.state_path.with_suffix(self.state_path.suffix + ".tmp")
            tmp.write_text(json.dumps(self.records, sort_keys=True, indent=2), encoding="utf-8")
            tmp.replace(self.state_path)
        except OSError as exc:  # noqa: BLE001 -- a state-write failure must never crash the engine
            logger.warning("Failed to persist alert outbox state: %s", exc)

    # -- observability --------------------------------------------------
    def pending_depth(self) -> int:
        return sum(1 for r in self.records.values() if r["status"] in PENDING_STATUSES)

    def stats(self) -> dict[str, int]:
        by_status = {s: 0 for s in PENDING_STATUSES + TERMINAL_STATUSES}
        for r in self.records.values():
            by_status[r["status"]] = by_status.get(r["status"], 0) + 1
        return {
            "enqueued": self._enqueued,
            "delivered": self._delivered,
            "retried": self._retried,
            "failed_permanently": self._failed_permanently,
            "duplicates_suppressed": self._duplicates_suppressed,
            "pending_depth": self.pending_depth(),
            **{f"status_{k.lower()}": v for k, v in by_status.items()},
        }

    # -- core API ------------------------------------------------------
    def enqueue(self, *, outbox_id: str, channel: str, payload: str, kind: str, ticker: str, action: str) -> dict[str, Any]:
        """Durably record that this alert must reach ``channel``. Idempotent
        on ``outbox_id`` -- re-enqueuing the same alert (restart, correlator
        re-fire) returns the existing record and never resets a SENT one
        back to PENDING."""
        existing = self.records.get(outbox_id)
        if existing is not None:
            if existing["status"] not in TERMINAL_STATUSES:
                # keep the freshest payload for a still-pending record
                existing["payload"] = payload
                self._save()
            else:
                self._duplicates_suppressed += 1
            return existing
        record = AlertOutboxRecord(
            outbox_id=outbox_id, channel=channel, payload=payload, kind=kind, ticker=ticker, action=action,
            next_attempt_at=datetime.now(timezone.utc).isoformat(),
        )
        self.records[outbox_id] = record.to_dict()
        self._enqueued += 1
        self._save()
        return self.records[outbox_id]

    def mark_published(self, outbox_id: str) -> None:
        rec = self.records.get(outbox_id)
        if rec is None or rec["status"] in TERMINAL_STATUSES:
            return
        rec["status"] = "SENT"
        rec["sent_at"] = datetime.now(timezone.utc).isoformat()
        rec["last_error"] = None
        self._delivered += 1
        self._save()

    def _schedule_retry(self, rec: dict[str, Any], err: str) -> None:
        rec["attempts"] += 1
        rec["last_attempt_at"] = datetime.now(timezone.utc).isoformat()
        rec["last_error"] = err
        if rec["attempts"] >= rec["max_attempts"]:
            rec["status"] = "FAILED"
            self._failed_permanently += 1
            logger.error(
                "Alert outbox: giving up on %s %s (%s) after %d attempts -- last error: %s",
                rec["kind"], rec["ticker"], rec["action"], rec["attempts"], err,
            )
            return
        wait = jittered_backoff_seconds(rec["attempts"], self._backoff_base, self._backoff_max)
        rec["status"] = "RETRY"
        rec["next_attempt_at"] = datetime.fromtimestamp(
            datetime.now(timezone.utc).timestamp() + wait, tz=timezone.utc
        ).isoformat()
        self._retried += 1

    async def flush(self, *, now: datetime | None = None) -> dict[str, int]:
        """Re-attempt every non-terminal record whose backoff has elapsed.
        Safe to call frequently (the message loop calls it every iteration);
        it is a cheap no-op when nothing is pending or nothing is due."""
        now = now or datetime.now(timezone.utc)
        outcome = {"attempted": 0, "delivered": 0, "retry": 0, "failed": 0, "uncertain": 0, "not_due": 0}
        for rec in list(self.records.values()):
            if rec["status"] not in PENDING_STATUSES:
                continue
            nxt = rec.get("next_attempt_at")
            if nxt is not None:
                try:
                    if datetime.fromisoformat(nxt) > now:
                        outcome["not_due"] += 1
                        continue
                except ValueError:
                    pass
            outcome["attempted"] += 1
            if self._publish is None:
                self._schedule_retry(rec, "no publish callable configured")
                outcome["failed" if rec["status"] == "FAILED" else "retry"] += 1
                continue
            try:
                ok = await self._publish(rec["channel"], rec["payload"])
            except Exception as exc:  # noqa: BLE001 -- publish raised: delivery UNKNOWN, retry later (dedup makes it safe)
                rec["status"] = "UNCERTAIN"
                rec["attempts"] += 1
                rec["last_attempt_at"] = now.isoformat()
                rec["last_error"] = f"{type(exc).__name__}: {exc}"
                wait = jittered_backoff_seconds(max(rec["attempts"], 1), self._backoff_base, self._backoff_max)
                rec["next_attempt_at"] = datetime.fromtimestamp(now.timestamp() + wait, tz=timezone.utc).isoformat()
                if rec["attempts"] >= rec["max_attempts"]:
                    rec["status"] = "FAILED"
                    self._failed_permanently += 1
                    outcome["failed"] += 1
                else:
                    outcome["uncertain"] += 1
                continue
            if ok:
                rec["status"] = "SENT"
                rec["sent_at"] = now.isoformat()
                rec["last_error"] = None
                self._delivered += 1
                outcome["delivered"] += 1
            else:
                self._schedule_retry(rec, "publish callable returned falsey")
                outcome["failed" if rec["status"] == "FAILED" else "retry"] += 1
        self._save()
        return outcome
