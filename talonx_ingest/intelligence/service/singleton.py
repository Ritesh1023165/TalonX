"""
talonx_ingest.intelligence.service.singleton
============================================
Process-singleton lock + heartbeat for the intelligence ingest service
(Phase 20). No dependency on the trading engine's supervisor.

* ``SingletonLock`` — a pid lock file under ``<state_dir>/service.lock``.
  A second ``acquire()`` while a *live* pid holds it returns ``False``
  (unless ``force=True``); a lock left by a dead process is reclaimed.
* ``write_heartbeat`` / ``read_heartbeat`` — a small JSON file the
  ``status`` command and any external monitor can read.
"""
from __future__ import annotations

import json
import os
import socket
import sys
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path


def _pid_alive(pid: int) -> bool:
    if pid <= 0:
        return False
    if os.name == "nt":
        try:
            import ctypes

            PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
            STILL_ACTIVE = 259
            k32 = ctypes.windll.kernel32  # type: ignore[attr-defined]
            handle = k32.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, False, pid)
            if not handle:
                return False
            code = ctypes.c_ulong()
            ok = k32.GetExitCodeProcess(handle, ctypes.byref(code))
            k32.CloseHandle(handle)
            return bool(ok) and code.value == STILL_ACTIVE
        except Exception:  # noqa: BLE001 - be conservative: assume not alive
            return False
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


@dataclass
class LockInfo:
    pid: int
    host: str
    started_at_utc: str
    argv: list[str]


class SingletonLock:
    def __init__(self, lock_path: str | Path):
        self.path = Path(lock_path)
        self._held = False

    def read(self) -> LockInfo | None:
        if not self.path.is_file():
            return None
        try:
            d = json.loads(self.path.read_text(encoding="utf-8"))
            return LockInfo(
                pid=int(d.get("pid", -1)),
                host=str(d.get("host", "")),
                started_at_utc=str(d.get("started_at_utc", "")),
                argv=list(d.get("argv", [])),
            )
        except (OSError, ValueError):
            return None

    def acquire(self, *, force: bool = False) -> bool:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        existing = self.read()
        if existing and not force:
            same_host = existing.host == socket.gethostname()
            if same_host and _pid_alive(existing.pid):
                return False
        payload = {
            "pid": os.getpid(),
            "host": socket.gethostname(),
            "started_at_utc": datetime.now(timezone.utc).isoformat(),
            "argv": list(sys.argv),
        }
        self.path.write_text(json.dumps(payload), encoding="utf-8")
        self._held = True
        return True

    def release(self) -> None:
        if not self._held:
            return
        try:
            cur = self.read()
            if cur and cur.pid == os.getpid():
                self.path.unlink(missing_ok=True)
        except OSError:
            pass
        self._held = False

    def __enter__(self) -> "SingletonLock":
        return self

    def __exit__(self, *exc) -> None:
        self.release()


def write_heartbeat(path: str | Path, payload: dict) -> None:
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    body = dict(payload)
    body.setdefault("pid", os.getpid())
    body["heartbeat_at_utc"] = datetime.now(timezone.utc).isoformat()
    body["heartbeat_monotonic"] = round(time.monotonic(), 3)
    try:
        p.write_text(json.dumps(body, indent=2), encoding="utf-8")
    except OSError:
        pass


def read_heartbeat(path: str | Path) -> dict | None:
    p = Path(path)
    if not p.is_file():
        return None
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
