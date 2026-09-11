"""
talonx_ingest.intelligence.pipeline
===================================
Thin orchestration: a raw EDGAR *submissions* JSON document ->
``NormalizedFiling`` -> classified, session-bucketed ``TextEvent`` rows ->
``EventStore``.

This is where 96A ends. There is no delivery here (no Telegram, no
dashboard, no Redis), no filing-diff, no significance scoring, no quant
trigger. ``build_alert_card`` produces the delivery *contract* only, with
the significance band deliberately unset.
"""
from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass, field
from datetime import datetime

from talonx_ingest.intelligence.config import (
    EDGAR_NORMALIZE_TRANSFORM,
    SESSION_BUCKET_TRANSFORM,
    TAXONOMY_TRANSFORM,
)
from talonx_ingest.intelligence.domain import (
    AlertCard,
    EventType,
    EvidenceRecord,
    FreshnessStatus,
    SourceType,
    TextEvent,
    utc_now,
)
from talonx_ingest.intelligence.edgar_normalize import (
    NormalizedFiling,
    iter_normalized_filings,
)
from talonx_ingest.intelligence.identity import (
    alert_id,
    card_id,
    event_id,
    source_hash,
)
from talonx_ingest.intelligence.sessions import bucket_session
from talonx_ingest.intelligence.taxonomy import classify_filing
from talonx_ingest.intelligence.store import EventStore
from talonx_ingest.intelligence.freshness import SourceFreshnessTracker

_DEFAULT_FORMS = ("8-K", "10-Q", "10-K")

# Deterministic, factual title fragments -- no adjective implying an outcome.
_TITLE_FRAGMENT: dict[EventType, str] = {
    EventType.EARNINGS_RESULTS: "filed an 8-K with results of operations (Item 2.02)",
    EventType.MATERIAL_AGREEMENT: "filed an 8-K reporting a material definitive agreement (Item 1.01)",
    EventType.AGREEMENT_TERMINATED: "filed an 8-K reporting termination of a material agreement (Item 1.02)",
    EventType.ACQUISITION_DISPOSITION: "filed an 8-K reporting an acquisition or disposition of assets (Item 2.01)",
    EventType.DEBT_FINANCING: "filed an 8-K reporting a direct financial obligation (Item 2.03/2.04)",
    EventType.RESTRUCTURING: "filed an 8-K reporting exit or disposal costs (Item 2.05)",
    EventType.MATERIAL_IMPAIRMENT: "filed an 8-K reporting a material impairment (Item 2.06)",
    EventType.EXECUTIVE_CHANGE: "filed an 8-K reporting a change of directors or officers (Item 5.02)",
    EventType.REGULATION_FD: "filed an 8-K Regulation FD disclosure (Item 7.01)",
    EventType.OTHER_MATERIAL_EVENT: "filed an 8-K under Item 8.01 (other events)",
    EventType.SHAREHOLDER_VOTE_RESULT: "filed an 8-K reporting shareholder vote results (Item 5.07)",
    EventType.CHARTER_BYLAW_AMENDMENT: "filed an 8-K reporting a charter or bylaw amendment (Item 5.03)",
    EventType.UNREGISTERED_EQUITY_SALE: "filed an 8-K reporting an unregistered sale of equity (Item 3.02)",
    EventType.DELISTING_NOTICE: "filed an 8-K reporting a delisting notice or transfer of listing (Item 3.01)",
    EventType.QUARTERLY_FILING: "filed a Form 10-Q quarterly report",
    EventType.ANNUAL_FILING: "filed a Form 10-K annual report",
    EventType.INSIDER_TRANSACTION: "had an insider ownership form filed",
    EventType.FILING_AMENDMENT: "filed an amendment to a prior filing",
    EventType.UNCLASSIFIED_8K: "filed an 8-K (items not individually classified)",
    EventType.UNSUPPORTED_FORM: "filed a form outside the current coverage set",
    EventType.EARNINGS_EXPECTED: "has an expected earnings date (unconfirmed)",
}


@dataclass
class IngestResult:
    filings_seen: int = 0
    events_built: int = 0
    events_new: int = 0
    events_existing: int = 0
    event_ids: list[str] = field(default_factory=list)


