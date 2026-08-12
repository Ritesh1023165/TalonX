"""
tests/test_quant_fundamental_consumer.py
--------------------------------------------------
Tests talonx_quant.fundamental_consumer.FundamentalScanner's message
routing, threshold gating, and cooldown -- Phase 2's LONG_TERM sibling
to test_quant_consumer.py. The Redis client is mocked (AsyncMock), same
boundary every other consumer's tests in this project use.
"""
from __future__ import annotations

import json
from unittest.mock import AsyncMock

import pytest

from talonx_quant.config import QuantConfig
from talonx_quant.fundamental_consumer import FundamentalScanner
from talonx_quant.store import QuantStateStore


def _facts(fiscal_year: int, **overrides) -> dict:
    defaults = dict(
        ticker="AAPL", cik="0000320193", fiscal_year=fiscal_year,
        revenue=800.0, operating_income=120.0, net_income=95.0,
        operating_cash_flow=150.0, capex=30.0, total_debt=200.0,
        cash_and_equivalents=50.0, total_equity=300.0,
        total_assets=1000.0, retained_earnings=200.0, shares_outstanding=100.0,
    )
    defaults.update(overrides)
    return defaults


def _fundamentals_payload(facts: list[dict] | None = None) -> dict:
    # Prior year deliberately weaker across every YoY-compared field
    # (lower NI/OCF, higher leverage, thinner margin, lower revenue) so
    # the default payload clears every Piotroski check as well as the
    # ROIC threshold -- tests that want a "doesn't clear thresholds"
    # case build their own facts instead of overriding this default.
    prior = _facts(2024, net_income=70.0, operating_cash_flow=100.0, operating_income=90.0, revenue=700.0, total_debt=250.0)
    return {
        "ticker": "AAPL", "cik": "0000320193",
        "facts": facts if facts is not None else [_facts(2025), prior],
        "published_at": "2026-08-12T12:00:00Z",
    }


def _bar_payload(symbol: str = "AAPL", close: float | None = 20.0) -> dict:
    return {
        "event_type": "bar", "symbol": symbol, "source": "polling",
        "timestamp": "2026-08-12T12:00:00Z", "close": close,
    }


def _msg(channel: str, payload: dict) -> dict:
    return {"channel": channel.encode(), "data": json.dumps(payload)}


@pytest.fixture
def scanner() -> FundamentalScanner:
    s = FundamentalScanner(QuantConfig())
    s._client = AsyncMock()
    s._client.exists.return_value = False  # not on cooldown by default
    return s


@pytest.mark.asyncio
async def test_market_tick_updates_the_latest_price_cache(scanner):
    await scanner._handle_message(_msg(scanner.config.market_stream_channel, _bar_payload(close=25.0)))
    assert scanner._latest_prices["AAPL"] == 25.0
    scanner._client.publish.assert_not_awaited()


@pytest.mark.asyncio
async def test_non_bar_market_event_is_ignored(scanner):
    payload = _bar_payload()
    payload["event_type"] = "trade"
    await scanner._handle_message(_msg(scanner.config.market_stream_channel, payload))
    assert scanner._latest_prices == {}


@pytest.mark.asyncio
async def test_fundamentals_event_that_clears_thresholds_publishes_a_signal(scanner):
    await scanner._handle_message(_msg(scanner.config.market_stream_channel, _bar_payload(close=20.0)))

    await scanner._handle_message(_msg(scanner.config.fundamentals_events_channel, _fundamentals_payload()))

    scanner._client.publish.assert_awaited_once()
    channel, payload = scanner._client.publish.await_args.args
    assert channel == scanner.config.fundamental_signals_channel
    body = json.loads(payload)
    assert body["ticker"] == "AAPL"
    assert body["fiscal_year"] == 2025
    assert body["roic"] is not None
    assert body["piotroski_f_score"] is not None
    assert scanner.signals_published == 1


@pytest.mark.asyncio
async def test_fundamentals_event_below_threshold_does_not_publish(scanner):
    weak_facts = [_facts(2025, operating_income=1.0, total_debt=1000.0, total_equity=1000.0)]  # tiny ROIC

    await scanner._handle_message(_msg(scanner.config.fundamentals_events_channel, _fundamentals_payload(weak_facts)))

    scanner._client.publish.assert_not_awaited()
    assert scanner.signals_published == 0


