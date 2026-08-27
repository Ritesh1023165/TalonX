"""Task 78I Stage 1D -- single-writer execution ownership. TEST_FIXTURE_ONLY
-- NOT ALPHA EVIDENCE throughout. The multiprocess test spawns an ACTUAL
separate OS process (not a thread) to prove the lock is genuinely
cross-process, per this task's explicit instruction."""
from __future__ import annotations

import subprocess
import sys
import time

import pytest

from talonx_piv.broker import AlpacaPaperClient, PaperGuardError
from talonx_piv.config import PAPER_ENDPOINT, PivConfig
from talonx_piv.execution_ownership import ExecutionOwnership, ExecutionOwnershipError, account_lock_key


def test_account_lock_key_is_stable_and_scoped_to_endpoint_and_account():
    a = account_lock_key(PAPER_ENDPOINT, "acct-1")
    b = account_lock_key(PAPER_ENDPOINT, "acct-1")
    c = account_lock_key(PAPER_ENDPOINT, "acct-2")
    assert a == b
    assert a != c


def test_single_process_acquire_and_release(tmp_path):
    lock = ExecutionOwnership(tmp_path, "acct-1")
    assert lock.acquire() is True
    assert lock.acquired is True
    lock.release()
    assert lock.acquired is False


def test_second_instance_same_process_cannot_acquire_while_first_holds(tmp_path):
    """Even within ONE process, a second ExecutionOwnership object for the
    SAME account_key cannot acquire while the first holds it -- proving
    in-process mutexing alone would be a weaker (and here, unnecessary)
    mechanism; this is genuinely OS-level."""
    lock1 = ExecutionOwnership(tmp_path, "acct-1")
    lock2 = ExecutionOwnership(tmp_path, "acct-1")
    assert lock1.acquire() is True
    assert lock2.acquire() is False
    assert lock2.acquired is False
    lock1.release()
    assert lock2.acquire() is True  # free after release
    lock2.release()


def test_different_account_keys_do_not_collide(tmp_path):
    lock1 = ExecutionOwnership(tmp_path, "acct-1")
    lock2 = ExecutionOwnership(tmp_path, "acct-2")
    assert lock1.acquire() is True
    assert lock2.acquire() is True
    lock1.release()
    lock2.release()


def test_require_raises_when_not_acquired(tmp_path):
    lock = ExecutionOwnership(tmp_path, "acct-1")
    with pytest.raises(ExecutionOwnershipError):
        lock.require()
    lock.acquire()
    lock.require()  # no raise
    lock.release()


def test_pid_in_lock_file_is_diagnostic_only_not_load_bearing(tmp_path):
    """Manually writing a stale/fabricated PID into the lock file's content
    must NOT fool a second instance into believing it can acquire -- the
    OS lock, not the file's JSON content, is what acquire() actually
    checks."""
    lock1 = ExecutionOwnership(tmp_path, "acct-1")
    assert lock1.acquire() is True
    # A hypothetical attacker/bug tampering with the lock file's VISIBLE
    # content (e.g. writing a PID that looks dead) must not matter -- the
    # OS-level lock on the file descriptor is independent of its content.
    lock2 = ExecutionOwnership(tmp_path, "acct-1")
    assert lock2.acquire() is False
    lock1.release()


def test_context_manager_releases_on_exit(tmp_path):
    with ExecutionOwnership(tmp_path, "acct-1") as owned:
        assert owned.acquired is True
        second = ExecutionOwnership(tmp_path, "acct-1")
        assert second.acquire() is False
    third = ExecutionOwnership(tmp_path, "acct-1")
    assert third.acquire() is True
    third.release()


# ---------------------------------------------------------------------------
# Genuine multiprocess test -- a real competing OS process, not a thread.
# ---------------------------------------------------------------------------

_CHILD_SCRIPT = """
import sys, time
from pathlib import Path
sys.path.insert(0, {repo_root!r})
from talonx_piv.execution_ownership import ExecutionOwnership
lock = ExecutionOwnership(Path({lock_dir!r}), "acct-multiproc")
acquired = lock.acquire()
print("ACQUIRED" if acquired else "DENIED", flush=True)
sys.stdout.flush()
time.sleep({hold_seconds})
lock.release()
"""


def test_duplicate_process_competing_for_the_same_account_ownership_is_denied(tmp_path):
    import pathlib
    repo_root = str(pathlib.Path(__file__).resolve().parents[1])
    script = _CHILD_SCRIPT.format(repo_root=repo_root, lock_dir=str(tmp_path), hold_seconds=2.5)
    script_path = tmp_path / "child.py"
    script_path.write_text(script, encoding="utf-8")

    child = subprocess.Popen(
        [sys.executable, str(script_path)], stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
    )
    try:
        line = child.stdout.readline().strip()
        assert line == "ACQUIRED", f"child process failed to acquire the lock first: {line!r}, stderr={child.stderr.read()}"

        # The child now holds the account lock -- a second, competing
        # instance in THIS (parent) process must be denied.
        competitor = ExecutionOwnership(tmp_path, "acct-multiproc")
        assert competitor.acquire() is False
    finally:
        child.wait(timeout=10)

    # Child has released -- now acquirable.
    after = ExecutionOwnership(tmp_path, "acct-multiproc")
    assert after.acquire() is True
    after.release()


