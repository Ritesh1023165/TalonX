"""
Task 117 D4 -- startup verdict + repeated/concurrent-start protection.

``prospective start`` now yields a first-class verdict
(NOT_STARTED / STARTING / READY / FAILED_WITH_RESIDUALS) from the ACTUAL
process/heartbeat state, and refuses to spawn a second stack while one is
already running (a second v2_lane.db writer).
"""
from __future__ import annotations

import pytest

import talonx_ops.prospective.proc as proc
from talonx_ops.prospective.proc import (
    ConcurrentStartError, assert_no_live_prior_stack, startup_verdict,
)


_ALL_UP = {"supervisor_alive": True, "v2_companion_alive": True, "dashboard_8787": True}


@pytest.mark.parametrize(
    "verify,hb,grace,residual,expected",
    [
        (_ALL_UP, True, True, False, "READY"),
        # dashboard not up yet -> STARTING even with sup+comp+heartbeat
        ({"supervisor_alive": True, "v2_companion_alive": True, "dashboard_8787": False},
         True, True, False, "STARTING"),
        (_ALL_UP, False, True, False, "STARTING"),                      # no first tick yet
        ({"supervisor_alive": True, "v2_companion_alive": True, "dashboard_8787": False},
         True, False, True, "FAILED_WITH_RESIDUALS"),                    # grace gone, dash missing
        ({"supervisor_alive": True, "v2_companion_alive": False}, False, True, False, "STARTING"),
        ({"supervisor_alive": True, "v2_companion_alive": False}, False, False, True, "FAILED_WITH_RESIDUALS"),
        ({"supervisor_alive": False, "v2_companion_alive": False}, False, False, False, "NOT_STARTED"),
        ({"supervisor_alive": False, "v2_companion_alive": False}, False, False, True, "FAILED_WITH_RESIDUALS"),
    ],
)
def test_startup_verdict_matrix(monkeypatch, verify, hb, grace, residual, expected):
    monkeypatch.setattr(proc, "_live_prior_stack", lambda: ([{"pid": 1}] if residual else []))
    assert startup_verdict({}, verify, heartbeat_fresh=hb, within_grace=grace) == expected


def test_ready_requires_the_dashboard_not_just_sup_and_companion(monkeypatch):
    monkeypatch.setattr(proc, "_live_prior_stack", lambda: [])
    v = startup_verdict({}, {"supervisor_alive": True, "v2_companion_alive": True,
                             "dashboard_8787": False},
                        heartbeat_fresh=True, within_grace=True)
    assert v == "STARTING"          # NOT READY -- essential dashboard is mandatory


def test_missing_mandatory_is_not_a_cosmetic_warning(monkeypatch):
    """supervisor up, companion down, grace elapsed -> a hard FAILED verdict,
    never READY / STARTING."""
    monkeypatch.setattr(proc, "_live_prior_stack", lambda: [{"pid": 42}])
    v = startup_verdict({}, {"supervisor_alive": True, "v2_companion_alive": False,
                             "dashboard_8787": True},
                        heartbeat_fresh=False, within_grace=False)
    assert v == "FAILED_WITH_RESIDUALS"


def test_concurrent_start_is_refused(monkeypatch):
    monkeypatch.setattr(proc, "_live_prior_stack",
                        lambda: [{"pid": 999, "cmd": "python -m talonx_v2.run --mode live"}])
    with pytest.raises(ConcurrentStartError):
        assert_no_live_prior_stack()


def test_no_prior_stack_allows_start(monkeypatch):
    monkeypatch.setattr(proc, "_live_prior_stack", lambda: [])
    assert_no_live_prior_stack()   # no raise


def _tmp_lock(monkeypatch, tmp_path):
    """Point the single-writer lock at an isolated tmp ledger, never prod."""
    from talonx_ops.prospective.lock import SingleWriterLock
    lp = tmp_path / "iso_v2_lane.db"
    monkeypatch.setattr(proc, "SingleWriterLock", lambda _p: SingleWriterLock(lp))


def test_start_stack_guard_blocks_a_second_spawn(monkeypatch, tmp_path):
    _tmp_lock(monkeypatch, tmp_path)
    monkeypatch.setattr(proc, "_live_prior_stack",
                        lambda: [{"pid": 7, "cmd": "talonx_ops.supervisor run"}])
    spawned = []
    monkeypatch.setattr(proc, "_spawn", lambda *a, **k: spawned.append(a) or 111)
    with pytest.raises(ConcurrentStartError):
        proc.start_stack(tmp_path, env={})
    assert spawned == []   # nothing was spawned
    # the lock was released on the failure (not left held)
    assert not (tmp_path / "iso_v2_lane.db.startlock").exists()


def test_start_stack_force_overrides_the_guard(monkeypatch, tmp_path):
    _tmp_lock(monkeypatch, tmp_path)
    monkeypatch.setattr(proc, "_live_prior_stack",
                        lambda: [{"pid": 7, "cmd": "talonx_ops.supervisor run"}])
    monkeypatch.setattr(proc.time, "sleep", lambda *_: None)
    spawned = []
    monkeypatch.setattr(proc, "_spawn", lambda argv, **k: spawned.append(argv) or 111)
    proc.start_stack(tmp_path, env={}, with_checkpoint_daemon=False, allow_when_running=True)
    assert any("talonx_v2.run" in a for a in spawned)
