"""
tests/test_insider_aggregate.py
-------------------------------
Task 96D -- descriptive rolling P/S aggregates, clusters, role subsets.
"""
from __future__ import annotations

from datetime import date

from talonx_ingest.intelligence.insider.aggregate import (
    build_insider_activity,
    detect_clusters,
    role_subset_aggregates,
    rolling_open_market,
)
from talonx_ingest.intelligence.insider.domain import (
    AcquiredDisposed,
    InsiderRole,
    InsiderTransaction,
    OwnershipNature,
    TransactionClass,
)

_ASOF = date(2026, 3, 1)


def _tx(tid, cls, shares, value, tdate, owner, roles=(InsiderRole.OFFICER,), officer=True):
    signed_sh = shares if cls is TransactionClass.OPEN_MARKET_PURCHASE else (
        -shares if cls is TransactionClass.OPEN_MARKET_SALE else None
    )
    signed_val = None
    if cls is TransactionClass.OPEN_MARKET_PURCHASE:
        signed_val = value
    elif cls is TransactionClass.OPEN_MARKET_SALE:
        signed_val = None if value is None else -value
    return InsiderTransaction(
        transaction_id=tid,
        accession="0000000000-26-000001",
        issuer_cik="0000320193",
        symbol="AAPL",
        classification=cls,
        transaction_code="S" if cls is TransactionClass.OPEN_MARKET_SALE else "P",
        transaction_shares=float(shares),
        transaction_value=value,
        transaction_date=tdate,
        owner_cik=owner,
        owner_role=roles[0],
        owner_roles=roles,
        is_officer=officer,
        acquired_disposed=AcquiredDisposed.DISPOSED,
        ownership_nature=OwnershipNature.DIRECT,
        signed_open_market_shares=signed_sh,
        signed_open_market_value=signed_val,
    )


def test_rolling_net_value_and_counts():
    txns = [
        _tx("a", TransactionClass.OPEN_MARKET_SALE, 1000, 200_000.0, date(2026, 2, 20), "o1"),
        _tx("b", TransactionClass.OPEN_MARKET_SALE, 500, 100_000.0, date(2026, 2, 25), "o2"),
        _tx("c", TransactionClass.OPEN_MARKET_PURCHASE, 300, 60_000.0, date(2026, 2, 27), "o3"),
        # grant -> excluded
        _tx("d", TransactionClass.GRANT_OR_AWARD, 10000, None, date(2026, 2, 26), "o1"),
    ]
    agg = rolling_open_market(txns, as_of_date=_ASOF, window_calendar_days=30)
    assert agg.total_sale_value == 300_000.0
    assert agg.total_purchase_value == 60_000.0
    assert agg.net_value == -240_000.0
    assert agg.net_shares == -1200.0        # -1000 -500 +300
    assert agg.distinct_sellers == 2
    assert agg.distinct_purchasers == 1
    assert agg.transaction_count == 3        # grant excluded
    assert agg.largest_single_transaction_value == 200_000.0
    assert agg.largest_single_transaction_id == "a"


def test_window_excludes_older_transactions():
    txns = [
        _tx("old", TransactionClass.OPEN_MARKET_SALE, 1000, 200_000.0, date(2026, 1, 1), "o1"),
        _tx("new", TransactionClass.OPEN_MARKET_SALE, 100, 20_000.0, date(2026, 2, 25), "o2"),
    ]
    a10 = rolling_open_market(txns, as_of_date=_ASOF, window_calendar_days=10)
    a90 = rolling_open_market(txns, as_of_date=_ASOF, window_calendar_days=90)
    assert a10.transaction_count == 1 and a10.total_sale_value == 20_000.0
    assert a90.transaction_count == 2


def test_missing_price_coverage_note():
    txns = [
        _tx("a", TransactionClass.OPEN_MARKET_SALE, 1000, 200_000.0, date(2026, 2, 20), "o1"),
        _tx("b", TransactionClass.OPEN_MARKET_SALE, 500, None, date(2026, 2, 25), "o2"),
    ]
    agg = rolling_open_market(txns, as_of_date=_ASOF, window_calendar_days=30)
    assert agg.transaction_count == 2
    assert agg.total_sale_value == 200_000.0
    assert "1 of 2" in agg.value_coverage_note


def test_cluster_detection_sellers_and_buyers():
    sells = [
        _tx(f"s{i}", TransactionClass.OPEN_MARKET_SALE, 100, 10_000.0, date(2026, 2, 20), f"o{i}")
        for i in range(3)
    ]
    buys = [
        _tx(f"b{i}", TransactionClass.OPEN_MARKET_PURCHASE, 100, 10_000.0, date(2026, 2, 21), f"p{i}")
        for i in range(1)   # only one buyer -> no buy cluster
    ]
    clusters = detect_clusters(sells + buys, as_of_date=_ASOF, window_calendar_days=30)
    kinds = {c.kind for c in clusters}
    assert kinds == {"MULTIPLE_OPEN_MARKET_SELLERS"}
    sc = next(c for c in clusters if c.kind == "MULTIPLE_OPEN_MARKET_SELLERS")
    assert sc.distinct_owners == 3
    assert sc.total_value == 30_000.0


def test_no_cluster_below_threshold():
    txns = [_tx("s0", TransactionClass.OPEN_MARKET_SALE, 100, 10_000.0, date(2026, 2, 20), "o0")]
    assert detect_clusters(txns, as_of_date=_ASOF, window_calendar_days=30) == []


def test_role_subsets():
    txns = [
        _tx("ceo", TransactionClass.OPEN_MARKET_SALE, 1000, 200_000.0, date(2026, 2, 20), "c1",
            roles=(InsiderRole.CEO,)),
        _tx("cfo", TransactionClass.OPEN_MARKET_SALE, 500, 100_000.0, date(2026, 2, 21), "c2",
            roles=(InsiderRole.CFO,)),
        _tx("dir", TransactionClass.OPEN_MARKET_PURCHASE, 200, 40_000.0, date(2026, 2, 22), "d1",
            roles=(InsiderRole.DIRECTOR,), officer=False),
    ]
    subs = {s.subset: s for s in role_subset_aggregates(txns, as_of_date=_ASOF, window_calendar_days=30)}
    assert subs["CEO"].sale_count == 1 and subs["CEO"].net_value == -200_000.0
    assert subs["CFO"].sale_count == 1
    assert subs["CEO_CFO"].sale_count == 2 and subs["CEO_CFO"].net_value == -300_000.0
    assert subs["DIRECTORS"].purchase_count == 1 and subs["DIRECTORS"].net_value == 40_000.0
    assert subs["ALL_OFFICERS"].sale_count == 2


def test_build_activity_wires_everything():
    txns = [
        _tx("a", TransactionClass.OPEN_MARKET_SALE, 1000, 200_000.0, date(2026, 2, 20), "o1"),
        _tx("b", TransactionClass.OPEN_MARKET_SALE, 500, 100_000.0, date(2026, 2, 25), "o2"),
    ]
    act = build_insider_activity(
        symbol="AAPL", issuer_cik="0000320193", company_name="Apple Inc.",
        filings=[], transactions=txns, as_of_date=_ASOF,
    )
    assert {a.window_calendar_days for a in act.open_market_aggregates} == {10, 30, 90}
    assert any(c.kind == "MULTIPLE_OPEN_MARKET_SELLERS" for c in act.clusters)
    assert act.as_of_date == _ASOF
