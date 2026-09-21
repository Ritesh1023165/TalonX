"""Task 66B-PREP Part 2: deterministic initial Quant preseed ordering.

Covers talonx_quant/preseed_ordering.py's run_initial_preseed() (causal
completion, fail-closed per-symbol isolation, zero-ready non-fatal
reporting, config-driven thresholds) and run_talonx.py's
WatchlistDrivenQuantPreseed (avoid double-preseeding the initial set while
preserving its unchanged reactive preseed loop for later additions)."""
from __future__ import annotations

import asyncio
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

import pytest

from talonx_quant.buffer import RollingBarBuffer
from talonx_quant.preseed_ordering import InitialPreseedReport, run_initial_preseed

HTF_PERIOD = 200
MIN_1M = 120


@dataclass(frozen=True)
class FakeQuantConfig:
    min_bars_required: int = MIN_1M
    htf_sma_period: int = HTF_PERIOD


class FakeScanner:
    """Same shape as tests/test_task65b_warmup.py's FakeScanner -- real
    RollingBarBuffer instances driven by a controllable fake
    preseed_symbols, isolating preseed_ordering.py's own logic from
    network/yfinance."""

    def __init__(self, populate: dict[str, tuple[int, int]] | None = None, raise_on_preseed: bool = False):
        self.config = FakeQuantConfig()
        self.buffer = RollingBarBuffer(max_bars_per_symbol=250)
        self.buffer_htf = RollingBarBuffer(max_bars_per_symbol=250)
        self._populate = populate or {}
        self._raise_on_preseed = raise_on_preseed
        self.preseed_calls: list[list[str]] = []

    async def preseed_symbols(self, symbols: list[str]) -> None:
        self.preseed_calls.append(list(symbols))
        if self._raise_on_preseed:
            raise RuntimeError("simulated preseed failure")
        base = datetime(2026, 8, 21, 9, 30, tzinfo=timezone.utc)
        for symbol in symbols:
            n_1m, n_15m = self._populate.get(symbol.upper(), (0, 0))
            for i in range(n_1m):
                ts = base + timedelta(minutes=i)
                self.buffer.add_bar(symbol, ts, 100.0, 101.0, 99.0, 100.0 + (i % 5), 1000, session="regular")
            for i in range(n_15m):
                ts = base + timedelta(minutes=15 * i)
                self.buffer_htf.add_bar(symbol, ts, 100.0, 101.0, 99.0, 100.0 + (i % 7), 1000, session="regular")


@pytest.mark.asyncio
async def test_empty_universe_is_not_blocked():
    scanner = FakeScanner()
    report = await run_initial_preseed(scanner, [])
    assert report.requested_symbols == ()
    assert report.ready_symbols == []
    assert report.is_blocked is False  # empty watchlist is not a blocked state
    assert scanner.preseed_calls == []  # never called for an empty request


@pytest.mark.asyncio
async def test_full_ready_reports_not_blocked():
    scanner = FakeScanner(populate={"AAPL": (120, 200)})
    report = await run_initial_preseed(scanner, ["AAPL"])
    assert report.ready_symbols == ["AAPL"]
    assert report.is_blocked is False


@pytest.mark.asyncio
async def test_zero_ready_is_reported_blocked_but_never_raises():
    scanner = FakeScanner()  # nothing populated
    report = await run_initial_preseed(scanner, ["AAPL", "MSFT"])
    assert report.ready_symbols == []
    assert report.is_blocked is True
    # no exception raised -- policy (fatal or not) is the caller's decision


@pytest.mark.asyncio
async def test_partial_preseed_failure_isolated_fail_closed():
    scanner = FakeScanner(populate={"AAPL": (120, 200)})  # MSFT never populated
    report = await run_initial_preseed(scanner, ["AAPL", "MSFT"])
    by_symbol = {s.symbol: s for s in report.statuses}
    assert by_symbol["AAPL"].ready is True
    assert by_symbol["MSFT"].ready is False
    assert report.is_blocked is False  # at least one symbol ready


@pytest.mark.asyncio
async def test_no_synthetic_bars_on_preseed_exception():
    scanner = FakeScanner(raise_on_preseed=True)
    report = await run_initial_preseed(scanner, ["AAPL"])
    assert report.statuses[0].bar_count_1m == 0
    assert report.statuses[0].bar_count_15m_htf == 0
    assert report.is_blocked is True


@pytest.mark.asyncio
async def test_thresholds_read_from_scanner_config_not_hardcoded():
    scanner = FakeScanner(populate={"AAPL": (50, 60)})
    scanner.config = FakeQuantConfig(min_bars_required=40, htf_sma_period=50)
    report = await run_initial_preseed(scanner, ["AAPL"])
    assert report.statuses[0].required_1m_bars == 40
    assert report.statuses[0].required_15m_bars == 50
    assert report.statuses[0].ready is True  # 50>=40 and 60>=50


