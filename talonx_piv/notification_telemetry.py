"""Durable, session-partitioned PIV notification telemetry.

The single state-directory file is a history container. Every update is
selected by the exact ``(session_id, trading_date_et)`` pair and performed
under an inter-process lock before an atomic replace.
"""

from __future__ import annotations

from contextlib import contextmanager
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import threading
import time
from typing import Any, Iterator
from uuid import uuid4

from .execution_ownership import _LockHeldError, _lock_exclusive_nonblocking, _unlock

TELEMETRY_NAME = "piv_notification_telemetry.json"
TELEMETRY_ERROR_NAME = "piv_notification_telemetry_error.json"
SCHEMA_VERSION = 2

_PATH_LOCKS_GUARD = threading.Lock()
_PATH_LOCKS: dict[str, threading.Lock] = {}


class NotificationTelemetryError(RuntimeError):
    """A telemetry boundary could not be durably recorded."""


def _empty(session_id: str, trading_date_et: str) -> dict[str, Any]:
    return {
        "session_id": session_id,
        "trading_date_et": trading_date_et,
        "ownership": {
            "outbound_enabled": False,
            "sender_constructed": False,
            "inbound_poller_constructed": False,
            "inbound_poller_started": False,
        },
        "outbound": {
            "attempts": 0, "successes": 0, "failures": 0,
            "last_attempt_at": None,
        },
        "inbound": {
            "poll_starts": 0, "poll_attempts": 0,
            "poll_successes": 0, "poll_failures": 0,
            "last_start_at": None, "last_attempt_at": None,
            "last_failure_at": None,
        },
        "updated_at": None,
    }


def _empty_store() -> dict[str, Any]:
    return {"schema_version": SCHEMA_VERSION, "sessions": []}


def _atomic_write(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(
        f".{path.name}.{os.getpid()}.{threading.get_ident()}.{uuid4().hex}.tmp"
    )
    try:
        with tmp.open("w", encoding="utf-8", newline="\n") as handle:
            handle.write(json.dumps(payload, indent=2, sort_keys=True) + "\n")
            handle.flush()
            os.fsync(handle.fileno())
        # Windows may transiently deny replace while filesystem/indexing
        # filters release a just-closed handle. Keep the operation atomic,
        # but retry that exact replace for a short bounded interval.
        for attempt in range(20):
            try:
                os.replace(tmp, path)
                break
            except PermissionError:
                if attempt == 19:
                    raise
                time.sleep(0.01)
    finally:
        try:
            tmp.unlink(missing_ok=True)
        except OSError:
            pass


@contextmanager
def _locked(path: Path, *, timeout_seconds: float = 10.0) -> Iterator[None]:
    """Serialize one resolved telemetry path across threads and processes.

    Reuses the repository's proven OS byte-lock primitive (``msvcrt.locking``
    on Windows, ``fcntl.flock`` on POSIX).  The persistent lock file is never
    deleted: ownership belongs to the open, locked file handle, and the kernel
    releases it automatically if its process exits abruptly.
    """
    if timeout_seconds < 0:
        raise NotificationTelemetryError("telemetry lock timeout cannot be negative")
    try:
        resolved_path = path.resolve(strict=False)
    except OSError as exc:
        raise NotificationTelemetryError(
            f"cannot resolve telemetry path {path}: {exc}"
        ) from exc
    lock_path = resolved_path.with_name(f".{resolved_path.name}.lock")
    deadline = time.monotonic() + timeout_seconds
    lock_key = os.path.normcase(str(resolved_path))
    with _PATH_LOCKS_GUARD:
        thread_lock = _PATH_LOCKS.setdefault(lock_key, threading.Lock())

    remaining = max(0.0, deadline - time.monotonic())
    if not thread_lock.acquire(timeout=remaining):
        raise NotificationTelemetryError(
            f"timed out acquiring in-process telemetry lock for {resolved_path}"
        )

    handle = None
    try:
        try:
            lock_path.parent.mkdir(parents=True, exist_ok=True)
        except OSError as exc:
            raise NotificationTelemetryError(
                f"cannot prepare telemetry lock directory {lock_path.parent}: {exc}"
            ) from exc

        last_error: OSError | None = None
        while True:
            acquired = False
            try:
                # A persistent file avoids stale-PID/stale-file recovery logic.
                # ``a+b`` creates it if absent and uses the same inode for the
                # subsequent OS byte lock.  Ensure byte zero exists because
                # Windows ``msvcrt.locking`` locks a byte range.
                handle = open(lock_path, "a+b")
                handle.seek(0, os.SEEK_END)
                if handle.tell() == 0:
                    handle.write(b"\0")
                    handle.flush()
                _lock_exclusive_nonblocking(handle)
                acquired = True
                break
            except _LockHeldError as exc:
                last_error = exc.__cause__ if isinstance(exc.__cause__, OSError) else exc
            except PermissionError as exc:
                # Windows can surface an active sharing/access violation while
                # opening the lock file.  Retry it without a racy existence
                # probe; a persistent permission failure reaches the deadline
                # and fails closed below.
                last_error = exc
            except OSError as exc:
                raise NotificationTelemetryError(
                    f"cannot acquire telemetry lock {lock_path}: {exc}"
                ) from exc
            finally:
                if handle is not None and not acquired:
                    handle.close()
                    handle = None

            if time.monotonic() >= deadline:
                detail = f": {last_error}" if last_error is not None else ""
                raise NotificationTelemetryError(
                    f"timed out acquiring OS telemetry lock {lock_path}{detail}"
                ) from last_error
            time.sleep(min(0.01, max(0.0, deadline - time.monotonic())))

        try:
            yield
        finally:
            if handle is not None:
                _unlock(handle)
    finally:
        if handle is not None:
            handle.close()
        thread_lock.release()


def _read_store(path: Path) -> tuple[str, dict[str, Any] | None]:
    if not path.exists():
        return "MISSING", None
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError, UnicodeError):
        return "CORRUPT", None
    if not isinstance(raw, dict):
        return "CORRUPT", None
    if raw.get("schema_version") == SCHEMA_VERSION and isinstance(raw.get("sessions"), list):
        if not all(isinstance(row, dict) for row in raw["sessions"]):
            return "CORRUPT", None
        return "OK", raw
    # R1 legacy shape: retain it as history on the first R2 write.
    if "session_id" in raw and "ownership" in raw:
        return "LEGACY", {"schema_version": SCHEMA_VERSION, "sessions": [raw]}
    return "CORRUPT", None


