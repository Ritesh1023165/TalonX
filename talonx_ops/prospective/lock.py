"""
Atomic single-writer lock for the prospective V2 stack.

A process scan alone cannot protect two ``prospective start`` invocations that
race: both scan, both see nothing, both spawn -> two supervisors + two V2
companions writing one ``v2_lane.db``.

``SingleWriterLock`` uses ``os.open(O_CREAT | O_EXCL)`` -- the OS guarantees
exactly one creator -- keyed on the V2 ledger identity. The lock is acquired
before the check, held across spawn + pid registration, and released only by a
clean ``stop_stack`` (or the partial-failure cleanup). A stale lock (owner PID
gone, or a different ledger path) can be broken; a lock whose owner is still
alive is NEVER broken, not even with ``--force``.
"""
from __future__ import annotations

import json
import os
import socket
import time
from datetime import datetime, timezone
from pathlib import Path


class ConcurrentStartError(RuntimeError):
    """Another live stack already owns this V2 ledger."""


class StaleLockError(RuntimeError):
    """The lock file exists but its owner cannot be verified gone."""


def _pid_alive(pid: int) -> bool:
    try:
        import psutil

        return psutil.pid_exists(pid) and psutil.Process(pid).is_running()
    except Exception:  # noqa: BLE001
        try:
            os.kill(pid, 0)          # POSIX fallback
            return True
        except (OSError, ProcessLookupError):
            return False
        except Exception:  # noqa: BLE001
            return True              # unknown -> assume alive (fail safe)


class SingleWriterLock:
    def __init__(self, ledger_path: str | os.PathLike):
        self.ledger_path = Path(ledger_path).resolve()
        # lock lives next to the ledger, keyed on its identity
        self.lock_path = self.ledger_path.with_suffix(self.ledger_path.suffix + ".startlock")
        self._held = False
        self._payload: dict | None = None

    # ------------------------------------------------------------------
    def read_owner(self) -> dict | None:
        try:
            return json.loads(self.lock_path.read_text(encoding="utf-8"))
        except Exception:  # noqa: BLE001
            return None

    def _owner_state(self) -> str:
        """'free' | 'live' | 'stale'."""
        if not self.lock_path.exists():
            return "free"
        info = self.read_owner()
        if not info:
            return "stale"
        if str(info.get("ledger_path", "")) != str(self.ledger_path):
            return "stale"                      # a lock for a different ledger
        pid = info.get("pid")
        if isinstance(pid, int) and _pid_alive(pid):
            return "live"
        return "stale"

    # ------------------------------------------------------------------
    def acquire(self, *, force: bool = False, break_stale: bool = True) -> "SingleWriterLock":
        state = self._owner_state()
        if state == "live":
            info = self.read_owner() or {}
            raise ConcurrentStartError(
                f"a live stack (pid {info.get('pid')}, since {info.get('started_utc')}) "
                f"already owns {self.ledger_path.name}. --force does NOT override an "
                f"active ledger writer -- run 'prospective close' first."
            )
        if state == "stale":
            if not (break_stale or force):
                raise StaleLockError(
                    f"stale lock at {self.lock_path} (owner gone); pass force/break_stale"
                )
            # owner verified gone (or ledger mismatch) -> safe to remove
            try:
                self.lock_path.unlink()
            except FileNotFoundError:
                pass

        payload = {
            "pid": os.getpid(),
            "host": socket.gethostname(),
            "started_utc": datetime.now(timezone.utc).isoformat(),
            "ledger_path": str(self.ledger_path),
        }
        try:
            fd = os.open(self.lock_path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o644)
        except FileExistsError as exc:
            # someone created it between our check and here -- re-evaluate
            if self._owner_state() == "live":
                info = self.read_owner() or {}
                raise ConcurrentStartError(
                    f"a live stack (pid {info.get('pid')}) won the lock race for "
                    f"{self.ledger_path.name}"
                ) from exc
            raise ConcurrentStartError("lock race lost; retry after resolving the other start") from exc
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            json.dump(payload, fh, indent=2)
        self._held = True
        self._payload = payload
        return self

    def release(self) -> None:
        if not self._held:
            return
        info = self.read_owner()
        if info and info.get("pid") == os.getpid():
            try:
                self.lock_path.unlink()
            except FileNotFoundError:
                pass
        self._held = False

    def __enter__(self):
        return self.acquire()

    def __exit__(self, *exc):
        self.release()
        return False
