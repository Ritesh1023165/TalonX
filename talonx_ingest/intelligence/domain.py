"""
talonx_ingest.intelligence.domain
=================================
Canonical, immutable value objects for the event-intelligence layer.

``TextEvent``   -- one classified, causally-timestamped disclosure event,
                   traceable to its SEC source.
``AlertCard``   -- the delivery-facing contract for one event. 96A defines
                   the SCHEMA only; the significance band and rendered
                   summary are populated by later workstreams.

Hard rule (``PRODUCT_CLAIM_POLICY.md``): nothing in this module encodes a
prediction. There is no expected-return, alpha, direction, bullish/bearish,
probability-of-gain, recommendation, target or outlook field, and
``AlertCard`` actively rejects any such key in ``summary_fields``.
"""
from __future__ import annotations

from datetime import date, datetime, timezone
from enum import Enum

from pydantic import BaseModel, ConfigDict, field_validator

from talonx_ingest.intelligence.config import (
    ALERT_CARD_SCHEMA_VERSION,
    EVENT_SCHEMA_VERSION,
)

# ---------------------------------------------------------------------------
# Enums
# ---------------------------------------------------------------------------


class SourceType(str, Enum):
    """Origin of an event or a provenance record."""

    SEC_EDGAR_SUBMISSIONS = "SEC_EDGAR_SUBMISSIONS"
    SEC_EDGAR_ARCHIVES = "SEC_EDGAR_ARCHIVES"
    SEC_EDGAR_FULLTEXT_RSS = "SEC_EDGAR_FULLTEXT_RSS"
    SEC_XBRL = "SEC_XBRL"
    SEC_FORM345_BULK = "SEC_FORM345_BULK"
    ALPACA_SIP = "ALPACA_SIP"
    YFINANCE_CALENDAR = "YFINANCE_CALENDAR"


class EventType(str, Enum):
    """Deterministic, source-derived event classification. No predictive
    labels. Names follow the Task 96A Phase 3 implementation list; the
    mapping to the ``EVENT_TAXONOMY.md`` display names is recorded in
    ``results/task96a_event_domain/taxonomy_spec.md``."""

    # --- earnings ---------------------------------------------------------
    EARNINGS_RESULTS = "EARNINGS_RESULTS"            # 8-K item 2.02
    EARNINGS_EXPECTED = "EARNINGS_EXPECTED"          # scheduler heads-up (not built in 96A)

    # --- material 8-K items --------------------------------------------------
    MATERIAL_AGREEMENT = "MATERIAL_AGREEMENT"        # 1.01
    AGREEMENT_TERMINATED = "AGREEMENT_TERMINATED"    # 1.02
    ACQUISITION_DISPOSITION = "ACQUISITION_DISPOSITION"  # 2.01
    DEBT_FINANCING = "DEBT_FINANCING"                # 2.03
    RESTRUCTURING = "RESTRUCTURING"                  # 2.05
    EXECUTIVE_CHANGE = "EXECUTIVE_CHANGE"            # 5.02 (direction NOT inferred)
    REGULATION_FD = "REGULATION_FD"                  # 7.01
    OTHER_MATERIAL_EVENT = "OTHER_MATERIAL_EVENT"    # 8.01
    SHAREHOLDER_VOTE_RESULT = "SHAREHOLDER_VOTE_RESULT"  # 5.07
    CHARTER_BYLAW_AMENDMENT = "CHARTER_BYLAW_AMENDMENT"  # 5.03
    UNREGISTERED_EQUITY_SALE = "UNREGISTERED_EQUITY_SALE"  # 3.02
    MATERIAL_IMPAIRMENT = "MATERIAL_IMPAIRMENT"      # 2.06
    DELISTING_NOTICE = "DELISTING_NOTICE"            # 3.01

    # --- periodic --------------------------------------------------------
    QUARTERLY_FILING = "QUARTERLY_FILING"            # 10-Q
    ANNUAL_FILING = "ANNUAL_FILING"                  # 10-K

    # --- insider (enum reserved; pipeline is Task 96D) ------------------
    INSIDER_TRANSACTION = "INSIDER_TRANSACTION"

    # --- fallbacks (observable, never silently dropped) ----------------
    FILING_AMENDMENT = "FILING_AMENDMENT"            # an /A with no recognised item
    UNCLASSIFIED_8K = "UNCLASSIFIED_8K"              # 8-K whose items map to nothing known
    UNSUPPORTED_FORM = "UNSUPPORTED_FORM"            # a form the MVP does not classify


