"""
talonx_ingest.intelligence.delivery.pipeline
============================================
Orchestration: render a card, run claim safety, apply the update policy,
persist to the durable outbox (BEFORE any send), then drain PENDING rows
to Telegram with retry / rate-limit handling.

Transport is pluggable (``SenderProtocol``). The default adapter wraps the
existing, already-qualified ``talonx_dispatch.telegram_client.TelegramClient``;
tests inject ``RecordingSender`` / ``NullSender`` and never touch the
network. The whole path is independent of any execution / paper / Redis
state (``EXECUTION_INDEPENDENCE_AUDIT.md``).
"""
from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Protocol

from talonx_ingest.intelligence.delivery.claim_safety import (
    PredictiveLanguageError,
    assert_clean,
)
from talonx_ingest.intelligence.delivery.config import (
    RENDER_VERSION,
    RETRY_BASE_SECONDS,
    RETRY_MAX_SECONDS,
    TIER_COMPACT,
    TIER_EXPANDED,
)
from talonx_ingest.intelligence.delivery.identity import delivery_id as _delivery_id
from talonx_ingest.intelligence.delivery.observability import DeliveryMetrics
from talonx_ingest.intelligence.delivery.outbox import (
    STATE_FAILED,
    DeliveryOutbox,
    DeliveryRow,
    EnqueueResult,
)
from talonx_ingest.intelligence.delivery.render_model import TelegramIntelligenceMessage
from talonx_ingest.intelligence.delivery.renderer import (
    render_compact,
    render_expanded,
    render_for_card,
)
from talonx_ingest.intelligence.delivery.update_policy import (
    DECISION_UPDATE,
    classify_update,
)


# ---------------------------------------------------------------------------
# transport
# ---------------------------------------------------------------------------
@dataclass(frozen=True)
class SenderResult:
    ok: bool
    error: str | None = None
    retry_after_seconds: float | None = None
    permanent: bool = False
    ambiguous: bool = False   # request left but the outcome is unconfirmable


class SenderProtocol(Protocol):
    @property
    def configured(self) -> bool: ...

    async def send(self, row: DeliveryRow) -> SenderResult: ...


class RecordingSender:
    """Test / dev sender. Records every send; can be told to fail the first
    ``fail_times`` attempts (optionally with a ``retry_after``)."""

    def __init__(
        self,
        *,
        configured: bool = True,
        fail_times: int = 0,
        fail_error: str = "simulated transient failure",
        retry_after_seconds: float | None = None,
        permanent: bool = False,
    ):
        self._configured = configured
        self.sent: list[DeliveryRow] = []
        self.attempts = 0
        self._fail_times = fail_times
        self._fail_error = fail_error
        self._retry_after = retry_after_seconds
        self._permanent = permanent

    @property
    def configured(self) -> bool:
        return self._configured

    async def send(self, row: DeliveryRow) -> SenderResult:
        self.attempts += 1
        if self.attempts <= self._fail_times:
            return SenderResult(
                ok=False, error=self._fail_error,
                retry_after_seconds=self._retry_after, permanent=self._permanent,
            )
        self.sent.append(row)
        return SenderResult(ok=True)


class NullSender:
    """Dry-run sender: reports success, sends nothing anywhere."""

    configured = True

    def __init__(self) -> None:
        self.rendered: list[DeliveryRow] = []

    async def send(self, row: DeliveryRow) -> SenderResult:
        self.rendered.append(row)
        return SenderResult(ok=True)


class TelegramSenderAdapter:
    """Wraps ``talonx_dispatch.telegram_client.TelegramClient`` — the only
    point that touches the real Telegram transport."""

    def __init__(self, client=None):
        if client is None:
            from talonx_dispatch.telegram_client import TelegramClient

            client = TelegramClient()
        self._client = client

    @property
    def configured(self) -> bool:
        return bool(getattr(self._client, "is_configured", False))

    async def send(self, row: DeliveryRow) -> SenderResult:
        from talonx_dispatch.telegram_client import TelegramSendError

        try:
            await self._client.send(row.text, parse_mode=row.parse_mode)
            return SenderResult(ok=True)
        except TelegramSendError as exc:
            msg = str(exc)
            low = msg.lower()
            if "non-retryable" in low or "invalid" in low or "forbidden" in low or "chat not found" in low:
                return SenderResult(ok=False, error=msg, permanent=True)
            # a timeout / 5xx AFTER the request left is unconfirmable -- do NOT
            # blind-retry (could double-send); mark the row AMBIGUOUS.
            if "timeout" in low or "timed out" in low or " 5" in msg or "ambig" in low:
                return SenderResult(ok=False, error=msg, ambiguous=True)
            return SenderResult(ok=False, error=msg)
        except TimeoutError as exc:
            return SenderResult(ok=False, error=f"timeout: {exc!r}", ambiguous=True)
        except Exception as exc:  # noqa: BLE001 - any other transport error is transient
            return SenderResult(ok=False, error=repr(exc))


