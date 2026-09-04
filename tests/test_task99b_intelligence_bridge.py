"""Task 99B -- live intelligence bridge (earnings RADAR + post-earnings).
Focused areas: RADAR milestone/dedup/date-shift, post-earnings row build from
96C/96D/96E, descriptive-only (no predictive language), reply detail
provenance, overnight events, bridge health, idempotency. A FakeIntelAPI keeps
the core tests offline+deterministic; a guarded replay test exercises the real
96A store when `_replay_ledger.db` is present. TEST_FIXTURE_ONLY -- NOT ALPHA
EVIDENCE.
"""

from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from talonx_signals.alert_store import ExperimentalAlertStore
from talonx_signals.dispatcher import ExperimentalDispatcher, RecordingSender
from talonx_signals.intelligence_bridge import (
    BridgeMetrics,
    EarningsRadarBridge,
    PostEarningsBridge,
    bridge_health,
    overnight_event_labels,
)
from talonx_signals.renderers import (
    assert_no_predictive_language,
    render_event_update,
    render_event_update_details,
    render_radar,
    render_radar_details,
)

NOW = datetime(2026, 8, 20, 12, 0, tzinfo=timezone.utc)


# ---------------------------------------------------------------------------
# Fake 96A/B read API
# ---------------------------------------------------------------------------

class FakeIntelAPI:
    def __init__(self):
        self._earnings = {
            "event_id": "SEC:0000320193-26-000011:EARNINGS_RESULTS",
            "symbol": "AAPL", "company_name": "Apple Inc.",
            "event_type": "EARNINGS_RESULTS", "form_type": "8-K",
            "filing_items": ["2.02", "9.01"], "accession": "0000320193-26-000011",
            "accepted_at_utc": "2026-08-19T20:31:00+00:00", "session_bucket": "AMC",
            "band": "HIGH", "score": 6,
            "significance_reasons": [
                "results-of-operations 8-K (Item 2.02)",
                "2 distinct disclosure types within 7 days",
                "this company is on your watchlist (user priority, not market significance)",
            ],
            "filing_index_url": "https://www.sec.gov/.../index.json",
            "primary_document_url": "https://www.sec.gov/.../a8k.htm",
        }
        self._tenq = {
            "event_id": "SEC:0000320193-26-000020:QUARTERLY_FILING",
            "symbol": "AAPL", "company_name": "Apple Inc.",
            "event_type": "QUARTERLY_FILING", "form_type": "10-Q",
            "filing_items": [], "accession": "0000320193-26-000020",
            "accepted_at_utc": "2026-08-19T21:05:00+00:00", "session_bucket": "AMC",
            "band": "HIGH", "score": 7,
            "significance_reasons": ["10-Q filed"],
            "filing_index_url": "https://www.sec.gov/.../q-index.json",
            "comparison_id": "FC:AAPL:10-Q:0000320193-26-000020",
            "has_comparison": True,
            "comparison": {
                "has_prior": True,
                "notable_changes": [
                    {"kind": "whole_document_changed_materially", "metric": "diff_ratio",
                     "value": 0.1362, "threshold": 0.1339},
                    {"kind": "section_changed_materially", "section": "risk_factors",
                     "metric": "diff_ratio", "value": 0.2350, "threshold": 0.1093},
                    {"kind": "new_material_passages", "metric": "count", "value": 6,
                     "min_words_each": 40},
                ],
                "xbrl": [
                    {"field": "revenue", "comparison": "YOY", "status": "FOUND",
                     "prior_value": 94036000000.0, "current_value": 109417000000.0,
                     "relative_delta": 0.163565},
                ],
            },
        }

    def ranked_events(self, *, event_type=None, symbols=None, since=None, limit=60):
        items = []
        if event_type == "EARNINGS_RESULTS":
            items = [self._earnings]
        elif event_type == "QUARTERLY_FILING":
            items = [self._tenq]
        return {"items": items, "next_cursor": None, "count": len(items), "total_candidates": len(items)}

    def event_detail(self, event_id):
        return self._earnings if "EARNINGS_RESULTS" in event_id else (
            self._tenq if "QUARTERLY_FILING" in event_id else None
        )

    def insider_activity(self, symbol):
        return {
            "symbol": symbol, "open_market_aggregates": [
                {"window_calendar_days": 30, "net_value": -1788964.8, "net_shares": -5700.0,
                 "distinct_purchasers": 0, "distinct_sellers": 2, "transaction_count": 4},
            ],
        }

    def freshness_state(self):
        return {"sources": [{"source": "SEC_EDGAR_SUBMISSIONS", "status": "FRESH"}], "worst": "FRESH"}

    def close(self):
        pass


