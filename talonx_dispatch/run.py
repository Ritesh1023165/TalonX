"""
talonx_dispatch.run
------------------------
Entrypoint. Runs continuously, listening to talonx:alerts:dispatch,
recording every alert to the audit trail, and sending Telegram push
notifications for alerts at or above TALONX_DISPATCH_MIN_SEVERITY, until
Ctrl+C.

This is ONLY the consumer half of Module 5 -- the Streamlit dashboard
(app.py) is a separate, always-standalone process (Streamlit's execution
model can't hold a persistent asyncio Redis subscription -- see its own
docstring), run with:
    streamlit run talonx_dispatch/app.py

Usage:
    python -m talonx_dispatch.run
"""
from __future__ import annotations

import asyncio
import logging
import signal

from talonx_dispatch.consumer import DispatchAgent

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger("talonx_dispatch.run")


async def main() -> None:
    agent = DispatchAgent()

    loop = asyncio.get_running_loop()

    def _handle_sigint() -> None:
        logger.info("Shutdown requested (Ctrl+C) -- stopping dispatch agent...")
        agent.stop()

    try:
        loop.add_signal_handler(signal.SIGINT, _handle_sigint)
    except NotImplementedError:
        pass  # Windows asyncio loop may not support this; Ctrl+C still raises KeyboardInterrupt

    logger.info(
        "Starting dispatch agent: %s -> audit trail (%s) + Telegram (%s) (Ctrl+C to stop)",
        agent.config.alerts_channel, agent.config.audit_db_path,
        "enabled" if agent.telegram_client.is_configured else "disabled",
    )
    try:
        await agent.run()
    except KeyboardInterrupt:
        agent.stop()
    finally:
        logger.info(
            "Stopped. Processed %d alerts, sent %d Telegram pushes (%d failed) this run.",
            agent.alerts_processed, agent.telegram_sent, agent.telegram_failed,
        )
        agent.store.close()
        agent.watchlist_store.close()


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\nStopped.")