@pytest.mark.asyncio
async def test_single_fiscal_year_does_not_crash_the_piotroski_comparison(scanner):
    """No prior-year data at all -- compute_piotroski_f_score(current, current)
    must degrade gracefully (no YoY check can pass), not raise."""
    await scanner._handle_message(
        _msg(scanner.config.fundamentals_events_channel, _fundamentals_payload([_facts(2025)]))
    )
    # Doesn't crash; whether it publishes depends purely on the threshold math.
    assert scanner.events_processed == 1


@pytest.mark.asyncio
async def test_empty_facts_list_is_processed_but_produces_no_signal(scanner):
    await scanner._handle_message(
        _msg(scanner.config.fundamentals_events_channel, _fundamentals_payload([]))
    )
    scanner._client.publish.assert_not_awaited()


@pytest.mark.asyncio
async def test_on_cooldown_suppresses_the_signal(scanner):
    scanner._client.exists.return_value = True

    await scanner._handle_message(_msg(scanner.config.fundamentals_events_channel, _fundamentals_payload()))

    scanner._client.publish.assert_not_awaited()
    scanner._client.set.assert_not_awaited()  # cooldown not re-armed while already locked
    assert scanner.signals_suppressed_cooldown == 1


@pytest.mark.asyncio
async def test_publishing_a_signal_starts_the_fundamental_cooldown(scanner):
    await scanner._handle_message(_msg(scanner.config.fundamentals_events_channel, _fundamentals_payload()))

    scanner._client.set.assert_awaited_once()
    args, kwargs = scanner._client.set.await_args
    assert args[0] == "fundamental_cooldown:AAPL"
    assert kwargs["ex"] == int(scanner.config.fundamental_cooldown_seconds)


@pytest.mark.asyncio
async def test_cooldown_uses_its_own_key_namespace_not_the_intraday_one(scanner):
    """Explicit regression coverage for the exact collision the research
    flagged: fundamental cooldown keys must never be `cooldown:{TICKER}`,
    the intraday QuantScanner's own key template."""
    await scanner._handle_message(_msg(scanner.config.fundamentals_events_channel, _fundamentals_payload()))

    key_checked = scanner._client.exists.await_args.args[0]
    key_set = scanner._client.set.await_args.args[0]
    assert key_checked == "fundamental_cooldown:AAPL"
    assert key_set == "fundamental_cooldown:AAPL"
    assert not key_checked.startswith("cooldown:")
    assert not key_set.startswith("cooldown:")


@pytest.mark.asyncio
async def test_suppression_is_persisted_when_a_store_is_set(tmp_path):
    with QuantStateStore(tmp_path / "quant.db") as store:
        scanner = FundamentalScanner(QuantConfig(), store=store)
        scanner._client = AsyncMock()
        scanner._client.exists.return_value = True

        await scanner._handle_message(_msg(scanner.config.fundamentals_events_channel, _fundamentals_payload()))

        import datetime as dt
        today = dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%d")
        rows = store.suppression_counts_for_date(today)
    assert len(rows) == 1
    assert rows[0]["ticker"] == "AAPL"
    assert rows[0]["reason"] == "FUNDAMENTAL_COOLDOWN"


@pytest.mark.asyncio
async def test_unparseable_fundamentals_event_is_dropped(scanner):
    await scanner._handle_message(
        {"channel": scanner.config.fundamentals_events_channel.encode(), "data": "not json"}
    )
    assert scanner.events_processed == 0


@pytest.mark.asyncio
async def test_invalid_fundamentals_payload_is_dropped(scanner):
    await scanner._handle_message(
        _msg(scanner.config.fundamentals_events_channel, {"ticker": "AAPL"})  # missing required fields
    )
    assert scanner.events_processed == 0


@pytest.mark.asyncio
async def test_message_on_unexpected_channel_is_dropped(scanner):
    await scanner._handle_message(_msg("some:other:channel", _fundamentals_payload()))
    assert scanner.events_processed == 0
