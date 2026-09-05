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
from talonx_compare.config import CompareConfig
from talonx_compare.dashboard_views import compare_view, original_view, piv_view
from talonx_ops.authoritative_read_model import AuthoritativeReadModel
from talonx_ops.dashboard_read import DashboardReadModel
from talonx_piv.config import PivConfig
from talonx_piv.observability import build_integrated_projection
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


# Task 100A: the Redis per-channel counters below are a live *transport* view;
# a channel showing 0 can mean ZERO_ACTIVITY, NO_ACTIVE_PRODUCER, STALE or
# SUPERSEDED and the raw counter cannot tell them apart. `_authority_block`
# adds a per-domain truthful status read (talonx_ops.authoritative_read_model,
# read-only, no write side effects) so the UI can label a 0 correctly. Cached
# with a short TTL -- it opens a handful of SQLite files per refresh.
_AUTHORITY_TTL_SECONDS = 15.0
_authority_cache: tuple[float, dict] = (0.0, {})


def _authority_block() -> dict:
    global _authority_cache
    age = time.monotonic() - _authority_cache[0]
    if _authority_cache[1] and age < _AUTHORITY_TTL_SECONDS:
        return _authority_cache[1]
    try:
        block = AuthoritativeReadModel().snapshot()
    except Exception as exc:  # noqa: BLE001 -- never let the authority read break the dashboard
        block = {"error": repr(exc), "domains": [], "status_counts": {}, "producers": {}}
    _authority_cache = (time.monotonic(), block)
    return block


# Task 100C: the six primary unified-cockpit sections. Each is a pure read over
# the Task 100A/B authoritative sources (talonx_ops.dashboard_read), TTL-cached
# so a burst of tab clicks does not re-open every SQLite file each time. Every
# handler is GET-only and has zero write side effects.
_SECTION_TTL_SECONDS = 4.0
_section_cache: dict[str, tuple[float, dict]] = {}
_UNIFIED_SECTIONS = ("overview", "premarket", "original_quant", "validation",
                     "intelligence", "paper_eod")


def _section_block(name: str) -> dict:
    cached = _section_cache.get(name)
    if cached is not None and (time.monotonic() - cached[0]) < _SECTION_TTL_SECONDS:
        return cached[1]
    try:
        model = DashboardReadModel()
        data = getattr(model, name)()
    except Exception as exc:  # noqa: BLE001 -- a read failure is surfaced, never a silent 200
        data = {"error": f"{type(exc).__name__}: {exc}", "section": name}
    _section_cache[name] = (time.monotonic(), data)
    return data


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
        "authority": _authority_block(),
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


async def piv_status_handler(request: web.Request) -> web.Response:
    """Task 78I Stage 4 -- ONE additive, read-only JSON endpoint exposing
    talonx_piv's own session-scoped projection (talonx_piv.observability
    .build_integrated_projection, already read-only, already reconciling
    to its own durable ledgers -- see dashboard_reconciliation.json). Does
    NOT touch `/`, `/static/*`, or `/ws`, and adds no order-placement or
    safety-override control of any kind. This dashboard has zero prior
    awareness of talonx_piv (a completely separate subsystem -- see
    architecture_and_ownership.md); this route is the sole connection
    point, read-only in both directions.

    Computed fresh on every request (never cached), so this endpoint can
    never show a stale value next to current data -- a read failure
    (corrupt state file, missing directory, etc.) is reported explicitly
    as an HTTP 500 with a clear error body, never silently as an empty-but-
    plausible-looking 200."""
    state_dir: Path = request.app["piv_state_dir"]
    try:
        projection = build_integrated_projection(state_dir)
    except Exception as exc:  # noqa: BLE001 -- a read failure must be reported explicitly, never
        # silently swallowed into a stale-looking success response.
        return web.json_response(
            {"error": f"PIV_STATUS_READ_FAILED: {type(exc).__name__}: {exc}", "state_dir": str(state_dir)},
            status=500,
        )
    return web.json_response(projection)


async def original_view_handler(request: web.Request) -> web.Response:
    """Task 83 §3 -- read-only Original view. Redis health, the
    Warmup/Quant/Brain/Core/Dispatch/Telegram stage funnel, and local
    simulated-paper activity. A missing/unreachable source is reported as
    its explicit health state, never as a plausible zero. GET only; no
    launch/order/authorization/safety-control endpoint of any kind."""
    import redis as _redis

    client = None
    try:
        client = _redis.from_url(REDIS_URL, socket_connect_timeout=1.0, socket_timeout=1.0)
        payload = await asyncio.to_thread(original_view, redis_client=client)
    except Exception as exc:  # noqa: BLE001 -- a read failure is surfaced, never a silent 200
        return web.json_response(
            {"error": f"ORIGINAL_VIEW_READ_FAILED: {type(exc).__name__}: {exc}"}, status=500)
    finally:
        if client is not None:
            try:
                client.close()
            except Exception:  # noqa: BLE001
                pass
    return web.json_response(payload)


