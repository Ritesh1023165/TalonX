"""
tests/test_dashboard_readapi.py
-------------------------------
Task 96G -- the read/service layer: canonical stores queried without
recomputation, deterministic pagination, joins, filters.
"""
from __future__ import annotations

from datetime import timedelta

import pytest

from talonx_ingest.intelligence.domain import EventType, SignificanceBand
from _dashboard_helpers import NOW, mk_comparison, mk_event, seeded_api


@pytest.fixture
def api(tmp_path):
    a = seeded_api(tmp_path / "ledger.db")
    yield a
    a.close()


def test_latest_and_ranked_events(api):
    latest = api.latest_events(limit=10)
    assert {r["symbol"] for r in latest} == {"KO", "MSFT", "AAPL", "NVDA"}
    ranked = api.ranked_events(limit=10)["items"]
    # ordered by score desc; the pinned multi-item restructuring (AAPL) leads
    scores = [r["score"] for r in ranked if r["score"] is not None]
    assert scores == sorted(scores, reverse=True)
    assert ranked[0]["symbol"] == "AAPL"


def test_ranked_events_pagination_is_deterministic(api):
    p1 = api.ranked_events(limit=2)
    p2 = api.ranked_events(limit=2, cursor=p1["next_cursor"])
    ids1 = [r["event_id"] for r in p1["items"]]
    ids2 = [r["event_id"] for r in p2["items"]]
    assert len(ids1) == 2 and not set(ids1) & set(ids2)          # no overlap
    # re-fetch page 1 -> identical
    assert [r["event_id"] for r in api.ranked_events(limit=2)["items"]] == ids1


def test_band_and_reasons_come_from_the_store_not_recomputed(api):
    row = next(r for r in api.latest_events(limit=10) if r["symbol"] == "AAPL")
    stored = api.significance.get_for_event(row["event_id"])
    assert row["band"] == stored.band.value
    assert row["score"] == stored.score
    assert row["significance_reasons"] == [r.description for r in stored.reasons]
    assert row["significance_ruleset"] == stored.ruleset_version


def test_unscored_event_has_null_band(tmp_path):
    a = seeded_api(
        tmp_path / "l.db",
        spec=[dict(event_type=EventType.EARNINGS_RESULTS, symbol="AAPL", accession="0000320193-26-000009",
                   skip_significance=True)],
    )
    row = a.latest_events(limit=5)[0]
    assert row["band"] is None and row["score"] is None and row["significance_reasons"] == []
    a.close()


def test_events_by_symbol_and_type(api):
    assert {r["event_id"] for r in api.latest_events(symbol="MSFT")} == {
        "SEC:0000789019-26-000002:EARNINGS_RESULTS"
    }
    r = api.ranked_events(event_type=EventType.EARNINGS_RESULTS.value)
    assert all(x["event_type"] == "EARNINGS_RESULTS" for x in r["items"])


def test_filing_comparison_detail(tmp_path):
    ev = mk_event(event_type=EventType.QUARTERLY_FILING, form_type="10-Q", items=(),
                  accession="0000320193-26-000050")
    fc = mk_comparison(event=ev, rf_diff=0.44, revenue_rel_delta=0.24, neg_kw_delta=6)
    a = seeded_api(
        tmp_path / "l.db",
        spec=[dict(event_type=EventType.QUARTERLY_FILING, symbol="AAPL", form_type="10-Q", items=(),
                   accession="0000320193-26-000050", comparison=fc, on_watchlist=True)],
    )
    row = a.latest_events(limit=5)[0]
    assert row["has_comparison"] and row["comparison_id"] == fc.comparison_id
    wc = a.comparison_detail(fc.comparison_id)
    assert wc["symbol"] == "AAPL"
    assert wc["sections"]["risk_factors"]["diff_ratio"] == 0.44
    assert any(x["field"] == "revenue" for x in wc["xbrl"])
    assert "evidence" in wc
    a.close()


def test_freshness_state_is_honest(api):
    fs = api.freshness_state()
    # never polled -> UNKNOWN, never fabricated as DOWN
    assert fs["overall"] in ("UNKNOWN", "FRESH")
    assert fs["counts"]["events"] == 4
    assert fs["counts"]["scored_events"] == 4
    assert {s["source"] for s in fs["sources"]} >= {"SEC_EDGAR_SUBMISSIONS"}


def test_watchlist_ranked_orders_by_significance_only(api):
    rows = api.watchlist_ranked(["AAPL", "MSFT", "KO", "TSLA"], pinned={"AAPL"})
    syms = [r["symbol"] for r in rows]
    assert syms[0] == "AAPL"                       # highest band in window
    assert rows[-1]["symbol"] == "TSLA" and rows[-1]["is_quiet"]  # no events -> quiet, last
    assert all("why" in r for r in rows)
    # no price / return field anywhere
    blob = str(rows)
    assert "expected_return" not in blob and "price_target" not in blob


def test_filings_filters(api):
    all_f = api.filings(limit=50)
    assert all(r["form_type"].startswith(("8-K", "10-Q", "10-K")) for r in all_f["items"])
    # 5.07 vote-result 8-K is included as a filing but not "material" panel; item filter works
    by_item = api.filings(item="2.05")
    assert by_item["items"] and all("2.05" in r["filing_items"] for r in by_item["items"])
    by_band = api.filings(band="LOW")
    assert all(r["band"] == "LOW" for r in by_band["items"])


def test_company_overview(api):
    co = api.company_overview("AAPL")
    assert co["symbol"] == "AAPL"
    assert co["event_count"] == 1
    assert co["latest_band"] in ("HIGH", "CRITICAL", "MEDIUM")
    assert co["timeline"][0]["event_type"] == "RESTRUCTURING"


def test_evidence_trace(api):
    row = api.latest_events(symbol="AAPL")[0]
    tr = api.evidence_trace(row["event_id"])
    assert tr["accession"] == "0000320193-26-000003"
    assert tr["event_evidence"]                      # 96A provenance records
    assert tr["significance"]["band"] == row["band"]
    assert tr["significance"]["input_fingerprint"]


def test_today_window(api):
    t = api.today()
    ids = [r["event_id"] for r in t["attention_feed"]]
    # the 30h-old KO vote-result is inside the 36h window; ordering is by score
    assert "SEC:0000320193-26-000003:RESTRUCTURING" == ids[0]
    assert set(t.keys()) >= {"attention_feed", "earnings", "material_filings", "insider_activity", "freshness"}
