"""Opt-in, fail-closed network isolation for the TalonX pytest suite.

The guard is deliberately implemented with the standard library and is
installed only when ``TALONX_TEST_NETWORK_GUARD=1``.  It rejects unknown or
non-loopback destinations before DNS resolution and records every decision in
the explicitly requested report file.
"""

from __future__ import annotations

import asyncio
import ipaddress
import json
import os
import socket
import tempfile
import threading
import time
from collections.abc import Iterator, Mapping
from contextlib import contextmanager
from pathlib import Path
from typing import Any


class NetworkGuardError(RuntimeError):
    """Base class for deterministic guard failures."""


class NetworkBlockedError(NetworkGuardError):
    """Raised before a non-loopback DNS lookup or connection attempt."""


class GuardInitializationError(NetworkGuardError):
    """Raised when every required low-level patch cannot be installed."""


_TARGETS = {
    "socket.socket.connect": (socket.socket, "connect"),
    "socket.socket.connect_ex": (socket.socket, "connect_ex"),
    "socket.create_connection": (socket, "create_connection"),
    "socket.getaddrinfo": (socket, "getaddrinfo"),
    "asyncio.BaseEventLoop.create_connection": (asyncio.BaseEventLoop, "create_connection"),
    "asyncio.BaseEventLoop.sock_connect": (asyncio.BaseEventLoop, "sock_connect"),
}

# Reporting is intentionally single-process.  Every NetworkGuard instance in
# this process that resolves to the same report path shares one writer lock;
# no cross-process serialization claim is made.
_REPORT_PATH_LOCKS_GUARD = threading.Lock()
_REPORT_PATH_LOCKS: dict[str, threading.RLock] = {}
_REPLACE_ATTEMPTS = 50


def _report_path_lock(path: Path) -> threading.RLock:
    key = os.path.normcase(str(path.resolve()))
    with _REPORT_PATH_LOCKS_GUARD:
        return _REPORT_PATH_LOCKS.setdefault(key, threading.RLock())


def _atomic_replace(source: Path, destination: Path) -> None:
    """Replace atomically, tolerating only transient Windows sharing denial.

    Readers on Windows can briefly prevent replacement of an existing file.
    The same writer-owned temporary file is retried for a bounded interval;
    persistent denial and every non-permission failure remain visible.
    """
    for attempt in range(_REPLACE_ATTEMPTS):
        try:
            os.replace(source, destination)
            return
        except PermissionError:
            if attempt == _REPLACE_ATTEMPTS - 1:
                raise
            time.sleep(min(0.001 * (2 ** min(attempt, 4)), 0.02))


def _destination(address: Any) -> tuple[Any, Any]:
    if isinstance(address, tuple) and address:
        return address[0], address[1] if len(address) > 1 else None
    return None, None  # local/Unix-domain address, not an IP destination


def _display_host(host: Any) -> str:
    if isinstance(host, bytes):
        host = host.decode("ascii", errors="replace")
    return str(host)[:255]


def _is_loopback(host: Any) -> bool:
    if host is None:
        return True
    if isinstance(host, bytes):
        try:
            host = host.decode("ascii")
        except UnicodeDecodeError:
            return False
    if not isinstance(host, str):
        return False
    normalized = host.strip().lower()
    if normalized == "localhost":
        return True
    if normalized.startswith("[") and normalized.endswith("]"):
        normalized = normalized[1:-1]
    if "%" in normalized:  # IPv6 scope identifier
        normalized = normalized.split("%", 1)[0]
    try:
        parsed = ipaddress.ip_address(normalized)
    except ValueError:
        return False
    if isinstance(parsed, ipaddress.IPv4Address):
        return parsed in ipaddress.ip_network("127.0.0.0/8")
    return parsed == ipaddress.ip_address("::1")


