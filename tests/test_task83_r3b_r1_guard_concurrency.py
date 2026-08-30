"""Task 83-R3B-R1 regressions for concurrent network-guard reporting."""

from __future__ import annotations

import json
import os
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest

import _network_guard as guard_module
from _network_guard import NetworkBlockedError, NetworkGuard


def test_concurrent_report_updates_never_share_the_legacy_fixed_temp(
    monkeypatch, tmp_path
):
    """Coordinate a stale fixed-temp overwrite without any external connection."""
    report_path = tmp_path / "guard.json"
    guard = NetworkGuard(report_path)
    guard.install()
    original_write_text = Path.write_text
    original_replace = os.replace
    fixed_temp_name = f".{report_path.name}.tmp"
    stale_payload_ready = threading.Event()
    newer_payload_replaced = threading.Event()
    writer = threading.local()

    def coordinated_write_text(path, data, *args, **kwargs):
        if path.name == fixed_temp_name and getattr(writer, "role", None) == "stale":
            # ``data`` was already rendered from the one-event snapshot. Hold
            # it until the other thread publishes the two-event snapshot.
            stale_payload_ready.set()
            assert newer_payload_replaced.wait(timeout=5)
        return original_write_text(path, data, *args, **kwargs)

    def coordinated_replace(source, destination):
        source_path = Path(source)
        result = original_replace(source, destination)
        if (
            Path(destination).resolve() == report_path.resolve()
            and source_path.name == fixed_temp_name
            and getattr(writer, "role", None) == "newer"
        ):
            newer_payload_replaced.set()
        return result

    def record_loopback(role, port):
        writer.role = role
        if role == "newer":
            # On the repaired unique-temp/serialized path there is no legacy
            # signal, so proceed after this bounded wait.
            stale_payload_ready.wait(timeout=1)
        guard.check_destination("concurrency.loopback", "127.0.0.1", port)

    try:
        with monkeypatch.context() as patcher:
            patcher.setattr(Path, "write_text", coordinated_write_text)
            patcher.setattr(os, "replace", coordinated_replace)
            with ThreadPoolExecutor(max_workers=2) as executor:
                futures = [
                    executor.submit(record_loopback, "stale", 41001),
                    executor.submit(record_loopback, "newer", 41002),
                ]
                failures = [future.exception(timeout=10) for future in futures]

        assert failures == [None, None]
        report = json.loads(report_path.read_text(encoding="utf-8"))
        assert report["counters"]["permitted_loopback_connections"] == 2
        assert not list(tmp_path.glob(f".{report_path.name}*.tmp"))
    finally:
        guard.uninstall()


def test_many_concurrent_loopback_updates_are_exact(tmp_path):
    report_path = tmp_path / "many.json"
    guard = NetworkGuard(report_path)
    guard.install()
    updates = 128

    try:
        with ThreadPoolExecutor(max_workers=16) as executor:
            list(
                executor.map(
                    lambda port: guard.check_destination(
                        "concurrency.many_loopback", "127.0.0.1", port
                    ),
                    range(42000, 42000 + updates),
                )
            )

        report = json.loads(report_path.read_text(encoding="utf-8"))
        assert report["counters"]["permitted_loopback_connections"] == updates
        assert len(report["events"]) == updates
        assert report["counters"]["unexpected_external_attempts"] == 0
        assert not list(tmp_path.glob(f".{report_path.name}.*.tmp"))
    finally:
        guard.uninstall()


def test_mixed_loopback_and_expected_block_reconcile_exactly(tmp_path):
    report_path = tmp_path / "mixed.json"
    guard = NetworkGuard(report_path)
    guard.install()
    loopback_updates = 64

    def expected_negative_control():
        with guard.expect_block("mixed_ipv4"):
            with pytest.raises(NetworkBlockedError):
                guard.check_destination(
                    "concurrency.expected", "198.51.100.77", 443
                )

    try:
        with ThreadPoolExecutor(max_workers=9) as executor:
            loopbacks = [
                executor.submit(
                    guard.check_destination,
                    "concurrency.mixed_loopback",
                    "127.0.0.1",
                    port,
                )
                for port in range(43000, 43000 + loopback_updates)
            ]
            blocked = executor.submit(expected_negative_control)
            for future in loopbacks:
                future.result(timeout=15)
            blocked.result(timeout=15)

        guard.assert_reconciled()
        report = json.loads(report_path.read_text(encoding="utf-8"))
        assert report["counters"]["permitted_loopback_connections"] == loopback_updates
        assert report["counters"]["expected_negative_control_blocks"] == 1
        assert report["expected_negative_controls"] == {"mixed_ipv4": 1}
        assert report["observed_expected_negative_control_blocks"] == {"mixed_ipv4": 1}
        assert report["negative_controls_reconciled"] is True
        assert report["counters"]["unexpected_external_attempts"] == 0
    finally:
        guard.uninstall()


