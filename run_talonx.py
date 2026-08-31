"""
run_talonx.py
----------------
Single entrypoint that starts EVERYTHING together, in one process, one
terminal, one Ctrl+C to stop:

  - Module 1, periodic:    SEC filing ingestion + news ingestion, run
                            immediately on startup, then re-run on a
                            repeating interval (default every 6 hours).
  - Module 1, continuous:  live market data (Polygon WebSocket, or
                            yfinance polling fallback), streaming until
                            stopped. Also polls pre-market prices
                            (PreMarketPoller, --skip-premarket) for the
                            whole watchlist during a configurable UTC
                            window, since the regular feed above only
                            reflects regular-session prices.
  - Module 2, continuous:  the quant scanner, consuming that market data
                            via Redis and publishing QuantSignals.
  - Module 3, continuous:  the research agent, consuming those QuantSignals,
                            retrieving filing context from ChromaDB, and
                            publishing LLM-generated ResearchReports (Gemini
                            or a local Ollama model -- see
                            TALONX_BRAIN_LLM_PROVIDER in talonx_brain/config.py).
  - Module 4, continuous:  the decision engine, correlating QuantSignals
                            and ResearchReports per ticker, and publishing
                            ActionableAlerts when they agree or conflict.
  - Module 5, continuous:  the dispatch agent, consuming those
                            ActionableAlerts, recording them to the audit
                            trail (SQLite), and pushing to Telegram if
                            configured.
  - Module 6, continuous:  the paper trading engine, simulating BUY/SELL
                            execution on ActionableAlerts for tickers with
                            paper trading enabled (talonx_watchlist), and
                            publishing PaperTradeExecutions that Module 5
                            also notifies on.

Phase 2 (LONG_TERM horizon) adds, for tickers tagged LONG_TERM or
DUAL_HORIZON in talonx_watchlist (see its strategy_horizon column):
  - periodic:    structured SEC XBRL financials ingestion (separate from,
                  alongside, the existing filing-TEXT ingestion above --
                  both run for a LONG_TERM ticker, since moat/DCF research
                  needs the qualitative text too).
  - continuous:  a slow (default daily) price poll for tickers that are
                  ONLY long-term (a DUAL_HORIZON ticker already gets a
                  price stream from Module 1's regular continuous feed
                  above -- this doesn't double up for those).
  - continuous:  the fundamental factor scanner (talonx_quant's sibling to
                  the technical scanner), publishing FundamentalFactorSignals.
  - continuous:  the long-term paper trading engine (talonx_paper's
                  sibling to Module 6 above), with its own recurring DCA
                  contribution loop.
Modules 3/4/5 (talonx_brain/talonx_core/talonx_dispatch) already handle
BOTH horizons internally within the SAME class/task started above --
no separate construction needed for those three.

Module 3 is OPTIONAL here, same "degrade, don't crash" philosophy as Redis
publishing elsewhere in this project: if the configured LLM provider isn't
ready (GEMINI_API_KEY not set for the "gemini" provider, or
talonx_brain/requirements.txt isn't installed for either provider), it's
logged once as a warning and the rest of the pipeline runs normally
without it. Use --skip-brain to leave it out on purpose even when it's
configured. Module 5 degrades the same way if its audit database can't be
opened (rare -- a bad path/permissions issue; Telegram itself is already
optional and handled internally, so its absence never disables the
module). Modules 2 and 4 have no such optional dependency (just
redis.asyncio + pydantic, already required everywhere else in this file),
so they're always started unless explicitly skipped.

EVERY continuous component can be pulled out with its own --skip-* flag
(market data, quant scanner, brain, core, dispatch, paper trading) --
handy while actively iterating on one piece: run the others here and the
one you're working on in its own terminal (`python -m talonx_quant.run`,
etc.) without restarting this whole process every time you make a change.

NOT included here, and never will be: the Streamlit dashboard
(talonx_dispatch/app.py). Streamlit reruns its entire script top-to-bottom
on every interaction/autorefresh tick, which is fundamentally incompatible
with holding a persistent asyncio task open in this process -- see that
file's own docstring. It reads the same audit trail this file's dispatch
agent writes to, so run it ALONGSIDE this file, in its own terminal:
    streamlit run talonx_dispatch\\app.py

Which tickers get tracked is no longer a startup-only decision. It's read
from talonx_watchlist's SQLite store (~/.talonx/watchlist.db by default),
which the Streamlit dashboard above can add to / remove from at any time --
see talonx_watchlist/store.py and app.py's new "Tracked tickers" section.
On a fresh install (empty store), it's seeded with one default ticker
(TALONX_WATCHLIST_DEFAULT_SYMBOL, default MSFT). Market data streaming
picks up an add/remove within one poll interval
(TALONX_WATCHLIST_POLL_INTERVAL, default 10s) by restarting the stream
with the new symbol set; filing/news/financials ingestion for a NEWLY
added, resumed, or re-tagged-LONG_TERM ticker is ALSO triggered within
one poll interval (WatchlistDrivenIngestion, below) -- it doesn't wait
for periodic_ingestion_loop's/periodic_long_term_financials_loop's next
scheduled --interval-hours cycle, which used to leave a freshly-tagged
LONG_TERM ticker with zero fundamental data for up to several hours.
Positional ticker args below still work, but only as a ONE-TIME seed for
a genuinely empty store -- once the store has any rows, they're ignored
in favor of the dashboard.

Replaces running `talonx_ingest.pipeline`, `talonx_ingest.news.pipeline`,
`talonx_ingest.market_data.run`, `talonx_quant.run`, `talonx_brain.run`,
`talonx_core.run`, `talonx_dispatch.run`, and `talonx_paper.run` by hand
in eight separate terminals.

Usage:
    python run_talonx.py
    python run_talonx.py AAPL MSFT NVDA TSLA   # only seeds an empty watchlist
    python run_talonx.py --interval-hours 12
    python run_talonx.py --skip-ingestion       # skip periodic filing/news ingestion
    python run_talonx.py --skip-market-data     # skip Module 1's live market stream
    python run_talonx.py --skip-quant           # skip Module 2 (talonx_quant)
    python run_talonx.py --skip-brain           # skip Module 3 (talonx_brain)
    python run_talonx.py --skip-core            # skip Module 4 (talonx_core)
    python run_talonx.py --skip-dispatch        # skip Module 5 (talonx_dispatch)
    python run_talonx.py --skip-paper-trading   # skip Module 6 (talonx_paper)
    python run_talonx.py --skip-premarket       # skip pre-market price monitoring

    # e.g. iterating on talonx_quant: run everything ELSE here, run
    # talonx_quant yourself in another terminal so you can restart just
    # that one process on each change:
    python run_talonx.py --skip-quant

Stop everything with Ctrl+C.
"""
from __future__ import annotations

import argparse
import asyncio
import logging
import os
import signal
from datetime import datetime, timedelta, timezone

from talonx_ingest.config import MarketDataConfig, settings
from talonx_ingest.earnings import fetch_earnings_calendar
from talonx_ingest.edgar.client import EdgarClient
from talonx_ingest.events.publisher import RedisEventPublisher
from talonx_ingest.market_data.manager import MarketDataManager
from talonx_ingest.market_data.run import make_on_event
from talonx_ingest.market_data.yfinance_poll import YFinancePoller, fetch_extended_hours_quote
from talonx_ingest.news.pipeline import run_news_ingestion
from talonx_ingest.pipeline import ingest_earnings_filing, run_ingestion, run_long_term_financials_ingestion
from talonx_ingest.poller import DEFAULT_REFRESH_WARN_SECONDS, fetch_watchlist_quotes
from talonx_ingest.processing.chunker import DocumentChunker
from talonx_ingest.session import is_premarket_window
from talonx_ingest.storage.ledger import IngestionLedger
from talonx_ingest.storage.vector_store import VectorStore, get_vector_store
from talonx_quant.config import QuantConfig
from talonx_quant.consumer import QuantScanner
from talonx_quant.fundamental_consumer import FundamentalScanner
from talonx_quant.preseed_ordering import run_initial_preseed
from talonx_quant.store import QuantStateStore
from talonx_brain.config import BrainConfig
from talonx_brain.consumer import ResearchAgent
from talonx_brain.store import BrainStatsStore
from talonx_core.config import DEFAULT_ALERT_OUTBOX_PATH, CoreConfig
from talonx_core.consumer import DecisionEngine
from talonx_core.store import TickerStateStore
from talonx_dispatch.consumer import DispatchAgent
from talonx_paper.config import PaperConfig
from talonx_paper.consumer import LongTermPaperEngine, PaperTradingEngine
from talonx_paper.store import PaperTradingStore
from talonx_watchlist.config import WatchlistConfig
from talonx_watchlist.store import TickerWatchlistStore

