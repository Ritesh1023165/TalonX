"""Task 87B FC_06 -- bounded startup sequencing + readiness reporting.

Task 87A root cause of the 2026-08-31 07:31-07:44 UTC Redis incident:
startup resource contention. The regime bootstrap / preseed, the first
(embedding-heavy) cycles of periodic_ingestion_loop and
periodic_long_term_financials_loop, the long-term factors reconciliation,
EDGAR HTTP, market polling, and a parallel PIV warmup all fired at t=0 on
one ~1 GB / ~85% CPU worker. The asyncio event loop stalled long enough
for Redis' socket timeouts to elapse -> the publisher tore its client
down and reconnected five times before the burst subsided.

This module does two small things, no functional change to what any
component computes:

  * ``StartupReadiness`` -- an in-process phase tracker whose snapshot is
    published to ``talonx:ingest:startup`` and folded into the liveness
    beat, so /ping and dashboards can see "market path ready, expensive
    bootstrap still warming" instead of a binary up/down.
  * ``delayed_start`` -- wrap an expensive background coroutine so its
    FIRST cycle is deferred by a small, bounded, staggered delay
    (default 3s * position), keeping the critical path (Redis connect,
    market pollers, core consumers) uncontended at t=0 without an
    arbitrary large sleep.
"""

from __future__ import annotations

import asyncio
import json
import logging
from datetime import datetime, timezone

logger = logging.getLogger("talonx_ingest.startup_readiness")

# Ordered critical-path -> background phases.
PHASE_PROCESS_START = "process_start"
PHASE_PRESEED_COMPLETE = "preseed_complete"
PHASE_REDIS_CONNECTED = "redis_connected"
PHASE_MARKET_POLLERS_STARTED = "market_pollers_started"
PHASE_CONSUMERS_STARTED = "consumers_started"
PHASE_BOOTSTRAP_SCHEDULED = "bootstrap_scheduled"
PHASE_FULL_READY = "full_ready"

_ORDER = (
    PHASE_PROCESS_START, PHASE_PRESEED_COMPLETE, PHASE_REDIS_CONNECTED,
    PHASE_MARKET_POLLERS_STARTED, PHASE_CONSUMERS_STARTED,
    PHASE_BOOTSTRAP_SCHEDULED, PHASE_FULL_READY,
)


class StartupReadiness:
    def __init__(self, publisher=None, *, redis_key: str = "talonx:ingest:startup", ttl_seconds: int = 3600) -> None:
        self._publisher = publisher
        self._redis_key = redis_key
        self._ttl = ttl_seconds
        self._marks: dict[str, str] = {}
        self.mark(PHASE_PROCESS_START)

    # -- state --------------------------------------------------------
    def mark(self, phase: str) -> None:
        if phase not in self._marks:
            self._marks[phase] = datetime.now(timezone.utc).isoformat()
            logger.info("Startup phase reached: %s", phase)

    @property
    def current_phase(self) -> str:
        reached = [p for p in _ORDER if p in self._marks]
        return reached[-1] if reached else PHASE_PROCESS_START

    def is_market_ready(self) -> bool:
        return PHASE_MARKET_POLLERS_STARTED in self._marks and PHASE_REDIS_CONNECTED in self._marks

    def is_full_ready(self) -> bool:
        return PHASE_FULL_READY in self._marks

    def snapshot(self) -> dict:
        return {
            "current_phase": self.current_phase,
            "market_ready": self.is_market_ready(),
            "full_ready": self.is_full_ready(),
            "phase_times": dict(self._marks),
        }

    # -- publish ----------------------------------------------------
    async def publish(self) -> None:
        if self._publisher is None:
            return
        try:
            client = getattr(self._publisher, "_client", None)
            if client is None:
                return
            await client.set(self._redis_key, json.dumps(self.snapshot()), ex=self._ttl)
        except Exception as exc:  # noqa: BLE001 -- readiness reporting must never break startup
            logger.debug("Startup readiness publish failed (non-fatal): %s", exc)


async def delayed_start(coro_factory, delay_seconds: float, *, name: str = "") -> None:
    """Await ``delay_seconds`` then run ``coro_factory()``. ``coro_factory``
    is a zero-arg callable returning the coroutine to run (so the
    coroutine object is not created -- and its resources not acquired --
    until the delay has elapsed)."""
    if delay_seconds > 0:
        logger.info("Deferring background task %s by %.1fs to ease startup contention", name or "<task>", delay_seconds)
        await asyncio.sleep(delay_seconds)
    await coro_factory()