class SessionBucket(str, Enum):
    """US-equities session an event's ``accepted_at_utc`` falls in
    (America/New_York, DST- and NYSE-holiday-aware)."""

    BMO = "BMO"                        # before market open, < 09:30 ET on a trading day
    RTH = "RTH"                        # regular trading hours, 09:30-16:00 ET
    AMC = "AMC"                        # after market close, >= 16:00 ET (or after a half-day close)
    NON_TRADING_DAY = "NON_TRADING_DAY"  # weekend or NYSE holiday
    UNKNOWN = "UNKNOWN"               # no usable acceptance timestamp


class SignificanceBand(str, Enum):
    """Informational-priority band. 96A defines the enum only -- the
    deterministic point rules that assign it are Task 96E. Never a
    return-based or directional score."""

    LOW = "LOW"
    MEDIUM = "MEDIUM"
    HIGH = "HIGH"
    CRITICAL = "CRITICAL"


class FreshnessStatus(str, Enum):
    FRESH = "FRESH"
    STALE = "STALE"
    UNKNOWN = "UNKNOWN"
    DOWN = "DOWN"


class DataQualityFlag(str, Enum):
    """Deterministic quality markers. An event with any of these is still
    stored and observable."""

    MISSING_SYMBOL_MAPPING = "missing_symbol_mapping"
    MISSING_ACCEPTANCE_TIMESTAMP = "missing_acceptance_timestamp"
    MISSING_ITEM_METADATA = "missing_item_metadata"
    PRIMARY_DOCUMENT_UNAVAILABLE = "primary_document_unavailable"
    EXHIBIT_FETCH_FAILED = "exhibit_fetch_failed"
    AMENDMENT = "amendment"
    UNSUPPORTED_FORM = "unsupported_form"
    NON_STANDARD_ITEM_CODE = "non_standard_item_code"
    MULTI_ITEM_FILING = "multi_item_filing"
    AMBIGUOUS_SESSION_BUCKET = "ambiguous_session_bucket"
    SESSION_CALENDAR_UNAVAILABLE = "session_calendar_unavailable"
    MISSING_REPORT_PERIOD_END = "missing_report_period_end"


# Keys that must never appear on a card -- a predictive/directional claim.
_FORBIDDEN_CARD_KEYS: frozenset[str] = frozenset(
    {
        "recommendation", "action", "signal", "outlook", "target", "target_price",
        "direction", "probability", "expected_return", "forecast", "alpha",
        "opportunity_score", "edge", "conviction", "bullish", "bearish",
        "buy", "sell", "hold", "rating", "price_target", "upside", "downside",
    }
)


# ---------------------------------------------------------------------------
# Value objects
# ---------------------------------------------------------------------------

_FROZEN = ConfigDict(frozen=True, extra="forbid")


class EvidenceRecord(BaseModel):
    """Provenance for one derived value or classification decision
    (``EVIDENCE_TRACE_SPEC.md``). Immutable."""

    model_config = _FROZEN

    source_provider: SourceType
    source_record_id: str
    source_url: str | None = None
    exact_timestamp: datetime | None = None    # the causal instant of the source datum
    retrieved_at: datetime                     # when TalonX fetched it
    transform: str                             # "name@version", e.g. "session_bucket@v1"
    input_hash: str | None = None              # sha256, LF-normalised, of the transform input
    notes: str | None = None


class ExhibitRef(BaseModel):
    """One document attached to a filing (EX-99.1 press release, etc.)."""

    model_config = _FROZEN

    filename: str
    source_url: str
    sequence: int | None = None
    document_type: str | None = None           # SEC "Type", e.g. "EX-99.1", "8-K"
    description: str | None = None


