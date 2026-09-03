"""
tests/test_comparison_store.py
------------------------------
Task 96C -- FilingComparisonStore: persist / read / restart / idempotent
upsert / additive migration alongside the Task 96A EventStore.
"""
from __future__ import annotations

from datetime import date, datetime, timezone

import pytest

from talonx_ingest.intelligence.comparison.domain import (
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
from talonx_ingest.intelligence.comparison.identity import comparison_id
from talonx_ingest.intelligence.comparison.store import FilingComparisonStore
from talonx_ingest.intelligence.domain import EvidenceRecord, SourceType
from talonx_ingest.intelligence.store import EventStore

_NOW = datetime(2026, 5, 1, 20, 0, tzinfo=timezone.utc)


def _comparison(current="0000320193-26-000040", prior="0000320193-26-000010", **kw) -> FilingComparison:
    cid = comparison_id(current, prior)
    base = dict(
        comparison_id=cid,
        symbol="AAPL",
        company_name="Apple Inc.",
        current_event_id=f"SEC:{current}:QUARTERLY_FILING",
        prior_event_id=f"SEC:{prior}:QUARTERLY_FILING" if prior else None,
        current_accession=current,
        prior_accession=prior,
        form_type="10-Q",
        base_form="10-Q",
        current_accepted_at_utc=_NOW,
        prior_accepted_at_utc=_NOW.replace(month=2),
        current_report_period_end=date(2026, 3, 31),
        prior_report_period_end=date(2025, 12, 31),
        current_document_hash="c" * 64,
        prior_document_hash="p" * 64,
        current_document_url="https://sec.gov/x/40.htm",
        prior_document_url="https://sec.gov/x/10.htm",
        whole_document_change=WholeDocumentChange(
            prior_word_count=1000, current_word_count=1120, word_count_delta=120,
            prior_char_count=6000, current_char_count=6720, char_count_delta=720,
            quick_ratio=0.82, diff_ratio=0.18, added_word_count=140, removed_word_count=20,
            changed_fraction=0.075, material_threshold=0.1339, exceeds_material_threshold=True,
        ),
        section_changes=(
            SectionChange(
                section_type=SectionType.RISK_FACTORS, status=SectionStatus.FOUND,
                prior_present=True, current_present=True,
                prior_char_count=2000, current_char_count=2600, char_count_delta=600,
                pct_char_delta=0.3, prior_word_count=300, current_word_count=390,
                word_count_delta=90, quick_ratio=0.55, diff_ratio=0.45,
                added_word_count=110, removed_word_count=20,
                prior_text_hash="a" * 64, current_text_hash="b" * 64,
                material_threshold=0.1093, exceeds_material_threshold=True,
                header_matched_current="item 1a. risk factors",
                header_matched_prior="item 1a. risk factors",
            ),
            SectionChange(
                section_type=SectionType.MDNA, status=SectionStatus.NOT_FOUND,
                prior_present=True, current_present=False,
            ),
            SectionChange(
                section_type=SectionType.LIQUIDITY, status=SectionStatus.FOUND,
                prior_present=True, current_present=True, diff_ratio=0.05,
                material_threshold=0.1511, exceeds_material_threshold=False,
            ),
        ),
        keyword_changes=(
            KeywordChange(category=KeywordCategory.NEGATIVE_RISK, term="impairment",
                          prior_count=1, current_count=4, delta=3),
            KeywordChange(category=KeywordCategory.POSITIVE_BUSINESS, term="backlog",
                          prior_count=2, current_count=2, delta=0),
        ),
        keyword_category_summaries=(
            KeywordCategorySummary(
                category=KeywordCategory.NEGATIVE_RISK, prior_total=1, current_total=4,
                total_delta=3, terms_increased=("impairment",),
            ),
            KeywordCategorySummary(
                category=KeywordCategory.POSITIVE_BUSINESS, prior_total=2, current_total=2,
                total_delta=0,
            ),
        ),
        xbrl_changes=(
            XbrlChange(
                field="revenue", taxonomy="us-gaap", concept="Revenues", unit="USD",
                comparison=XbrlPeriodComparison.YOY, prior_period_end=date(2025, 3, 31),
                current_period_end=date(2026, 3, 31), prior_value=100.0, current_value=118.0,
                absolute_delta=18.0, relative_delta=0.18, prior_filed_accession="x",
                current_filed_accession="y", status="FOUND",
            ),
        ),
        new_passages=(
            PassageChange(change_type=PassageChangeType.NEW_IN_CURRENT, section="risk_factors",
                          index=0, word_count=55, char_count=340, text="new risk " * 40,
                          current_word_offset=120),
        ),
        removed_passages=(
            PassageChange(change_type=PassageChangeType.REMOVED_SINCE_PRIOR, section="mdna",
                          index=0, word_count=48, char_count=300, text="gone text " * 30,
                          prior_word_offset=80),
        ),
        data_quality_flags=(ComparisonQualityFlag.SECTION_NOT_FOUND.value,),
        evidence=(
            EvidenceRecord(
                source_provider=SourceType.SEC_EDGAR_ARCHIVES, source_record_id="filing_comparison",
                retrieved_at=_NOW, transform="difflib_wordratio@v1", input_hash="h",
                notes="whole + section diff",
            ),
        ),
        created_at_utc=_NOW,
    )
    base.update(kw)
    return FilingComparison(**base)


@pytest.fixture
def store_path(tmp_path):
    return tmp_path / "shared.db"


def test_schema_version_and_tables(store_path):
    with FilingComparisonStore(store_path) as st:
        assert st.schema_version() == 1
        names = {
            r[0]
            for r in st._conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            ).fetchall()
        }
    assert {
        "filing_comparisons", "filing_section_changes", "filing_keyword_changes",
        "filing_keyword_summaries", "filing_xbrl_changes", "filing_passage_changes",
        "filing_comparison_evidence",
    } <= names


