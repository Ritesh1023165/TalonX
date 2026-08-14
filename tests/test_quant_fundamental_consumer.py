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
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock

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


# --- Price fallback (regression coverage for a live-caught bug: a fundamentals
# event arriving before any market tick produced price=0.0, which made
# talonx_core's margin-of-safety math read as a bogus "+100% discount" and
# would have made the HIGH_CONVICTION_BUY price<=threshold check always pass) ---

@pytest.mark.asyncio
async def test_no_live_price_falls_back_to_yfinance_last_close(scanner, monkeypatch):
    """No BAR event was ever sent for AAPL -- _latest_prices is empty --
    but the fallback should still let a genuinely-qualifying signal
    publish, using yfinance's last close instead of price=0.0."""
    monkeypatch.setattr(
        "talonx_quant.fundamental_consumer._fetch_last_close", lambda ticker: 187.50,
    )

    await scanner._handle_message(_msg(scanner.config.fundamentals_events_channel, _fundamentals_payload()))

    scanner._client.publish.assert_awaited_once()
    _, payload = scanner._client.publish.await_args.args
    body = json.loads(payload)
    assert body["price"] == 187.50
    assert scanner._latest_prices["AAPL"] == 187.50  # cached for next time


@pytest.mark.asyncio
async def test_fallback_is_not_attempted_when_a_live_price_is_already_known(scanner, monkeypatch):
    fetch = MagicMock(return_value=999.0)
    monkeypatch.setattr("talonx_quant.fundamental_consumer._fetch_last_close", fetch)
    await scanner._handle_message(_msg(scanner.config.market_stream_channel, _bar_payload(close=190.0)))

    await scanner._handle_message(_msg(scanner.config.fundamentals_events_channel, _fundamentals_payload()))

    fetch.assert_not_called()
    _, payload = scanner._client.publish.await_args.args
    assert json.loads(payload)["price"] == 190.0


@pytest.mark.asyncio
async def test_fallback_is_not_attempted_for_a_signal_that_would_not_pass_anyway(scanner, monkeypatch):
    """The fallback is a real network call -- only worth paying for once
    we know the signal would otherwise publish. A ticker whose ROIC/F-Score
    don't clear the threshold should never trigger it."""
    fetch = MagicMock(return_value=100.0)
    monkeypatch.setattr("talonx_quant.fundamental_consumer._fetch_last_close", fetch)
    weak_facts = [_facts(2025, operating_income=1.0, total_debt=1000.0, total_equity=1000.0)]

    await scanner._handle_message(_msg(scanner.config.fundamentals_events_channel, _fundamentals_payload(weak_facts)))

    fetch.assert_not_called()


@pytest.mark.asyncio
async def test_fallback_failure_suppresses_the_signal_instead_of_publishing_zero_price(scanner, monkeypatch):
    monkeypatch.setattr("talonx_quant.fundamental_consumer._fetch_last_close", lambda ticker: None)

    await scanner._handle_message(_msg(scanner.config.fundamentals_events_channel, _fundamentals_payload()))

    scanner._client.publish.assert_not_awaited()
    assert scanner.signals_published == 0


@pytest.mark.asyncio
async def test_fallback_failure_is_persisted_as_suppressed_when_a_store_is_set(tmp_path, monkeypatch):
    monkeypatch.setattr("talonx_quant.fundamental_consumer._fetch_last_close", lambda ticker: None)
    store = QuantStateStore(tmp_path / "quant.db")
    try:
        scanner = FundamentalScanner(QuantConfig(), store=store)
        scanner._client = AsyncMock()
        scanner._client.exists.return_value = False

        await scanner._handle_message(_msg(scanner.config.fundamentals_events_channel, _fundamentals_payload()))

        today = datetime.now(timezone.utc).date().isoformat()
        counts = store.suppression_counts_for_date(today)
        assert any(c["reason"] == "NO_PRICE_AVAILABLE" for c in counts)
    finally:
        store.close()


@pytest.mark.asyncio
async def test_fallback_fetch_exception_does_not_crash_the_scanner(scanner, monkeypatch):
    def _raise(ticker):
        raise ConnectionError("network unreachable")

    monkeypatch.setattr("talonx_quant.fundamental_consumer._fetch_last_close", _raise)

    await scanner._handle_message(_msg(scanner.config.fundamentals_events_channel, _fundamentals_payload()))

    scanner._client.publish.assert_not_awaited()  # suppressed, not crashed


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


# --- clear_cooldown (run_talonx.reconcile_missing_long_term_factors's escape hatch) --