async def piv_view_handler(request: web.Request) -> web.Response:
    """Task 83 §3 -- read-only PIV view: provider/readiness/freshness,
    quant funnel, decisions, shadow, PAPER lifecycle, reconciliation, EOD,
    plus UNVALIDATED status, feed/exec mode, real-capital prohibition and
    the QuantStateStore capability limitation. GET only."""
    state_dir: Path = request.app["piv_state_dir"]
    try:
        payload = await asyncio.to_thread(piv_view, state_dir=state_dir)
    except Exception as exc:  # noqa: BLE001
        return web.json_response(
            {"error": f"PIV_VIEW_READ_FAILED: {type(exc).__name__}: {exc}",
             "state_dir": str(state_dir)}, status=500)
    return web.json_response(payload)


async def compare_view_handler(request: web.Request) -> web.Response:
    """Task 83 §3 -- read-only Compare view: per-stage totals, per-symbol
    agreement/divergence, missing/late stages + reason codes, and the
    separate Original-simulated vs PIV-shadow/PAPER outcome streams. GET
    only; reads only the collector's date-partitioned evidence store."""
    trading_date = request.query.get("date")
    try:
        payload = await asyncio.to_thread(
            compare_view, config=request.app["compare_config"], trading_date=trading_date)
    except Exception as exc:  # noqa: BLE001
        return web.json_response(
            {"error": f"COMPARE_VIEW_READ_FAILED: {type(exc).__name__}: {exc}"}, status=500)
    return web.json_response(payload)


async def admin_config_get(request: web.Request) -> web.Response:
    """Task 102 -- GET /admin/config. Read-only: what the local admin surface
    can do + the strategy/execution denylist + the audit tail. Only served when
    the server is bound to a loopback host."""
    if not request.app.get("admin_enabled", False):
        return web.json_response({"enabled": False,
                                  "reason": "admin config is only available on a loopback bind"}, status=403)
    from talonx_ops.admin_config import ALLOWED_ACTIONS, AdminConfigService

    svc = AdminConfigService()
    try:
        tail = svc.audit_tail(30)
    finally:
        svc.close()
    return web.json_response({
        "enabled": True,
        "note": "Local operational config only. Strategy / execution / broker / short / "
                "Experimental-promotion keys are permanently denied.",
        "allowed_actions": list(ALLOWED_ACTIONS),
        "requires": {"confirm": True},
        "audit_tail": tail,
    })


async def admin_index(request: web.Request) -> web.Response:
    """Task 104 -- GET /admin/ : the dedicated local admin page (loopback only).
    Static HTML that drives the existing /admin/config API. Not linked from the
    read-only cockpit."""
    if not request.app.get("admin_enabled", False):
        return web.Response(status=403, text="admin config is only available on a loopback bind")
    return web.FileResponse(STATIC_DIR / "admin.html")


async def admin_config_state(request: web.Request) -> web.Response:
    """Task 104 -- GET /admin/config/state : read-only current values for the 9
    editable fields, so the admin page can show current-vs-proposed."""
    if not request.app.get("admin_enabled", False):
        return web.json_response({"error": "loopback only"}, status=403)
    from talonx_ops.admin_config import AdminConfigService

    svc = AdminConfigService()
    try:
        state = await asyncio.to_thread(svc.current_state)
    finally:
        svc.close()
    return web.json_response(state)


async def admin_config_apply(request: web.Request) -> web.Response:
    """Task 102 -- POST /admin/config/apply. Body: {action, params, confirm}.
    Loopback-only; every attempt (accepted, rejected, refused) is audited."""
    if not request.app.get("admin_enabled", False):
        return web.json_response({"ok": False,
                                  "reason": "admin config is only available on a loopback bind"}, status=403)
    from talonx_ops.admin_config import AdminConfigService, ConfigDenied

    try:
        body = await request.json()
    except Exception:  # noqa: BLE001
        return web.json_response({"ok": False, "reason": "invalid JSON body"}, status=400)
    action = str(body.get("action", ""))
    params = body.get("params") or {}
    confirm = bool(body.get("confirm", False))
    if not isinstance(params, dict):
        return web.json_response({"ok": False, "reason": "params must be an object"}, status=400)

    svc = AdminConfigService()
    try:
        result = await asyncio.to_thread(svc.apply, action, params, confirm=confirm,
                                         source="admin surface (:8787 /admin/config)")
    except ConfigDenied as exc:
        return web.json_response({"ok": False, "outcome": "REFUSED_DENYLIST", "reason": str(exc)}, status=403)
    finally:
        svc.close()
    return web.json_response(result.to_dict(), status=200 if result.ok else 422)


