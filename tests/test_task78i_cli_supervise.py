"""Task 78I Stage 2 -- cli.py `supervise` command wiring. TEST_FIXTURE_ONLY
-- NOT ALPHA EVIDENCE. Monkeypatches `requests` directly (never a real
socket) so `cli.main()`'s real AlpacaPaperClient(config) can be exercised
end-to-end, exactly as test_task78i_cli_ownership.py does."""
from __future__ import annotations

import asyncio
import json

import pytest

from talonx_piv import cli
from talonx_piv.config import PAPER_ENDPOINT
from talonx_piv.execution_ownership import account_lock_key


class _Resp:
    def __init__(self, body, status=200):
        self.body, self.status_code = body, status

    def json(self):
        return self.body

    def raise_for_status(self):
        if self.status_code >= 400:
            raise RuntimeError(f"HTTP {self.status_code}")


@pytest.fixture(autouse=True)
def _fake_requests(monkeypatch):
    import requests

    def fake_get(url, headers=None, params=None, timeout=None):
        if url.endswith("/v2/account"):
            return _Resp({"id": "acct-supervise-test", "account_number": "PA888888", "status": "ACTIVE"})
        if url.endswith("/v2/orders"):
            return _Resp([])
        if url.endswith("/v2/positions"):
            return _Resp([])
        if "/trades/latest" in url:
            return _Resp({"trade": {"t": "2026-08-27T14:30:00Z", "p": 100.0}})
        if url.endswith("/getMe"):
            return _Resp({"ok": False}, 200)
        return _Resp({}, 404)

    def fake_post(url, headers=None, json=None, timeout=None):
        return _Resp({"id": "o1", "status": "new", "filled_qty": "0"})

    def fake_delete(url, headers=None, params=None, timeout=None):
        return _Resp([])

    monkeypatch.setattr(requests, "get", fake_get)
    monkeypatch.setattr(requests, "post", fake_post)
    monkeypatch.setattr(requests, "delete", fake_delete)
    monkeypatch.setattr(requests, "request", lambda *a, **k: (_ for _ in ()).throw(AssertionError("unexpected raw request()")))
    yield


def _base_env(monkeypatch, tmp_path):
    monkeypatch.setenv("TALONX_PIV_LOCK_DIR", str(tmp_path / "locks"))
    monkeypatch.setenv("TALONX_PIV_STATE_DIR", str(tmp_path / "state"))
    monkeypatch.setenv("APCA_API_KEY_ID", "key")
    monkeypatch.setenv("APCA_API_SECRET_KEY", "secret")
    monkeypatch.setenv("TALONX_PIV_PAPER_TRADING", "true")
    monkeypatch.setenv("TALONX_PIV_APPROVED_SHA", "abc")
    monkeypatch.setenv("TALONX_PIV_DECISION_PATH", "false")  # no Redis in this test


def test_supervise_blocked_when_preflight_fails(tmp_path, monkeypatch):
    """Preflight will fail here (approved_sha mismatch vs actual repo HEAD,
    Telegram not configured, etc.) -- supervise must report PIV_BLOCKED and
    persist a startup-failure recovery record, never silently proceed."""
    _base_env(monkeypatch, tmp_path)
    code = cli.main(["supervise", "--approved-sha", "abc", "--confirm-paper-session-start"])
    assert code == 2
    health_path = tmp_path / "state" / "component_health.json"
    assert health_path.exists()
    health = json.loads(health_path.read_text(encoding="utf-8"))
    assert health["overall"] == "FAILED"
    recovery_path = tmp_path / "state" / "supervisor_recovery_state.json"
    assert recovery_path.exists()
    recovery = json.loads(recovery_path.read_text(encoding="utf-8"))
    assert recovery["invocations"][-1]["startup"]["passed"] is False


def test_supervise_second_instance_blocked_by_ownership(tmp_path, monkeypatch):
    """Even if preflight WOULD pass, a competing lock holder must block
    supervise from ever reaching start_session."""
    from talonx_piv.execution_ownership import ExecutionOwnership
    _base_env(monkeypatch, tmp_path)
    lock_dir = tmp_path / "locks"
    key = account_lock_key(PAPER_ENDPOINT, "acct-supervise-test")
    holder = ExecutionOwnership(lock_dir, key)
    assert holder.acquire() is True
    try:
        code = cli.main(["supervise", "--approved-sha", "abc", "--confirm-paper-session-start"])
        assert code == 2  # PIV_BLOCKED, regardless of whether preflight itself would have passed
    finally:
        holder.release()
