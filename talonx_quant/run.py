"""
talonx_quant.run
--------------------
Entrypoint. Runs continuously, listening to talonx:market:stream and
publishing to talonx:signals:quant until Ctrl+C.

Usage:
    python -m talonx_quant.run
"""
from __future__ import annotations

import asyncio
import logging
import signal

from talonx_quant.config import QuantConfig
from talonx_quant.consumer import QuantScanner
from talonx_quant.store import QuantStateStore

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger("talonx_quant.run")


async def main() -> None:
    config = QuantConfig()

    store: QuantStateStore | None = None
    if config.enable_persistence:
        try:
            store = QuantStateStore(config.db_path)
        except Exception as exc:  # noqa: BLE001 -- persistence is a nice-to-have, not required
            logger.warning(
                "Suppression-count persistence disabled for this run: %s. "
                "Continuing without it (EOD reports won't see this process' "
                "cooldown/throttle counts).", exc,
            )

    scanner = QuantScanner(config=config, store=store)

    loop = asyncio.get_running_loop()

    def _handle_sigint() -> None:
        logger.info("Shutdown requested (Ctrl+C) -- stopping scanner...")
        scanner.stop()

    try:
        loop.add_signal_handler(signal.SIGINT, _handle_sigint)
    except NotImplementedError:
        pass  # Windows asyncio loop may not support this; Ctrl+C still raises KeyboardInterrupt

    logger.info(
        "Starting quant scanner: %s -> %s (Ctrl+C to stop)",
        scanner.config.market_stream_channel, scanner.config.signals_channel,
    )
    try:
        await scanner.run()
    except KeyboardInterrupt:
        scanner.stop()
    finally:
        logger.info(
            "Stopped. Processed %d bars, published %d signals this run.",
            scanner._bars_processed, scanner.signals_published,
        )
        if store is not None:
            store.close()


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\nStopped.")
