"""
talonx_ingest.intelligence.comparison.config
============================================
Frozen constants for the filing-comparison engine. Nothing here is a live
tunable: the material-change thresholds were computed once from the Task
95I research distribution and are pinned; the keyword lexicon is copied
verbatim from ``FILING_RESEARCH_PROTOCOL.md`` §7 and must not be edited to
suit current product wishes.
"""
from __future__ import annotations

import re

# ---------------------------------------------------------------------------
# transform / schema versions (evidence trace)
# ---------------------------------------------------------------------------
COMPARISON_SCHEMA_VERSION = "filing_comparison@v1"
COMPARISON_STORE_SCHEMA_VERSION = 1

PRIOR_MATCH_TRANSFORM = "prior_comparable_match@v1"
RETRIEVAL_TRANSFORM = "edgar_archive_fetch@v1"
NORMALIZE_TRANSFORM = "filing_normalize@v1"
SECTION_EXTRACT_TRANSFORM = "section_extract@v1"
DIFF_TRANSFORM = "difflib_wordratio@v1"          # 1 - SequenceMatcher(word list).quick_ratio()
PASSAGE_TRANSFORM = "difflib_opcodes@v1"
KEYWORD_TRANSFORM = "frozen_lexicon_count@v1"
XBRL_TRANSFORM = "xbrl_first_filed@v1"
COMPARISON_IDENTITY_TRANSFORM = "comparison_identity@v1"

# ---------------------------------------------------------------------------
# material-change thresholds -- top-tercile boundary of the Task 95I
# distribution (results/task95i_filing_alpha/_events/text_features.parquet,
# 763 filings with a prior). Computed ONCE, pinned here, NEVER recomputed
# live (FILING_CHANGE_INTELLIGENCE_SPEC.md). 96C emits the metric + an
# optional boolean flag; the significance BAND is Task 96E.
# ---------------------------------------------------------------------------
MATERIAL_CHANGE_THRESHOLDS: dict[str, float] = {
    "whole_document": 0.1339,
    "risk_factors": 0.1093,
    "mdna": 0.1659,
    "liquidity": 0.1511,
}
MATERIAL_THRESHOLD_PROVENANCE = (
    "top-tercile boundary of task95i_filing_alpha/_events/text_features.parquet "
    "(763 rows with a prior filing); frozen 2026-09-03"
)

# ---------------------------------------------------------------------------
# passages
# ---------------------------------------------------------------------------
PASSAGE_MIN_WORDS = 40                 # FILING_CHANGE_INTELLIGENCE_SPEC.md NEW_MATERIAL_PASSAGES
NEW_MATERIAL_PASSAGES_MIN_COUNT = 2
PASSAGE_MAX_CHARS = 4000              # a single stored passage is truncated past this (flagged)

# ---------------------------------------------------------------------------
# frozen keyword lexicon -- VERBATIM from FILING_RESEARCH_PROTOCOL.md §7.
# Do not add/remove/reword terms in Task 96C. Counts only, never sentiment.
# ---------------------------------------------------------------------------
NEGATIVE_RISK_TERMS: tuple[str, ...] = (
    "going concern",
    "material weakness",
    "impairment",
    "restructuring",
    "covenant",
    "litigation",
    "subpoena",
    "investigation",
    "default",
    "dilution",
    "headwind",
    "decline in demand",
)
POSITIVE_BUSINESS_TERMS: tuple[str, ...] = (
    "record revenue",
    "raised guidance",
    "strong demand",
    "backlog",
    "expansion",
    "share repurchase",
    "margin expansion",
    "accelerating",
)

