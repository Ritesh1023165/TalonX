"""
talonx_ingest.intelligence.significance.config
==============================================
Frozen constants for the Information Significance Engine.

**Nothing here is a live tunable.** The event-type weights and the banding
come straight from ``results/task96_decision_support_design/INFORMATION_SIGNIFICANCE_SPEC.md``
(the binding design). The change-magnitude thresholds are percentiles of
the Task 95I filing-diff distribution
(``results/task95i_filing_alpha/_events/text_features.parquet``) — computed
**once**, pinned here, never recomputed live, and independent of any
return / P&L history. A weight change is a documented ``RULESET_VERSION``
bump, reviewed, never fitted to outcomes.
"""
from __future__ import annotations

from talonx_ingest.intelligence.comparison.config import (
    MATERIAL_CHANGE_THRESHOLDS,  # tercile boundary, frozen from 95I (reused verbatim)
)
from talonx_ingest.intelligence.domain import EventType, SignificanceBand

# ---------------------------------------------------------------------------
# schema / ruleset versions
# ---------------------------------------------------------------------------
SIGNIFICANCE_SCHEMA_VERSION = "information_significance@v1"
SIGNIFICANCE_STORE_SCHEMA_VERSION = 1

#: Frozen ruleset identity. Every stored score records this. A change to any
#: weight, cap, threshold or band rule in this file REQUIRES bumping this
#: string — old scores keep their id, re-computed scores get a new id, and
#: ``recompute.needs_recompute`` treats the mismatch as an invalidation.
RULESET_VERSION = "information-significance-v1"

EVALUATE_TRANSFORM = "information_significance_evaluate@v1"
FINGERPRINT_TRANSFORM = "significance_input_fingerprint@v1"

# ---------------------------------------------------------------------------
# Phase 4 — event-type base significance (INFORMATION_SIGNIFICANCE_SPEC.md row 1)
# "material / rare disclosures warrant a look". No direction is implied — a
# hire and a departure (both item 5.02) score the same.
# ---------------------------------------------------------------------------
EVENT_TYPE_BASE_POINTS: dict[EventType, int] = {
    # --- rare / structural 8-K items -> +3 -------------------------------
    EventType.ACQUISITION_DISPOSITION: 3,   # 8-K 2.01
    EventType.RESTRUCTURING: 3,             # 8-K 2.05
    EventType.MATERIAL_IMPAIRMENT: 3,       # 8-K 2.06
    EventType.DELISTING_NOTICE: 3,          # 8-K 3.01
    # --- material 8-K items -> +2 --------------------------------------
    EventType.EARNINGS_RESULTS: 2,          # 8-K 2.02
    EventType.MATERIAL_AGREEMENT: 2,        # 8-K 1.01
    EventType.AGREEMENT_TERMINATED: 2,      # 8-K 1.02
    EventType.DEBT_FINANCING: 2,            # 8-K 2.03 / 2.04
    EventType.EXECUTIVE_CHANGE: 2,          # 8-K 5.02
    EventType.REGULATION_FD: 2,             # 8-K 7.01
    # --- lower / informational 8-K items -> +1 -----------------------
    EventType.OTHER_MATERIAL_EVENT: 1,     # 8-K 8.01 (+ 1.03/3.03/4.01/4.02/5.01)
    EventType.UNREGISTERED_EQUITY_SALE: 1,  # 8-K 3.02
    EventType.UNCLASSIFIED_8K: 1,
    EventType.FILING_AMENDMENT: 1,          # a correction to a prior filing
    # --- routine 8-K items -> 0 -------------------------------------
    EventType.SHAREHOLDER_VOTE_RESULT: 0,   # 8-K 5.07
    EventType.CHARTER_BYLAW_AMENDMENT: 0,   # 8-K 5.03
    # --- periodic filings ------------------------------------------
    EventType.ANNUAL_FILING: 2,            # 10-K
    EventType.QUARTERLY_FILING: 1,         # 10-Q
    # --- insider (only scores when open-market P/S activity is present) --
    EventType.INSIDER_TRANSACTION: 1,
    # --- everything else --------------------------------------------
    EventType.EARNINGS_EXPECTED: 0,
    EventType.UNSUPPORTED_FORM: 0,
}
EVENT_TYPE_BASE_DEFAULT = 0

