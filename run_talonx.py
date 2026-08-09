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
(market data, quant scanner, brain, core, dispatch) -- handy while
actively iterating on one piece: run the other four here and the one
you're working on in its own terminal (`python -m talonx_quant.run`, etc.)
without restarting this whole process every time you make a change.

NOT included here, and never will be: the Streamlit dashboard
(talonx_dispatch/app.py). Streamlit reruns its entire script top-to-bottom
on every interaction/autorefresh tick, which is fundamentally incompatible
with holding a persistent asyncio task open in this process -- see that
file's own docstring. It reads the same audit trail this file's dispatch
agent writes to, so run it ALONGSIDE this file, in its own terminal:
    streamlit run talonx_dispatch\\app.py

Replaces running `talonx_ingest.pipeline`, `talonx_ingest.news.pipeline`,
`talonx_ingest.market_data.run`, `talonx_quant.run`, `talonx_brain.run`,
`talonx_core.run`, and `talonx_dispatch.run` by hand in seven separate
terminals.

Usage:
    python run_talonx.py
    python run_talonx.py AAPL MSFT NVDA TSLA
    python run_talonx.py --interval-hours 12
    python run_talonx.py --skip-ingestion     # skip periodic filing/news ingestion
    python run_talonx.py --skip-market-data   # skip Module 1's live market stream
    python run_talonx.py --skip-quant         # skip Module 2 (talonx_quant)
    python run_talonx.py --skip-brain         # skip Module 3 (talonx_brain)
    python run_talonx.py --skip-core          # skip Module 4 (talonx_core)
    python run_talonx.py --skip-dispatch      # skip Module 5 (talonx_dispatch)

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
from talonx_quant.consumer import QuantScanner
from talonx_brain.consumer import ResearchAgent
from talonx_core.config import CoreConfig
from talonx_core.consumer import DecisionEngine
from talonx_core.store import TickerStateStore
from talonx_dispatch.consumer import DispatchAgent

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger("run_talonx")

DEFAULT_TICKERS = ["AAPL", "MSFT", "NVDA"]


async def periodic_ingestion_loop(
    tickers: list[str], interval_hours: float, stop_event: asyncio.Event
) -> None:
    """
    Runs SEC filing + news ingestion immediately, then again every
    `interval_hours`, until `stop_event` is set. A failure in one cycle
    is logged and the loop continues to the next scheduled run rather
    than dying -- same isolate-failures philosophy as the rest of the
    project (one bad cycle shouldn't take down a long-running process).
    """
    interval_seconds = interval_hours * 3600

    while not stop_event.is_set():
        logger.info("=== Ingestion cycle starting (filings + news) ===")
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
    tickers = args.tickers or DEFAULT_TICKERS

    stop_event = asyncio.Event()
    market_manager: MarketDataManager | None = None if args.skip_market_data else MarketDataManager()
    quant_scanner: QuantScanner | None = None if args.skip_quant else QuantScanner()
    market_publisher = RedisEventPublisher()

    research_agent: ResearchAgent | None = None
    if not args.skip_brain:
        try:
            research_agent = ResearchAgent()
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
            dispatch_agent = DispatchAgent()
        except Exception as exc:  # noqa: BLE001 -- audit DB init failure shouldn't crash the whole run
            logger.warning(
                "Module 5 (talonx_dispatch) disabled for this run: %s. Modules 1-4 "
                "will run normally without it.",
                exc,
            )

    def _handle_sigint() -> None:
        logger.info("Shutdown requested (Ctrl+C) -- stopping all components...")
        stop_event.set()
        if market_manager is not None:
            market_manager.stop()
        if quant_scanner is not None:
            quant_scanner.stop()
        if research_agent is not None:
            research_agent.stop()
        if decision_engine is not None:
            decision_engine.stop()
        if dispatch_agent is not None:
            dispatch_agent.stop()

    loop = asyncio.get_running_loop()
    try:
        loop.add_signal_handler(signal.SIGINT, _handle_sigint)
    except NotImplementedError:
        pass  # Windows asyncio loop may not support this; Ctrl+C still raises KeyboardInterrupt

    if market_manager is not None:
        await market_publisher.connect()  # logs a warning and continues if Redis unavailable

    logger.info(
        "Starting TalonX for tickers: %s (interval=%.1fh, ingestion=%s, market_data=%s, "
        "quant=%s, brain=%s, core=%s, dispatch=%s)",
        tickers, args.interval_hours, "disabled" if args.skip_ingestion else "enabled",
        "enabled" if market_manager is not None else "disabled",
        "enabled" if quant_scanner is not None else "disabled",
        "enabled" if research_agent is not None else "disabled",
        "enabled" if decision_engine is not None else "disabled",
        "enabled" if dispatch_agent is not None else "disabled",
    )

    tasks = []
    if market_manager is not None:
        tasks.append(
            asyncio.create_task(
                market_manager.stream(tickers, make_on_event(market_publisher)),
                name="market_data",
            )
        )
    if quant_scanner is not None:
        tasks.append(asyncio.create_task(quant_scanner.run(), name="quant_scanner"))
    if research_agent is not None:
        tasks.append(asyncio.create_task(research_agent.run(), name="research_agent"))
    if decision_engine is not None:
        tasks.append(asyncio.create_task(decision_engine.run(), name="decision_engine"))
    if dispatch_agent is not None:
        tasks.append(asyncio.create_task(dispatch_agent.run(), name="dispatch_agent"))
    if not args.skip_ingestion:
        tasks.append(
            asyncio.create_task(
                periodic_ingestion_loop(tickers, args.interval_hours, stop_event),
                name="periodic_ingestion",
            )
        )

    if not tasks:
        logger.error("Everything was skipped -- nothing to run. Drop at least one --skip-* flag.")
        await market_publisher.close()
        return

    try:
        await asyncio.gather(*tasks)
    except KeyboardInterrupt:
        stop_event.set()
        if market_manager is not None:
            market_manager.stop()
        if quant_scanner is not None:
            quant_scanner.stop()
        if research_agent is not None:
            research_agent.stop()
        if decision_engine is not None:
            decision_engine.stop()
        if dispatch_agent is not None:
            dispatch_agent.stop()
    finally:
        await market_publisher.close()
        if core_store is not None:
            core_store.close()
        if dispatch_agent is not None:
            dispatch_agent.store.close()
        logger.info("All components stopped.")


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run all of TalonX Module 1 + 2 + 3 + 4 + 5 together")
    parser.add_argument(
        "tickers", nargs="*", default=None,
        help=f"Ticker symbols to track (default: {' '.join(DEFAULT_TICKERS)})",
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
    return parser.parse_args()


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\nStopped.")