"""Task 78I Stage 4 -- dashboard_web.py's new, additive /piv/status route.
TEST_FIXTURE_ONLY -- NOT ALPHA EVIDENCE. Uses aiohttp's own TestClient/
TestServer (loopback-only, in-process) -- no real network, no real Redis
(the Redis-backed consumer/broadcaster tasks are never started; only the
route handler under test is exercised directly via the test client)."""
from __future__ import annotations

import json

import pytest
from aiohttp.test_utils import TestClient, TestServer

import dashboard_web


def _write(path, data):
    path.write_text(json.dumps(data), encoding="utf-8")


@pytest.mark.asyncio
async def test_piv_status_route_returns_the_integrated_projection(tmp_path):
    _write(tmp_path / "session_identity.json", {"session_id": "s1", "trading_date_et": "2026-08-27"})
    _write(tmp_path / "decision_ledger.json", {
        "d1": {"session_id": "s1", "recommendation": "BUY", "reason_codes": [], "decision_execution_status": "ENTRY_ELIGIBLE"},
    })
    app = dashboard_web.build_app(piv_state_dir=tmp_path)
    server = TestServer(app)
    client = TestClient(server)
    await client.start_server()
    try:
        resp = await client.get("/piv/status")
        assert resp.status == 200
        body = await resp.json()
        assert body["scope"]["session_id"] == "s1"
        assert body["decisions"]["total"] == 1
    finally:
        await client.close()


@pytest.mark.asyncio
async def test_piv_status_route_on_empty_state_dir_returns_zero_counts_not_an_error(tmp_path):
    app = dashboard_web.build_app(piv_state_dir=tmp_path)
    server = TestServer(app)
    client = TestClient(server)
    await client.start_server()
    try:
        resp = await client.get("/piv/status")
        assert resp.status == 200
        body = await resp.json()
        assert body["decisions"]["total"] == 0
    finally:
        await client.close()


@pytest.mark.asyncio
async def test_piv_status_route_reports_read_failure_explicitly(tmp_path, monkeypatch):
    """A read failure must surface as an explicit error, never a
    silently-empty-looking success -- simulated here by monkeypatching
    build_integrated_projection to raise."""
    def _raise(*args, **kwargs):
        raise RuntimeError("simulated corrupt state file")

    monkeypatch.setattr(dashboard_web, "build_integrated_projection", _raise)
    app = dashboard_web.build_app(piv_state_dir=tmp_path)
    server = TestServer(app)
    client = TestClient(server)
    await client.start_server()
    try:
        resp = await client.get("/piv/status")
        assert resp.status == 500
        body = await resp.json()
        assert "PIV_STATUS_READ_FAILED" in body["error"]
    finally:
        await client.close()


@pytest.mark.asyncio
async def test_existing_routes_unaffected(tmp_path):
    """The new route must not disturb the existing `/` (static HTML) or
    `/static/*` routes -- confirmed by checking `/` still serves the
    existing index.html file, not a 404/500 introduced by this change."""
    app = dashboard_web.build_app(piv_state_dir=tmp_path)
    server = TestServer(app)
    client = TestClient(server)
    await client.start_server()
    try:
        resp = await client.get("/")
        assert resp.status == 200
        text = await resp.text()
        assert "<html" in text.lower() or "<!doctype" in text.lower()
    finally:
        await client.close()


def test_default_piv_state_dir_matches_pivconfig_own_default():
    from talonx_piv.config import PivConfig
    app = dashboard_web.build_app()  # no override -- must resolve to PivConfig()'s own default
    assert app["piv_state_dir"] == PivConfig().state_dir
