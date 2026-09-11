"""
talonx_ingest.intelligence.dashboard.app
========================================
Thin aiohttp wiring. Every request is adapted to a pure
``routes.handle(...)`` call; the server adds nothing but transport,
timing and a generic error page. Binds ``127.0.0.1`` by default —
local-only, read-only, no cloud dependency (same philosophy as the
existing ``dashboard_web.py``).

    python -m talonx_ingest.intelligence.dashboard --port 8760
"""
from __future__ import annotations

import argparse
import time

from aiohttp import web

from talonx_ingest.intelligence.dashboard.observability import DashboardMetrics
from talonx_ingest.intelligence.dashboard.readapi import IntelligenceReadAPI
from talonx_ingest.intelligence.dashboard.routes import Response, handle


def make_app(
    *,
    ledger_path: str | None = None,
    api: IntelligenceReadAPI | None = None,
    metrics: DashboardMetrics | None = None,
) -> web.Application:
    metrics = metrics or DashboardMetrics()
    read_api = api or IntelligenceReadAPI(ledger_path=ledger_path)
    app = web.Application()

    async def _dispatch(request: web.Request) -> web.Response:
        started = time.perf_counter()
        resp: Response = handle(
            read_api, request.method, request.path, dict(request.query), metrics=metrics
        )
        metrics.record_request(
            resp.route, api=resp.is_api,
            latency_ms=(time.perf_counter() - started) * 1000.0, status=resp.status,
        )
        return web.Response(status=resp.status, text=resp.body, content_type=resp.content_type.split(";")[0],
                            charset="utf-8")

    async def _metrics(request: web.Request) -> web.Response:
        return web.json_response(metrics.as_dict())

    async def _health(request: web.Request) -> web.Response:
        try:
            fs = read_api.freshness_state()
            return web.json_response({"ok": True, "freshness": fs["overall"], "counts": fs["counts"]})
        except Exception as exc:  # noqa: BLE001
            return web.json_response({"ok": False, "error": type(exc).__name__}, status=503)

    async def _on_cleanup(_app):
        if api is None:
            read_api.close()

    app.router.add_get("/__metrics", _metrics)
    app.router.add_get("/__health", _health)
    app.router.add_route("*", "/{tail:.*}", _dispatch)
    app.on_cleanup.append(_on_cleanup)
    return app


def main() -> int:
    ap = argparse.ArgumentParser(description="TalonX Event-Intelligence Dashboard (read-only, local)")
    ap.add_argument("--host", default="127.0.0.1")
    ap.add_argument("--port", type=int, default=8760)
    ap.add_argument("--ledger-path", default=None, help="override the intelligence ledger DB path")
    args = ap.parse_args()
    web.run_app(make_app(ledger_path=args.ledger_path), host=args.host, port=args.port)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
