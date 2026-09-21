"""
talonx_ingest.intelligence.dashboard.config
===========================================
Frozen presentation constants for the Event-Intelligence Dashboard.
Nothing here is fitted to anything. Band icons / labels are re-used from
the Task 96F Telegram layer so the two surfaces speak the same
attention-priority language (no market direction).
"""
from __future__ import annotations

from talonx_ingest.intelligence.delivery.config import (
    BAND_ICON,
    BAND_LABEL,
    DISCLAIMER_SHORT,
    EVENT_TYPE_LABEL,
)
from talonx_ingest.intelligence.domain import SignificanceBand
from talonx_ingest.intelligence.significance.config import RULESET_VERSION

DASHBOARD_VERSION = "event-intelligence-dashboard-v1"

# ---------------------------------------------------------------------------
# navigation — the five pages of DASHBOARD_INFORMATION_ARCHITECTURE.md
# ---------------------------------------------------------------------------
NAV_PAGES: tuple[tuple[str, str], ...] = (
    ("today", "Today"),
    ("watchlist", "Watchlist"),
    ("filings", "Filings"),
    ("evidence", "Evidence"),
)
#: "Company" is reachable only via a symbol; it is not a top-nav item.

# ---------------------------------------------------------------------------
# pagination — deterministic, bounded
# ---------------------------------------------------------------------------
PAGE_SIZE_DEFAULT = 25
PAGE_SIZE_MAX = 100
TODAY_FEED_LIMIT = 40
TODAY_PANEL_LIMIT = 10
COMPANY_TIMELINE_LIMIT = 40
WATCHLIST_TRAILING_DAYS = 7

# ---------------------------------------------------------------------------
# "today" window — trailing hours counted as "today" for the feed
# ---------------------------------------------------------------------------
TODAY_WINDOW_HOURS = 36

# ---------------------------------------------------------------------------
# timezone display — source truth is UTC; UI also shows US/Eastern.
# ---------------------------------------------------------------------------
DISPLAY_TZ_NAME = "America/New_York"
DISPLAY_TZ_LABEL = "ET"

# ---------------------------------------------------------------------------
# band presentation (re-exported from 96F)
# ---------------------------------------------------------------------------
BAND_ICON = BAND_ICON
BAND_LABEL = BAND_LABEL
EVENT_TYPE_LABEL = EVENT_TYPE_LABEL
DISCLAIMER_SHORT = DISCLAIMER_SHORT

SIGNIFICANCE_HELP = (
    "Information Significance ranks how much changed and how unusual it is for this "
    "company — i.e. what may be worth a human look first. It is NOT a prediction of "
    "price or return, not a buy/sell signal, and not a confidence score."
)

BAND_ORDER: dict[SignificanceBand, int] = {
    SignificanceBand.CRITICAL: 0,
    SignificanceBand.HIGH: 1,
    SignificanceBand.MEDIUM: 2,
    SignificanceBand.LOW: 3,
}

# ---------------------------------------------------------------------------
# friendly wording for data-quality flags (Phase 14)
# ---------------------------------------------------------------------------
QUALITY_FLAG_LABEL: dict[str, str] = {
    "missing_acceptance_timestamp": "SEC acceptance time missing — causal timing is approximate",
    "primary_document_unavailable": "primary filing document could not be fetched",
    "ambiguous_session_bucket": "market session at acceptance time is ambiguous",
    "session_calendar_unavailable": "exchange calendar unavailable — session is approximate",
    "missing_item_metadata": "8-K item codes were not listed by SEC",
    "multi_item_filing": "filing carries several material items",
    "amendment": "this is an amendment / correction of a prior filing",
    "non_standard_item_code": "filing contains an item code outside the standard set",
    "missing_prior_filing": "no prior comparable filing found — change vs prior not computed",
    "prior_is_first_filing": "prior filing is the company's first of this type",
    "section_not_found": "a section could not be located in one of the filings",
    "ambiguous_section": "a section heading matched more than once",
    "xbrl_unavailable": "XBRL financial data was unavailable",
    "xbrl_concept_missing": "an XBRL concept was not reported",
    "current_document_unavailable": "the current filing document could not be fetched",
    "prior_document_unavailable": "the prior filing document could not be fetched",
    "low_quality_comparison": "filing comparison is low-confidence",
    "prior_form_mismatch": "prior filing is a different form type",
    "unknown_transaction_code": "an insider transaction code was not recognised",
    "role_unresolved": "an insider's role could not be resolved from the filing",
    "missing_price": "an insider transaction had no reported price",
    "missing_shares": "an insider transaction had no reported share count",
    "missing_transaction_date": "an insider transaction had no reported date",
    "symbol_unresolved": "the issuer ticker could not be resolved",
    "source_stale": "the SEC source feed was stale at load time",
    "source_down": "the SEC source feed was down at load time",
    "rarity_insufficient_history": "not enough tracked history to assess how unusual this is",
}


def friendly_quality_flag(flag: str) -> str:
    return QUALITY_FLAG_LABEL.get(flag, flag.replace("_", " "))


# ---------------------------------------------------------------------------
# Evidence page content (Phase 10) — factual status, no logs
# ---------------------------------------------------------------------------
EVIDENCE_STATEMENTS: tuple[str, ...] = (
    "Autonomous alpha research is CLOSED under the current mandate "
    "(Tasks 93–95I: eight hypothesis spaces tested, no free causal long-only edge found).",
    "Predictive risk filtering is CLOSED (Task 95K: the deterministic negative signals did "
    "not improve an independently-selected long book and did not identify the bad-outcome "
    "population).",
    "There is no validated free causal long-only alpha. The signed information TalonX can "
    "extract deterministically from free sources is descriptive event / risk information, "
    "not a return prediction.",
    "The current product is a descriptive, human-in-the-loop event and risk intelligence "
    "system. It detects, classifies, causally-timestamps and explains SEC filings, earnings "
    "and insider activity for a watchlist, and ranks them for human attention.",
)
EVIDENCE_ARTIFACT_LINKS: tuple[tuple[str, str], ...] = (
    ("Alpha program review (Task 95J)", "results/task95j_alpha_program_review/"),
    ("Risk-filter research (Task 95K)", "results/task95k_risk_filter/"),
    ("Product design (Task 96)", "results/task96_decision_support_design/"),
    ("Information Significance engine (Task 96E)", "results/task96e_information_significance/"),
)
DATA_SOURCES: tuple[str, ...] = (
    "SEC EDGAR submissions + Archives (8-K / 10-Q / 10-K, acceptanceDateTime)",
    "SEC XBRL company-concept facts (first-filed only)",
    "SEC Form 3/4/5 ownership filings (quarterly bulk + per-filing XML)",
)
EVIDENCE_PHILOSOPHY = (
    "Every surfaced value carries its source (provider, accession, exact timestamp, "
    "transform + version) and a data-quality flag when an input was missing. Nothing is "
    "interpolated; a missing input is shown as unavailable. Corrections are additive — a "
    "corrected value is a new record citing the old, never a silent overwrite."
)

CLAIM_POLICY_SHORT = (
    "TalonX shows what changed and where the evidence is. It does not tell you what to buy "
    "or sell, and it makes no claim to predict returns. No page uses the words buy, sell, "
    "target, outlook, recommendation, or probability of return."
)