from talonx_ops.provider_status import configured_market_data_provider, paper_execution_path_label
from talonx_ops.runtime_metadata import write_runtime_metadata

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger("run_talonx")


def _env_float(name: str, default: float) -> float:
    try:
        return float(os.environ.get(name, default))
    except (TypeError, ValueError):
        return default


def _env_int(name: str, default: int) -> int:
    try:
        return int(os.environ.get(name, default))
    except (TypeError, ValueError):
        return default


def _diff_symbols(old: set[str], new: set[str]) -> tuple[set[str], set[str]]:
    """Returns (added, removed) between two symbol sets."""
    return new - old, old - new


class WatchlistDrivenMarketData:
    """
    Keeps a MarketDataManager's stream aligned with talonx_watchlist's
    live-editable ticker list, without needing incremental subscribe/
    unsubscribe support in either backend (Polygon WS or yfinance
    polling). Simple over precise: on any add/remove, detected by polling
    the store every `poll_interval_seconds`, the current stream is stopped
    and a fresh one started with the new symbol set. A few seconds of
    reconnect gap on the Polygon WS path is an acceptable trade for not
    needing surgical per-backend incremental-update code -- see the
    watchlist plan/README for the full rationale.

    If the watchlist is empty (every ticker removed), stays idle -- logged
    once -- rather than calling stream([]), which raises ValueError.
    """

    def __init__(
        self, watchlist_store: TickerWatchlistStore, on_event, poll_interval_seconds: float,
        metrics_publisher=None,
    ):
        self._store = watchlist_store
        self._on_event = on_event
        self._poll_interval = poll_interval_seconds
        self._stop_event = asyncio.Event()
        self._manager: MarketDataManager | None = None
        self._task: asyncio.Task | None = None
        self._current_symbols: set[str] = set()
        self._was_idle_empty = False
        # 2026-08-18 /ping observability fix: forwarded to each
        # MarketDataManager this reconciler constructs -- see
        # MarketDataManager.__init__'s own docstring. Optional/additive.
        self._metrics_publisher = metrics_publisher

    def stop(self) -> None:
        self._stop_event.set()
        if self._manager is not None:
            self._manager.stop()

    async def run(self) -> None:
        await self._reconcile()
        while not self._stop_event.is_set():
            try:
                await asyncio.wait_for(self._stop_event.wait(), timeout=self._poll_interval)
            except asyncio.TimeoutError:
                pass  # normal case: poll interval elapsed, check for changes
            if self._stop_event.is_set():
                break
            await self._reconcile()
        await self._stop_current()

    async def _reconcile(self) -> None:
        new_symbols = set(self._store.list_active_symbols())
        added, removed = _diff_symbols(self._current_symbols, new_symbols)
        if not added and not removed:
            return

        logger.info(
            "Ticker watchlist changed (added=%s, removed=%s) -- restarting market data stream",
            sorted(added) or "none", sorted(removed) or "none",
        )
        await self._stop_current()
        self._current_symbols = new_symbols

        if not new_symbols:
            if not self._was_idle_empty:
                logger.warning(
                    "Ticker watchlist is empty -- market data streaming paused "
                    "until a ticker is added via the dashboard."
                )
                self._was_idle_empty = True
            return

        self._was_idle_empty = False
        self._manager = MarketDataManager(metrics_publisher=self._metrics_publisher)
        self._task = asyncio.create_task(
            self._manager.stream(sorted(new_symbols), self._on_event), name="market_data_stream"
        )

    async def _stop_current(self) -> None:
        if self._manager is not None:
            self._manager.stop()
        if self._task is not None:
            try:
                await self._task
            except Exception as exc:  # noqa: BLE001 -- a stream failure shouldn't kill the reconciler
                logger.warning("Previous market data stream ended with an error: %s", exc)
            self._task = None
        self._manager = None


class LongTermPriceRunner:
    """
    Phase 2's slow-cadence price feed for LONG_TERM-ONLY tickers (a
    DUAL_HORIZON ticker already gets a price stream from
    WatchlistDrivenMarketData above -- this deliberately EXCLUDES those,
    to avoid double-publishing ticks for the same symbol). Reuses
    talonx_ingest.market_data.yfinance_poll.YFinancePoller -- the same
    fallback poller Module 1's continuous feed already uses when Polygon
    isn't configured -- just at a much longer interval (default daily,
    TALONX_LT_PRICE_POLL_INTERVAL), since margin-of-safety math needs A
    current price, not minute-fresh ticks (the spec's "bypass minute-bar
    TECHNICAL SCANNING" for LONG_TERM tickers -- this poller never
    computes RSI/MACD, it only keeps talonx_paper/talonx_quant's
    fundamental scanner fed with a price to value against).

    Same reconcile-by-restarting-the-whole-stream pattern
    WatchlistDrivenMarketData already uses, for the same reason: no
    incremental subscribe/unsubscribe support needed in the poller.

    `active_earnings_symbols_fn`, if given, is called on every reconcile
    to ALSO exclude any ticker currently owned by EarningsFastTrackPoller
    (Event-Driven Earnings Radar, Requirement 6) -- same "avoid double-
    publishing ticks for the same symbol" reasoning that already excludes
    DUAL_HORIZON tickers above, extended to cover the OTHER situation
    where two independent pollers could race MarketTickEvent ticks for
    one symbol onto talonx:market:stream with no ordering/session
    tiebreak: this runner's regular-session tick could otherwise silently
    overwrite the post-earnings extended-hours price the fast-track
    poller just captured.
    """

    def __init__(
        self, watchlist_store: TickerWatchlistStore, on_event, watchlist_poll_interval_seconds: float,
        price_poll_interval_seconds: float, active_earnings_symbols_fn=None,
    ):
        self._store = watchlist_store
        self._on_event = on_event
        self._watchlist_poll_interval = watchlist_poll_interval_seconds
        self._price_poll_interval = price_poll_interval_seconds
        self._active_earnings_symbols_fn = active_earnings_symbols_fn
        self._stop_event = asyncio.Event()
        self._poller: YFinancePoller | None = None
        self._task: asyncio.Task | None = None
        self._current_symbols: set[str] = set()

    def stop(self) -> None:
        self._stop_event.set()
        if self._poller is not None:
            self._poller.stop()

    def _long_term_only_symbols(self) -> set[str]:
        long_term = set(self._store.list_by_horizon("LONG_TERM"))
        intraday = set(self._store.list_by_horizon("INTRADAY"))
        symbols = long_term - intraday
        if self._active_earnings_symbols_fn is not None:
            symbols -= self._active_earnings_symbols_fn()
        return symbols

    async def run(self) -> None:
        await self._reconcile()
        while not self._stop_event.is_set():
            try:
                await asyncio.wait_for(self._stop_event.wait(), timeout=self._watchlist_poll_interval)
            except asyncio.TimeoutError:
                pass  # normal case: poll interval elapsed, check for changes
            if self._stop_event.is_set():
                break
            await self._reconcile()
        await self._stop_current()

    async def _reconcile(self) -> None:
        new_symbols = self._long_term_only_symbols()
        if new_symbols == self._current_symbols:
            return

        logger.info(
            "LONG_TERM-only ticker set changed (now %s) -- restarting daily price poll",
            sorted(new_symbols) or "none",
        )
        await self._stop_current()
        self._current_symbols = new_symbols

        if not new_symbols:
            return

        self._poller = YFinancePoller(MarketDataConfig(yfinance_poll_interval_seconds=self._price_poll_interval))
        self._task = asyncio.create_task(
            self._poller.stream(sorted(new_symbols), self._on_event), name="long_term_price_poll"
        )

    async def _stop_current(self) -> None:
        if self._poller is not None:
            self._poller.stop()
        if self._task is not None:
            try:
                await self._task
            except Exception as exc:  # noqa: BLE001 -- a stream failure shouldn't kill the reconciler
                logger.warning("Previous long-term price poll ended with an error: %s", exc)
            self._task = None
        self._poller = None


