"""Task 83 §3 -- the browser dashboard's three additive read-only views.

TEST_FIXTURE_ONLY -- NOT ALPHA EVIDENCE. aiohttp's in-process TestServer
(loopback only); the Redis-backed consumer/broadcaster tasks are never
started -- only the new route handlers are exercised.
"""

from __future__ import annotations

import json

import pytest
from aiohttp.test_utils import TestClient, TestServer

import dashboard_web
from talonx_compare.config import CompareConfig
from talonx_compare.collector import ComparisonCollector
from talonx_compare.testing import make_pair, write_piv_state

DATE = "2026-08-28"
SESSION = "piv_2026-08-28_100000_abcd1234"


async def _client(app):
    server = TestServer(app)
    client = TestClient(server)
    await client.start_server()
    return client


@pytest.mark.asyncio
async def test_routes_present(tmp_path):
    app = dashboard_web.build_app(piv_state_dir=tmp_path)
    paths = {r.get_info().get("path") for r in app.router.routes() if "path" in r.get_info()}
    assert {"/views/original", "/views/piv", "/views/compare"} <= paths


@pytest.mark.asyncio
async def test_all_routes_are_get_only(tmp_path):
    app = dashboard_web.build_app(piv_state_dir=tmp_path)
    methods = {}
    for r in app.router.routes():
        info = r.get_info()
        p = info.get("path") or info.get("prefix")
        methods.setdefault(p, set()).add(r.method)
    for p, ms in methods.items():
        assert ms <= {"GET", "HEAD"}, f"{p} exposes non-GET methods: {ms}"


@pytest.mark.asyncio
async def test_no_mutating_endpoints(tmp_path):
    """No route path hints at launch / order / auth / kill / settings."""
    app = dashboard_web.build_app(piv_state_dir=tmp_path)
    banned = ("start", "launch", "order", "submit", "auth", "approve", "kill",
              "enable", "disable", "settings", "config", "shutdown", "activate")
    for r in app.router.routes():
        info = r.get_info()
        p = (info.get("path") or info.get("prefix") or "").lower()
        assert not any(b in p for b in banned), p


@pytest.mark.asyncio
async def test_piv_view_sections(tmp_path):
    write_piv_state(
        tmp_path,
        freshness={"provider_state": "HEALTHY", "symbols": {"AAPL": "FRESH"},
                   "coverage": {"AAPL": {"coverage_ratio": 0.8}}},
        readiness={"session_date": DATE, "finalized": {"AAPL": {"status": "READY"}}},
        reconciliation={"complete": True, "consistent": True},
        eod={"status": "PASSED", "trading_date_et": DATE},
    )
    client = await _client(dashboard_web.build_app(piv_state_dir=tmp_path))
    try:
        body = await (await client.get("/views/piv")).json()
    finally:
        await client.close()
    assert body["strategy_approval_status"] == "UNVALIDATED"
    assert body["profitability"] == "UNDETERMINED"
    assert body["execution_mode"] in ("SHADOW", "PAPER")
    assert body["real_capital_prohibited"] is True
    for key in ("provider_state", "per_symbol_readiness", "per_symbol_freshness",
                "quant_funnel", "decisions", "shadow", "paper_lifecycle",
                "reconciliation", "eod", "capability_limitations", "unresolved_questions"):
        assert key in body, key
    # QuantStateStore limitation surfaced
    assert body["capability_limitations"][0]["state"] == "NOT_IMPLEMENTED"
    assert body["capability_limitations"][0]["persistence_exists"] is False
    # IEX question surfaced, unresolved
    assert body["unresolved_questions"][0]["state"] == "UNRESOLVED"
    # P&L streams kept apart
    assert body["shadow"]["execution_class"] == "PIV_SHADOW"
    assert body["paper_lifecycle"]["execution_class"] == "PIV_PAPER"


@pytest.mark.asyncio
async def test_piv_view_missing_source_is_not_zero(tmp_path):
    # completely empty state dir
    client = await _client(dashboard_web.build_app(piv_state_dir=tmp_path))
    try:
        body = await (await client.get("/views/piv")).json()
    finally:
        await client.close()
    assert body["identity"]["health"]["state"] == "MISSING"
    assert body["identity"]["health"]["trustworthy_zero"] is False
    assert body["decisions"]["total"] == 0
    # ...but the decisions health makes clear that 0 is NOT_RUN, not a real zero
    assert body["decisions"]["health"]["state"] in ("NOT_RUN", "MISSING")


@pytest.mark.asyncio
async def test_original_view_sections(tmp_path, monkeypatch):
    original, _ = make_pair()
    for module, counter, val in [("ingest", "bars_read", 100), ("quant", "evaluated", 40),
                                 ("brain", "received", 10), ("core", "action_bullish", 3),
                                 ("dispatch", "pushed_telegram", 2)]:
        original.seed_metric("2026-08-28", module, counter, val)

    import redis as _redis
    monkeypatch.setattr(_redis, "from_url", lambda *a, **k: original)

    from datetime import datetime, timezone
    import talonx_compare.dashboard_views as dv
    monkeypatch.setattr(dv, "_utcnow", lambda: datetime(2026, 8, 28, 15, 0, tzinfo=timezone.utc))

    client = await _client(dashboard_web.build_app(piv_state_dir=tmp_path))
    try:
        body = await (await client.get("/views/original")).json()
    finally:
        await client.close()
    assert body["pipeline"] == "ORIGINAL"
    stages = {s["stage"] for s in body["lifecycle_stages"]}
    assert {"warmup", "quant", "brain", "core", "dispatch", "telegram"} == stages
    assert body["telegram"]["owner"] == "ORIGINAL"
    assert body["simulated_paper"]["execution_class"] == "SIMULATED_PAPER"
    assert "NEVER combined" in body["simulated_paper"]["note"]
    # each stage carries a health block + last-update / age fields
    for s in body["lifecycle_stages"]:
        assert "health" in s and "state" in s["health"]
        assert "age_seconds" in s["health"] and "last_update" in s["health"]


