"""Task 99A S6 -- experimental-signal dashboard. Focused areas: routes return,
data displays, no production-state mutation, deterministic order, missing-data
behaviour, HTML escaping, no short-execution controls, works with no signals.
TEST_FIXTURE_ONLY -- NOT ALPHA EVIDENCE.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from talonx_signals.alert_store import ExperimentalAlertStore
from talonx_signals.dashboard import ExperimentalDashboard, make_app
from talonx_signals.premarket import PremarketSymbolInput, PremarketWatchEngine
from talonx_signals.schemas import (
    AlertDirection, DirectionalAlert, MarketSession, SetupEvidence, TradeGateStatus, make_alert_id,
)
from talonx_signals.telemetry import ForwardOutcomeRecorder, ForwardOutcomeStore

T0 = datetime(2026, 8, 7, 15, 0, tzinfo=timezone.utc)


@pytest.fixture
def stores(tmp_path):
    a = ExperimentalAlertStore(tmp_path / "exp_alerts.db")
    o = ForwardOutcomeStore(tmp_path / "fo.db")
    yield a, o
    a.close()
    o.close()


def _alert(sym="AAPL", direction=AlertDirection.BULLISH, profile="FROZEN_CONTROL", ts=T0, msg="ok"):
    return DirectionalAlert(
        alert_id=make_alert_id(symbol=sym, direction=direction.value, setup_type="macd_bullish_cross",
                               session="regular", episode_ts=ts),
        symbol=sym, direction=direction, profile=profile, setup_type="macd_bullish_cross",
        setup_score=1, session=MarketSession.REGULAR, price=100.0,
        trade_gate_status=TradeGateStatus.WOULD_REJECT, trade_gate_reject_reason="LOW_CONFLUENCE",
        message=msg, evidence=SetupEvidence(atr_pct=0.12), bar_timestamp=ts, generated_at=ts,
    )


def _health():
    return {
        "market_feed": {"status": "up", "detail": "yfinance poll 12s"},
        "control_strategy": {"status": "healthy"},
        "experimental_strategy": {"status": "healthy"},
        "intelligence_service": {"status": "fresh"},
        "dispatcher": {"status": "healthy"},
        "paper_engine": {"status": "healthy"},
        "telegram": {"status": "degraded", "detail": "dry-run"},
        "last_event_at": "2026-08-07T15:00:00Z",
        "coverage": "39/39",
    }


def test_render_has_all_required_sections_when_empty(stores):
    a, o = stores
    board = ExperimentalDashboard(a, o, health_provider=_health)
    out = board.render()
    for heading in ("System Health", "Pre-market", "Latest BULLISH", "Latest BEARISH",
                    "Experimental Trades", "Control vs Experimental", "Forward Outcomes"):
        assert heading in out
    assert "no execution controls on this page" in out
    assert "<table" in out or "no rows" in out


def test_render_shows_directional_alerts_and_outcomes(stores):
    a, o = stores
    a.record_directional(_alert("AAPL", AlertDirection.BULLISH))
    a.record_directional(_alert("TSLA", AlertDirection.BEARISH))
    rec = ForwardOutcomeRecorder(o)
    obs = rec.open_from_directional(_alert("AAPL"))
    rec.resolve_eod(obs, 103.0)
    out = ExperimentalDashboard(a, o, health_provider=_health).render()
    assert "AAPL" in out and "TSLA" in out
    assert "PENDING_1D" in out
    assert "3.00" in out  # +3% EOD


def test_control_vs_experimental_counts(stores):
    a, o = stores
    a.record_directional(_alert("AAPL", AlertDirection.BULLISH, profile="FROZEN_CONTROL"))
    a.record_directional(_alert("MSFT", AlertDirection.BULLISH, profile="EXPERIMENTAL_RELAXED_V1"))
    a.record_directional(_alert("NVDA", AlertDirection.BEARISH, profile="EXPERIMENTAL_RELAXED_V1"))
    out = ExperimentalDashboard(a, o).render()
    assert "Control vs Experimental" in out
    assert "EXPERIMENTAL_RELAXED_V1" in out
    assert "reject: LOW_CONFLUENCE" in out


def test_html_escaping_of_untrusted_text(stores):
    a, o = stores
    bundle = PremarketWatchEngine().assess(
        [PremarketSymbolInput(symbol="AAPL", prev_close=100.0, latest_price=100.0, latest_volume=1,
                              overnight_events=("<script>alert(1)</script>",))],
        now=T0,
    )
    out = ExperimentalDashboard(a, o, premarket_provider=lambda: bundle).render()
    assert "<script>alert(1)</script>" not in out
    assert "&lt;script&gt;" in out


def test_no_short_or_order_controls_anywhere(stores):
    a, o = stores
    a.record_directional(_alert())
    out = ExperimentalDashboard(a, o, health_provider=_health).render().lower()
    assert "<form" not in out
    assert "<button" not in out
    assert "<input" not in out
    assert "onclick" not in out


def test_premarket_section_from_bundle(stores):
    a, o = stores
    bundle = PremarketWatchEngine().assess(
        [PremarketSymbolInput(symbol="AAPL", prev_close=100.0, latest_price=103.0, latest_volume=1000)],
        now=T0,
    )
    out = ExperimentalDashboard(a, o, premarket_provider=lambda: bundle).render()
    assert "Bullish watch" in out and "AAPL" in out


def test_render_is_deterministic_for_same_data(stores):
    a, o = stores
    a.record_directional(_alert("AAPL", ts=T0))
    a.record_directional(_alert("MSFT", ts=T0 + timedelta(minutes=1)))
    board = ExperimentalDashboard(a, o)
    first = board.render()
    second = board.render()
    # only the footer timestamp differs -> strip it
    assert first.split("<footer>")[0] == second.split("<footer>")[0]


def test_render_does_not_mutate_stores(stores):
    a, o = stores
    a.record_directional(_alert())
    before = a.counts()
    ExperimentalDashboard(a, o).render()
    assert a.counts() == before


@pytest.mark.asyncio
async def test_routes(tmp_path):
    from aiohttp.test_utils import TestClient, TestServer

    app = make_app(alert_db=str(tmp_path / "a.db"), outcome_db=str(tmp_path / "o.db"),
                   health_provider=_health)
    async with TestClient(TestServer(app)) as client:
        r = await client.get("/")
        assert r.status == 200 and "text/html" in r.headers["Content-Type"]
        assert "System Health" in await r.text()

        h = await client.get("/__health")
        assert h.status == 200
        assert (await h.json())["ok"] is True

        missing = await client.get("/does-not-exist")
        assert missing.status == 404

        posted = await client.post("/")
        assert posted.status == 405
