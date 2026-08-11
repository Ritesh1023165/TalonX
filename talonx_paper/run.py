"""
talonx_paper.run
---------------------
Entrypoint. Runs continuously, listening to talonx:alerts:dispatch (trade
decisions) and talonx:market:stream (live mark-to-market pricing), and
publishing PaperTradeExecutions to talonx:paper:trades until Ctrl+C.

Usage:
    python -m talonx_paper.run
"""
from __future__ import annotations

import asyncio
import logging
import signal

from talonx_paper.consumer import PaperTradingEngine

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger("talonx_paper.run")


async def main() -> None:
    engine = PaperTradingEngine()

    loop = asyncio.get_running_loop()

    def _handle_sigint() -> None:
        logger.info("Shutdown requested (Ctrl+C) -- stopping paper trading engine...")
        engine.stop()

    try:
        loop.add_signal_handler(signal.SIGINT, _handle_sigint)
    except NotImplementedError:
        pass  # Windows asyncio loop may not support this; Ctrl+C still raises KeyboardInterrupt

    logger.info(
        "Starting paper trading engine: %s + %s -> %s (Ctrl+C to stop)",
        engine.config.alerts_channel, engine.config.market_channel, engine.config.paper_trades_channel,
    )
    try:
        await engine.run()
    except KeyboardInterrupt:
        engine.stop()
    finally:
        logger.info(
            "Stopped. Processed %d alerts, executed %d trades, ignored %d this run.",
            engine.alerts_processed, engine.trades_executed, engine.trades_ignored,
        )
        engine.store.close()
        engine.watchlist_store.close()


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\nStopped.")
