"""Task 65 -- explicit IEX_PAPER_PIV feed mode: no silent fallback, feed
identity in telemetry, operational-only classification, fail-closed."""
from __future__ import annotations

from pathlib import Path

import pytest

from talonx_piv.broker import AlpacaPaperClient, PaperGuardError
from talonx_piv.config import PAPER_ENDPOINT, PivConfig
from talonx_piv.events import EventBus, PivEvent
from talonx_piv.preflight import Preflight


class Response:
    def __init__(self, body, status=200): self.body, self.status_code = body, status
    def json(self): return self.body
    def raise_for_status(self):
        if self.status_code >= 400: raise RuntimeError(f"HTTP {self.status_code}")


class RecordingTransport:
    """Tracks every feed param requested so a test can assert no fallback occurred."""

    def __init__(self, feed_status: dict[str, int]):
        self.feed_status = feed_status
        self.calls: list[str] = []

    def get(self, url, **kwargs):
        if url.endswith("/v2/account"):
            return Response({"id": "paper-id", "account_number": "PA123456", "status": "ACTIVE"}, 200)
        if url.endswith("/v2/orders"):
            return Response([])
        if url.endswith("/v2/positions"):
            return Response([])
        if "trades/latest" in url:
            feed = kwargs.get("params", {}).get("feed")
            self.calls.append(feed)
            status = self.feed_status.get(feed, 404)
            body = {"trade": {"t": "2026-08-24T14:31:00Z"}} if status == 200 else {}
            return Response(body, status)
        if "telegram.org" in url:
            return Response({"ok": True})
        return Response({}, 404)


def config(tmp_path, **overrides):
    values = dict(key_id="key", secret_key="secret", paper_trading=True, real_capital=False,
                  broker_endpoint=PAPER_ENDPOINT, approved_sha="abc", telegram_token="token",
                  telegram_chat_id="chat", state_dir=tmp_path)
    values.update(overrides)
    return PivConfig(**values)


def preflight(tmp_path, feed_status: dict[str, int], **overrides):
    transport = RecordingTransport(feed_status)
    cfg = config(tmp_path, **overrides)
    broker = AlpacaPaperClient(cfg, transport)
    bus = EventBus(tmp_path / "events.jsonl", feed_mode=cfg.feed_mode)
    flight = Preflight(cfg, broker, bus, tmp_path, transport)
    flight._git = lambda *args: "abc" if args[0] == "rev-parse" else ""
    return flight, transport, bus


def test_iex_mode_feed_check_accepts_http_200(tmp_path):
    flight, transport, _ = preflight(tmp_path, {"iex": 200}, feed_mode="IEX_PAPER_PIV")
    status, checks = flight.run()
    assert status == "PIV_READY"
    assert transport.calls == ["iex"]


def test_sip_mode_requires_sip_and_does_not_fall_back_to_iex(tmp_path):
    # sip fails (403); iex would succeed if tried -- it must NOT be tried.
    flight, transport, _ = preflight(tmp_path, {"sip": 403, "iex": 200}, feed_mode="RESEARCH_SIP")
    status, checks = flight.run()
    assert status == "PIV_BLOCKED"
    assert transport.calls == ["sip"]  # exactly one call, never fell back to iex


def test_iex_mode_does_not_fall_back_to_sip(tmp_path):
    flight, transport, _ = preflight(tmp_path, {"iex": 403, "sip": 200}, feed_mode="IEX_PAPER_PIV")
    status, _ = flight.run()
    assert status == "PIV_BLOCKED"
    assert transport.calls == ["iex"]


def test_feed_identity_recorded_in_telemetry(tmp_path):
    flight, _, bus = preflight(tmp_path, {"iex": 200}, feed_mode="IEX_PAPER_PIV")
    flight.run()
    rows = bus.path.read_text(encoding="utf-8").splitlines()
    assert rows and all('"feed_mode": "IEX_PAPER_PIV"' in row for row in rows)


def test_iex_mode_marked_operational_only_not_canonical_alpha(tmp_path):
    flight, _, _ = preflight(tmp_path, {"iex": 200}, feed_mode="IEX_PAPER_PIV")
    _, checks = flight.run()
    classification = next(c for c in checks if c.name == "feed_mode_classification")
    assert classification.passed
    assert "OPERATIONAL_PIV_ONLY_NOT_ALPHA_EVIDENCE" in classification.detail


def test_sip_mode_marked_canonical_alpha_evidence(tmp_path):
    flight, _, _ = preflight(tmp_path, {"sip": 200}, feed_mode="RESEARCH_SIP")
    _, checks = flight.run()
    classification = next(c for c in checks if c.name == "feed_mode_classification")
    assert "CANONICAL_ALPHA_EVIDENCE" in classification.detail and "NOT_ALPHA" not in classification.detail


def test_paper_hard_guard_unchanged_under_iex_mode(tmp_path):
    cfg = config(tmp_path, feed_mode="IEX_PAPER_PIV", broker_endpoint="https://api.alpaca.markets")
    client = AlpacaPaperClient(cfg, RecordingTransport({"iex": 200}))
    with pytest.raises(PaperGuardError):
        client.verify_paper_identity()


def test_real_capital_path_remains_unsupported_under_iex_mode(tmp_path):
    cfg = config(tmp_path, feed_mode="IEX_PAPER_PIV", real_capital=True)
    client = AlpacaPaperClient(cfg, RecordingTransport({"iex": 200}))
    with pytest.raises(PaperGuardError):
        client.verify_paper_identity()


def test_preflight_ready_when_iex_mode_valid(tmp_path):
    flight, _, _ = preflight(tmp_path, {"iex": 200}, feed_mode="IEX_PAPER_PIV")
    status, checks = flight.run()
    assert status == "PIV_READY" and all(c.passed for c in checks)


def test_warmup_capability_check_skipped_when_decision_path_disabled(tmp_path):
    flight, _, _ = preflight(tmp_path, {"iex": 200}, feed_mode="IEX_PAPER_PIV", decision_path_enabled=False)
    _, checks = flight.run()
    warmup = next(c for c in checks if c.name == "warmup_mechanism_capability")
    assert warmup.passed and "not required" in warmup.detail


def test_warmup_capability_check_passes_when_yfinance_importable(tmp_path):
    flight, _, _ = preflight(tmp_path, {"iex": 200}, feed_mode="IEX_PAPER_PIV", decision_path_enabled=True)
    _, checks = flight.run()
    warmup = next(c for c in checks if c.name == "warmup_mechanism_capability")
    assert warmup.passed  # yfinance is an installed dependency in this environment


def test_preflight_fails_closed_on_unknown_feed_mode(tmp_path):
    flight, transport, _ = preflight(tmp_path, {"iex": 200, "sip": 200}, feed_mode="LIVE_SIP")
    status, checks = flight.run()
    assert status == "PIV_BLOCKED"
    assert transport.calls == []  # never attempted any feed for an unrecognized mode
    failed = next(c for c in checks if c.name == "market_data_feed_accessible")
    assert not failed.passed and "unknown feed_mode" in failed.detail
