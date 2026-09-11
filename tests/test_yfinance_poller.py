"""
tests/test_yfinance_poller.py
------------------------------------
Tests talonx_ingest.market_data.yfinance_poll.YFinancePoller.stream's
degraded-cycle handling: a poll cycle where _fetch_snapshots returns
data for only a fraction of symbols (per-symbol failures are already
swallowed inside _fetch_snapshots itself, so this never raises) must be
treated as a real failure -- backed off and, after enough consecutive
degraded cycles, escalated into a yfinance session reset -- not silently
treated as a healthy cycle forever (the bug this module fixes: a stuck
yfinance session previously required a manual process restart).

_fetch_snapshots and _reset_yfinance_session are monkeypatched so these
tests never touch the network or real yfinance internals -- same
"exercise the orchestration logic, mock the external boundary" approach
test_quant_consumer.py/test_dispatch_consumer.py use.
"""
from __future__ import annotations

from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock

import pytest

from talonx_ingest.config import MarketDataConfig
from talonx_ingest.market_data import yfinance_poll as poll_module
from talonx_ingest.market_data.models import DataSource, MarketEvent, MarketEventType
from talonx_ingest.market_data.yfinance_poll import YFinancePoller


def _event(symbol: str) -> MarketEvent:
    from datetime import datetime, timezone
    return MarketEvent(
        symbol=symbol, event_type=MarketEventType.BAR, source=DataSource.POLLING,
        timestamp=datetime.now(timezone.utc), open=1.0, high=1.0, low=1.0, close=1.0, volume=1.0, raw={},
    )


def _config(**overrides) -> MarketDataConfig:
    defaults = dict(
        yfinance_poll_interval_seconds=0.0, yfinance_backoff_base_seconds=0.0,
        yfinance_backoff_max_seconds=0.0, yfinance_degraded_cycle_failure_rate=0.5,
        yfinance_session_reset_after_failures=3,
    )
    defaults.update(overrides)
    return MarketDataConfig(**defaults)


@pytest.fixture
def poller(monkeypatch) -> YFinancePoller:
    p = YFinancePoller(_config())
    monkeypatch.setattr(poll_module, "jittered_backoff_seconds", lambda *a, **k: 0.0)
    return p


@pytest.mark.asyncio
async def test_healthy_cycle_does_not_reset_session(poller, monkeypatch):
    monkeypatch.setattr(poll_module, "is_premarket_window", lambda: False)
    symbols = ["AAPL", "MSFT", "NVDA"]
    monkeypatch.setattr(poller, "_fetch_snapshots", lambda syms: [_event(s) for s in syms])
    reset_mock = MagicMock()
    monkeypatch.setattr(poll_module, "_reset_yfinance_session", reset_mock)
    on_event = AsyncMock()

    async def stop_after_one_cycle(seconds):
        poller.stop()

    monkeypatch.setattr(poller, "_sleep_or_stop", stop_after_one_cycle)

    await poller.stream(symbols, on_event)

    assert on_event.await_count == 3
    reset_mock.assert_not_called()


@pytest.mark.asyncio
async def test_degraded_cycle_is_not_silently_treated_as_healthy(poller, monkeypatch):
    monkeypatch.setattr(poll_module, "is_premarket_window", lambda: False)
    # 3 symbols requested, only 1 comes back -- 67% failure, above the 50% threshold.
    symbols = ["AAPL", "MSFT", "NVDA"]
    monkeypatch.setattr(poller, "_fetch_snapshots", lambda syms: [_event("AAPL")])
    monkeypatch.setattr(poller, "_sleep_or_stop", AsyncMock())

    async def fake_sleep(seconds):
        poller.stop()  # stop right after the first degraded-cycle backoff sleep

    monkeypatch.setattr("asyncio.sleep", fake_sleep)
    on_event = AsyncMock()

    await poller.stream(symbols, on_event)

    # Still emits whatever partial data it got, exactly once (one cycle ran)...
    on_event.assert_awaited_once()
    # ...but backs off via asyncio.sleep rather than going straight to the
    # normal poll-interval sleep (_sleep_or_stop was never reached because
    # the degraded-cycle branch `continue`s past it).
    poller._sleep_or_stop.assert_not_called()