class EarningsFastTrackPoller:
    """
    Event-Driven Earnings Radar, Requirement 6. Every poll_interval_seconds
    (default 15 min), fast-track-ingests 8-K/10-Q filings AND captures an
    extended-hours price quote for every ticker CURRENTLY inside its
    earnings window (upcoming_earnings) -- independent of periodic_
    ingestion_loop's/periodic_long_term_financials_loop's 6-hour cadence
    and LongTermPriceRunner's daily one. No existing reconcile-loop
    abstraction supports one ticker polling at a DIFFERENT cadence than
    the rest of a symbol set (every one of them diffs a whole set at ONE
    uniform interval), so this is a standalone poller, not a variant of
    WatchlistDrivenIngestion/WatchlistDrivenMarketData.

    Session-aware BEFORE_MARKET/AFTER_MARKET windowing is deliberately
    skipped -- yfinance's session data isn't reliable enough to window
    precisely against (see talonx_ingest.earnings's own docstring). The
    active window is simply [earnings_date 00:00 UTC, earnings_date + 1
    day 23:59:59 UTC], a flat 2-calendar-day span, same reasoning
    talonx_dispatch.consumer's T-48h heads-up check already applies to
    "is this ticker's earnings day still relevant."

    Heavyweight resources (DocumentChunker, VectorStore, IngestionLedger,
    RedisEventPublisher) are created ONCE in run(), not once per poll --
    VectorStore alone loads/downloads an embedding model on first use, so
    recreating it every 15 minutes would be wasteful. A fresh EdgarClient
    (aiohttp session) IS opened per poll cycle, matching run_ingestion's/
    run_long_term_financials_ingestion's own "new session per batch call"
    convention.
    """

    def __init__(
        self, watchlist_store: TickerWatchlistStore, on_event, poll_interval_seconds: float,
    ):
        self._store = watchlist_store
        self._on_event = on_event
        self._poll_interval = poll_interval_seconds
        self._stop_event = asyncio.Event()
        self._active_symbols: set[str] = set()
        self._chunker: DocumentChunker | None = None
        self._vector_store: VectorStore | None = None
        self._ledger: IngestionLedger | None = None
        self._publisher: RedisEventPublisher | None = None

    def stop(self) -> None:
        self._stop_event.set()

    def active_symbols(self) -> set[str]:
        """Read by LongTermPriceRunner (via active_earnings_symbols_fn)
        to avoid double-publishing price ticks for a ticker this poller
        currently owns."""
        return set(self._active_symbols)

    def _tickers_in_window(self) -> list[str]:
        now = datetime.now(timezone.utc)
        window_end = now + timedelta(days=1)
        result = []
        for row in self._store.list_upcoming_earnings():
            try:
                earnings_date = datetime.fromisoformat(row["earnings_date"]).replace(tzinfo=timezone.utc)
            except ValueError:
                continue
            earnings_day_end = earnings_date + timedelta(days=1)
            if now <= earnings_day_end and earnings_date <= window_end:
                result.append(row["ticker"])
        return result

    async def run(self) -> None:
        self._chunker = DocumentChunker()
        # Cached process-wide (talonx_ingest.storage.vector_store.get_vector_store) --
        # this uses the same default "sec_filings" collection run_ingestion()
        # does, so it shares that already-loaded embedding model instead of
        # holding a second full copy resident in memory for the life of the
        # process.
        self._vector_store = get_vector_store()
        self._ledger = IngestionLedger(settings.ledger.path)
        self._publisher = RedisEventPublisher()
        await self._publisher.connect()  # logs a warning and continues if Redis is unavailable

        try:
            while not self._stop_event.is_set():
                await self._poll_once()
                try:
                    await asyncio.wait_for(self._stop_event.wait(), timeout=self._poll_interval)
                except asyncio.TimeoutError:
                    pass  # normal case: interval elapsed, poll again
        finally:
            self._ledger.close()
            await self._publisher.close()

    async def _poll_once(self) -> None:
        tickers = self._tickers_in_window()
        self._active_symbols = set(t.upper() for t in tickers)
        if not tickers:
            return

        logger.info("Earnings fast-track poll for %s", tickers)
        async with EdgarClient() as edgar_client:
            for ticker in tickers:
                try:
                    found = await ingest_earnings_filing(
                        ticker, edgar_client, self._chunker, self._vector_store, self._ledger, self._publisher,
                    )
                except Exception as exc:  # noqa: BLE001 -- one bad ticker shouldn't kill the poll
                    logger.error("Earnings fast-track ingestion failed for %s: %s", ticker, exc)
                    found = False

                if found:
                    # A confirmed earnings-related filing landed (8-K
                    # Item 2.02 or a 10-Q) -- real XBRL facts may finally
                    # be available too, so trigger financials ingestion
                    # NOW rather than waiting for the next 6h cycle.
                    try:
                        await run_long_term_financials_ingestion([ticker], is_earnings_related=True)
                    except Exception as exc:  # noqa: BLE001
                        logger.error("Earnings-triggered financials ingestion failed for %s: %s", ticker, exc)

                try:
                    quote = await asyncio.to_thread(fetch_extended_hours_quote, ticker)
                except Exception as exc:  # noqa: BLE001 -- one bad ticker shouldn't kill the poll
                    logger.warning("Extended-hours quote fetch failed for %s: %s", ticker, exc)
                    quote = None
                if quote is not None:
                    await self._on_event(quote)


class PreMarketPoller:
    """
    Pre-Market Radar: extends extended-hours quote coverage (originally
    built only for EarningsFastTrackPoller's narrow earnings-window ticker
    set, Requirement 6 above) to the WHOLE active watchlist during the
    pre-market session. Regular hours already get live prices from
    WatchlistDrivenMarketData/LongTermPriceRunner via yfinance's
    `fast_info`, which does NOT reflect pre/post-market trading (see
    fetch_extended_hours_quote's own docstring) -- so without this, a
    pre-market move sits invisible until the regular session opens and
    the price gaps into view all at once.

    Ticks flow onto the SAME talonx:market:stream channel as every other
    price source, so they hit the exact same downstream signal/decision/
    notification pipeline and gates as a regular-session tick -- no
    separate, looser filtering for pre-market moves.

    Dynamic ET Timezone: the pre-market window is gated on
    talonx_ingest.session.is_premarket_window (04:00-09:30 ET via
    zoneinfo.ZoneInfo("America/New_York")), not a flat, hardcoded
    UTC-time-of-day range -- the previous implementation's window was
    sized to cover the UNION of both EDT and EST offsets specifically
    because it did no DST-awareness, which is a genuine mismatch (up to
    an hour) between "the flat UTC clock says pre-market" and "it's
    actually pre-market in New York" depending on the time of year, not
    just imprecision. See talonx_ingest.session's own docstring for the
    full rationale. Mon-Fri only -- still no trading-holiday calendar
    beyond that, same documented tradeoff talonx_quant.session accepts.

    Excludes any ticker currently owned by EarningsFastTrackPoller, same
    "avoid double-publishing ticks for one symbol" reasoning
    LongTermPriceRunner already applies to that poller -- it already
    handles extended-hours pricing for its own (narrower) ticker set at a
    cadence tied to the actual earnings event, so this poller staying out
    of its way avoids two independent sources racing ticks for one symbol
    with no ordering/session tiebreak.

    Vectorized Multi-Quote Poller: polls the FULL watchlist every tick via
    talonx_ingest.poller.fetch_watchlist_quotes, a single batched
    `yf.download(..., group_by="ticker")` call, rather than the previous
    per-symbol `fetch_extended_hours_quote` loop -- which had to rotate
    through only a small batch (5 symbols) per tick specifically to bound
    a curl_cffi memory leak in `yf.Ticker(...).history(prepost=True)`
    (the installed curl_cffi build, 0.16.0, has a broken `Curl.__del__`
    that leaks native memory Python's own GC can't see or reclaim; hitting
    the full watchlist that way was confirmed live to OOM the whole
    machine within ~15 minutes). One `yf.download` call per tick means one
    native-handle churn per cycle regardless of watchlist size, not one
    per symbol -- see fetch_watchlist_quotes' own docstring.
    """

    def __init__(
        self, watchlist_store: TickerWatchlistStore, on_event, poll_interval_seconds: float,
        active_earnings_symbols_fn=None, refresh_warn_seconds: float = DEFAULT_REFRESH_WARN_SECONDS,
    ):
        self._store = watchlist_store
        self._on_event = on_event
        self._poll_interval = poll_interval_seconds
        self._active_earnings_symbols_fn = active_earnings_symbols_fn
        self._refresh_warn_seconds = refresh_warn_seconds
        self._stop_event = asyncio.Event()

    def stop(self) -> None:
        self._stop_event.set()

    def _in_window(self) -> bool:
        return is_premarket_window()

    def _symbols(self) -> set[str]:
        symbols = set(self._store.list_active_symbols())
        if self._active_earnings_symbols_fn is not None:
            symbols -= self._active_earnings_symbols_fn()
        return symbols

    async def run(self) -> None:
        while not self._stop_event.is_set():
            if self._in_window():
                await self._poll_once()
            try:
                await asyncio.wait_for(self._stop_event.wait(), timeout=self._poll_interval)
            except asyncio.TimeoutError:
                pass  # normal case: interval elapsed -- poll again if still in window, or check again if not

    async def _poll_once(self) -> None:
        symbols = sorted(self._symbols())
        if not symbols:
            return
        logger.info("Pre-market vectorized poll for %d tracked symbol(s)", len(symbols))
        try:
            quotes = await asyncio.to_thread(fetch_watchlist_quotes, symbols, self._refresh_warn_seconds)
        except Exception as exc:  # noqa: BLE001 -- a bad cycle shouldn't kill the poller
            logger.warning("Pre-market vectorized quote fetch failed: %s", exc)
            return
        for quote in quotes:
            await self._on_event(quote)


