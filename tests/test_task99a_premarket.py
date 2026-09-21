"""Task 99A S3.5 -- PremarketWatchEngine. Focused areas: premarket watch
behavior, gap movers, abnormal volume, RADAR, event context, no order path.
TEST_FIXTURE_ONLY -- NOT ALPHA EVIDENCE.
"""

from __future__ import annotations

from datetime import datetime, timezone

from talonx_signals.premarket import PremarketSymbolInput, PremarketWatchEngine
from talonx_signals.schemas import MarketSession, WatchKind

NOW = datetime(2026, 8, 7, 12, 0, tzinfo=timezone.utc)


def test_gap_up_produces_bullish_watch_and_gap_mover():
    eng = PremarketWatchEngine()
    b = eng.assess(
        [PremarketSymbolInput(symbol="AAPL", prev_close=100.0, latest_price=103.0, latest_volume=1_000)],
        now=NOW,
    )
    assert len(b.bullish_watch) == 1
    assert b.bullish_watch[0].kind == WatchKind.BULLISH_WATCH
    assert b.bullish_watch[0].session == MarketSession.PRE_MARKET
    assert len(b.gap_up) == 1 and b.gap_up[0].gap_pct == 3.0
    assert not b.bearish_watch and not b.gap_down


def test_gap_down_produces_bearish_watch():
    eng = PremarketWatchEngine()
    b = eng.assess(
        [PremarketSymbolInput(symbol="TSLA", prev_close=200.0, latest_price=190.0, latest_volume=5_000)],
        now=NOW,
    )
    assert len(b.bearish_watch) == 1
    assert b.bearish_watch[0].kind == WatchKind.BEARISH_WATCH
    assert len(b.gap_down) == 1 and b.gap_down[0].gap_pct == -5.0


def test_small_gap_is_no_watch():
    eng = PremarketWatchEngine()
    b = eng.assess(
        [PremarketSymbolInput(symbol="MSFT", prev_close=100.0, latest_price=100.3, latest_volume=1_000)],
        now=NOW,
    )
    assert not b.bullish_watch and not b.bearish_watch and not b.gap_up and not b.gap_down


def test_radar_from_scheduled_earnings():
    eng = PremarketWatchEngine()
    b = eng.assess(
        [PremarketSymbolInput(symbol="NVDA", prev_close=100.0, latest_price=100.5,
                              latest_volume=1_000, earnings_when="2026-08-08 AMC")],
        now=NOW,
    )
    assert len(b.radar) == 1
    assert b.radar[0].kind == WatchKind.RADAR
    assert "2026-08-08 AMC" in b.radar[0].detail


def test_overnight_event_context_surfaced():
    eng = PremarketWatchEngine()
    b = eng.assess(
        [PremarketSymbolInput(symbol="AMD", prev_close=100.0, latest_price=100.0,
                              latest_volume=1_000, overnight_events=("8-K Item 2.02 filed 04:12 ET",))],
        now=NOW,
    )
    assert len(b.event_context) == 1
    assert b.event_context[0].kind == WatchKind.EVENT_CONTEXT
    assert "8-K" in b.event_context[0].detail


def test_abnormal_premarket_volume():
    eng = PremarketWatchEngine(abnormal_volume_x=3.0)
    b = eng.assess(
        [PremarketSymbolInput(symbol="AMZN", prev_close=100.0, latest_price=100.5,
                              latest_volume=40_000, avg_premarket_volume=10_000)],
        now=NOW,
    )
    assert len(b.abnormal_volume) == 1
    assert "4.0x" in b.abnormal_volume[0].detail


def test_data_not_ready_is_skipped_and_noted():
    eng = PremarketWatchEngine()
    b = eng.assess(
        [
            PremarketSymbolInput(symbol="AAPL", prev_close=None, latest_price=None),
            PremarketSymbolInput(symbol="MSFT", prev_close=100.0, latest_price=104.0, latest_volume=1),
        ],
        now=NOW, watchlist_configured=2, watchlist_active=2,
    )
    assert b.watchlist_covered == 1
    assert any("no usable pre-market quote" in n for n in b.notes)


def test_watch_ids_are_deterministic_per_day():
    eng = PremarketWatchEngine()
    args = [PremarketSymbolInput(symbol="AAPL", prev_close=100.0, latest_price=103.0, latest_volume=1_000)]
    a = eng.assess(args, now=NOW).bullish_watch[0].watch_id
    b = eng.assess(args, now=NOW).bullish_watch[0].watch_id
    assert a == b and a.startswith("W")


def test_premarket_bundle_has_no_execution_surface():
    eng = PremarketWatchEngine()
    b = eng.assess(
        [PremarketSymbolInput(symbol="AAPL", prev_close=100.0, latest_price=103.0, latest_volume=1_000)],
        now=NOW,
    )
    dumped = b.model_dump()
    text = repr(dumped).lower()
    for forbidden in ("order", "buy(", "'buy'", "quantity", "broker"):
        assert forbidden not in text
