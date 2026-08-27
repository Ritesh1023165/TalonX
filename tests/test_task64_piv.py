from __future__ import annotations

from datetime import date, datetime, timedelta
import json
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest

from talonx_piv.broker import AlpacaPaperClient, PaperGuardError
from talonx_piv.config import PAPER_ENDPOINT, PivConfig
from talonx_piv.events import EventBus, PivEvent
from talonx_piv.execution_settings import PaperEntrySettings
from talonx_piv.lifecycle import PaperLifecycle, paper_cleanup, stable_id
from talonx_piv.preflight import Preflight
from talonx_piv.readiness import SessionReadinessValidator

ET = ZoneInfo("America/New_York")
SESSION = date(2026, 8, 24)


class Response:
    def __init__(self, body, status=200): self.body, self.status_code = body, status
    def json(self): return self.body
    def raise_for_status(self):
        if self.status_code >= 400: raise RuntimeError(f"HTTP {self.status_code}")


class Transport:
    def __init__(self, account=True):
        self.account = account; self.orders = []; self.positions = []; self.submits = 0
    def get(self, url, **kwargs):
        if url.endswith("/v2/account"):
            return Response({"id": "paper-id", "account_number": "PA123456", "status": "ACTIVE"} if self.account else {}, 200 if self.account else 401)
        if url.endswith("/v2/orders"): return Response(self.orders)
        if url.endswith("/v2/positions"): return Response(self.positions)
        if "trades/latest" in url: return Response({"trade": {"t": "2026-08-21T20:00:00Z"}})
        if "telegram.org" in url: return Response({"ok": True})
        return Response({}, 404)
    def post(self, url, **kwargs):
        self.submits += 1; order = {"id": f"order-{self.submits}", **kwargs.get("json", {})}; self.orders.append(order); return Response(order)
    def delete(self, url, **kwargs):
        if url.endswith("/v2/orders"): self.orders = []
        if url.endswith("/v2/positions"): self.positions = []
        return Response([])


def config(tmp_path, **overrides):
    values = dict(key_id="key", secret_key="secret", paper_trading=True, real_capital=False,
                  broker_endpoint=PAPER_ENDPOINT, approved_sha="abc", telegram_token="token",
                  telegram_chat_id="chat", state_dir=tmp_path)
    values.update(overrides); return PivConfig(**values)


def ready_validator(missing=()):
    validator = SessionReadinessValidator(); start = datetime(2026, 8, 24, 9, 30, tzinfo=ET)
    for i in range(30):
        if i not in missing: validator.observe("AAPL", SESSION, start + timedelta(minutes=i))
    return validator


def lifecycle(tmp_path, transport=None, telegram=None):
    # Task 76S: TEST_FIXTURE_ONLY -- NOT ALPHA EVIDENCE. This file's tests
    # exercise the AAPL order lifecycle pre-dating the Stage 2 fail-closed
    # paper_entry_enabled default; explicitly enabling AAPL here preserves
    # their original intent (duplicate/partial-fill/reject/restart/kill-
    # switch mechanics) rather than having every one of them newly blocked
    # by PAPER_ENTRY_DISABLED_FOR_TICKER.
    transport = transport or Transport(); broker = AlpacaPaperClient(config(tmp_path), transport); broker.verify_paper_identity()
    events = EventBus(tmp_path / "events.jsonl", telegram)
    life = PaperLifecycle(tmp_path / "state.json", broker, events, PaperEntrySettings.for_test("AAPL"))
    life.start_session(True, True)
    return life, broker, transport, events


def test_all_30_opening_minutes_ready():
    result = ready_validator().evaluate("AAPL", SESSION, datetime(2026, 8, 24, 10, 0, tzinfo=ET))
    assert result.status == "READY" and result.observed_minutes == 30 and not result.synthetic_data_used


def test_missing_minute_data_not_ready():
    result = ready_validator({7}).evaluate("AAPL", SESSION, datetime(2026, 8, 24, 10, 0, tzinfo=ET))
    assert result.status == "DATA_NOT_READY" and len(result.missing_minutes) == 1


def test_no_interpolation_or_forward_fill():
    result = ready_validator({1, 2}).evaluate("AAPL", SESSION, datetime(2026, 8, 24, 10, 1, tzinfo=ET))
    assert result.observed_minutes == 28 and result.synthetic_data_used is False


def test_one_bad_symbol_does_not_block_others():
    validator = ready_validator({3}); start = datetime(2026, 8, 24, 9, 30, tzinfo=ET)
    for i in range(30): validator.observe("MSFT", SESSION, start + timedelta(minutes=i))
    now = datetime(2026, 8, 24, 10, 0, tzinfo=ET)
    assert validator.evaluate("AAPL", SESSION, now).status == "DATA_NOT_READY"
    assert validator.evaluate("MSFT", SESSION, now).status == "READY"


def test_next_session_recovery():
    validator = ready_validator({3}); now = datetime(2026, 8, 24, 10, 0, tzinfo=ET)
    assert validator.evaluate("AAPL", SESSION, now).status == "DATA_NOT_READY"
    next_day = date(2026, 8, 25); start = datetime(2026, 8, 25, 9, 30, tzinfo=ET)
    for i in range(30): validator.observe("AAPL", next_day, start + timedelta(minutes=i))
    assert validator.evaluate("AAPL", next_day, datetime(2026, 8, 25, 10, 0, tzinfo=ET)).status == "READY"


def test_readiness_only_after_completed_0959_bar():
    result = ready_validator().evaluate("AAPL", SESSION, datetime(2026, 8, 24, 9, 59, 59, tzinfo=ET))
    assert result.status == "PENDING"


