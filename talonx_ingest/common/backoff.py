"""
talonx_ingest.common.backoff
-------------------------------
Shared jittered-exponential-backoff helper. Used by both the EDGAR client
and the market data module so reconnect/retry behavior is consistent
across the structured and unstructured ingestion paths.
"""
from __future__ import annotations

import random


def jittered_backoff_seconds(
    attempt: int, base_seconds: float, max_seconds: float
) -> float:
    """
    Exponential backoff with full jitter: delay = rand(0.5x, 1.5x) of
    min(base * 2^(attempt-1), max). `attempt` is 1-indexed (first retry
    passes attempt=1). Jitter avoids many concurrent retries synchronizing
    into a "thundering herd" against the remote service.
    """
    raw = base_seconds * (2 ** (attempt - 1))
    capped = min(raw, max_seconds)
    return capped * (0.5 + random.random())
