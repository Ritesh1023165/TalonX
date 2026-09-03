"""
tests/test_dashboard_app.py
---------------------------
Task 96G -- the aiohttp wiring: health, metrics, transport, no stack
traces, observability separate from quant.
"""
from __future__ import annotations

import pytest
from aiohttp.test_utils import TestClient, TestServer

from talonx_ingest.intelligence.dashboard.app import make_app
from talonx_ingest.intelligence.dashboard.observability import DashboardMetrics
from _dashboard_helpers import seeded_api


async def _client(app):
    server = TestServer(app)
    client = TestClient(server)
    await client.start_server()
    return client


@pytest.mark.asyncio
async def test_pages_and_api_served(tmp_path):
    api = seeded_api(tmp_path / "ledger.db")
    metrics = DashboardMetrics()
    client = await _client(make_app(api=api, metrics=metrics))
    try:
        for path, ct in [
            ("/", "text/html"),
            ("/filings", "text/html"),
            ("/evidence", "text/html"),
            ("/company/AAPL", "text/html"),
            ("/api/today", "application/json"),
            ("/api/freshness", "application/json"),
        ]:
            r = await client.get(path)
            assert r.status == 200, (path, r.status)
            assert r.content_type == ct
        assert metrics.page_requests >= 4 and metrics.api_requests >= 2
    finally:
        await client.close()
        api.close()


@pytest.mark.asyncio
async def test_health_and_metrics_endpoints(tmp_path):
    api = seeded_api(tmp_path / "ledger.db")
    client = await _client(make_app(api=api))
    try:
        h = await client.get("/__health")
        assert h.status == 200
        hj = await h.json()
        assert hj["ok"] is True and "counts" in hj

        mj = await (await client.get("/__metrics")).json()
        assert "latency_ms_p95" in mj and "by_route" in mj
        assert set(mj) & {"signals_emitted", "alerts_pushed", "quant_opportunity_score"} == set()
    finally:
        await client.close()
        api.close()


@pytest.mark.asyncio
async def test_unknown_route_is_404_not_500_and_no_stack_trace(tmp_path):
    api = seeded_api(tmp_path / "ledger.db")
    client = await _client(make_app(api=api))
    try:
        r = await client.get("/totally/unknown")
        assert r.status == 404
        body = await r.text()
        assert "Traceback" not in body and 'File "' not in body
        assert "Page not found." in body
    finally:
        await client.close()
        api.close()


@pytest.mark.asyncio
async def test_api_json_carries_disclaimer(tmp_path):
    api = seeded_api(tmp_path / "ledger.db")
    client = await _client(make_app(api=api))
    try:
        j = await (await client.get("/api/today")).json()
        assert "disclaimer" in j and "no prediction" in j["disclaimer"].lower()
    finally:
        await client.close()
        api.close()


@pytest.mark.asyncio
async def test_all_routes_are_get_only(tmp_path):
    api = seeded_api(tmp_path / "ledger.db")
    client = await _client(make_app(api=api))
    try:
        for method in ("POST", "PUT", "DELETE", "PATCH"):
            r = await client.request(method, "/")
            assert r.status in (403, 405), (method, r.status)
    finally:
        await client.close()
        api.close()