@pytest.mark.asyncio
async def test_premarket_cycle_fetches_but_suppresses_non_authoritative_callbacks(poller, monkeypatch):
    symbols = ["AAPL", "MSFT", "NVDA"]
    fetched = MagicMock(return_value=[_event(s) for s in symbols])
    monkeypatch.setattr(poller, "_fetch_snapshots", fetched)
    monkeypatch.setattr(poll_module, "is_premarket_window", lambda: True)
    monkeypatch.setattr(poller, "_sleep_or_stop", AsyncMock(side_effect=lambda _: poller.stop()))
    on_event = AsyncMock()

    await poller.stream(symbols, on_event)

    fetched.assert_called_once_with(symbols)
    on_event.assert_not_awaited()


@pytest.mark.asyncio
async def test_degraded_cycle_resets_session_after_threshold_consecutive_failures(monkeypatch):
    config = _config(yfinance_session_reset_after_failures=3)
    poller = YFinancePoller(config)
    monkeypatch.setattr(poll_module, "jittered_backoff_seconds", lambda *a, **k: 0.0)
    symbols = ["AAPL", "MSFT", "NVDA"]
    monkeypatch.setattr(poller, "_fetch_snapshots", lambda syms: [])  # 100% failure every cycle
    reset_mock = MagicMock()
    monkeypatch.setattr(poll_module, "_reset_yfinance_session", reset_mock)

    call_count = {"n": 0}

    async def fake_sleep(seconds):
        call_count["n"] += 1
        if call_count["n"] >= 3:  # stop right after the 3rd degraded cycle resets
            poller.stop()

    monkeypatch.setattr("asyncio.sleep", fake_sleep)

    await poller.stream(symbols, AsyncMock())

    reset_mock.assert_called_once()


@pytest.mark.asyncio
async def test_hard_exception_also_counts_toward_session_reset(monkeypatch):
    config = _config(yfinance_session_reset_after_failures=2)
    poller = YFinancePoller(config)
    monkeypatch.setattr(poll_module, "jittered_backoff_seconds", lambda *a, **k: 0.0)
    symbols = ["AAPL"]

    def raise_error(syms):
        raise ConnectionError("network down")

    monkeypatch.setattr(poller, "_fetch_snapshots", raise_error)
    reset_mock = MagicMock()
    monkeypatch.setattr(poll_module, "_reset_yfinance_session", reset_mock)

    call_count = {"n": 0}

    async def fake_sleep(seconds):
        call_count["n"] += 1
        if call_count["n"] >= 2:
            poller.stop()

    monkeypatch.setattr("asyncio.sleep", fake_sleep)

    await poller.stream(symbols, AsyncMock())

    reset_mock.assert_called_once()


@pytest.mark.asyncio
async def test_recovery_resets_consecutive_failure_count(monkeypatch):
    config = _config(yfinance_session_reset_after_failures=2)
    poller = YFinancePoller(config)
    monkeypatch.setattr(poll_module, "jittered_backoff_seconds", lambda *a, **k: 0.0)
    symbols = ["AAPL", "MSFT"]
    reset_mock = MagicMock()
    monkeypatch.setattr(poll_module, "_reset_yfinance_session", reset_mock)

    # Cycle 1: fails. Cycle 2: fully healthy (should reset the counter).
    # Cycle 3: fails again -- if the counter wasn't reset, this would be
    # "consecutive failure #2" and trigger a reset; it must NOT.
    responses = iter([[], [_event("AAPL"), _event("MSFT")], []])
    monkeypatch.setattr(poller, "_fetch_snapshots", lambda syms: next(responses))

    call_count = {"n": 0}

    async def fake_sleep(seconds):
        call_count["n"] += 1

    monkeypatch.setattr("asyncio.sleep", fake_sleep)
    monkeypatch.setattr(poller, "_sleep_or_stop", AsyncMock(side_effect=lambda s: poller.stop()))

    await poller.stream(symbols, AsyncMock())

    reset_mock.assert_not_called()


