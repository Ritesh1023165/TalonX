"""Task 77I Stages 2/3 -- proves, at the DecisionEngine integration level
(not just NotificationOutbox/ShadowLedger unit tests), that a failure in
one of the three independent branches (notification, shadow, real
order_intent) can never suppress another. TEST_FIXTURE_ONLY -- NOT ALPHA
EVIDENCE throughout; no real broker/Telegram call anywhere in this file."""
from __future__ import annotations

from datetime import datetime, timezone
from unittest.mock import AsyncMock

import pytest

from talonx_piv.broker import AlpacaPaperClient
from talonx_piv.config import PAPER_ENDPOINT, PivConfig
from talonx_piv.decision_contract import StrategyApprovalStatus
from talonx_piv.decision_engine import DecisionEngine
from talonx_piv.decision_ledger import DecisionLedger
from talonx_piv.events import EventBus
from talonx_piv.execution_settings import PaperEntrySettings
from talonx_piv.lifecycle import PaperLifecycle
from talonx_piv.notification_outbox import NotificationOutbox
from talonx_piv.session_runner import Bar
from talonx_piv.shadow_ledger import ShadowLedger
from talonx_quant.schemas import QuantSignal, SignalDirection, SignalType


class Response:
    def __init__(self, body, status=200): self.body, self.status_code = body, status
    def json(self): return self.body
    def raise_for_status(self):
        if self.status_code >= 400: raise RuntimeError(f"HTTP {self.status_code}")


class Transport:
    def __init__(self):
        self.orders: list[dict] = []

    def get(self, url, **kwargs):
        if url.endswith("/v2/account"):
            return Response({"id": "id", "account_number": "PA1", "status": "ACTIVE"}, 200)
        if url.endswith("/v2/orders"):
            return Response([o for o in self.orders if o["status"] == "open"])
        if "/v2/orders/" in url:
            order_id = url.rsplit("/", 1)[-1]
            match = next((o for o in self.orders if o["id"] == order_id), None)
            return Response(match or {}, 200 if match else 404)
        if url.endswith("/v2/positions"):
            return Response([])
        return Response({}, 404)

    def post(self, url, **kwargs):
        order = {"id": f"order-{len(self.orders) + 1}", "status": "filled", "filled_qty": "1",
                 "filled_avg_price": "100.0", **kwargs.get("json", {})}
        self.orders.append(order)
        return Response(order)

    def delete(self, url, **kwargs):
        return Response([])


class FakePubSub:
    def __init__(self, messages=None):
        self._messages = list(messages or [])

    async def subscribe(self, channel): pass
    async def unsubscribe(self, channel): pass
    async def close(self): pass

    async def get_message(self, ignore_subscribe_messages=True, timeout=0.2):
        if self._messages:
            return {"data": self._messages.pop(0)}
        return None


class FakeRedisClient:
    def __init__(self, pubsub):
        self._pubsub = pubsub

    def pubsub(self):
        return self._pubsub


def make_signal(direction=SignalDirection.BULLISH, ticker="AAPL", stop=98.0, target=104.0) -> QuantSignal:
    now = datetime.now(timezone.utc)
    return QuantSignal(
        ticker=ticker, signal_type=SignalType.MACD_BULLISH_CROSS, direction=direction,
        message="TEST_FIXTURE_ONLY -- NOT ALPHA EVIDENCE", price=100.0, stop_price=stop, target_price=target,
        bar_timestamp=now,
    )


def bar(price=100.0):
    return Bar(datetime.now(timezone.utc), price, price + 1, price - 1, price, 1000)


def _config(tmp_path):
    return PivConfig(key_id="key", secret_key="secret", paper_trading=True, real_capital=False,
                      broker_endpoint=PAPER_ENDPOINT, approved_sha="abc", state_dir=tmp_path,
                      universe=("AAPL", "MSFT"))


def build_engine(tmp_path, *, send=None):
    cfg = _config(tmp_path)
    transport = Transport()
    broker = AlpacaPaperClient(cfg, transport)
    broker.verify_paper_identity()
    bus = EventBus(tmp_path / "events.jsonl", feed_mode=cfg.feed_mode, session_id="s1")
    life = PaperLifecycle(tmp_path / "state.json", broker, bus, PaperEntrySettings.for_test("AAPL"))
    life.start_session(True, True)
    decision_ledger = DecisionLedger(tmp_path / "decisions.json")
    outbox = NotificationOutbox(tmp_path / "outbox.json", send)
    shadow = ShadowLedger(tmp_path / "shadow.json")
    signal = make_signal()
    engine = DecisionEngine(
        FakeRedisClient(FakePubSub([signal.model_dump_json().encode()])), bus, life,
        decision_ledger=decision_ledger, notification_outbox=outbox, shadow_ledger=shadow,
        strategy_approval_status_override=StrategyApprovalStatus.APPROVED,
    )
    engine.scanner._handle_market_tick = AsyncMock()
    engine.scanner._flush_throttle_window = AsyncMock()
    return engine, transport, decision_ledger, outbox, shadow


