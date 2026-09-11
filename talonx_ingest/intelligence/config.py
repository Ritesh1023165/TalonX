"""
talonx_ingest.intelligence.config
=================================
Static configuration for the event-intelligence foundation: transform
version identifiers (for the evidence trace), the set of SEC forms the
MVP classifies, and per-source data-freshness thresholds.

Everything here is a fixed constant, not a tunable knob. A transform
version bump is a deliberate, reviewed change that re-stamps affected
evidence records (``EVIDENCE_TRACE_SPEC.md`` rule 2).
"""
from __future__ import annotations

from dataclasses import dataclass

# ---------------------------------------------------------------------------
# Transform version identifiers -- every derived value names the transform
# (name@version) that produced it, so a card can be recomputed byte-for-byte.
# ---------------------------------------------------------------------------
EVENT_SCHEMA_VERSION = "text_event@v1"
ALERT_CARD_SCHEMA_VERSION = "alert_card@v1"
EVENT_STORE_SCHEMA_VERSION = 1

TAXONOMY_TRANSFORM = "edgar_taxonomy@v1"
SESSION_BUCKET_TRANSFORM = "session_bucket@v1"
EDGAR_NORMALIZE_TRANSFORM = "edgar_submission_normalize@v1"
EVENT_IDENTITY_TRANSFORM = "event_identity@v1"
SOURCE_HASH_TRANSFORM = "sha256_lf_normalized@v1"

# ---------------------------------------------------------------------------
# Forms the MVP classifies. Anything else is stored as UNSUPPORTED_FORM with
# a data-quality flag -- observable, never silently dropped.
# ---------------------------------------------------------------------------
SUPPORTED_FORMS: frozenset[str] = frozenset(
    {"8-K", "8-K/A", "10-Q", "10-Q/A", "10-K", "10-K/A"}
)

# Reserved: 96A defines the enum member and store support for insider events
# but does not run a Form 3/4/5 pipeline (that is Task 96D).
INSIDER_FORMS: frozenset[str] = frozenset({"3", "4", "5", "3/A", "4/A", "5/A"})


# ---------------------------------------------------------------------------
# Data freshness -- per source. FRESH/STALE come from how long ago the last
# *successful poll* was (NOT from whether a new event arrived: EDGAR
# legitimately has quiet periods). DOWN comes from consecutive poll
# failures. Mirrors DATA_FRESHNESS_SPEC.md and the Task 87B liveness rule.
# ---------------------------------------------------------------------------
@dataclass(frozen=True)
class FreshnessThresholds:
    """Seconds since last successful poll before a source is STALE, split by
    US market session (``day`` = pre-market through after-hours, ``night`` =
    overnight / weekend when EDGAR itself is quiet). ``down_after_failures``
    consecutive failed poll attempts force DOWN regardless of recency."""

    stale_after_seconds_day: int
    stale_after_seconds_night: int
    down_after_failures: int = 3


FRESHNESS_THRESHOLDS: dict[str, FreshnessThresholds] = {
    # values from DATA_FRESHNESS_SPEC.md
    "SEC_EDGAR_SUBMISSIONS": FreshnessThresholds(
        stale_after_seconds_day=30 * 60, stale_after_seconds_night=3 * 60 * 60
    ),
    "SEC_EDGAR_FULLTEXT_RSS": FreshnessThresholds(
        stale_after_seconds_day=30 * 60, stale_after_seconds_night=30 * 60
    ),
    "SEC_XBRL": FreshnessThresholds(
        stale_after_seconds_day=24 * 60 * 60, stale_after_seconds_night=24 * 60 * 60
    ),
    "SEC_FORM345_BULK": FreshnessThresholds(
        stale_after_seconds_day=3 * 60 * 60, stale_after_seconds_night=6 * 60 * 60
    ),
    "ALPACA_SIP": FreshnessThresholds(
        stale_after_seconds_day=10 * 60, stale_after_seconds_night=24 * 60 * 60
    ),
    "YFINANCE_CALENDAR": FreshnessThresholds(
        stale_after_seconds_day=26 * 60 * 60, stale_after_seconds_night=48 * 60 * 60
    ),
}

DEFAULT_FRESHNESS = FreshnessThresholds(
    stale_after_seconds_day=60 * 60, stale_after_seconds_night=6 * 60 * 60
)
