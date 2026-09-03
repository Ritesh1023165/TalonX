"""
talonx_ingest.intelligence.delivery.config
==========================================
Frozen constants for Telegram intelligence delivery. Nothing here is a
tunable knob fitted to anything — the disclaimer text is copied verbatim
from ``PRODUCT_CLAIM_POLICY.md``, the band icons encode **attention
priority only** (no market direction), the size budget mirrors Telegram's
documented limits.
"""
from __future__ import annotations

from talonx_ingest.intelligence.domain import EventType, SignificanceBand

# ---------------------------------------------------------------------------
# versions
# ---------------------------------------------------------------------------
#: bump when the RENDERED text layout changes in a way that should mark
#: previously-sent alerts as a different render (see identity.delivery_id).
#: A render-version bump must NOT auto-resend old alerts (TELEGRAM_UPDATE_POLICY).
RENDER_VERSION = "telegram-intel-v1"
DELIVERY_STORE_SCHEMA_VERSION = 1

RENDER_TRANSFORM = "telegram_intel_render@v1"

# ---------------------------------------------------------------------------
# transport
# ---------------------------------------------------------------------------
PARSE_MODE = "HTML"                       # robust escaping is just & < > ; avoids MarkdownV2 minefield
DISABLE_WEB_PAGE_PREVIEW = True
DELIVERY_CHANNEL = "telegram"            # the channel component of delivery_id

# ---------------------------------------------------------------------------
# message tiers
# ---------------------------------------------------------------------------
TIER_COMPACT = "COMPACT"
TIER_EXPANDED = "EXPANDED"
TIER_DIGEST = "DIGEST"

#: bands rendered EXPANDED by default (HIGH/CRITICAL); others render COMPACT.
EXPANDED_BANDS: frozenset[SignificanceBand] = frozenset(
    {SignificanceBand.HIGH, SignificanceBand.CRITICAL}
)

# ---------------------------------------------------------------------------
# delivery priority / routing (attention order ONLY — never direction)
# ---------------------------------------------------------------------------
#: bands delivered immediately; others are queued for the next digest
#: (TELEGRAM_ALERT_DESIGN.md "LOW/MEDIUM held for the digest; HIGH/CRITICAL
#: go immediately"). MVP-approved default.
IMMEDIATE_MIN_BAND: SignificanceBand = SignificanceBand.HIGH

ROUTE_IMMEDIATE = "IMMEDIATE"
ROUTE_DIGEST = "DIGEST"

#: strict delivery ordering when draining the outbox — CRITICAL first.
BAND_DELIVERY_ORDER: dict[SignificanceBand, int] = {
    SignificanceBand.CRITICAL: 0,
    SignificanceBand.HIGH: 1,
    SignificanceBand.MEDIUM: 2,
    SignificanceBand.LOW: 3,
}

_BAND_RANK: dict[SignificanceBand, int] = {
    SignificanceBand.LOW: 0,
    SignificanceBand.MEDIUM: 1,
    SignificanceBand.HIGH: 2,
    SignificanceBand.CRITICAL: 3,
}


def is_immediate(band: SignificanceBand) -> bool:
    return _BAND_RANK[band] >= _BAND_RANK[IMMEDIATE_MIN_BAND]


# ---------------------------------------------------------------------------
# band presentation — PRIORITY ICONS ONLY. Not red=bad / green=good; these
# are attention markers. LOW..CRITICAL.
# ---------------------------------------------------------------------------
BAND_ICON: dict[SignificanceBand, str] = {
    SignificanceBand.LOW: "⚪",        # white circle
    SignificanceBand.MEDIUM: "\U0001f7e1",  # yellow circle
    SignificanceBand.HIGH: "\U0001f7e0",   # orange circle
    SignificanceBand.CRITICAL: "\U0001f534",  # red circle (priority, not "bad")
}
BAND_LABEL: dict[SignificanceBand, str] = {
    SignificanceBand.LOW: "LOW INFORMATION SIGNIFICANCE",
    SignificanceBand.MEDIUM: "MEDIUM INFORMATION SIGNIFICANCE",
    SignificanceBand.HIGH: "HIGH INFORMATION SIGNIFICANCE",
    SignificanceBand.CRITICAL: "CRITICAL INFORMATION SIGNIFICANCE",
}

