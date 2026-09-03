"""
tests/test_comparison_engine.py
-------------------------------
Task 96C -- compare_filings (pure) integration: normalise -> sections ->
diff -> passages -> keywords -> xbrl -> FilingComparison, plus the
what_changed contract and language safety over a full comparison.
"""
from __future__ import annotations

from datetime import date, datetime, timezone

import pytest

from talonx_ingest.intelligence.comparison.config import XBRL_FIELDS
from talonx_ingest.intelligence.comparison.domain import SectionStatus, SectionType
from talonx_ingest.intelligence.comparison.engine import compare_filings
from talonx_ingest.intelligence.comparison.language_safety import scan_comparison
from talonx_ingest.intelligence.comparison.whatchanged import build_what_changed

_NOW = datetime(2026, 5, 1, 20, 0, tzinfo=timezone.utc)
_PRIOR = datetime(2026, 2, 1, 20, 0, tzinfo=timezone.utc)

_RF_PRIOR = "the company faces competition and regulatory and supply chain risk. " * 40
_RF_CUR = (
    "the company faces competition and regulatory and supply chain risk. " * 18
    + "during the quarter we identified a material weakness in internal control over financial "
      "reporting and remediation efforts are ongoing while related litigation remains pending. " * 6
)
_MDNA_PRIOR = "revenue rose on higher unit volumes and favorable pricing across regions. " * 40
_MDNA_CUR = (
    "revenue rose on higher unit volumes and favorable pricing across regions. " * 40
    + "we also completed a share repurchase and achieved margin expansion this period which "
      "management attributes to operating leverage and disciplined cost control efforts. " * 6
)
_LIQ = "we believe our existing cash and cash flow from operations are adequate for twelve months. " * 25


def _doc(rf, mdna):
    return (
        "<html><body>"
        "<p>table of contents item 1a. risk factors 14 item 2. md&a 22</p>"
        f"<p>Item 1A. Risk Factors</p><p>{rf}</p>"
        "<p>Item 2. Management's Discussion and Analysis of Financial Condition and Results of Operations</p>"
        f"<p>{mdna}</p>"
        f"<p>Liquidity and Capital Resources</p><p>{_LIQ}</p>"
        "<p>Item 3. Quantitative and Qualitative Disclosures About Market Risk</p><p>none</p>"
        "</body></html>"
    )


def _all_none_concepts():
    d = {}
    for spec in XBRL_FIELDS:
        for k in spec["concepts"]:
            d[k] = None
    return d


@pytest.fixture
def comparison():
    return compare_filings(
        symbol="test",
        company_name="Test Corp",
        current_event_id="SEC:0000000000-26-000002:QUARTERLY_FILING",
        prior_event_id="SEC:0000000000-26-000001:QUARTERLY_FILING",
        current_accession="0000000000-26-000002",
        prior_accession="0000000000-26-000001",
        form_type="10-Q",
        current_accepted_at_utc=_NOW,
        prior_accepted_at_utc=_PRIOR,
        current_report_period_end=date(2026, 3, 31),
        prior_report_period_end=date(2025, 12, 31),
        current_html=_doc(_RF_CUR, _MDNA_CUR),
        prior_html=_doc(_RF_PRIOR, _MDNA_PRIOR),
        current_document_url="https://sec.gov/x/2.htm",
        prior_document_url="https://sec.gov/x/1.htm",
        concept_data=_all_none_concepts(),
        now=_NOW,
    )


def test_engine_produces_full_comparison(comparison):
    c = comparison
    assert c.comparison_id.startswith("CMP:0000000000-26-000002:0000000000-26-000001:")
    assert c.symbol == "TEST"
    assert c.base_form == "10-Q"
    assert c.whole_document_change is not None
    assert {s.section_type for s in c.section_changes} == set(SectionType)
    assert len(c.keyword_changes) == 20
    assert len(c.keyword_category_summaries) == 2
    assert c.current_document_hash and c.prior_document_hash


