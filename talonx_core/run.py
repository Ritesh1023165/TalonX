"""
talonx_core.run
--------------------
Entrypoint. Runs continuously, listening to talonx:signals:quant and
talonx:reports:brain, and publishing correlated alerts to
talonx:alerts:dispatch until Ctrl+C.

Usage:
    python -m talonx_core.run
"""
from __future__ import annotations

import asyncio
import logging
import signal

from talonx_core.config import CoreConfig
from talonx_core.consumer import DecisionEngine
from talonx_core.store import TickerStateStore

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger("talonx_core.run")


async def main() -> None:
    config = CoreConfig()

    store: TickerStateStore | None = None
    if config.enable_persistence:
        try:
            store = TickerStateStore(config.state_db_path)
        except Exception as exc:  # noqa: BLE001 -- persistence is a nice-to-have, not required
            logger.warning(
                "State persistence disabled for this run: %s. Continuing with "
                "in-memory-only state (a restart will lose in-flight correlations).",
                exc,
            )

    engine = DecisionEngine(config=config, store=store)

    loop = asyncio.get_running_loop()

    def _handle_sigint() -> None:
        logger.info("Shutdown requested (Ctrl+C) -- stopping decision engine...")
        engine.stop()

    try:
        loop.add_signal_handler(signal.SIGINT, _handle_sigint)
    except NotImplementedError:
        pass  # Windows asyncio loop may not support this; Ctrl+C still raises KeyboardInterrupt

    logger.info(
        "Starting decision engine: %s + %s -> %s (persistence=%s, Ctrl+C to stop)",
        engine.config.signals_channel, engine.config.reports_channel, engine.config.alerts_channel,
        "enabled" if store is not None else "disabled",
    )
    try:
        await engine.run()
    except KeyboardInterrupt:
        engine.stop()
    finally:
        logger.info(
            "Stopped. Processed %d signals, %d reports, published %d alerts this run.",
            engine.signals_processed, engine.reports_processed, engine.alerts_published,
        )
        if store is not None:
            store.close()


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\nStopped.")