class WatchlistDrivenIngestion:
    """
    Reacts to talonx_watchlist changes by triggering a ONE-OFF ingestion
    for just the ticker(s) that changed, immediately -- rather than
    waiting for periodic_ingestion_loop's/periodic_long_term_financials_loop's
    next --interval-hours cycle (default 6h, so a ticker added or
    re-tagged mid-session could otherwise sit with zero filing/financials
    data for hours). Same "poll short interval, diff against last-known
    state, react only to the diff" shape as WatchlistDrivenMarketData
    above, for the same underlying reason: talonx_watchlist is a live,
    dashboard-editable control surface, not a startup-only ticker list --
    ingestion should behave the same way market data streaming and
    paper-trading enablement already do.

    Two independent diffs, since they trigger different work:
      - a ticker newly ACTIVE (added, or resumed from paused) gets
        immediate filing-text + news ingestion -- this benefits ANY
        horizon, since talonx_brain's retrieval needs this context for
        both the intraday and long-term research chains.
      - a ticker newly eligible for LONG_TERM (added with that horizon,
        OR re-tagged from INTRADAY to LONG_TERM/DUAL_HORIZON) gets
        immediate structured-financials ingestion -- this is the gap a
        live smoke test caught: re-tagging a ticker LONG_TERM used to
        leave it with zero fundamental data until the next scheduled
        cycle, up to --interval-hours away.

    Seeds its "known" sets from the CURRENT watchlist state at startup
    (not empty) -- the initial batch is already covered by the periodic
    loops' own "run immediately on startup" behavior; this class only
    reacts to CHANGES made after that.

    A failure for a given ticker (e.g. a transient SEC API error) is
    logged and NOT retried by this class -- the ticker is still marked
    "known" after the attempt either way, so it won't be re-triggered
    reactively. The existing periodic --interval-hours cycle remains the
    eventual safety net/retry path for anything that fails here.
    """

    def __init__(self, watchlist_store: TickerWatchlistStore, poll_interval_seconds: float):
        self._store = watchlist_store
        self._poll_interval = poll_interval_seconds
        self._stop_event = asyncio.Event()
        self._known_active_symbols: set[str] = set()
        self._known_long_term_symbols: set[str] = set()

    def stop(self) -> None:
        self._stop_event.set()

    async def run(self) -> None:
        self._known_active_symbols = set(self._store.list_active_symbols())
        self._known_long_term_symbols = set(self._store.list_by_horizon("LONG_TERM"))

        while not self._stop_event.is_set():
            try:
                await asyncio.wait_for(self._stop_event.wait(), timeout=self._poll_interval)
            except asyncio.TimeoutError:
                pass  # normal case: poll interval elapsed, check for changes
            if self._stop_event.is_set():
                break
            await self._reconcile()

    async def _reconcile(self) -> None:
        current_active = set(self._store.list_active_symbols())
        current_long_term = set(self._store.list_by_horizon("LONG_TERM"))

        new_active = sorted(current_active - self._known_active_symbols)
        new_long_term = sorted(current_long_term - self._known_long_term_symbols)
        self._known_active_symbols = current_active
        self._known_long_term_symbols = current_long_term

        if new_active:
            logger.info(
                "New/resumed ticker(s) detected -- triggering immediate filing+news ingestion: %s",
                new_active,
            )
            try:
                results = await run_ingestion(new_active)
                logger.info("Reactive filing ingestion: %s", results)
            except Exception as exc:  # noqa: BLE001 -- one bad batch shouldn't kill the reconciler
                logger.error("Reactive filing ingestion failed: %s", exc)
            try:
                news_results = await run_news_ingestion(new_active)
                logger.info("Reactive news ingestion: %s", news_results)
            except Exception as exc:  # noqa: BLE001
                logger.error("Reactive news ingestion failed: %s", exc)

        if new_long_term:
            logger.info(
                "New LONG_TERM-eligible ticker(s) detected -- triggering immediate financials ingestion: %s",
                new_long_term,
            )
            try:
                results = await run_long_term_financials_ingestion(new_long_term)
                logger.info("Reactive long-term financials ingestion: %s", results)
            except Exception as exc:  # noqa: BLE001
                logger.error("Reactive long-term financials ingestion failed: %s", exc)


class WatchlistDrivenQuantPreseed:
    """
    Requirement 2 (Instant Historical Pre-Seeding): eagerly backfills
    both of QuantScanner's RollingBarBuffers via yfinance for every
    watchlist symbol -- once for the WHOLE watchlist at startup (so a
    fresh process doesn't sit through the ~24min/1-min-buffer and
    ~50-continuous-hour/HTF-buffer live warm-up documented in
    docs/bar_buffer_persistence.md), then reactively for just the
    symbol(s) newly added/resumed thereafter. Same poll-and-diff shape
    as WatchlistDrivenIngestion above, for the same reason: the
    watchlist is a live, dashboard-editable control surface, not a
    startup-only list.

    QuantScanner itself deliberately never imports talonx_watchlist (see
    its own module docstring's "self-contained at the code level"
    convention) -- this class is the one place that bridges the two,
    driving QuantScanner.preseed_symbols() from here instead.

    `already_preseeded_symbols` (Task 66B-PREP): main() now awaits
    talonx_quant.preseed_ordering.run_initial_preseed() for the startup
    watchlist BEFORE any task -- including this one -- is created, so live
    market data / quant_scanner.run() can never reach QuantScanner ahead of
    that hydration. Symbols already covered by that call are passed in here
    so run()'s own "initial preseed" step below doesn't repeat it -- it
    still runs for whatever's left (e.g. a ticker added to the watchlist
    during that earlier await) and its REACTIVE preseed loop for symbols
    added/resumed after startup is completely unchanged.
    """

    def __init__(
        self, watchlist_store: TickerWatchlistStore, quant_scanner: QuantScanner, poll_interval_seconds: float,
        already_preseeded_symbols: set[str] | None = None,
    ):
        self._store = watchlist_store
        self._scanner = quant_scanner
        self._poll_interval = poll_interval_seconds
        self._stop_event = asyncio.Event()
        self._known_active_symbols: set[str] = set()
        self._already_preseeded_symbols = set(already_preseeded_symbols or ())

    def stop(self) -> None:
        self._stop_event.set()

    async def run(self) -> None:
        initial = sorted(self._store.list_active_symbols())
        self._known_active_symbols = set(initial)
        pending_initial = [s for s in initial if s.upper() not in self._already_preseeded_symbols]
        if pending_initial:
            logger.info("Pre-seeding talonx_quant buffers for the current watchlist: %s", pending_initial)
            await self._scanner.preseed_symbols(pending_initial)

        while not self._stop_event.is_set():
            try:
                await asyncio.wait_for(self._stop_event.wait(), timeout=self._poll_interval)
            except asyncio.TimeoutError:
                pass  # normal case: poll interval elapsed, check for changes
            if self._stop_event.is_set():
                break

            current_active = set(self._store.list_active_symbols())
            new_active = sorted(current_active - self._known_active_symbols)
            self._known_active_symbols = current_active
            if new_active:
                logger.info(
                    "New/resumed ticker(s) detected -- pre-seeding talonx_quant buffers: %s", new_active,
                )
                await self._scanner.preseed_symbols(new_active)


async def periodic_ingestion_loop(
    watchlist_store: TickerWatchlistStore, interval_hours: float, stop_event: asyncio.Event
) -> None:
    """
    Runs SEC filing + news ingestion immediately, then again every
    `interval_hours`, until `stop_event` is set. A failure in one cycle
    is logged and the loop continues to the next scheduled run rather
    than dying -- same isolate-failures philosophy as the rest of the
    project (one bad cycle shouldn't take down a long-running process).

    The ticker list is re-read from the watchlist store fresh at the top
    of every cycle (not captured once at startup) -- an add/remove made
    via the dashboard takes effect on the NEXT scheduled cycle, same as
    any other periodic job; there's no reason to restart this loop
    mid-interval just because the list changed. Only ACTIVE tickers are
    ingested -- a paused ticker skips filing/news ingestion too, same as
    it skips market data streaming.
    """
    interval_seconds = interval_hours * 3600

    while not stop_event.is_set():
        tickers = watchlist_store.list_active_symbols()
        if not tickers:
            logger.warning("Ticker watchlist is empty -- skipping this ingestion cycle.")
            try:
                await asyncio.wait_for(stop_event.wait(), timeout=interval_seconds)
            except asyncio.TimeoutError:
                pass
            continue

        logger.info("=== Ingestion cycle starting (filings + news) for %s ===", tickers)
        try:
            filing_results = await run_ingestion(tickers)
            logger.info("Filing ingestion this cycle: %s", filing_results)
        except Exception as exc:  # noqa: BLE001 -- one bad cycle shouldn't kill the loop
            logger.error("Filing ingestion cycle failed: %s", exc)

        try:
            news_results = await run_news_ingestion(tickers)
            logger.info("News ingestion this cycle: %s", news_results)
        except Exception as exc:  # noqa: BLE001
            logger.error("News ingestion cycle failed: %s", exc)

        logger.info(
            "=== Ingestion cycle complete. Next cycle in %.1f hours ===",
            interval_hours,
        )
        try:
            await asyncio.wait_for(stop_event.wait(), timeout=interval_seconds)
        except asyncio.TimeoutError:
            pass  # normal case: interval elapsed, loop again


