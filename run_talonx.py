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
                            stopped.
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
with the new symbol set; periodic filing/news ingestion picks it up on its
next scheduled cycle. Positional ticker args below still work, but only as
a ONE-TIME seed for a genuinely empty store -- once the store has any
rows, they're ignored in favor of the dashboard.

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
import signal

from talonx_ingest.events.publisher import RedisEventPublisher
from talonx_ingest.market_data.manager import MarketDataManager
from talonx_ingest.market_data.run import make_on_event
from talonx_ingest.news.pipeline import run_news_ingestion
from talonx_ingest.pipeline import run_ingestion
from talonx_quant.config import QuantConfig
from talonx_quant.consumer import QuantScanner
from talonx_quant.store import QuantStateStore
from talonx_brain.config import BrainConfig
from talonx_brain.consumer import ResearchAgent
from talonx_brain.store import BrainStatsStore
from talonx_core.config import CoreConfig
from talonx_core.consumer import DecisionEngine
from talonx_core.store import TickerStateStore
from talonx_dispatch.consumer import DispatchAgent
from talonx_paper.consumer import PaperTradingEngine
from talonx_watchlist.config import WatchlistConfig
from talonx_watchlist.store import TickerWatchlistStore

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger("run_talonx")


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

    def __init__(self, watchlist_store: TickerWatchlistStore, on_event, poll_interval_seconds: float):
        self._store = watchlist_store
        self._on_event = on_event
        self._poll_interval = poll_interval_seconds
        self._stop_event = asyncio.Event()
        self._manager: MarketDataManager | None = None
        self._task: asyncio.Task | None = None
        self._current_symbols: set[str] = set()
        self._was_idle_empty = False

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
        self._manager = MarketDataManager()
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


async def main() -> None:
    args = _parse_args()

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
        core_config = CoreConfig()
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
    if not args.skip_paper_trading:
        try:
            # Shares the SAME watchlist_store instance/connection already
            # created above (not a second TickerWatchlistStore against the
            # same file) -- one connection per process, matching the
            # convention already used for market_data_runner/periodic_ingestion_loop.
            paper_trading_engine = PaperTradingEngine(watchlist_store=watchlist_store)
        except Exception as exc:  # noqa: BLE001 -- ledger init failure shouldn't crash the whole run
            logger.warning(
                "Module 6 (talonx_paper) disabled for this run: %s. Modules 1-5 "
                "will run normally without it.",
                exc,
            )

    market_data_runner: WatchlistDrivenMarketData | None = None
    if not args.skip_market_data:
        market_data_runner = WatchlistDrivenMarketData(
            watchlist_store, make_on_event(market_publisher), watchlist_config.poll_interval_seconds,
        )

    def _handle_sigint() -> None:
        logger.info("Shutdown requested (Ctrl+C) -- stopping all components...")
        stop_event.set()
        if market_data_runner is not None:
            market_data_runner.stop()
        if quant_scanner is not None:
            quant_scanner.stop()
        if research_agent is not None:
            research_agent.stop()
        if decision_engine is not None:
            decision_engine.stop()
        if dispatch_agent is not None:
            dispatch_agent.stop()
        if paper_trading_engine is not None:
            paper_trading_engine.stop()

    loop = asyncio.get_running_loop()
    try:
        loop.add_signal_handler(signal.SIGINT, _handle_sigint)
    except NotImplementedError:
        pass  # Windows asyncio loop may not support this; Ctrl+C still raises KeyboardInterrupt

    if market_data_runner is not None:
        await market_publisher.connect()  # logs a warning and continues if Redis unavailable

    logger.info(
        "Starting TalonX (interval=%.1fh, ingestion=%s, market_data=%s, "
        "quant=%s, brain=%s, core=%s, dispatch=%s, paper_trading=%s)",
        args.interval_hours, "disabled" if args.skip_ingestion else "enabled",
        "enabled" if market_data_runner is not None else "disabled",
        "enabled" if quant_scanner is not None else "disabled",
        "enabled" if research_agent is not None else "disabled",
        "enabled" if decision_engine is not None else "disabled",
        "enabled" if dispatch_agent is not None else "disabled",
        "enabled" if paper_trading_engine is not None else "disabled",
    )

    tasks = []
    if market_data_runner is not None:
        tasks.append(asyncio.create_task(market_data_runner.run(), name="market_data"))
    if quant_scanner is not None:
        tasks.append(asyncio.create_task(quant_scanner.run(), name="quant_scanner"))
    if research_agent is not None:
        tasks.append(asyncio.create_task(research_agent.run(), name="research_agent"))
    if decision_engine is not None:
        tasks.append(asyncio.create_task(decision_engine.run(), name="decision_engine"))
    if dispatch_agent is not None:
        tasks.append(asyncio.create_task(dispatch_agent.run(), name="dispatch_agent"))
    if paper_trading_engine is not None:
        tasks.append(asyncio.create_task(paper_trading_engine.run(), name="paper_trading_engine"))
    if not args.skip_ingestion:
        tasks.append(
            asyncio.create_task(
                periodic_ingestion_loop(watchlist_store, args.interval_hours, stop_event),
                name="periodic_ingestion",
            )
        )

    if not tasks:
        logger.error("Everything was skipped -- nothing to run. Drop at least one --skip-* flag.")
        await market_publisher.close()
        watchlist_store.close()
        return

    try:
        await asyncio.gather(*tasks)
    except KeyboardInterrupt:
        stop_event.set()
        if market_data_runner is not None:
            market_data_runner.stop()
        if quant_scanner is not None:
            quant_scanner.stop()
        if research_agent is not None:
            research_agent.stop()
        if decision_engine is not None:
            decision_engine.stop()
        if dispatch_agent is not None:
            dispatch_agent.stop()
        if paper_trading_engine is not None:
            paper_trading_engine.stop()
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
        if paper_trading_engine is not None:
            paper_trading_engine.store.close()
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
    return parser.parse_args()


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\nStopped.")