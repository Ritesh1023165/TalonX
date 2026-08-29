"""Task 83 -- read-only Original/PIV comparison layer.

This package is a PASSIVE OBSERVER. It never publishes to, acknowledges,
suppresses, deduplicates, or otherwise mutates either the Original pipeline
(Redis DB 0, ``talonx:*`` channels) or the PIV validation runtime (Redis
DB 1, ``talonx:piv:*`` channels). It owns its own namespace, cursors,
deduplication index, and date-partitioned evidence store, and reuses none
of Original's or PIV's locks, cooldowns, metrics keys, state files, or
session identifiers.

Operational agreement measured here is NOT alpha or profitability evidence
(see ``divergence.py`` and every emitted manifest). Strategy status is
UNVALIDATED; profitability is UNDETERMINED.
"""

from .config import CompareConfig
from .health import (
    DEGRADED,
    DISCONNECTED,
    HEALTHY,
    MISSING,
    NOT_RUN,
    RUNNING,
    STALE,
    UNREADABLE,
    WRONG_SESSION,
    HEALTH_STATES,
)

__all__ = [
    "CompareConfig",
    "HEALTH_STATES",
    "RUNNING",
    "HEALTHY",
    "DEGRADED",
    "STALE",
    "MISSING",
    "DISCONNECTED",
    "NOT_RUN",
    "UNREADABLE",
    "WRONG_SESSION",
]
