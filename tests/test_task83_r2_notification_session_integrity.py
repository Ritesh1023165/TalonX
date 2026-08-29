"""Task 83-R2 notification session isolation and real poll boundaries.

All Telegram and runtime dependencies are deterministic local fakes.
No external request can be made.
"""

from __future__ import annotations

import asyncio
import builtins
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import subprocess
import sys
import time

import pytest
from telegram.error import NetworkError

from talonx_compare.notification import assess_piv_notification
from talonx_dispatch.config import DispatchConfig
from talonx_dispatch.store import AuditStore
from talonx_dispatch.telegram_listener import TelegramReplyListener
from talonx_piv.events import EventBus, PivEvent
from talonx_piv.notification_telemetry import (
    NotificationTelemetryError,
    PivInboundPollTelemetry,
    TELEMETRY_NAME,
    _locked,
    load_telemetry,
    merge_telemetry,
)
from talonx_piv.telegram_inbound import build_piv_telegram_listener

DATE = "2026-08-28"
DATE_2 = "2026-08-29"
SESSION_A = "piv_2026-08-28_100000_aaaa1111"
SESSION_B = "piv_2026-08-28_143000_bbbb2222"


def _disabled(state_dir, session, date=DATE):
    return merge_telemetry(
        state_dir, session_id=session, trading_date_et=date,
        ownership={
            "outbound_enabled": False, "sender_constructed": False,
            "inbound_poller_constructed": False, "inbound_poller_started": False,
        },
    )


class _FakeBot:
    def __init__(self, responses):
        self.responses = list(responses)
        self.calls = []
        self.listener = None

    async def __aenter__(self):
        return self

    async def __aexit__(self, *_):
        return None

    async def get_updates(self, **kwargs):
        self.calls.append(kwargs)
        result = self.responses.pop(0)
        if isinstance(result, Exception):
            raise result
        if callable(result):
            result = result()
        return result


class _Factory:
    def __init__(self, bot):
        self.bot = bot

    def __call__(self, *, token):
        assert token == "piv-token"
        return self.bot


def _listener(tmp_path, bot, *, session=SESSION_A, date=DATE):
    return build_piv_telegram_listener(
        tmp_path, session_id=session, trading_date_et=date,
        telegram_token="piv-token", telegram_chat_id="123",
        bot_factory=_Factory(bot),
    )


def test_session_rollover_does_not_inherit_counters_or_ownership(tmp_path):
    bus = EventBus(
        tmp_path / "events.jsonl", lambda _: True, session_id=SESSION_A,
        telemetry_path=tmp_path, trading_date_et=DATE,
    )
    assert bus.emit(PivEvent.build("SIGNAL", symbol="AAPL"))
    merge_telemetry(
        tmp_path, session_id=SESSION_A, trading_date_et=DATE,
        ownership={"inbound_poller_constructed": True, "inbound_poller_started": True},
        inbound_delta={"poll_starts": 1, "poll_attempts": 2},
    )

    b = _disabled(tmp_path, SESSION_B)
    assert b["outbound"]["attempts"] == 0
    assert b["inbound"]["poll_starts"] == 0
    assert b["inbound"]["poll_attempts"] == 0
    assert all(value is False for value in b["ownership"].values())


def test_previous_session_remains_readable_and_restart_preserves_counters(tmp_path):
    _disabled(tmp_path, SESSION_A)
    merge_telemetry(
        tmp_path, session_id=SESSION_A, trading_date_et=DATE,
        outbound_delta={"attempts": 2, "successes": 2},
    )
    _disabled(tmp_path, SESSION_B)
    merge_telemetry(
        tmp_path, session_id=SESSION_A, trading_date_et=DATE,
        outbound_delta={"attempts": 1, "failures": 1},
    )
    a = load_telemetry(tmp_path, session_id=SESSION_A, trading_date_et=DATE)
    b = load_telemetry(tmp_path, session_id=SESSION_B, trading_date_et=DATE)
    assert a["outbound"] == {
        "attempts": 3, "successes": 2, "failures": 1, "last_attempt_at": None,
    }
    assert b["outbound"]["attempts"] == 0
    assert load_telemetry(tmp_path) is None  # selector-free multi-session read fails closed


@pytest.mark.parametrize("case", ["missing", "corrupt", "wrong_session", "wrong_date", "ambiguous"])
def test_bad_or_ambiguous_evidence_is_unverified(tmp_path, case):
    path = tmp_path / TELEMETRY_NAME
    if case == "corrupt":
        path.write_text("{broken", encoding="utf-8")
    elif case == "wrong_session":
        _disabled(tmp_path, SESSION_B)
    elif case == "wrong_date":
        _disabled(tmp_path, SESSION_A, DATE_2)
    elif case == "ambiguous":
        row = _disabled(tmp_path, SESSION_A)
        payload = {"schema_version": 2, "sessions": [row, row]}
        path.write_text(json.dumps(payload), encoding="utf-8")
    result = assess_piv_notification(tmp_path, SESSION_A, DATE)
    assert result["verdict"] == "UNVERIFIED"
    assert result["piv_zero_attempt_assertion"] is False