# ---------------------------------------------------------------------------
# results
# ---------------------------------------------------------------------------
@dataclass
class DrainResult:
    mode: str = "enabled"
    attempted: int = 0
    delivered: int = 0        # real transport ack, mode="enabled" only
    retried: int = 0
    failed: int = 0
    expired: int = 0
    held: int = 0             # left PENDING because delivery is disabled
    held_reason: str | None = None
    simulated: int = 0        # would-send count, outbox NOT mutated
    ambiguous: int = 0
    skipped_not_configured: bool = False
    delivery_ids: list[str] = field(default_factory=list)
    expired_ids: list[str] = field(default_factory=list)
    simulated_ids: list[str] = field(default_factory=list)
    ambiguous_ids: list[str] = field(default_factory=list)


# ---------------------------------------------------------------------------
# enqueue
# ---------------------------------------------------------------------------
def render_card(
    card,
    *,
    what_changed: dict | None = None,
    insider_activity=None,
    tier: str | None = None,
) -> TelegramIntelligenceMessage:
    if tier == TIER_COMPACT:
        return render_compact(card, what_changed=what_changed, insider_activity=insider_activity)
    if tier == TIER_EXPANDED:
        return render_expanded(card, what_changed=what_changed, insider_activity=insider_activity)
    return render_for_card(card, what_changed=what_changed, insider_activity=insider_activity)


def enqueue_card(
    card,
    *,
    outbox: DeliveryOutbox,
    what_changed: dict | None = None,
    insider_activity=None,
    tier: str | None = None,
    allow_update: bool = False,
    metrics: DeliveryMetrics | None = None,
    render_version: str = RENDER_VERSION,
    now: datetime | None = None,
) -> EnqueueResult:
    """Render + claim-safety + update-policy + durable persist. Raises
    ``PredictiveLanguageError`` (fail closed) if the rendered text carries
    prohibited claim language — a bad message never reaches the outbox."""
    now = now or datetime.now(timezone.utc)
    message = render_card(
        card, what_changed=what_changed, insider_activity=insider_activity, tier=tier
    )
    if metrics is not None:
        metrics.record_render(message.band.value if message.band else None, truncated=message.truncated)

    try:
        assert_clean(message.text)
    except PredictiveLanguageError:
        if metrics is not None:
            metrics.record_claim_safety_rejection()
        raise

    did = _delivery_id(card.alert_id, render_version=render_version)
    existing = outbox.get(did)
    prior_sent_text = existing.text if (existing and existing.state == "SENT") else None
    decision = classify_update(
        prior_sent_text=prior_sent_text,
        prior_band=(existing.band if existing else None),
        new_text=message.text,
        new_band=message.band.value if message.band else None,
        prior_content_hash=(existing.content_hash if existing else None),
        new_content_hash=message.content_hash,
    )

    disposition = "NEW"
    if decision.decision == DECISION_UPDATE:
        if not allow_update:
            if metrics is not None:
                metrics.record_suppressed(decision.decision)
            res = EnqueueResult(existing, False, "SUPPRESSED", "UPDATE not permitted by caller")
            return res
        disposition = "UPDATE"
    elif not decision.should_enqueue:
        if metrics is not None:
            metrics.record_suppressed(decision.decision)
        return EnqueueResult(existing, False, "SUPPRESSED", decision.reason)

    result = outbox.enqueue(
        message, delivery_id=did, disposition=disposition, reason=decision.reason, now=now
    )
    if metrics is not None and result.disposition in ("NEW", "UPDATE"):
        metrics.record_enqueue(message.route, result.disposition)
    elif metrics is not None:
        metrics.record_suppressed(result.disposition)
    return result


# ---------------------------------------------------------------------------
# drain
# ---------------------------------------------------------------------------
def _backoff(attempts: int) -> float:
    return min(RETRY_MAX_SECONDS, RETRY_BASE_SECONDS * (2 ** max(0, attempts)))


