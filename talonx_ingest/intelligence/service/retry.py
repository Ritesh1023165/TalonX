"""
talonx_ingest.intelligence.service.retry
========================================
Retryable-vs-terminal classification (``INGEST_RETRY_POLICY.md``).

RETRYABLE  — a transient condition that a later attempt can clear:
  * SEC HTTP 429 / 503 / 502 / 504 / other 5xx
  * connection reset / timeout / DNS blip
  * "document temporarily unavailable"
  * SQLite "database is locked" / "database is busy"

TERMINAL   — a data-quality / structural condition retrying will not fix:
  * an unsupported form
  * a filing document that stays malformed after repeated retrieval
  * an irreconcilable symbol -> CIK mapping
  * a permanently-missing prior filing (no comparable exists)

Terminal items are recorded with a reason and stay observable (Phase 17);
they are never silently dropped and never retried on a fixed schedule.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from enum import Enum

_RETRYABLE_SUBSTRINGS = (
    "429",
    "too many requests",
    "timeout",
    "timed out",
    "temporarily unavailable",
    "connection reset",
    "connection aborted",
    "connection refused",
    "database is locked",
    "database is busy",
    "server disconnected",
    "bad gateway",
    "service unavailable",
    "gateway timeout",
    "exhausted",           # EdgarClient "Exhausted N retries" — transport gave up, try later
)

_TERMINAL_SUBSTRINGS = (
    "unsupported form",
    "not found in sec ticker map",
    "no comparable prior filing",
    "malformed",
    "unparseable",
    "no primary_document_url",
    "accessionformaterror",
)

_5XX = re.compile(r"\b5\d\d\b")
_4XX_NON_429 = re.compile(r"\b4(?!29)\d\d\b")


class RetryClass(str, Enum):
    RETRYABLE = "RETRYABLE"
    TERMINAL = "TERMINAL"


@dataclass(frozen=True)
class RetryDecision:
    cls: RetryClass
    reason: str

    @property
    def retryable(self) -> bool:
        return self.cls is RetryClass.RETRYABLE


def classify_error(exc: BaseException | str) -> RetryDecision:
    text = (exc if isinstance(exc, str) else f"{type(exc).__name__}: {exc}").lower()

    for s in _TERMINAL_SUBSTRINGS:
        if s in text:
            return RetryDecision(RetryClass.TERMINAL, f"matched terminal marker {s!r}")

    for s in _RETRYABLE_SUBSTRINGS:
        if s in text:
            return RetryDecision(RetryClass.RETRYABLE, f"matched transient marker {s!r}")

    if _5XX.search(text):
        return RetryDecision(RetryClass.RETRYABLE, "5xx status")
    if "403" in text:
        # a 403 from SEC is usually a User-Agent problem — operator must fix,
        # but a later attempt after they do will succeed, so: retryable-slow.
        return RetryDecision(RetryClass.RETRYABLE, "403 (likely User-Agent) — retry after operator fix")
    if "404" in text:
        return RetryDecision(RetryClass.TERMINAL, "404 — resource does not exist")
    if _4XX_NON_429.search(text):
        return RetryDecision(RetryClass.TERMINAL, "4xx (non-429) status")

    # Unknown errors: retry a bounded number of times rather than silently drop.
    return RetryDecision(RetryClass.RETRYABLE, "unclassified error — bounded retry")


def backoff_seconds(attempt: int, *, base: float = 30.0, cap: float = 3600.0) -> float:
    """Exponential, capped. ``attempt`` is 1-based."""
    return min(cap, base * (2 ** max(0, attempt - 1)))
