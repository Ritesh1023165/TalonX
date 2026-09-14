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
from collections.abc import Callable
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
    _FRESH_DEFER,
    _FRESH_EXPIRED,
    _FRESH_OK,
    _FRESH_UNQUALIFIED,
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
    message_id: str | int | None = None   # transport ack id on ok


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
            # retry_ambiguous=False: the LOWER layer must not blind-retry a
            # post-request timeout / network drop (could double-send). It raises
            # TelegramAmbiguousError instead -- caught below and surfaced as
            # ambiguous so the OUTBOX (not the transport) owns the decision.
            res = await self._client.send(
                row.text, parse_mode=row.parse_mode, retry_ambiguous=False,
            )
            mid = None
            try:
                mid = getattr(res, "message_id", None) if res is not None else None
            except Exception:  # noqa: BLE001
                mid = None
            return SenderResult(ok=True, message_id=mid)
        except asyncio.CancelledError:
            # a cancel DURING a send: the request may have reached Telegram.
            raise _SendCancelled()
        except TelegramSendError as exc:
            msg = str(exc)
            low = msg.lower()
            if getattr(exc, "ambiguous", False) or "ambiguous" in low or "unconfirmed" in low:
                return SenderResult(ok=False, error=msg, ambiguous=True)
            if ("non-retryable" in low or "invalid" in low or "forbidden" in low
                    or "chat not found" in low or "bad request" in low):
                return SenderResult(ok=False, error=msg, permanent=True)
            if "timeout" in low or "timed out" in low or "network" in low:
                return SenderResult(ok=False, error=msg, ambiguous=True)
            return SenderResult(ok=False, error=msg)   # clean transient -> retry
        except (TimeoutError, asyncio.TimeoutError) as exc:
            return SenderResult(ok=False, error=f"timeout: {exc!r}", ambiguous=True)
        except Exception as exc:  # noqa: BLE001 - any other transport error is transient
            return SenderResult(ok=False, error=repr(exc))


class _SendCancelled(Exception):
    """Internal: a send was cancelled while it may have been in flight."""


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
    unqualified: int = 0      # Task 136B: no usable source-time evidence -- SUPPRESSED, distinct from EXPIRED
    held: int = 0             # left PENDING because delivery is disabled
    held_reason: str | None = None
    simulated: int = 0        # would-send count, outbox NOT mutated
    ambiguous: int = 0
    skipped_not_configured: bool = False
    delivery_ids: list[str] = field(default_factory=list)
    expired_ids: list[str] = field(default_factory=list)
    unqualified_ids: list[str] = field(default_factory=list)
    simulated_ids: list[str] = field(default_factory=list)
    ambiguous_ids: list[str] = field(default_factory=list)
    message_ids: dict = field(default_factory=dict)     # delivery_id -> transport message id
    errors: list[str] = field(default_factory=list)     # unexpected per-row errors (visible, not swallowed)


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
_VALID_MODES = frozenset({MODE_ENABLED, MODE_DISABLED, MODE_SIMULATE})


