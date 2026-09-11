"""Task 78I Stage 1D -- single-writer execution ownership.

Enforced at the one true broker-mutation chokepoint
(`AlpacaPaperClient.submit_order`/`cancel_all_orders`/`close_all_positions`
-- see `broker.py`), not at `PaperLifecycle` -- `eod_lifecycle.py` calls
`lifecycle.broker.cancel_all_orders()`/`close_all_positions()` directly,
bypassing any gate placed only on `PaperLifecycle`'s own methods, so the
broker client itself is the only place that genuinely covers normal
orders, probes, manual CLI paths, recovery, and EOD uniformly.

Scope is the (broker_endpoint, account_id) pair, NEVER a session directory
or `state_dir` -- two application instances configured with DIFFERENT
`state_dir` but the SAME underlying Alpaca paper account must still
collide on the SAME lock, because they would otherwise both believe they
are free to submit orders against the one account. `account_id` is only
known AFTER `AlpacaPaperClient.verify_paper_identity()` succeeds (a
read-only GET), so ownership is acquired AFTER identity verification,
before any mutation is attempted.

Crash safety: uses the operating system's own advisory file lock
(`msvcrt.locking` on Windows, `fcntl.flock` on POSIX) -- NOT a hand-written
PID file. An OS-level lock is automatically released by the kernel when
the holding process exits for ANY reason, including a crash or an abrupt
host/process termination, without requiring any in-process cleanup code (a
`finally` block, an atexit hook) to run at all. A PID file, by contrast,
can be left behind stale after a crash, and "is this PID still alive"
checks are inherently racy (PID reuse across reboots/time) -- this is why
"do not assume a stored PID proves ownership" holds here: the PID written
into the lock file is diagnostic/operator-visible ONLY, never consulted by
`acquire()`'s own pass/fail logic (that logic is solely the OS lock call).

Recovery implication (documented, not solved by this module alone): an
abrupt termination releases the LOCK immediately, but does NOT itself
prove the broker's true state (an in-flight order at the moment of the
crash may or may not have reached the broker). The next process to acquire
ownership must still run `PaperLifecycle.reconcile()` (which now also
resolves any `UNCONFIRMED_TIMEOUT` order -- see Task 77I Stage 1) BEFORE
treating the account as known-safe to trade in -- see
`multiprocess_ownership_evidence.json`'s own "abrupt termination" section
and the supervisor's startup sequence (Stage 2).
"""

from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import json
import os
import sys
from pathlib import Path
from typing import Any


def account_lock_key(broker_endpoint: str, account_id: str) -> str:
    body = f"{broker_endpoint}|{account_id}"
    return hashlib.sha256(body.encode()).hexdigest()[:24]


class ExecutionOwnershipError(RuntimeError):
    pass


class _LockHeldError(RuntimeError):
    pass


def _lock_exclusive_nonblocking(fh) -> None:
    fh.seek(0)
    if sys.platform == "win32":
        import msvcrt
        try:
            msvcrt.locking(fh.fileno(), msvcrt.LK_NBLCK, 1)
        except OSError as exc:
            raise _LockHeldError from exc
    else:
        import fcntl
        try:
            fcntl.flock(fh.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError as exc:
            raise _LockHeldError from exc


def _unlock(fh) -> None:
    if sys.platform == "win32":
        import msvcrt
        fh.seek(0)
        try:
            msvcrt.locking(fh.fileno(), msvcrt.LK_UNLCK, 1)
        except OSError:
            pass
    else:
        import fcntl
        fcntl.flock(fh.fileno(), fcntl.LOCK_UN)


class ExecutionOwnership:
    """Acquire ONCE at startup (after identity verification, before any
    mutation), hold for the process's entire lifetime, `release()`
    explicitly on graceful shutdown. `acquired` is False until a
    successful `acquire()` -- every mutating broker call must check it."""

    def __init__(self, lock_dir: Path, account_key: str, *, owner_label: str | None = None) -> None:
        self.lock_dir = lock_dir
        self.account_key = account_key
        self.lock_path = lock_dir / f"{account_key}.lock"
        self.owner_label = owner_label or f"pid={os.getpid()}"
        self._fh = None
        self.acquired = False

    def acquire(self) -> bool:
        """Non-blocking. Returns True iff this process now holds exclusive
        ownership of `account_key`. A lock already held by another live
        process is the EXPECTED, handled case (returns False) -- this
        never raises for contention, only for an unexpected I/O failure."""
        self.lock_dir.mkdir(parents=True, exist_ok=True)
        if not self.lock_path.exists():
            self.lock_path.write_bytes(b"\0")
        fh = open(self.lock_path, "r+b")
        try:
            _lock_exclusive_nonblocking(fh)
        except _LockHeldError:
            fh.close()
            self.acquired = False
            return False
        fh.seek(0)
        fh.truncate()
        payload = json.dumps({
            "owner_label": self.owner_label, "pid": os.getpid(),
            "acquired_at": datetime.now(timezone.utc).isoformat(), "account_key": self.account_key,
        }).encode()
        fh.write(payload if payload else b"\0")
        fh.flush()
        self._fh = fh
        self.acquired = True
        return True

    def release(self) -> None:
        if self._fh is not None:
            try:
                _unlock(self._fh)
            finally:
                self._fh.close()
                self._fh = None
        self.acquired = False

    def require(self) -> None:
        """Raise if this process does NOT currently hold ownership -- the
        check every mutating broker call makes. `None` ownership (no
        ExecutionOwnership configured at all -- e.g. most existing tests)
        is a separate, backward-compatible case handled by the caller, not
        here."""
        if not self.acquired:
            raise ExecutionOwnershipError(
                f"execution ownership is not held for account_key={self.account_key} -- "
                "another process may already own it, or ownership was never acquired"
            )

    def __enter__(self) -> "ExecutionOwnership":
        if not self.acquire():
            raise ExecutionOwnershipError(f"execution ownership already held for account_key={self.account_key}")
        return self

    def __exit__(self, *exc: Any) -> None:
        self.release()
