"""
tests/test_comparison_domain.py
-------------------------------
Task 96C -- FilingComparison domain value objects: immutability, schema
version, and the absence of any predictive/directional field.
"""
from __future__ import annotations

from datetime import datetime, timezone

import pytest
from pydantic import ValidationError

from talonx_ingest.intelligence.comparison.config import COMPARISON_SCHEMA_VERSION
from talonx_ingest.intelligence.comparison.domain import (
    ComparisonMethod,
    FilingComparison,
    KeywordCategory,
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

_NOW = datetime(2026, 5, 1, 20, 0, tzinfo=timezone.utc)

_FORBIDDEN = {
    "expected_return", "direction", "sentiment", "sentiment_score", "signal",
    "recommendation", "target_price", "probability", "bullish", "bearish",
    "risk_score", "severity", "outlook",
}


def _min_comparison(**kw) -> FilingComparison:
    base = dict(
        comparison_id="CMP:0000000000-26-000002:0000000000-26-000001:filing_comparison@v1",
        symbol="test",
        company_name="Test Corp",
        current_event_id="e2",
        prior_event_id="e1",
        current_accession="0000000000-26-000002",
        prior_accession="0000000000-26-000001",
        form_type="10-Q",
        base_form="10-Q",
        current_accepted_at_utc=_NOW,
        prior_accepted_at_utc=None,
        created_at_utc=_NOW,
    )
    base.update(kw)
    return FilingComparison(**base)


def test_defaults_and_schema_version():
    fc = _min_comparison()
    assert fc.schema_version == COMPARISON_SCHEMA_VERSION
    assert fc.symbol == "test"  # not auto-upper here (engine upper-cases)
    assert fc.comparison_method is ComparisonMethod.SEQUENCEMATCHER_QUICKRATIO_WORDLIST_V1
    assert fc.section_changes == ()
    assert fc.data_quality_flags == ()


def test_frozen():
    fc = _min_comparison()
    with pytest.raises(ValidationError):
        fc.symbol = "MSFT"


def test_rejects_unknown_field():
    with pytest.raises(ValidationError):
        _min_comparison(expected_return=0.1)


def test_no_predictive_fields_on_any_model():
    for model in (
        FilingComparison, WholeDocumentChange, SectionChange, KeywordChange,
        XbrlChange, PassageChange,
    ):
        fields = set(model.model_fields)
        assert not (fields & _FORBIDDEN), (model.__name__, fields & _FORBIDDEN)


def test_json_roundtrip():
    fc = _min_comparison(
        whole_document_change=WholeDocumentChange(
            prior_word_count=100, current_word_count=120, word_count_delta=20,
            prior_char_count=600, current_char_count=720, char_count_delta=120,
            quick_ratio=0.8, diff_ratio=0.2, added_word_count=25, removed_word_count=5,
            changed_fraction=0.13, material_threshold=0.1339, exceeds_material_threshold=True,
        ),
        section_changes=(
            SectionChange(
                section_type=SectionType.RISK_FACTORS, status=SectionStatus.FOUND,
                prior_present=True, current_present=True, diff_ratio=0.4,
            ),
        ),
        keyword_changes=(
            KeywordChange(
                category=KeywordCategory.NEGATIVE_RISK, term="impairment",
                prior_count=1, current_count=4, delta=3,
            ),
        ),
        xbrl_changes=(
            XbrlChange(field="revenue", comparison=XbrlPeriodComparison.YOY, status="NO_PRIOR"),
        ),
        new_passages=(
            PassageChange(
                change_type=PassageChangeType.NEW_IN_CURRENT, section="risk_factors",
                index=0, word_count=50, char_count=300, text="x " * 50,
            ),
        ),
    )
    restored = FilingComparison.model_validate_json(fc.model_dump_json())
    assert restored == fc
