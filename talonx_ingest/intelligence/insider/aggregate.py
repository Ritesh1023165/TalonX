"""
talonx_ingest.intelligence.insider.aggregate
============================================
Deterministic **descriptive** aggregation of open-market (P/S) insider
activity: rolling net value/shares over calendar windows, cluster
detection, and executive/role subsets.

"net" is plain arithmetic (purchases minus sales). It is **not** a signal.
Windows are CALENDAR days keyed on ``transaction_date``; the caller is
responsible for passing only transactions whose filing is already known
as-of the reference date (causality).
"""
from __future__ import annotations

from datetime import date, timedelta

from talonx_ingest.intelligence.insider.config import (
    CLUSTER_MIN_DISTINCT_OWNERS,
    CLUSTER_WINDOW_CALENDAR_DAYS,
    ROLE_SUBSETS,
    ROLLING_WINDOWS_CALENDAR_DAYS,
)
from talonx_ingest.intelligence.insider.domain import (
    InsiderActivity,
    InsiderCluster,
    InsiderFiling,
    InsiderRole,
    InsiderTransaction,
    RoleSubsetAggregate,
    RollingOpenMarketAggregate,
    TransactionClass,
)

__all__ = [
    "rolling_open_market",
    "detect_clusters",
    "role_subset_aggregates",
    "build_insider_activity",
]


def _in_window(t: InsiderTransaction, as_of: date, days: int) -> bool:
    if t.transaction_date is None:
        return False
    return (as_of - timedelta(days=days)) <= t.transaction_date <= as_of


def _open_market(transactions):
    return [t for t in transactions if t.is_open_market_discretionary]


def rolling_open_market(
    transactions: list[InsiderTransaction],
    *,
    as_of_date: date,
    window_calendar_days: int,
) -> RollingOpenMarketAggregate:
    rows = [t for t in _open_market(transactions) if _in_window(t, as_of_date, window_calendar_days)]
    purchases = [t for t in rows if t.classification is TransactionClass.OPEN_MARKET_PURCHASE]
    sales = [t for t in rows if t.classification is TransactionClass.OPEN_MARKET_SALE]

    buy_val = sum(t.transaction_value for t in purchases if t.transaction_value is not None)
    sell_val = sum(t.transaction_value for t in sales if t.transaction_value is not None)
    net_shares = sum(
        t.signed_open_market_shares
        for t in rows
        if t.signed_open_market_shares is not None
    )

    valued = [t for t in rows if t.transaction_value is not None]
    largest = max(valued, key=lambda t: abs(t.transaction_value), default=None)
    n_priced = len(valued)
    note = (
        None
        if n_priced == len(rows)
        else f"{n_priced} of {len(rows)} open-market transactions had a usable price"
    )

    return RollingOpenMarketAggregate(
        window_calendar_days=window_calendar_days,
        as_of_date=as_of_date,
        total_purchase_value=round(float(buy_val), 2),
        total_sale_value=round(float(sell_val), 2),
        net_value=round(float(buy_val) - float(sell_val), 2),
        net_shares=round(float(net_shares), 4),
        distinct_purchasers=len({t.owner_cik for t in purchases if t.owner_cik}),
        distinct_sellers=len({t.owner_cik for t in sales if t.owner_cik}),
        transaction_count=len(rows),
        largest_single_transaction_value=(
            None if largest is None else round(float(largest.transaction_value), 2)
        ),
        largest_single_transaction_id=(None if largest is None else largest.transaction_id),
        purchaser_ciks=tuple(sorted({t.owner_cik for t in purchases if t.owner_cik})),
        seller_ciks=tuple(sorted({t.owner_cik for t in sales if t.owner_cik})),
        value_coverage_note=note,
    )


def detect_clusters(
    transactions: list[InsiderTransaction],
    *,
    as_of_date: date,
    window_calendar_days: int = CLUSTER_WINDOW_CALENDAR_DAYS,
    min_distinct_owners: int = CLUSTER_MIN_DISTINCT_OWNERS,
) -> list[InsiderCluster]:
    rows = [t for t in _open_market(transactions) if _in_window(t, as_of_date, window_calendar_days)]
    out: list[InsiderCluster] = []
    for cls, kind in (
        (TransactionClass.OPEN_MARKET_PURCHASE, "MULTIPLE_OPEN_MARKET_BUYERS"),
        (TransactionClass.OPEN_MARKET_SALE, "MULTIPLE_OPEN_MARKET_SELLERS"),
    ):
        side = [t for t in rows if t.classification is cls]
        owners = {t.owner_cik for t in side if t.owner_cik}
        if len(owners) >= min_distinct_owners:
            vals = [t.transaction_value for t in side if t.transaction_value is not None]
            out.append(
                InsiderCluster(
                    kind=kind,
                    window_calendar_days=window_calendar_days,
                    as_of_date=as_of_date,
                    distinct_owners=len(owners),
                    owner_ciks=tuple(sorted(owners)),
                    transaction_count=len(side),
                    total_value=round(float(sum(vals)), 2) if vals else None,
                )
            )
    return out


