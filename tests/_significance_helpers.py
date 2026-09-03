"""
tests/_significance_helpers.py
-----------------------------
Shared builders for the Task 96E significance tests. Not a test module.
"""
from __future__ import annotations

from datetime import date, datetime, timedelta, timezone

from talonx_ingest.intelligence.comparison.domain import (
    FilingComparison,
    KeywordCategory,
    KeywordCategorySummary,
    SectionChange,
    SectionStatus,
    SectionType,
    WholeDocumentChange,
    XbrlChange,
    XbrlPeriodComparison,
)
from talonx_ingest.intelligence.domain import (
    EventType,
    FreshnessStatus,
    SessionBucket,
    SourceType,
    TextEvent,
)
from talonx_ingest.intelligence.insider.domain import (
    AcquiredDisposed,
    InsiderActivity,
    InsiderCluster,
    InsiderRole,
    InsiderTransaction,
    OwnershipNature,
    RollingOpenMarketAggregate,
    TransactionClass,
)

UTC = timezone.utc
NOW = datetime(2026, 9, 3, 15, 0, 0, tzinfo=UTC)


def mk_event(
    *,
    event_type: EventType = EventType.EARNINGS_RESULTS,
    symbol: str = "AAPL",
    accession: str = "0000320193-26-000101",
    form_type: str = "8-K",
    items: tuple[str, ...] = ("2.02", "9.01"),
    accepted_at: datetime | None = None,
    age_hours: float | None = None,
    quality_flags: tuple[str, ...] = (),
    is_amendment: bool = False,
    now: datetime = NOW,
) -> TextEvent:
    if accepted_at is None:
        hrs = 1.0 if age_hours is None else age_hours
        accepted_at = now - timedelta(hours=hrs)
    return TextEvent(
        event_id=f"SEC:{accession}:{event_type.value}",
        symbol=symbol,
        company_name=f"{symbol} Inc.",
        source_type=SourceType.SEC_EDGAR_SUBMISSIONS,
        source_record_id=accession,
        event_type=event_type,
        form_type=form_type,
        filing_items=items,
        accession=accession,
        accepted_at_utc=accepted_at,
        session_bucket=SessionBucket.RTH,
        ingested_at_utc=now,
        freshness=FreshnessStatus.FRESH,
        is_amendment=is_amendment,
        data_quality_flags=quality_flags,
    )


def mk_comparison(
    *,
    event: TextEvent,
    prior_accession: str = "0000320193-25-000090",
    rf_diff: float | None = None,
    mdna_diff: float | None = None,
    liq_diff: float | None = None,
    whole_diff: float | None = None,
    rf_status: SectionStatus = SectionStatus.FOUND,
    revenue_rel_delta: float | None = None,
    eps_rel_delta: float | None = None,
    neg_kw_delta: int | None = None,
    quality_flags: tuple[str, ...] = (),
    now: datetime = NOW,
) -> FilingComparison:
    sections = []
    for st, dr in (
        (SectionType.RISK_FACTORS, rf_diff),
        (SectionType.MDNA, mdna_diff),
        (SectionType.LIQUIDITY, liq_diff),
    ):
        if dr is None:
            continue
        sections.append(
            SectionChange(
                section_type=st,
                status=rf_status if st is SectionType.RISK_FACTORS else SectionStatus.FOUND,
                prior_present=True,
                current_present=True,
                diff_ratio=dr,
                quick_ratio=1.0 - dr,
                material_threshold=0.1,
                exceeds_material_threshold=dr >= 0.1,
            )
        )
    xbrl = []
    if revenue_rel_delta is not None:
        xbrl.append(
            XbrlChange(
                field="revenue",
                comparison=XbrlPeriodComparison.YOY,
                relative_delta=revenue_rel_delta,
                absolute_delta=revenue_rel_delta * 1e9,
                status="FOUND",
            )
        )
    if eps_rel_delta is not None:
        xbrl.append(
            XbrlChange(
                field="eps_diluted",
                comparison=XbrlPeriodComparison.YOY,
                relative_delta=eps_rel_delta,
                status="FOUND",
            )
        )
    kw_summaries = ()
    if neg_kw_delta is not None:
        kw_summaries = (
            KeywordCategorySummary(
                category=KeywordCategory.NEGATIVE_RISK,
                prior_total=10,
                current_total=10 + neg_kw_delta,
                total_delta=neg_kw_delta,
                terms_increased=("impairment", "litigation") if neg_kw_delta > 0 else (),
            ),
        )
    whole = None
    if whole_diff is not None:
        whole = WholeDocumentChange(
            prior_word_count=1000,
            current_word_count=1100,
            word_count_delta=100,
            prior_char_count=6000,
            current_char_count=6600,
            char_count_delta=600,
            quick_ratio=1.0 - whole_diff,
            diff_ratio=whole_diff,
            added_word_count=100,
            removed_word_count=50,
            changed_fraction=whole_diff,
            material_threshold=0.1339,
            exceeds_material_threshold=whole_diff >= 0.1339,
        )
    return FilingComparison(
        comparison_id=f"CMP:{event.accession}:{prior_accession}:filing_comparison@v1",
        symbol=event.symbol,
        company_name=event.company_name,
        current_event_id=event.event_id,
        prior_event_id=f"SEC:{prior_accession}:{event.event_type.value}",
        current_accession=event.accession,
        prior_accession=prior_accession,
        form_type=event.form_type,
        base_form=event.form_type.replace("/A", ""),
        current_accepted_at_utc=event.accepted_at_utc,
        prior_accepted_at_utc=now - timedelta(days=365),
        whole_document_change=whole,
        section_changes=tuple(sections),
        xbrl_changes=tuple(xbrl),
        keyword_category_summaries=kw_summaries,
        data_quality_flags=quality_flags,
        created_at_utc=now,
    )


