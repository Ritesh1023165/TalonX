"""
talonx_ingest.intelligence.insider.pipeline
===========================================
Orchestration: SEC ownership rows / XML -> canonical transactions ->
``InsiderStore`` (+ an ``INSIDER_TRANSACTION`` parent event on the Task
96A ``EventStore``) -> ``InsiderActivity`` aggregate.

No delivery, no significance scoring, no rendering here. No trading import.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta

from talonx_ingest.intelligence.domain import (
    EventType,
    EvidenceRecord,
    FreshnessStatus,
    SessionBucket,
    SourceType,
    TextEvent,
    utc_now,
)
from talonx_ingest.intelligence.identity import event_id as make_event_id
from talonx_ingest.intelligence.identity import normalize_accession, source_hash
from talonx_ingest.intelligence.insider.aggregate import build_insider_activity as _build_activity
from talonx_ingest.intelligence.insider.bulk import BulkTables, parse_row_groups
from talonx_ingest.intelligence.insider.config import (
    AGGREGATE_TRANSFORM,
    BULK_PARSE_TRANSFORM,
    LATEST_FILINGS_LIMIT,
    RECENT_TRANSACTIONS_WINDOW_DAYS,
    ROLLING_WINDOWS_CALENDAR_DAYS,
    XML_PARSE_TRANSFORM,
)
from talonx_ingest.intelligence.insider.domain import InsiderActivity, InsiderFiling
from talonx_ingest.intelligence.insider.language_safety import assert_clean
from talonx_ingest.intelligence.insider.ownership_xml import parse_ownership_xml
from talonx_ingest.intelligence.insider.store import InsiderStore

logger = logging.getLogger("talonx_ingest.intelligence.insider.pipeline")


@dataclass
class InsiderIngestResult:
    filings_seen: int = 0
    transactions_built: int = 0
    transactions_new: int = 0
    transactions_existing: int = 0
    filing_ids: list[str] = field(default_factory=list)
    parent_events_created: int = 0


# ---------------------------------------------------------------------------
# parent INSIDER_TRANSACTION event on the Task 96A EventStore
# ---------------------------------------------------------------------------
def make_event_lookup(event_store):
    """``accession -> (accepted_at_utc, event_id) | None`` from an existing
    ``INSIDER_TRANSACTION`` ``text_events`` row (so 96D uses the causal
    acceptance instant 96A already recorded)."""

    def _lookup(accession: str):
        eid = make_event_id(
            SourceType.SEC_EDGAR_SUBMISSIONS, accession, EventType.INSIDER_TRANSACTION
        )
        ev = event_store.get_event(eid)
        if ev is None:
            return None
        return ev.accepted_at_utc, ev.event_id

    return _lookup


def ensure_parent_event(event_store, filing: InsiderFiling, *, now: datetime | None = None) -> str:
    """Create (idempotently) the ``INSIDER_TRANSACTION`` parent event for a
    Form 3/4/5 filing on the Task 96A ``EventStore``. Returns its
    ``event_id``. One event per ownership filing -- transactions are NOT
    separate events (avoids alert spam)."""
    now = now or utc_now()
    eid = make_event_id(
        SourceType.SEC_EDGAR_SUBMISSIONS, filing.accession, EventType.INSIDER_TRANSACTION
    )
    if event_store.has_event(eid):
        return eid
    acc = filing.accession
    ev = TextEvent(
        event_id=eid,
        symbol=filing.symbol or "",
        company_name=filing.company_name,
        source_type=SourceType.SEC_EDGAR_SUBMISSIONS,
        source_record_id=acc,
        event_type=EventType.INSIDER_TRANSACTION,
        form_type=filing.form_type.value,
        filing_items=(),
        accession=acc,
        accepted_at_utc=filing.accepted_at_utc,
        filing_date=filing.filing_date,
        report_period_end=filing.period_of_report,
        session_bucket=SessionBucket.UNKNOWN,
        is_amendment=filing.is_amendment,
        source_hash=source_hash(acc, filing.form_type.value, str(filing.n_transactions)),
        ingested_at_utc=now,
        freshness=FreshnessStatus.UNKNOWN,
        data_quality_flags=tuple(filing.data_quality_flags),
        evidence=(
            EvidenceRecord(
                source_provider=SourceType.SEC_FORM345_BULK
                if filing.source_reference.startswith("SEC_FORM345")
                else SourceType.SEC_EDGAR_ARCHIVES,
                source_record_id=acc,
                retrieved_at=now,
                transform="insider_parent_event@v1",
                notes=(
                    f"ownership filing {filing.form_type.value}; "
                    f"{filing.n_transactions} transaction(s), {filing.n_owners} owner(s)"
                ),
            ),
        ),
    )
    event_store.upsert_event(ev)
    return eid


# ---------------------------------------------------------------------------
# ingest
# ---------------------------------------------------------------------------
def ingest_bulk_rows(
    store: InsiderStore,
    *,
    nonderiv_rows: list[dict],
    submissions_rows: list[dict] | None = None,
    owner_rows: list[dict] | None = None,
    deriv_rows: list[dict] | None = None,
    holding_rows: list[dict] | None = None,
    symbols=None,
    issuer_ciks=None,
    event_store=None,
    source_reference: str = "SEC_FORM345_BULK",
    now: datetime | None = None,
) -> InsiderIngestResult:
    tables = BulkTables()
    for r in submissions_rows or []:
        acc = (r.get("ACCESSION_NUMBER") or "").strip()
        if acc:
            tables.submissions[acc] = r
    for attr, rows in (
        ("nonderiv_trans", nonderiv_rows),
        ("owners", owner_rows or []),
        ("deriv_trans", deriv_rows or []),
        ("nonderiv_holding", holding_rows or []),
    ):
        for r in rows or []:
            acc = (r.get("ACCESSION_NUMBER") or "").strip()
            if acc:
                getattr(tables, attr).setdefault(acc, []).append(r)

    lookup = make_event_lookup(event_store) if event_store is not None else None
    out = InsiderIngestResult()
    for filing, txns in parse_row_groups(
        tables,
        symbols=symbols,
        issuer_ciks=issuer_ciks,
        event_lookup=lookup,
        ingested_at_utc=now,
        source_reference=source_reference,
    ):
        eid = None
        if event_store is not None:
            before = event_store.has_event(
                make_event_id(
                    SourceType.SEC_EDGAR_SUBMISSIONS, filing.accession,
                    EventType.INSIDER_TRANSACTION,
                )
            )
            eid = ensure_parent_event(event_store, filing, now=now)
            if not before:
                out.parent_events_created += 1
            filing = filing.model_copy(update={"event_id": eid})
            txns = [t.model_copy(update={"event_id": eid}) for t in txns]

        evidence = [
            EvidenceRecord(
                source_provider=SourceType.SEC_FORM345_BULK,
                source_record_id=filing.accession,
                retrieved_at=now or utc_now(),
                transform=BULK_PARSE_TRANSFORM,
                input_hash=source_hash(filing.accession, str(len(txns))),
                notes=f"{filing.form_type.value}; {len(txns)} transaction row(s) parsed from bulk",
            )
        ]
        new, total = store.upsert_batch(filing, txns, evidence)
        out.filings_seen += 1
        out.transactions_built += total
        out.transactions_new += new
        out.transactions_existing += total - new
        out.filing_ids.append(filing.accession)
    return out


def ingest_form4_xml(
    store: InsiderStore,
    xml_text: str,
    *,
    accession: str,
    accepted_at_utc: datetime | None = None,
    event_store=None,
    symbol_hint: str | None = None,
    form_type_hint: str | None = None,
    source_url: str | None = None,
    now: datetime | None = None,
) -> InsiderIngestResult:
    now = now or utc_now()
    acc = normalize_accession(accession)
    filing, txns = parse_ownership_xml(
        xml_text,
        accession=acc,
        accepted_at_utc=accepted_at_utc,
        symbol_hint=symbol_hint,
        form_type_hint=form_type_hint,
        source_reference=(source_url and f"SEC_EDGAR_ARCHIVES:{source_url}")
        or f"SEC_EDGAR_ARCHIVES:{acc}",
        ingested_at_utc=now,
    )
    out = InsiderIngestResult(filings_seen=1)
    eid = None
    if event_store is not None:
        before = event_store.has_event(
            make_event_id(
                SourceType.SEC_EDGAR_SUBMISSIONS, acc, EventType.INSIDER_TRANSACTION
            )
        )
        eid = ensure_parent_event(event_store, filing, now=now)
        if not before:
            out.parent_events_created += 1
        filing = filing.model_copy(update={"event_id": eid})
        txns = [t.model_copy(update={"event_id": eid}) for t in txns]

    evidence = [
        EvidenceRecord(
            source_provider=SourceType.SEC_EDGAR_ARCHIVES,
            source_record_id=acc,
            source_url=source_url,
            exact_timestamp=accepted_at_utc,
            retrieved_at=now,
            transform=XML_PARSE_TRANSFORM,
            input_hash=source_hash(xml_text),
            notes=f"{filing.form_type.value} ownership XML; {len(txns)} transaction row(s)",
        )
    ]
    new, total = store.upsert_batch(filing, txns, evidence)
    out.transactions_built = total
    out.transactions_new = new
    out.transactions_existing = total - new
    out.filing_ids.append(acc)
    return out


# ---------------------------------------------------------------------------
# aggregate build (from the store)
# ---------------------------------------------------------------------------
def build_insider_activity(
    store: InsiderStore,
    symbol: str,
    *,
    as_of_date: date | None = None,
    windows: tuple[int, ...] = ROLLING_WINDOWS_CALENDAR_DAYS,
    recent_days: int = RECENT_TRANSACTIONS_WINDOW_DAYS,
    latest_limit: int = LATEST_FILINGS_LIMIT,
    now: datetime | None = None,
) -> InsiderActivity:
    now = now or utc_now()
    causal_cutoff = (
        datetime(as_of_date.year, as_of_date.month, as_of_date.day, 23, 59, 59)
        if as_of_date is not None
        else None
    )
    all_txns = store.query_transactions(
        symbol=symbol, causal_cutoff=causal_cutoff, newest_first=False, limit=None
    )
    filings = store.latest_filings(symbol, limit=latest_limit)

    issuer_cik = filings[0].issuer_cik if filings else (all_txns[0].issuer_cik if all_txns else "")
    company = filings[0].company_name if filings else (all_txns[0].company_name if all_txns else "")

    if as_of_date is None:
        cand = [t.transaction_date for t in all_txns if t.transaction_date] + [
            f.filing_date for f in filings if f.filing_date
        ]
        as_of_date = max(cand) if cand else now.date()

    recent = [
        t for t in all_txns
        if t.transaction_date and t.transaction_date >= as_of_date - timedelta(days=recent_days)
    ]

    flags: list[str] = []
    for t in all_txns:
        flags.extend(t.data_quality_flags)
    flag_summary = tuple(sorted(set(flags)))

    n_priced = sum(1 for t in recent if t.is_open_market_discretionary and t.transaction_value is not None)
    n_om = sum(1 for t in recent if t.is_open_market_discretionary)
    note = (
        f"{len(filings)} recent filing(s), {len(all_txns)} transaction(s); "
        f"open-market rows in last {recent_days}d: {n_om} ({n_priced} priced)"
    )
    assert_clean(note)
    evidence = (
        EvidenceRecord(
            source_provider=SourceType.SEC_FORM345_BULK,
            source_record_id=symbol.upper(),
            retrieved_at=now,
            transform=AGGREGATE_TRANSFORM,
            input_hash=source_hash(symbol.upper(), as_of_date.isoformat(), str(len(all_txns))),
            notes=note,
        ),
    )

    return _build_activity(
        symbol=symbol,
        issuer_cik=issuer_cik,
        company_name=company,
        filings=filings,
        transactions=all_txns,
        as_of_date=as_of_date,
        windows=windows,
        recent_transactions=recent,
        latest_filings=filings,
        evidence=evidence,
        data_quality_flags=flag_summary,
    )