@pytest.mark.asyncio
async def test_causal_ordering_preseed_completes_before_verification_reflects_it():
    scanner = FakeScanner(populate={"AAPL": (120, 200)})
    assert scanner.buffer.bar_count("AAPL") == 0  # cold before the call
    report = await run_initial_preseed(scanner, ["AAPL"])
    # awaited to completion -- verification below reflects POST-preseed
    # state, proving preseed_symbols() ran and finished before this
    # function returned (the property main() relies on for ordering).
    assert scanner.preseed_calls == [["AAPL"]]
    assert report.ready_symbols == ["AAPL"]


@pytest.mark.asyncio
async def test_report_to_dict_shape():
    scanner = FakeScanner(populate={"AAPL": (120, 200)})
    report = await run_initial_preseed(scanner, ["AAPL"])
    payload = report.to_dict()
    assert payload["requested_count"] == 1
    assert payload["ready_count"] == 1
    assert payload["is_blocked"] is False
    assert payload["statuses"][0]["symbol"] == "AAPL"


class FakeWatchlistStore:
    def __init__(self, active: list[str]):
        self._active = list(active)

    def list_active_symbols(self) -> list[str]:
        return list(self._active)


@pytest.mark.asyncio
async def test_no_double_preseed_of_the_initial_set(monkeypatch):
    """main() awaits run_initial_preseed() for the startup watchlist BEFORE
    constructing WatchlistDrivenQuantPreseed -- passing those symbols as
    already_preseeded_symbols must make run()'s own initial-preseed step a
    no-op for them (still preseeding anything genuinely new)."""
    import run_talonx

    scanner = FakeScanner(populate={"AAPL": (120, 200), "MSFT": (120, 200)})
    store = FakeWatchlistStore(["AAPL", "MSFT"])
    reconciler = run_talonx.WatchlistDrivenQuantPreseed(
        store, scanner, poll_interval_seconds=3600, already_preseeded_symbols={"AAPL", "MSFT"},
    )

    task = asyncio.create_task(reconciler.run())
    await asyncio.sleep(0)  # let run()'s startup block execute
    reconciler.stop()
    await task

    assert scanner.preseed_calls == []  # both already covered -- nothing repeated


@pytest.mark.asyncio
async def test_pending_initial_symbols_still_preseeded(monkeypatch):
    """A symbol added to the watchlist during main()'s earlier blocking
    await (so it wasn't part of already_preseeded_symbols) must still be
    covered by run()'s own initial pass -- avoiding double-preseed must
    never silently drop a genuinely new symbol."""
    import run_talonx

    scanner = FakeScanner(populate={"AAPL": (120, 200), "MSFT": (120, 200)})
    store = FakeWatchlistStore(["AAPL", "MSFT"])
    reconciler = run_talonx.WatchlistDrivenQuantPreseed(
        store, scanner, poll_interval_seconds=3600, already_preseeded_symbols={"AAPL"},
    )

    task = asyncio.create_task(reconciler.run())
    await asyncio.sleep(0)
    reconciler.stop()
    await task

    assert scanner.preseed_calls == [["MSFT"]]


@pytest.mark.asyncio
async def test_reactive_preseed_for_later_additions_still_works(monkeypatch):
    """The Task 66B-PREP change only touches the INITIAL pass -- reactive
    preseed for a ticker added/resumed after startup must be completely
    unchanged."""
    import run_talonx

    scanner = FakeScanner(populate={"AAPL": (120, 200), "TSLA": (120, 200)})
    store = FakeWatchlistStore(["AAPL"])
    reconciler = run_talonx.WatchlistDrivenQuantPreseed(
        store, scanner, poll_interval_seconds=0.01, already_preseeded_symbols={"AAPL"},
    )

    task = asyncio.create_task(reconciler.run())
    await asyncio.sleep(0)
    assert scanner.preseed_calls == []  # AAPL already covered, nothing yet for TSLA

    store._active.append("TSLA")  # ticker added mid-session
    await asyncio.sleep(0.05)  # let the reactive poll loop notice
    reconciler.stop()
    await task

    assert scanner.preseed_calls == [["TSLA"]]


@pytest.mark.asyncio
async def test_default_already_preseeded_is_empty_when_omitted():
    """A caller that never used run_initial_preseed() (e.g. an older test,
    or main() with quant_scanner=None so initial_preseed_report stays
    None) must get the exact pre-Task-66B-PREP behavior back -- the whole
    initial watchlist preseeded by run() itself."""
    import run_talonx

    scanner = FakeScanner(populate={"AAPL": (120, 200)})
    store = FakeWatchlistStore(["AAPL"])
    reconciler = run_talonx.WatchlistDrivenQuantPreseed(store, scanner, poll_interval_seconds=3600)

    task = asyncio.create_task(reconciler.run())
    await asyncio.sleep(0)
    reconciler.stop()
    await task

    assert scanner.preseed_calls == [["AAPL"]]