# ---------------------------------------------------------------------------
# section header regexes. Case-insensitive; run against normalised
# (lower-cased) text. "Take the last non-TOC match" is enforced in
# sections.py, not here.
# ---------------------------------------------------------------------------
SECTION_HEADER_PATTERNS: dict[str, re.Pattern] = {
    "risk_factors": re.compile(r"item\s+1a\.?\s+risk\s+factors", re.IGNORECASE),
    "mdna": re.compile(
        r"(?:item\s+[27]\.?\s+)?management['’]s\s+discussion\s+and\s+analysis",
        re.IGNORECASE,
    ),
    "liquidity": re.compile(r"liquidity\s+and\s+capital\s+resources", re.IGNORECASE),
}
# a generic "next Item Nx." boundary
NEXT_ITEM_PATTERN = re.compile(r"\bitem\s+\d{1,2}[a-z]?\.", re.IGNORECASE)
# a match is treated as a real section (not a bare table-of-contents line)
# only if at least this many characters of body follow it before the next
# Item header. 200 keeps a genuine "there have been no material changes to
# our risk factors" stub (which IS the disclosure) while still rejecting a
# 2-4 word TOC entry.
MIN_SECTION_BODY_CHARS = 200

# ---------------------------------------------------------------------------
# page-furniture / EDGAR wrapper noise removed during normalisation.
# Deterministic patterns only -- never drop a whole disclosure section.
# ---------------------------------------------------------------------------
PAGE_FURNITURE_PATTERNS: tuple[re.Pattern, ...] = (
    re.compile(r"^\s*page\s+\d+\s*(?:of\s+\d+)?\s*$", re.IGNORECASE | re.MULTILINE),
    re.compile(r"^\s*-\s*\d+\s*-\s*$", re.MULTILINE),                 # "- 12 -"
    re.compile(r"^\s*table\s+of\s+contents\s*$", re.IGNORECASE | re.MULTILINE),
    re.compile(r"^\s*\d{1,3}\s*$", re.MULTILINE),                     # bare page number line
)
# inline XBRL / iXBRL leftovers occasionally survive tag-stripping
INLINE_XBRL_PATTERNS: tuple[re.Pattern, ...] = (
    re.compile(r"\b(?:us-gaap|dei|ix|xbrli|srt):[A-Za-z0-9_]+\b"),
    re.compile(r"\bcontextref\s*=\s*\S+", re.IGNORECASE),
)

# ---------------------------------------------------------------------------
# XBRL concepts -- first-filed only. Fallback chains: first concept with a
# usable value wins for that logical field.
# ---------------------------------------------------------------------------
XBRL_FIELDS: tuple[dict, ...] = (
    {
        "field": "revenue",
        "unit": "USD",
        "concepts": [
            ("us-gaap", "RevenueFromContractWithCustomerExcludingAssessedTax"),
            ("us-gaap", "Revenues"),
            ("us-gaap", "SalesRevenueNet"),
        ],
    },
    {
        "field": "net_income",
        "unit": "USD",
        "concepts": [("us-gaap", "NetIncomeLoss")],
    },
    {
        "field": "eps_diluted",
        "unit": "USD/shares",
        "concepts": [("us-gaap", "EarningsPerShareDiluted")],
    },
    {
        "field": "operating_income",
        "unit": "USD",
        "concepts": [("us-gaap", "OperatingIncomeLoss")],
    },
    {
        "field": "cash_and_equivalents",
        "unit": "USD",
        "concepts": [
            ("us-gaap", "CashAndCashEquivalentsAtCarryingValue"),
            ("us-gaap", "CashCashEquivalentsRestrictedCashAndRestrictedCashEquivalents"),
        ],
    },
    {
        "field": "long_term_debt",
        "unit": "USD",
        "concepts": [
            ("us-gaap", "LongTermDebtNoncurrent"),
            ("us-gaap", "LongTermDebt"),
        ],
    },
    {
        "field": "shares_outstanding",
        "unit": "shares",
        "concepts": [
            ("dei", "EntityCommonStockSharesOutstanding"),
            ("us-gaap", "CommonStockSharesOutstanding"),
        ],
    },
)

# ---------------------------------------------------------------------------
# how many prior candidates to pull from the event store when resolving the
# prior comparable filing
# ---------------------------------------------------------------------------
PRIOR_MATCH_LOOKBACK = 8
