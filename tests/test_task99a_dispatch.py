"""Task 99A S4 -- restored alert families + Telegram dispatch + reply-for-details.
Focused areas: RADAR/bullish/bearish/experimental-BUY/SELL render, reply lookup,
unknown id, stale id, dedup, retry, permanent failure, no short order,
predictive-probability wording absent, dry-run default, resolver isolation.
TEST_FIXTURE_ONLY -- NOT ALPHA EVIDENCE.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from talonx_signals.alert_store import ExperimentalAlertStore
from talonx_signals.dispatcher import ExperimentalDispatcher, RecordingSender
from talonx_signals.renderers import (
    PredictiveLanguageError,
    assert_no_predictive_language,
    render_directional_setup,
    render_experimental_trade,
    render_radar,
)
from talonx_signals.reply import make_reply_resolver
from talonx_signals.schemas import (
    AlertDirection,
    DirectionalAlert,
    MarketSession,
    SetupEvidence,
    TradeGateStatus,
    make_alert_id,
    make_radar_id,
    make_trade_id,
)

NOW = datetime(2026, 8, 7, 15, 0, tzinfo=timezone.utc)


@pytest.fixture
def store(tmp_path):
    s = ExperimentalAlertStore(tmp_path / "exp_alerts.db")
    yield s
    s.close()


def _alert(direction=AlertDirection.BULLISH, profile="FROZEN_CONTROL", score=2, **kw) -> DirectionalAlert:
    ts = kw.pop("bar_timestamp", NOW)
    return DirectionalAlert(
        alert_id=make_alert_id(symbol="AAPL", direction=direction.value, setup_type="macd_bullish_cross",
                               session="regular", episode_ts=ts),
        symbol="AAPL", direction=direction, profile=profile, setup_type="macd_bullish_cross",
        setup_score=score, session=MarketSession.REGULAR, price=100.0,
        trade_gate_status=TradeGateStatus.WOULD_REJECT, trade_gate_reject_reason="LOW_CONFLUENCE",
        risk_reward_ratio=1.2, stop_price=98.0, target_price=104.0, geometry_path="STRUCTURAL_PRIMARY",
        message="MACD crossed above signal", evidence=SetupEvidence(rsi=41.0, atr=1.0, atr_pct=1.0),
        bar_timestamp=ts, generated_at=NOW, **kw,
    )


def _trade(side="BUY"):
    tid = make_trade_id(symbol="AAPL", profile="EXPERIMENTAL_RELAXED_V1", side=side, opened_at=NOW)
    base = dict(trade_id=tid, symbol="AAPL", profile="EXPERIMENTAL_RELAXED_V1", side=side,
                entry=100.0, stop=98.0, target=104.0, quantity=25, admitted_by="relaxed_confluence",
                opened_at=NOW.isoformat())
    if side == "SELL":
        base.update(exit=103.0, exit_reason="target_exit", gross_pnl=75.0, est_costs=3.0,
                    net_pnl=72.0, r_multiple=1.44, mfe=90.0, mae=-10.0, closed_at=NOW.isoformat())
    return base


# ---------------------------------------------------------------------------
# renders
# ---------------------------------------------------------------------------

def test_bullish_and_bearish_render_use_setup_score_not_confidence():
    bull = render_directional_setup(_alert(AlertDirection.BULLISH))
    bear = render_directional_setup(_alert(AlertDirection.BEARISH))
    assert "BULLISH SETUP" in bull and "BEARISH SETUP" in bear
    assert "Setup Score:" in bull
    for txt in (bull, bear):
        assert "confidence" not in txt.lower()
        assert "% chance" not in txt.lower()
        assert_no_predictive_language(txt)
    assert "Reply `D" in bull


def test_experimental_buy_and_sell_render():
    buy = render_experimental_trade(_trade("BUY"))
    sell = render_experimental_trade(_trade("SELL"))
    assert "EXPERIMENTAL BUY (paper)" in buy
    # Task 99H: `admitted_by` is an internal identifier routed through
    # `_raw()`, which now Markdown-escapes underscores (`_` -> `\_`) so
    # Telegram's legacy Markdown parser never treats it as an italic
    # delimiter -- Telegram strips the backslash on render, so the human
    # reads "relaxed_confluence" unchanged; only the raw string differs.
    assert r"Admitted by: relaxed\_confluence" in buy
    assert "EXPERIMENTAL SELL / EXIT (paper)" in sell
    assert "Closes an existing experimental LONG only -- never a short." in sell
    assert "R multiple: 1.44" in sell


def test_radar_render_has_no_fabricated_valuation():
    rid = make_radar_id(symbol="NVDA", reporting_when="2026-08-20 AMC", day=NOW)
    txt = render_radar(dict(radar_id=rid, symbol="NVDA", company="NVIDIA",
                            reporting_when="2026-08-20 AMC", current_price=120.0,
                            context="DUAL_HORIZON watch"))
    assert "UPCOMING EARNINGS RADAR" in txt and "#RADAR" in txt
    for banned in ("fair value", "moat", "margin of safety", "intrinsic"):
        assert banned not in txt.lower()


def test_predictive_language_guard_trips_on_probability_wording():
    with pytest.raises(PredictiveLanguageError):
        assert_no_predictive_language("Setup with 80% chance of profit")
    with pytest.raises(PredictiveLanguageError):
        assert_no_predictive_language("Confidence: 0.82")


# ---------------------------------------------------------------------------
# dispatch: dedup / dry-run / retry / permanent
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_dry_run_is_the_default_no_external_send(store):
    d = ExperimentalDispatcher(store=store, sender=RecordingSender())
    res = await d.dispatch_directional(_alert())
    assert res == "HELD"
    assert d.sender.sent == []
    assert store.get_directional(_alert().alert_id) is not None  # recorded
    assert d.metrics.dry_run_held == 1


@pytest.mark.asyncio
async def test_dedup_skips_second_dispatch_of_same_alert(store):
    d = ExperimentalDispatcher(store=store, sender=RecordingSender(), enable_external_send=True)
    a = _alert()
    assert await d.dispatch_directional(a) == "SENT"
    assert await d.dispatch_directional(a) == "DUPLICATE"
    assert len(d.sender.sent) == 1
    assert d.metrics.duplicates_skipped == 1


@pytest.mark.asyncio
async def test_retry_then_success(store):
    d = ExperimentalDispatcher(
        store=store, sender=RecordingSender(fail_times=2), enable_external_send=True,
        backoff_base_seconds=0.0,
    )
    assert await d.dispatch_directional(_alert()) == "SENT"
    assert len(d.sender.sent) == 1


@pytest.mark.asyncio
async def test_permanent_failure_marks_failed_not_retried(store):
    sender = RecordingSender(fail_times=1, permanent=True)
    d = ExperimentalDispatcher(store=store, sender=sender, enable_external_send=True)
    assert await d.dispatch_directional(_alert()) == "FAILED"
    assert d.metrics.send_failures == 1
    row = store.get_directional(_alert().alert_id)
    assert row["sent"] == 0 and row["send_error"]


@pytest.mark.asyncio
async def test_drain_pending_resends_after_restart(store):
    # record while dry-run (held), then a "restart" with sending enabled drains it
    d1 = ExperimentalDispatcher(store=store, sender=RecordingSender())
    await d1.dispatch_directional(_alert())
    d2 = ExperimentalDispatcher(store=store, sender=RecordingSender(), enable_external_send=True)
    out = await d2.drain_pending()
    assert out["directional"] == 1
    assert len(d2.sender.sent) == 1


@pytest.mark.asyncio
async def test_no_trading_order_is_ever_sent(store):
    """The dispatcher only sends text. A trade card describes a paper fill; it
    is not an order and the sender only ever receives strings."""
    d = ExperimentalDispatcher(store=store, sender=RecordingSender(), enable_external_send=True)
    await d.dispatch_trade(_trade("BUY"))
    await d.dispatch_trade(_trade("SELL"))
    assert all(isinstance(x, str) for x in d.sender.sent)
    assert all("paper" in x.lower() for x in d.sender.sent)


# ---------------------------------------------------------------------------
# reply-for-details
# ---------------------------------------------------------------------------

def test_reply_resolver_directional_lookup(store):
    store.record_directional(_alert())
    resolve = make_reply_resolver(store)
    out = resolve(f"{_alert().alert_id}")
    assert out and "FULL DETAIL" in out and "Provenance:" in out


def test_reply_resolver_trade_and_radar_lookup(store):
    store.record_trade(_trade("SELL"))
    rid = make_radar_id(symbol="NVDA", reporting_when="2026-08-20 AMC", day=NOW)
    store.record_radar(dict(radar_id=rid, symbol="NVDA", reporting_when="2026-08-20 AMC"))
    resolve = make_reply_resolver(store)
    assert "EXPERIMENTAL SELL" in resolve(_trade("SELL")["trade_id"])
    assert "UPCOMING EARNINGS RADAR" in resolve(rid)


def test_reply_resolver_unknown_id(store):
    resolve = make_reply_resolver(store)
    out = resolve("Dabc123def456aa99")
    assert "not found" in out


def test_reply_resolver_stale_id_after_purge(store):
    store.record_directional(_alert())
    store.purge_older_than(datetime.now(timezone.utc) + timedelta(days=1))
    resolve = make_reply_resolver(store)
    assert "not found" in resolve(_alert().alert_id)


def test_reply_resolver_returns_none_for_non_prefixed_text(store):
    """So the Original numeric-id / LT path still runs unchanged."""
    resolve = make_reply_resolver(store)
    assert resolve("47") is None
    assert resolve("LT47") is None
    assert resolve("/ping") is None
    assert resolve("hello there") is None


def test_listener_accepts_extra_resolvers_kwarg():
    from talonx_dispatch.telegram_listener import TelegramReplyListener

    class _FakeStore:
        pass

    r = lambda t: None  # noqa: E731
    listener = TelegramReplyListener(store=_FakeStore(), extra_resolvers=[r])
    assert listener.extra_resolvers == [r]
    # default is empty -> Original behaviour unchanged
    assert TelegramReplyListener(store=_FakeStore()).extra_resolvers == []