class InvalidDeliveryMode(ValueError):
    """An unrecognised ``mode`` -- fail closed, never fall through to sending."""


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
    stale_in_flight_seconds: float = 90.0,
    expire_scan_limit: int | None = None,
    clock: "Callable[[], datetime] | None" = None,
) -> DrainResult:
    """Process due PENDING rows, CRITICAL first. Persist-before-send is
    guaranteed by ``enqueue``. Safe to call repeatedly and after a restart.

    Task 136B: ``clock`` is the injectable UTC clock used for the FINAL,
    per-row freshness decision immediately before each send -- distinct
    from ``now`` (used for row SELECTION / the bulk expire_stale sweep /
    claim timestamps elsewhere). Production leaves it ``None`` and gets a
    fresh ``datetime.now(timezone.utc)`` read at each row's decision
    point (a row selected while fresh can still cross its cutoff while
    waiting in a large batch -- using a single stale ``now`` for the
    whole batch, as an earlier fix did to satisfy test determinism,
    reintroduced exactly that gap). Tests pass a small stateful callable
    (e.g. one that advances a controlled starting time) to deterministically
    prove that behaviour without depending on real wall-clock timing.

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
    # (1A) validate the mode BEFORE any expiry / DB mutation / network activity.
    if mode not in _VALID_MODES:
        raise InvalidDeliveryMode(
            f"delivery mode {mode!r} is not one of {sorted(_VALID_MODES)} -- refusing "
            f"(fail closed; no expiry, no send)"
        )
    # (1D) decision time = NOW, not a stale timestamp captured before the poll.
    now = datetime.now(timezone.utc) if now is None else now
    result = DrainResult(mode=mode)

    # (1B) recover any row stuck IN_FLIGHT from a previous drainer that died /
    # was cancelled mid-send -> AMBIGUOUS (never blind re-send). Cheap; runs in
    # every mode so a disabled/simulate cycle still surfaces a stuck claim.
    recovered = outbox.recover_in_flight(now=now, stale_after_seconds=stale_in_flight_seconds)
    if recovered:
        result.ambiguous += len(recovered)
        result.ambiguous_ids.extend(recovered)

    if enforce_age_cutoff:
        result.expired_ids = outbox.expire_stale(
            now=now, max_age_seconds=max_age_seconds, event_time_lookup=event_time_lookup,
            limit=expire_scan_limit, unqualified_ids_out=result.unqualified_ids,
        )
        result.expired = len(result.expired_ids)
        result.unqualified = len(result.unqualified_ids)

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

    import uuid as _uuid

    # Task 136B: `clock` defaults to REUSING the drain's own resolved
    # `now` (not a fresh real-time read) when the caller does not pass
    # one explicitly -- this preserves exact backward compatibility for
    # every existing caller/test that pins `now` for determinism and
    # never mixes it with real wall time. Production (runner.py's
    # deliver_cycle) explicitly passes clock=lambda: datetime.now(...)
    # so it gets a genuinely fresh per-row read; a test that wants to
    # prove the boundary-crossing behaviour passes its own controlled/
    # advancing callable.
    _clock = clock if clock is not None else (lambda: now)

    for row in rows:
        send_now = datetime.now(timezone.utc)          # (1D) per-row decision time
        # Task 136A: the LAST-MOMENT freshness gate, independent of whether
        # the bulk expire_stale() pass above (bounded, enqueued_at_utc-
        # ordered) had already reached THIS row -- outbox.pending() above
        # orders by BAND priority first, so a HIGH-band historical card
        # can be selected for sending well ahead of older-enqueued, lower-
        # band rows the bounded sweep processes first. Without this, queue
        # creation time (today) stands in for source freshness (possibly
        # years old) purely because the two scans disagree on order.
        #
        # Task 136B: this decision MUST use a freshly-read clock, not the
        # single drain-level `now` captured once at the top of the call --
        # a card can cross its expiry boundary while it waits its turn in a
        # large batch, and a stale reused `now` would let it pass anyway.
        # `clock()` defaults to a real fresh `datetime.now(timezone.utc)`
        # read in production; tests inject a controlled/advancing callable.
        if enforce_age_cutoff:
            outcome = outbox.expire_one_if_stale(
                row, now=_clock(), max_age_seconds=max_age_seconds,
                event_time_lookup=event_time_lookup,
            )
            if outcome.disposition == _FRESH_DEFER:
                # transient lookup failure -- row left untouched, PENDING,
                # naturally retried on a later drain. Not counted as
                # expired/unqualified; it is neither.
                continue
            if outcome.disposition in (_FRESH_EXPIRED, _FRESH_UNQUALIFIED):
                if outcome.disposition == _FRESH_EXPIRED:
                    result.expired += 1
                    result.expired_ids.append(row.delivery_id)
                else:
                    result.unqualified += 1
                    result.unqualified_ids.append(row.delivery_id)
                continue
        attempt_id = _uuid.uuid4().hex[:16]
        # (1B) persist-before-network: claim PENDING -> IN_FLIGHT, committed,
        # BEFORE the transport is touched. A competing drainer that lost the
        # claim gets False and skips -- no double logical delivery.
        if not outbox.claim_for_send(row.delivery_id, attempt_id, now=send_now):
            continue
        result.attempted += 1
        try:
            res = await sender.send(row)
        except _SendCancelled:
            # cancelled mid-send: the request may have reached Telegram.
            outbox.mark_ambiguous(
                row.delivery_id, "send cancelled while possibly in flight", now=send_now)
            result.ambiguous += 1
            result.ambiguous_ids.append(row.delivery_id)
            raise                                      # propagate the shutdown signal
        except asyncio.CancelledError:
            outbox.mark_ambiguous(
                row.delivery_id, "task cancelled during send", now=send_now)
            result.ambiguous += 1
            result.ambiguous_ids.append(row.delivery_id)
            raise
        except Exception as exc:  # noqa: BLE001
            # an UNEXPECTED sender error: we crossed (or may have crossed) the
            # boundary -> ambiguous, never a blind retry, never swallowed.
            outbox.mark_ambiguous(
                row.delivery_id, f"unexpected sender error: {exc!r}", now=send_now)
            result.ambiguous += 1
            result.ambiguous_ids.append(row.delivery_id)
            result.errors.append(f"{row.delivery_id}: {exc!r}")
            continue

        if res.ok:
            outbox.mark_sent(row.delivery_id, message_id=res.message_id, now=send_now)
            result.delivered += 1
            result.delivery_ids.append(row.delivery_id)
            if res.message_id is not None:
                result.message_ids[row.delivery_id] = str(res.message_id)
            if metrics is not None:
                metrics.record_delivered(is_update=(row.disposition == "UPDATE"))
            continue
        if res.ambiguous:
            outbox.mark_ambiguous(row.delivery_id, res.error or "unconfirmable outcome", now=send_now)
            result.ambiguous += 1
            result.ambiguous_ids.append(row.delivery_id)
            if metrics is not None and hasattr(metrics, "record_failure"):
                metrics.record_failure()
            continue
        # a CLEAN rejection (rate limit / bad-request / other non-timeout):
        # Telegram did NOT accept it -> safe to release + retry.
        retry_after = res.retry_after_seconds
        if retry_after is None and not res.permanent:
            retry_after = _backoff(row.attempts + 1)
        new_state = outbox.mark_failed(
            row.delivery_id, res.error or "unknown error",
            retry_after_seconds=retry_after, permanent=res.permanent, now=send_now,
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


# ---------------------------------------------------------------------------
# digest -- DIGEST-route rows are AGGREGATED into one periodic message, not
# sent individually. Restart-safe via a persisted last-sent bucket.
# ---------------------------------------------------------------------------
_DIGEST_META_KEY = "last_digest_bucket"
_DIGEST_SENT_AT_KEY = "last_digest_sent_utc"


def _digest_row_summary(r) -> str:
    """Task 118A P3: a plain-text, event-facts-only summary line for one
    digest row -- ticker (by the caller), a concise event description (the
    row's OWN event_id, never invented), an observation time (the row's own
    enqueue time -- labelled as such, not claimed to be the SEC acceptance
    time), and a source link if the row carries one. This digest message is
    sent with parse_mode=None (plain text): it must NEVER embed HTML markup
    -- r.text (rendered for parse_mode="HTML" individual card sends, and
    starting with a literal "<b>...</b>" band line) is deliberately never
    used here, unlike the previous implementation."""
    from talonx_ingest.intelligence.delivery.config import EVENT_TYPE_LABEL
    from talonx_ingest.intelligence.domain import EventType

    etype_raw = r.event_id.rsplit(":", 1)[-1] if r.event_id else None
    try:
        desc = EVENT_TYPE_LABEL.get(EventType(etype_raw), etype_raw or "event")
    except ValueError:
        desc = etype_raw or "event"
    when = r.enqueued_at_utc.strftime("%Y-%m-%dT%H:%MZ") if r.enqueued_at_utc else "time unknown"
    link = f" {r.evidence_urls[0]}" if getattr(r, "evidence_urls", None) else ""
    return f"{desc} (enqueued {when}){link}"


def _digest_text_from_rows(rows: list, now: datetime) -> str:
    from talonx_ingest.intelligence.delivery.config import MAX_DIGEST_ROWS

    rank = {"CRITICAL": 0, "HIGH": 1, "MEDIUM": 2, "LOW": 3, None: 4}
    srt = sorted(rows, key=lambda r: (rank.get(r.band, 4), r.symbol, r.event_id))
    shown = srt[:MAX_DIGEST_ROWS]
    # Task 118A P3: this batch is being sent right now (the caller only
    # reaches this function once `due` is True) -- "held" described rows
    # still PENDING elsewhere in the outbox, which these are not.
    lines = [f"TalonX Intelligence digest - {now.strftime('%Y-%m-%dT%H:%MZ')}",
             f"{len(srt)} event(s) in this digest"]
    for r in shown:
        lines.append(f"- {r.symbol}: {_digest_row_summary(r)}")
    if len(srt) > len(shown):
        lines.append(f"+ {len(srt) - len(shown)} more - open the dashboard")
    lines.append("Informational only - not a recommendation.")
    return "\n".join(lines)


async def process_digest(
    outbox: DeliveryOutbox,
    sender: SenderProtocol,
    *,
    mode: str,
    interval_seconds: float,
    now: datetime | None = None,
    limit: int | None = None,
    enforce_age_cutoff: bool = True,
    max_age_seconds: "dict[str, int] | int | None" = None,
    event_time_lookup=None,
    stale_in_flight_seconds: float = 90.0,
    expire_scan_limit: int | None = None,
    clock: "Callable[[], datetime] | None" = None,
) -> DrainResult:
    """Aggregate + deliver the DIGEST route on a schedule.

    Not due -> the DIGEST rows stay PENDING and are reported as ``held``
    (``held_reason="digest_not_due"``). Due + enabled -> stale rows are
    expired, the rest are claimed as ONE batch, rendered into ONE message,
    sent once, and all marked SENT referencing the digest id. Restart-safe:
    the last-sent time-bucket is persisted, so a restart in the same window
    does not re-send.

    Task 136B: ``clock`` (see ``process_pending``) is read fresh a SECOND
    time immediately before the claimed batch is actually rendered/sent --
    a card can be fresh when first selected for this digest and still cross
    its cutoff while the batch is being assembled. Any card that falls out
    of eligibility at that final check is excluded from the digest and
    never marked SENT; if none remain, nothing is sent at all.
    """
    if mode not in _VALID_MODES:
        raise InvalidDeliveryMode(f"delivery mode {mode!r} invalid")
    now = datetime.now(timezone.utc) if now is None else now
    result = DrainResult(mode=mode)
    result.ambiguous_ids.extend(
        outbox.recover_in_flight(now=now, stale_after_seconds=stale_in_flight_seconds))
    result.ambiguous = len(result.ambiguous_ids)

    bucket = int(now.timestamp() // max(1.0, interval_seconds))
    last_bucket = outbox.get_meta(_DIGEST_META_KEY)
    due = last_bucket is None or int(last_bucket) < bucket

    if enforce_age_cutoff:
        result.expired_ids = outbox.expire_stale(
            now=now, max_age_seconds=max_age_seconds, event_time_lookup=event_time_lookup,
            limit=expire_scan_limit, unqualified_ids_out=result.unqualified_ids,
        )
        result.expired = len(result.expired_ids)
        result.unqualified = len(result.unqualified_ids)

    # Task 136B: `clock` defaults to REUSING the drain's own resolved
    # `now` (not a fresh real-time read) when the caller does not pass
    # one explicitly -- this preserves exact backward compatibility for
    # every existing caller/test that pins `now` for determinism and
    # never mixes it with real wall time. Production (runner.py's
    # deliver_cycle) explicitly passes clock=lambda: datetime.now(...)
    # so it gets a genuinely fresh per-row read; a test that wants to
    # prove the boundary-crossing behaviour passes its own controlled/
    # advancing callable.
    _clock = clock if clock is not None else (lambda: now)

    rows = outbox.digest_pending(now=now, limit=limit)
    # Task 136A/136B: the same last-moment freshness gate as process_pending
    # -- digest_pending() orders/selects independently of the bulk expire_
    # stale() sweep above, so a stale row can otherwise reach the digest
    # batch before the sweep (bounded, enqueue-time-ordered) reaches it.
    # Filtered out BEFORE the due/disabled/simulate checks below so a
    # stale row is never counted as "held" either -- it is independently
    # stale regardless of whether this digest bucket is due. This is an
    # early elimination pass only -- see the SECOND, final-decision-time
    # check right before the claimed batch is actually sent, below.
    if enforce_age_cutoff and rows:
        fresh_rows = []
        for r in rows:
            outcome = outbox.expire_one_if_stale(
                r, now=_clock(), max_age_seconds=max_age_seconds,
                event_time_lookup=event_time_lookup,
            )
            if outcome.disposition == _FRESH_OK:
                fresh_rows.append(r)
            elif outcome.disposition == _FRESH_DEFER:
                # transient lookup failure -- leave this row PENDING,
                # untouched, out of THIS digest attempt, retried later.
                continue
            elif outcome.disposition == _FRESH_EXPIRED:
                result.expired += 1
                result.expired_ids.append(r.delivery_id)
            else:  # _FRESH_UNQUALIFIED
                result.unqualified += 1
                result.unqualified_ids.append(r.delivery_id)
        rows = fresh_rows
    if not due:
        result.held = len(rows)
        result.held_reason = "digest_not_due"
        return result
    if mode == MODE_DISABLED:
        result.held = len(rows)
        result.held_reason = "delivery_disabled"
        for r in rows:
            outbox._log(r.delivery_id, "HELD", "digest due but delivery disabled -- PENDING")
        outbox._conn.commit()
        return result
    if mode == MODE_SIMULATE:
        result.simulated = len(rows)
        result.simulated_ids = [r.delivery_id for r in rows]
        return result
    if not rows:
        # nothing to aggregate -- still advance the bucket so we don't recheck
        outbox.set_meta(_DIGEST_META_KEY, str(bucket))
        outbox.set_meta(_DIGEST_SENT_AT_KEY, now.isoformat())
        return result
    if not sender.configured:
        result.skipped_not_configured = True
        result.held = len(rows)
        result.held_reason = "transport_not_configured"
        return result

    import types
    import uuid as _uuid

    digest_id = f"digest-{bucket}-{_uuid.uuid4().hex[:8]}"
    claimed = outbox.claim_digest_batch([r.delivery_id for r in rows], digest_id, now=now)
    if not claimed:
        return result

    # Task 136B: FINAL-decision-time re-validation. A row can be fresh at
    # the early filter above and still cross its cutoff while this batch
    # was being claimed/assembled (rendering + the checks above take real
    # time in production; a test can simulate the same gap by advancing
    # its injected clock between digest_pending() and here). Re-check each
    # CLAIMED row against a freshly read clock and rebuild the digest from
    # only the still-eligible survivors -- an excluded row is never part
    # of the sent digest and never marked SENT alongside it.
    rows_by_id = {r.delivery_id: r for r in rows}
    send_time = _clock()
    still_eligible: list[str] = []
    for did in claimed:
        outcome = outbox.expire_one_if_stale(
            rows_by_id[did], now=send_time, max_age_seconds=max_age_seconds,
            event_time_lookup=event_time_lookup,
        )
        if outcome.disposition == _FRESH_OK:
            still_eligible.append(did)
        elif outcome.disposition == _FRESH_DEFER:
            # transient -- release our claim so the row returns to PENDING
            # and a later cycle can retry it; not a verdict either way.
            outbox.release_claim(did, digest_id, now=send_time)
        elif outcome.disposition == _FRESH_EXPIRED:
            result.expired += 1
            result.expired_ids.append(did)
        else:  # _FRESH_UNQUALIFIED
            result.unqualified += 1
            result.unqualified_ids.append(did)
    claimed = still_eligible
    if not claimed:
        # Every claimed card fell out of eligibility before the digest
        # could actually be sent -- send nothing (no transport call). The
        # excluded rows above are already in their correct terminal
        # (EXPIRED/SUPPRESSED) or recoverable (released to PENDING) state.
        # The bucket is deliberately NOT advanced here, so a still-fresh
        # set of rows can still produce a real digest send within the same
        # window on a subsequent call.
        return result
    text = _digest_text_from_rows([rows_by_id[did] for did in claimed], now)
    synthetic = types.SimpleNamespace(
        delivery_id=digest_id, text=text, parse_mode=None, disposition="NEW",
        band=None, route="DIGEST", symbol="DIGEST", event_id=digest_id)
    result.attempted += 1
    try:
        res = await sender.send(synthetic)
    except _SendCancelled:
        for did in claimed:
            outbox.mark_ambiguous(did, f"digest {digest_id} cancelled in flight", now=now)
        result.ambiguous += len(claimed); result.ambiguous_ids.extend(claimed)
        raise
    except asyncio.CancelledError:
        for did in claimed:
            outbox.mark_ambiguous(did, f"digest {digest_id} task cancelled", now=now)
        result.ambiguous += len(claimed); result.ambiguous_ids.extend(claimed)
        raise
    except Exception as exc:  # noqa: BLE001
        for did in claimed:
            outbox.mark_ambiguous(did, f"digest {digest_id} unexpected error: {exc!r}", now=now)
        result.ambiguous += len(claimed); result.ambiguous_ids.extend(claimed)
        result.errors.append(f"{digest_id}: {exc!r}")
        return result

    if res.ok:
        outbox.mark_digest_sent(claimed, digest_id, message_id=res.message_id, now=now)
        outbox.set_meta(_DIGEST_META_KEY, str(bucket))
        outbox.set_meta(_DIGEST_SENT_AT_KEY, now.isoformat())
        result.delivered += len(claimed)
        result.delivery_ids.extend(claimed)
        if res.message_id is not None:
            result.message_ids[digest_id] = str(res.message_id)
    elif res.ambiguous:
        for did in claimed:
            outbox.mark_ambiguous(did, res.error or f"digest {digest_id} unconfirmed", now=now)
        result.ambiguous += len(claimed); result.ambiguous_ids.extend(claimed)
    else:
        # clean rejection -> release the batch back to PENDING for the next window
        for did in claimed:
            outbox.mark_failed(did, res.error or f"digest {digest_id} rejected",
                               retry_after_seconds=_backoff(1), permanent=res.permanent, now=now)
        result.retried += len(claimed)
    return result