async def periodic_long_term_financials_loop(
    watchlist_store: TickerWatchlistStore, interval_hours: float, stop_event: asyncio.Event
) -> None:
    """
    Phase 2's sibling to periodic_ingestion_loop above -- SEC XBRL
    structured financials instead of filing text, for every ticker
    tagged LONG_TERM or DUAL_HORIZON (list_by_horizon already includes
    DUAL_HORIZON in a "LONG_TERM" query -- see talonx_watchlist/store.py).
    Runs on the SAME interval_hours as the text-ingestion loop for
    simplicity (one --interval-hours flag, not two) -- financials update
    far less often than that in reality (annual 10-Ks), but
    ingest_long_term_financials()'s own ledger check already makes a
    same-fiscal-year re-run a fast no-op, so a shorter-than-necessary
    interval costs a bit of wasted polling, not correctness.
    """
    interval_seconds = interval_hours * 3600

    while not stop_event.is_set():
        tickers = watchlist_store.list_by_horizon("LONG_TERM")
        if not tickers:
            try:
                await asyncio.wait_for(stop_event.wait(), timeout=interval_seconds)
            except asyncio.TimeoutError:
                pass
            continue

        logger.info("=== Long-term financials ingestion cycle starting for %s ===", tickers)
        try:
            results = await run_long_term_financials_ingestion(tickers)
            logger.info("Long-term financials ingestion this cycle: %s", results)
        except Exception as exc:  # noqa: BLE001 -- one bad cycle shouldn't kill the loop
            logger.error("Long-term financials ingestion cycle failed: %s", exc)

        try:
            await asyncio.wait_for(stop_event.wait(), timeout=interval_seconds)
        except asyncio.TimeoutError:
            pass  # normal case: interval elapsed, loop again


async def reconcile_missing_long_term_factors(
    watchlist_store: TickerWatchlistStore, quant_store: QuantStateStore, stop_event: asyncio.Event,
    fundamental_scanner: FundamentalScanner | None = None, head_start_seconds: float = 15.0,
) -> None:
    """
    One-shot startup reconciliation for a confirmed-live gap: `NewFundamentalsIngestedEvent`
    is a single Redis Pub/Sub publish with no replay/ack/retry, so if
    `FundamentalScanner` (talonx_quant) wasn't subscribed yet at the
    exact moment `periodic_long_term_financials_loop`'s first cycle
    published it -- a real race, since both start concurrently in this
    process's task list -- the event is gone. Worse, `ingest_long_term_financials`'s
    OWN ledger then marks that fiscal year "already ingested," so every
    NORMAL future cycle correctly (and silently) skips re-fetching it --
    permanently starving that ticker's long-term pipeline until its next
    annual 10-K, months away. Confirmed live: 18 of 30 ever-ingested
    tickers lost their event this way across repeated restarts.

    Fix: after giving the rest of this process's startup tasks (in
    particular FundamentalScanner's own Redis connect+subscribe) a head
    start, compare quant_store.get_latest_factors() -- populated ONLY by
    FundamentalScanner actually receiving and computing from the event,
    never by the ledger -- against every LONG_TERM/DUAL_HORIZON
    watchlist ticker. Anything missing gets one `force=True` re-publish,
    which bypasses ingest_long_term_financials's ledger skip and
    re-fetches from EDGAR (the ledger never stored the actual facts,
    only a fiscal-year watermark, so there's nothing cheaper to reuse).

    Self-healing even if THIS attempt also loses the race (FundamentalScanner
    still starting up, a transient EDGAR error): a ticker this pass fails
    to fix is still missing from quant_store afterward, so the NEXT
    restart's reconciliation pass retries it too -- no separate state of
    its own to track "did this already run."

    `fundamental_scanner`, if given, also gets each missing ticker's
    `fundamental_cooldown:{TICKER}` Redis key cleared before the forced
    republish -- found live: a ticker whose quant.db row was lost
    SEPARATELY from its original successful run (that run's cooldown TTL
    keeps ticking down independently in Redis, unaffected by whatever
    wiped the SQLite row) would otherwise have this reconciliation's
    forced republish immediately re-suppressed by that stale cooldown,
    right back to square one. Safe to clear unconditionally here since
    this method is only ever called for a ticker already confirmed to
    have NO computed factors at all -- never a general-purpose bypass.
    """
    try:
        await asyncio.wait_for(stop_event.wait(), timeout=head_start_seconds)
        return  # stop() fired during the head-start delay -- shutting down already
    except asyncio.TimeoutError:
        pass  # normal case: head start elapsed, proceed

    tickers = watchlist_store.list_by_horizon("LONG_TERM")
    missing = [t for t in tickers if quant_store.get_latest_factors(t) is None]
    if not missing:
        logger.info("Long-term factors reconciliation: every tracked ticker already has computed factors.")
        return

    logger.info(
        "Long-term factors reconciliation: %d ticker(s) missing computed factors "
        "(lost NewFundamentalsIngestedEvent or never ingested) -- %s", len(missing), missing,
    )
    if fundamental_scanner is not None:
        for ticker in missing:
            await fundamental_scanner.clear_cooldown(ticker)
    try:
        results = await run_long_term_financials_ingestion(missing, force=True)
        logger.info("Long-term factors reconciliation complete: %s", results)
    except Exception as exc:  # noqa: BLE001 -- best-effort; retried on the next restart regardless
        logger.error("Long-term factors reconciliation failed: %s", exc)


async def periodic_wal_checkpoint_loop(
    checkpointable_stores: list, interval_seconds: float, stop_event: asyncio.Event,
) -> None:
    """
    Forces a WAL checkpoint (PRAGMA wal_checkpoint(TRUNCATE)) on every
    WAL-mode SQLite store this process owns, on a fixed interval. Exists
    because SQLite's own automatic "PASSIVE" checkpoint silently skips
    itself whenever another connection has a read transaction open at
    that moment -- and talonx_dispatch/app.py's Streamlit dashboard (a
    SEPARATE process, polling every TALONX_DISPATCH_AUTOREFRESH_MS) is
    exactly that kind of frequent reader. Left unchecked, the WAL file
    grows unbounded for as long as this process runs -- and every read
    against a large uncheckpointed WAL gets progressively SLOWER (SQLite
    has to reconstruct current page state by scanning the whole WAL),
    which is what actually made the dashboard feel like it was "hanging"
    over a live session, not query complexity or data volume (row counts
    stay tiny; this is write CHURN to the same handful of rows -- see
    talonx_paper.store.PaperTradingStore.checkpoint's own docstring, the
    highest-write-volume store and the one this was first diagnosed
    against, since it commits on every single market tick).

    Runs immediately at startup (so a long-uncheckpointed WAL left over
    from a PREVIOUS session gets cleaned up right away, not just
    eventually) then every interval_seconds thereafter. Always runs,
    independent of any --skip-* flag -- pure maintenance, no functional
    effect on the pipeline, cheap even when there's nothing to do.

    Each store.checkpoint() runs INLINE on the event loop, not via
    asyncio.to_thread -- tried that once (2026-08-13) and it broke
    AuditStore immediately: its connection deliberately keeps
    check_same_thread's True default (see talonx_dispatch/store.py's own
    docstring, which names asyncio.to_thread specifically as the thing
    NOT to do), because it's built for exactly this -- one connection,
    one thread, for its whole life. Handing that connection to
    to_thread's threadpool raised "SQLite objects created in a thread
    can only be used in that same thread" on every single checkpoint
    attempt. PaperTradingStore/TickerWatchlistStore pass
    check_same_thread=False so they wouldn't raise, but per that same
    docstring that only disables the assertion -- it doesn't make a
    connection safe for genuinely concurrent cross-thread access, so
    to_thread would have been a latent hazard for those two even without
    an error to show for it. Net effect: TRUNCATE-mode checkpoints DO
    block (busy-retry up to sqlite3.connect's default 5s timeout) until
    every other connection's read transaction clears, so this can stall
    the rest of this process for up to ~5s per store, per interval, if
    the dashboard happens to be mid-read right then -- accepted as the
    lesser risk given the alternative is a cross-thread SQLite violation.
    """
    while not stop_event.is_set():
        for store in checkpointable_stores:
            try:
                store.checkpoint()
            except Exception as exc:  # noqa: BLE001 -- one bad checkpoint shouldn't kill the loop
                logger.warning("WAL checkpoint failed for %s: %s", type(store).__name__, exc)
        try:
            await asyncio.wait_for(stop_event.wait(), timeout=interval_seconds)
        except asyncio.TimeoutError:
            pass  # normal case: interval elapsed, checkpoint again


