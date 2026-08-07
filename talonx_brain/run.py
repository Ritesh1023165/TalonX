"""
talonx_brain.run
---------------------
Entrypoint. Runs continuously, listening to talonx:signals:quant and
publishing research reports to talonx:reports:brain until Ctrl+C.

Usage:
    python -m talonx_brain.run
"""
from __future__ import annotations

import asyncio
import logging
import signal

from talonx_brain.consumer import ResearchAgent

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger("talonx_brain.run")


async def main() -> None:
    agent = ResearchAgent()

    loop = asyncio.get_running_loop()

    def _handle_sigint() -> None:
        logger.info("Shutdown requested (Ctrl+C) -- stopping research agent...")
        agent.stop()

    try:
        loop.add_signal_handler(signal.SIGINT, _handle_sigint)
    except NotImplementedError:
        pass  # Windows asyncio loop may not support this; Ctrl+C still raises KeyboardInterrupt

    logger.info(
        "Starting research agent: %s -> %s, LLM provider: %s (Ctrl+C to stop)",
        agent.config.signals_channel, agent.config.reports_channel,
        agent.llm_chain.describe(),
    )
    try:
        await agent.run()
    except KeyboardInterrupt:
        agent.stop()
    finally:
        logger.info(
            "Stopped. Processed %d signals, published %d reports this run.",
            agent.signals_processed, agent.reports_published,
        )


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\nStopped.")