def build_events_from_filing(
    nf: NormalizedFiling,
    *,
    freshness: FreshnessStatus = FreshnessStatus.UNKNOWN,
    now: datetime | None = None,
) -> list[TextEvent]:
    """One ``NormalizedFiling`` -> one ``TextEvent`` per distinct classified
    ``event_type`` (all sharing ``nf.accession``)."""
    now = now or utc_now()
    result = classify_filing(nf.form, nf.items)
    session = bucket_session(nf.acceptance_datetime)

    flags = _dedupe(nf.flags + result.flags + session.flags)

    shash = source_hash(
        nf.cik,
        nf.accession,
        nf.form,
        nf.acceptance_datetime.isoformat() if nf.acceptance_datetime else "",
        ",".join(nf.items),
        nf.primary_document or "",
    )

    events: list[TextEvent] = []
    for classification in result.classifications:
        et = classification.event_type
        eid = event_id(SourceType.SEC_EDGAR_SUBMISSIONS, nf.accession, et)
        evidence = (
            EvidenceRecord(
                source_provider=SourceType.SEC_EDGAR_SUBMISSIONS,
                source_record_id=nf.accession,
                source_url=nf.filing_index_url,
                exact_timestamp=nf.acceptance_datetime,
                retrieved_at=now,
                transform=EDGAR_NORMALIZE_TRANSFORM,
                input_hash=shash,
                notes=f"form={nf.form}",
            ),
            EvidenceRecord(
                source_provider=SourceType.SEC_EDGAR_SUBMISSIONS,
                source_record_id=nf.accession,
                source_url=nf.filing_index_url,
                exact_timestamp=nf.acceptance_datetime,
                retrieved_at=now,
                transform=TAXONOMY_TRANSFORM,
                input_hash=source_hash(nf.form, ",".join(nf.items)),
                notes=(
                    f"items={list(nf.items)} -> {et.value} "
                    f"(triggering={list(classification.triggering_items)})"
                ),
            ),
            EvidenceRecord(
                source_provider=SourceType.SEC_EDGAR_SUBMISSIONS,
                source_record_id=nf.accession,
                source_url=None,
                exact_timestamp=nf.acceptance_datetime,
                retrieved_at=now,
                transform=SESSION_BUCKET_TRANSFORM,
                input_hash=source_hash(
                    nf.acceptance_datetime.isoformat() if nf.acceptance_datetime else ""
                ),
                notes=f"bucket={session.bucket.value} reason={session.reason}",
            ),
        )
        events.append(
            TextEvent(
                event_id=eid,
                symbol=nf.symbol or "",
                company_name=nf.company_name,
                source_type=SourceType.SEC_EDGAR_SUBMISSIONS,
                source_record_id=nf.accession,
                event_type=et,
                form_type=nf.form,
                filing_items=nf.items,
                accession=nf.accession,
                accepted_at_utc=nf.acceptance_datetime,
                filing_date=nf.filing_date,
                report_period_end=nf.report_date,
                session_bucket=session.bucket,
                session_reason=session.reason,
                primary_document=nf.primary_document,
                primary_document_url=nf.primary_document_url,
                filing_index_url=nf.filing_index_url,
                exhibits=nf.exhibits,
                is_amendment=nf.is_amendment,
                amends_accession=None,  # original-filing resolution is Task 96C
                source_hash=shash,
                ingested_at_utc=now,
                freshness=freshness,
                data_quality_flags=flags,
                evidence=evidence,
            )
        )
    return events


def ingest_submissions(
    store: EventStore,
    submissions_json: dict,
    *,
    symbol: str | None = None,
    forms: Iterable[str] = _DEFAULT_FORMS,
    tracker: SourceFreshnessTracker | None = None,
    now: datetime | None = None,
) -> IngestResult:
    """Normalise every recent filing in ``submissions_json``, build events,
    persist them idempotently. Records a successful poll on ``tracker`` if
    one is supplied."""
    now = now or utc_now()
    forms_tuple = tuple(forms)
    freshness = FreshnessStatus.UNKNOWN
    latest_event_ts: datetime | None = None

    filings = list(
        iter_normalized_filings(submissions_json, symbol=symbol, forms=forms_tuple)
    )
    for nf in filings:
        if nf.acceptance_datetime and (
            latest_event_ts is None or nf.acceptance_datetime > latest_event_ts
        ):
            latest_event_ts = nf.acceptance_datetime

    if tracker is not None:
        snap = tracker.record_attempt(
            SourceType.SEC_EDGAR_SUBMISSIONS,
            success=True,
            latest_source_event_utc=latest_event_ts,
        )
        freshness = snap.status

    out = IngestResult(filings_seen=len(filings))
    for nf in filings:
        for event in build_events_from_filing(nf, freshness=freshness, now=now):
            out.events_built += 1
            if store.upsert_event(event):
                out.events_new += 1
            else:
                out.events_existing += 1
            out.event_ids.append(event.event_id)
    return out


def build_alert_card(event: TextEvent) -> AlertCard:
    """The delivery contract for one event. 96A: factual fields only;
    ``significance`` stays ``None`` (Task 96E assigns it)."""
    fragment = _TITLE_FRAGMENT.get(event.event_type, "filed with the SEC")
    title = f"{event.symbol} {fragment}"
    summary_fields: dict[str, str] = {
        "form": event.form_type,
        "items": ",".join(event.filing_items) if event.filing_items else "",
        "session": event.session_bucket.value,
        "accepted_at_utc": (
            event.accepted_at_utc.isoformat() if event.accepted_at_utc else ""
        ),
        "accession": event.accession,
    }
    if event.report_period_end:
        summary_fields["report_period_end"] = event.report_period_end.isoformat()
    return AlertCard(
        alert_id=alert_id(event.event_id),
        event_id=event.event_id,
        symbol=event.symbol,
        company_name=event.company_name,
        title=title,
        event_type=event.event_type,
        significance=None,
        significance_reasons=(),
        timestamp_utc=event.accepted_at_utc,
        session_bucket=event.session_bucket,
        form_type=event.form_type,
        filing_items=event.filing_items,
        summary_fields=summary_fields,
        evidence=event.evidence,
        freshness=event.freshness,
        data_quality_flags=event.data_quality_flags,
        source_url=event.filing_index_url or event.primary_document_url,
    )


def make_card_id(event: TextEvent) -> str:
    return card_id(event.symbol, event.accession, event.event_type)


def _dedupe(items: Iterable[str]) -> tuple[str, ...]:
    seen: list[str] = []
    for it in items:
        if it not in seen:
            seen.append(it)
    return tuple(seen)
