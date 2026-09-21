"""
tests/test_comparison_keywords.py
---------------------------------
Task 96C -- frozen-lexicon keyword deltas (counts only).
"""
from __future__ import annotations

from talonx_ingest.intelligence.comparison.config import (
    NEGATIVE_RISK_TERMS,
    POSITIVE_BUSINESS_TERMS,
)
from talonx_ingest.intelligence.comparison.domain import KeywordCategory
from talonx_ingest.intelligence.comparison.keywords import count_term, keyword_deltas


def test_frozen_lexicon_matches_protocol_section_7():
    # verbatim from FILING_RESEARCH_PROTOCOL.md §7 -- guard against drift
    assert NEGATIVE_RISK_TERMS == (
        "going concern", "material weakness", "impairment", "restructuring", "covenant",
        "litigation", "subpoena", "investigation", "default", "dilution", "headwind",
        "decline in demand",
    )
    assert POSITIVE_BUSINESS_TERMS == (
        "record revenue", "raised guidance", "strong demand", "backlog", "expansion",
        "share repurchase", "margin expansion", "accelerating",
    )


def test_count_term_word_boundary():
    assert count_term("the company defaulted on a note", "default") == 0   # not inside "defaulted"
    assert count_term("an event of default occurred; default continues", "default") == 2
    assert count_term("impairment and further impairment charges", "impairment") == 2


def test_unchanged_lexicon_zero_delta():
    text = "impairment litigation covenant backlog expansion " * 3
    changes, summaries = keyword_deltas(text, text)
    assert all(c.delta == 0 for c in changes)
    for s in summaries:
        assert s.total_delta == 0
        assert s.terms_increased == () and s.terms_decreased == ()


def test_increase_and_decrease_tracked_per_term():
    prior = "the filing mentions impairment once and litigation once"
    current = "impairment impairment impairment; no more of that other l-word"
    changes, summaries = keyword_deltas(prior, current)
    by_term = {c.term: c for c in changes}
    assert by_term["impairment"].delta == 2       # 1 -> 3
    assert by_term["litigation"].delta == -1      # 1 -> 0
    neg = next(s for s in summaries if s.category is KeywordCategory.NEGATIVE_RISK)
    assert "impairment" in neg.terms_increased
    assert "litigation" in neg.terms_decreased
    assert neg.total_delta == 1                   # +2 impairment, -1 litigation


def test_phrase_terms_counted():
    prior = ""
    current = "there is substantial doubt about our ability to continue as a going concern"
    changes, _ = keyword_deltas(prior, current)
    assert next(c for c in changes if c.term == "going concern").delta == 1


def test_positive_and_negative_categories_independent():
    changes, summaries = keyword_deltas(
        "backlog", "backlog backlog record revenue impairment"
    )
    pos = next(s for s in summaries if s.category is KeywordCategory.POSITIVE_BUSINESS)
    neg = next(s for s in summaries if s.category is KeywordCategory.NEGATIVE_RISK)
    assert pos.total_delta == 2      # +1 backlog, +1 record revenue
    assert neg.total_delta == 1      # +1 impairment


def test_deterministic():
    a = keyword_deltas("impairment", "impairment impairment")
    b = keyword_deltas("impairment", "impairment impairment")
    assert a == b
