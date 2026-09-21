"""
tests/test_dashboard_pages.py
-----------------------------
Task 96G -- Phase 26 fixture matrix: LOW / MEDIUM / HIGH / CRITICAL /
insider / missing-comparison / stale / partial / empty, each rendered
through the real route stack.
"""
from __future__ import annotations

import pytest

from talonx_ingest.intelligence.dashboard.claim_safety import scan_page
from talonx_ingest.intelligence.dashboard.routes import handle
from talonx_ingest.intelligence.domain import EventType, SignificanceBand
from talonx_ingest.intelligence.significance.rarity import RarityResult
from _dashboard_helpers import NOW, mk_comparison, mk_event, seeded_api


def _page(api, path, q=None):
    r = handle(api, "GET", path, q or {})
    assert r.status == 200, (path, r.status)
    assert scan_page(r.body) == []
    assert "Information, not advice" in r.body
    return r.body


def test_low_event_minimal_card(tmp_path):
    a = seeded_api(
        tmp_path / "l.db",
        spec=[dict(event_type=EventType.SHAREHOLDER_VOTE_RESULT, symbol="KO", items=("5.07",),
                   accession="0000021344-26-000001", age_hours=5)],
    )
    body = _page(a, "/event/SEC:0000021344-26-000001:SHAREHOLDER_VOTE_RESULT")
    assert ">LOW<" in body or "LOW</span>" in body
    assert "INFORMATION SIGNIFICANCE" in body
    a.close()


def test_medium_earnings_event(tmp_path):
    a = seeded_api(
        tmp_path / "l.db",
        spec=[dict(event_type=EventType.EARNINGS_RESULTS, symbol="MSFT", items=("2.02", "9.01"),
                   accession="0000789019-26-000002", age_hours=1, on_watchlist=True)],
    )
    body = _page(a, "/")
    assert "Earnings / results" in body
    assert "MEDIUM" in body or "HIGH" in body
    a.close()


def test_high_filing_change_event(tmp_path):
    ev = mk_event(event_type=EventType.QUARTERLY_FILING, form_type="10-Q", items=(),
                  accession="0000320193-26-000070")
    fc = mk_comparison(event=ev, rf_diff=0.7, mdna_diff=0.3, revenue_rel_delta=0.24, neg_kw_delta=8)
    a = seeded_api(
        tmp_path / "l.db",
        spec=[dict(event_type=EventType.QUARTERLY_FILING, symbol="AAPL", form_type="10-Q", items=(),
                   accession="0000320193-26-000070", comparison=fc, on_watchlist=True)],
    )
    body = _page(a, "/event/SEC:0000320193-26-000070:QUARTERLY_FILING")
    assert "HIGH" in body
    assert "Risk Factors: changed above the frozen material threshold" in body
    assert "What changed" in body
    # filing comparison detail drill-down
    detail = _page(a, f"/filing/{fc.comparison_id}")
    assert "Section-level changes" in detail
    a.close()


def test_critical_multi_factor_event(tmp_path):
    ev = mk_event(event_type=EventType.ANNUAL_FILING, form_type="10-K", items=(),
                  accession="0000320193-26-000080")
    fc = mk_comparison(event=ev, rf_diff=0.7, mdna_diff=0.4, whole_diff=0.4,
                       revenue_rel_delta=-0.6, eps_rel_delta=0.9, neg_kw_delta=25)
    from talonx_ingest.intelligence.significance import evaluate_significance

    a = seeded_api(tmp_path / "l.db", spec=[])
    a.events.upsert_event(ev)
    a.comparisons.upsert_comparison(fc)
    sig = evaluate_significance(
        ev, comparison=fc, rarity_result=RarityResult("UNCOMMON", 1, "d", 0, 1, NOW),
        simultaneous_type_count=2, pinned=True, on_watchlist=True, now=NOW,
    )
    assert sig.band is SignificanceBand.CRITICAL
    a.significance.upsert(sig)
    body = _page(a, "/event/SEC:0000320193-26-000080:ANNUAL_FILING")
    assert "CRITICAL" in body
    assert "Why this is significant" in body
    a.close()


