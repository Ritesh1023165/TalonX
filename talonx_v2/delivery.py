"""
talonx_v2.delivery -- durable V2 official-alert delivery worker (Task 117 overnight)
================================================================================
The V2 pipeline produces alert intents; ``V2Service`` persists them into the
``v2_alert_outbox`` table (``store.enqueue_alert``).  This module drains that
outbox:

  1. ask ``talonx_ops.official_dispatch.OfficialExternalRouter`` whether the
     ``insider_buy_cluster_v2`` family may send and whether this dedup_key was
     already delivered (per that family's OWN store -- no cross-store merge);
  2. hand the rendered payload to an INJECTED transport at the final boundary;
  3. record an explicit terminal-ish state: SENT / HELD / AMBIGUOUS / RETRY / FAILED,
     with attempt count, bounded backoff, last error and transport evidence.

Nothing here opens a network socket by itself.  The default transport is a
dry-run that HOLDS (records the intent, sends nothing).  Tests inject a
RecordingTransport.  A real ``talonx:alerts:dispatch`` publisher transport is
provided but is NOT wired into any running service by this task.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Any, Callable, Protocol

from talonx_v2.dispatch_bridge import FAMILY

logger = logging.getLogger("talonx_v2.delivery")

_BACKOFF_BASE_S = 5
_BACKOFF_CAP_S = 300
_DEFAULT_MAX_ATTEMPTS = 5


class Transport(Protocol):
    name: str

    def send(self, payload_text: str, *, meta: dict[str, Any]) -> dict[str, Any]:
        """Return one of:
          {"ok": True, "ref": "<transport ref>"}          -> SENT (with evidence)
          {"held": True, "detail": "..."}                  -> HELD (deliberate no-send)
          {"ambiguous": True, "detail": "..."}             -> AMBIGUOUS (unknown outcome)
          {"ok": False, "detail": "..."}                   -> RETRY / FAILED
        or raise -> RETRY / FAILED.
        """


class DryRunTransport:
    """Default: records the intent, sends nothing.  Every attempt -> HELD."""

    name = "dry_run"

    def send(self, payload_text: str, *, meta: dict[str, Any]) -> dict[str, Any]:
        return {"held": True, "detail": "dry-run transport -- external send disabled this run"}


@dataclass
class RecordingTransport:
    """Test/isolation transport: captures every payload at the final boundary
    and returns an explicit outcome.  NO real network."""

    name: str = "recording"
    outcomes: list[dict[str, Any]] = field(default_factory=list)   # forced per-call outcomes
    sent: list[dict[str, Any]] = field(default_factory=list)
    _n: int = 0

    def send(self, payload_text: str, *, meta: dict[str, Any]) -> dict[str, Any]:
        self._n += 1
        rec = {"seq": self._n, "payload_text": payload_text, "meta": dict(meta),
               "at_utc": datetime.now(timezone.utc).isoformat()}
        if self.outcomes:
            forced = self.outcomes.pop(0)
            if forced.get("raise"):
                self.sent.append({**rec, "result": "RAISED"})
                raise RuntimeError(forced.get("detail", "forced transport failure"))
            self.sent.append({**rec, "result": forced})
            return forced
        ref = f"rec-{self._n:04d}"
        self.sent.append({**rec, "result": {"ok": True, "ref": ref}})
        return {"ok": True, "ref": ref}


class RedisDispatchPublishTransport:
    """Production transport (NOT wired to run by Task 117): publish the V2 card
    onto the existing official ``talonx:alerts:dispatch`` channel so the running
    DispatchAgent delivers it via the ONE official Telegram path.  Requires an
    explicit redis url + an isolated instance for any test."""

    name = "redis_dispatch_publish"

    def __init__(self, *, redis_url: str, channel: str = "talonx:alerts:dispatch"):
        self._url = redis_url
        self._channel = channel

    def send(self, payload_text: str, *, meta: dict[str, Any]) -> dict[str, Any]:  # pragma: no cover
        import redis
        r = redis.Redis.from_url(self._url, decode_responses=True)
        n = r.publish(self._channel, payload_text)
        if n <= 0:
            # published but no live subscriber -- outcome is genuinely unknown
            return {"ambiguous": True, "detail": f"published to {self._channel} but 0 subscribers"}
        return {"ok": True, "ref": f"redis_publish:{self._channel}:subs={n}"}


class OfficialTelegramTransport:
    """The REAL official Telegram transport for the V2 outbox.

    Wraps ``talonx_dispatch.telegram_client.TelegramClient`` -- the ONE official
    sender the DispatchAgent already uses.  It:
      * resolves the logical ``TRADE_EVENT`` destination (TalonX Signal) through
        ``talonx_ops.notify.telegram_client_for`` -- the SAME resolution the
        release gate validates (2026-09-25 fix: it used to build a bare
        ``TelegramClient()`` from the legacy ``TELEGRAM_BOT_TOKEN``, which had
        been revoked, so a real BUY/SELL would have failed with 401);
      * HOLDS (sends nothing) when that destination is disabled/unconfigured --
        it NEVER falls back to the legacy ``TELEGRAM_BOT_TOKEN``;
      * sends with ``parse_mode=None`` (the V2 card carries raw ``*``/``_``;
        Telegram would 400 the whole message otherwise -- 2026-08-18 incident);
      * maps a non-retryable client error (bad token / bot blocked) to a
        ``permanent`` failure so the worker does not burn its retry budget;
      * maps an exhausted-retries client error to a transient not-ok
        (worker retries with its own bounded backoff, then FAILED, still visible).

    Nothing here changes routing -- ``deliver_outbox`` still asks
    ``OfficialExternalRouter`` first.  Delivery is enabled ONLY by the caller
    passing this transport with ``deliver=True``; the default stays dry-run HOLD.
    """

    name = "official_telegram"

    def __init__(self, *, client: object | None = None, destination: str = "TRADE_EVENT"):
        self._client = client
        self.destination = destination

    def _resolve(self):
        """The client for ``self.destination`` (None when that destination is disabled). Never the legacy
        default-config ``TelegramClient()``."""
        if self._client is not None:
            return self._client
        from talonx_ops.notify import telegram_client_for
        return telegram_client_for(self.destination)

    def send(self, payload_text: str, *, meta: dict[str, Any]) -> dict[str, Any]:
        import asyncio
        client = self._resolve()
        if client is None or not getattr(client, "is_configured", False):
            return {"held": True,
                    "detail": f"{self.destination} destination not enabled/configured -- HOLD "
                              "(no fallback to the legacy TELEGRAM_BOT_TOKEN)"}
        try:
            from talonx_dispatch.telegram_client import TelegramSendError
        except Exception:  # noqa: BLE001 -- narrow import guard for tests with a stub client
            TelegramSendError = Exception  # type: ignore
        try:
            coro = client.send(payload_text, parse_mode=None)
            try:
                asyncio.get_running_loop()
            except RuntimeError:
                asyncio.run(coro)
            else:  # pragma: no cover - the worker is sync; this is defensive
                raise RuntimeError("OfficialTelegramTransport.send called inside a running loop")
        except TelegramSendError as exc:  # type: ignore[misc]
            txt = str(exc)
            permanent = "non-retryable" in txt
            return {"ok": False, "permanent": permanent, "detail": f"telegram: {txt}"}
        except Exception as exc:  # noqa: BLE001
            return {"ok": False, "detail": f"telegram transport error: {exc!r}"}
        cid = str(meta.get("dedup_key", ""))
        return {"ok": True, "ref": f"telegram:sent:{cid}"}


def _backoff_s(attempts: int) -> int:
    return min(_BACKOFF_CAP_S, _BACKOFF_BASE_S * (2 ** max(0, attempts - 1)))


def deliver_outbox(store, *, router, transport: Transport | None = None,
                   now: datetime | None = None,
                   max_attempts: int = _DEFAULT_MAX_ATTEMPTS,
                   broad_discovery_symbols: frozenset[str] = frozenset()) -> dict[str, Any]:
    """Drain v2_alert_outbox once.  Returns a per-run summary.

    ``router`` = talonx_ops.official_dispatch.OfficialExternalRouter (or a
    compatible object with ``.decide(family, dedup_key, origin=...)``).

    ``broad_discovery_symbols`` (Task 131 Directive 5): symbols whose alert
    should be tagged ``origin="BROAD_DISCOVERY"`` for the router's own,
    independent dispatch toggle -- empty by default, byte-identical to
    pre-Task-131 routing for every symbol.
    """
    transport = transport or DryRunTransport()
    now = now or datetime.now(timezone.utc)
    now_iso = now.isoformat()
    summary = {"transport": transport.name, "considered": 0, "sent": 0, "held": 0,
               "retry": 0, "failed": 0, "ambiguous": 0, "dedup_skipped": 0, "events": []}

    for row in store.outbox_due(now_iso=now_iso):
        summary["considered"] += 1
        eid, dedup = row["event_id"], row["dedup_key"]

        # NOTIFICATION DEADLINE (Task 117 deployment-readiness): an
        # actionable-instruction alert (ENTRY_INTENT / PLANNED BUY) must NOT be
        # sent after its window -- a queued instruction that emerges post-open is
        # no longer actionable.  Expire it instead.  Pure notifications
        # (ENTRY_FILL / EXIT_FILL / ENTRY_STALE) carry no deadline.
        deadline = row.get("deliver_by_utc")
        if deadline and now_iso >= deadline:
            store.update_outbox(eid, state="EXPIRED",
                                last_error=f"actionable-instruction deadline {deadline} passed "
                                           "-- not delivered as fresh; the planned open is no "
                                           "longer actionable")
            summary.setdefault("expired", 0)
            summary["expired"] += 1
            summary["events"].append({"event_id": eid, "state": "EXPIRED", "reason": "deadline"})
            continue

        origin = "BROAD_DISCOVERY" if row["symbol"] in broad_discovery_symbols else "PRODUCT_WATCHLIST"
        try:
            rd = router.decide(FAMILY, dedup, origin=origin)
        except TypeError:
            rd = router.decide(FAMILY, dedup)  # a minimal test double without ``origin`` support
        if not getattr(rd, "eligible", False):
            store.update_outbox(eid, state="HELD", last_error=f"router: {rd.reason}")
            summary["held"] += 1
            summary["events"].append({"event_id": eid, "state": "HELD", "reason": rd.reason})
            continue
        if getattr(rd, "already_delivered", False):
            store.update_outbox(eid, state="SENT", transport_ref="dedup:already_delivered",
                                sent=True)
            summary["dedup_skipped"] += 1
            summary["events"].append({"event_id": eid, "state": "SENT",
                                      "reason": "already delivered (family store) -- no duplicate"})
            continue

        attempts = int(row["attempts"]) + 1
        meta = {"event_id": eid, "episode_id": row["episode_id"], "kind": row["kind"],
                "action": row["action"], "symbol": row["symbol"],
                "strategy_version": row["strategy_version"],
                "horizon_trading_days": row["horizon_trading_days"],
                "dedup_key": dedup, "provenance": row["provenance_json"]}
        try:
            res = transport.send(row["payload_text"], meta=meta)
        except Exception as exc:  # noqa: BLE001
            res = {"ok": False, "detail": f"transport raised: {exc!r}"}

        if res.get("ok") is True:
            store.update_outbox(eid, state="SENT", attempts=attempts,
                                transport_ref=str(res.get("ref", "")), sent=True)
            summary["sent"] += 1
            st = "SENT"
        elif res.get("ambiguous"):
            store.update_outbox(eid, state="AMBIGUOUS", attempts=attempts,
                                last_error=str(res.get("detail", "ambiguous transport outcome")))
            summary["ambiguous"] += 1
            st = "AMBIGUOUS"
        elif res.get("held"):
            store.update_outbox(eid, state="HELD", attempts=attempts,
                                last_error=str(res.get("detail", "held")))
            summary["held"] += 1
            st = "HELD"
        else:
            detail = str(res.get("detail", "transport returned not-ok"))
            if res.get("permanent") or attempts >= max_attempts:
                why = ("permanent transport failure" if res.get("permanent")
                       else f"max attempts ({max_attempts})")
                store.update_outbox(eid, state="FAILED", attempts=attempts,
                                    last_error=f"{why}: {detail}", next_attempt_utc=None)
                summary["failed"] += 1
                st = "FAILED"
            else:
                nxt = (now + timedelta(seconds=_backoff_s(attempts))).isoformat()
                store.update_outbox(eid, state="RETRY", attempts=attempts,
                                    last_error=detail, next_attempt_utc=nxt)
                summary["retry"] += 1
                st = "RETRY"
        summary["events"].append({"event_id": eid, "state": st, "attempts": attempts})
    return summary