def _txn(tid, cls, shares, value, tdate, owner, roles=(InsiderRole.OFFICER,)):
    signed = (
        shares
        if cls is TransactionClass.OPEN_MARKET_PURCHASE
        else (-shares if cls is TransactionClass.OPEN_MARKET_SALE else None)
    )
    return InsiderTransaction(
        transaction_id=tid,
        accession="0000320193-26-000200",
        issuer_cik="0000320193",
        symbol="AAPL",
        company_name="AAPL Inc.",
        classification=cls,
        transaction_code={"P": "P", "S": "S"}.get(
            "P" if cls is TransactionClass.OPEN_MARKET_PURCHASE else "S", None
        ),
        transaction_shares=float(shares),
        price_per_share=(value / shares) if value else None,
        transaction_value=value,
        transaction_date=tdate,
        owner_cik=owner,
        owner_role=roles[0],
        owner_roles=roles,
        is_officer=True,
        acquired_disposed=AcquiredDisposed.DISPOSED,
        ownership_nature=OwnershipNature.DIRECT,
        signed_open_market_shares=signed,
    )


def mk_insider_activity(
    *,
    largest_value: float | None = None,
    cluster: bool = False,
    quality_flags: tuple[str, ...] = (),
    as_of: date = NOW.date(),
) -> InsiderActivity:
    aggs = []
    txns = []
    for w in (10, 30, 90):
        aggs.append(
            RollingOpenMarketAggregate(
                window_calendar_days=w,
                as_of_date=as_of,
                total_purchase_value=0.0,
                total_sale_value=largest_value or 0.0,
                net_value=-(largest_value or 0.0),
                net_shares=-100.0,
                distinct_sellers=2 if cluster else 1,
                distinct_purchasers=0,
                transaction_count=2 if cluster else 1,
                largest_single_transaction_value=largest_value,
                largest_single_transaction_id="tx-largest" if largest_value else None,
            )
        )
    clusters = ()
    if cluster:
        clusters = (
            InsiderCluster(
                kind="MULTIPLE_OPEN_MARKET_SELLERS",
                window_calendar_days=30,
                as_of_date=as_of,
                distinct_owners=2,
                owner_ciks=("o1", "o2"),
                transaction_count=2,
                total_value=largest_value,
            ),
        )
    if largest_value:
        txns = [
            _txn("tx-largest", TransactionClass.OPEN_MARKET_SALE, 1000, largest_value, as_of, "o1")
        ]
    return InsiderActivity(
        symbol="AAPL",
        issuer_cik="0000320193",
        company_name="AAPL Inc.",
        as_of_date=as_of,
        transactions=tuple(txns),
        open_market_aggregates=tuple(aggs),
        clusters=clusters,
        data_quality_flags=quality_flags,
    )


class FakeEventStore:
    """Minimal in-memory stand-in for EventStore.query_events used by the
    rarity + simultaneous-event helpers."""

    def __init__(self, events: list[TextEvent] | None = None):
        self._events = list(events or [])

    def add(self, ev: TextEvent) -> None:
        self._events.append(ev)

    def query_events(
        self,
        *,
        symbol=None,
        event_type=None,
        form_type=None,
        since=None,
        until=None,
        limit=None,
        newest_first=True,
    ):
        def _u(dt):
            if dt is None:
                return None
            return dt if dt.tzinfo else dt.replace(tzinfo=UTC)

        rows = []
        for e in self._events:
            if symbol and e.symbol != symbol.upper():
                continue
            if event_type is not None:
                etv = getattr(event_type, "value", event_type)
                if e.event_type.value != etv:
                    continue
            if form_type and e.form_type != form_type:
                continue
            if since is not None and (e.accepted_at_utc is None or _u(e.accepted_at_utc) < _u(since)):
                continue
            if until is not None and (e.accepted_at_utc is None or _u(e.accepted_at_utc) > _u(until)):
                continue
            rows.append(e)
        rows.sort(
            key=lambda e: (e.accepted_at_utc or datetime.min.replace(tzinfo=UTC)),
            reverse=newest_first,
        )
        return rows[:limit] if limit is not None else rows
