"""
tests/_dashboard_helpers.py
---------------------------
Shared seeding for the Task 96G dashboard tests. Not a test module.
Builds a real ledger DB with 96A events + 96E significance + (optionally)
96C comparisons, then hands back an ``IntelligenceReadAPI`` over it.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

from talonx_ingest.intelligence.comparison.whatchanged import build_what_changed  # noqa: F401
from talonx_ingest.intelligence.dashboard.readapi import IntelligenceReadAPI
from talonx_ingest.intelligence.domain import (
    EventType,
    EvidenceRecord,
    FreshnessStatus,
    SessionBucket,
    SourceType,
    TextEvent,
)
from talonx_ingest.intelligence.significance import evaluate_significance
from _significance_helpers import mk_comparison  # noqa: F401

UTC = timezone.utc
NOW = datetime(2026, 9, 3, 20, 0, 0, tzinfo=UTC)


def mk_event(
    *,
    event_type: EventType = EventType.EARNINGS_RESULTS,
    symbol: str = "AAPL",
    company: str | None = None,
    accession: str = "0000320193-26-000101",
    form_type: str = "8-K",
    items: tuple[str, ...] = ("2.02", "9.01"),
    age_hours: float = 2.0,
    quality_flags: tuple[str, ...] = (),
    is_amendment: bool = False,
    report_period_end=None,
    now: datetime = NOW,
) -> TextEvent:
    return TextEvent(
        event_id=f"SEC:{accession}:{event_type.value}",
        symbol=symbol,
        company_name=company or f"{symbol} Inc.",
        source_type=SourceType.SEC_EDGAR_SUBMISSIONS,
        source_record_id=accession,
        event_type=event_type,
        form_type=form_type,
        filing_items=items,
        accession=accession,
        accepted_at_utc=now - timedelta(hours=age_hours),
        filing_date=(now - timedelta(hours=age_hours)).date(),
        report_period_end=report_period_end,
        session_bucket=SessionBucket.RTH,
        session_reason=None,
        primary_document="doc.htm",
        primary_document_url="https://www.sec.gov/Archives/edgar/data/320193/x/doc.htm",
        filing_index_url="https://www.sec.gov/Archives/edgar/data/320193/x/index.htm",
        is_amendment=is_amendment,
        ingested_at_utc=now,
        freshness=FreshnessStatus.FRESH,
        data_quality_flags=quality_flags,
        evidence=(
            EvidenceRecord(
                source_provider=SourceType.SEC_EDGAR_SUBMISSIONS,
                source_record_id=accession,
                source_url="https://www.sec.gov/Archives/edgar/data/320193/x/index.htm",
                exact_timestamp=now - timedelta(hours=age_hours),
                retrieved_at=now,
                transform="edgar_submission_normalize@v1",
                input_hash="0" * 64,
                notes=f"form={form_type}",
            ),
        ),
    )


def seeded_api(tmp_db, *, now: datetime = NOW, spec: list[dict] | None = None) -> IntelligenceReadAPI:
    """`spec` entries: {event_type, symbol, items, accession, age_hours,
    on_watchlist, pinned, comparison(FilingComparison|None), quality_flags}."""
    api = IntelligenceReadAPI(ledger_path=str(tmp_db), now=now)
    spec = _default_spec() if spec is None else spec
    for s in spec:
        ev = mk_event(
            event_type=s.get("event_type", EventType.EARNINGS_RESULTS),
            symbol=s.get("symbol", "AAPL"),
            company=s.get("company"),
            accession=s["accession"],
            form_type=s.get("form_type", "8-K"),
            items=s.get("items", ("2.02", "9.01")),
            age_hours=s.get("age_hours", 2.0),
            quality_flags=s.get("quality_flags", ()),
            is_amendment=s.get("is_amendment", False),
            now=now,
        )
        api.events.upsert_event(ev)
        comp = s.get("comparison")
        if comp is not None:
            api.comparisons.upsert_comparison(comp)
        sig = evaluate_significance(
            ev,
            comparison=comp,
            on_watchlist=s.get("on_watchlist", False),
            pinned=s.get("pinned", False),
            simultaneous_type_count=s.get("simultaneous", 0),
            source_status=s.get("source_status"),
            now=now,
        )
        if not s.get("skip_significance"):
            api.significance.upsert(sig)
    return api


def _default_spec() -> list[dict]:
    return [
        dict(event_type=EventType.SHAREHOLDER_VOTE_RESULT, symbol="KO", items=("5.07",),
             accession="0000021344-26-000001", age_hours=30),
        dict(event_type=EventType.EARNINGS_RESULTS, symbol="MSFT", items=("2.02", "9.01"),
             accession="0000789019-26-000002", age_hours=3, on_watchlist=True),
        dict(event_type=EventType.RESTRUCTURING, symbol="AAPL", items=("2.05", "1.01"),
             accession="0000320193-26-000003", age_hours=1, on_watchlist=True, pinned=True,
             simultaneous=2),
        dict(event_type=EventType.INSIDER_TRANSACTION, symbol="NVDA", items=(), form_type="4",
             accession="0001045810-26-000004", age_hours=5),
    ]
