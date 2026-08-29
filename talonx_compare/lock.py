"""Task 83-R1 §6.6 -- collector-owned concurrency control.

A single advisory lock file that EVERY collector write path takes --
``collect_once`` and the long-running ``CollectorService`` alike. It is
collector-owned (lives under the collector state dir, never an
Original/PIV lock), self-heals when its recorded PID is gone, and is
released on clean exit.
"""

from __future__ import annotations

import contextlib
import json
import os
from pathlib import Path
import time


class CollectorLockError(RuntimeError):
    pass


def _pid_alive(pid: int) -> bool:
    if pid <= 0:
        return False
    try:
        os.kill(pid, 0)
        return True
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    except OSError:
        # Windows: os.kill with signal 0 raises OSError for a live PID it
        # cannot signal; fall back to OpenProcess.
        try:
            import ctypes

            handle = ctypes.windll.kernel32.OpenProcess(0x1000, False, pid)  # type: ignore[attr-defined]
            if handle:
                ctypes.windll.kernel32.CloseHandle(handle)  # type: ignore[attr-defined]
                return True
            return False
        except Exception:  # noqa: BLE001
            return False


class CollectorLock:
    def __init__(self, path: Path, *, stale_after_seconds: float = 900.0,
                 acquire_wait: float = 0.0) -> None:
        self.path = Path(path)
        self.stale_after = stale_after_seconds
        self._acquire_wait = acquire_wait
        self._held = False

    def _holder(self) -> tuple[int, float] | None:
        try:
            rec = json.loads(self.path.read_text(encoding="utf-8"))
            return int(rec.get("pid", -1)), float(rec.get("acquired_at", 0.0))
        except (OSError, ValueError, json.JSONDecodeError):
            return None

    def acquire(self, *, wait_seconds: float = 0.0, poll: float = 0.05) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        deadline = time.monotonic() + max(0.0, wait_seconds)
        while True:
            if self.path.exists():
                holder = self._holder()
                if holder is not None:
                    pid, acquired_at = holder
                    fresh = (time.time() - acquired_at) < self.stale_after
                    if pid != os.getpid() and _pid_alive(pid) and fresh:
                        if time.monotonic() < deadline:
                            time.sleep(poll)
                            continue
                        raise CollectorLockError(
                            f"another collector holds {self.path} (pid {pid})")
                # stale / dead holder -> reclaim
            try:
                self.path.write_text(
                    json.dumps({"pid": os.getpid(), "acquired_at": time.time()}),
                    encoding="utf-8",
                )
                self._held = True
                return
            except OSError as exc:  # pragma: no cover -- filesystem race
                if time.monotonic() < deadline:
                    time.sleep(poll)
                    continue
                raise CollectorLockError(str(exc)) from exc

    def release(self) -> None:
        if self._held:
            with contextlib.suppress(OSError):
                self.path.unlink()
            self._held = False

    def __enter__(self) -> "CollectorLock":
        self.acquire(wait_seconds=self._acquire_wait)
        return self

    def __exit__(self, *exc: object) -> None:
        self.release()
