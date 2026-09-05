"""
talonx_ingest.intelligence.comparison
=====================================
Task 96C -- the deterministic **"WHAT CHANGED?"** engine for SEC 10-Q /
10-K filings.

Given a current filing and its prior comparable filing it produces a
canonical, immutable ``FilingComparison``:

    prior filing ─┐
                  ├─ normalise ─ section extract ─ whole+section diff ─┐
    current ──────┘                                                    │
        + frozen keyword deltas + first-filed XBRL deltas + passages ──┴─ what_changed

It answers *"what objectively changed between this filing and the prior
comparable filing?"* and **never** *"what will the stock do?"* -- there is
no predictive, directional, sentiment or expected-return field anywhere in
this package, and machine-generated labels are lint-checked
(``language_safety``).

Deterministic (``difflib`` + regex + first-filed XBRL only), causal
(current + strictly-prior **original** filing; first-filed values only),
explainable (every derived value carries an ``EvidenceRecord`` naming its
transform@version), £0, no AI/NLP.

This subpackage is additive: it reads the Task 96A ``text_events`` store,
adds its own ``filing_comparison_*`` tables to the same SQLite file, and
touches no trading module.
"""
from __future__ import annotations

from talonx_ingest.intelligence.comparison.domain import (
    ComparisonMethod,
    ComparisonQualityFlag,
    FilingComparison,
    KeywordCategory,
    KeywordCategorySummary,
    KeywordChange,
    PassageChange,
    PassageChangeType,
    SectionChange,
    SectionStatus,
    SectionType,
    WholeDocumentChange,
    XbrlChange,
    XbrlPeriodComparison,
)

__all__ = [
    "ComparisonMethod",
    "ComparisonQualityFlag",
    "FilingComparison",
    "KeywordCategory",
    "KeywordCategorySummary",
    "KeywordChange",
    "PassageChange",
    "PassageChangeType",
    "SectionChange",
    "SectionStatus",
    "SectionType",
    "WholeDocumentChange",
    "XbrlChange",
    "XbrlPeriodComparison",
]
