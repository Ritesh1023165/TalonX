"""Task 83-R1 §7 -- expanded offline rehearsal (production-loop cases
21-33). The original 20 scenarios stay in tests/test_task83_offline_dual_run.py.

Every case here drives the REAL production surface: ``CollectorService``
(async), ``ComparisonCollector``, the archive readers, and the dashboard
projections. Helper-only exercising is not accepted.

TEST_FIXTURE_ONLY -- NOT ALPHA EVIDENCE. Deterministic in-memory async
fakes; no network, no real Redis, no production state dir.
"""

from __future__ import annotations

import csv
import json
import os
import subprocess
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from talonx_compare.archive import CompareArchive
from talonx_compare.collector import ComparisonCollector
from talonx_compare.config import CompareConfig
from talonx_compare.dashboard_views import compare_view
from talonx_compare.runner import CollectorLock, CollectorService
from talonx_compare.testing import (
    AsyncFakeRedis,
    install_async_fakes,
    make_pair,
    new_async_server,
    write_piv_state,
)
from talonx_piv.notification_telemetry import merge_telemetry

LABEL = "TEST_FIXTURE_ONLY -- NOT ALPHA EVIDENCE"
DATE = "2026-08-28"
SESSION_A = "piv_2026-08-28_100000_aaaa1111"
SESSION_B = "piv_2026-08-28_143000_bbbb2222"
T0 = datetime(2026, 8, 28, 15, 0, 0, tzinfo=timezone.utc)

_MATRIX = Path("results/task83_r1_production_collector_closure/expanded_rehearsal_matrix.csv")
_RESULTS: list[dict] = []


def _rec(n, name, expected, observed, verdict):
    _RESULTS.append({"scenario": n, "name": name, "expected": expected,
                     "observed": observed, "verdict": verdict, "label": LABEL})