# ---------------------------------------------------------------------------
# Earnings RADAR
# ---------------------------------------------------------------------------

def _upcoming(sym, d, session="UNSPECIFIED", last_updated="2026-08-19T08:00:00+00:00"):
    return {"ticker": sym, "earnings_date": d, "session": session, "last_updated": last_updated}


def test_radar_milestone_rows_built_only_when_due():
    br = EarningsRadarBridge()
    rows = br.build_rows(
        [_upcoming("AAPL", "2026-08-27"),   # T-7 today
         _upcoming("MSFT", "2026-08-22"),   # T-2 today
         _upcoming("NVDA", "2026-08-20"),   # T-0 today
         _upcoming("TSLA", "2026-09-15")],  # not due
        now=NOW,
    )
    got = {(r["symbol"], r["reporting_when"].split()[0]) for r in rows}
    assert ("AAPL", "2026-08-27") in got
    assert ("MSFT", "2026-08-22") in got
    assert ("NVDA", "2026-08-20") in got
    assert not any(r["symbol"] == "TSLA" for r in rows)
    for r in rows:
        assert r["radar_id"].startswith("R")


def test_radar_id_is_deterministic_and_dedups_on_rerun():
    br = EarningsRadarBridge()
    a = br.build_rows([_upcoming("AAPL", "2026-08-27")], now=NOW)
    b = br.build_rows([_upcoming("AAPL", "2026-08-27")], now=NOW + timedelta(hours=3))
    assert a and b and a[0]["radar_id"] == b[0]["radar_id"]


def test_radar_date_shift_yields_a_new_id():
    br = EarningsRadarBridge()
    a = br.build_rows([_upcoming("AAPL", "2026-08-27")], now=NOW)          # T-7
    shifted = NOW + timedelta(days=1)
    b = br.build_rows([_upcoming("AAPL", "2026-08-28")], now=shifted)      # still T-7, new date
    assert a[0]["radar_id"] != b[0]["radar_id"]


def test_radar_skips_already_reported():
    br = EarningsRadarBridge()
    assert br.build_rows([_upcoming("AAPL", "2026-08-01")], now=NOW) == []


def test_radar_card_renders_and_has_no_fabricated_valuation():
    br = EarningsRadarBridge()
    row = br.build_rows([_upcoming("AAPL", "2026-08-20")], now=NOW, price_lookup=lambda s: 190.0)[0]
    row["company"] = "Apple Inc."
    compact = render_radar(row)
    detail = render_radar_details(row)
    for txt in (compact, detail):
        assert "UPCOMING EARNINGS RADAR" in txt
        assert_no_predictive_language(txt)
        # "fair value" / "moat" may appear ONLY inside the "No ... shown" disclaimer
        for banned in ("intrinsic", "price target"):
            assert banned not in txt.lower()
    assert "No fair value / moat" in detail
    assert "watchlist" in detail.lower() and "yfinance" in detail.lower()  # provenance


# ---------------------------------------------------------------------------
# Post-earnings bridge
# ---------------------------------------------------------------------------

def test_post_earnings_row_from_8k_uses_significance_reasons():
    api = FakeIntelAPI()
    rows = PostEarningsBridge(include_periodic_enrichment=False).scan(api)
    assert len(rows) == 1
    r = rows[0]
    assert r["symbol"] == "AAPL"
    assert r["event_type"].startswith("8-K Item 2.02")
    assert r["significance_band"] == "HIGH"
    # watchlist reason is filtered out of the material-changes fallback
    assert not any("watchlist" in m.lower() for m in r["material_changes"])
    assert r["insider_context"] and "net selling" in r["insider_context"]
    assert r["event_id"].startswith("E")
    assert r["source_event_id"].startswith("SEC:")


def test_post_earnings_row_from_10q_uses_what_changed():
    api = FakeIntelAPI()
    rows = PostEarningsBridge().scan(api)
    tenq = [r for r in rows if "10-Q" in r["event_type"]]
    assert tenq
    mc = tenq[0]["material_changes"]
    assert any("whole-document" in m for m in mc)
    assert any("risk_factors" in m for m in mc)
    assert any("revenue YOY" in m or "XBRL revenue YOY" in m for m in mc)


def test_post_earnings_card_is_descriptive_only():
    api = FakeIntelAPI()
    for row in PostEarningsBridge().scan(api):
        for txt in (render_event_update(row), render_event_update_details(row)):
            assert_no_predictive_language(txt)
            low = txt.lower()
            # no directional / return / target language in 96-derived content
            for banned in ("bullish", "bearish", "price target", "expected return",
                           "likely to rise", "likely to fall", "buy signal", "sell signal"):
                assert banned not in low
            # "fair value" / "moat" only ever in the negation disclaimer
            assert "no fair-value / moat" in low or "no fair value / moat" in low
            assert "not a forecast" in low or "descriptive only" in low