def test_sections_extracted_and_rf_changed_materially(comparison):
    by = {s.section_type: s for s in comparison.section_changes}
    assert by[SectionType.RISK_FACTORS].status is SectionStatus.FOUND
    assert by[SectionType.RISK_FACTORS].exceeds_material_threshold is True
    assert by[SectionType.MDNA].status is SectionStatus.FOUND


def test_keyword_deltas_captured(comparison):
    neg = next(s for s in comparison.keyword_category_summaries
               if s.category.value == "negative_risk")
    pos = next(s for s in comparison.keyword_category_summaries
               if s.category.value == "positive_business")
    assert neg.total_delta > 0            # added "material weakness", "litigation"
    assert "material weakness" in neg.terms_increased
    assert pos.total_delta > 0            # added "share repurchase", "margin expansion"


def test_new_passages_detected(comparison):
    assert len(comparison.new_passages) >= 1
    assert all(p.word_count >= 40 for p in comparison.new_passages)
    assert all(p.section in ("risk_factors", "mdna") for p in comparison.new_passages)


def test_xbrl_unavailable_when_concepts_all_missing(comparison):
    # concept_data supplied but every concept None -> CONCEPT_MISSING rows
    assert comparison.xbrl_changes
    assert all(x.status == "CONCEPT_MISSING" for x in comparison.xbrl_changes)


def test_evidence_trace_complete(comparison):
    transforms = {e.transform for e in comparison.evidence}
    assert transforms == {
        "prior_comparable_match@v1",
        "edgar_archive_fetch@v1:current",
        "edgar_archive_fetch@v1:prior",
        "filing_normalize@v1",
        "section_extract@v1",
        "difflib_opcodes@v1",
        "frozen_lexicon_count@v1",
        "xbrl_first_filed@v1",
    }
    for e in comparison.evidence:
        assert e.retrieved_at is not None


def test_no_predictive_language_in_engine_output(comparison):
    assert scan_comparison(comparison) == []


def test_deterministic(comparison):
    again = compare_filings(
        symbol="test", company_name="Test Corp",
        current_event_id="SEC:0000000000-26-000002:QUARTERLY_FILING",
        prior_event_id="SEC:0000000000-26-000001:QUARTERLY_FILING",
        current_accession="0000000000-26-000002", prior_accession="0000000000-26-000001",
        form_type="10-Q", current_accepted_at_utc=_NOW, prior_accepted_at_utc=_PRIOR,
        current_report_period_end=date(2026, 3, 31), prior_report_period_end=date(2025, 12, 31),
        current_html=_doc(_RF_CUR, _MDNA_CUR), prior_html=_doc(_RF_PRIOR, _MDNA_PRIOR),
        concept_data=_all_none_concepts(), now=_NOW,
    )
    assert again.whole_document_change == comparison.whole_document_change
    assert again.section_changes == comparison.section_changes
    assert again.keyword_changes == comparison.keyword_changes


def test_missing_current_document_low_quality():
    c = compare_filings(
        symbol="t", company_name="T", current_event_id="e2", prior_event_id="e1",
        current_accession="0000000000-26-000002", prior_accession="0000000000-26-000001",
        form_type="10-Q", current_accepted_at_utc=_NOW, prior_accepted_at_utc=_PRIOR,
        current_html=None, prior_html=_doc(_RF_PRIOR, _MDNA_PRIOR), concept_data=None,
    )
    assert "current_document_unavailable" in c.data_quality_flags
    assert "low_quality_comparison" in c.data_quality_flags
    assert c.whole_document_change is None


def test_what_changed_contract(comparison):
    wc = build_what_changed(comparison)
    assert wc["comparison_id"] == comparison.comparison_id
    assert wc["has_prior"] is True
    assert set(wc["sections"]) == {"risk_factors", "mdna", "liquidity"}
    assert wc["whole_document"]["diff_ratio"] == comparison.whole_document_change.diff_ratio
    assert isinstance(wc["notable_changes"], list)
    kinds = {n["kind"] for n in wc["notable_changes"]}
    assert "section_changed_materially" in kinds
    assert "keyword_category_count_changed" in kinds
    # nothing predictive in the structured output
    assert scan_comparison(comparison) == []
    for n in wc["notable_changes"]:
        assert "direction" not in n and "expected_return" not in n
