"""Task 66A Part 2 -- full runtime feature parity: inbound Telegram /ping
reuse (no duplicate listener), runtime parity manifest/preflight."""
from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock

import pytest

from talonx_piv.cli import run_session
from talonx_piv.runtime_manifest import COMPONENT_COVERAGE, RUNTIME_COMPONENTS, runtime_parity_status
from talonx_piv.telegram_inbound import build_piv_telegram_listener, telegram_inbound_capable


def test_telegram_inbound_capable_constructs_without_network_call(tmp_path):
    ok, detail = telegram_inbound_capable(tmp_path)
    assert ok
    assert "TelegramReplyListener constructed" in detail


def test_build_piv_telegram_listener_uses_piv_scoped_audit_db(tmp_path):
    listener = build_piv_telegram_listener(tmp_path)
    assert listener.config.audit_db_path == str(tmp_path / "piv_telegram_audit.db")
    assert listener.dispatch_agent is None  # documented degrade path, no full app coupling


def test_runtime_parity_reports_pass_with_current_manifest():
    status, coverage = runtime_parity_status()
    assert status == "RUNTIME_PARITY_PASS"
    assert set(c.component for c in coverage) == set(RUNTIME_COMPONENTS)
    assert all(c.present_in_piv_runtime for c in coverage)


def test_runtime_parity_fails_if_a_component_is_missing(monkeypatch):
    import talonx_piv.runtime_manifest as manifest_module
    degraded = tuple(
        c if c.component != "telegram_inbound_command_listener" else
        type(c)(c.component, False, None, "simulated omission")
        for c in manifest_module.COMPONENT_COVERAGE
    )
    monkeypatch.setattr(manifest_module, "COMPONENT_COVERAGE", degraded)
    status, coverage = manifest_module.runtime_parity_status()
    assert status == "RUNTIME_PARITY_FAIL"


@pytest.mark.asyncio
async def test_run_session_starts_and_stops_listener_alongside_runner():
    runner = AsyncMock()
    listener = MagicMock()
    listener.run = AsyncMock()
    await run_session(runner, listener)
    runner.run.assert_awaited_once()
    listener.run.assert_awaited_once()
    listener.stop.assert_called_once()


@pytest.mark.asyncio
async def test_run_session_stops_listener_even_if_runner_raises():
    runner = AsyncMock()
    runner.run.side_effect = RuntimeError("boom")
    listener = MagicMock()
    listener.run = AsyncMock()
    with pytest.raises(RuntimeError):
        await run_session(runner, listener)
    listener.stop.assert_called_once()  # cleanup still happens


@pytest.mark.asyncio
async def test_run_session_with_no_listener_configured():
    runner = AsyncMock()
    await run_session(runner, None)  # --no-telegram-inbound path -- no listener task at all
    runner.run.assert_awaited_once()


def test_telegram_inbound_capability_check_is_present_in_preflight_module():
    """Confirms the manifest's cross-reference name actually exists as a
    real preflight check, not just a stale string."""
    import inspect
    from talonx_piv import preflight as preflight_module
    source = inspect.getsource(preflight_module)
    assert 'check("telegram_inbound_capability"' in source
    assert 'check("runtime_parity"' in source