#: raw 8-K item codes that lift the base to +3 regardless of the mapped
#: event_type (rare, structural disclosures). Item 1.05 = material
#: cybersecurity incident (SEC 2023 rule) — not in the 96A item map.
HIGH_BASE_RAW_ITEMS: frozenset[str] = frozenset({"1.05", "2.01", "2.05", "2.06", "3.01"})

#: 8-K item codes that never count as a "material item" for the multi-item
#: rule (exhibit carriers / pure administrative).
NON_MATERIAL_ITEMS: frozenset[str] = frozenset({"9.01"})

EVENT_TYPE_BASE_CAP = 3

# ---------------------------------------------------------------------------
# Phase 5 — multi-item filing contribution (spec row 3)
# ---------------------------------------------------------------------------
MULTI_ITEM_MIN_COUNT = 3            # >= 3 distinct material items in one 8-K
MULTI_ITEM_POINTS = 1
MULTI_ITEM_CAP = 1

# ---------------------------------------------------------------------------
# Phase 6 — filing-change magnitude (spec row 4). Per section: diff_ratio at
# or above the DECILE boundary -> +2, at or above the TERCILE boundary ->
# +1. Whole-document change contributes at most +1 inside the same cap.
# NEW_MATERIAL_PASSAGES and a large negative-risk keyword swing each add +1
# inside the cap.
#
# TERCILE boundary: reused verbatim from Task 96C MATERIAL_CHANGE_THRESHOLDS.
# DECILE boundary: p90 of the same Task 95I distribution
#   (text_features.parquet, positive values), computed once 2026-09-03:
#     whole_document 0.2239 | risk_factors 0.6466 | mdna 0.2934 | liquidity 0.3113
# ---------------------------------------------------------------------------
TERCILE_CHANGE_THRESHOLDS: dict[str, float] = dict(MATERIAL_CHANGE_THRESHOLDS)
DECILE_CHANGE_THRESHOLDS: dict[str, float] = {
    "whole_document": 0.2239,
    "risk_factors": 0.6466,
    "mdna": 0.2934,
    "liquidity": 0.3113,
}
CHANGE_THRESHOLD_PROVENANCE = (
    "tercile = Task 96C MATERIAL_CHANGE_THRESHOLDS (frozen from "
    "task95i_filing_alpha/_events/text_features.parquet); decile = p90 of the same "
    "distribution (positive values), computed once 2026-09-03; returns-free"
)
FILING_CHANGE_SECTION_KEYS = ("risk_factors", "mdna", "liquidity")
FILING_CHANGE_DECILE_POINTS = 2
FILING_CHANGE_TERCILE_POINTS = 1
FILING_CHANGE_WHOLE_DOC_POINTS = 1
NEW_MATERIAL_PASSAGES_POINTS = 1
FILING_CHANGE_CAP = 3

#: net increase in the frozen negative-risk lexicon count (96C
#: keyword_category_summaries total_delta) at or above this -> +1. p90 of
#: the Task 95I neg_kw_delta distribution (= 15), computed once 2026-09-03.
NEGATIVE_RISK_KEYWORD_DELTA_THRESHOLD = 15
RISK_LANGUAGE_POINTS = 1
RISK_LANGUAGE_CAP = 1

# ---------------------------------------------------------------------------
# Phase 7 — XBRL fundamental magnitude (spec row 6). ABSOLUTE value of the
# first-filed relative delta only — +40% and -40% score identically. Frozen
# absolute bands (interpretable, not fitted to any return history). The
# design's "top decile of the issuer's history" phrasing is realised as a
# fixed band because no returns-free per-issuer XBRL-delta history store
# exists yet; a fixed band is the conservative, deterministic stand-in.
# ---------------------------------------------------------------------------
XBRL_MAGNITUDE_FIELDS = ("revenue", "eps_diluted")
XBRL_DECILE_ABS_RELATIVE_DELTA = 0.50    # |rel delta| >= 0.50 -> +2
XBRL_TERCILE_ABS_RELATIVE_DELTA = 0.20   # |rel delta| >= 0.20 -> +1
XBRL_DECILE_POINTS = 2
XBRL_TERCILE_POINTS = 1
XBRL_CAP = 2

