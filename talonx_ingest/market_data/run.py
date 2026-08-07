"""
talonx_ingest.market_data.run
----------------------------------
Entrypoint for live market data. Every normalized MarketEvent is:
  1. Printed to the console (for visibility while running).
  2. Converted to the MarketTickEvent contract and published to the
     `talonx:market:stream` Redis channel -- this IS the module's real
     output contract per the project spec; the console printing is just
     a convenience for running this standalone.

If Redis isn't reachable, publishing is silently disabled (logged once)
and the stream still runs and prints normally -- a broker outage
shouldn't stop you from seeing the data locally.

Usage:
    python -m talonx_ingest.market_data.run AAPL MSFT NVDA

With POLYGON_API_KEY set in your .env or environment, this streams via
WebSocket. Without it, it automatically polls via yfinance every few
seconds instead.

Stop with Ctrl+C -- SIGINT triggers a graceful shutdown via manager.stop().
"""
from __future__ import annotations

import asyncio
import logging
import signal
import sys

from talonx_ingest.events.publisher import RedisEventPublisher
from talonx_ingest.events.schemas import MarketTickEvent, TickEventType, TickSource
from talonx_ingest.market_data.manager import MarketDataManager
from talonx_ingest.market_data.models import MarketEvent

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger("talonx_ingest.market_data.run")


def _print_event(event: MarketEvent) -> None:
    ts = event.timestamp.strftime("%H:%M:%S")
    if event.event_type.value == "trade":
        print(f"[{ts}] {event.symbol:<6} TRADE  price={event.price} vol={event.volume} "
              f"({event.source.value})")
    elif event.event_type.value == "quote":
        print(f"[{ts}] {event.symbol:<6} QUOTE  bid={event.bid} ask={event.ask} "
              f"({event.source.value})")
    else:
        print(f"[{ts}] {event.symbol:<6} BAR    O={event.open} H={event.high} "
              f"L={event.low} C={event.close} V={event.volume} ({event.source.value})")


def _to_tick_event(event: MarketEvent) -> MarketTickEvent:
    return MarketTickEvent(
        event_type=TickEventType(event.event_type.value),
        symbol=event.symbol,
        source=TickSource(event.source.value),
        timestamp=event.timestamp,
        price=event.price,
        volume=event.volume,
        bid=event.bid,
        ask=event.ask,
        bid_size=event.bid_size,
        ask_size=event.ask_size,
        open=event.open,
        high=event.high,
        low=event.low,
        close=event.close,
    )


def make_on_event(publisher: RedisEventPublisher):
    async def on_event(event: MarketEvent) -> None:
        _print_event(event)
        await publisher.publish_market_tick(_to_tick_event(event))

    return on_event


async def main(symbols: list[str]) -> None:
    manager = MarketDataManager()
    publisher = RedisEventPublisher()
    await publisher.connect()  # logs a warning and continues if Redis unavailable

    loop = asyncio.get_running_loop()

    def _handle_sigint() -> None:
        logger.info("Shutdown requested (Ctrl+C) -- stopping stream...")
        manager.stop()

    # Windows' asyncio event loop doesn't support add_signal_handler for
    # SIGINT in all configurations -- fall back to default KeyboardInterrupt
    # handling if it's unavailable rather than crashing on startup.
    try:
        loop.add_signal_handler(signal.SIGINT, _handle_sigint)
    except NotImplementedError:
        pass

    logger.info(
        "Streaming market data for: %s (Ctrl+C to stop). Publishing to "
        "Redis: %s", symbols, publisher.is_connected,
    )
    try:
        await manager.stream(symbols, make_on_event(publisher))
    except KeyboardInterrupt:
        manager.stop()
    finally:
        await publisher.close()


if __name__ == "__main__":
    tickers = sys.argv[1:] or ["AAPL", "MSFT", "NVDA"]
    try:
        asyncio.run(main(tickers))
    except KeyboardInterrupt:
        print("\nStopped.")
