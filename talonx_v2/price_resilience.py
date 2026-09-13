"""
talonx_v2.price_resilience -- Task 131 Directive 3: bounded, idempotent
retry for a missing market-data bar at the moment of an entry/exit price
lookup.

A missing bar at the EXACT open/close is treated as a possibly-transient
data-provider gap (a brief feed-publish delay right at the open) -- not
immediately a terminal failure. This polls the SAME underlying price
lookup for up to ``max_wait_seconds`` (default 300s / 5 minutes),
sleeping ``poll_interval_seconds`` between attempts (default 15s), and
returns the first available price. If the bounded window is exhausted
with no price ever observed, the caller releases the intent with an
explicit ``FAILED_NO_MARKET_DATA`` terminal state -- never a
substituted, invented, current, or later price.

Fully dependency-injected (``sleep_fn``/``time_fn``) so tests exercise a
full bounded-retry-then-timeout cycle in milliseconds, not minutes.
Applied ONLY to true live ticks (``as_of is None``) -- a pinned replay/
dry-run tick has a simulated clock, not a real one, so "waiting" inside
it would be both meaningless and slow (talonx_v2.service._resilient_price_lookup
is the sole caller and already enforces this distinction).
"""
from __future__ import annotations

import logging
import time as _time_module
from dataclasses import dataclass
from typing import Callable

logger = logging.getLogger("talonx_v2.price_resilience")

DEFAULT_MAX_WAIT_SECONDS = 300.0
DEFAULT_POLL_INTERVAL_SECONDS = 15.0


@dataclass
class RetryOutcome:
    price: dict | None
    attempts: int
    elapsed_seconds: float
    succeeded: bool


def fetch_price_with_bounded_retry(
    fetch: Callable[[], dict | None],
    *,
    max_wait_seconds: float = DEFAULT_MAX_WAIT_SECONDS,
    poll_interval_seconds: float = DEFAULT_POLL_INTERVAL_SECONDS,
    sleep_fn: Callable[[float], None] = _time_module.sleep,
    time_fn: Callable[[], float] = _time_module.monotonic,
    context: str = "",
) -> RetryOutcome:
    """Calls ``fetch()`` repeatedly until it returns a truthy price dict
    (one containing a usable 'open' or 'close' value) or the bounded
    window elapses. Never fabricates a price -- only ever returns
    exactly what ``fetch()`` itself returned, or None. The FIRST call is
    always attempted immediately (no pre-sleep), so a price that is
    already available costs nothing extra."""
    if max_wait_seconds < 0 or poll_interval_seconds <= 0:
        raise ValueError("max_wait_seconds must be >= 0 and poll_interval_seconds > 0")
    start = time_fn()
    attempts = 0
    while True:
        attempts += 1
        price = fetch()
        if price:
            return RetryOutcome(price=price, attempts=attempts,
                                elapsed_seconds=time_fn() - start, succeeded=True)
        elapsed = time_fn() - start
        if elapsed >= max_wait_seconds:
            logger.warning("bounded price retry exhausted context=%s attempts=%d elapsed=%.1fs",
                          context, attempts, elapsed)
            return RetryOutcome(price=None, attempts=attempts, elapsed_seconds=elapsed, succeeded=False)
        remaining = max_wait_seconds - elapsed
        sleep_fn(min(poll_interval_seconds, remaining))