async def section_handler(request: web.Request) -> web.Response:
    """Task 100C -- GET /api/section/{name}. Read-only unified-cockpit section
    data from talonx_ops.dashboard_read (Task 100A/B authoritative sources).
    No write side effect of any kind."""
    name = request.match_info.get("name", "")
    if name not in _UNIFIED_SECTIONS:
        return web.json_response({"error": f"unknown section '{name}'",
                                  "sections": list(_UNIFIED_SECTIONS)}, status=404)
    data = await asyncio.to_thread(_section_block, name)
    status = 500 if isinstance(data, dict) and "error" in data else 200
    return web.json_response(data, status=status)


async def sections_all_handler(request: web.Request) -> web.Response:
    """Task 100C -- GET /api/sections : all six sections in one read."""
    out = {}
    for name in _UNIFIED_SECTIONS:
        out[name] = await asyncio.to_thread(_section_block, name)
    return web.json_response(out)


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


def build_app(piv_state_dir: Path | None = None, *, admin_enabled: bool = True) -> web.Application:
    app = web.Application()
    # Task 102: the local admin-config surface (POST /admin/config/apply) is only
    # served on a loopback bind. main() computes this from --host; the default
    # bind is localhost, so tests/dev get it, a non-loopback bind does not.
    app["admin_enabled"] = bool(admin_enabled)
    # Task 78I Stage 4: same default-resolution PivConfig().state_dir
    # already uses (TALONX_PIV_STATE_DIR env var, else the existing
    # results/task64_paper_piv_readiness/runtime default) -- never a new,
    # separate default. Tests/rehearsal pass an isolated tmp_path directly.
    app["piv_state_dir"] = piv_state_dir if piv_state_dir is not None else PivConfig().state_dir
    app["compare_config"] = CompareConfig()
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
    app.router.add_get("/piv/status", piv_status_handler)
    # Task 83 §3 -- three additive, GET-only, read-only views.
    app.router.add_get("/views/original", original_view_handler)
    app.router.add_get("/views/piv", piv_view_handler)
    app.router.add_get("/views/compare", compare_view_handler)
    # Task 100C -- six additive, GET-only, read-only unified-cockpit sections.
    app.router.add_get("/api/sections", sections_all_handler)
    app.router.add_get("/api/section/{name}", section_handler)
    # Task 102/104 -- local-only operational config (loopback-gated, audited, no
    # strategy/execution keys). GET is read-only; POST requires confirm=true.
    app.router.add_get("/admin/", admin_index)
    app.router.add_get("/admin/config", admin_config_get)
    app.router.add_get("/admin/config/state", admin_config_state)
    app.router.add_post("/admin/config/apply", admin_config_apply)
    app.router.add_static("/static/", STATIC_DIR, show_index=False)

    app.on_startup.append(on_startup)
    app.on_cleanup.append(on_cleanup)
    return app


def main() -> None:
    parser = argparse.ArgumentParser(description="Live browser dashboard for the TalonX pipeline")
    parser.add_argument("--port", type=int, default=8787, help="Port to serve on (default: 8787)")
    parser.add_argument("--host", default="localhost", help="Host to bind (default: localhost)")
    parser.add_argument("--piv-state-dir", default=None, help="Task 78I: override talonx_piv's state_dir for the /piv/status endpoint (default: PivConfig()'s own resolution, i.e. TALONX_PIV_STATE_DIR or its built-in default)")
    args = parser.parse_args()

    from talonx_ops.admin_config import loopback_host

    admin_ok = loopback_host(args.host)
    app = build_app(Path(args.piv_state_dir) if args.piv_state_dir else None, admin_enabled=admin_ok)
    logger.info("Starting dashboard web server -- open http://%s:%d in your browser "
                "(admin config %s)", args.host, args.port, "enabled" if admin_ok else "DISABLED (non-loopback bind)")
    web.run_app(app, host=args.host, port=args.port, print=None)


if __name__ == "__main__":
    main()