class TextEvent(BaseModel):
    """One classified, causally-timestamped disclosure event.

    Identity is ``event_id`` (deterministic, restart-stable -- see
    ``identity.py``). A single filing with multiple material items produces
    multiple ``TextEvent`` rows, one per classified ``event_type``, all
    sharing ``accession``; every raw item code is preserved in
    ``filing_items`` and in the store's ``text_event_items`` table.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    # --- identity ------------------------------------------------------
    event_id: str
    schema_version: str = EVENT_SCHEMA_VERSION

    # --- subject -----------------------------------------------------
    symbol: str
    company_name: str

    # --- source / classification --------------------------------------
    source_type: SourceType
    source_record_id: str                       # == accession for EDGAR filings
    event_type: EventType
    form_type: str
    filing_items: tuple[str, ...] = ()
    accession: str

    # --- causal timing ----------------------------------------------
    accepted_at_utc: datetime | None            # EDGAR acceptanceDateTime -- the event instant
    filing_date: date | None = None             # display-only; never the event instant
    report_period_end: date | None = None
    session_bucket: SessionBucket = SessionBucket.UNKNOWN
    session_reason: str | None = None           # "weekend" / "nyse_holiday" / "half_day_amc" / ...

    # --- documents -------------------------------------------------
    primary_document: str | None = None
    primary_document_url: str | None = None
    filing_index_url: str | None = None
    exhibits: tuple[ExhibitRef, ...] = ()

    # --- amendment lineage ----------------------------------------
    is_amendment: bool = False
    amends_accession: str | None = None

    # --- provenance / bookkeeping -------------------------------
    source_hash: str | None = None              # hash of the normalised source record
    ingested_at_utc: datetime
    freshness: FreshnessStatus = FreshnessStatus.UNKNOWN
    data_quality_flags: tuple[str, ...] = ()
    evidence: tuple[EvidenceRecord, ...] = ()

    @field_validator("symbol")
    @classmethod
    def _upper_symbol(cls, v: str) -> str:
        return v.upper()

    @field_validator("accepted_at_utc", "filing_date", mode="before")
    @classmethod
    def _keep(cls, v):  # pragma: no cover - passthrough hook kept for clarity
        return v


class AlertCard(BaseModel):
    """Delivery-facing contract for one event. 96A: SCHEMA ONLY.

    ``significance`` / ``significance_reasons`` are left unset here -- the
    Information Significance engine (Task 96E) fills them. ``summary_fields``
    is a plain factual key/value map; a predictive or directional key is
    rejected at construction.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    alert_id: str
    event_id: str
    schema_version: str = ALERT_CARD_SCHEMA_VERSION

    symbol: str
    company_name: str
    title: str
    event_type: EventType

    significance: SignificanceBand | None = None
    significance_reasons: tuple[str, ...] = ()

    timestamp_utc: datetime | None = None
    session_bucket: SessionBucket = SessionBucket.UNKNOWN
    form_type: str = ""
    filing_items: tuple[str, ...] = ()

    summary_fields: dict[str, str] = {}
    evidence: tuple[EvidenceRecord, ...] = ()
    freshness: FreshnessStatus = FreshnessStatus.UNKNOWN
    data_quality_flags: tuple[str, ...] = ()
    source_url: str | None = None

    disclaimer: str = (
        "Information, not advice. TalonX makes no prediction about future price or returns."
    )
    status: str = "EMITTED"                     # EMITTED / CORRECTED_BY:<id> / SUPERSEDED_BY:<id>

    @field_validator("summary_fields")
    @classmethod
    def _no_predictive_keys(cls, v: dict[str, str]) -> dict[str, str]:
        bad = sorted(k for k in v if k.strip().lower() in _FORBIDDEN_CARD_KEYS)
        if bad:
            raise ValueError(
                f"AlertCard.summary_fields must not contain predictive/directional keys: {bad}"
            )
        return v

    @field_validator("significance_reasons")
    @classmethod
    def _reasons_present_if_banded(cls, v, info):
        return v


def utc_now() -> datetime:
    """Single source of 'now' for ingestion timestamps -- always tz-aware UTC."""
    return datetime.now(timezone.utc)