@pytest.mark.asyncio
async def test_too_few_symbols_does_not_trigger_degraded_logic(monkeypatch):
    """A 2-symbol poll (e.g. an earnings fast-track edge case) returning
    zero events -- 100% failure -- isn't statistically meaningful enough
    to call it a 'degraded cycle': the len(symbols) >= 3 guard means this
    falls through to the normal healthy-cycle path (_sleep_or_stop),
    never touching the backoff/session-reset machinery."""
    config = _config()
    poller = YFinancePoller(config)
    symbols = ["AAPL", "MSFT"]
    monkeypatch.setattr(poller, "_fetch_snapshots", lambda syms: [])
    reset_mock = MagicMock()
    monkeypatch.setattr(poll_module, "_reset_yfinance_session", reset_mock)
    sleep_or_stop_mock = AsyncMock(side_effect=lambda s: poller.stop())
    monkeypatch.setattr(poller, "_sleep_or_stop", sleep_or_stop_mock)

    await poller.stream(symbols, AsyncMock())

    sleep_or_stop_mock.assert_awaited_once()
    reset_mock.assert_not_called()


# ------------------------------------------------------------------
# 2026-08-17 live-data correctness fix: fast_info.last_volume is Yahoo's
# CUMULATIVE day-to-date volume (confirmed by tracing yfinance's own
# quote.py -- last_volume reads the last row of a DAILY-interval
# history() call), not a per-poll figure. _incremental_volume converts
# it to a genuine per-poll delta; talonx_quant.consumer sums event.volume
# across every tick in a minute bucket, so feeding it the raw cumulative
# number used to inflate minute volume by however many polls (up to ~12,
# at the 5s default interval) landed in that minute.
# ------------------------------------------------------------------

_JAN5_1400 = datetime(2026, 1, 5, 14, 0, tzinfo=timezone.utc)   # 09:00 ET (EST, UTC-5)
_JAN5_1500 = datetime(2026, 1, 5, 15, 0, tzinfo=timezone.utc)   # 10:00 ET, same day
_JAN5_1600 = datetime(2026, 1, 5, 16, 0, tzinfo=timezone.utc)   # 11:00 ET, same day
_JAN6_1400 = datetime(2026, 1, 6, 14, 0, tzinfo=timezone.utc)   # 09:00 ET, NEXT day


def test_first_observation_is_none_not_the_full_cumulative_value():
    poller = YFinancePoller(_config())
    assert poller._incremental_volume("AAPL", 500_000.0, _JAN5_1400) is None


def test_cumulative_volume_converts_to_the_documented_example_sequence():
    # TEST 1 -- poll 1 = 500,000 / poll 2 = 501,200 / poll 3 = 503,000
    # -> None (first observation), 1,200, 1,800.
    poller = YFinancePoller(_config())
    assert poller._incremental_volume("AAPL", 500_000.0, _JAN5_1400) is None
    assert poller._incremental_volume("AAPL", 501_200.0, _JAN5_1500) == pytest.approx(1_200.0)
    assert poller._incremental_volume("AAPL", 503_000.0, _JAN5_1600) == pytest.approx(1_800.0)


def test_volume_never_goes_negative(monkeypatch):
    # TEST 2 -- a same-day cumulative DECREASE must never produce a
    # negative increment.
    poller = YFinancePoller(_config())
    poller._incremental_volume("AAPL", 500_000.0, _JAN5_1400)  # first observation
    poller._incremental_volume("AAPL", 501_200.0, _JAN5_1500)  # baseline = 501,200

    result = poller._incremental_volume("AAPL", 499_000.0, _JAN5_1600)  # decreased
    assert result is None
    assert result != -2_200.0


def test_cumulative_reset_is_handled_safely_and_tracking_resumes():
    # TEST 3 -- a same-day reset (e.g. Yahoo data correction) yields one
    # honest "unknown" reading, then tracking resumes correctly from the
    # new (lower) baseline on the next poll -- never permanently poisoned.
    poller = YFinancePoller(_config())
    poller._incremental_volume("AAPL", 500_000.0, _JAN5_1400)
    poller._incremental_volume("AAPL", 501_200.0, _JAN5_1500)  # baseline = 501,200

    reset_result = poller._incremental_volume("AAPL", 100.0, _JAN5_1600)  # reset to 100
    assert reset_result is None

    resumed = poller._incremental_volume("AAPL", 150.0, _JAN6_1400.replace(day=5, hour=17))
    assert resumed == pytest.approx(50.0)  # 150 - 100, diffed against the NEW baseline


