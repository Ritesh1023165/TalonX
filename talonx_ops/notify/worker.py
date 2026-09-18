"""
talonx_ops.notify.worker -- generic drain loop for the OPERATIONS/
RESEARCH outbox (RI-2, RI2-I/J).
====================================================================
Mirrors ``talonx_v2/delivery.py::deliver_outbox``'s state-machine shape
and backoff formula exactly (same SENT/HELD/RETRY/FAILED/EXPIRED/
AMBIGUOUS semantics) -- deliberately NOT importing that function
directly, since its ``meta``/deadline handling is specific to V2's own
row shape (episode_id/symbol/strategy_version); this is the equivalent
for the destination-generic ``ops_notification_outbox`` row shape.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any

from talonx_ops.notify import resolve_destination_config, telegram_client_for

_BACKOFF_BASE_S = 5
_BACKOFF_CAP_S = 300
_DEFAULT_MAX_ATTEMPTS = 5


def _backoff_s(attempts: int) -> int:
    return min(_BACKOFF_CAP_S, _BACKOFF_BASE_S * (2 ** max(0, attempts - 1)))


def drain(store, *, destination: str, now: datetime | None = None,
         max_attempts: int = _DEFAULT_MAX_ATTEMPTS, client=None) -> dict[str, Any]:
    """Drain one destination's due rows once. Returns a per-run summary.

    If the destination is not enabled (RI2-C/F), every due row is left
    EXACTLY as it was -- PENDING, untouched, eligible to drain the
    instant an operator configures/enables it later. This is never an
    error; it is the safe default (RI2-M: do not silently discard).

    ``client`` -- optional injected transport-capable object exposing a
    sync ``.send(text) -> dict``-ish outcome; when omitted, resolves the
    REAL client for this destination via
    ``talonx_ops.notify.telegram_client_for`` (async
    ``talonx_dispatch.telegram_client.TelegramClient``, invoked
    synchronously the same way ``OfficialTelegramTransport`` already
    does -- see that class for the exact async-bridging pattern reused
    here)."""
    now = now or datetime.now(timezone.utc)
    now_iso = now.isoformat()
    cfg = resolve_destination_config(destination)
    summary = {"destination": destination, "enabled": cfg.enabled, "reason": cfg.reason,
               "considered": 0, "sent": 0, "held": 0, "retry": 0, "failed": 0,
               "ambiguous": 0, "expired": 0, "skipped_disabled": 0}

    due = store.outbox_due(now_iso=now_iso, destination=destination)
    if not cfg.enabled:
        # RI2-F/M: destination disabled -> no send, no fallback, rows
        # stay PENDING (never silently discarded, never expired merely
        # for being disabled).
        summary["skipped_disabled"] = len(due)
        return summary

    resolved_client = client if client is not None else telegram_client_for(destination)

    for row in due:
        summary["considered"] += 1
        eid = row["event_id"]

        deadline = row.get("deliver_by_utc")
        if deadline and now_iso >= deadline:
            store.update_outbox(eid, state="EXPIRED",
                                last_error=f"deadline {deadline} passed -- not delivered as fresh")
            summary["expired"] += 1
            continue

        attempts = int(row["attempts"]) + 1
        try:
            res = _send_sync(resolved_client, row["payload_text"], meta={
                "event_id": eid, "destination": destination, "event_type": row["event_type"],
                "producer": row["producer"], "dedup_key": row["dedup_key"],
            })
        except Exception as exc:  # noqa: BLE001
            res = {"ok": False, "detail": f"transport raised: {exc!r}"}

        if res.get("ok") is True:
            store.update_outbox(eid, state="SENT", attempts=attempts,
                                transport_ref=str(res.get("ref", "")), sent=True)
            summary["sent"] += 1
        elif res.get("ambiguous"):
            store.update_outbox(eid, state="AMBIGUOUS", attempts=attempts,
                                last_error=str(res.get("detail", "ambiguous transport outcome")))
            summary["ambiguous"] += 1
        elif res.get("held"):
            store.update_outbox(eid, state="HELD", attempts=attempts,
                                last_error=str(res.get("detail", "held")))
            summary["held"] += 1
        else:
            detail = str(res.get("detail", "transport returned not-ok"))
            if res.get("permanent") or attempts >= max_attempts:
                why = "permanent transport failure" if res.get("permanent") else f"max attempts ({max_attempts})"
                store.update_outbox(eid, state="FAILED", attempts=attempts,
                                    last_error=f"{why}: {detail}", next_attempt_utc=None)
                summary["failed"] += 1
            else:
                nxt = (now + timedelta(seconds=_backoff_s(attempts))).isoformat()
                store.update_outbox(eid, state="RETRY", attempts=attempts,
                                    last_error=detail, next_attempt_utc=nxt)
                summary["retry"] += 1
    return summary


def _send_sync(client, payload_text: str, *, meta: dict) -> dict[str, Any]:
    """Bridges the async talonx_dispatch.telegram_client.TelegramClient
    (or a sync test double) into this sync drain loop -- the exact
    pattern talonx_v2/delivery.py::OfficialTelegramTransport already
    uses (asyncio.run when no loop is running)."""
    if client is None:
        return {"held": True, "detail": "destination enabled but no transport resolved -- HOLD"}
    if not getattr(client, "is_configured", True):
        return {"held": True, "detail": "destination enabled but Telegram credentials invalid/"
                                        "unconfigured -- HOLD (never silently discarded)"}
    send = getattr(client, "send", None)
    if send is None:
        return {"ok": False, "detail": "transport has no .send()"}
    import asyncio
    import inspect
    try:
        if inspect.iscoroutinefunction(send):
            coro = send(payload_text, parse_mode=None)
            try:
                asyncio.get_running_loop()
            except RuntimeError:
                asyncio.run(coro)
            else:  # pragma: no cover - this worker is sync; defensive only
                raise RuntimeError("_send_sync called inside a running event loop")
            ref = f"telegram:sent:{meta.get('dedup_key', meta.get('event_id', ''))}"
            return {"ok": True, "ref": ref}
        # a plain sync test double / RecordingTransport-shaped object
        return send(payload_text, meta=meta)
    except Exception as exc:  # noqa: BLE001
        try:
            from talonx_dispatch.telegram_client import TelegramSendError
        except Exception:  # noqa: BLE001
            TelegramSendError = ()  # type: ignore
        if TelegramSendError and isinstance(exc, TelegramSendError):
            return {"ok": False, "permanent": getattr(exc, "ambiguous", False) is False
                    and "non-retryable" in str(exc), "detail": f"telegram: {exc}"}
        return {"ok": False, "detail": f"telegram transport error: {exc!r}"}
