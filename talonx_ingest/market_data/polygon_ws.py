"""
talonx_ingest.market_data.polygon_ws
----------------------------------------
Async WebSocket client for Polygon.io's real-time stocks feed.

Protocol (see https://polygon.io/docs/stocks/ws_getting-started):
  1. Connect to wss://socket.polygon.io/stocks
  2. Send {"action": "auth", "params": "<API_KEY>"}
     -> server replies with a status message; "auth_success" or "auth_failed"
  3. Send {"action": "subscribe", "params": "T.AAPL,Q.AAPL,AM.AAPL,T.MSFT,..."}
  4. Server streams JSON arrays of events until disconnected.

Event shapes (abbreviated):
  Trade:  {"ev":"T",  "sym":"AAPL", "p":227.5, "s":100, "t":1690000000000}
  Quote:  {"ev":"Q",  "sym":"AAPL", "bp":227.4, "bs":2, "ap":227.6, "as":3, "t":...}
  Minute: {"ev":"AM", "sym":"AAPL", "o":227.1,"h":227.9,"l":227.0,"c":227.5,"v":15000,"s":...}

This client handles auth, subscription, message parsing into `MarketEvent`,
and reconnect-with-backoff. It does NOT decide what to do after reconnects
are exhausted -- it raises `MaxReconnectAttemptsExceeded` and lets the
caller (market_data.manager) decide whether to fail over to polling.
"""
from __future__ import annotations

import asyncio
import json
import logging
from datetime import datetime, timezone
from typing import Awaitable, Callable

from talonx_ingest.common.backoff import jittered_backoff_seconds
from talonx_ingest.config import MarketDataConfig, settings
from talonx_ingest.market_data.models import DataSource, MarketEvent, MarketEventType

logger = logging.getLogger("talonx_ingest.market_data.polygon_ws")

# websockets is only needed for the Polygon path -- import it lazily so
# `market_data.manager` (and anything that imports this module) still works
# for users who only want the yfinance polling fallback and haven't
# installed `websockets`. The real error surfaces the moment someone
# actually tries to construct a PolygonWebSocketClient, with a clear
# "pip install websockets" message rather than a confusing import-time crash.
try:
    import websockets
    from websockets.exceptions import ConnectionClosed, WebSocketException
except ImportError:  # pragma: no cover - exercised only when dependency missing
    websockets = None

    class ConnectionClosed(Exception):
        pass

    class WebSocketException(Exception):
        pass

EventCallback = Callable[[MarketEvent], Awaitable[None]]


class PolygonAuthError(Exception):
    """Raised when Polygon rejects the API key -- not retryable."""


class MaxReconnectAttemptsExceeded(Exception):
    """Raised when the client has exhausted its reconnect budget."""