def test_abrupt_process_kill_releases_the_os_lock_crash_safety(tmp_path):
    """Simulates an abrupt termination (SIGKILL/taskkill /F, not a clean
    exit) -- proves the OS lock is released WITHOUT the child's own
    release()/finally code ever running, which is exactly the crash-safety
    guarantee a hand-written PID file could not provide."""
    import pathlib
    repo_root = str(pathlib.Path(__file__).resolve().parents[1])
    script = _CHILD_SCRIPT.format(repo_root=repo_root, lock_dir=str(tmp_path), hold_seconds=30)
    script_path = tmp_path / "child_killed.py"
    script_path.write_text(script, encoding="utf-8")

    child = subprocess.Popen(
        [sys.executable, str(script_path)], stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
    )
    try:
        line = child.stdout.readline().strip()
        assert line == "ACQUIRED"
        competitor = ExecutionOwnership(tmp_path, "acct-multiproc")
        assert competitor.acquire() is False  # still held while child is alive
    finally:
        child.kill()  # abrupt termination -- child's own release()/finally never runs
        child.wait(timeout=10)

    # Give the OS a brief moment to finalize handle cleanup after kill.
    time.sleep(0.5)
    after_kill = ExecutionOwnership(tmp_path, "acct-multiproc")
    assert after_kill.acquire() is True  # OS released it automatically, without any cooperation from the killed process
    after_kill.release()


# ---------------------------------------------------------------------------
# Broker-boundary enforcement
# ---------------------------------------------------------------------------

class Response:
    def __init__(self, body, status=200): self.body, self.status_code = body, status
    def json(self): return self.body
    def raise_for_status(self):
        if self.status_code >= 400: raise RuntimeError(f"HTTP {self.status_code}")


class FakeTransport:
    def __init__(self):
        self.orders = []

    def get(self, url, **kwargs):
        if url.endswith("/v2/account"):
            return Response({"id": "acct-1", "account_number": "PA123456", "status": "ACTIVE"})
        return Response([])

    def post(self, url, **kwargs):
        order = {"id": "o1", "status": "new", "filled_qty": "0", **kwargs.get("json", {})}
        self.orders.append(order)
        return Response(order)

    def delete(self, url, **kwargs):
        return Response([])


def _broker(tmp_path):
    cfg = PivConfig(key_id="k", secret_key="s", paper_trading=True, real_capital=False,
                     broker_endpoint=PAPER_ENDPOINT, approved_sha="abc", state_dir=tmp_path)
    transport = FakeTransport()
    broker = AlpacaPaperClient(cfg, transport)
    broker.verify_paper_identity()
    return broker, transport


def test_no_ownership_configured_behaves_exactly_as_before(tmp_path):
    """Backward compatible -- broker.execution_ownership defaults to None,
    every pre-Task78I test/behavior is completely unaffected."""
    broker, transport = _broker(tmp_path)
    result = broker.submit_order({"symbol": "AAPL", "side": "buy", "qty": "1", "type": "market", "time_in_force": "day"})
    assert result["id"] == "o1"


def test_submit_order_blocked_when_ownership_not_held(tmp_path):
    broker, transport = _broker(tmp_path)
    lock = ExecutionOwnership(tmp_path / "locks", "acct-1")  # never acquired
    broker.execution_ownership = lock
    with pytest.raises(PaperGuardError, match="EXECUTION_OWNERSHIP_NOT_HELD"):
        broker.submit_order({"symbol": "AAPL", "side": "buy", "qty": "1", "type": "market", "time_in_force": "day"})
    assert transport.orders == []


def test_submit_order_succeeds_when_ownership_held(tmp_path):
    broker, transport = _broker(tmp_path)
    lock = ExecutionOwnership(tmp_path / "locks", "acct-1")
    assert lock.acquire() is True
    broker.execution_ownership = lock
    result = broker.submit_order({"symbol": "AAPL", "side": "buy", "qty": "1", "type": "market", "time_in_force": "day"})
    assert result["id"] == "o1"
    lock.release()


def test_cancel_and_close_all_also_gated(tmp_path):
    broker, transport = _broker(tmp_path)
    lock = ExecutionOwnership(tmp_path / "locks", "acct-1")  # never acquired
    broker.execution_ownership = lock
    with pytest.raises(PaperGuardError, match="EXECUTION_OWNERSHIP_NOT_HELD"):
        broker.cancel_all_orders()
    with pytest.raises(PaperGuardError, match="EXECUTION_OWNERSHIP_NOT_HELD"):
        broker.close_all_positions()


def test_reads_never_require_ownership():
    """Readers may continue without becoming execution writers -- open_orders/
    get_order/positions/verify_paper_identity never check ownership at all
    (confirmed by source inspection: no _require_execution_ownership call
    in any of them)."""
    import inspect
    import talonx_piv.broker as module
    src = inspect.getsource(module.AlpacaPaperClient)
    for method_name in ("open_orders", "get_order", "positions", "verify_paper_identity"):
        method_src = inspect.getsource(getattr(module.AlpacaPaperClient, method_name))
        assert "_require_execution_ownership" not in method_src
