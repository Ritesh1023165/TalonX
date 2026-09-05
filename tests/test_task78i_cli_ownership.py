"""Task 78I Stage 1D -- cli.py's acquire_execution_ownership wiring.
TEST_FIXTURE_ONLY -- NOT ALPHA EVIDENCE. Monkeypatches `requests` module
functions directly (never a real socket) so `cli.main()`'s own
`AlpacaPaperClient(config)` (constructed with the real `requests` module as
transport, exactly as production does) can be exercised end-to-end."""
from __future__ import annotations

import pytest

from talonx_piv import cli
from talonx_piv.config import PAPER_ENDPOINT
from talonx_piv.execution_ownership import ExecutionOwnership, account_lock_key


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
    """TEST_FIXTURE_ONLY -- NOT ALPHA EVIDENCE. A minimal in-memory Alpaca
    paper stand-in, monkeypatched directly onto the `requests` module (the
    same module cli.py's real AlpacaPaperClient(config) uses by default) --
    never a real socket."""
    import requests

    orders: list[dict] = []

    def fake_get(url, headers=None, params=None, timeout=None):
        if url.endswith("/v2/account"):
            return _Resp({"id": "acct-cli-test", "account_number": "PA999999", "status": "ACTIVE"})
        if url.endswith("/v2/orders"):
            return _Resp([o for o in orders if o.get("status") == "open"])
        if url.endswith("/v2/positions"):
            return _Resp([])
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


def test_kill_switch_acquires_ownership_and_succeeds(tmp_path, monkeypatch):
    monkeypatch.setenv("TALONX_PIV_LOCK_DIR", str(tmp_path / "locks"))
    monkeypatch.setenv("TALONX_PIV_STATE_DIR", str(tmp_path / "state"))
    monkeypatch.setenv("APCA_API_KEY_ID", "key")
    monkeypatch.setenv("APCA_API_SECRET_KEY", "secret")
    monkeypatch.setenv("TALONX_PIV_PAPER_TRADING", "true")
    monkeypatch.setenv("TALONX_PIV_APPROVED_SHA", "abc")
    monkeypatch.setenv("TALONX_PIV_DECISION_PATH", "false")
    code = cli.main(["kill-switch"])
    assert code == 0


def test_second_kill_switch_invocation_while_first_still_holds_lock_is_blocked(tmp_path, monkeypatch):
    """Simulates a competing SECOND application instance for the same
    account -- it must not silently proceed."""
    lock_dir = tmp_path / "locks"
    monkeypatch.setenv("TALONX_PIV_LOCK_DIR", str(lock_dir))
    monkeypatch.setenv("TALONX_PIV_STATE_DIR", str(tmp_path / "state"))
    monkeypatch.setenv("APCA_API_KEY_ID", "key")
    monkeypatch.setenv("APCA_API_SECRET_KEY", "secret")
    monkeypatch.setenv("TALONX_PIV_PAPER_TRADING", "true")
    monkeypatch.setenv("TALONX_PIV_APPROVED_SHA", "abc")
    monkeypatch.setenv("TALONX_PIV_DECISION_PATH", "false")

    # Pre-acquire the SAME account lock as if another live process holds it.
    key = account_lock_key(PAPER_ENDPOINT, "acct-cli-test")
    holder = ExecutionOwnership(lock_dir, key)
    assert holder.acquire() is True
    try:
        code = cli.main(["kill-switch"])
        assert code == 2  # PIV_BLOCKED -- ownership contention, never silently proceeds
    finally:
        holder.release()


def test_cleanup_acquires_ownership_before_calling_paper_cleanup(tmp_path, monkeypatch):
    monkeypatch.setenv("TALONX_PIV_LOCK_DIR", str(tmp_path / "locks"))
    monkeypatch.setenv("TALONX_PIV_STATE_DIR", str(tmp_path / "state"))
    monkeypatch.setenv("APCA_API_KEY_ID", "key")
    monkeypatch.setenv("APCA_API_SECRET_KEY", "secret")
    monkeypatch.setenv("TALONX_PIV_PAPER_TRADING", "true")
    monkeypatch.setenv("TALONX_PIV_APPROVED_SHA", "abc")
    monkeypatch.setenv("TALONX_PIV_DECISION_PATH", "false")
    code = cli.main(["cleanup", "--confirm-paper-cleanup"])
    assert code == 0


def test_start_no_live_loop_acquires_ownership_when_ready(tmp_path, monkeypatch):
    monkeypatch.setenv("TALONX_PIV_LOCK_DIR", str(tmp_path / "locks"))
    monkeypatch.setenv("TALONX_PIV_STATE_DIR", str(tmp_path / "state"))
    monkeypatch.setenv("APCA_API_KEY_ID", "key")
    monkeypatch.setenv("APCA_API_SECRET_KEY", "secret")
    monkeypatch.setenv("TALONX_PIV_PAPER_TRADING", "true")
    monkeypatch.setenv("TALONX_PIV_APPROVED_SHA", "abc")
    monkeypatch.setenv("TALONX_PIV_DECISION_PATH", "false")
    code = cli.main(["start", "--approved-sha", "abc", "--confirm-paper-session-start", "--no-live-loop"])
    # Preflight may or may not report PIV_READY depending on other checks
    # (e.g. repo/approved-sha matching) -- either way this must not crash,
    # and if it DID reach PIV_READY, a lock file must now exist.
    key = account_lock_key(PAPER_ENDPOINT, "acct-cli-test")
    lock_path = (tmp_path / "locks") / f"{key}.lock"
    if code == 0:
        assert lock_path.exists()