@pytest.mark.asyncio
async def test_clear_cooldown_deletes_the_right_key(scanner):
    await scanner.clear_cooldown("AAPL")

    scanner._client.delete.assert_awaited_once_with("fundamental_cooldown:AAPL")


@pytest.mark.asyncio
async def test_clear_cooldown_normalizes_the_ticker_case(scanner):
    await scanner.clear_cooldown("aapl")

    scanner._client.delete.assert_awaited_once_with("fundamental_cooldown:AAPL")


@pytest.mark.asyncio
async def test_clear_cooldown_is_a_noop_with_no_client():
    scanner_ = FundamentalScanner(QuantConfig())  # fresh instance -- _client is None until run()
    await scanner_.clear_cooldown("AAPL")  # must not raise


@pytest.mark.asyncio
async def test_clear_cooldown_swallows_redis_errors(scanner):
    scanner._client.delete.side_effect = ConnectionError("redis down")

    await scanner.clear_cooldown("AAPL")  # must not raise


@pytest.mark.asyncio
async def test_cleared_cooldown_lets_a_republished_event_through(scanner):
    """End-to-end: a ticker still 'on cooldown' per the client's exists()
    check would normally get suppressed -- after clear_cooldown, the
    SAME client's own delete() having been called doesn't automatically
    flip exists() in this mocked test, so this instead verifies the
    intended real-Redis behavior indirectly: clear_cooldown targets
    the EXACT key _is_on_cooldown checks, nothing else."""
    await scanner.clear_cooldown("AAPL")
    deleted_key = scanner._client.delete.await_args.args[0]

    is_on_cooldown = await scanner._is_on_cooldown("AAPL")  # a fresh mock call, not affected by the delete above
    checked_key = scanner._client.exists.await_args.args[0]

    assert deleted_key == checked_key == "fundamental_cooldown:AAPL"


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


# ==========================================================================
# Event-Driven Earnings Radar -- Stage 1 (8-K) republish from persisted factors
# ==========================================================================

def _filing_payload(
    ticker: str = "AAPL", form_type: str = "8-K", is_earnings_related: bool = True,
) -> dict:
    return {"ticker": ticker, "form_type": form_type, "is_earnings_related": is_earnings_related}


def _filing_msg(config, payload: dict) -> dict:
    return _msg(config.filings_channel, payload)


@pytest.fixture
def scanner_with_store(tmp_path):
    store = QuantStateStore(tmp_path / "quant.db")
    s = FundamentalScanner(QuantConfig(), store=store)
    s._client = AsyncMock()
    s._client.exists.return_value = False
    yield s
    store.close()


@pytest.mark.asyncio
async def test_filing_event_ignores_non_earnings_related_8k(scanner_with_store):
    scanner_with_store.store.save_latest_factors("AAPL", 2025, 0.21, 8, 0.05, 5.5, 1.2, datetime.now(timezone.utc))

    await scanner_with_store._handle_message(
        _filing_msg(scanner_with_store.config, _filing_payload(is_earnings_related=False))
    )

    scanner_with_store._client.publish.assert_not_awaited()


@pytest.mark.asyncio
async def test_filing_event_ignores_a_10q_stage_2_handles_those(scanner_with_store):
    scanner_with_store.store.save_latest_factors("AAPL", 2025, 0.21, 8, 0.05, 5.5, 1.2, datetime.now(timezone.utc))

    await scanner_with_store._handle_message(
        _filing_msg(scanner_with_store.config, _filing_payload(form_type="10-Q"))
    )

    scanner_with_store._client.publish.assert_not_awaited()


@pytest.mark.asyncio
async def test_filing_event_republishes_using_persisted_factors(scanner_with_store):
    await scanner_with_store._handle_message(_msg(scanner_with_store.config.market_stream_channel, _bar_payload(close=180.0)))
    scanner_with_store.store.save_latest_factors("AAPL", 2025, 0.21, 8, 0.05, 5.5, 1.2, datetime.now(timezone.utc))

    await scanner_with_store._handle_message(_filing_msg(scanner_with_store.config, _filing_payload()))

    scanner_with_store._client.publish.assert_awaited_once()
    channel, payload = scanner_with_store._client.publish.await_args.args
    assert channel == scanner_with_store.config.fundamental_signals_channel
    body = json.loads(payload)
    assert body["ticker"] == "AAPL"
    assert body["fiscal_year"] == 2025
    assert body["roic"] == 0.21
    assert body["price"] == 180.0
    assert body["is_earnings_related"] is True
    assert scanner_with_store.earnings_signals_published == 1