def _role_predicate(subset: str):
    if subset == "CEO":
        return lambda t: InsiderRole.CEO in t.owner_roles
    if subset == "CFO":
        return lambda t: InsiderRole.CFO in t.owner_roles
    if subset == "CEO_CFO":
        return lambda t: (InsiderRole.CEO in t.owner_roles) or (InsiderRole.CFO in t.owner_roles)
    if subset == "DIRECTORS":
        return lambda t: InsiderRole.DIRECTOR in t.owner_roles
    if subset == "ALL_OFFICERS":
        return lambda t: t.is_officer
    return lambda t: False


def role_subset_aggregates(
    transactions: list[InsiderTransaction],
    *,
    as_of_date: date,
    window_calendar_days: int,
) -> list[RoleSubsetAggregate]:
    rows = [t for t in _open_market(transactions) if _in_window(t, as_of_date, window_calendar_days)]
    out: list[RoleSubsetAggregate] = []
    for subset in ROLE_SUBSETS:
        pred = _role_predicate(subset)
        sub = [t for t in rows if pred(t)]
        purchases = [t for t in sub if t.classification is TransactionClass.OPEN_MARKET_PURCHASE]
        sales = [t for t in sub if t.classification is TransactionClass.OPEN_MARKET_SALE]
        buy_val = sum(t.transaction_value for t in purchases if t.transaction_value is not None)
        sell_val = sum(t.transaction_value for t in sales if t.transaction_value is not None)
        net_shares = sum(
            t.signed_open_market_shares for t in sub if t.signed_open_market_shares is not None
        )
        out.append(
            RoleSubsetAggregate(
                subset=subset,
                window_calendar_days=window_calendar_days,
                as_of_date=as_of_date,
                purchase_count=len(purchases),
                sale_count=len(sales),
                net_value=round(float(buy_val) - float(sell_val), 2),
                net_shares=round(float(net_shares), 4),
                distinct_owners=len({t.owner_cik for t in sub if t.owner_cik}),
                owner_ciks=tuple(sorted({t.owner_cik for t in sub if t.owner_cik})),
            )
        )
    return out


def build_insider_activity(
    *,
    symbol: str,
    issuer_cik: str,
    company_name: str,
    filings: list[InsiderFiling],
    transactions: list[InsiderTransaction],
    as_of_date: date | None = None,
    windows: tuple[int, ...] = ROLLING_WINDOWS_CALENDAR_DAYS,
    recent_transactions: list[InsiderTransaction] | None = None,
    latest_filings: list[InsiderFiling] | None = None,
    evidence: tuple = (),
    data_quality_flags: tuple[str, ...] = (),
) -> InsiderActivity:
    if as_of_date is None:
        cand = [t.transaction_date for t in transactions if t.transaction_date] + [
            f.filing_date for f in filings if f.filing_date
        ]
        as_of_date = max(cand) if cand else date.today()

    role_subs: list[RoleSubsetAggregate] = []
    for w in windows:
        role_subs.extend(
            role_subset_aggregates(transactions, as_of_date=as_of_date, window_calendar_days=w)
        )

    return InsiderActivity(
        symbol=symbol.upper(),
        issuer_cik=issuer_cik,
        company_name=company_name,
        as_of_date=as_of_date,
        latest_filings=tuple(latest_filings if latest_filings is not None else filings),
        transactions=tuple(
            recent_transactions if recent_transactions is not None else transactions
        ),
        open_market_aggregates=tuple(
            rolling_open_market(transactions, as_of_date=as_of_date, window_calendar_days=w)
            for w in windows
        ),
        clusters=tuple(detect_clusters(transactions, as_of_date=as_of_date)),
        role_subsets=tuple(role_subs),
        data_quality_flags=tuple(data_quality_flags),
        evidence=tuple(evidence),
    )