async def periodic_earnings_calendar_sync_loop(
    watchlist_store: TickerWatchlistStore, interval_hours: float, stop_event: asyncio.Event
) -> None:
    """
    Event-Driven Earnings Radar, Requirement 4: syncs each LONG_TERM/
    DUAL_HORIZON ticker's next known earnings date from yfinance into
    watchlist_store's upcoming_earnings table. Same interval-since-start
    shape as periodic_ingestion_loop/periodic_long_term_financials_loop
    above -- NOT anchored to actual Sunday-00:00-UTC wall-clock time (this
    codebase has no wall-clock/day-of-week scheduling precedent anywhere;
    the retention sweep is "every 24h from process start," not "at
    midnight"), so "weekly" here means every interval_hours (default 168
    = 7 days) from when this loop starts, which is close enough for a
    calendar that itself only resolves to day-granularity.

    A per-ticker fetch failure (see talonx_ingest.earnings's own
    fail-soft posture) or a ticker with no available earnings date is
    skipped, not fatal to the cycle.
    """
    interval_seconds = interval_hours * 3600

    while not stop_event.is_set():
        tickers = watchlist_store.list_by_horizon("LONG_TERM")
        if not tickers:
            try:
                await asyncio.wait_for(stop_event.wait(), timeout=interval_seconds)
            except asyncio.TimeoutError:
                pass
            continue

        logger.info("=== Earnings calendar sync starting for %s ===", tickers)
        synced = 0
        for ticker in tickers:
            try:
                entry = await asyncio.to_thread(fetch_earnings_calendar, ticker)
            except Exception as exc:  # noqa: BLE001 -- one bad ticker shouldn't kill the cycle
                logger.warning("Earnings calendar fetch failed for %s: %s", ticker, exc)
                continue
            if entry is None:
                continue
            watchlist_store.upsert_upcoming_earnings(
                entry.ticker, entry.earnings_date.isoformat(), entry.session, entry.reporting_period,
            )
            synced += 1
        logger.info(
            "=== Earnings calendar sync complete: %d/%d ticker(s) updated. Next cycle in %.1f hours ===",
            synced, len(tickers), interval_hours,
        )

        try:
            await asyncio.wait_for(stop_event.wait(), timeout=interval_seconds)
        except asyncio.TimeoutError:
            pass  # normal case: interval elapsed, loop again


