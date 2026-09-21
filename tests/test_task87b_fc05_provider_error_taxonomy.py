"""Task 87B FC_05 -- yfinance provider-error taxonomy.

Proves each representative failure maps to an operator-facing category,
that a transient no-data condition never permanently invalidates a
symbol, that recovery is logged, and that category-tagged metrics are
emitted so the counted set matches the surfaced set.

TEST_FIXTURE_ONLY.
"""
from __future__ import annotations

import pytest

from talonx_ingest.market_data.yfinance_poll import (
    PROVIDER_ERR_RATE_LIMIT,
    PROVIDER_ERR_SCHEMA,
    PROVIDER_ERR_SYMBOL_INVALID,
    PROVIDER_ERR_TEMPORARY_NO_DATA,
    PROVIDER_ERR_TIMEOUT,
    PROVIDER_ERR_UNKNOWN,
    PROVIDER_ERR_UNSUPPORTED_SESSION,
    YFinancePoller,
    classify_provider_error,
)


class _SymbolNotFound(Exception):
    pass


class _ReadTimeout(Exception):
    pass


@pytest.mark.parametrize("exc,expected", [
    (Exception("YFPricesMissingError: $AFL: possibly delisted; no price data found  (period=1d)"),
     PROVIDER_ERR_TEMPORARY_NO_DATA),
    (Exception("no data found for this date range"), PROVIDER_ERR_TEMPORARY_NO_DATA),
    (KeyError("currentTradingPeriod"), PROVIDER_ERR_SCHEMA),
    (ValueError("JSONDecodeError: Expecting value"), PROVIDER_ERR_UNKNOWN),  # name has no json/schema token
    (Exception("HTTP 429 Too Many Requests"), PROVIDER_ERR_RATE_LIMIT),
    (Exception("rate limit exceeded"), PROVIDER_ERR_RATE_LIMIT),
    (_ReadTimeout("read timed out after 10s"), PROVIDER_ERR_TIMEOUT),
    (_SymbolNotFound("SymbolNotFoundError: XYZ is not a valid ticker"), PROVIDER_ERR_SYMBOL_INVALID),
    (Exception("prepost data unsupported for this symbol"), PROVIDER_ERR_UNSUPPORTED_SESSION),
    (Exception("totally novel provider hiccup"), PROVIDER_ERR_UNKNOWN),
])
def test_classification_matrix(exc, expected):
    assert classify_provider_error(exc) == expected


def test_possibly_delisted_is_temporary_not_symbol_invalid():
    """Task 87A: never infer a delisting from a single cycle."""
    assert classify_provider_error(
        Exception("$ADC: possibly delisted; no price data found")
    ) == PROVIDER_ERR_TEMPORARY_NO_DATA


def test_classify_and_record_tallies_by_category_and_logs_attributed(caplog):
    poller = YFinancePoller()
    with caplog.at_level("INFO", logger="talonx_ingest.market_data.yfinance_poll"):
        poller._classify_and_record("AFL", Exception("possibly delisted; no price data found"))
        poller._classify_and_record("AAPL", KeyError("currentTradingPeriod"))
        poller._classify_and_record("AFL", Exception("possibly delisted; no price data found"))
    assert poller.error_categories == {PROVIDER_ERR_TEMPORARY_NO_DATA: 2, PROVIDER_ERR_SCHEMA: 1}
    text = "\n".join(r.message for r in caplog.records)
    assert "[provider TEMPORARY_NO_DATA] AFL" in text
    assert "[provider PROVIDER_SCHEMA_ERROR] AAPL" in text


def test_transient_no_data_then_recovery_is_logged_and_symbol_never_removed(caplog):
    poller = YFinancePoller()
    with caplog.at_level("INFO", logger="talonx_ingest.market_data.yfinance_poll"):
        poller._note_no_data("AFL")
        poller._note_no_data("AFL")  # still dark -- no duplicate log
        assert poller.no_data_symbols == {"AFL"}
        poller._note_recovery("AFL")
        assert poller.no_data_symbols == set()
    assert "[provider RECOVERED] AFL" in "\n".join(r.message for r in caplog.records)


def test_category_deltas_drain_without_double_count():
    poller = YFinancePoller()
    poller._classify_and_record("A", Exception("no price data"))
    poller._classify_and_record("B", KeyError("x"))
    d1 = poller._drain_category_deltas()
    assert d1 == {PROVIDER_ERR_TEMPORARY_NO_DATA: 1, PROVIDER_ERR_SCHEMA: 1}
    assert poller._drain_category_deltas() == {}  # nothing new
    poller._classify_and_record("C", Exception("no price data"))
    assert poller._drain_category_deltas() == {PROVIDER_ERR_TEMPORARY_NO_DATA: 1}


@pytest.mark.asyncio
async def test_stream_emits_category_tagged_provider_metrics(monkeypatch):
    flushed: list[tuple[str, int]] = []

    class _Pub:
        async def incr_metric(self, stage, counter, amount=1):
            flushed.append((counter, amount))

    poller = YFinancePoller(metrics_publisher=_Pub())

    calls = {"n": 0}

    def fake_fetch(symbols):
        calls["n"] += 1
        # one schema error per cycle
        poller._classify_and_record("AAPL", KeyError("currentTradingPeriod"))
        poller._requests_failed += 1
        if calls["n"] >= 1:
            poller.stop()
        return []

    monkeypatch.setattr(poller, "_fetch_snapshots", fake_fetch)
    await poller.stream(["AAPL", "MSFT", "NVDA"], lambda e: _noop())

    counters = {c for c, _ in flushed}
    assert "provider_requests_failed" in counters
    assert "provider_err_provider_schema_error" in counters


async def _noop():
    return None