def select_telemetry(
    state_dir: Path, *, session_id: str, trading_date_et: str,
) -> tuple[str, dict[str, Any] | None]:
    """Return an exact record plus an explicit fail-closed selection status."""
    error_path = Path(state_dir) / TELEMETRY_ERROR_NAME
    if error_path.exists():
        try:
            error = json.loads(error_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError, UnicodeError):
            return "WRITE_ERROR", None
        if (
            error.get("session_id") == session_id
            and error.get("trading_date_et") == trading_date_et
        ):
            return "WRITE_ERROR", None
    status, store = _read_store(Path(state_dir) / TELEMETRY_NAME)
    if store is None:
        return status, None
    matches = [
        row for row in store["sessions"]
        if row.get("session_id") == session_id
        and row.get("trading_date_et") == trading_date_et
    ]
    if len(matches) > 1:
        return "AMBIGUOUS", None
    if len(matches) == 1:
        return "OK", matches[0]
    same_session = [row for row in store["sessions"] if row.get("session_id") == session_id]
    return ("WRONG_DATE" if same_session else "WRONG_SESSION"), None


def load_telemetry(
    state_dir: Path, *, session_id: str | None = None,
    trading_date_et: str | None = None,
) -> dict[str, Any] | None:
    """Read one record; selector-free reads fail on multi-session ambiguity."""
    if (session_id is None) != (trading_date_et is None):
        return None
    if session_id is not None and trading_date_et is not None:
        status, row = select_telemetry(
            state_dir, session_id=session_id, trading_date_et=trading_date_et,
        )
        return row if status == "OK" else None
    status, store = _read_store(Path(state_dir) / TELEMETRY_NAME)
    if status not in {"OK", "LEGACY"} or store is None or len(store["sessions"]) != 1:
        return None
    return store["sessions"][0]


def _deep_merge(base: dict[str, Any], updates: dict[str, Any]) -> None:
    for key, value in updates.items():
        if isinstance(value, dict) and isinstance(base.get(key), dict):
            _deep_merge(base[key], value)
        else:
            base[key] = value