# ---------------------------------------------------------------------------
# event-type human labels (deterministic, factual — no outcome adjective)
# ---------------------------------------------------------------------------
EVENT_TYPE_LABEL: dict[EventType, str] = {
    EventType.EARNINGS_RESULTS: "Earnings / results (8-K Item 2.02)",
    EventType.EARNINGS_EXPECTED: "Expected earnings date (unconfirmed)",
    EventType.MATERIAL_AGREEMENT: "Material definitive agreement (8-K Item 1.01)",
    EventType.AGREEMENT_TERMINATED: "Material agreement terminated (8-K Item 1.02)",
    EventType.ACQUISITION_DISPOSITION: "Acquisition / disposition of assets (8-K Item 2.01)",
    EventType.DEBT_FINANCING: "Direct financial obligation (8-K Item 2.03/2.04)",
    EventType.RESTRUCTURING: "Exit / disposal (restructuring) costs (8-K Item 2.05)",
    EventType.MATERIAL_IMPAIRMENT: "Material impairment (8-K Item 2.06)",
    EventType.EXECUTIVE_CHANGE: "Director / officer change (8-K Item 5.02)",
    EventType.REGULATION_FD: "Regulation FD disclosure (8-K Item 7.01)",
    EventType.OTHER_MATERIAL_EVENT: "Other material event (8-K Item 8.01)",
    EventType.SHAREHOLDER_VOTE_RESULT: "Shareholder vote results (8-K Item 5.07)",
    EventType.CHARTER_BYLAW_AMENDMENT: "Charter / bylaw amendment (8-K Item 5.03)",
    EventType.UNREGISTERED_EQUITY_SALE: "Unregistered sale of equity (8-K Item 3.02)",
    EventType.DELISTING_NOTICE: "Delisting / listing-transfer notice (8-K Item 3.01)",
    EventType.QUARTERLY_FILING: "Quarterly report (Form 10-Q)",
    EventType.ANNUAL_FILING: "Annual report (Form 10-K)",
    EventType.INSIDER_TRANSACTION: "Insider ownership filing (Form 3/4/5)",
    EventType.FILING_AMENDMENT: "Amendment to a prior filing",
    EventType.UNCLASSIFIED_8K: "8-K (items not individually classified)",
    EventType.UNSUPPORTED_FORM: "Filing outside the current coverage set",
}

# ---------------------------------------------------------------------------
# disclaimer — VERBATIM from PRODUCT_CLAIM_POLICY.md (short form)
# ---------------------------------------------------------------------------
DISCLAIMER_SHORT = (
    "Information, not advice. TalonX makes no prediction about future price or returns."
)

# ---------------------------------------------------------------------------
# size budget. Telegram hard limit is 4096 UTF-16 code units; keep well
# under it and truncate deterministically (TELEGRAM_SIZE_POLICY.md).
# ---------------------------------------------------------------------------
TELEGRAM_HARD_LIMIT = 4096
MESSAGE_BUDGET = 3500                    # our own ceiling; leaves headroom for entities
COMPACT_TARGET = 900

#: section priority when trimming to fit (keep earlier, drop later).
SECTION_PRIORITY: tuple[str, ...] = (
    "identity",          # band + symbol + company + session
    "event",             # event-type line + what happened
    "reasons",           # top significance reasons
    "facts",             # what_changed / XBRL / insider facts
    "quality",           # freshness / data-quality
    "evidence",          # source links
    "disclaimer",        # standing disclaimer (never dropped — appended last, always kept)
)
MAX_REASONS_COMPACT = 2
MAX_REASONS_EXPANDED = 4
MAX_FACTS_EXPANDED = 8
MAX_EVIDENCE_LINKS = 4
MAX_DIGEST_ROWS = 30

# ---------------------------------------------------------------------------
# retry / rate-limit (drain loop). The per-send retry is inside
# talonx_dispatch.TelegramClient; this governs the OUTBOX drain.
# ---------------------------------------------------------------------------
MAX_SEND_ATTEMPTS = 5                    # outbox row is FAILED (terminal) after this many
RETRY_BASE_SECONDS = 2.0
RETRY_MAX_SECONDS = 300.0