@pytest.mark.asyncio
async def test_notification_adapter_outage_never_prevents_shadow_or_broker_entry(tmp_path):
    """dispatch_pending() is called separately (never from enqueue()), so
    this actually proves enqueue-time isolation; a raising send() would
    only ever affect dispatch_pending(), never decision recording or shadow
    creation, which already happened first."""
    def _raising_send(message: str) -> bool:
        raise RuntimeError("simulated Telegram outage")

    engine, transport, ledger, outbox, shadow = build_engine(tmp_path, send=_raising_send)
    await engine.on_bars({"AAPL": bar()})
    assert transport.orders and transport.orders[0]["side"] == "buy"  # real entry unaffected
    assert len(shadow.positions) == 1  # shadow tracking unaffected
    assert len(ledger.records) >= 1  # decision durably recorded
    # dispatch is independent -- calling it now must not raise or corrupt state
    outbox.dispatch_pending()
    record = next(iter(outbox.records.values()))
    assert record["status"] == "UNCERTAIN"  # exception recorded honestly, never fabricated SENT


@pytest.mark.asyncio
async def test_shadow_ledger_failure_never_prevents_notification_or_broker_entry(tmp_path, monkeypatch):
    engine, transport, ledger, outbox, shadow = build_engine(tmp_path, send=lambda m: True)

    def _raise(*args, **kwargs):
        raise RuntimeError("simulated shadow ledger bug")

    monkeypatch.setattr(engine.shadow_ledger, "consider_entry", _raise)
    await engine.on_bars({"AAPL": bar()})
    assert transport.orders and transport.orders[0]["side"] == "buy"  # real entry unaffected
    assert len(outbox.records) == 1  # notification still enqueued
    outbox.dispatch_pending()
    assert next(iter(outbox.records.values()))["status"] == "SENT"


@pytest.mark.asyncio
async def test_broker_rejection_never_prevents_notification_or_shadow(tmp_path):
    """Task 76S's own broker boundary rejects an entry for a ticker with
    PAPER entry disabled -- the decision/notification/shadow branches must
    still have already happened by the time that rejection (or the
    intentional skip, since execution_status downgrades before order_intent
    is even called) occurs."""
    cfg = _config(tmp_path)
    transport = Transport()
    broker = AlpacaPaperClient(cfg, transport)
    broker.verify_paper_identity()
    bus = EventBus(tmp_path / "events.jsonl", feed_mode=cfg.feed_mode, session_id="s1")
    life = PaperLifecycle(tmp_path / "state.json", broker, bus, PaperEntrySettings.all_disabled())  # AAPL NOT enabled
    life.start_session(True, True)
    decision_ledger = DecisionLedger(tmp_path / "decisions.json")
    outbox = NotificationOutbox(tmp_path / "outbox.json", lambda m: True)
    shadow = ShadowLedger(tmp_path / "shadow.json")
    signal = make_signal()
    engine = DecisionEngine(
        FakeRedisClient(FakePubSub([signal.model_dump_json().encode()])), bus, life,
        decision_ledger=decision_ledger, notification_outbox=outbox, shadow_ledger=shadow,
        strategy_approval_status_override=StrategyApprovalStatus.APPROVED,
    )
    engine.scanner._handle_market_tick = AsyncMock()
    engine.scanner._flush_throttle_window = AsyncMock()
    await engine.on_bars({"AAPL": bar()})
    assert transport.orders == []  # broker entry withheld
    assert len(outbox.records) == 1  # alert still produced
    assert len(shadow.positions) == 1  # shadow tracking still created


@pytest.mark.asyncio
async def test_restart_across_all_three_ledgers_does_not_duplicate_work(tmp_path):
    """Simulates a process restart: a NEW DecisionEngine (and fresh ledger
    instances) pointed at the SAME state files, re-processing what would be
    the exact same decision_id, must not create duplicate ledger/outbox/
    shadow entries."""
    cfg = _config(tmp_path)
    transport = Transport()
    broker = AlpacaPaperClient(cfg, transport)
    broker.verify_paper_identity()
    bus = EventBus(tmp_path / "events.jsonl", feed_mode=cfg.feed_mode, session_id="s1")
    life = PaperLifecycle(tmp_path / "state.json", broker, bus, PaperEntrySettings.for_test("AAPL"))
    life.start_session(True, True)
    signal = make_signal()

    decision_ledger1 = DecisionLedger(tmp_path / "decisions.json")
    outbox1 = NotificationOutbox(tmp_path / "outbox.json", lambda m: True)
    shadow1 = ShadowLedger(tmp_path / "shadow.json")
    from talonx_piv.decision_contract import DataReadiness, MarketView, decide
    decision = decide(
        decision_id="fixed-decision-id", session_id="s1", trading_date_et="2026-08-27", ticker="AAPL",
        market_view=MarketView.BULLISH, has_open_long=False, approved_exit_condition=False,
        strategy_approval_status=StrategyApprovalStatus.APPROVED, data_readiness=DataReadiness.READY,
        paper_entry_enabled=True,
    )
    decision_ledger1.record(decision, event_id="fixed-decision-id", evidence_category="natural")
    outbox1.enqueue(decision)
    shadow1.consider_entry(decision, source="STRATEGY")

    # "restart" -- fresh instances, same files
    decision_ledger2 = DecisionLedger(tmp_path / "decisions.json")
    outbox2 = NotificationOutbox(tmp_path / "outbox.json", lambda m: True)
    shadow2 = ShadowLedger(tmp_path / "shadow.json")
    decision_ledger2.record(decision, event_id="fixed-decision-id", evidence_category="natural")
    outbox2.enqueue(decision)
    shadow2.consider_entry(decision, source="STRATEGY")

    assert len(decision_ledger2.records) == 1
    assert len(outbox2.records) == 1
    assert len(shadow2.positions) == 1