def test_concurrent_updates_do_not_lose_increments(tmp_path):
    _disabled(tmp_path, SESSION_A)

    def increment(_):
        merge_telemetry(
            tmp_path, session_id=SESSION_A, trading_date_et=DATE,
            outbound_delta={"attempts": 1, "successes": 1},
        )

    # Repeat bursts so lock hand-off is exercised, not merely one lucky
    # scheduler ordering. Exact reconciliation proves no read/modify/write
    # update was lost.
    for _ in range(4):
        with ThreadPoolExecutor(max_workers=12) as pool:
            list(pool.map(increment, range(50)))
    row = load_telemetry(tmp_path, session_id=SESSION_A, trading_date_et=DATE)
    assert row["outbound"]["attempts"] == 200
    assert row["outbound"]["successes"] == 200


def _subprocess_env() -> dict[str, str]:
    env = os.environ.copy()
    root = str(Path(__file__).resolve().parents[1])
    env["PYTHONPATH"] = root + os.pathsep + env.get("PYTHONPATH", "")
    return env


def test_competing_os_processes_reconcile_exact_counters(tmp_path):
    _disabled(tmp_path, SESSION_A)
    script = """
from pathlib import Path
import sys
from talonx_piv.notification_telemetry import merge_telemetry
state_dir, session_id, trading_date, count = sys.argv[1:]
for _ in range(int(count)):
    merge_telemetry(
        Path(state_dir), session_id=session_id, trading_date_et=trading_date,
        outbound_delta={"attempts": 1, "successes": 1},
    )
"""
    children = [
        subprocess.Popen(
            [sys.executable, "-c", script, str(tmp_path), SESSION_A, DATE, "25"],
            cwd=Path(__file__).resolve().parents[1], env=_subprocess_env(),
            stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
        )
        for _ in range(4)
    ]
    for child in children:
        stdout, stderr = child.communicate(timeout=30)
        assert child.returncode == 0, f"stdout={stdout}\nstderr={stderr}"

    row = load_telemetry(tmp_path, session_id=SESSION_A, trading_date_et=DATE)
    assert row["outbound"]["attempts"] == 100
    assert row["outbound"]["successes"] == 100
    assert row["outbound"]["failures"] == 0


def test_same_path_thread_lock_timeout_is_visible(tmp_path):
    telemetry_path = tmp_path / TELEMETRY_NAME
    with _locked(telemetry_path):
        started = time.monotonic()
        with pytest.raises(NotificationTelemetryError, match="timed out"):
            with _locked(telemetry_path, timeout_seconds=0.03):
                pytest.fail("nested acquisition unexpectedly succeeded")
        assert time.monotonic() - started < 1.0


def test_persistent_permission_failure_is_bounded_and_fails_closed(tmp_path, monkeypatch):
    telemetry_path = tmp_path / TELEMETRY_NAME
    lock_path = telemetry_path.with_name(f".{telemetry_path.name}.lock").resolve()
    real_open = builtins.open

    def deny_lock_file(path, *args, **kwargs):
        if Path(path).resolve() == lock_path:
            raise PermissionError("simulated unwritable telemetry lock")
        return real_open(path, *args, **kwargs)

    monkeypatch.setattr(builtins, "open", deny_lock_file)
    started = time.monotonic()
    with pytest.raises(NotificationTelemetryError, match="timed out acquiring OS telemetry lock"):
        with _locked(telemetry_path, timeout_seconds=0.03):
            pytest.fail("unwritable lock unexpectedly acquired")
    assert time.monotonic() - started < 1.0
    assert not telemetry_path.exists()


def test_os_lock_timeout_and_abrupt_owner_termination_recovery(tmp_path):
    telemetry_path = tmp_path / TELEMETRY_NAME
    ready = tmp_path / "owner-ready"
    script = """
from pathlib import Path
import sys
import time
from talonx_piv.notification_telemetry import _locked
with _locked(Path(sys.argv[1])):
    Path(sys.argv[2]).write_text("locked", encoding="utf-8")
    time.sleep(60)
"""
    child = subprocess.Popen(
        [sys.executable, "-c", script, str(telemetry_path), str(ready)],
        cwd=Path(__file__).resolve().parents[1], env=_subprocess_env(),
        stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
    )
    try:
        deadline = time.monotonic() + 10.0
        while not ready.exists() and child.poll() is None and time.monotonic() < deadline:
            time.sleep(0.01)
        assert ready.exists(), child.communicate(timeout=1)

        with pytest.raises(NotificationTelemetryError, match="timed out acquiring OS telemetry lock"):
            with _locked(telemetry_path, timeout_seconds=0.05):
                pytest.fail("competing process lock unexpectedly acquired")

        child.kill()  # no child finally/release path: kernel must release it
        child.wait(timeout=10)
        with _locked(telemetry_path, timeout_seconds=2.0):
            pass
    finally:
        if child.poll() is None:
            child.kill()
            child.wait(timeout=10)