def test_insider_activity_view(tmp_path):
    from talonx_ingest.intelligence.insider.domain import (
        AcquiredDisposed, InsiderRole, InsiderTransaction, OwnershipFormType,
        OwnershipNature, TransactionClass,
    )

    a = seeded_api(
        tmp_path / "l.db",
        spec=[dict(event_type=EventType.INSIDER_TRANSACTION, symbol="NVDA", items=(), form_type="4",
                   accession="0001045810-26-000004", age_hours=5)],
    )
    for i, (cls, code) in enumerate([(TransactionClass.OPEN_MARKET_SALE, "S"),
                                     (TransactionClass.GRANT_OR_AWARD, "A")]):
        a.insider.upsert_transaction(InsiderTransaction(
            transaction_id=f"F4TX:0001045810-26-000004:{i}",
            accession="0001045810-26-000004", issuer_cik="0001045810", symbol="NVDA",
            company_name="NVIDIA Corp",
            transaction_date=NOW.date(),
            owner_name="A Person", owner_role=InsiderRole.CEO, owner_roles=(InsiderRole.CEO,),
            is_officer=True, form_type=OwnershipFormType.FORM_4,
            transaction_code=code, classification=cls,
            transaction_shares=1000.0, price_per_share=100.0,
            transaction_value=(100000.0 if cls is TransactionClass.OPEN_MARKET_SALE else None),
            acquired_disposed=AcquiredDisposed.DISPOSED, ownership_nature=OwnershipNature.DIRECT,
            signed_open_market_shares=(-1000.0 if cls is TransactionClass.OPEN_MARKET_SALE else None),
        ))
    body = _page(a, "/company/NVDA")
    assert "OPEN-MARKET (discretionary P / S)" in body
    assert "OTHER / ADMINISTRATIVE" in body
    assert "bullish" not in body.lower() and "bearish" not in body.lower()
    a.close()


def test_missing_comparison_is_graceful(tmp_path):
    a = seeded_api(
        tmp_path / "l.db",
        spec=[dict(event_type=EventType.QUARTERLY_FILING, symbol="AAPL", form_type="10-Q", items=(),
                   accession="0000320193-26-000090", on_watchlist=True)],  # no comparison
    )
    body = _page(a, "/company/AAPL")
    assert "Event timeline" in body
    # no comparison section crash; filings page shows n/a
    f = _page(a, "/filings")
    assert "n/a" in f
    a.close()


def test_partial_data_quality_flags_shown(tmp_path):
    ev = mk_event(event_type=EventType.QUARTERLY_FILING, form_type="10-Q", items=(),
                  accession="0000320193-26-000091",
                  quality_flags=("missing_acceptance_timestamp",))
    fc = mk_comparison(event=ev, rf_diff=0.5, quality_flags=("section_not_found", "xbrl_unavailable"))
    a = seeded_api(
        tmp_path / "l.db",
        spec=[dict(event_type=EventType.QUARTERLY_FILING, symbol="AAPL", form_type="10-Q", items=(),
                   accession="0000320193-26-000091", comparison=fc, quality_flags=("missing_acceptance_timestamp",))],
    )
    body = _page(a, "/event/SEC:0000320193-26-000091:QUARTERLY_FILING")
    assert "SEC acceptance time missing" in body
    detail = _page(a, f"/filing/{fc.comparison_id}")
    assert "a section could not be located" in detail or "XBRL financial data was unavailable" in detail
    a.close()


def test_empty_dashboard(tmp_path):
    a = seeded_api(tmp_path / "l.db", spec=[])
    body = _page(a, "/")
    assert "No material SEC events recorded in the current window." in body
    wl = handle(a, "GET", "/watchlist", {})
    assert "No watchlist symbols configured" in wl.body
    a.close()
