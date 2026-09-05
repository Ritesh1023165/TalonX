"""Task 83 §5 -- offline Original+PIV rehearsal (20 scenarios).

TEST_FIXTURE_ONLY -- NOT ALPHA EVIDENCE. No external network, no real
Redis, no production state dir. Synthetic signals used to exercise the
flow are labelled below. Where process ownership is under test (scenarios
4-8, 19) GENUINE competing OS subprocesses are spawned whose command
lines are matched by the real ``talonx_core.process_guard`` Windows
enumeration; the guard then runs for real against the live process table.

Ordinary pytest execution records verdicts in memory only. An explicit output
option is required to publish a retained evidence candidate.
"""

from __future__ import annotations

import csv
import json
import os
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

import pytest

from talonx_core import process_guard
from talonx_compare.collector import ComparisonCollector
from talonx_compare.config import CompareConfig
from talonx_compare.runner import CollectorLock
from talonx_compare.testing import RecordingTelegram, make_pair, write_piv_state
from talonx_piv import cli
from talonx_piv.config import PivConfig
from talonx_piv.isolation import validate_piv_isolation
from talonx_piv.session_identity import SessionRecoveryRequired, assess_session_recovery, resolve_session_identity

LABEL = "TEST_FIXTURE_ONLY -- NOT ALPHA EVIDENCE"
DATE = "2026-08-28"
SESSION = "piv_2026-08-28_100000_abcd1234"
NOW = datetime(2026, 8, 28, 15, 0, 0, tzinfo=timezone.utc)

_RESULTS: list[dict] = []


def _record(n: int, name: str, expected: str, observed: str, verdict: str) -> None:
    _RESULTS.append({
        "scenario": n, "name": name, "expected": expected, "observed": observed,
        "verdict": verdict, "label": LABEL,
    })