def test_new_trading_day_resets_state_correctly():
    # TEST 4 -- yesterday's cumulative total must never be diffed against
    # today's, even though today's early cumulative volume is numerically
    # far smaller than yesterday's late-session total.
    poller = YFinancePoller(_config())
    poller._incremental_volume("AAPL", 500_000.0, _JAN5_1400)
    poller._incremental_volume("AAPL", 999_000.0, _JAN5_1600)  # yesterday's late total

    first_poll_new_day = poller._incremental_volume("AAPL", 8_000.0, _JAN6_1400)
    assert first_poll_new_day is None  # NOT 8,000 - 999,000 (would be hugely negative)

    second_poll_new_day = poller._incremental_volume("AAPL", 8_500.0, _JAN6_1400.replace(hour=15))
    assert second_poll_new_day == pytest.approx(500.0)  # correctly diffs within the new day


def test_duplicate_stale_observation_does_not_double_count():
    # TEST 5 -- Yahoo hasn't updated between two polls -> delta is
    # exactly 0.0 (accurate), never a repeated/duplicated count.
    poller = YFinancePoller(_config())
    poller._incremental_volume("AAPL", 500_000.0, _JAN5_1400)
    first = poller._incremental_volume("AAPL", 501_200.0, _JAN5_1500)
    stale = poller._incremental_volume("AAPL", 501_200.0, _JAN5_1600)  # identical reading

    assert first == pytest.approx(1_200.0)
    assert stale == pytest.approx(0.0)


def test_missing_cumulative_value_leaves_state_untouched():
    # A poll where Yahoo returns no volume at all: no delta, and the next
    # SUCCESSFUL poll must still diff correctly against the last known
    # good value (the gap is absorbed automatically).
    poller = YFinancePoller(_config())
    poller._incremental_volume("AAPL", 500_000.0, _JAN5_1400)
    missing = poller._incremental_volume("AAPL", None, _JAN5_1500)
    assert missing is None

    recovered = poller._incremental_volume("AAPL", 501_200.0, _JAN5_1600)
    assert recovered == pytest.approx(1_200.0)  # still diffs against 500,000, not None/0


def test_ticker_specific_state_does_not_cross_contaminate():
    poller = YFinancePoller(_config())
    poller._incremental_volume("AAPL", 500_000.0, _JAN5_1400)
    poller._incremental_volume("MSFT", 10_000_000.0, _JAN5_1400)

    aapl_delta = poller._incremental_volume("AAPL", 500_500.0, _JAN5_1500)
    msft_delta = poller._incremental_volume("MSFT", 10_000_100.0, _JAN5_1500)

    assert aapl_delta == pytest.approx(500.0)
    assert msft_delta == pytest.approx(100.0)


def test_process_restart_is_a_fresh_first_observation_not_a_fabricated_spike():
    # A NEW YFinancePoller instance (simulating a process restart) must
    # treat every symbol as a first observation again, never inheriting
    # -- or fabricating from nothing -- a huge initial "volume" spike.
    old_poller = YFinancePoller(_config())
    old_poller._incremental_volume("AAPL", 500_000.0, _JAN5_1400)
    old_poller._incremental_volume("AAPL", 999_000.0, _JAN5_1600)

    new_poller = YFinancePoller(_config())  # fresh instance, empty state
    result = new_poller._incremental_volume("AAPL", 999_500.0, _JAN5_1600)
    assert result is None  # NOT 999,500 (the full cumulative day volume)


# --- _fetch_snapshots-level tests (mocked yf.Tickers) ---

class _FakeFastInfo:
    def __init__(self, last_price, last_volume, open_=100.0, day_high=105.0, day_low=95.0):
        self.last_price = last_price
        self.last_volume = last_volume
        self.open = open_
        self.day_high = day_high
        self.day_low = day_low


class _FakeTicker:
    def __init__(self, fast_info=None, raise_on_access=False):
        self._fast_info = fast_info
        self._raise_on_access = raise_on_access

    @property
    def fast_info(self):
        if self._raise_on_access:
            raise ConnectionError("simulated fetch failure")
        return self._fast_info


