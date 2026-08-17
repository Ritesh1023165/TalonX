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

Bar buffer warm-up (talonx_quant's RollingBarBuffer pre-seeding/session-
aware buffering, see docs/bar_buffer_persistence.md) is a SEPARATE data
source added alongside the Redis channel stats above: it isn't published
to Redis at all, so a pure pub/sub observer can't see it (same "can't
count what's never published" limitation dashboard.py's own docstring
already calls out for suppressed signals). `_buffer_stats_poll` instead
reads `quant.db`'s `bar_buffer` table directly, read-only WAL mode, same
technique `scripts/ticker_funnel_report.py` already uses to read a live
writer's SQLite file safely -- polled independently of the Redis
consumer and broadcast in the same WebSocket snapshot.

Usage:
    python dashboard_web.py
    python dashboard_web.py --port 9000
"""
from __future__ import annotations

import argparse
import asyncio
import json
import logging
import sqlite3
import time
from pathlib import Path

from aiohttp import WSMsgType, web

from dashboard import CHANNELS, REDIS_URL, ChannelStats, handle_message
from talonx_quant.config import QuantConfig

logging.basicConfig(
    level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s"
)
logger = logging.getLogger("dashboard_web")

STATIC_DIR = Path(__file__).resolve().parent / "dashboard_web_static"
BROADCAST_INTERVAL_SECONDS = 1.0
# bar_buffer only changes as often as talonx_quant's own checkpoint
# interval (60s default) or a one-off pre-seed write -- polling every 10s
# is plenty responsive without hammering a live writer's SQLite file for
# no reason.
BUFFER_POLL_INTERVAL_SECONDS = 10.0


def _read_buffer_stats(db_path: str, min_bars_required: int, htf_sma_period: int) -> dict:
    """Blocking -- run via asyncio.to_thread. Opens a FRESH read-only
    connection every call (quant.db is tiny; this is far simpler than
    holding a long-lived connection across restarts of the writer
    process) so it always reflects the latest committed checkpoint.
    Never raises -- a missing/locked/mid-migration db degrades to
    `db_unavailable: true` rather than crashing the poll loop."""
    path = Path(db_path)
    if not path.is_file():
        return {"db_unavailable": True, "symbols": [], "session_counts": {}, "summary": {"total": 0, "ready_1m": 0, "ready_15m": 0}}

    try:
        conn = sqlite3.connect(f"file:{path.as_posix()}?mode=ro", uri=True, timeout=2.0)
        conn.row_factory = sqlite3.Row
        try:
            bar_rows = conn.execute(
                "SELECT symbol, buffer_type, COUNT(*) AS n, MAX(ts) AS newest "
                "FROM bar_buffer GROUP BY symbol, buffer_type"
            ).fetchall()
            session_rows = conn.execute(
                "SELECT COALESCE(session, 'unknown') AS session, COUNT(*) AS n FROM bar_buffer GROUP BY session"
            ).fetchall()
        finally:
            conn.close()
    except sqlite3.Error as exc:  # noqa: BLE001 -- best-effort read, never fatal to the dashboard
        logger.warning("Buffer stats read failed (%s): %s", db_path, exc)
        return {"db_unavailable": True, "symbols": [], "session_counts": {}, "summary": {"total": 0, "ready_1m": 0, "ready_15m": 0}}

    by_symbol: dict[str, dict] = {}
    for row in bar_rows:
        entry = by_symbol.setdefault(row["symbol"], {"symbol": row["symbol"], "bar_1m": 0, "bar_15m": 0})
        if row["buffer_type"] == "1m":
            entry["bar_1m"] = row["n"]
            entry["newest_1m"] = row["newest"]
        elif row["buffer_type"] == "15m":
            entry["bar_15m"] = row["n"]
            entry["newest_15m"] = row["newest"]

    symbols = []
    ready_1m = ready_15m = 0
    for symbol in sorted(by_symbol):
        entry = by_symbol[symbol]
        is_ready_1m = entry["bar_1m"] >= min_bars_required
        is_ready_15m = entry["bar_15m"] >= htf_sma_period
        ready_1m += int(is_ready_1m)
        ready_15m += int(is_ready_15m)
        symbols.append({
            "symbol": symbol,
            "bar_1m": entry["bar_1m"], "bar_15m": entry["bar_15m"],
            "ready_1m": is_ready_1m, "ready_15m": is_ready_15m,
        })

    return {
        "db_unavailable": False,
        "min_bars_required": min_bars_required,
        "htf_sma_period": htf_sma_period,
        "summary": {"total": len(symbols), "ready_1m": ready_1m, "ready_15m": ready_15m},
        "session_counts": {row["session"]: row["n"] for row in session_rows},
        "symbols": symbols,
    }


async def _buffer_stats_poll(app: web.Application) -> None:
    """Mutates app["buffer_stats"]["data"] in place on every poll tick,
    rather than reassigning app["buffer_stats"] itself -- aiohttp's
    Application deprecates `app[key] = ...` once the app has started
    (app["stats"]'s ChannelStats objects avoid this the same way: they're
    mutated in place, never reassigned, after on_startup runs)."""
    stop_event: asyncio.Event = app["stop_event"]
    config: QuantConfig = app["quant_config"]
    while not stop_event.is_set():
        app["buffer_stats"]["data"] = await asyncio.to_thread(
            _read_buffer_stats, config.db_path, config.min_bars_required, config.htf_sma_period,
        )
        try:
            await asyncio.wait_for(stop_event.wait(), timeout=BUFFER_POLL_INTERVAL_SECONDS)
        except asyncio.TimeoutError:
            pass  # normal case: poll interval elapsed


def _snapshot(stats: dict[str, ChannelStats], started_at: float, buffer_stats: dict) -> dict:
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
                "category_label": watch.category_label,
                "categories": s.categories.most_common(8) if watch.categorize else [],
                "numeric_label": watch.numeric_label,
                "numeric_total": round(s.numeric_total, 2) if watch.numeric_field else None,
            }
        )

    return {
        "uptime_seconds": elapsed,
        "grand_total": grand_total,
        "distinct_tickers": len(all_tickers),
        "channels": channels,
        "buffer_warmup": buffer_stats,
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
        payload = json.dumps(_snapshot(app["stats"], app["started_at"], app["buffer_stats"]["data"]))
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
        snapshot = _snapshot(request.app["stats"], request.app["started_at"], request.app["buffer_stats"]["data"])
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
    app["buffer_poll_task"] = asyncio.create_task(_buffer_stats_poll(app))


async def on_cleanup(app: web.Application) -> None:
    app["stop_event"].set()
    for key in ("redis_task", "broadcast_task", "buffer_poll_task"):
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
    app["quant_config"] = QuantConfig()
    # "data" populated on the first _buffer_stats_poll tick (up to
    # BUFFER_POLL_INTERVAL_SECONDS after startup) -- db_unavailable=true
    # until then, same "don't block startup on it" posture the Redis
    # consumer already has (a client connecting before the first poll
    # just sees an empty buffer panel for a few seconds, not an error).
    # Wrapped in a dict (mutated in place by _buffer_stats_poll) rather
    # than reassigning app["buffer_stats"] directly -- see that
    # function's own docstring.
    app["buffer_stats"] = {
        "data": {"db_unavailable": True, "symbols": [], "session_counts": {}, "summary": {"total": 0, "ready_1m": 0, "ready_15m": 0}},
    }

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