def test_post_earnings_detail_has_provenance_and_evidence_link():
    api = FakeIntelAPI()
    row = PostEarningsBridge().scan(api)[0]
    d = render_event_update_details(row)
    assert "Accession:" in d and "96A event_id:" in d
    assert "127.0.0.1:8760/evidence/event/" in d


# ---------------------------------------------------------------------------
# overnight events + health
# ---------------------------------------------------------------------------

def test_overnight_event_labels():
    class _API:
        def ranked_events(self, **kw):
            return {"items": [
                {"symbol": "AAPL", "form_type": "8-K", "filing_items": ["2.02"],
                 "event_type": "EARNINGS_RESULTS", "band": "HIGH",
                 "accepted_at_utc": "2026-08-20T04:12:00+00:00"},
                {"symbol": "AAPL", "form_type": "8-K", "filing_items": ["7.01"],
                 "event_type": "REGULATION_FD", "band": "MEDIUM",
                 "accepted_at_utc": "2026-08-19T10:00:00+00:00"},  # too old
            ]}
    got = overnight_event_labels(_API(), ["AAPL"], since=NOW - timedelta(hours=18))
    assert "AAPL" in got and len(got["AAPL"]) == 1
    assert "2.02" in got["AAPL"][0] and "band HIGH" in got["AAPL"][0]


def test_bridge_health_shape():
    api = FakeIntelAPI()
    h = bridge_health(api, [_upcoming("AAPL", "2026-08-27")], BridgeMetrics(), now=NOW)
    assert h["earnings_source"]["status"] == "healthy"
    assert h["intelligence_source"]["status"] == "healthy"  # FakeIntelAPI reports FRESH
    assert h["dispatch_bridge"]["status"] == "healthy"


def test_bridge_health_earnings_down_when_empty():
    api = FakeIntelAPI()
    h = bridge_health(api, [], BridgeMetrics(), now=NOW)
    assert h["earnings_source"]["status"] == "down"


# ---------------------------------------------------------------------------
# idempotency through the dispatcher
# ---------------------------------------------------------------------------

def test_radar_and_event_idempotent_through_dispatch(tmp_path):
    async def _run():
        store = ExperimentalAlertStore(tmp_path / "a.db")
        d = ExperimentalDispatcher(store=store, sender=RecordingSender(), enable_external_send=True)
        br = EarningsRadarBridge()
        row = br.build_rows([_upcoming("AAPL", "2026-08-20")], now=NOW)[0]
        api = FakeIntelAPI()
        ev = PostEarningsBridge(include_periodic_enrichment=False).scan(api)[0]
        results = []
        for _ in range(3):
            results.append(await d.dispatch_radar(dict(row)))
            results.append(await d.dispatch_event_update(dict(ev)))
        # fresh store object -> replay again
        store2 = ExperimentalAlertStore(tmp_path / "a.db")
        d2 = ExperimentalDispatcher(store=store2, sender=RecordingSender(), enable_external_send=True)
        await d2.dispatch_radar(dict(row))
        await d2.dispatch_event_update(dict(ev))

        assert results.count("SENT") == 2          # first radar + first event only
        assert results.count("DUPLICATE") == 4
        assert store.counts()["radar_alerts"] == 1
        assert store.counts()["event_updates"] == 1
        assert len(d.sender.sent) == 2
        assert d2.sender.sent == []                # restart: nothing re-sent
        store.close(); store2.close()

    asyncio.run(_run())


# ---------------------------------------------------------------------------
# real 96A replay (guarded)
# ---------------------------------------------------------------------------

_REPLAY = Path("results/task99b_live_intelligence_bridge/_replay_ledger.db")


@pytest.mark.skipif(not _REPLAY.exists(), reason="real 96A replay ledger not present")
def test_replay_real_8k_item_202_through_bridge():
    from talonx_ingest.intelligence.dashboard.readapi import IntelligenceReadAPI

    api = IntelligenceReadAPI(ledger_path=str(_REPLAY))
    try:
        rows = PostEarningsBridge().scan(api, since=None, limit=50)
        assert rows, "expected at least one EARNINGS_RESULTS / 10-Q row from the real ledger"
        earnings = [r for r in rows if "2.02" in r["event_type"]]
        assert earnings
        r = earnings[0]
        assert r["symbol"] in {"AAPL", "MSFT"}
        assert r["significance_band"] in {"LOW", "MEDIUM", "HIGH", "CRITICAL"}
        txt = render_event_update_details(r)
        assert_no_predictive_language(txt)
        assert r["accession"] and "-" in r["accession"]
    finally:
        api.close()