async def main() -> None:
    args = _parse_args()

    # Task 82: one Original runtime is allowed to coexist with one PIV
    # process only when the latter advertises the isolation profile that
    # its own preflight has already validated. Duplicate Original runtimes
    # and unmarked/uncertain PIV peers fail before any store is opened.
    from talonx_core import process_guard
    process_ok, process_detail = process_guard.no_competing_talonx_process(
        current_role=process_guard.ORIGINAL_ROLE,
    )
    if not process_ok:
        raise RuntimeError(f"Original startup blocked by runtime process policy: {process_detail}")

    watchlist_config = WatchlistConfig()
    watchlist_store = TickerWatchlistStore(watchlist_config.db_path)
    if args.tickers:
        # Only takes effect on a genuinely fresh (empty) store -- once the
        # watchlist has any rows, the dashboard is the source of truth and
        # these positional args are ignored.
        if not watchlist_store.list_tickers():
            for symbol in args.tickers:
                watchlist_store.add_ticker(symbol, symbol)
            logger.info("Seeded watchlist from command line: %s", args.tickers)
        else:
            logger.info(
                "Ignoring command-line tickers %s -- watchlist already has "
                "tracked tickers; manage it via the dashboard instead.",
                args.tickers,
            )
    seeded = watchlist_store.ensure_seeded(
        watchlist_config.default_symbol, watchlist_config.default_name, watchlist_config.default_exchange,
    )
    if seeded:
        logger.info(
            "Watchlist was empty -- seeded default ticker %s (%s).",
            watchlist_config.default_symbol, watchlist_config.default_name,
        )
    logger.info("Tracked tickers: %s", watchlist_store.list_symbols())

    stop_event = asyncio.Event()
    quant_scanner: QuantScanner | None = None
    fundamental_scanner: FundamentalScanner | None = None
    quant_store: QuantStateStore | None = None
    if not args.skip_quant:
        quant_config = QuantConfig()
        if quant_config.enable_persistence:
            try:
                quant_store = QuantStateStore(quant_config.db_path)
            except Exception as exc:  # noqa: BLE001 -- persistence is a nice-to-have, not required
                logger.warning(
                    "Module 2 (talonx_quant) suppression-count persistence disabled "
                    "for this run: %s. Continuing without it.", exc,
                )
        quant_scanner = QuantScanner(config=quant_config, store=quant_store)
        # Sibling to quant_scanner, not a second loop inside it (different
        # cooldown/throttle semantics -- see fundamental_consumer.py's own
        # docstring) -- shares the SAME quant_store/config the technical
        # scanner uses.
        fundamental_scanner = FundamentalScanner(config=quant_config, store=quant_store)

    # Task 66B-PREP: deterministic startup ordering -- awaited HERE, before
    # any asyncio task exists, so it fully completes (or fails per-symbol)
    # before market data streaming / quant_scanner.run() can start. See
    # talonx_quant/preseed_ordering.py's own docstring for the race this
    # closes. Zero-ready is reported, never fatal here -- QuantScanner's
    # existing live-accumulation fallback still applies unchanged; this is
    # ordering only, not a new requirement on strategy readiness.
    initial_preseed_report = None
    if quant_scanner is not None:
        initial_watchlist_symbols = sorted(watchlist_store.list_active_symbols())
        if initial_watchlist_symbols:
            logger.info(
                "Running initial Quant preseed for %s before starting live market data / "
                "quant_scanner.run() ...", initial_watchlist_symbols,
            )
            initial_preseed_report = await run_initial_preseed(quant_scanner, initial_watchlist_symbols)
            logger.info(
                "Initial Quant preseed complete: %d/%d symbol(s) ready%s",
                len(initial_preseed_report.ready_symbols), len(initial_watchlist_symbols),
                " -- ZERO READY" if initial_preseed_report.is_blocked else "",
            )
        else:
            logger.info("Watchlist is empty at startup -- skipping initial Quant preseed (nothing to seed).")

    market_publisher = RedisEventPublisher()

    research_agent: ResearchAgent | None = None
    brain_store: BrainStatsStore | None = None
    if not args.skip_brain:
        try:
            brain_config = BrainConfig()
            if brain_config.enable_persistence:
                try:
                    brain_store = BrainStatsStore(brain_config.db_path)
                except Exception as exc:  # noqa: BLE001 -- persistence is a nice-to-have, not required
                    logger.warning(
                        "Module 3 (talonx_brain) report-category persistence disabled "
                        "for this run: %s. Continuing without it.", exc,
                    )
            research_agent = ResearchAgent(config=brain_config, store=brain_store)
            logger.info("Module 3 (talonx_brain) LLM provider: %s", research_agent.llm_chain.describe())
        except (ImportError, ValueError) as exc:
            logger.warning(
                "Module 3 (talonx_brain) disabled for this run: %s. Install "
                "talonx_brain\\requirements.txt, and either set GEMINI_API_KEY "
                "in .env at the repo root (TALONX_BRAIN_LLM_PROVIDER=gemini, the "
                "default) or set TALONX_BRAIN_LLM_PROVIDER=ollama and run "
                "`ollama serve` locally. Modules 1+2 will run normally without it.",
                exc,
            )

    decision_engine: DecisionEngine | None = None
    core_store: TickerStateStore | None = None
    if not args.skip_core:
        # Task 87B FC_01: wire the durable decision-bearing alert outbox to a
        # real on-disk path for the live runtime (a bare CoreConfig() in a
        # unit test stays in-memory). An explicit env var still wins.
        core_config = CoreConfig(
            alert_outbox_path=os.environ.get(
                "TALONX_CORE_ALERT_OUTBOX_PATH", DEFAULT_ALERT_OUTBOX_PATH
            )
        )
        if core_config.enable_persistence:
            try:
                core_store = TickerStateStore(core_config.state_db_path)
            except Exception as exc:  # noqa: BLE001 -- persistence is a nice-to-have, not required
                logger.warning(
                    "Module 4 (talonx_core) state persistence disabled for this run: "
                    "%s. Continuing with in-memory-only state.", exc,
                )
        decision_engine = DecisionEngine(config=core_config, store=core_store)

    dispatch_agent: DispatchAgent | None = None
    if not args.skip_dispatch:
        try:
            # Shares the SAME watchlist_store instance already created
            # above (not a second TickerWatchlistStore against the same
            # file) -- same one-connection-per-process convention
            # paper_trading_engine's construction already follows.
            dispatch_agent = DispatchAgent(watchlist_store=watchlist_store)
        except Exception as exc:  # noqa: BLE001 -- audit DB init failure shouldn't crash the whole run
            logger.warning(
                "Module 5 (talonx_dispatch) disabled for this run: %s. Modules 1-4 "
                "will run normally without it.",
                exc,
            )

    paper_trading_engine: PaperTradingEngine | None = None
    long_term_paper_engine: LongTermPaperEngine | None = None
    paper_store: PaperTradingStore | None = None
    if not args.skip_paper_trading or not args.skip_long_term_paper:
        try:
            # ONE PaperTradingStore instance/connection, shared by BOTH
            # engines below (same SQLite file, different tables -- see
            # store.py) -- not two separate connections to the same file.
            paper_config = PaperConfig()
            paper_store = PaperTradingStore(
                paper_config.db_path, paper_config.default_initial_balance,
                paper_config.default_trade_allocation_usd, paper_config.default_long_term_initial_balance,
                paper_config.dca_contribution_usd,
            )
        except Exception as exc:  # noqa: BLE001 -- ledger init failure shouldn't crash the whole run
            logger.warning(
                "Module 6 (talonx_paper) disabled for this run: %s. Modules 1-5 "
                "will run normally without it.",
                exc,
            )

    if paper_store is not None and not args.skip_paper_trading:
        # Shares the SAME watchlist_store instance/connection already
        # created above (not a second TickerWatchlistStore against the
        # same file) -- one connection per process, matching the
        # convention already used for market_data_runner/periodic_ingestion_loop.
        paper_trading_engine = PaperTradingEngine(store=paper_store, watchlist_store=watchlist_store)
    if paper_store is not None and not args.skip_long_term_paper:
        long_term_paper_engine = LongTermPaperEngine(store=paper_store, watchlist_store=watchlist_store)

    # Every WAL-mode store this process owns -- see
    # periodic_wal_checkpoint_loop's own docstring for why this needs to
    # be forced periodically rather than left to SQLite's own automatic
    # (but easily-starved) checkpoint.
    checkpointable_stores = [watchlist_store]
    if dispatch_agent is not None:
        checkpointable_stores.append(dispatch_agent.store)
    if paper_store is not None:
        checkpointable_stores.append(paper_store)

    earnings_fast_track_poller: EarningsFastTrackPoller | None = None
    if not args.skip_earnings_fast_track:
        earnings_fast_track_poller = EarningsFastTrackPoller(
            watchlist_store, make_on_event(market_publisher),
            _env_float("TALONX_EARNINGS_FAST_TRACK_POLL_SECONDS", 900.0),
        )

    premarket_poller: PreMarketPoller | None = None
    if not args.skip_premarket:
        premarket_poller = PreMarketPoller(
            watchlist_store, make_on_event(market_publisher),
            _env_float("TALONX_PREMARKET_POLL_INTERVAL_SECONDS", 300.0),
            active_earnings_symbols_fn=(
                earnings_fast_track_poller.active_symbols if earnings_fast_track_poller is not None else None
            ),
            refresh_warn_seconds=settings.market_data.premarket_refresh_warn_seconds,
        )

    market_data_runner: WatchlistDrivenMarketData | None = None
    long_term_price_runner: LongTermPriceRunner | None = None
    if not args.skip_market_data:
        # Task 66B-PREP explicitness (Part 5): which provider WILL be used
        # is knowable statically from config, before MarketDataManager
        # constructs anything -- log it plainly rather than only inside
        # MarketDataManager.stream()'s own log line, so it's visible even
        # to someone scanning startup logs for "did this use Polygon or
        # yfinance today" without reading module internals.
        logger.info("Market data provider (configured): %s", configured_market_data_provider())
        long_term_price_runner = LongTermPriceRunner(
            watchlist_store, make_on_event(market_publisher), watchlist_config.poll_interval_seconds,
            _env_float("TALONX_LT_PRICE_POLL_INTERVAL", 86400.0),
            active_earnings_symbols_fn=(
                earnings_fast_track_poller.active_symbols if earnings_fast_track_poller is not None else None
            ),
        )
        market_data_runner = WatchlistDrivenMarketData(
            watchlist_store, make_on_event(market_publisher), watchlist_config.poll_interval_seconds,
            metrics_publisher=market_publisher,
        )

    reactive_ingestion: WatchlistDrivenIngestion | None = None
    if not args.skip_ingestion:
        reactive_ingestion = WatchlistDrivenIngestion(watchlist_store, watchlist_config.poll_interval_seconds)

    quant_preseed: WatchlistDrivenQuantPreseed | None = None
    if quant_scanner is not None:
        quant_preseed = WatchlistDrivenQuantPreseed(
            watchlist_store, quant_scanner, watchlist_config.poll_interval_seconds,
            already_preseeded_symbols=(
                set(initial_preseed_report.requested_symbols) if initial_preseed_report is not None else None
            ),
        )

    # Gated on quant_store specifically (not just not args.skip_quant) --
    # without persistence enabled there's no get_latest_factors() to
    # reconcile against, and without a FundamentalScanner running at all
    # (--skip-quant) there's no subscriber to receive a re-publish anyway.
    run_long_term_factors_reconciliation = quant_store is not None and not args.skip_ingestion

    def _handle_sigint() -> None:
        logger.info("Shutdown requested (Ctrl+C) -- stopping all components...")
        stop_event.set()
        if market_data_runner is not None:
            market_data_runner.stop()
        if long_term_price_runner is not None:
            long_term_price_runner.stop()
        if earnings_fast_track_poller is not None:
            earnings_fast_track_poller.stop()
        if premarket_poller is not None:
            premarket_poller.stop()
        if quant_scanner is not None:
            quant_scanner.stop()
        if fundamental_scanner is not None:
            fundamental_scanner.stop()
        if research_agent is not None:
            research_agent.stop()
        if decision_engine is not None:
            decision_engine.stop()
        if dispatch_agent is not None:
            dispatch_agent.stop()
        if paper_trading_engine is not None:
            paper_trading_engine.stop()
        if long_term_paper_engine is not None:
            long_term_paper_engine.stop()
        if reactive_ingestion is not None:
            reactive_ingestion.stop()
        if quant_preseed is not None:
            quant_preseed.stop()

    loop = asyncio.get_running_loop()
    try:
        loop.add_signal_handler(signal.SIGINT, _handle_sigint)
    except NotImplementedError:
        pass  # Windows asyncio loop may not support this; Ctrl+C still raises KeyboardInterrupt

    if market_data_runner is not None:
        await market_publisher.connect()  # logs a warning and continues if Redis unavailable

    logger.info(
        "Starting TalonX (interval=%.1fh, ingestion=%s, market_data=%s, "
        "quant=%s, brain=%s, core=%s, dispatch=%s, paper_trading=%s, long_term_paper=%s)",
        args.interval_hours, "disabled" if args.skip_ingestion else "enabled",
        "enabled" if market_data_runner is not None else "disabled",
        "enabled" if quant_scanner is not None else "disabled",
        "enabled" if research_agent is not None else "disabled",
        "enabled" if decision_engine is not None else "disabled",
        "enabled" if dispatch_agent is not None else "disabled",
        "enabled" if paper_trading_engine is not None else "disabled",
        "enabled" if long_term_paper_engine is not None else "disabled",
    )
    if paper_trading_engine is not None or long_term_paper_engine is not None:
        # Task 66B-PREP explicitness (Part 6): this is talonx_paper's own
        # local simulated ledger (SQLite), never Alpaca -- unlike talonx_piv,
        # which submits real (paper-mode) orders to Alpaca's broker
        # endpoint. Stated explicitly here so a log/EOD reader never
        # conflates the two execution paths.
        logger.info("Paper execution path: %s", paper_execution_path_label())

    # Task 66B-PREP (Parts 5/6/10): best-effort, additive, never fatal --
    # gives generate_eod_report.py something concrete to attribute a report
    # to (which provider/execution path/commit actually ran this session),
    # and distinguishes a normal run_talonx.py run from a talonx_piv one.
    try:
        write_runtime_metadata(
            run_mode="FULL_APP",
            market_data_provider_configured=configured_market_data_provider() if market_data_runner is not None else "DISABLED",
            paper_execution_path=paper_execution_path_label(),
            quant_enabled=quant_scanner is not None,
            brain_enabled=research_agent is not None,
            core_enabled=decision_engine is not None,
            dispatch_enabled=dispatch_agent is not None,
            paper_trading_enabled=paper_trading_engine is not None,
        )
    except Exception as exc:  # noqa: BLE001 -- pure observability, never blocks startup
        logger.warning("Failed to write runtime metadata (non-fatal): %s", exc)

    tasks = []
    if market_data_runner is not None:
        tasks.append(asyncio.create_task(market_data_runner.run(), name="market_data"))
    if long_term_price_runner is not None:
        tasks.append(asyncio.create_task(long_term_price_runner.run(), name="long_term_price_poll"))
    if earnings_fast_track_poller is not None:
        tasks.append(asyncio.create_task(earnings_fast_track_poller.run(), name="earnings_fast_track"))
    if premarket_poller is not None:
        tasks.append(asyncio.create_task(premarket_poller.run(), name="premarket_poller"))
    if quant_scanner is not None:
        tasks.append(asyncio.create_task(quant_scanner.run(), name="quant_scanner"))
    if fundamental_scanner is not None:
        tasks.append(asyncio.create_task(fundamental_scanner.run(), name="fundamental_scanner"))
    if research_agent is not None:
        tasks.append(asyncio.create_task(research_agent.run(), name="research_agent"))
    if decision_engine is not None:
        tasks.append(asyncio.create_task(decision_engine.run(), name="decision_engine"))
    if dispatch_agent is not None:
        tasks.append(asyncio.create_task(dispatch_agent.run(), name="dispatch_agent"))
    if paper_trading_engine is not None:
        tasks.append(asyncio.create_task(paper_trading_engine.run(), name="paper_trading_engine"))
    if long_term_paper_engine is not None:
        tasks.append(asyncio.create_task(long_term_paper_engine.run(), name="long_term_paper_engine"))
    if not args.skip_ingestion:
        tasks.append(
            asyncio.create_task(
                periodic_ingestion_loop(watchlist_store, args.interval_hours, stop_event),
                name="periodic_ingestion",
            )
        )
        tasks.append(
            asyncio.create_task(
                periodic_long_term_financials_loop(watchlist_store, args.interval_hours, stop_event),
                name="periodic_long_term_financials",
            )
        )
    if not args.skip_earnings_sync:
        tasks.append(
            asyncio.create_task(
                periodic_earnings_calendar_sync_loop(
                    watchlist_store, _env_float("TALONX_INGEST_EARNINGS_SYNC_INTERVAL_HOURS", 168.0), stop_event,
                ),
                name="periodic_earnings_calendar_sync",
            )
        )
    if reactive_ingestion is not None:
        tasks.append(asyncio.create_task(reactive_ingestion.run(), name="reactive_ingestion"))
    if quant_preseed is not None:
        tasks.append(asyncio.create_task(quant_preseed.run(), name="quant_preseed"))
    if run_long_term_factors_reconciliation:
        tasks.append(
            asyncio.create_task(
                reconcile_missing_long_term_factors(
                    watchlist_store, quant_store, stop_event, fundamental_scanner,
                ),
                name="reconcile_long_term_factors",
            )
        )

    if not tasks:
        logger.error("Everything was skipped -- nothing to run. Drop at least one --skip-* flag.")
        await market_publisher.close()
        watchlist_store.close()
        return

    # Added only once we know there's real work happening -- otherwise
    # this trivial maintenance task alone would defeat the "nothing to
    # run" check above (it would always be non-empty, since
    # checkpointable_stores always has at least watchlist_store in it).
    tasks.append(
        asyncio.create_task(
            periodic_wal_checkpoint_loop(
                checkpointable_stores, _env_float("TALONX_WAL_CHECKPOINT_INTERVAL_SECONDS", 300.0), stop_event,
            ),
            name="periodic_wal_checkpoint",
        )
    )

    try:
        await asyncio.gather(*tasks)
    except KeyboardInterrupt:
        stop_event.set()
        if market_data_runner is not None:
            market_data_runner.stop()
        if long_term_price_runner is not None:
            long_term_price_runner.stop()
        if earnings_fast_track_poller is not None:
            earnings_fast_track_poller.stop()
        if premarket_poller is not None:
            premarket_poller.stop()
        if quant_scanner is not None:
            quant_scanner.stop()
        if fundamental_scanner is not None:
            fundamental_scanner.stop()
        if research_agent is not None:
            research_agent.stop()
        if decision_engine is not None:
            decision_engine.stop()
        if dispatch_agent is not None:
            dispatch_agent.stop()
        if paper_trading_engine is not None:
            paper_trading_engine.stop()
        if long_term_paper_engine is not None:
            long_term_paper_engine.stop()
        if reactive_ingestion is not None:
            reactive_ingestion.stop()
        if quant_preseed is not None:
            quant_preseed.stop()
    finally:
        await market_publisher.close()
        if quant_store is not None:
            quant_store.close()
        if brain_store is not None:
            brain_store.close()
        if core_store is not None:
            core_store.close()
        if dispatch_agent is not None:
            dispatch_agent.store.close()
        if paper_store is not None:
            paper_store.close()
        watchlist_store.close()
        logger.info("All components stopped.")


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run all of TalonX Module 1 + 2 + 3 + 4 + 5 + 6 together")
    parser.add_argument(
        "tickers", nargs="*", default=None,
        help="Ticker symbols to seed the watchlist with -- only takes effect if the "
             "watchlist is completely empty (fresh install). Once it has any tickers, "
             "manage it via the dashboard instead (streamlit run talonx_dispatch/app.py). "
             "A fresh install with no args here defaults to one ticker "
             "(TALONX_WATCHLIST_DEFAULT_SYMBOL, default MSFT).",
    )
    parser.add_argument(
        "--interval-hours", type=float, default=6.0,
        help="How often to re-run SEC filing + news ingestion (default: 6.0)",
    )
    parser.add_argument(
        "--skip-ingestion", action="store_true",
        help="Skip periodic filing/news ingestion; only run the continuous streams",
    )
    parser.add_argument(
        "--skip-market-data", action="store_true",
        help="Skip Module 1's live market data stream -- run it yourself with "
             "`python -m talonx_ingest.market_data.run` instead",
    )
    parser.add_argument(
        "--skip-quant", action="store_true",
        help="Skip Module 2 (talonx_quant) -- run it yourself with "
             "`python -m talonx_quant.run` instead",
    )
    parser.add_argument(
        "--skip-brain", action="store_true",
        help="Skip Module 3 (talonx_brain) even if its LLM provider is configured",
    )
    parser.add_argument(
        "--skip-core", action="store_true",
        help="Skip Module 4 (talonx_core)",
    )
    parser.add_argument(
        "--skip-dispatch", action="store_true",
        help="Skip Module 5 (talonx_dispatch) -- run it yourself with "
             "`python -m talonx_dispatch.run` instead",
    )
    parser.add_argument(
        "--skip-paper-trading", action="store_true",
        help="Skip Module 6 (talonx_paper) -- run it yourself with "
             "`python -m talonx_paper.run` instead",
    )
    parser.add_argument(
        "--skip-long-term-paper", action="store_true",
        help="Skip the Phase 2 long-term paper trading engine (DCA + rebalance) -- "
             "run it yourself with `python -m talonx_paper.run` instead",
    )
    parser.add_argument(
        "--skip-earnings-sync", action="store_true",
        help="Skip the Event-Driven Earnings Radar's weekly earnings-calendar sync "
             "(TALONX_INGEST_EARNINGS_SYNC_INTERVAL_HOURS, default every 168h)",
    )
    parser.add_argument(
        "--skip-earnings-fast-track", action="store_true",
        help="Skip the Event-Driven Earnings Radar's fast-track 8-K/10-Q ingestion + "
             "extended-hours price capture (TALONX_EARNINGS_FAST_TRACK_POLL_SECONDS, "
             "default every 900s) for tickers currently in their earnings window",
    )
    parser.add_argument(
        "--skip-premarket", action="store_true",
        help="Skip pre-market price monitoring for the whole watchlist "
             "(04:00-09:30 America/New_York, dynamically DST-aware -- see "
             "talonx_ingest.session -- poll every "
             "TALONX_PREMARKET_POLL_INTERVAL_SECONDS, default 300s, "
             "vectorized full-watchlist refresh warns past "
             "TALONX_PREMARKET_REFRESH_WARN_SECONDS, default 30s)",
    )
    return parser.parse_args()


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\nStopped.")
