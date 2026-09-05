"""
tests/test_task69p_telegram_piv_parity.py
--------------------------------------------
Focused tests for Task 69P's Telegram inbound /ping parity fix:
talonx_piv.telegram_inbound's PIV-aware dispatch_agent shim, and
telegram_listener.TelegramReplyListener's new additive `_piv_section`.
"""
from __future__ import annotations

import asyncio
from datetime import datetime, timezone

import pytest

from talonx_dispatch.config import DispatchConfig
from talonx_dispatch.store import AuditStore
from talonx_dispatch.telegram_listener import TelegramReplyListener
from talonx_piv.telegram_inbound import (
    _PivPingContext,
    _feed_provider_label,
    build_piv_telegram_listener,
    telegram_inbound_capable,
)


def _listener(tmp_path, **kwargs) -> TelegramReplyListener:
    return build_piv_telegram_listener(tmp_path, **kwargs)


def test_feed_provider_label_iex_paper_piv():
    assert "Alpaca IEX" in _feed_provider_label("IEX_PAPER_PIV")


def test_feed_provider_label_research_sip():
    assert "Alpaca SIP" in _feed_provider_label("RESEARCH_SIP")


def test_feed_provider_label_never_falsely_reports_yfinance():
    # Regression pin for the exact concern Task 69P raised: whatever the
    # label logic does, it must never contain "yfinance" for a PIV feed_mode.
    for mode in ("IEX_PAPER_PIV", "RESEARCH_SIP", None, "SOME_FUTURE_MODE"):
        assert "yfinance" not in _feed_provider_label(mode).lower()


def test_build_piv_telegram_listener_default_call_still_works(tmp_path):
    """Backward compatibility: telegram_inbound_capable() and any other
    caller passing only state_dir must keep working unchanged."""
    ok, msg = telegram_inbound_capable(tmp_path)
    assert ok
    assert "TelegramReplyListener constructed" in msg


def test_dispatch_agent_is_piv_context_not_none(tmp_path):
    listener = _listener(tmp_path, feed_mode="IEX_PAPER_PIV", universe=("AAPL", "MSFT"))
    assert isinstance(listener.dispatch_agent, _PivPingContext)
    assert listener.dispatch_agent.piv_info["mode"] == "PAPER / NO REAL CAPITAL"
    assert listener.dispatch_agent.piv_info["feed_provider"] == _feed_provider_label("IEX_PAPER_PIV")
    assert listener.dispatch_agent.piv_info["universe_size"] == 2


def test_piv_section_present_when_piv_info_set(tmp_path):
    listener = _listener(tmp_path, feed_mode="IEX_PAPER_PIV", universe=("AAPL",) * 35)
    lines = listener._piv_section()
    joined = "\n".join(lines)
    assert "PAPER / NO REAL CAPITAL" in joined
    assert "Alpaca IEX" in joined
    assert "35" in joined


def test_piv_section_empty_for_general_app_dispatch_agent():
    """The general run_talonx.py app's real DispatchAgent never sets
    `piv_info` -- _piv_section must return [] (no output change) for it,
    proving the fix is additive/opt-in, not a behavior change for the
    existing production app."""
    class _FakeGeneralDispatchAgent:
        started_at = datetime.now(timezone.utc)
        watchlist_store = None
        _client = None
        # deliberately NO piv_info attribute

    config = DispatchConfig()
    store = AuditStore(":memory:")
    listener = TelegramReplyListener(store, config, dispatch_agent=_FakeGeneralDispatchAgent())
    assert listener._piv_section() == []


def test_piv_section_empty_when_dispatch_agent_none():
    config = DispatchConfig()
    store = AuditStore(":memory:")
    listener = TelegramReplyListener(store, config, dispatch_agent=None)
    assert listener._piv_section() == []


def test_uptime_and_client_wired_through_shim(tmp_path):
    started = datetime.now(timezone.utc)
    listener = _listener(tmp_path, redis_client="FAKE_CLIENT_SENTINEL", started_at=started, feed_mode="IEX_PAPER_PIV")
    assert listener.dispatch_agent._client == "FAKE_CLIENT_SENTINEL"
    assert listener.dispatch_agent.started_at == started
    assert listener.dispatch_agent.watchlist_store is None  # honest "unknown" path preserved


def test_universe_size_unknown_when_empty(tmp_path):
    listener = build_piv_telegram_listener(tmp_path)  # no universe passed
    assert listener.dispatch_agent.piv_info["universe_size"] == "unknown"


# --- 2026-08-25 live-incident follow-up: Pipeline/MARKET label clarification ---

@pytest.mark.asyncio
async def test_handle_ping_pipeline_line_annotated_for_piv_context(tmp_path):
    """Regression pin for the live finding: /ping's 'Pipeline: DEGRADED
    (market feed disconnected)' line is scoped to talonx_ingest, which PIV
    never uses -- for a piv_info-carrying listener it must be annotated so
    a reader doesn't mistake it for whole-system health."""
    listener = _listener(tmp_path, feed_mode="IEX_PAPER_PIV", universe=("AAPL",) * 5)
    sent = {}

    async def _fake_reply(text, plain=False):
        sent["text"] = text

    listener._reply = _fake_reply
    await listener._handle_ping()
    assert "Pipeline: " in sent["text"]
    assert "NOT used by this PIV session" in sent["text"]
    assert "MARKET" in sent["text"]


@pytest.mark.asyncio
async def test_handle_ping_general_app_unaffected_by_annotation():
    """The general app's real DispatchAgent (no piv_info) must see NO
    annotation suffix at all -- confirms the fix is additive/opt-in."""
    class _FakeGeneralDispatchAgent:
        started_at = None
        watchlist_store = None
        _client = None

    config = DispatchConfig()
    store = AuditStore(":memory:")
    listener = TelegramReplyListener(store, config, dispatch_agent=_FakeGeneralDispatchAgent())
    sent = {}

    async def _fake_reply(text, plain=False):
        sent["text"] = text

    listener._reply = _fake_reply
    await listener._handle_ping()
    assert "NOT used by this PIV session" not in sent["text"]
    assert "scoped to the general ingest pipeline" not in sent["text"]