@pytest.mark.asyncio
async def test_filing_event_republishes_even_when_factors_are_below_threshold(scanner_with_store):
    """UNDER_PERFORM_REBALANCE needs below-threshold factors to be
    available too -- the republish path must NOT re-check the ROIC/
    F-Score passes gate."""
    await scanner_with_store._handle_message(_msg(scanner_with_store.config.market_stream_channel, _bar_payload(close=50.0)))
    scanner_with_store.store.save_latest_factors("AAPL", 2025, 0.02, 2, -0.01, 1.0, 6.0, datetime.now(timezone.utc))

    await scanner_with_store._handle_message(_filing_msg(scanner_with_store.config, _filing_payload()))

    scanner_with_store._client.publish.assert_awaited_once()
    body = json.loads(scanner_with_store._client.publish.await_args.args[1])
    assert body["roic"] == 0.02
    assert body["piotroski_f_score"] == 2


@pytest.mark.asyncio
async def test_filing_event_skipped_when_no_store_configured(scanner):
    await scanner._handle_message(_filing_msg(scanner.config, _filing_payload()))
    scanner._client.publish.assert_not_awaited()


@pytest.mark.asyncio
async def test_filing_event_skipped_when_no_persisted_factors_yet(scanner_with_store):
    # First-ever earnings cycle since being tagged LONG_TERM -- no 10-Q
    # has ever landed, so nothing is persisted. Correct no-op, not a bug.
    await scanner_with_store._handle_message(_filing_msg(scanner_with_store.config, _filing_payload()))

    scanner_with_store._client.publish.assert_not_awaited()
    assert scanner_with_store.earnings_republish_suppressed_no_factors == 1


@pytest.mark.asyncio
async def test_filing_event_suppressed_when_on_earnings_cooldown(scanner_with_store):
    scanner_with_store.store.save_latest_factors("AAPL", 2025, 0.21, 8, 0.05, 5.5, 1.2, datetime.now(timezone.utc))
    scanner_with_store._client.exists.return_value = True  # earnings_republish_cooldown:AAPL active

    await scanner_with_store._handle_message(_filing_msg(scanner_with_store.config, _filing_payload()))

    scanner_with_store._client.publish.assert_not_awaited()
    assert scanner_with_store.earnings_republish_suppressed_cooldown == 1


@pytest.mark.asyncio
async def test_filing_event_starts_a_separate_earnings_cooldown_key(scanner_with_store):
    await scanner_with_store._handle_message(_msg(scanner_with_store.config.market_stream_channel, _bar_payload(close=180.0)))
    scanner_with_store.store.save_latest_factors("AAPL", 2025, 0.21, 8, 0.05, 5.5, 1.2, datetime.now(timezone.utc))

    await scanner_with_store._handle_message(_filing_msg(scanner_with_store.config, _filing_payload()))

    scanner_with_store._client.set.assert_awaited_once()
    args, kwargs = scanner_with_store._client.set.await_args
    assert args[0] == "earnings_republish_cooldown:AAPL"
    assert kwargs["ex"] == int(scanner_with_store.config.earnings_republish_cooldown_seconds)


@pytest.mark.asyncio
async def test_filing_event_uses_price_fallback_when_no_live_price(scanner_with_store, monkeypatch):
    monkeypatch.setattr("talonx_quant.fundamental_consumer._fetch_last_close", lambda ticker: 175.0)
    scanner_with_store.store.save_latest_factors("AAPL", 2025, 0.21, 8, 0.05, 5.5, 1.2, datetime.now(timezone.utc))

    await scanner_with_store._handle_message(_filing_msg(scanner_with_store.config, _filing_payload()))

    scanner_with_store._client.publish.assert_awaited_once()
    body = json.loads(scanner_with_store._client.publish.await_args.args[1])
    assert body["price"] == 175.0


@pytest.mark.asyncio
async def test_filing_event_suppressed_when_no_usable_price(scanner_with_store, monkeypatch):
    monkeypatch.setattr("talonx_quant.fundamental_consumer._fetch_last_close", lambda ticker: None)
    scanner_with_store.store.save_latest_factors("AAPL", 2025, 0.21, 8, 0.05, 5.5, 1.2, datetime.now(timezone.utc))

    await scanner_with_store._handle_message(_filing_msg(scanner_with_store.config, _filing_payload()))

    scanner_with_store._client.publish.assert_not_awaited()


@pytest.mark.asyncio
async def test_invalid_filing_payload_is_dropped(scanner_with_store):
    await scanner_with_store._handle_message(_filing_msg(scanner_with_store.config, {"ticker": "AAPL"}))
    scanner_with_store._client.publish.assert_not_awaited()
