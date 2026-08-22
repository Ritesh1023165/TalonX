"""
talonx_ingest.market_data.manager
--------------------------------------
Single entrypoint for structured market data. Chooses Polygon.io WebSocket
streaming when an API key is configured, and falls back to yfinance polling
either when no key is present at all, or automatically mid-run if the
WebSocket exhausts its reconnect budget.

Downstream code (the quant filtering stage) only ever talks to this
manager and only ever sees normalized `MarketEvent` objects -- it never
needs to know or care which source produced them.
"""
from __future__ import annotations

import logging
from typing import Awaitable, Callable

from talonx_ingest.config import MarketDataConfig, settings
from talonx_ingest.market_data.models import MarketEvent
from talonx_ingest.market_data.polygon_ws import (
    MaxReconnectAttemptsExceeded,
    PolygonAuthError,
    PolygonWebSocketClient,
)
from talonx_ingest.market_data.yfinance_poll import YFinancePoller

logger = logging.getLogger("talonx_ingest.market_data.manager")

EventCallback = Callable[[MarketEvent], Awaitable[None]]


class MarketDataManager:
    def __init__(self, config: MarketDataConfig | None = None, metrics_publisher=None):
        self.config = config or settings.market_data
        self._ws_client: PolygonWebSocketClient | None = None
        self._poller: YFinancePoller | None = None
        # 2026-08-18 /ping observability fix: forwarded straight through to
        # the yfinance fallback poller (see YFinancePoller.__init__'s own
        # docstring) -- optional, additive, no behavior change when omitted.
        self._metrics_publisher = metrics_publisher

    def stop(self) -> None:
        """Signal a graceful shutdown of whichever source is currently active."""
        if self._ws_client:
            self._ws_client.stop()
        if self._poller:
            self._poller.stop()

    async def stream(self, symbols: list[str], on_event: EventCallback) -> None:
        """
        Stream normalized market events for `symbols` until `stop()` is
        called. Tries Polygon WebSocket first (if configured); falls back
        to yfinance polling on missing API key, auth failure, or exhausted
        reconnects.
        """
        if not symbols:
            raise ValueError("stream() requires at least one symbol")

        if self.config.polygon_api_key:
            try:
                logger.info("Starting market data via Polygon WebSocket")
                self._ws_client = PolygonWebSocketClient(self.config)
                await self._ws_client.stream(symbols, on_event)
                return  # clean stop() was called
            except PolygonAuthError as exc:
                logger.error(
                    "Polygon API key rejected (%s) -- falling back to "
                    "yfinance polling. Fix POLYGON_API_KEY to use "
                    "WebSocket streaming.", exc,
                )
            except MaxReconnectAttemptsExceeded as exc:
                logger.error(
                    "Polygon WebSocket exhausted its reconnect budget (%s) "
                    "-- falling back to yfinance polling for the rest of "
                    "this run.", exc,
                )
        else:
            logger.info(
                "No POLYGON_API_KEY configured -- using yfinance polling "
                "(delayed data, not true real-time)."
            )

        self._poller = YFinancePoller(self.config, metrics_publisher=self._metrics_publisher)
        await self._poller.stream(symbols, on_event)
