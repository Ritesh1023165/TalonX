"""
Task 117 Phase 0 -- operator lifecycle repairs (Phase 4).

4.1  verify_running does a BOUNDED retry over the actual required
     components and reports attempts + a `ready` flag (not "success from a
     heartbeat alone").
4.3  the evening close must NOT report a clean PASS while required stack
     children are still running -- residuals become a finding, a PARTIAL
     assert, and feed the non-zero exit status.

These touch only talonx_ops/prospective/* (operator plumbing) -- no
strategy semantics, no fingerprint impact.
"""
from __future__ import annotations

import json
from pathlib import Path

from talonx_ops.prospective import proc as _proc
from talonx_ops.prospective.close import CloseResult


# --------------------------------------------------------------------------- #
# 4.1 verify_running bounded retry
# --------------------------------------------------------------------------- #
def test_verify_running_retries_until_components_up(tmp_path, monkeypatch):
    (tmp_path / "session.pids.json").write_text(json.dumps(
        {"supervisor_pid": 111, "v2_companion_pid": 222, "checkpoint_daemon_pid": 333}))
    monkeypatch.setattr(_proc, "read_pids", lambda sd: json.loads(
        (Path(sd) / "session.pids.json").read_text()))
    monkeypatch.setattr(_proc, "_port_open", lambda p: False)
    monkeypatch.setattr(_proc.time, "sleep", lambda *_: None)

    calls = {"n": 0}

    def _alive(pid):
        # supervisor + companion come up only on the 3rd poll
        calls["n"] += 1
        return calls["n"] > 4

    monkeypatch.setattr(_proc, "_alive", _alive)
    out = _proc.verify_running(tmp_path, retries=8, delay_s=0)
    assert out["ready"] is True
    assert out["attempts"] >= 2


def test_verify_running_gives_up_bounded(tmp_path, monkeypatch):
    (tmp_path / "session.pids.json").write_text(json.dumps(
        {"supervisor_pid": 111, "v2_companion_pid": 222}))
    monkeypatch.setattr(_proc, "read_pids", lambda sd: json.loads(
        (Path(sd) / "session.pids.json").read_text()))
    monkeypatch.setattr(_proc, "_port_open", lambda p: False)
    monkeypatch.setattr(_proc, "_alive", lambda pid: False)
    monkeypatch.setattr(_proc.time, "sleep", lambda *_: None)
    out = _proc.verify_running(tmp_path, retries=5, delay_s=0)
    assert out["ready"] is False and out["attempts"] == 5


# --------------------------------------------------------------------------- #
# 4.3 close: residual processes -> finding + PARTIAL + non-clean
# --------------------------------------------------------------------------- #
def _run_close_with_shutdown(tmp_path, monkeypatch, residual):
    import talonx_ops.prospective.close as _close
    import talonx_ops.prospective.proc as _p

    monkeypatch.setattr(_close, "eod_state", lambda *a, **k: {"state": "PENDING", "reason": "due"})
    monkeypatch.setattr(_close, "capture", lambda *a, **k: {
        "funnel": {}, "market": {}, "service_health": {}, "official_dispatch": {}})
    monkeypatch.setattr(_close, "_v2_reconcile", lambda: (
        {"cash": 300000.0, "open": 0, "closed": 0, "buys": 0, "sells": 0,
         "exit_unresolved": 0, "starting_cash": 300000.0, "realized_pnl_usd": 0.0, "open_cost_usd": 0.0},
        {"buys_eq_sells_plus_open_plus_unresolved": "PASS", "no_negative_cash": "PASS"},
        []))
    monkeypatch.setattr(_close, "_base_reconcile", lambda: {"status": "RECONCILED", "mismatches": []})
    monkeypatch.setattr(_close, "_experimental_external_zero", lambda ck: (True, ""))
    # keep the real shutil.copy2 from clobbering -- point the copy targets at tmp
    monkeypatch.setattr(_close, "V2_DB_PATH", str(tmp_path / "src_v2.db"))
    monkeypatch.setattr(_close, "V2_STATUS_PATH", str(tmp_path / "src_status.json"))
    (tmp_path / "src_v2.db").write_bytes(b"x")
    (tmp_path / "src_status.json").write_text("{}")
    monkeypatch.setattr(_p, "stop_stack", lambda sd, **k: {
        "checkpoint_daemon": "stopped", "v2_companion": "stopped", "supervisor": "stopped",
        "residual_talonx_processes": residual, "ports": {}, "v2_lane_db_intact": True})
    return _close.run_close(tmp_path, do_shutdown=True)


def test_close_flags_residual_processes(tmp_path, monkeypatch):
    res = _run_close_with_shutdown(
        tmp_path, monkeypatch,
        residual=[{"pid": 4708, "cmd": "python dashboard_web.py"},
                  {"pid": 13128, "cmd": "python run_talonx.py"}])
    assert res.shutdown["shutdown_clean"] is False
    assert res.asserts.get("controlled_shutdown_complete") == "PARTIAL"
    assert any("residual" in f.lower() for f in res.findings)
    assert res.verdict == "PASS_WITH_FINDINGS"


def test_close_clean_shutdown_is_pass(tmp_path, monkeypatch):
    res = _run_close_with_shutdown(tmp_path, monkeypatch, residual=[])
    assert res.shutdown["shutdown_clean"] is True
    assert res.asserts.get("controlled_shutdown_complete") == "PASS"
