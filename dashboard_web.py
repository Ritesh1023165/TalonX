"""
dashboard_web.py
---------------------
Browser-based live dashboard for the TalonX pipeline -- same underlying
data as dashboard.py (the terminal version), served as a local web page
with charts instead of a text table.

Runs entirely on your machine: a small aiohttp web server (aiohttp is
already a dependency -- see talonx_ingest/requirements.txt -- so this
adds no new heavy framework) serves a self-contained HTML/JS page and
pushes live stats over a WebSocket, all on http://localhost. Deliberately
NOT a published Claude Artifact -- Artifacts enforce a strict CSP that
blocks fetch/WebSocket calls to any host outside the artifact's own
origin, which would block reaching this project's local, Redis-backed
data entirely. Same "runs entirely on your machine, no cloud dependency"
philosophy as everything else in this project (local Redis, local
ChromaDB, local SQLite).

Reuses dashboard.py's channel-watching logic (CHANNELS, ChannelWatch,
ChannelStats, REDIS_URL, handle_message) rather than duplicating it --
the channel-to-ticker-field mapping is the one thing that MUST stay in
sync between the two tools, so it lives in exactly one place.

Usage:
    python dashboard_web.py
    python dashboard_web.py --port 9000
"""
from __future__ import annotations

import argparse
import asyncio
import json
import logging
import time
from pathlib import Path

from aiohttp import WSMsgType, web

from dashboard import CHANNELS, REDIS_URL, ChannelStats, handle_message

logging.basicConfig(
    level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s"
)
logger = logging.getLogger("dashboard_web")

STATIC_DIR = Path(__file__).resolve().parent / "dashboard_web_static"
BROADCAST_INTERVAL_SECONDS = 1.0


def _snapshot(stats: dict[str, ChannelStats], started_at: float) -> dict:
    elapsed = time.monotonic() - started_at
    all_tickers: set[str] = set()
    channels = []
    grand_total = 0

    for watch in CHANNELS:
        s = stats[watch.key]
        s.snapshot_interval()
        grand_total += s.total
        all_tickers.update(s.tickers.keys())
        channels.append(
            {
                "key": watch.key,
                "label": watch.label,
                "channel": watch.channel,
                "total": s.total,
                "unparseable": s.unparseable,
                "rate_per_min": round(s.rate_per_min(elapsed), 1),
                "top_tickers": s.tickers.most_common(8),
                "history": list(s.history),
            }
        )

    return {
        "uptime_seconds": elapsed,
        "grand_total": grand_total,
        "distinct_tickers": len(all_tickers),
        "channels": channels,
    }


async def _redis_consumer(app: web.Application) -> None:
    import redis.asyncio as redis_asyncio

    stats: dict[str, ChannelStats] = app["stats"]
    by_channel = {w.channel: w for w in CHANNELS}
    stop_event: asyncio.Event = app["stop_event"]

    attempt = 0
    while not stop_event.is_set():
        client = redis_asyncio.from_url(REDIS_URL)
        try:
            await client.ping()
            logger.info("Connected to Redis at %s", REDIS_URL)
            attempt = 0

            pubsub = client.pubsub()
            await pubsub.subscribe(*by_channel.keys())
            try:
                while not stop_event.is_set():
                    message = await pubsub.get_message(
                        ignore_subscribe_messages=True, timeout=1.0
                    )
                    if message is not None:
                        handle_message(message, by_channel, stats)
            finally:
                await pubsub.unsubscribe(*by_channel.keys())
                await pubsub.aclose()
            return
        except Exception as exc:  # noqa: BLE001 -- any connection/listen failure retries
            attempt += 1
            wait = min(30.0, 1.0 * (2**(attempt - 1)))
            logger.warning("Redis connection error (%s); retrying in %.1fs", exc, wait)
            await asyncio.sleep(wait)
        finally:
            await client.aclose()


async def _broadcaster(app: web.Application) -> None:
    stop_event: asyncio.Event = app["stop_event"]
    while not stop_event.is_set():
        await asyncio.sleep(BROADCAST_INTERVAL_SECONDS)
        payload = json.dumps(_snapshot(app["stats"], app["started_at"]))
        dead = []
        for ws in app["websockets"]:
            try:
                await ws.send_str(payload)
            except (ConnectionResetError, RuntimeError):
                dead.append(ws)
        for ws in dead:
            app["websockets"].discard(ws)


async def websocket_handler(request: web.Request) -> web.WebSocketResponse:
    ws = web.WebSocketResponse(heartbeat=30)
    await ws.prepare(request)
    request.app["websockets"].add(ws)
    logger.info("Dashboard client connected (%d total)", len(request.app["websockets"]))
    try:
        # Immediate snapshot so the page isn't blank until the next broadcast tick.
        snapshot = _snapshot(request.app["stats"], request.app["started_at"])
        await ws.send_str(json.dumps(snapshot))
        async for msg in ws:
            if msg.type == WSMsgType.ERROR:
                break
    finally:
        request.app["websockets"].discard(ws)
        logger.info("Dashboard client disconnected (%d remaining)", len(request.app["websockets"]))
    return ws


async def index_handler(request: web.Request) -> web.FileResponse:
    return web.FileResponse(STATIC_DIR / "index.html")


async def on_startup(app: web.Application) -> None:
    app["redis_task"] = asyncio.create_task(_redis_consumer(app))
    app["broadcast_task"] = asyncio.create_task(_broadcaster(app))


async def on_cleanup(app: web.Application) -> None:
    app["stop_event"].set()
    for key in ("redis_task", "broadcast_task"):
        task = app[key]
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass


def build_app() -> web.Application:
    app = web.Application()
    app["stats"] = {watch.key: ChannelStats() for watch in CHANNELS}
    app["websockets"] = set()
    app["started_at"] = time.monotonic()
    app["stop_event"] = asyncio.Event()

    app.router.add_get("/ws", websocket_handler)
    app.router.add_get("/", index_handler)
    app.router.add_static("/static/", STATIC_DIR, show_index=False)

    app.on_startup.append(on_startup)
    app.on_cleanup.append(on_cleanup)
    return app


def main() -> None:
    parser = argparse.ArgumentParser(description="Live browser dashboard for the TalonX pipeline")
    parser.add_argument("--port", type=int, default=8787, help="Port to serve on (default: 8787)")
    parser.add_argument("--host", default="localhost", help="Host to bind (default: localhost)")
    args = parser.parse_args()

    app = build_app()
    logger.info("Starting dashboard web server -- open http://%s:%d in your browser", args.host, args.port)
    web.run_app(app, host=args.host, port=args.port, print=None)


if __name__ == "__main__":
    main()