def merge_telemetry(
    state_dir: Path,
    *,
    session_id: str,
    trading_date_et: str,
    ownership: dict[str, Any] | None = None,
    outbound: dict[str, Any] | None = None,
    inbound: dict[str, Any] | None = None,
    outbound_delta: dict[str, int] | None = None,
    inbound_delta: dict[str, int] | None = None,
) -> dict[str, Any]:
    """Locked atomic read-modify-write for one exact session partition."""
    if not session_id or not trading_date_et:
        raise NotificationTelemetryError("session_id and trading_date_et are required")
    path = Path(state_dir) / TELEMETRY_NAME
    try:
        with _locked(path):
            status, store = _read_store(path)
            if status == "CORRUPT":
                raise NotificationTelemetryError(f"refusing to overwrite corrupt {path}")
            store = store or _empty_store()
            matches = [
                row for row in store["sessions"]
                if row.get("session_id") == session_id
                and row.get("trading_date_et") == trading_date_et
            ]
            if len(matches) > 1:
                raise NotificationTelemetryError(
                    f"ambiguous telemetry partition for {session_id!r} on {trading_date_et!r}"
                )
            current = matches[0] if matches else _empty(session_id, trading_date_et)
            if not matches:
                store["sessions"].append(current)
            if ownership:
                _deep_merge(current.setdefault("ownership", {}), ownership)
            if outbound:
                _deep_merge(current.setdefault("outbound", {}), outbound)
            if inbound:
                _deep_merge(current.setdefault("inbound", {}), inbound)
            for section, delta in (("outbound", outbound_delta), ("inbound", inbound_delta)):
                if not delta:
                    continue
                target = current.setdefault(section, {})
                for key, increment in delta.items():
                    target[key] = int(target.get(key, 0) or 0) + int(increment)
            current["updated_at"] = datetime.now(timezone.utc).isoformat()
            _atomic_write(path, store)
            error_path = Path(state_dir) / TELEMETRY_ERROR_NAME
            if error_path.exists():
                try:
                    error = json.loads(error_path.read_text(encoding="utf-8"))
                except (OSError, json.JSONDecodeError, UnicodeError):
                    error = {}
                if (
                    error.get("session_id") == session_id
                    and error.get("trading_date_et") == trading_date_et
                ):
                    error_path.unlink(missing_ok=True)
            return current
    except NotificationTelemetryError:
        raise
    except OSError as exc:
        raise NotificationTelemetryError(f"telemetry write failed for {path}: {exc}") from exc


class PivInboundPollTelemetry:
    """Optional hook used by the existing Telegram listener in PIV only."""

    def __init__(self, state_dir: Path, session_id: str, trading_date_et: str) -> None:
        self.state_dir = Path(state_dir)
        self.session_id = session_id
        self.trading_date_et = trading_date_et
        self.last_error: str | None = None

    def _merge(self, **updates: Any) -> None:
        try:
            merge_telemetry(
                self.state_dir, session_id=self.session_id,
                trading_date_et=self.trading_date_et, **updates,
            )
            self.last_error = None
        except Exception as exc:
            self.last_error = f"{type(exc).__name__}: {exc}"
            self._write_error_marker(self.last_error)
            raise NotificationTelemetryError(self.last_error) from exc

    def _write_error_marker(self, detail: str) -> None:
        """Best-effort independent fail-closed marker for assessment.

        A request is never made after a primary telemetry write failure.
        This separate marker also prevents a prior zero snapshot from being
        mistaken for fully verified evidence of the failed runtime boundary.
        """
        path = self.state_dir / TELEMETRY_ERROR_NAME
        payload = {
            "session_id": self.session_id,
            "trading_date_et": self.trading_date_et,
            "recorded_at": datetime.now(timezone.utc).isoformat(),
            "detail": detail,
        }
        tmp = path.with_name(f".{path.name}.{uuid4().hex}.tmp")
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            with tmp.open("w", encoding="utf-8", newline="\n") as handle:
                handle.write(json.dumps(payload, indent=2, sort_keys=True) + "\n")
            os.replace(tmp, path)
        except OSError:
            # The in-process ``last_error`` remains visible and the guarded
            # external request is still not issued.
            pass
        finally:
            try:
                tmp.unlink(missing_ok=True)
            except OSError:
                pass

    def poller_started(self) -> None:
        now = datetime.now(timezone.utc).isoformat()
        self._merge(
            ownership={"inbound_poller_constructed": True, "inbound_poller_started": True},
            inbound_delta={"poll_starts": 1}, inbound={"last_start_at": now},
        )

    def before_get_updates(self) -> None:
        self._merge(
            inbound_delta={"poll_attempts": 1},
            inbound={"last_attempt_at": datetime.now(timezone.utc).isoformat()},
        )

    def get_updates_succeeded(self) -> None:
        self._merge(inbound_delta={"poll_successes": 1})

    def get_updates_failed(self) -> None:
        self._merge(
            inbound_delta={"poll_failures": 1},
            inbound={"last_failure_at": datetime.now(timezone.utc).isoformat()},
        )
