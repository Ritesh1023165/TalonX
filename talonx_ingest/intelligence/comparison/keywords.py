"""
talonx_ingest.intelligence.comparison.keywords
==============================================
Frozen-lexicon keyword-delta computation.

Lexicon: ``FILING_RESEARCH_PROTOCOL.md`` §7, copied verbatim into
``config.py``. **Counts only** -- occurrences of a fixed phrase in the
current filing minus occurrences in the prior comparable filing. No
sentiment, no classifier, no direction. The product may say
"term count increased"; it must never say "bearish".
"""
from __future__ import annotations

import re

from talonx_ingest.intelligence.comparison.config import (
    NEGATIVE_RISK_TERMS,
    POSITIVE_BUSINESS_TERMS,
)
from talonx_ingest.intelligence.comparison.domain import (
    KeywordCategory,
    KeywordCategorySummary,
    KeywordChange,
)

_CATEGORY_TERMS: dict[KeywordCategory, tuple[str, ...]] = {
    KeywordCategory.NEGATIVE_RISK: NEGATIVE_RISK_TERMS,
    KeywordCategory.POSITIVE_BUSINESS: POSITIVE_BUSINESS_TERMS,
}

# non-overlapping, case-insensitive (text is already lower-cased), with a
# soft alnum boundary so "default" does not match inside "defaulted".
_TERM_PATTERNS: dict[str, re.Pattern] = {
    term: re.compile(r"(?<![a-z0-9])" + re.escape(term) + r"(?![a-z0-9])")
    for term in (*NEGATIVE_RISK_TERMS, *POSITIVE_BUSINESS_TERMS)
}


def count_term(text_lower: str, term: str) -> int:
    return len(_TERM_PATTERNS[term].findall(text_lower or ""))


def keyword_deltas(
    prior_text_lower: str,
    current_text_lower: str,
) -> tuple[tuple[KeywordChange, ...], tuple[KeywordCategorySummary, ...]]:
    changes: list[KeywordChange] = []
    summaries: list[KeywordCategorySummary] = []

    for category, terms in _CATEGORY_TERMS.items():
        prior_total = current_total = 0
        up: list[str] = []
        down: list[str] = []
        for term in terms:
            pc = count_term(prior_text_lower, term)
            cc = count_term(current_text_lower, term)
            prior_total += pc
            current_total += cc
            changes.append(
                KeywordChange(
                    category=category,
                    term=term,
                    prior_count=pc,
                    current_count=cc,
                    delta=cc - pc,
                )
            )
            if cc - pc > 0:
                up.append(term)
            elif cc - pc < 0:
                down.append(term)
        summaries.append(
            KeywordCategorySummary(
                category=category,
                prior_total=prior_total,
                current_total=current_total,
                total_delta=current_total - prior_total,
                terms_increased=tuple(up),
                terms_decreased=tuple(down),
            )
        )
    return tuple(changes), tuple(summaries)
