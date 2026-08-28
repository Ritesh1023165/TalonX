"""Task 80-P1 deterministic fail-closed process-guard tests."""

from __future__ import annotations

import subprocess

import pytest

from talonx_core.process_guard import no_competing_talonx_process
from talonx_ops.preflight import FULL_APP_E2E_BLOCKED, FullAppPreflight
from talonx_piv import preflight as piv_preflight_module
from talonx_piv import supervisor
from talonx_piv.config import PivConfig
from talonx_piv.events import EventBus


class _Response:
    status_code = 200

    def json(self):
        return {"ok": True, "trade": {"t": "2026-08-28T14:30:00Z"}}


class _Transport:
    def get(self, *args, **kwargs):
        return _Response()


def _output(value: str):
    def run(*args, **kwargs):
        return value
    return run


def test_empty_enumeration_passes():
    passed, detail = no_competing_talonx_process(exclude_pid=10, check_output=_output(""))
    assert passed is True
    assert "completed successfully" in detail


def test_self_only_is_excluded():
    passed, _ = no_competing_talonx_process(exclude_pid=10, check_output=_output("10\n"))
    assert passed is True


def test_one_or_multiple_competitors_block():
    passed, detail = no_competing_talonx_process(exclude_pid=10, check_output=_output("20\n30\n20\n"))
    assert passed is False
    assert "2 competing" in detail
    assert "20" in detail and "30" in detail


def test_self_plus_competitor_blocks_only_on_competitor():
    passed, detail = no_competing_talonx_process(exclude_pid=10, check_output=_output("10\n20\n"))
    assert passed is False
    assert "1 competing" in detail and "20" in detail


@pytest.mark.parametrize(
    "error",
    [
        PermissionError("access denied"),
        subprocess.TimeoutExpired("powershell", 20),
        subprocess.CalledProcessError(1, "powershell"),
        FileNotFoundError("powershell"),
    ],
)
def test_every_enumeration_error_fails_closed_without_echoing_error(error):
    def fail(*args, **kwargs):
        raise error

    passed, detail = no_competing_talonx_process(exclude_pid=10, check_output=fail)
    assert passed is False
    assert "failed closed" in detail
    assert "access denied" not in detail


@pytest.mark.parametrize("output", ["abc\n", "12.5\n", "-1\n", "１２\n"])
def test_malformed_pid_output_fails_closed(output):
    passed, detail = no_competing_talonx_process(exclude_pid=10, check_output=_output(output))
    assert passed is False
    assert "malformed PID" in detail


def test_powershell_query_forces_nonterminating_errors_to_stop():
    captured = {}

    def run(command, **kwargs):
        captured["command"] = command
        captured["kwargs"] = kwargs
        return ""

    assert no_competing_talonx_process(exclude_pid=10, check_output=run)[0] is True
    query = captured["command"][-1]
    assert "$ErrorActionPreference = 'Stop'" in query
    assert "-ErrorAction Stop" in query
    assert "$_.Name -match '^python(?:w)?(?:\\.exe)?$'" in query
    assert captured["kwargs"]["stderr"] == subprocess.STDOUT


def test_supervisor_wrapper_delegates_exclusion(monkeypatch):
    seen = {}

    def fake(*, exclude_pid=None):
        seen["exclude_pid"] = exclude_pid
        return False, "blocked"

    monkeypatch.setattr(supervisor.process_guard, "no_competing_talonx_process", fake)
    assert supervisor.no_duplicate_full_app_or_piv_process(exclude_pid=42) == (False, "blocked")
    assert seen["exclude_pid"] == 42


def test_piv_preflight_status_blocks_when_enumeration_is_uncertain(tmp_path, monkeypatch):
    class Broker:
        headers = {}

        def verify_paper_identity(self):
            raise AssertionError("later checks may run but this test only needs the process gate")

        def open_orders(self):
            return []

        def positions(self):
            return []

    monkeypatch.setattr(
        piv_preflight_module.process_guard,
        "no_competing_talonx_process",
        lambda: (False, "process enumeration failed closed (PermissionError)"),
    )
    cfg = PivConfig(approved_sha="abc", state_dir=tmp_path, decision_path_enabled=False)
    flight = piv_preflight_module.Preflight(
        cfg, Broker(), EventBus(tmp_path / "events.jsonl"), tmp_path, _Transport(),
    )
    monkeypatch.setattr(flight, "_git", lambda *args: "abc" if args[0] == "rev-parse" else "")
    status, checks = flight.run()
    check = next(item for item in checks if item.name == "no_duplicate_full_app_or_piv_process")
    assert status == "PIV_BLOCKED"
    assert check.passed is False


def test_full_app_status_blocks_when_enumeration_is_uncertain(monkeypatch):
    monkeypatch.setattr(
        "talonx_ops.preflight.process_guard.no_competing_talonx_process",
        lambda: (False, "process enumeration failed closed (PermissionError)"),
    )
    status, checks = FullAppPreflight(
        expected_sha="definitely-not-current", transport=_Transport(),
    ).run()
    check = next(item for item in checks if item.name == "no_duplicate_full_app_or_piv_process")
    assert status == FULL_APP_E2E_BLOCKED
    assert check.passed is False