@pytest.mark.asyncio
async def test_not_run_is_not_zero_activity(tmp_path, monkeypatch):
    """Original never started: runtime metadata absent, Redis unreachable.
    The view must say NOT_RUN / DISCONNECTED, not present a zero funnel as
    fact."""
    from talonx_compare.testing import FakeRedis
    unreachable = FakeRedis(unreachable=True)
    import redis as _redis
    monkeypatch.setattr(_redis, "from_url", lambda *a, **k: unreachable)
    monkeypatch.setenv("TALONX_RUNTIME_METADATA_PATH", str(tmp_path / "nonexistent.json"))

    client = await _client(dashboard_web.build_app(piv_state_dir=tmp_path))
    try:
        body = await (await client.get("/views/original")).json()
    finally:
        await client.close()
    assert body["run_health"]["state"] == "NOT_RUN"
    assert body["redis_health"]["state"] == "DISCONNECTED"
    for s in body["lifecycle_stages"]:
        assert s["health"]["state"] in ("DISCONNECTED", "NOT_RUN", "UNREADABLE")
        assert s["health"]["trustworthy_zero"] is False


@pytest.mark.asyncio
async def test_compare_view_sections(tmp_path):
    piv = tmp_path / "piv"
    write_piv_state(piv)
    cfg = CompareConfig(state_dir=tmp_path / "cs", evidence_root=tmp_path / "ev", piv_state_dir=piv)
    ComparisonCollector(cfg).collect_once()

    app = dashboard_web.build_app(piv_state_dir=piv)
    app["compare_config"] = cfg
    client = await _client(app)
    try:
        body = await (await client.get("/views/compare")).json()
    finally:
        await client.close()
    assert body["pipeline"] == "COMPARE"
    for key in ("per_stage_totals", "per_symbol_stage", "divergence_by_class",
                "missing_or_late_stages", "diagnostics", "outcome_streams",
                "archive_integrity"):
        assert key in body, key
    assert body["operational_agreement_only"] is True
    assert "UNVALIDATED" in body["not_alpha_evidence"]
    # separate outcome streams
    streams = body["outcome_streams"]
    assert streams["original_simulated"] == "SIMULATED_PAPER"
    assert streams["piv_shadow"] == "PIV_SHADOW"
    assert streams["piv_paper"] == "PIV_PAPER"


@pytest.mark.asyncio
async def test_compare_view_not_run_when_no_evidence(tmp_path):
    cfg = CompareConfig(state_dir=tmp_path / "cs", evidence_root=tmp_path / "ev-empty",
                        piv_state_dir=tmp_path / "piv")
    app = dashboard_web.build_app(piv_state_dir=tmp_path)
    app["compare_config"] = cfg
    client = await _client(app)
    try:
        body = await (await client.get("/views/compare")).json()
    finally:
        await client.close()
    assert body["health"]["state"] == "NOT_RUN"
    assert body["trading_date"] is None


@pytest.mark.asyncio
async def test_index_html_has_the_three_view_tabs(tmp_path):
    client = await _client(dashboard_web.build_app(piv_state_dir=tmp_path))
    try:
        text = await (await client.get("/")).text()
    finally:
        await client.close()
    for marker in ('data-view="original"', 'data-view="piv"', 'data-view="compare"',
                   '"/views/" + view'):
        assert marker in text, marker
    # read-only affordance only -- no form/POST in the page
    assert 'method="post"' not in text.lower()


@pytest.mark.asyncio
async def test_existing_routes_unaffected(tmp_path):
    client = await _client(dashboard_web.build_app(piv_state_dir=tmp_path))
    try:
        assert (await client.get("/")).status == 200
        piv_status = await client.get("/piv/status")
        assert piv_status.status == 200
        body = await piv_status.json()
        assert "decisions" in body  # the Task 78I contract still holds
    finally:
        await client.close()


@pytest.mark.asyncio
async def test_timestamps_and_age_present(tmp_path):
    write_piv_state(tmp_path)
    client = await _client(dashboard_web.build_app(piv_state_dir=tmp_path))
    try:
        body = await (await client.get("/views/piv")).json()
    finally:
        await client.close()
    assert "as_of" in body
    # body["events"] IS a health block -- it carries the timestamp + age
    assert "age_seconds" in body["events"] and "last_update" in body["events"]
    assert "state" in body["events"]


@pytest.mark.asyncio
async def test_pnl_streams_separated(tmp_path):
    write_piv_state(tmp_path)
    client = await _client(dashboard_web.build_app(piv_state_dir=tmp_path))
    try:
        piv = await (await client.get("/views/piv")).json()
    finally:
        await client.close()
    # three distinct execution_class labels, three distinct "never combine" notes
    assert piv["shadow"]["execution_class"] != piv["paper_lifecycle"]["execution_class"]
    assert "NEVER combined" in piv["shadow"]["note"]
    assert "NEVER combined" in piv["paper_lifecycle"]["note"]
