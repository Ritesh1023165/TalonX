"""
talonx_paper.run
---------------------
Entrypoint. Runs BOTH paper trading engines concurrently until Ctrl+C:
  - PaperTradingEngine (intraday): talonx:alerts:dispatch + talonx:market:stream
    -> talonx:paper:trades
  - LongTermPaperEngine (Phase 2 LONG_TERM): talonx:alerts:longterm +
    talonx:market:stream -> talonx:paper:trades:longterm, plus its own
    recurring DCA contribution loop

They share ONE PaperTradingStore instance (same SQLite file, different
tables -- see store.py) and one TickerWatchlistStore instance, rather
than each opening a second connection to the same files.

Usage:
    python -m talonx_paper.run
"""
from __future__ import annotations

import asyncio
import logging
import signal

from talonx_paper.config import PaperConfig
from talonx_paper.consumer import LongTermPaperEngine, PaperTradingEngine
from talonx_paper.store import PaperTradingStore
from talonx_watchlist.config import WatchlistConfig
from talonx_watchlist.store import TickerWatchlistStore

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger("talonx_paper.run")


async def main() -> None:
    config = PaperConfig()
    store = PaperTradingStore(
        config.db_path, config.default_initial_balance, config.default_trade_allocation_usd,
        config.default_long_term_initial_balance, config.dca_contribution_usd,
    )
    watchlist_store = TickerWatchlistStore(WatchlistConfig().db_path)

    intraday_engine = PaperTradingEngine(config=config, store=store, watchlist_store=watchlist_store)
    long_term_engine = LongTermPaperEngine(config=config, store=store, watchlist_store=watchlist_store)

    loop = asyncio.get_running_loop()

    def _handle_sigint() -> None:
        logger.info("Shutdown requested (Ctrl+C) -- stopping both paper trading engines...")
        intraday_engine.stop()
        long_term_engine.stop()

    try:
        loop.add_signal_handler(signal.SIGINT, _handle_sigint)
    except NotImplementedError:
        pass  # Windows asyncio loop may not support this; Ctrl+C still raises KeyboardInterrupt

    logger.info(
        "Starting paper trading engines: intraday(%s + %s -> %s), long_term(%s + %s -> %s, DCA every %.0fd) "
        "(Ctrl+C to stop)",
        config.alerts_channel, config.market_channel, config.paper_trades_channel,
        config.alerts_channel_long_term, config.market_channel, config.paper_trades_channel_long_term,
        config.dca_interval_days,
    )
    try:
        await asyncio.gather(intraday_engine.run(), long_term_engine.run())
    except KeyboardInterrupt:
        intraday_engine.stop()
        long_term_engine.stop()
    finally:
        logger.info(
            "Stopped. Intraday: %d alerts, %d trades, %d ignored. Long-term: %d alerts, %d trades, "
            "%d ignored, %d DCA contributions.",
            intraday_engine.alerts_processed, intraday_engine.trades_executed, intraday_engine.trades_ignored,
            long_term_engine.alerts_processed, long_term_engine.trades_executed, long_term_engine.trades_ignored,
            long_term_engine.dca_contributions_made,
        )
        store.close()
        watchlist_store.close()


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\nStopped.")