MODE_ENABLED = "enabled"
MODE_DISABLED = "disabled"
MODE_SIMULATE = "simulate"


async def process_pending(
    outbox: DeliveryOutbox,
    sender: SenderProtocol,
    *,
    mode: str | None = None,
    route: str | None = None,
    limit: int | None = None,
    dry_run: bool = False,                       # back-compat alias for mode="simulate"
    metrics: DeliveryMetrics | None = None,
    now: datetime | None = None,
    enforce_age_cutoff: bool = False,
    max_age_seconds: "dict[str, int] | int | None" = None,
    event_time_lookup=None,
) -> DrainResult:
    """Process due PENDING rows, CRITICAL first. Persist-before-send is
    guaranteed by ``enqueue``. Safe to call repeatedly and after a restart.

    ``mode``:
      * ``"enabled"``  -- the ONLY mode that can produce ``SENT``. A row is
        marked SENT only on a real transport ack; a transient failure -> RETRY;
        permanent -> FAILED; an unconfirmable outcome -> AMBIGUOUS (durable,
        never blind-retried).
      * ``"disabled"`` (default when neither ``mode`` nor ``dry_run`` given) --
        no sender is called and NO row is mutated. Eligible rows stay PENDING
        and are reported as ``held`` with ``held_reason="delivery_disabled"``.
      * ``"simulate"`` -- renders the drain PLAN (which rows, in what order) on
        an isolated basis; the outbox is NOT mutated and nothing is represented
        as delivered. ``dry_run=True`` maps here.

    ``enforce_age_cutoff`` (D5) is an EXPLICIT, separate step: when passed it
    calls ``outbox.expire_stale`` first. It is independent of ``mode`` -- but a
    caller in ``"disabled"`` mode must opt in on purpose (backlog expiry is not
    a side effect of a disabled drain).
    """
    if mode is None:
        mode = MODE_SIMULATE if dry_run else MODE_DISABLED
    now = now or datetime.now(timezone.utc)
    result = DrainResult(mode=mode)

    if enforce_age_cutoff:
        result.expired_ids = outbox.expire_stale(
            now=now, max_age_seconds=max_age_seconds, event_time_lookup=event_time_lookup,
        )
        result.expired = len(result.expired_ids)

    rows = outbox.pending(route=route, now=now, limit=limit)

    if mode == MODE_DISABLED:
        result.held = len(rows)
        result.held_reason = "delivery_disabled"
        for row in rows:
            outbox._log(row.delivery_id, "HELD", "delivery disabled -- left PENDING")
        outbox._conn.commit()
        return result

    if mode == MODE_SIMULATE:
        result.simulated = len(rows)
        result.simulated_ids = [r.delivery_id for r in rows]
        return result                            # outbox untouched

    # ---- mode == "enabled" -------------------------------------------------
    if not sender.configured:
        result.skipped_not_configured = True
        result.held = len(rows)
        result.held_reason = "transport_not_configured"
        return result

    for row in rows:
        result.attempted += 1
        res = await sender.send(row)
        if res.ok:
            outbox.mark_sent(row.delivery_id, now=now)
            result.delivered += 1
            result.delivery_ids.append(row.delivery_id)
            if metrics is not None:
                metrics.record_delivered(is_update=(row.disposition == "UPDATE"))
            continue
        if res.ambiguous:
            outbox.mark_ambiguous(row.delivery_id, res.error or "unconfirmable outcome", now=now)
            result.ambiguous += 1
            result.ambiguous_ids.append(row.delivery_id)
            if metrics is not None and hasattr(metrics, "record_failure"):
                metrics.record_failure()
            continue
        retry_after = res.retry_after_seconds
        if retry_after is None and not res.permanent:
            retry_after = _backoff(row.attempts + 1)
        new_state = outbox.mark_failed(
            row.delivery_id, res.error or "unknown error",
            retry_after_seconds=retry_after, permanent=res.permanent, now=now,
        )
        if new_state == STATE_FAILED:
            result.failed += 1
            if metrics is not None:
                metrics.record_failure()
        else:
            result.retried += 1
            if metrics is not None:
                metrics.record_retry()
    return result


def process_pending_sync(*args, **kwargs) -> DrainResult:
    return asyncio.run(process_pending(*args, **kwargs))
