"""Task 87B FC_03 -- market-independent ingest liveness beacon.

Task 87A forensic finding: ``/ping`` market-feed health was derived
*only* from ``talonx:ingest:ws_heartbeat``, which is written *only when a
market BAR event flows*. Any legitimate quiet interval longer than the
heartbeat's 90s "stale" / 120s TTL -- the market-close transition, thin
pre-market (PreMarketPoller cadence 300s > 120s TTL), weekends, or the
Redis-incident window -- therefore read as
``DEGRADED (market feed disconnected)`` even though the ingest process,
all four pollers and Redis were perfectly alive. There was no
proof-of-life independent of market data flow.

``LivenessBeacon`` fixes the *producer* side: a timer task that writes
``talonx:ingest:liveness`` on a fixed cadence regardless of market
activity, carrying enough context for a session-aware reader
(talonx_dispatch's ``/ping``) to tell these four apart:

  * HEALTHY      -- a market event arrived recently
  * IDLE         -- no recent market event, but the process is alive and
                    the current US session phase legitimately has no
                    ticks to expect (pre-market thin / after-hours /
                    closed / weekend)
  * STALE        -- process alive, but market events have gone quiet
                    *during the regular session* -- genuinely unhealthy
  * DISCONNECTED -- the liveness beat itself is missing/expired, i.e. the
                    ingest process or its Redis link is actually down

Historical Redis reconnect/failure counters are deliberately NOT part of
this beat and must never determine current feed state.
"""

from __future__ import annotations

import asyncio
import json
import logging
from datetime import datetime, timezone
from typing import Callable

from talonx_ingest.config import settings
from talonx_ingest.session import get_session_state

logger = logging.getLogger("talonx_ingest.liveness")

LIVENESS_COMPONENT = "ingest"


class LivenessBeacon:
    def __init__(
        self,
        publisher,
        *,
        interval_seconds: float | None = None,
        ttl_seconds: int | None = None,
        active_poller_fn: Callable[[], str] | None = None,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        self._publisher = publisher
        cfg = settings.redis
        self._interval = interval_seconds if interval_seconds is not None else cfg.liveness_interval_seconds
        self._ttl = ttl_seconds if ttl_seconds is not None else cfg.liveness_ttl_seconds
        self._active_poller_fn = active_poller_fn
        self._now = clock or (lambda: datetime.now(timezone.utc))
        self._stop_event = asyncio.Event()
        self._beats_written = 0

    @property
    def beats_written(self) -> int:
        return self._beats_written

    def stop(self) -> None:
        self._stop_event.set()

    async def _market_event_age_seconds(self) -> float | None:
        """Best-effort read of how long since the last market BAR event,
        from the SAME ``ws_heartbeat`` key market_data.run already writes --
        no new producer, just re-read here so the beat carries it."""
        raw = await self._publisher.read_ws_heartbeat()
        if not raw:
            return None
        try:
            updated_at = datetime.fromisoformat(json.loads(raw).get("updated_at"))
        except (TypeError, ValueError, AttributeError):
            return None
        return (self._now() - updated_at).total_seconds()

    async def _write_once(self) -> None:
        now = self._now()
        age = await self._market_event_age_seconds()
        payload = {
            "component": LIVENESS_COMPONENT,
            "process_alive": True,
            "redis_reachable": bool(getattr(self._publisher, "is_connected", False)),
            "updated_at": now.isoformat(),
            "session_phase": get_session_state(now),
            "last_market_event_age_seconds": None if age is None else round(age, 1),
            "active_poller": (self._active_poller_fn() if self._active_poller_fn is not None else "unknown"),
        }
        ok = await self._publisher.write_liveness(payload, self._ttl)
        if ok:
            self._beats_written += 1

    async def run(self) -> None:
        logger.info(
            "Ingest liveness beacon started (every %.0fs, TTL %ds, key %s)",
            self._interval, self._ttl, settings.redis.liveness_key,
        )
        while not self._stop_event.is_set():
            try:
                await self._write_once()
            except Exception as exc:  # noqa: BLE001 -- a liveness write must never crash ingestion
                logger.warning("Liveness beacon write failed (will retry): %s", exc)
            try:
                await asyncio.wait_for(self._stop_event.wait(), timeout=self._interval)
            except asyncio.TimeoutError:
                pass