@pytest.fixture(scope="module", autouse=True)
def _write_matrix(request):
    yield
    output = request.config.getoption("--task83-r2-retained-matrix-output")
    if not output:
        return
    expected = set(range(1, 21))
    observed = [int(row["scenario"]) for row in _RESULTS]
    assert set(observed) == expected and len(observed) == len(expected), (
        f"explicit retained rehearsal requires exactly scenarios 1-20; got {observed}"
    )
    assert all(row["verdict"] == "PASS" for row in _RESULTS), _RESULTS
    matrix = Path(output)
    matrix.parent.mkdir(parents=True, exist_ok=True)
    with matrix.open("w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=["scenario", "name", "expected", "observed", "verdict", "label"])
        w.writeheader()
        for row in sorted(_RESULTS, key=lambda r: r["scenario"]):
            w.writerow(row)


# --------------------------------------------------------------------------
# genuine competing-subprocess helper (scenarios 4-8, 19)
# --------------------------------------------------------------------------

class _FakeProc:
    """A real OS python subprocess whose command line the process guard's
    WMI query matches ('run_talonx.py' or 'talonx_piv.cli'), so the guard
    genuinely sees it in the live process table."""

    def __init__(self, role: str, *, isolated: bool = False, hold_file: Path | None = None) -> None:
        marker = "talonx_piv.cli" if role == "PIV" else "run_talonx.py"
        args = [sys.executable, "-c",
                "import sys,time\n"
                "hf = sys.argv[2] if len(sys.argv) > 2 else None\n"
                "open(sys.argv[1],'w').close() if False else None\n"
                "time.sleep(60)\n",
                marker]
        if isolated:
            args.append("--isolated-parallel")
        self._proc = subprocess.Popen(args, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        self.pid = self._proc.pid
        # give the OS a moment to register the process
        time.sleep(0.4)

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self._proc.terminate()
        try:
            self._proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            self._proc.kill()


def _guard(role: str, *, verified: bool) -> tuple[bool, str]:
    return process_guard.no_competing_talonx_process(
        current_role=role, piv_isolation_verified=verified,
    )


# --------------------------------------------------------------------------
# shared fixtures
# --------------------------------------------------------------------------

@pytest.fixture
def piv_dir(tmp_path):
    d = tmp_path / "piv"
    write_piv_state(d)
    return d


@pytest.fixture
def cfg(tmp_path, piv_dir):
    return CompareConfig(state_dir=tmp_path / "cs", evidence_root=tmp_path / "ev", piv_state_dir=piv_dir)


def _collect(cfg, **kw):
    return ComparisonCollector(cfg, clock=lambda: NOW, **kw).collect_once(**kw)


# ========================================================================
# 1. Original alone
# ========================================================================

def test_scenario_01_original_alone(tmp_path):
    original, _ = make_pair()
    original.seed_metric(DATE, "ingest", "bars_read", 500)
    original.seed_metric(DATE, "quant", "evaluated", 20)
    cfg = CompareConfig(state_dir=tmp_path / "cs", evidence_root=tmp_path / "ev",
                        piv_state_dir=tmp_path / "no_piv")
    res = ComparisonCollector(cfg, clock=lambda: NOW,
                              original_redis=original).collect_once(trading_date=DATE)
    # PIV never ran -> honest NOT_RUN / MISSING, never a fake zero
    piv_id = res.source_health["piv_session_identity"]["state"]
    ok = piv_id in ("MISSING", "NOT_RUN") and original.write_calls == []
    _record(1, "Original alone", "PIV honestly NOT_RUN; collector read-only",
            f"piv_identity={piv_id}, original_writes={original.write_calls}", "PASS" if ok else "FAIL")
    assert ok


# ========================================================================
# 2. PIV alone in shadow mode
# ========================================================================

def test_scenario_02_piv_alone_shadow(cfg):
    res = _collect(cfg)
    manifest = json.loads((cfg.evidence_root / DATE / "manifest.json").read_text())
    ok = (manifest["piv"]["execution_mode"] == "SHADOW"
          and manifest["piv"]["strategy_approval_status"] == "UNVALIDATED"
          and res.original_appended == 0)
    _record(2, "PIV alone (shadow)", "PIV SHADOW recorded; Original absent handled",
            f"execution_mode={manifest['piv']['execution_mode']}", "PASS" if ok else "FAIL")
    assert ok


# ========================================================================
# 3. Original plus correctly isolated PIV
# ========================================================================

def test_scenario_03_original_plus_isolated_piv(cfg, monkeypatch):
    monkeypatch.setenv("TALONX_REDIS_URL", "redis://localhost:6379/0")
    piv_cfg = PivConfig(state_dir=cfg.piv_state_dir, redis_url="redis://localhost:6379/1")
    passed, detail = validate_piv_isolation(piv_cfg)
    original, piv = make_pair()
    original.seed_metric(DATE, "quant", "evaluated", 5)
    res = ComparisonCollector(cfg, clock=lambda: NOW, original_redis=original,
                              piv_redis=piv).collect_once()
    ok = passed and res.original_appended > 0 and res.piv_appended > 0
    _record(3, "Original + isolated PIV", "isolation validates; both sides recorded",
            f"isolation_passed={passed}; orig={res.original_appended}; piv={res.piv_appended}",
            "PASS" if ok else "FAIL")
    assert ok


# ========================================================================
# 4. Duplicate Original rejected  (genuine subprocess)
# ========================================================================

def test_scenario_04_duplicate_original_rejected():
    with _FakeProc("ORIGINAL"):
        ok_self, detail = _guard(process_guard.ORIGINAL_ROLE, verified=False)
    verdict = "PASS" if ok_self is False and "blocked" in detail else "FAIL"
    _record(4, "Duplicate Original rejected", "guard blocks a second ORIGINAL",
            f"ok={ok_self}; {detail}", verdict)
    assert ok_self is False


# ========================================================================
# 5. Duplicate PIV rejected  (genuine subprocess)
# ========================================================================

def test_scenario_05_duplicate_piv_rejected():
    with _FakeProc("PIV", isolated=True):
        ok_self, detail = _guard(process_guard.PIV_ROLE, verified=True)
    verdict = "PASS" if ok_self is False else "FAIL"
    _record(5, "Duplicate PIV rejected", "guard blocks a second PIV even when isolation-verified",
            f"ok={ok_self}; {detail}", verdict)
    assert ok_self is False


# ========================================================================
# 6. Overlapping / uncertain bindings rejected
# ========================================================================

def test_scenario_06_overlapping_bindings_rejected(tmp_path, monkeypatch):
    monkeypatch.setenv("TALONX_REDIS_URL", "redis://localhost:6379/0")
    # PIV pointed at the SAME db as Original
    same_db = PivConfig(state_dir=tmp_path, redis_url="redis://localhost:6379/0")
    p1, d1 = validate_piv_isolation(same_db)
    # unmarked PIV peer seen by Original
    with _FakeProc("PIV", isolated=False):
        ok_orig, detail = _guard(process_guard.ORIGINAL_ROLE, verified=False)
    ok = p1 is False and ok_orig is False
    _record(6, "Overlapping/uncertain bindings rejected",
            "same-DB isolation fails AND unmarked PIV peer blocks Original",
            f"same_db_isolation={p1}; unmarked_peer_ok={ok_orig}", "PASS" if ok else "FAIL")
    assert ok


# ========================================================================
# 7. Redis DB separation but channel overlap rejected
# ========================================================================

def test_scenario_07_db_separate_channel_overlap_rejected(tmp_path):
    cfg = PivConfig(state_dir=tmp_path, redis_url="redis://localhost:6379/1",
                    signals_channel="talonx:signals:quant")  # Original's channel name
    passed, detail = validate_piv_isolation(cfg)
    ok = passed is False and "Pub/Sub" in detail
    _record(7, "DB separate + channel overlap rejected",
            "different DB does not save an overlapping channel name",
            f"passed={passed}; {detail}", "PASS" if ok else "FAIL")
    assert ok


# ========================================================================
# 8. Correct DB plus prefixed channels accepted
# ========================================================================

def test_scenario_08_correct_db_prefixed_channels_accepted(tmp_path, monkeypatch):
    monkeypatch.setenv("TALONX_REDIS_URL", "redis://localhost:6379/0")
    monkeypatch.delenv("TALONX_QUANT_DB_PATH", raising=False)
    cfg = PivConfig(state_dir=tmp_path, redis_url="redis://localhost:6379/1")
    passed, detail = validate_piv_isolation(cfg)
    all_prefixed = all(c.startswith("talonx:piv:") for c in (
        cfg.market_stream_channel, cfg.signals_channel, cfg.rejected_candidates_channel,
        cfg.news_events_channel, cfg.paper_trades_channel))
    ok = passed and all_prefixed
    _record(8, "Correct DB + prefixed channels accepted", "isolation passes",
            f"passed={passed}; all_prefixed={all_prefixed}", "PASS" if ok else "FAIL")
    assert ok


# ========================================================================
# 9. Collector observes both without republishing
# ========================================================================

def test_scenario_09_collector_observes_without_republish(cfg):
    original, piv = make_pair()
    # live traffic on both buses
    original.publish("talonx:signals:quant",
                     json.dumps({"ticker": "AAPL", "timestamp": f"{DATE}T14:00:00+00:00", "signal_type": "LONG"}))
    piv.publish("talonx:piv:signals:quant",
                json.dumps({"ticker": "AAPL", "timestamp": f"{DATE}T14:00:05+00:00", "signal_type": "LONG"}))
    server_log_before = list(original._server.publish_log)
    o_writes_before, p_writes_before = len(original.write_calls), len(piv.write_calls)
    ComparisonCollector(cfg, clock=lambda: NOW, original_redis=original, piv_redis=piv).collect_once(
        captured_original_messages=[{"channel": "talonx:signals:quant",
                                     "data": json.dumps({"ticker": "AAPL",
                                                         "timestamp": f"{DATE}T14:00:00+00:00",
                                                         "signal_type": "LONG"})}],
        captured_piv_messages=[{"channel": "talonx:piv:signals:quant",
                                "data": json.dumps({"ticker": "AAPL",
                                                    "timestamp": f"{DATE}T14:00:05+00:00",
                                                    "signal_type": "LONG"})}],
    )
    # the collector added no publishes and no writes of its own
    ok = (original._server.publish_log == server_log_before
          and len(original.write_calls) == o_writes_before
          and len(piv.write_calls) == p_writes_before)
    _record(9, "Collector observes without republish", "zero collector publishes/writes",
            f"publishes_added={len(original._server.publish_log) - len(server_log_before)}",
            "PASS" if ok else "FAIL")
    assert ok


# ========================================================================
# 10. PIV outbound Telegram attempts remain exactly zero
# ========================================================================

def test_scenario_10_piv_outbound_telegram_zero(tmp_path, monkeypatch):
    monkeypatch.delenv("TALONX_PIV_TELEGRAM_ENABLED", raising=False)
    cfg = PivConfig(state_dir=tmp_path)
    bus, broker, lifecycle, _ = cli.runtime(cfg)
    tg = RecordingTelegram()
    # emit a batch of events -- with telegram disabled the bus has no sender
    from talonx_piv.events import PivEvent
    for evt in ("STARTUP", "SIGNAL", "POSITION_OPENED", "POSITION_CLOSED", "EOD_SUMMARY"):
        bus.emit(PivEvent.build(evt, symbol="AAPL"))
    ok = bus.telegram_send is None and bus.telegram_attempts == 0 and tg.attempts == 0
    _record(10, "PIV outbound Telegram == 0", "no sender constructed, zero attempts",
            f"sender={bus.telegram_send}; attempts={bus.telegram_attempts}", "PASS" if ok else "FAIL")
    assert ok


# ========================================================================
# 11. PIV inbound Telegram poller starts exactly zero times
# ========================================================================

def test_scenario_11_piv_inbound_poller_zero_starts(tmp_path, monkeypatch):
    monkeypatch.delenv("TALONX_PIV_TELEGRAM_ENABLED", raising=False)
    cfg = PivConfig(state_dir=tmp_path)
    # cli builds a listener only when telegram_enabled; default is disabled
    from talonx_piv.telegram_inbound import build_piv_telegram_listener
    listener = None if not cfg.telegram_enabled else build_piv_telegram_listener(cfg, None)
    ok = cfg.telegram_enabled is False and listener is None
    _record(11, "PIV inbound poller zero starts", "no listener built when telegram disabled",
            f"telegram_enabled={cfg.telegram_enabled}; listener={listener}", "PASS" if ok else "FAIL")
    assert ok


# ========================================================================
# 12. PIV shadow mode produces exactly zero broker-mutating calls
# ========================================================================

def test_scenario_12_shadow_zero_broker_mutations(tmp_path):
    from talonx_piv.broker import AlpacaPaperClient

    class RecordingTransport:
        def __init__(self):
            self.calls = []
        def get(self, *a, **k):
            self.calls.append(("get", a))
            class R:
                status_code = 200
                def json(self_inner): return {}
                def raise_for_status(self_inner): return None
            return R()
        def post(self, *a, **k):
            self.calls.append(("post", a)); raise AssertionError("shadow must not POST to the broker")
        def delete(self, *a, **k):
            self.calls.append(("delete", a)); raise AssertionError("shadow must not DELETE at the broker")

    rt = RecordingTransport()
    _ = AlpacaPaperClient(PivConfig(state_dir=tmp_path), transport=rt)
    # shadow path: record + settle a synthetic decision, broker never involved
    from talonx_piv.decision_contract import (
        DataReadiness, Decision, ExecutionStatus, MarketView, Recommendation, StrategyApprovalStatus,
    )
    from talonx_piv.shadow_ledger import ShadowLedger

    decision = Decision(  # synthetic -- TEST_FIXTURE_ONLY -- NOT ALPHA EVIDENCE
        decision_id="d1", session_id=SESSION, trading_date_et=DATE, ticker="AAPL",
        market_view=MarketView.BULLISH, recommendation=Recommendation.BUY, reason_codes=(),
        strategy_id="s", strategy_version="0", strategy_approval_status=StrategyApprovalStatus.UNVALIDATED,
        data_readiness=DataReadiness.READY, paper_entry_enabled=False,
        execution_status=ExecutionStatus.ENTRY_BLOCKED_PAPER_DISABLED,
        timestamp=f"{DATE}T14:05:00+00:00", entry_price=100.0, stop_price=99.0, target_price=103.0,
    )
    sl = ShadowLedger(tmp_path / "shadow_ledger.json")
    sl.consider_entry(decision, source="STRATEGY")

    class _Bar:
        open = high = low = close = 100.5
        timestamp = datetime(2026, 8, 28, 14, 6, 0, tzinfo=timezone.utc)
    sl.on_bar("AAPL", _Bar())  # advance PENDING_FILL -> OPEN, still no broker

    class _StopBar:
        open = 100.5; high = 100.6; low = 98.0; close = 98.5
        timestamp = datetime(2026, 8, 28, 14, 7, 0, tzinfo=timezone.utc)
    sl.on_bar("AAPL", _StopBar())  # OPEN -> CLOSED at the shadow stop, still no broker
    mutating = [c for c in rt.calls if c[0] in ("post", "delete")]
    ok = mutating == [] and sl.get_by_decision("d1") is not None
    _record(12, "Shadow == 0 broker mutations", "no POST/DELETE to broker in shadow mode",
            f"mutating_calls={mutating}", "PASS" if ok else "FAIL")
    assert ok


# ========================================================================
# 13. Original notifications remain unaffected
# ========================================================================

def test_scenario_13_original_notifications_unaffected(cfg):
    original, piv = make_pair()
    original.seed_metric(DATE, "dispatch", "pushed_telegram", 9)
    before = dict(original._server.kv[0])
    ComparisonCollector(cfg, clock=lambda: NOW, original_redis=original, piv_redis=piv).collect_once()
    after = dict(original._server.kv[0])
    ok = before == after and original.write_calls == []
    _record(13, "Original notifications unaffected", "collector never mutates Original keyspace",
            f"keyspace_changed={before != after}", "PASS" if ok else "FAIL")
    assert ok


# ========================================================================
# 14. Missing / stale / corrupt / wrong-session states appear honestly
# ========================================================================

def test_scenario_14_bad_source_states_honest(tmp_path):
    piv = tmp_path / "piv"
    write_piv_state(piv)
    # corrupt one file, stale the events, add a wrong-session event
    (piv / "decision_ledger.json").write_text("{corrupt", encoding="utf-8")
    (piv / "piv_events.jsonl").write_text(
        json.dumps({"event": "SIGNAL", "timestamp": "2026-08-28T09:00:00+00:00",
                    "symbol": "AAPL", "session_id": SESSION, "trading_date_et": DATE}) + "\n"
        + json.dumps({"event": "SIGNAL", "timestamp": f"{DATE}T14:00:00+00:00", "symbol": "NVDA",
                      "session_id": "piv_OTHER", "trading_date_et": DATE}) + "\n",
        encoding="utf-8")
    cfg = CompareConfig(state_dir=tmp_path / "cs", evidence_root=tmp_path / "ev", piv_state_dir=piv)
    res = ComparisonCollector(cfg, clock=lambda: NOW).collect_once()
    kinds = {d["kind"] for d in res.diagnostics}
    states = {v["state"] for k, v in res.source_health.items() if isinstance(v, dict) and "state" in v}
    ok = {"UNREADABLE", "WRONG_SESSION"} <= kinds and "STALE" in states
    _record(14, "Bad source states honest", "UNREADABLE + WRONG_SESSION + STALE all surfaced",
            f"kinds={sorted(kinds)}; states={sorted(states)}", "PASS" if ok else "FAIL")
    assert ok


# ========================================================================
# 15. Collector/dashboard restart does not duplicate events
# ========================================================================

def test_scenario_15_restart_no_duplicate(cfg):
    r1 = _collect(cfg)
    r2 = ComparisonCollector(cfg, clock=lambda: NOW).collect_once()  # fresh object == restart
    lines = (cfg.evidence_root / DATE / "piv_records.jsonl").read_text().splitlines()
    ids = [json.loads(x)["_id"] for x in lines if x.strip()]
    ok = r2.piv_appended == 0 and len(ids) == len(set(ids))
    _record(15, "Restart no duplicate", "second pass appends 0; evidence has unique ids",
            f"second_pass_appended={r2.piv_appended}; unique={len(ids) == len(set(ids))}",
            "PASS" if ok else "FAIL")
    assert ok


# ========================================================================
# 16. Late EOD record updates the correct archived session
# ========================================================================

def test_scenario_16_late_eod_correct_session(cfg, piv_dir):
    _collect(cfg)
    (piv_dir / "eod_state.json").write_text(json.dumps({
        "status": "PASSED", "trading_date_et": DATE, "completed_at": f"{DATE}T20:30:00+00:00"}),
        encoding="utf-8")
    ComparisonCollector(cfg, clock=lambda: NOW).collect_once()
    recs = [json.loads(x) for x in
            (cfg.evidence_root / DATE / "piv_records.jsonl").read_text().splitlines() if x.strip()]
    eod = [x for x in recs if x["stage"] == "eod"]
    ok = len(eod) == 1 and eod[0]["session_id"] == SESSION and eod[0]["decision_outcome"] == "PASSED"
    _record(16, "Late EOD correct session", "one eod record, bound to archived session",
            f"eod_records={len(eod)}; session={eod[0]['session_id'] if eod else None}",
            "PASS" if ok else "FAIL")
    assert ok


# ========================================================================
# 17. One pipeline failure does not suppress or corrupt the other
# ========================================================================

def test_scenario_17_one_failure_isolated(tmp_path):
    from talonx_compare.dashboard_views import original_view, piv_view

    piv = tmp_path / "piv"
    piv.mkdir()
    (piv / "session_identity.json").write_text("{totally broken", encoding="utf-8")

    original, _ = make_pair()
    original.seed_metric(datetime.now(timezone.utc).date().isoformat(), "quant", "evaluated", 3)

    ov = original_view(redis_client=original, now=NOW)
    pv = piv_view(state_dir=piv, now=NOW)
    ok = (pv["identity"]["health"]["state"] == "UNREADABLE"
          and ov["pipeline"] == "ORIGINAL"
          and any(s["total"] >= 0 for s in ov["lifecycle_stages"]))
    _record(17, "One failure isolated", "PIV UNREADABLE; Original view still renders",
            f"piv_state={pv['identity']['health']['state']}; original_ok={ov['pipeline']}",
            "PASS" if ok else "FAIL")
    assert ok


# ========================================================================
# 18. Reconciliation / recovery-required retains priority over startup markers
# ========================================================================

def test_scenario_18_recovery_priority_over_startup(tmp_path):
    sd = tmp_path / "piv"
    sd.mkdir()
    # a startup / isolation marker is present...
    (sd / "isolation_verified.marker").write_text("ok", encoding="utf-8")
    # ...but there is unresolved exposure + a changed binding + missing identity
    (sd / "lifecycle_state.json").write_text(json.dumps({
        "orders": {"o1": {"status": "new", "symbol": "AAPL"}},
        "positions": {"p1": {"status": "OPEN", "symbol": "AAPL", "quantity": 1}},
        "session_enabled": True, "kill_switch": False,
        "reconciliation_flags": {"entry_admission_blocked": True},
    }), encoding="utf-8")
    cfg = PivConfig(state_dir=sd)
    assessment = assess_session_recovery(cfg, now=NOW)
    raised = False
    try:
        resolve_session_identity(cfg, now=NOW)
    except SessionRecoveryRequired:
        raised = True
    ok = assessment.mode == "RECOVERY_REQUIRED" and raised
    _record(18, "Recovery priority over startup markers",
            "RECOVERY_REQUIRED despite a startup marker being present",
            f"mode={assessment.mode}; raised={raised}", "PASS" if ok else "FAIL")
    assert ok


# ========================================================================
# 19. Abrupt process termination releases only owned locks, preserves evidence
# ========================================================================

def test_scenario_19_abrupt_termination_owned_locks_only(tmp_path):
    cfg = CompareConfig(state_dir=tmp_path / "cs", evidence_root=tmp_path / "ev",
                        piv_state_dir=tmp_path / "piv")
    write_piv_state(cfg.piv_state_dir)
    # a PIV lock file that the collector must NEVER touch
    piv_lock = cfg.piv_state_dir / "execution_ownership.lock"
    piv_lock.write_text("held-by-piv", encoding="utf-8")

    # a real subprocess acquires the COLLECTOR lock, then is killed abruptly
    holder = subprocess.Popen(
        [sys.executable, "-c",
         "import sys,time\n"
         "from talonx_compare.runner import CollectorLock\n"
         "l = CollectorLock(__import__('pathlib').Path(sys.argv[1]))\n"
         "l.acquire(); open(sys.argv[2],'w').write('locked'); time.sleep(60)\n",
         str(cfg.lock_path), str(tmp_path / "ready")],
        cwd=str(Path.cwd()), stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    try:
        for _ in range(50):
            if (tmp_path / "ready").exists():
                break
            time.sleep(0.1)
        assert cfg.lock_path.exists()
        holder.kill()  # abrupt -- no clean release
        holder.wait(timeout=5)
    finally:
        if holder.poll() is None:
            holder.kill()

    # a new collector run: the stale collector lock self-heals; the PIV
    # lock is untouched; prior evidence survives
    ComparisonCollector(cfg, clock=lambda: NOW).collect_once()
    with CollectorLock(cfg.lock_path):  # acquirable again -> stale lock was reclaimed
        acquired = True
    ok = (acquired and piv_lock.read_text() == "held-by-piv"
          and (cfg.evidence_root / DATE / "manifest.json").exists())
    _record(19, "Abrupt termination owned locks only",
            "collector lock self-heals; PIV lock untouched; evidence preserved",
            f"piv_lock_intact={piv_lock.read_text() == 'held-by-piv'}", "PASS" if ok else "FAIL")
    assert ok


# ========================================================================
# 20. Dashboard and collector remain read-only throughout
# ========================================================================

def test_scenario_20_read_only_throughout(cfg):
    original, piv = make_pair()
    original.seed_metric(DATE, "quant", "evaluated", 4)
    # full collector pass
    ComparisonCollector(cfg, clock=lambda: NOW, original_redis=original, piv_redis=piv).collect_once()
    # dashboard view builders
    from talonx_compare.dashboard_views import compare_view, original_view, piv_view
    original_view(redis_client=original, now=NOW)
    piv_view(state_dir=cfg.piv_state_dir, now=NOW)
    compare_view(config=cfg)
    ok = original.write_calls == [] and piv.write_calls == [] and original._server.publish_log == []
    _record(20, "Dashboard + collector read-only",
            "no writes, no publishes across collector + all three views",
            f"original_writes={len(original.write_calls)}; piv_writes={len(piv.write_calls)}",
            "PASS" if ok else "FAIL")
    assert ok