def _install_fake_yfinance(monkeypatch, tickers_by_symbol: dict):
    fake_tickers_obj = MagicMock()
    fake_tickers_obj.tickers = tickers_by_symbol
    fake_module = MagicMock()
    fake_module.Tickers.return_value = fake_tickers_obj
    monkeypatch.setitem(__import__("sys").modules, "yfinance", fake_module)


def test_fetch_snapshots_emits_incremental_volume_not_cumulative(monkeypatch):
    # TEST 8 -- normal polling behavior end-to-end: two successive
    # _fetch_snapshots calls, second one's event.volume must be the
    # delta, not the raw cumulative fast_info value.
    poller = YFinancePoller(_config())
    _install_fake_yfinance(monkeypatch, {"AAPL": _FakeTicker(_FakeFastInfo(150.0, 500_000.0))})
    first_events = poller._fetch_snapshots(["AAPL"])
    assert len(first_events) == 1
    assert first_events[0].volume is None  # first observation

    _install_fake_yfinance(monkeypatch, {"AAPL": _FakeTicker(_FakeFastInfo(150.5, 501_200.0))})
    second_events = poller._fetch_snapshots(["AAPL"])
    assert len(second_events) == 1
    assert second_events[0].volume == pytest.approx(1_200.0)
    assert second_events[0].volume != 501_200.0  # the bug: raw cumulative, not the delta


def test_fetch_snapshots_failed_symbol_produces_no_fabricated_bar(monkeypatch):
    # TEST 6 -- a per-symbol exception must skip that symbol entirely,
    # never publish a placeholder/fabricated BAR event for it.
    poller = YFinancePoller(_config())
    _install_fake_yfinance(monkeypatch, {"AAPL": _FakeTicker(raise_on_access=True)})

    events = poller._fetch_snapshots(["AAPL"])
    assert events == []


def test_fetch_snapshots_distinguishes_provider_exception_from_no_usable_row(monkeypatch):
    # A PROVIDER FETCH FAILURE (fast_info access raises) and a VALID
    # RESPONSE WITH NO USABLE MARKET ROW (fast_info returns cleanly but
    # last_price is None -- e.g. a halted/no-quote symbol) are two
    # architecturally distinct paths in _fetch_snapshots (an `except
    # Exception` at the bottom of the loop vs. an explicit `if last_price
    # is None: continue` earlier in it). Both must produce zero events --
    # neither may fabricate a bar -- but they are different states, not
    # the same one reached two ways.
    poller = YFinancePoller(_config())

    _install_fake_yfinance(monkeypatch, {"AAPL": _FakeTicker(raise_on_access=True)})
    exception_path_events = poller._fetch_snapshots(["AAPL"])

    _install_fake_yfinance(monkeypatch, {"AAPL": _FakeTicker(_FakeFastInfo(last_price=None, last_volume=500_000.0))})
    no_usable_row_events = poller._fetch_snapshots(["AAPL"])

    assert exception_path_events == []
    assert no_usable_row_events == []


# --- 2026-08-18 /ping observability completion: provider failure/retry/
# rate-limit counters -- genuine, in-process, directly testable without any
# real network or event loop (requests_failed/rate_limited are incremented
# as plain instance-attribute writes inside the sync _fetch_snapshots). ---

def test_fetch_snapshots_successful_poll_does_not_increment_failures(monkeypatch):
    poller = YFinancePoller(_config())
    _install_fake_yfinance(monkeypatch, {"AAPL": _FakeTicker(_FakeFastInfo(150.0, 500_000.0))})

    poller._fetch_snapshots(["AAPL"])

    assert poller.requests_failed == 0
    assert poller.rate_limited == 0


def test_fetch_snapshots_provider_exception_increments_requests_failed(monkeypatch):
    poller = YFinancePoller(_config())
    _install_fake_yfinance(monkeypatch, {"AAPL": _FakeTicker(raise_on_access=True)})

    poller._fetch_snapshots(["AAPL"])

    assert poller.requests_failed == 1
    assert poller.rate_limited == 0


def test_fetch_snapshots_no_usable_row_does_not_count_as_a_failure(monkeypatch):
    # Ordinary "no new bar" response (fast_info returns cleanly, no
    # last_price yet) must NOT be counted as a provider failure.
    poller = YFinancePoller(_config())
    _install_fake_yfinance(monkeypatch, {"AAPL": _FakeTicker(_FakeFastInfo(last_price=None, last_volume=500_000.0))})

    poller._fetch_snapshots(["AAPL"])

    assert poller.requests_failed == 0