class NetworkGuard:
    """Patch the lowest common socket and asyncio connection boundaries."""

    def __init__(
        self,
        report_path: str | os.PathLike[str] | None = None,
        *,
        target_overrides: Mapping[str, Any] | None = None,
    ) -> None:
        self.report_path = Path(report_path).resolve() if report_path else None
        self._target_overrides = dict(target_overrides or {})
        self._originals: dict[str, Any] = {}
        self._events: list[dict[str, Any]] = []
        self._expected_labels: list[str] = []
        self._expected_declarations: dict[str, int] = {}
        self._lock = threading.RLock()
        self.initialized = False
        self.installation_succeeded = False
        self.initialization_error: str | None = None

    def install(self) -> None:
        if self.initialized:
            return
        resolved: dict[str, Any] = {}
        for name, (owner, attribute) in _TARGETS.items():
            candidate = (
                self._target_overrides[name]
                if name in self._target_overrides
                else getattr(owner, attribute, None)
            )
            if not callable(candidate):
                self._initialization_failed(f"missing or non-callable guard target: {name}")
            resolved[name] = candidate

        self._originals = resolved
        replacements = self._replacements()
        patched: list[str] = []
        try:
            for name, (owner, attribute) in _TARGETS.items():
                setattr(owner, attribute, replacements[name])
                patched.append(name)
        except Exception as exc:  # pragma: no cover - platform failure path
            for name in reversed(patched):
                owner, attribute = _TARGETS[name]
                setattr(owner, attribute, self._originals[name])
            self._originals.clear()
            self._initialization_failed(
                f"failed to install guard target {name}: {type(exc).__name__}"
            )

        self.initialized = True
        self.installation_succeeded = True
        self.initialization_error = None
        self.write_report()

    def uninstall(self) -> None:
        if not self.initialized:
            self.write_report()
            return
        for name, original in reversed(tuple(self._originals.items())):
            owner, attribute = _TARGETS[name]
            setattr(owner, attribute, original)
        self._originals.clear()
        self.initialized = False
        self.write_report()

    def _initialization_failed(self, message: str) -> None:
        self.initialized = False
        self.initialization_error = message
        self._record(
            "guard_initialization_failure",
            path="guard.install",
            host=None,
            port=None,
            label=None,
            detail=message,
        )
        raise GuardInitializationError(message)

    def _replacements(self) -> dict[str, Any]:
        guard = self
        original_connect = self._originals["socket.socket.connect"]
        original_connect_ex = self._originals["socket.socket.connect_ex"]
        original_create_connection = self._originals["socket.create_connection"]
        original_getaddrinfo = self._originals["socket.getaddrinfo"]
        original_async_create = self._originals["asyncio.BaseEventLoop.create_connection"]
        original_async_sock = self._originals["asyncio.BaseEventLoop.sock_connect"]

        def guarded_connect(sock: socket.socket, address: Any) -> Any:
            host, port = _destination(address)
            guard.check_destination("socket.socket.connect", host, port)
            return original_connect(sock, address)

        def guarded_connect_ex(sock: socket.socket, address: Any) -> Any:
            host, port = _destination(address)
            guard.check_destination("socket.socket.connect_ex", host, port)
            return original_connect_ex(sock, address)

        def guarded_create_connection(address: Any, *args: Any, **kwargs: Any) -> Any:
            host, port = _destination(address)
            guard.check_destination("socket.create_connection", host, port)
            return original_create_connection(address, *args, **kwargs)

        def guarded_getaddrinfo(host: Any, port: Any, *args: Any, **kwargs: Any) -> Any:
            guard.check_destination("socket.getaddrinfo", host, port)
            return original_getaddrinfo(host, port, *args, **kwargs)

        async def guarded_async_create(
            loop: asyncio.BaseEventLoop,
            protocol_factory: Any,
            host: Any = None,
            port: Any = None,
            *args: Any,
            **kwargs: Any,
        ) -> Any:
            guard.check_destination("asyncio.BaseEventLoop.create_connection", host, port)
            return await original_async_create(
                loop, protocol_factory, host, port, *args, **kwargs
            )

        async def guarded_async_sock(
            loop: asyncio.BaseEventLoop, sock: socket.socket, address: Any
        ) -> Any:
            host, port = _destination(address)
            guard.check_destination("asyncio.BaseEventLoop.sock_connect", host, port)
            return await original_async_sock(loop, sock, address)

        return {
            "socket.socket.connect": guarded_connect,
            "socket.socket.connect_ex": guarded_connect_ex,
            "socket.create_connection": guarded_create_connection,
            "socket.getaddrinfo": guarded_getaddrinfo,
            "asyncio.BaseEventLoop.create_connection": guarded_async_create,
            "asyncio.BaseEventLoop.sock_connect": guarded_async_sock,
        }

    def check_destination(self, path: str, host: Any, port: Any = None) -> None:
        if _is_loopback(host):
            self._record(
                "permitted_loopback_connection",
                path=path,
                host=host,
                port=port,
                label=None,
            )
            return

        with self._lock:
            label = self._expected_labels[-1] if self._expected_labels else None
        kind = "expected_negative_control_block" if label else "unexpected_external_attempt"
        self._record(kind, path=path, host=host, port=port, label=label)
        category = "expected negative control" if label else "unexpected external attempt"
        raise NetworkBlockedError(
            f"TalonX test network guard blocked {category} via {path} "
            f"to host={_display_host(host)!r} port={port!r}"
        )

    @contextmanager
    def expect_block(self, label: str, *, expected_attempts: int = 1) -> Iterator[None]:
        if not label or not label.replace("_", "").replace("-", "").isalnum():
            raise ValueError("negative-control label must be a non-empty identifier")
        if expected_attempts < 1:
            raise ValueError("expected_attempts must be at least one")
        before = self.snapshot()["observed_expected_negative_control_blocks"].get(label, 0)
        with self._lock:
            self._expected_declarations[label] = (
                self._expected_declarations.get(label, 0) + expected_attempts
            )
            self._expected_labels.append(label)
        self.write_report()
        try:
            yield
        finally:
            with self._lock:
                popped = self._expected_labels.pop()
            if popped != label:  # pragma: no cover - defensive concurrency invariant
                raise AssertionError("network guard negative-control stack was corrupted")
            after = self.snapshot()["observed_expected_negative_control_blocks"].get(
                label, 0
            )
            observed = after - before
            if observed != expected_attempts:
                raise AssertionError(
                    f"negative control {label!r} expected {expected_attempts} guarded "
                    f"attempt(s), observed {observed}"
                )

    def _record(
        self,
        kind: str,
        *,
        path: str,
        host: Any,
        port: Any,
        label: str | None,
        detail: str | None = None,
    ) -> None:
        event = {
            "sequence": 0,
            "kind": kind,
            "path": path,
            "host": None if host is None else _display_host(host),
            "port": port if isinstance(port, (int, str)) or port is None else str(port),
            "label": label,
        }
        if detail is not None:
            event["detail"] = detail
        with self._lock:
            event["sequence"] = len(self._events) + 1
            self._events.append(event)
        self.write_report()

    def snapshot(self) -> dict[str, Any]:
        with self._lock:
            events = [dict(event) for event in self._events]
            declarations = dict(self._expected_declarations)
            installation_succeeded = self.installation_succeeded
            initialization_error = self.initialization_error
        observed: dict[str, int] = {}
        for event in events:
            if event["kind"] == "expected_negative_control_block":
                label = event["label"]
                observed[label] = observed.get(label, 0) + 1
        counters = {
            "unexpected_external_attempts": sum(
                event["kind"] == "unexpected_external_attempt" for event in events
            ),
            "expected_negative_control_blocks": sum(observed.values()),
            "permitted_loopback_connections": sum(
                event["kind"] == "permitted_loopback_connection" for event in events
            ),
            "guard_initialization_failures": sum(
                event["kind"] == "guard_initialization_failure" for event in events
            ),
        }
        return {
            "schema_version": 1,
            "guard_enabled": True,
            "guard_initialized_successfully": (
                installation_succeeded and initialization_error is None
            ),
            "initialization_error": initialization_error,
            "counters": counters,
            "expected_negative_controls": dict(sorted(declarations.items())),
            "observed_expected_negative_control_blocks": dict(sorted(observed.items())),
            "negative_controls_reconciled": declarations == observed,
            "events": events,
        }

    def assert_reconciled(self) -> None:
        report = self.snapshot()
        declared = report["expected_negative_controls"]
        observed = report["observed_expected_negative_control_blocks"]
        if declared != observed:
            raise AssertionError(
                f"expected negative controls do not reconcile: {declared!r} != {observed!r}"
            )
        if report["counters"]["unexpected_external_attempts"] != 0:
            raise AssertionError("unexpected external network attempts were recorded")
        if report["counters"]["guard_initialization_failures"] != 0:
            raise AssertionError("the active network guard recorded an initialization failure")

    def read_report(self) -> dict[str, Any]:
        """Read one complete report within the documented process boundary."""
        if self.report_path is None:
            raise NetworkGuardError("network guard report path is not configured")
        with _report_path_lock(self.report_path):
            return json.loads(self.report_path.read_text(encoding="utf-8"))

    def write_report(self) -> None:
        if self.report_path is None:
            return
        report_path = self.report_path
        with _report_path_lock(report_path):
            # Snapshot only after acquiring the path writer lock. This ensures
            # an older in-memory view can never replace a newer completed one.
            report = self.snapshot()
            report_path.parent.mkdir(parents=True, exist_ok=True)
            descriptor = -1
            temporary: Path | None = None
            try:
                descriptor, name = tempfile.mkstemp(
                    prefix=f".{report_path.name}.",
                    suffix=".tmp",
                    dir=report_path.parent,
                )
                temporary = Path(name)
                with os.fdopen(descriptor, "w", encoding="utf-8", newline="\n") as handle:
                    descriptor = -1  # ownership transferred to the context manager
                    json.dump(report, handle, indent=2, sort_keys=True)
                    handle.write("\n")
                    handle.flush()
                    os.fsync(handle.fileno())
                _atomic_replace(temporary, report_path)
                temporary = None  # atomically moved; nothing remains to clean
            except BaseException as exc:
                if descriptor >= 0:
                    os.close(descriptor)
                if temporary is not None:
                    try:
                        temporary.unlink(missing_ok=True)
                    except OSError as cleanup_error:
                        exc.add_note(
                            f"failed to remove this writer's temporary report "
                            f"{temporary}: {cleanup_error}"
                        )
                raise
