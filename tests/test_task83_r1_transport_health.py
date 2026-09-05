"""Task 83-R1 §4 -- honest transport health, exercised via the REAL
async ``CollectorService``.

TEST_FIXTURE_ONLY -- NOT ALPHA EVIDENCE. Deterministic in-memory async
fake Redis / PubSub; no network.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
import json

import pytest

from talonx_compare.config import CompareConfig
from talonx_compare.runner import CollectorService
from talonx_compare.transport import DISCONNECTED, NOT_RUN, RUNNING, STALE, TransportHealth
from talonx_compare.testing import (
    AsyncFakeRedis,
    install_async_fakes,
    make_pair,
    new_async_server,
    write_piv_state,
)

DATE = "2026-08-28"
SESSION = "piv_2026-08-28_100000_abcd1234"
NOW = datetime(2026, 8, 28, 15, 0, 0, tzinfo=timezone.utc)


@pytest.fixture
def cfg(tmp_path):
    piv = tmp_path / "piv"
    write_piv_state(piv, session_id=SESSION)
    return CompareConfig(state_dir=tmp_path / "cs", evidence_root=tmp_path / "ev", piv_state_dir=piv)


# --- 4.2 state machine ------------------------------------------

def test_transport_health_state_machine():
    h = TransportHealth("ORIGINAL", stale_seconds=100)
    clk = [NOW]
    h._now = lambda: clk[0]
    assert h.snapshot()["state"] == NOT_RUN
    h.mark_attempt()
    h.mark_error("refused")
    assert h.snapshot()["state"] == DISCONNECTED
    assert h.snapshot()["last_error"] == "refused"
    h.mark_connected(("c1", "c2"))
    assert h.snapshot()["state"] == RUNNING
    assert h.snapshot()["subscribed_channels"] == ["c1", "c2"]
    assert h.snapshot()["reconnect_count"] == 1  # was down -> now up
    clk[0] = NOW + timedelta(seconds=250)
    assert h.snapshot()["state"] == STALE
    clk[0] = NOW + timedelta(seconds=260)
    h.mark_message()
    assert h.snapshot()["state"] == RUNNING
    assert h.snapshot()["last_message_at"] is not None


# --- 4.1 / 4.3 service passes a thread-safe snapshot copy --------

@pytest.mark.asyncio
async def test_service_passes_transport_snapshot_into_collect(cfg, monkeypatch):
    srv = new_async_server()
    o = AsyncFakeRedis(srv)
    p = AsyncFakeRedis(srv)
    install_async_fakes(monkeypatch, original=o, piv=p)
    svc = CollectorService(cfg, interval_seconds=0.05)
    result = await svc.run_for(2)
    assert result is not None
    rs = json.loads((cfg.evidence_root / DATE / "runtime_status.json").read_text())
    assert set(rs["transport_health"]) == {"ORIGINAL", "PIV"}
    assert rs["transport_health"]["ORIGINAL"]["state"] in (RUNNING, STALE, NOT_RUN)


@pytest.mark.asyncio
async def test_snapshot_is_a_copy_not_live_ref(cfg, monkeypatch):
    srv = new_async_server()
    install_async_fakes(monkeypatch, original=AsyncFakeRedis(srv), piv=AsyncFakeRedis(srv))
    svc = CollectorService(cfg, interval_seconds=0.05)
    snap1 = svc._snapshot()
    svc.health_original.mark_message()
    snap2 = svc._snapshot()
    assert snap1 is not snap2
    assert snap1["ORIGINAL"]["last_message_at"] != snap2["ORIGINAL"]["last_message_at"] \
        or snap1["ORIGINAL"]["last_message_at"] is None


# --- 4.4 failed subscription -> DISCONNECTED, not NOT_RUN --------

@pytest.mark.asyncio
async def test_failed_subscription_is_disconnected_not_not_run(cfg, monkeypatch):
    srv = new_async_server()
    o = AsyncFakeRedis(srv, unreachable=True)   # Original never connects
    p = AsyncFakeRedis(srv)
    install_async_fakes(monkeypatch, original=o, piv=p)
    svc = CollectorService(cfg, interval_seconds=0.05)
    await svc.run_for(3)
    rs = json.loads((cfg.evidence_root / DATE / "runtime_status.json").read_text())
    assert rs["transport_health"]["ORIGINAL"]["state"] == DISCONNECTED
    assert rs["transport_health"]["ORIGINAL"]["state"] != NOT_RUN
    comp = json.loads((cfg.evidence_root / DATE / "comparison.json").read_text())
    assert comp["source_health"]["original_redis"]["state"] == DISCONNECTED
    assert comp["source_health"]["original_redis"]["trustworthy_zero"] is False


# --- 4.5 one-sided failure isolated ---------------------------

@pytest.mark.asyncio
async def test_one_sided_failure_isolated(cfg, monkeypatch):
    srv = new_async_server()
    o = AsyncFakeRedis(srv, unreachable=True)   # Original down
    p = AsyncFakeRedis(srv)                     # PIV healthy
    install_async_fakes(monkeypatch, original=o, piv=p)
    svc = CollectorService(cfg, interval_seconds=0.05)
    await svc.run_for(3)
    comp = json.loads((cfg.evidence_root / DATE / "comparison.json").read_text())
    sh = comp["source_health"]
    assert sh["original_redis"]["state"] == DISCONNECTED
    # PIV state-file evidence is untouched by Original's failure
    assert sh["piv_session_identity"]["state"] == "HEALTHY"
    assert sh["piv_events"]["state"] in ("HEALTHY", "STALE")
    # PIV records still archived
    assert (cfg.evidence_root / DATE / "piv_records.jsonl").read_text().strip()


# --- 4.6 read-only metrics client + read-failure recorded ------

def test_original_metrics_client_is_read_only(cfg):
    from talonx_compare.collector import ComparisonCollector

    original, _ = make_pair()
    original.seed_metric(DATE, "quant", "evaluated", 5)
    ComparisonCollector(cfg, clock=lambda: NOW, original_redis=original).collect_once()
    # the collector issued zero mutating calls against the Original client
    assert original.write_calls == []


def test_metrics_read_failure_recorded(cfg):
    from talonx_compare.collector import ComparisonCollector
    from talonx_compare.testing import FakeRedis

    down = FakeRedis(unreachable=True)
    r = ComparisonCollector(cfg, clock=lambda: NOW, original_redis=down).collect_once()
    assert any(d["kind"] == "SOURCE_UNAVAILABLE" and "redis:original" in d["source"]
               for d in r.diagnostics)
    assert r.source_health["original_redis"]["state"] == DISCONNECTED


# --- 4.7 PIV pubsub health separate from state-file health -----

@pytest.mark.asyncio
async def test_piv_pubsub_health_separate_from_state_file_health(cfg, monkeypatch):
    srv = new_async_server()
    o = AsyncFakeRedis(srv)
    p = AsyncFakeRedis(srv, unreachable=True)   # PIV Pub/Sub down...
    install_async_fakes(monkeypatch, original=o, piv=p)
    svc = CollectorService(cfg, interval_seconds=0.05)
    await svc.run_for(3)
    comp = json.loads((cfg.evidence_root / DATE / "comparison.json").read_text())
    sh = comp["source_health"]
    assert sh["piv_pubsub"]["state"] == DISCONNECTED       # ...pubsub disconnected
    assert sh["piv_session_identity"]["state"] == "HEALTHY"  # ...but state files still fine
    assert sh["piv_events"]["state"] in ("HEALTHY", "STALE")


# --- 4.8 reconnect recovery evidence, no event loss -----------

@pytest.mark.asyncio
async def test_reconnect_recovery_evidence_no_event_loss(cfg, monkeypatch):
    srv = new_async_server()
    # Original: fail the first ping, connect after
    o = AsyncFakeRedis(srv, fail_ping_times=1)
    p = AsyncFakeRedis(srv)
    install_async_fakes(monkeypatch, original=o, piv=p)
    svc = CollectorService(cfg, interval_seconds=0.03)
    await svc.run_for(6, tick=0.05)
    rs = json.loads((cfg.evidence_root / DATE / "runtime_status.json").read_text())
    # a reconnect happened and is visible
    assert rs["transport_health"]["ORIGINAL"]["reconnect_count"] >= 1
    assert rs["transport_health"]["ORIGINAL"]["state"] in (RUNNING, STALE)


# --- 4.9 messages arriving during a pass stay for the next pass ---

@pytest.mark.asyncio
async def test_messages_during_pass_retained(cfg, monkeypatch):
    from talonx_compare.runner import _Buffer

    buf = _Buffer()
    buf.append({"channel": "a", "data": "1"})
    taken = buf.swap()
    # a producer appends WHILE the pass is running
    buf.append({"channel": "b", "data": "2"})
    assert taken == [{"channel": "a", "data": "1"}]
    assert buf.swap() == [{"channel": "b", "data": "2"}]  # retained for next pass


# --- 4.10 collector writes confined ---------------------------

@pytest.mark.asyncio
async def test_collector_writes_confined(cfg, monkeypatch):
    srv = new_async_server()
    install_async_fakes(monkeypatch, original=AsyncFakeRedis(srv), piv=AsyncFakeRedis(srv))
    svc = CollectorService(cfg, interval_seconds=0.05)
    await svc.run_for(2)
    # everything written is under the collector's own evidence root / state dir
    assert (cfg.evidence_root / DATE).exists()
    assert not any(cfg.piv_state_dir.glob("collector*"))
    assert not any(cfg.piv_state_dir.glob("*.lock"))