# ---------------------------------------------------------------------------
# Phase 8 — insider activity (spec row 7). Purchase and sale are the same
# for significance — neither is translated into a bullish/bearish meaning.
# ---------------------------------------------------------------------------
INSIDER_LARGE_TRANSACTION_USD = 1_000_000.0    # frozen $ band, single open-market P/S txn
INSIDER_LARGE_TRANSACTION_POINTS = 1
INSIDER_CLUSTER_POINTS = 2                      # MULTIPLE_OPEN_MARKET_BUYERS / SELLERS
INSIDER_CAP = 3

# ---------------------------------------------------------------------------
# Phase 9 — event rarity for this filer (spec row 2). Metadata only:
# how long since this issuer last filed an event of the same type.
# ---------------------------------------------------------------------------
RARITY_ABSENT_MONTHS_RARE = 24        # not seen in 24 months -> +2 (RARE)
RARITY_ABSENT_MONTHS_UNCOMMON = 12    # not seen in 12 months -> +1 (UNCOMMON)
RARITY_RARE_POINTS = 2
RARITY_UNCOMMON_POINTS = 1
RARITY_CAP = 2
#: if the event store holds no event for this symbol older than this many
#: months before the event, rarity is scored 0 (insufficient history —
#: avoids a tiny-denominator "everything is rare" artefact).
RARITY_MIN_HISTORY_MONTHS = 12

# ---------------------------------------------------------------------------
# Phase 10 — recency (spec row 8). "accepted < 2h ago -> +1 (decays to 0
# after 48h)". Integerised conservatively: only the < 2h state scores; the
# 2h..48h decay ramp is floored to 0. A non-scoring recency_state reason
# (FRESH / RECENT / AGED) carries the 48h horizon for context.
# ---------------------------------------------------------------------------
RECENCY_FRESH_SECONDS = 2 * 60 * 60
RECENCY_HORIZON_SECONDS = 48 * 60 * 60
RECENCY_POINTS = 1
RECENCY_CAP = 1

# ---------------------------------------------------------------------------
# Phase 11 — watchlist relevance (spec row 9). A USER-PRIORITY feature, kept
# in its own component and reported separately from market significance. It
# can lift an event to MEDIUM but never, on its own, to HIGH/CRITICAL
# (see the substantive-points floor below).
# ---------------------------------------------------------------------------
WATCHLIST_POINTS = 1
WATCHLIST_PINNED_POINTS = 2
WATCHLIST_CAP = 2

# ---------------------------------------------------------------------------
# Phase — simultaneous events (spec row 10). >= 2 distinct event_type for the
# same issuer within ~5 trading days (backward-looking only, causal).
# ---------------------------------------------------------------------------
SIMULTANEOUS_WINDOW_DAYS = 7          # calendar days ~= 5 trading days
SIMULTANEOUS_MIN_DISTINCT_TYPES = 2
SIMULTANEOUS_POINTS = 1
SIMULTANEOUS_CAP = 1

# ---------------------------------------------------------------------------
# Phase 12 — data-quality penalty. Incomplete evidence reduces the score
# and can cap the band. One penalty point per issue, floored at the cap.
# ---------------------------------------------------------------------------
QUALITY_PENALTY_PER_ISSUE = -1
QUALITY_PENALTY_FLOOR = -2           # most negative the penalty component can be
#: event-level data_quality_flags that each dock a point
QUALITY_EVENT_FLAGS: frozenset[str] = frozenset(
    {
        "missing_acceptance_timestamp",
        "primary_document_unavailable",
        "ambiguous_session_bucket",
        "session_calendar_unavailable",
    }
)
#: comparison-level flags that (collectively, once) dock a point
QUALITY_COMPARISON_FLAGS: frozenset[str] = frozenset(
    {
        "missing_prior_filing",
        "prior_is_first_filing",
        "section_not_found",
        "ambiguous_section",
        "xbrl_unavailable",
        "xbrl_concept_missing",
        "current_document_unavailable",
        "prior_document_unavailable",
        "low_quality_comparison",
        "prior_form_mismatch",
    }
)
#: insider-level flags that (collectively, once) dock a point
QUALITY_INSIDER_FLAGS: frozenset[str] = frozenset(
    {
        "unknown_transaction_code",
        "role_unresolved",
        "missing_price",
        "missing_shares",
        "missing_transaction_date",
        "symbol_unresolved",
    }
)
#: issues that additionally CAP the band at MEDIUM
QUALITY_BAND_CAP_TRIGGERS: frozenset[str] = frozenset(
    {"missing_acceptance_timestamp", "source_down"}
)

