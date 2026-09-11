"""
Task 117 Phase 0 -- Acceptance closure Phase 7: startup grace + supervisor-owned
recursive shutdown.

Two groups:
  L1  startup_grace / _service_health / _invariant_flags  -- bounded warmup, hard
      invariants never suppressed  (pure, runs everywhere)
  L2  Supervisor._stop_component over REAL isolated Windows subprocesses -- the
      supervisor's OWN stop path now reaps an orphaned .venv-shim grandchild
      (skipif not Windows)

No Redis, no network, no production component. Marker strings are passed as REAL
argv so psutil.cmdline() sees them.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import textwrap
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

# --------------------------------------------------------------------------- L1
from talonx_ops.prospective import checkpoint as _ck


def _now():
    return datetime(2026, 9, 8, 15, 0, tzinfo=timezone.utc)


def _status(hb_age_s=None, version="INSIDER_BUY_CLUSTER_V2@1", tick=3, records=12):
    s = {"strategy_version": version, "heartbeat_ttl_s": 180, "tick": tick,
         "form4_records_seen": records}
    if hb_age_s is not None:
        s["heartbeat_utc"] = (_now() - timedelta(seconds=hb_age_s)).isoformat()
    return s


def test_l1a_young_session_no_status_is_STARTING_not_DOWN():
    started = _now() - timedelta(seconds=30)
    g = _ck.startup_grace({}, _now(), started)
    assert g["state"] == "STARTING"
    assert g["seconds_remaining"] > 0 and "deadline_utc" in g
    h = _ck._service_health({}, _now(), started)
    assert h["health"] == "STARTING"


def test_l1b_grace_exhausted_is_explicit_STARTUP_FAILED():
    started = _now() - timedelta(seconds=_ck.STARTUP_GRACE_S + 20)
    g = _ck.startup_grace(_status(hb_age_s=None), _now(), started)
    assert g["state"] == "STARTUP_FAILED"
    h = _ck._service_health({}, _now(), started)
    assert h["health"] == "STARTUP_FAILED"                # never a silent DOWN


def test_l1c_ready_during_grace_clears_startup():
    started = _now() - timedelta(seconds=45)
    g = _ck.startup_grace(_status(hb_age_s=10), _now(), started)
    assert g["state"] == "NOT_IN_STARTUP"
    assert _ck._service_health(_status(hb_age_s=10), _now(), started)["health"] == "HEALTHY"


def test_l1d_stale_old_marker_falls_through_to_normal_health():
    started = _now() - timedelta(seconds=_ck.STARTUP_GRACE_S * 3 + 600)
    assert _ck.startup_grace({}, _now(), started)["state"] == "NOT_IN_STARTUP"
    assert _ck._service_health({}, _now(), started)["health"] == "DOWN"


def test_l1e_hard_ledger_invariant_never_suppressed_during_STARTING():
    """A negative-cash ledger during the warmup grace still fires CRITICAL."""
    class _Ledger:
        cash = -5.0
        problems: list[str] = []

    class _Poller:
        healthy = True
    svc = {"health": "STARTING"}
    flags = _ck._invariant_flags(_status(), _Ledger(), {"clusters": {}}, {"sent_today": 0},
                                 _Poller(), svc)
    assert flags["negative_cash"] is True
    assert flags["any_critical"] is True
    assert flags["v2_process_dead"] is False              # warmup -> not "dead"
    assert flags["v2_startup_failed"] is False


def test_l1f_startup_failed_sets_its_own_critical_flag():
    class _Ledger:
        cash = 300000.0
        problems: list[str] = []

    class _Poller:
        healthy = True
    flags = _ck._invariant_flags(_status(), _Ledger(), {"clusters": {}}, {"sent_today": 0},
                                 _Poller(), {"health": "STARTUP_FAILED"})
    assert flags["v2_startup_failed"] is True and flags["any_critical"] is True


# --------------------------------------------------------------------------- L2
pytest_windows = pytest.mark.skipif(os.name != "nt", reason="real Windows subprocess stop path")

from talonx_ops import supervisor as _sup
from talonx_ops.supervisor import (Classification, ComponentSpec, ComponentState,
                                   Supervisor, SubprocessRunner)

_MARK = "talonx_v2.run"

_SHIM = textwrap.dedent("""
    import subprocess, sys, time
    subprocess.Popen([sys.executable, "-c", "import time; time.sleep(600)", sys.argv[1]])
    print("SHIM_UP", flush=True)
    time.sleep(600)