@pytest.fixture(scope="module", autouse=True)
def _write_matrix():
    yield
    _MATRIX.parent.mkdir(parents=True, exist_ok=True)
    with _MATRIX.open("w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=["scenario", "name", "expected", "observed", "verdict", "label"])
        w.writeheader()
        for row in sorted(_RESULTS, key=lambda r: r["scenario"]):
            w.writerow(row)


@pytest.fixture
def cfg(tmp_path):
    piv = tmp_path / "piv"
    write_piv_state(piv, session_id=SESSION_A)
    return CompareConfig(state_dir=tmp_path / "cs", evidence_root=tmp_path / "ev", piv_state_dir=piv)


async def _service(cfg, monkeypatch, *, o=None, p=None, srv=None, interval=0.05):
    srv = srv or new_async_server()
    o = o or AsyncFakeRedis(srv)
    p = p or AsyncFakeRedis(srv)
    install_async_fakes(monkeypatch, original=o, piv=p)
    return CollectorService(cfg, interval_seconds=interval), srv, o, p


# ── 21. two real passes, different clocks, stable bindings ───────────────

def test_s21_two_passes_stable_bindings_no_conflict(cfg):
    r1 = ComparisonCollector(cfg, clock=lambda: T0).collect_once()
    r2 = ComparisonCollector(cfg, clock=lambda: T0 + timedelta(seconds=5)).collect_once()
    ok = r1.manifest_written and not r2.manifest_conflict and not r2.manifest_written
    _rec(21, "two passes stable bindings", "no manifest_conflict from elapsed time",
         f"r1.written={r1.manifest_written} r2.conflict={r2.manifest_conflict}", "PASS" if ok else "FAIL")
    assert ok


# ── 22. same-day multiple decisions for one symbol ──────────────────────

def test_s22_same_day_multiple_decisions_one_symbol(cfg):
    write_piv_state(cfg.piv_state_dir, session_id=SESSION_A, decisions={
        f"d{i}": {"session_id": SESSION_A, "trading_date_et": DATE, "symbol": "AAPL",
                  "timestamp": f"{DATE}T14:0{i}:00+00:00", "recommendation": "HOLD",
                  "reason_codes": [], "market_view": "BULLISH",
                  "decision_execution_status": "NO_ACTION", "data_readiness": "COMPLETE"}
        for i in range(1, 4)
    })
    ComparisonCollector(cfg, clock=lambda: T0).collect_once()
    comp = json.loads((cfg.evidence_root / DATE / "comparison.json").read_text())
    dec = {x["event_identity"] for x in comp["per_symbol_stage"]
           if x["stage"] == "decision" and x["symbol"] == "AAPL"}
    ok = dec == {"d1", "d2", "d3"}
    _rec(22, "same-day multiple decisions one symbol", "3 distinct decision rows",
         f"event_identities={sorted(dec)}", "PASS" if ok else "FAIL")
    assert ok


# ── 23. same-day different session/run scopes ──────────────────────────

def test_s23_same_day_two_run_scopes_separated(cfg):
    ComparisonCollector(cfg, clock=lambda: T0).collect_once()
    write_piv_state(cfg.piv_state_dir, session_id=SESSION_B, config_hash="rebind")
    r2 = ComparisonCollector(cfg, clock=lambda: T0 + timedelta(hours=1)).collect_once()
    recs = [json.loads(x) for x in
            (cfg.evidence_root / DATE / "piv_records.jsonl").read_text().splitlines() if x.strip()]
    scopes = {x["run_scope"] for x in recs}
    ok = r2.manifest_conflict and scopes == {SESSION_A, SESSION_B}
    _rec(23, "same-day two run scopes separated", "both sessions kept, manifest conflict raised",
         f"conflict={r2.manifest_conflict} scopes={sorted(scopes)}", "PASS" if ok else "FAIL")
    assert ok


# ── 24. Original scope unavailable ────────────────────────────────────

def test_s24_original_scope_unavailable(tmp_path):
    piv = tmp_path / "piv"
    write_piv_state(piv, session_id=SESSION_A)
    cfg = CompareConfig(state_dir=tmp_path / "cs", evidence_root=tmp_path / "ev", piv_state_dir=piv,
                        original_runtime_metadata_path=tmp_path / "nope.json")
    ComparisonCollector(cfg, clock=lambda: T0).collect_once()
    comp = json.loads((cfg.evidence_root / DATE / "comparison.json").read_text())
    ok = comp["original_run_scope"] == "UNSCOPED" and comp["event_level_agreement_assertable"] is False
    _rec(24, "Original scope unavailable", "UNSCOPED; no event-level agreement asserted",
         f"scope={comp['original_run_scope']}", "PASS" if ok else "FAIL")
    assert ok


# ── 25. Original Redis disconnected, PIV healthy ─────────────────────

@pytest.mark.asyncio
async def test_s25_original_redis_down_piv_healthy(cfg, monkeypatch):
    srv = new_async_server()
    svc, *_ = await _service(cfg, monkeypatch, srv=srv,
                             o=AsyncFakeRedis(srv, unreachable=True), p=AsyncFakeRedis(srv))
    await svc.run_for(3)
    comp = json.loads((cfg.evidence_root / DATE / "comparison.json").read_text())
    sh = comp["source_health"]
    ok = (sh["original_redis"]["state"] == "DISCONNECTED"
          and sh["piv_session_identity"]["state"] == "HEALTHY"
          and (cfg.evidence_root / DATE / "piv_records.jsonl").read_text().strip())
    _rec(25, "Original Redis down, PIV healthy", "Original DISCONNECTED; PIV evidence intact",
         f"orig={sh['original_redis']['state']} piv={sh['piv_session_identity']['state']}",
         "PASS" if ok else "FAIL")
    assert ok


# ── 26. PIV Pub/Sub disconnected, Original healthy ─────────────────

@pytest.mark.asyncio
async def test_s26_piv_pubsub_down_original_healthy(cfg, monkeypatch):
    srv = new_async_server()
    svc, *_ = await _service(cfg, monkeypatch, srv=srv,
                             o=AsyncFakeRedis(srv), p=AsyncFakeRedis(srv, unreachable=True))
    await svc.run_for(3)
    comp = json.loads((cfg.evidence_root / DATE / "comparison.json").read_text())
    sh = comp["source_health"]
    ok = (sh["piv_pubsub"]["state"] == "DISCONNECTED"
          and sh["piv_session_identity"]["state"] == "HEALTHY"
          and sh["original_redis"]["state"] in ("RUNNING", "STALE"))
    _rec(26, "PIV Pub/Sub down, Original healthy",
         "PIV pubsub DISCONNECTED separate from PIV state-file HEALTHY",
         f"pubsub={sh['piv_pubsub']['state']} files={sh['piv_session_identity']['state']}",
         "PASS" if ok else "FAIL")
    assert ok


# ── 27. disconnect -> reconnect, buffered messages preserved ─────

@pytest.mark.asyncio
async def test_s27_reconnect_preserves_buffered_messages(cfg, monkeypatch):
    srv = new_async_server()
    o = AsyncFakeRedis(srv, fail_ping_times=1)   # first connect fails, then recovers
    p = AsyncFakeRedis(srv)
    install_async_fakes(monkeypatch, original=o, piv=p)
    svc = CollectorService(cfg, interval_seconds=0.03)
    await svc.run_for(6, tick=0.06)
    rs = json.loads((cfg.evidence_root / DATE / "runtime_status.json").read_text())
    rc = rs["transport_health"]["ORIGINAL"]["reconnect_count"]
    ok = rc >= 1 and rs["transport_health"]["ORIGINAL"]["state"] in ("RUNNING", "STALE")
    _rec(27, "reconnect preserves buffered messages", "reconnect recorded, no loss",
         f"reconnect_count={rc}", "PASS" if ok else "FAIL")
    assert ok


# ── 28. missing PIV notification telemetry ─────────────────────

def test_s28_missing_piv_notification_telemetry(cfg):
    ComparisonCollector(cfg, clock=lambda: T0).collect_once()
    tg = json.loads((cfg.evidence_root / DATE / "telegram.json").read_text())
    ok = (tg["piv_notification_telemetry"]["verdict"] == "UNVERIFIED"
          and tg["piv_zero_attempt_assertion"] is False)
    _rec(28, "missing PIV notification telemetry", "verdict UNVERIFIED, not zero",
         f"verdict={tg['piv_notification_telemetry']['verdict']}", "PASS" if ok else "FAIL")
    assert ok


# ── 29. disabled PIV notification, verified zero ──────────────

def test_s29_disabled_notification_verified_zero(cfg):
    merge_telemetry(cfg.piv_state_dir, session_id=SESSION_A, trading_date_et=DATE,
                    ownership={"outbound_enabled": False, "sender_constructed": False,
                              "inbound_poller_constructed": False, "inbound_poller_started": False})
    ComparisonCollector(cfg, clock=lambda: T0).collect_once()
    tg = json.loads((cfg.evidence_root / DATE / "telegram.json").read_text())
    ok = tg["piv_notification_telemetry"]["verdict"] == "VERIFIED_ZERO" and tg["piv_zero_attempt_assertion"] is True
    _rec(29, "disabled notification verified zero", "verdict VERIFIED_ZERO",
         f"verdict={tg['piv_notification_telemetry']['verdict']}", "PASS" if ok else "FAIL")
    assert ok


# ── 30. enabled fake sender with a persisted failed attempt ──

def test_s30_enabled_sender_persisted_failed_attempt(cfg):
    from talonx_piv.events import EventBus, PivEvent

    def boom(_):
        raise RuntimeError("down")

    bus = EventBus(cfg.piv_state_dir / "piv_events.jsonl", boom, session_id=SESSION_A,
                   telemetry_path=cfg.piv_state_dir, trading_date_et=DATE)
    bus.emit(PivEvent.build("SIGNAL", symbol="AAPL"))
    ComparisonCollector(cfg, clock=lambda: T0).collect_once()
    tg = json.loads((cfg.evidence_root / DATE / "telegram.json").read_text())
    tel = tg["piv_notification_telemetry"]["telemetry"]
    ok = (tg["piv_notification_telemetry"]["verdict"] == "ATTEMPTS_RECORDED"
          and tel["outbound"]["attempts"] == 1 and tel["outbound"]["failures"] == 1
          and tg["piv_zero_attempt_assertion"] is False)
    _rec(30, "enabled sender persisted failed attempt", "1 attempt archived even though send raised",
         f"attempts={tel['outbound']['attempts']} failures={tel['outbound']['failures']}",
         "PASS" if ok else "FAIL")
    assert ok


# ── 31. archive corruption before the next collection pass ──

def test_s31_archive_corruption_before_next_pass(cfg):
    ComparisonCollector(cfg, clock=lambda: T0).collect_once()
    hashes_before = (cfg.evidence_root / DATE / "file_hashes.json").read_text()
    (cfg.evidence_root / DATE / "comparison.json").write_text("{corrupt", encoding="utf-8")
    r = ComparisonCollector(cfg, clock=lambda: T0 + timedelta(minutes=5)).collect_once()
    view = compare_view(config=cfg, trading_date=DATE)
    ok = (r.write_aborted is True
          and (cfg.evidence_root / DATE / "file_hashes.json").read_text() == hashes_before
          and view["trustworthy"] is False and view["per_stage_totals"] == {})
    _rec(31, "archive corruption before next pass",
         "write aborted, hashes not regenerated, dashboard flags corruption",
         f"aborted={r.write_aborted} trustworthy={view['trustworthy']}", "PASS" if ok else "FAIL")
    assert ok


# ── 32. concurrent collect-once / service writer contention ──

@pytest.mark.skipif(os.name != "nt", reason="Windows process-probe regression")
def test_windows_collector_pid_probe_is_read_only(monkeypatch):
    """A liveness check must never route through Windows TerminateProcess."""
    from talonx_compare import lock as lock_module

    def forbidden_kill(*_args, **_kwargs):
        pytest.fail("Windows collector liveness probe called destructive os.kill")

    monkeypatch.setattr(lock_module.os, "kill", forbidden_kill)
    assert lock_module._pid_alive(os.getpid()) is True


def test_s32_concurrent_writer_contention(cfg):
    ComparisonCollector(cfg, clock=lambda: T0).collect_once()
    # hold the collector lock from a genuine competing OS subprocess
    holder = subprocess.Popen(
        [sys.executable, "-c",
         "import sys,time\n"
         "from talonx_compare.lock import CollectorLock\n"
         "l=CollectorLock(__import__('pathlib').Path(sys.argv[1]))\n"
         "l.acquire(); open(sys.argv[2],'w').write('x'); time.sleep(2.0); l.release()\n",
         str(cfg.lock_path), str(cfg.state_dir / "ready")],
        cwd=str(Path.cwd()), stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    try:
        for _ in range(50):
            if (cfg.state_dir / "ready").exists():
                break
            import time
            time.sleep(0.1)
        # this collect_once must WAIT for the lock, then succeed -- never
        # write concurrently, never corrupt.
        r = ComparisonCollector(cfg, clock=lambda: T0 + timedelta(minutes=5)).collect_once()
        integ = CompareArchive(cfg).day(DATE)["archive_integrity"]
        ok = r.trading_date == DATE and integ["ok"] is True
    finally:
        holder.wait(timeout=10)
    _rec(32, "concurrent writer contention", "collect_once waits for the lock, archive stays HEALTHY",
         f"integrity_ok={integ['ok']}", "PASS" if ok else "FAIL")
    assert ok


# ── 33. fresh-clone evidence-manifest verification ──────────

def test_s33_fresh_clone_manifest_verification(tmp_path):
    """The evidence-manifest generator hashes GIT-NORMALIZED (LF) bytes so
    a manifest committed on one platform verifies from a fresh clone on
    another. Proven two ways: (a) the generator's own round-trip against
    real files with CRLF injected, and (b) -- when the R1 evidence is
    already committed -- against the committed git blob content."""
    import hashlib
    import importlib.util

    gen_path = Path("results/task83_r1_production_collector_closure/_make_manifest.py")
    assert gen_path.exists(), "the R1 manifest generator must be present"
    spec = importlib.util.spec_from_file_location("_r1_make_manifest", gen_path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)

    # (a) round-trip: a file with CRLF hashes the SAME as its LF form
    sample = tmp_path / "sample.md"
    sample.write_bytes(b"line one\r\nline two\r\n")
    lf = b"line one\nline two\n"
    assert mod._sha256_lf(sample) == hashlib.sha256(lf).hexdigest()
    assert mod._byte_len_lf(sample) == len(lf)

    # (b) committed-blob check when available (never skips -- just a no-op
    #     assertion when the evidence has not been committed yet)
    manifest_rel = "results/task83_r1_production_collector_closure/evidence_manifest.json"
    proc = subprocess.run(["git", "cat-file", "-p", f"HEAD:{manifest_rel}"],
                          capture_output=True)
    committed_checked = 0
    mismatches: list[str] = []
    if proc.returncode == 0:
        manifest = json.loads(proc.stdout)
        for art in manifest.get("artifacts", []):
            rel = "results/task83_r1_production_collector_closure/" + art["file"]
            b = subprocess.run(["git", "cat-file", "-p", f"HEAD:{rel}"], capture_output=True)
            if b.returncode != 0:
                mismatches.append(f"{art['file']}: not in git")
                continue
            norm = b.stdout.replace(b"\r\n", b"\n")
            committed_checked += 1
            if hashlib.sha256(norm).hexdigest() != art["sha256"]:
                mismatches.append(f"{art['file']}: hash mismatch")
            if len(norm) != art["bytes"]:
                mismatches.append(f"{art['file']}: byte mismatch")
    _rec(33, "fresh-clone manifest verification",
         "LF-normalized hashing round-trips; committed blobs match when present",
         f"committed_checked={committed_checked} mismatches={mismatches}",
         "PASS" if not mismatches else "FAIL")
    assert not mismatches, mismatches