def test_fetch_snapshots_rate_limit_exception_increments_rate_limited(monkeypatch):
    class _RateLimitedTicker(_FakeTicker):
        @property
        def fast_info(self):
            raise ConnectionError("HTTP Error 429: Too Many Requests")

    poller = YFinancePoller(_config())
    _install_fake_yfinance(monkeypatch, {"AAPL": _RateLimitedTicker()})

    poller._fetch_snapshots(["AAPL"])

    assert poller.requests_failed == 1
    assert poller.rate_limited == 1


def test_fetch_snapshots_non_rate_limit_exception_does_not_count_as_rate_limited(monkeypatch):
    poller = YFinancePoller(_config())
    _install_fake_yfinance(monkeypatch, {"AAPL": _FakeTicker(raise_on_access=True)})  # plain ConnectionError

    poller._fetch_snapshots(["AAPL"])

    assert poller.requests_failed == 1
    assert poller.rate_limited == 0


@pytest.mark.asyncio
async def test_stream_flushes_provider_failures_to_metrics_publisher(poller, monkeypatch):
    metrics_publisher = AsyncMock()
    poller._metrics_publisher = metrics_publisher

    def fake_fetch(syms):
        poller._requests_failed += 2  # simulates 2 per-symbol exceptions this cycle
        return [_event(s) for s in syms]  # every symbol still "succeeds" overall -- a healthy, not degraded, cycle

    monkeypatch.setattr(poller, "_fetch_snapshots", fake_fetch)
    monkeypatch.setattr(poller, "_sleep_or_stop", AsyncMock(side_effect=lambda s: poller.stop()))

    await poller.stream(["AAPL", "MSFT", "NVDA"], AsyncMock())

    failure_calls = [c for c in metrics_publisher.incr_metric.await_args_list if c.args[1] == "provider_requests_failed"]
    assert len(failure_calls) == 1
    assert failure_calls[0].args[2] == 2


@pytest.mark.asyncio
async def test_stream_successful_cycle_does_not_flush_any_provider_metric(poller, monkeypatch):
    metrics_publisher = AsyncMock()
    poller._metrics_publisher = metrics_publisher

    monkeypatch.setattr(poller, "_fetch_snapshots", lambda syms: [_event(s) for s in syms])
    monkeypatch.setattr(poller, "_sleep_or_stop", AsyncMock(side_effect=lambda s: poller.stop()))

    await poller.stream(["AAPL"], AsyncMock())

    metrics_publisher.incr_metric.assert_not_awaited()


@pytest.mark.asyncio
async def test_stream_hard_failure_flushes_a_retry_to_metrics_publisher(poller, monkeypatch):
    metrics_publisher = AsyncMock()
    poller._metrics_publisher = metrics_publisher

    def raise_error(syms):
        poller.stop()  # stop after this one failed cycle
        raise ConnectionError("cycle failed")

    monkeypatch.setattr(poller, "_fetch_snapshots", raise_error)
    monkeypatch.setattr("asyncio.sleep", AsyncMock())

    await poller.stream(["AAPL"], AsyncMock())

    retry_calls = [c for c in metrics_publisher.incr_metric.await_args_list if c.args[1] == "provider_retries"]
    assert len(retry_calls) == 1
    assert retry_calls[0].args[2] == 1


def test_fetch_snapshots_one_ticker_failure_does_not_break_others(monkeypatch):
    # TEST 7 -- AAPL fails, MSFT/NVDA must still produce real events with
    # correctly-computed (not fabricated) volume.
    poller = YFinancePoller(_config())
    _install_fake_yfinance(monkeypatch, {
        "AAPL": _FakeTicker(raise_on_access=True),
        "MSFT": _FakeTicker(_FakeFastInfo(300.0, 200_000.0)),
        "NVDA": _FakeTicker(_FakeFastInfo(900.0, 50_000.0)),
    })

    events = poller._fetch_snapshots(["AAPL", "MSFT", "NVDA"])
    symbols = {e.symbol for e in events}
    assert symbols == {"MSFT", "NVDA"}
    assert all(e.volume is None for e in events)  # both first observations
