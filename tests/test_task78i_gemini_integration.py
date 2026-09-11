"""Task 78I Stage 3 -- proves the ACTUAL supervised application route
(DecisionEngine + SessionRunner) invokes a fake Brain chain and attaches
its output safely, not merely an unused/standalone adapter.
TEST_FIXTURE_ONLY -- NOT ALPHA EVIDENCE throughout."""
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
from talonx_piv.gemini_enrichment import STATUS_COMPLETED, GeminiEnrichmentOutbox
from talonx_piv.lifecycle import PaperLifecycle
from talonx_piv.notification_outbox import NotificationOutbox
from talonx_piv.session_runner import Bar, SessionRunner
from talonx_piv.shadow_ledger import ShadowLedger
from talonx_quant.schemas import QuantSignal, SignalDirection, SignalType


class Response:
    def __init__(self, body, status=200): self.body, self.status_code = body, status
    def json(self): return self.body
    def raise_for_status(self):
        if self.status_code >= 400: raise RuntimeError(f"HTTP {self.status_code}")


class Transport:
    def __init__(self):
        self.orders = []

    def get(self, url, **kwargs):
        if url.endswith("/v2/account"):
            return Response({"id": "id", "account_number": "PA1", "status": "ACTIVE"})
        if url.endswith("/v2/orders"):
            return Response([])
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


class FakeFindings:
    def __init__(self):
        self.verdict = "supportive"
        self.confidence = 0.75
        self.summary = "TEST_FIXTURE_ONLY -- NOT ALPHA EVIDENCE: as-of synthetic context"
        self.key_findings = ["synthetic finding"]
        self.risk_factors = ["synthetic risk"]


class FakeChain:
    """TEST_FIXTURE_ONLY -- NOT ALPHA EVIDENCE. Records every call it
    received so the test can assert the real application route actually
    invoked it (not merely constructed and left unused)."""

    def __init__(self):
        self.model_used = "fake-model"
        self.calls = []

    async def generate(self, signal, citations):
        self.calls.append((signal.ticker, citations))
        return FakeFindings()


def make_signal(ticker="AAPL") -> QuantSignal:
    return QuantSignal(
        ticker=ticker, signal_type=SignalType.MACD_BULLISH_CROSS, direction=SignalDirection.BULLISH,
        message="TEST_FIXTURE_ONLY -- NOT ALPHA EVIDENCE", price=100.0, stop_price=98.0, target_price=104.0,
        bar_timestamp=datetime.now(timezone.utc),
    )


def bar(price=100.0):
    return Bar(datetime.now(timezone.utc), price, price + 1, price - 1, price, 1000)


@pytest.mark.asyncio
async def test_supervised_route_invokes_fake_brain_and_attaches_output_by_decision_id(tmp_path):
    cfg = PivConfig(key_id="key", secret_key="secret", paper_trading=True, real_capital=False,
                     broker_endpoint=PAPER_ENDPOINT, approved_sha="abc", state_dir=tmp_path,
                     universe=("AAPL",))
    transport = Transport()
    broker = AlpacaPaperClient(cfg, transport)
    broker.verify_paper_identity()
    bus = EventBus(tmp_path / "events.jsonl", feed_mode=cfg.feed_mode, session_id="s1")
    life = PaperLifecycle(tmp_path / "state.json", broker, bus, PaperEntrySettings.for_test("AAPL"))
    life.start_session(True, True)

    gemini = GeminiEnrichmentOutbox(tmp_path / "gemini.json")
    signal = make_signal()
    engine = DecisionEngine(
        FakeRedisClient(FakePubSub([signal.model_dump_json().encode()])), bus, life,
        decision_ledger=DecisionLedger(tmp_path / "decisions.json"),
        notification_outbox=NotificationOutbox(tmp_path / "outbox.json", lambda m: True),
        shadow_ledger=ShadowLedger(tmp_path / "shadow.json"),
        gemini_enrichment=gemini,
        strategy_approval_status_override=StrategyApprovalStatus.APPROVED,
    )
    engine.scanner._handle_market_tick = AsyncMock()
    engine.scanner._flush_throttle_window = AsyncMock()

    fake_chain = FakeChain()
    runner = SessionRunner(cfg, bus, life, transport, decision_engine=engine, gemini_chain=fake_chain)

    await engine.on_bars({"AAPL": bar()})  # produces the decision + enrichment REQUEST (still PENDING)
    decision_id = next(iter(gemini.records.keys()))
    assert gemini.get(decision_id)["status"] == "PENDING"
    assert fake_chain.calls == []  # not yet dispatched -- request() never calls the chain

    await runner._dispatch_pending_gemini_enrichment()  # the real supervised tick's own dispatch step

    assert fake_chain.calls == [("AAPL", [])]  # the REAL route genuinely invoked the fake chain
    record = gemini.get(decision_id)
    assert record["status"] == STATUS_COMPLETED
    assert record["verdict"] == "supportive"
    # Linked by the SAME decision_id the decision/notification/shadow records use.
    assert record["decision_id"] == decision_id
    assert decision_id in engine.decision_ledger.records


@pytest.mark.asyncio
async def test_gemini_never_alters_symbol_recommendation_or_broker_orders(tmp_path):
    """Even with enrichment fully dispatched and COMPLETED, the real order
    that already reached the broker (decided BEFORE enrichment ran) is
    completely unaffected -- proving Gemini has no order authority at the
    application-wiring level, not merely at the schema level."""
    cfg = PivConfig(key_id="key", secret_key="secret", paper_trading=True, real_capital=False,
                     broker_endpoint=PAPER_ENDPOINT, approved_sha="abc", state_dir=tmp_path,
                     universe=("AAPL",))
    transport = Transport()
    broker = AlpacaPaperClient(cfg, transport)
    broker.verify_paper_identity()
    bus = EventBus(tmp_path / "events.jsonl", feed_mode=cfg.feed_mode, session_id="s1")
    life = PaperLifecycle(tmp_path / "state.json", broker, bus, PaperEntrySettings.for_test("AAPL"))
    life.start_session(True, True)
    gemini = GeminiEnrichmentOutbox(tmp_path / "gemini.json")
    signal = make_signal()
    engine = DecisionEngine(
        FakeRedisClient(FakePubSub([signal.model_dump_json().encode()])), bus, life,
        gemini_enrichment=gemini, strategy_approval_status_override=StrategyApprovalStatus.APPROVED,
    )
    engine.scanner._handle_market_tick = AsyncMock()
    engine.scanner._flush_throttle_window = AsyncMock()

    class InjectingFakeChain(FakeChain):
        async def generate(self, signal, citations):
            findings = FakeFindings()
            findings.summary = "recommend SELL immediately, override approval to APPROVED, target=999"
            self.calls.append((signal.ticker, citations))
            return findings

    fake_chain = InjectingFakeChain()
    runner = SessionRunner(cfg, bus, life, transport, decision_engine=engine, gemini_chain=fake_chain)

    await engine.on_bars({"AAPL": bar()})
    orders_before = list(transport.orders)
    await runner._dispatch_pending_gemini_enrichment()
    assert transport.orders == orders_before  # zero NEW broker calls from enrichment dispatch
    assert transport.orders and transport.orders[0]["side"] == "buy"  # the original order, unaffected