def test_insert_read_full_roundtrip(store_path):
    fc = _comparison()
    with FilingComparisonStore(store_path) as st:
        assert st.upsert_comparison(fc) is True
        got = st.get_comparison(fc.comparison_id)
    assert got == fc


def test_idempotent_upsert(store_path):
    fc = _comparison()
    with FilingComparisonStore(store_path) as st:
        assert st.upsert_comparison(fc) is True
        assert st.upsert_comparison(fc) is False
        assert st.upsert_comparison(fc) is False
        assert st.count() == 1
        assert len(st.get_section_changes(fc.comparison_id)) == 3
        assert len(st.get_xbrl_changes(fc.comparison_id)) == 1
        assert len(st.get_passages(fc.comparison_id)) == 2
        assert len(st._keyword_changes(fc.comparison_id)) == 2


def test_state_persists_across_reopen(store_path):
    fc = _comparison()
    with FilingComparisonStore(store_path) as st:
        st.upsert_comparison(fc)
    with FilingComparisonStore(store_path) as st2:
        assert st2.has_comparison(fc.comparison_id)
        assert st2.get_comparison(fc.comparison_id).symbol == "AAPL"


def test_query_interfaces(store_path):
    fc1 = _comparison(current="0000320193-26-000010", prior="0000320193-25-000090")
    fc2 = _comparison(current="0000320193-26-000040", prior="0000320193-26-000010")
    fc2 = fc2.model_copy(update={"current_accepted_at_utc": _NOW})
    fc1 = fc1.model_copy(update={"current_accepted_at_utc": _NOW.replace(month=2)})
    with FilingComparisonStore(store_path) as st:
        st.upsert_comparison(fc1)
        st.upsert_comparison(fc2)
        assert st.get_comparison_for_current_event(fc2.current_event_id).comparison_id == fc2.comparison_id
        assert st.latest_for_symbol("AAPL", base_form="10-Q").comparison_id == fc2.comparison_id
        rows = st.query_comparisons(symbol="AAPL")
        assert [r.comparison_id for r in rows] == [fc2.comparison_id, fc1.comparison_id]
        assert st.query_comparisons(symbol="AAPL", limit=1)[0].comparison_id == fc2.comparison_id
        assert len(st.query_comparisons(since=_NOW.replace(month=3))) == 1


def test_upsert_rebuilds_children_not_duplicates(store_path):
    fc = _comparison()
    with FilingComparisonStore(store_path) as st:
        st.upsert_comparison(fc)
        # a re-computed comparison for the same id with fewer keyword rows
        fc2 = fc.model_copy(
            update={
                "keyword_changes": (fc.keyword_changes[0],),
                "new_passages": (),
            }
        )
        st.upsert_comparison(fc2)
        assert len(st._keyword_changes(fc.comparison_id)) == 1
        assert st.get_passages(fc.comparison_id, change_type=PassageChangeType.NEW_IN_CURRENT) == []


def test_additive_migration_preserves_event_store(tmp_path):
    db = tmp_path / "ingestion_ledger.db"
    with EventStore(db) as es:
        from talonx_ingest.intelligence.domain import (
            EventType, FreshnessStatus, SessionBucket, SourceType as ST, TextEvent,
        )

        es.upsert_event(
            TextEvent(
                event_id="SEC:0000320193-26-000040:QUARTERLY_FILING", symbol="AAPL",
                company_name="Apple Inc.", source_type=ST.SEC_EDGAR_SUBMISSIONS,
                source_record_id="0000320193-26-000040", event_type=EventType.QUARTERLY_FILING,
                form_type="10-Q", accession="0000320193-26-000040", accepted_at_utc=_NOW,
                session_bucket=SessionBucket.AMC, ingested_at_utc=_NOW, freshness=FreshnessStatus.FRESH,
            )
        )
    with FilingComparisonStore(db) as st:
        st.upsert_comparison(_comparison())
        tables = {
            r[0]
            for r in st._conn.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()
        }
        assert "text_events" in tables and "filing_comparisons" in tables
    with EventStore(db) as es2:
        assert es2.has_event("SEC:0000320193-26-000040:QUARTERLY_FILING")
        assert es2.schema_version() == 1
