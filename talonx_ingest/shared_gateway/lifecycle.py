"""
talonx_ingest.shared_gateway.lifecycle
---------------------------------------------
Process entrypoint for the Shared Alpaca Gateway producer.

Usage:
    python -m talonx_ingest.shared_gateway.lifecycle --confirm-shadow-mode

Requires --confirm-shadow-mode (an explicit, operator-typed acknowledgement,
same "no silent capability creep" posture as talonx_piv.cli's
--confirm-paper-session-start / --isolated-parallel flags) so this can
never be started as a side effect of another script forgetting a flag.
This process is READ-ONLY market-data plumbing: it never imports or
constructs anything execution/lifecycle-capable (see module docstrings in
alpaca_gateway.py and shadow_consumer_base.py).

Stop with Ctrl+C -- SIGINT triggers a graceful stop() so the current poll
cycle finishes and the Redis connection closes cleanly.
"""
from __future__ import annotations

import argparse
import asyncio
import logging
import signal
import sys

import requests

from .alpaca_gateway import AlpacaGatewayProducer
from .config import GatewayConfig

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger("talonx_ingest.shared_gateway.lifecycle")


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Task 88 Shared Alpaca Gateway (SHADOW_INGESTION_ONLY)")
    parser.add_argument(
        "--confirm-shadow-mode", action="store_true",
        help="Required explicit acknowledgement that this process is read-only market-data plumbing only.",
    )
    return parser.parse_args(argv)


async def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    if not args.confirm_shadow_mode:
        logger.error("Refusing to start without --confirm-shadow-mode.")
        return 2

    config = GatewayConfig()
    if not config.key_id or not config.secret_key:
        logger.error("APCA_API_KEY_ID / APCA_API_SECRET_KEY are not configured -- cannot start.")
        return 2

    producer = AlpacaGatewayProducer(config=config, transport=requests)

    loop = asyncio.get_running_loop()

    def _handle_sigint() -> None:
        logger.info("Shutdown requested (Ctrl+C) -- stopping gateway...")
        producer.stop()

    try:
        loop.add_signal_handler(signal.SIGINT, _handle_sigint)
    except NotImplementedError:
        pass  # Windows asyncio event loop limitation -- falls back to KeyboardInterrupt below

    try:
        await producer.run()
    except KeyboardInterrupt:
        producer.stop()
    return 0


if __name__ == "__main__":
    try:
        sys.exit(asyncio.run(main()))
    except KeyboardInterrupt:
        print("\nStopped.")