# ---------------------------------------------------------------------------
# Phase 13 — score composition. Additive fixed-point (integers only). Each
# category is capped; the total is capped; there is no multiplier and no
# non-linear term.
# ---------------------------------------------------------------------------
COMPONENT_CAPS: dict[str, int] = {
    "event_type_base": EVENT_TYPE_BASE_CAP,
    "material_items": MULTI_ITEM_CAP,
    "filing_change": FILING_CHANGE_CAP,
    "risk_language": RISK_LANGUAGE_CAP,
    "xbrl_magnitude": XBRL_CAP,
    "insider_activity": INSIDER_CAP,
    "rarity": RARITY_CAP,
    "recency": RECENCY_CAP,
    "watchlist_priority": WATCHLIST_CAP,
    "simultaneous_events": SIMULTANEOUS_CAP,
}
SCORE_TOTAL_CAP = 12                 # well above the CRITICAL threshold (7)
SCORE_FLOOR = 0

#: component families that count toward the "substantive" floor for the
#: HIGH / CRITICAL bands. Excludes recency, watchlist and the quality
#: penalty — those must never, alone, push a band up.
SUBSTANTIVE_COMPONENTS: frozenset[str] = frozenset(
    {
        "event_type_base",
        "material_items",
        "filing_change",
        "risk_language",
        "xbrl_magnitude",
        "insider_activity",
        "rarity",
        "simultaneous_events",
    }
)

# ---------------------------------------------------------------------------
# Phase 2 / 13 — banding. FROZEN by INFORMATION_SIGNIFICANCE_SPEC.md.
# ---------------------------------------------------------------------------
BAND_THRESHOLDS: tuple[tuple[int, SignificanceBand], ...] = (
    (7, SignificanceBand.CRITICAL),
    (4, SignificanceBand.HIGH),
    (2, SignificanceBand.MEDIUM),
    (0, SignificanceBand.LOW),
)

# ---------------------------------------------------------------------------
# Phase 16 — CRITICAL band policy. A single ordinary 8-K must not become
# CRITICAL. On top of score >= 7, CRITICAL requires a structural minimum of
# substantive evidence.
# ---------------------------------------------------------------------------
CRITICAL_MIN_SUBSTANTIVE_POINTS = 5
CRITICAL_MIN_SUBSTANTIVE_FAMILIES = 2
HIGH_MIN_SUBSTANTIVE_POINTS = 2

#: If ZERO substantive points were scored (the total is made up only of
#: recency and/or watchlist points, or is negative), the band is held at
#: LOW no matter the raw score. This is the Phase 27 guard against a
#: watchlist / recency boost, on its own, promoting an event. It matches
#: the design's own WATCHLIST_RANKING example (a watch-listed KO with only
#: a routine Item 5.07 8-K ranks LOW).
NON_SUBSTANTIVE_ONLY_BAND = SignificanceBand.LOW

_BAND_ORDER: dict[SignificanceBand, int] = {
    SignificanceBand.LOW: 0,
    SignificanceBand.MEDIUM: 1,
    SignificanceBand.HIGH: 2,
    SignificanceBand.CRITICAL: 3,
}


def band_for_score(score: int) -> SignificanceBand:
    """Raw score -> band, per the frozen thresholds (before caps/floors)."""
    for threshold, band in BAND_THRESHOLDS:
        if score >= threshold:
            return band
    return SignificanceBand.LOW


def min_band(a: SignificanceBand, b: SignificanceBand) -> SignificanceBand:
    """The lower-priority of two bands."""
    return a if _BAND_ORDER[a] <= _BAND_ORDER[b] else b