class PolygonWebSocketClient:
    def __init__(self, config: MarketDataConfig | None = None):
        self.config = config or settings.market_data
        if websockets is None:
            raise ImportError(
                "The 'websockets' package is required for Polygon streaming. "
                "Install it with: pip install websockets"
            )
        if not self.config.polygon_api_key:
            raise ValueError(
                "PolygonWebSocketClient requires POLYGON_API_KEY to be set"
            )
        self._stop_event = asyncio.Event()

    def stop(self) -> None:
        """Signal a graceful shutdown of the streaming loop."""
        self._stop_event.set()

    async def stream(self, symbols: list[str], on_event: EventCallback) -> None:
        """
        Run the connect -> auth -> subscribe -> receive loop, reconnecting
        with backoff on transient failures. Returns normally only if
        `stop()` is called. Raises MaxReconnectAttemptsExceeded if the
        reconnect budget is exhausted without a stop request, or
        PolygonAuthError if the API key itself is rejected (not retried).
        """
        attempt = 0
        while not self._stop_event.is_set():
            try:
                await self._connect_and_run(symbols, on_event)
                # _connect_and_run only returns normally on a clean stop.
                return
            except PolygonAuthError:
                raise  # bad API key -- no point retrying
            except (ConnectionClosed, WebSocketException, OSError, asyncio.TimeoutError) as exc:
                attempt += 1
                if attempt > self.config.ws_max_reconnect_attempts:
                    raise MaxReconnectAttemptsExceeded(
                        f"Polygon WebSocket failed {attempt - 1} reconnect "
                        f"attempts: {exc}"
                    ) from exc
                wait = jittered_backoff_seconds(
                    attempt,
                    self.config.ws_backoff_base_seconds,
                    self.config.ws_backoff_max_seconds,
                )
                logger.warning(
                    "Polygon WebSocket disconnected (%s); reconnect attempt "
                    "%d/%d in %.1fs",
                    exc, attempt, self.config.ws_max_reconnect_attempts, wait,
                )
                await asyncio.sleep(wait)

    async def _connect_and_run(
        self, symbols: list[str], on_event: EventCallback
    ) -> None:
        async with websockets.connect(
            self.config.polygon_ws_url, ping_interval=20, ping_timeout=20
        ) as ws:
            await self._authenticate(ws)
            await self._subscribe(ws, symbols)
            logger.info(
                "Polygon WebSocket connected and subscribed: %d symbols, "
                "channels=%s", len(symbols), self.config.polygon_channels,
            )

            while not self._stop_event.is_set():
                try:
                    raw_message = await asyncio.wait_for(
                        ws.recv(), timeout=self.config.ws_message_idle_timeout_seconds
                    )
                except asyncio.TimeoutError:
                    logger.warning(
                        "No Polygon message in %.0fs -- treating as stale "
                        "connection, forcing reconnect",
                        self.config.ws_message_idle_timeout_seconds,
                    )
                    raise  # bubbles up to stream()'s retry logic

                for event in self._parse_message(raw_message):
                    await on_event(event)

    async def _authenticate(self, ws) -> None:
        await ws.send(json.dumps({"action": "auth", "params": self.config.polygon_api_key}))
        raw = await asyncio.wait_for(ws.recv(), timeout=self.config.ws_auth_timeout_seconds)
        messages = json.loads(raw)
        for msg in messages if isinstance(messages, list) else [messages]:
            status = msg.get("status")
            if status == "auth_success":
                return
            if status == "auth_failed":
                raise PolygonAuthError(f"Polygon auth failed: {msg.get('message')}")
        # Some accounts get an initial "connected" status before auth_success
        # arrives in a follow-up message; give it one more read.
        raw2 = await asyncio.wait_for(ws.recv(), timeout=self.config.ws_auth_timeout_seconds)
        messages2 = json.loads(raw2)
        for msg in messages2 if isinstance(messages2, list) else [messages2]:
            if msg.get("status") == "auth_success":
                return
            if msg.get("status") == "auth_failed":
                raise PolygonAuthError(f"Polygon auth failed: {msg.get('message')}")
        raise PolygonAuthError("Polygon did not confirm auth_success in time")

    async def _subscribe(self, ws, symbols: list[str]) -> None:
        params = ",".join(
            f"{channel}.{symbol.upper()}"
            for symbol in symbols
            for channel in self.config.polygon_channels
        )
        await ws.send(json.dumps({"action": "subscribe", "params": params}))

    def _parse_message(self, raw_message: str) -> list[MarketEvent]:
        try:
            payload = json.loads(raw_message)
        except json.JSONDecodeError:
            logger.warning("Non-JSON message from Polygon, skipping: %r", raw_message[:200])
            return []

        items = payload if isinstance(payload, list) else [payload]
        events: list[MarketEvent] = []
        for item in items:
            event = self._parse_one(item)
            if event is not None:
                events.append(event)
        return events

    @staticmethod
    def _parse_one(item: dict) -> MarketEvent | None:
        ev = item.get("ev")
        if ev == "status":
            return None  # heartbeats / status frames, not data

        symbol = item.get("sym")
        if not symbol:
            return None

        if ev == "T":
            return MarketEvent(
                symbol=symbol,
                event_type=MarketEventType.TRADE,
                source=DataSource.WEBSOCKET,
                timestamp=_ms_to_datetime(item.get("t")),
                price=item.get("p"),
                volume=item.get("s"),
                raw=item,
            )
        if ev == "Q":
            return MarketEvent(
                symbol=symbol,
                event_type=MarketEventType.QUOTE,
                source=DataSource.WEBSOCKET,
                timestamp=_ms_to_datetime(item.get("t")),
                bid=item.get("bp"),
                ask=item.get("ap"),
                bid_size=item.get("bs"),
                ask_size=item.get("as"),
                raw=item,
            )
        if ev == "AM":
            return MarketEvent(
                symbol=symbol,
                event_type=MarketEventType.BAR,
                source=DataSource.WEBSOCKET,
                timestamp=_ms_to_datetime(item.get("s")),
                open=item.get("o"),
                high=item.get("h"),
                low=item.get("l"),
                close=item.get("c"),
                volume=item.get("v"),
                raw=item,
            )

        logger.debug("Unhandled Polygon event type: %s", ev)
        return None


def _ms_to_datetime(ms: int | None) -> datetime:
    if ms is None:
        return datetime.now(timezone.utc)
    return datetime.fromtimestamp(ms / 1000, tz=timezone.utc)