@pytest.mark.asyncio
async def test_backlog_and_successful_live_poll_use_real_get_updates_boundary(tmp_path):
    bot = _FakeBot([[], lambda: []])
    listener = _listener(tmp_path, bot)
    bot.responses[1] = lambda: (listener.stop() or [])
    await listener.run()
    row = load_telemetry(tmp_path, session_id=SESSION_A, trading_date_et=DATE)
    assert len(bot.calls) == 2
    assert bot.calls[0]["timeout"] == 0
    assert bot.calls[1]["timeout"] == int(listener.config.telegram_poll_timeout_seconds)
    assert row["inbound"]["poll_starts"] == 1
    assert row["inbound"]["poll_attempts"] == 2
    assert row["inbound"]["poll_successes"] == 2
    assert row["inbound"]["poll_failures"] == 0


@pytest.mark.asyncio
async def test_failed_live_poll_and_retry_are_recorded(tmp_path, monkeypatch):
    bot = _FakeBot([[], NetworkError("fake failure"), lambda: []])
    listener = _listener(tmp_path, bot)
    bot.responses[2] = lambda: (listener.stop() or [])

    async def no_sleep(_):
        return None

    monkeypatch.setattr(asyncio, "sleep", no_sleep)
    await listener.run()
    row = load_telemetry(tmp_path, session_id=SESSION_A, trading_date_et=DATE)
    assert len(bot.calls) == 3
    assert row["inbound"]["poll_attempts"] == 3
    assert row["inbound"]["poll_successes"] == 2
    assert row["inbound"]["poll_failures"] == 1


@pytest.mark.asyncio
async def test_same_session_listener_restart_preserves_boundary_counts(tmp_path):
    for _ in range(2):
        bot = _FakeBot([[], lambda: []])
        listener = _listener(tmp_path, bot)
        bot.responses[1] = lambda listener=listener: (listener.stop() or [])
        await listener.run()
    row = load_telemetry(tmp_path, session_id=SESSION_A, trading_date_et=DATE)
    assert row["inbound"]["poll_starts"] == 2
    assert row["inbound"]["poll_attempts"] == 4
    assert row["inbound"]["poll_successes"] == 4


@pytest.mark.asyncio
async def test_disabled_piv_constructs_no_sender_or_poller_and_stays_zero(tmp_path, monkeypatch):
    monkeypatch.delenv("TALONX_PIV_TELEGRAM_ENABLED", raising=False)
    from talonx_piv import cli
    from talonx_piv.config import PivConfig

    session = "piv_disabled"
    bus, *_ = cli.runtime(PivConfig(state_dir=tmp_path), session_id=session)
    date = datetime.now(timezone.utc).astimezone(cli._ET).date().isoformat()
    row = load_telemetry(tmp_path, session_id=session, trading_date_et=date)
    assert bus.telegram_send is None
    assert row["ownership"] == {
        "outbound_enabled": False, "sender_constructed": False,
        "inbound_poller_constructed": False, "inbound_poller_started": False,
    }
    assert row["outbound"]["attempts"] == 0
    assert row["inbound"]["poll_starts"] == row["inbound"]["poll_attempts"] == 0
    assert assess_piv_notification(tmp_path, session, date)["verdict"] == "VERIFIED_ZERO"


@pytest.mark.asyncio
async def test_original_listener_has_no_piv_telemetry_side_effect(tmp_path):
    bot = _FakeBot([[]])
    listener = TelegramReplyListener(
        AuditStore(":memory:"),
        DispatchConfig(telegram_bot_token="original-token", telegram_chat_id="1"),
        bot_factory=lambda *, token: bot,
    )
    await listener._drain_backlog(bot)
    assert len(bot.calls) == 1
    assert listener.poll_telemetry is None
    assert not (tmp_path / TELEMETRY_NAME).exists()


@pytest.mark.asyncio
async def test_telemetry_write_failure_is_visible_and_prevents_request(tmp_path, monkeypatch):
    _disabled(tmp_path, SESSION_A)
    telemetry = PivInboundPollTelemetry(tmp_path, SESSION_A, DATE)
    bot = _FakeBot([[]])
    listener = TelegramReplyListener(
        AuditStore(":memory:"), DispatchConfig(), poll_telemetry=telemetry,
    )

    def fail_write(*_args, **_kwargs):
        raise OSError("simulated disk failure")

    monkeypatch.setattr("talonx_piv.notification_telemetry._atomic_write", fail_write)
    with pytest.raises(NotificationTelemetryError):
        await listener._drain_backlog(bot)
    assert bot.calls == []
    assert "simulated disk failure" in telemetry.last_error
    assert assess_piv_notification(tmp_path, SESSION_A, DATE)["verdict"] != "VERIFIED_ZERO"