def test_concurrent_readers_never_see_partial_json(tmp_path):
    report_path = tmp_path / "readers.json"
    guard = NetworkGuard(report_path)
    guard.install()
    stop = threading.Event()
    reader_errors = []
    updates = 96

    def read_until_stopped():
        while not stop.is_set():
            try:
                guard.read_report()
                # Leave a bounded Windows sharing window between complete
                # reads so the atomic replacer can make progress.
                time.sleep(0.001)
            except Exception as exc:  # noqa: BLE001 - captured for assertion
                reader_errors.append(exc)
                stop.set()

    try:
        with ThreadPoolExecutor(max_workers=13) as executor:
            readers = [executor.submit(read_until_stopped) for _ in range(4)]
            writers = [
                executor.submit(
                    guard.check_destination,
                    "concurrency.reader_stress",
                    "::1" if index % 2 else "127.0.0.1",
                    44000 + index,
                )
                for index in range(updates)
            ]
            for future in writers:
                future.result(timeout=20)
            stop.set()
            for future in readers:
                future.result(timeout=10)

        assert reader_errors == []
        report = json.loads(report_path.read_text(encoding="utf-8"))
        assert report["counters"]["permitted_loopback_connections"] == updates
    finally:
        stop.set()
        guard.uninstall()


def test_each_write_uses_a_unique_temporary_file(monkeypatch, tmp_path):
    report_path = tmp_path / "unique.json"
    guard = NetworkGuard(report_path)
    guard.install()
    original_replace = os.replace
    sources = []

    def recording_replace(source, destination):
        if Path(destination).resolve() == report_path.resolve():
            sources.append(Path(source).name)
        return original_replace(source, destination)

    try:
        with monkeypatch.context() as patcher:
            patcher.setattr(os, "replace", recording_replace)
            for port in range(45000, 45032):
                guard.check_destination(
                    "concurrency.unique_temp", "127.0.0.1", port
                )

        assert len(sources) == 32
        assert len(set(sources)) == 32
        assert f".{report_path.name}.tmp" not in sources
        assert not list(tmp_path.glob(f".{report_path.name}.*.tmp"))
    finally:
        guard.uninstall()


def test_failed_replace_cleans_only_current_writer_temp(monkeypatch, tmp_path):
    report_path = tmp_path / "cleanup.json"
    unrelated = tmp_path / f".{report_path.name}.unrelated.tmp"
    unrelated.write_text("preserve", encoding="utf-8")
    guard = NetworkGuard(report_path)
    guard.install()
    attempted_sources = []

    def failing_replace(source, destination):
        attempted_sources.append(Path(source))
        raise PermissionError("synthetic replace denial")

    try:
        with monkeypatch.context() as patcher:
            patcher.setattr(os, "replace", failing_replace)
            patcher.setattr(guard_module.time, "sleep", lambda _seconds: None)
            with pytest.raises(PermissionError, match="synthetic replace denial"):
                guard.write_report()

        assert len(attempted_sources) == guard_module._REPLACE_ATTEMPTS
        assert len(set(attempted_sources)) == 1
        assert not attempted_sources[-1].exists()
        assert unrelated.read_text(encoding="utf-8") == "preserve"
    finally:
        try:
            guard.uninstall()
        finally:
            unrelated.unlink(missing_ok=True)


def test_transient_replace_denial_retries_same_writer_temp(monkeypatch, tmp_path):
    report_path = tmp_path / "transient.json"
    guard = NetworkGuard(report_path)
    guard.install()
    original_replace = os.replace
    attempts = []

    def transient_replace(source, destination):
        attempts.append(Path(source))
        if len(attempts) <= 3:
            raise PermissionError("synthetic transient sharing denial")
        return original_replace(source, destination)

    try:
        with monkeypatch.context() as patcher:
            patcher.setattr(os, "replace", transient_replace)
            patcher.setattr(guard_module.time, "sleep", lambda _seconds: None)
            guard.check_destination(
                "concurrency.transient_replace", "127.0.0.1", 46001
            )

        assert len(attempts) == 4
        assert len(set(attempts)) == 1
        assert not attempts[0].exists()
        report = json.loads(report_path.read_text(encoding="utf-8"))
        assert report["counters"]["permitted_loopback_connections"] == 1
    finally:
        guard.uninstall()


def test_persistent_unwritable_destination_fails_visibly(monkeypatch, tmp_path):
    report_path = tmp_path / "unwritable.json"
    guard = NetworkGuard(report_path)
    guard.install()

    def deny_temp_creation(*_args, **_kwargs):
        raise PermissionError("synthetic persistent destination denial")

    try:
        with monkeypatch.context() as patcher:
            patcher.setattr(guard_module.tempfile, "mkstemp", deny_temp_creation)
            with pytest.raises(
                PermissionError, match="synthetic persistent destination denial"
            ):
                guard.write_report()
    finally:
        guard.uninstall()


def test_unexpected_external_attempt_stays_blocked_and_unexpected(tmp_path):
    report_path = tmp_path / "unexpected.json"
    guard = NetworkGuard(report_path)
    guard.install()

    try:
        with pytest.raises(NetworkBlockedError, match="unexpected external attempt"):
            guard.check_destination(
                "concurrency.unexpected", "203.0.113.99", 443
            )

        report = json.loads(report_path.read_text(encoding="utf-8"))
        assert report["counters"]["unexpected_external_attempts"] == 1
        assert report["counters"]["expected_negative_control_blocks"] == 0
        assert report["events"][-1]["kind"] == "unexpected_external_attempt"
        assert report["events"][-1]["label"] is None
    finally:
        guard.uninstall()


@pytest.mark.asyncio
@pytest.mark.parametrize("iteration", range(12))
async def test_original_browser_dashboard_route_repeated_under_guard(
    iteration, tmp_path
):
    """Repeat the exact R3C-failing route contract under the active guard."""
    del iteration
    import test_task83_browser_dashboard as browser_tests

    await browser_tests.test_existing_routes_unaffected(tmp_path)