""")

_DEAF = textwrap.dedent("""
    import signal, time
    for s in ("SIGTERM", "SIGBREAK", "SIGINT"):
        try: signal.signal(getattr(signal, s), lambda *a: None)
        except Exception: pass
    print("DEAF_UP", flush=True)
    time.sleep(600)
""")


def _alive(pid) -> bool:
    import psutil
    try:
        p = psutil.Process(pid)
        return p.is_running() and p.status() != psutil.STATUS_ZOMBIE
    except Exception:
        return False


def _spec(script: Path, name="v2") -> ComponentSpec:
    return ComponentSpec(
        name=name, argv=[sys.executable, str(script), _MARK],
        classification=Classification.OPTIONAL, start_order=10, stop_order=10,
        readiness_grace_s=0.5, readiness_timeout_s=8.0, graceful_stop_s=6.0)


def _sup_with(script: Path) -> Supervisor:
    return Supervisor([_spec(script)], runner=SubprocessRunner())


@pytest_windows
def test_l2a_supervisor_stop_reaps_shim_and_grandchild(tmp_path):
    import psutil
    script = tmp_path / "shim.py"
    script.write_text(_SHIM)
    sv = _sup_with(script)
    c = sv.components["v2"]
    sv._spawn(c)
    time.sleep(2.5)
    kids = [k.pid for k in psutil.Process(c.pid).children(recursive=True)]
    assert kids, "shim should have a grandchild"

    t0 = time.monotonic()
    sv._stop_component(c)
    assert time.monotonic() - t0 < 15.0
    assert c.state is ComponentState.STOPPED
    assert not _alive(c.pid)
    for k in kids:
        assert not _alive(k), f"grandchild {k} orphaned by supervisor stop"
    assert c.last_stop_mode in ("graceful", "forced", "forced_descendant")


@pytest_windows
def test_l2b_stop_all_verifies_no_residual_descendants(tmp_path):
    script = tmp_path / "shim.py"
    script.write_text(_SHIM)
    sv = _sup_with(script)
    sv.start_all()
    c = sv.components["v2"]
    assert c.pid and _alive(c.pid)
    res = sv.stop_all()
    assert res["orphans"] == []
    assert res["residual_descendants"] == []
    assert res["stop_modes"].get("v2") in ("graceful", "forced", "forced_descendant")


@pytest_windows
def test_l2c_unresponsive_child_escalated_within_budget(tmp_path):
    script = tmp_path / "deaf.py"
    script.write_text(_DEAF)
    sv = _sup_with(script)
    c = sv.components["v2"]
    sv._spawn(c)
    time.sleep(1.5)
    t0 = time.monotonic()
    sv._stop_component(c)
    assert time.monotonic() - t0 < 20.0
    assert not _alive(c.pid)
    assert c.last_stop_mode in ("forced", "forced_descendant", "graceful")


@pytest_windows
def test_l2d_unrelated_python_process_is_never_touched(tmp_path):
    # a descendant-looking process with NO component marker must survive
    victim = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(600)"])
    time.sleep(0.5)
    try:
        entry = {"pid": victim.pid,
                 "create_time": __import__("psutil").Process(victim.pid).create_time(),
                 "cmd": "python -c sleep"}
        assert _sup._same_owned_component(entry) is False
        reap = _sup._reap_owned_descendants([entry], budget_s=3.0)
        assert reap["mode"] == "none"
        assert _alive(victim.pid)
    finally:
        victim.kill()


@pytest_windows
def test_l2e_repeat_stop_is_idempotent_and_no_respawn(tmp_path):
    script = tmp_path / "shim.py"
    script.write_text(_SHIM)
    sv = _sup_with(script)
    c = sv.components["v2"]
    sv._spawn(c)
    time.sleep(2.0)
    sv._stop_component(c)
    st1 = c.state
    sv._stop_component(c)                    # again -- must be a no-op
    assert c.state is ComponentState.STOPPED and st1 is ComponentState.STOPPED
    sv.poll_once()                           # must NOT schedule a restart for a stopped comp
    assert c.state is ComponentState.STOPPED
    assert not _alive(c.pid)


@pytest_windows
def test_l2f_reused_pid_by_create_time_is_not_killed(tmp_path):
    # snapshot entry whose create_time is deliberately wrong -> treated as reused
    victim = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(600)", _MARK])
    time.sleep(0.5)
    try:
        entry = {"pid": victim.pid, "create_time": 1.0, "cmd": "stale"}   # 1970 -> mismatch
        assert _sup._same_owned_component(entry) is False
        assert _alive(victim.pid)
    finally:
        victim.kill()