def test_readiness_causality_ignores_future_timestamp():
    validator = ready_validator({5}); validator.observe("AAPL", SESSION, datetime(2026, 8, 24, 10, 5, tzinfo=ET))
    result = validator.evaluate("AAPL", SESSION, datetime(2026, 8, 24, 10, 0, tzinfo=ET))
    assert result.status == "DATA_NOT_READY" and result.observed_minutes == 29


def test_paper_live_account_discrimination(tmp_path):
    client = AlpacaPaperClient(config(tmp_path, broker_endpoint="https://api.alpaca.markets"), Transport())
    with pytest.raises(PaperGuardError): client.verify_paper_identity()


def test_paper_verification_failure_is_fail_closed(tmp_path):
    client = AlpacaPaperClient(config(tmp_path), Transport(account=False))
    with pytest.raises(PaperGuardError): client.verify_paper_identity()
    with pytest.raises(PaperGuardError): client.submit_order({})


def test_duplicate_order_prevention(tmp_path):
    life, _, transport, _ = lifecycle(tmp_path); life.order_intent("sig", "AAPL", "buy", 1)
    with pytest.raises(PaperGuardError): life.order_intent("sig", "AAPL", "buy", 1)
    assert transport.submits == 1


def test_partial_fill_lifecycle(tmp_path):
    life, _, _, _ = lifecycle(tmp_path); result = life.order_intent("sig", "AAPL", "buy", 2)
    life.apply_broker_update(result["id"], "partially_filled", 1, 100.0)
    assert next(iter(life.state.positions.values()))["quantity"] == 1


@pytest.mark.parametrize("status,event", [("rejected", "PAPER_ORDER_REJECTED"), ("canceled", "PAPER_ORDER_CANCELLED")])
def test_reject_cancel_lifecycle(tmp_path, status, event):
    life, _, _, bus = lifecycle(tmp_path); result = life.order_intent(status, "AAPL", "buy", 1)
    life.apply_broker_update(result["id"], status)
    assert event in bus.path.read_text(encoding="utf-8")


def test_restart_preserves_duplicate_guard_and_reconciliation(tmp_path):
    life, broker, transport, bus = lifecycle(tmp_path); life.order_intent("sig", "AAPL", "buy", 1)
    restarted = PaperLifecycle(tmp_path / "state.json", broker, bus); restarted.state.session_enabled = True
    with pytest.raises(PaperGuardError): restarted.order_intent("sig", "AAPL", "buy", 1)


def test_kill_switch_blocks_new_orders(tmp_path):
    life, _, _, _ = lifecycle(tmp_path); life.activate_kill_switch()
    with pytest.raises(PaperGuardError): life.order_intent("sig", "AAPL", "buy", 1)


def test_eod_flatten_cancels_and_closes(tmp_path):
    transport = Transport(); transport.orders = [{"id": "x"}]; transport.positions = [{"symbol": "AAPL"}]
    life, _, transport, _ = lifecycle(tmp_path, transport); result = life.eod_flatten()
    assert result["matched"] and not transport.orders and not transport.positions


def test_telegram_failure_isolation(tmp_path):
    def fail(_): raise OSError("down")
    bus = EventBus(tmp_path / "events.jsonl", fail)
    assert bus.emit(PivEvent.build("SIGNAL", correlation_id="x")) is False
    assert bus.path.exists() and bus.telegram_failures == 1


def test_telegram_deduplicates(tmp_path):
    sent = []; bus = EventBus(tmp_path / "events.jsonl", lambda msg: sent.append(msg) or True)
    event = PivEvent.build("SIGNAL", correlation_id="x"); bus.emit(event); bus.emit(event)
    assert len(sent) == 1


def test_correlation_ids_stable_and_present(tmp_path):
    assert stable_id("intent", "a", 1) == stable_id("intent", "a", 1)
    life, _, _, bus = lifecycle(tmp_path); life.order_intent("signal-1", "AAPL", "buy", 1)
    rows = [json.loads(line) for line in bus.path.read_text().splitlines()]
    assert any(row["signal_id"] == "signal-1" and row["order_intent_id"] for row in rows)


def test_preflight_pass(tmp_path, monkeypatch):
    transport = Transport(); cfg = config(tmp_path); broker = AlpacaPaperClient(cfg, transport); bus = EventBus(tmp_path / "events.jsonl")
    flight = Preflight(cfg, broker, bus, tmp_path, transport); monkeypatch.setattr(flight, "_git", lambda *args: "abc" if args[0] == "rev-parse" else "")
    status, checks = flight.run()
    assert status == "PIV_READY" and all(item.passed for item in checks)


def test_preflight_blocked(tmp_path, monkeypatch):
    transport = Transport(); cfg = config(tmp_path, broker_endpoint="https://api.alpaca.markets"); broker = AlpacaPaperClient(cfg, transport)
    flight = Preflight(cfg, broker, EventBus(tmp_path / "events.jsonl"), tmp_path, transport); monkeypatch.setattr(flight, "_git", lambda *args: "abc" if args[0] == "rev-parse" else "")
    status, _ = flight.run()
    assert status == "PIV_BLOCKED"


def test_cleanup_cannot_operate_on_live_account(tmp_path):
    transport = Transport(); client = AlpacaPaperClient(config(tmp_path, real_capital=True), transport)
    with pytest.raises(PaperGuardError): paper_cleanup(client, EventBus(tmp_path / "events.jsonl"), True)
    assert transport.orders == [] and transport.positions == []
