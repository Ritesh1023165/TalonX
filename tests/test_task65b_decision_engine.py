"""Task 65B Part E -- DecisionEngine: wires bars into the real QuantScanner's
live entrypoint, and turns whatever QuantScanner actually publishes into a
real PAPER order. QuantScanner's own gating (confluence/RR/trend/cooldown)
is NOT re-tested here -- that's tests/test_quant_consumer.py's job; this
file tests only DecisionEngine's own glue: does it call the scanner
correctly, and does a published QuantSignal correctly become (or correctly
NOT become, for a bearish signal) a paper order intent."""
from __future__ import annotations

from datetime import datetime, timezone
from unittest.mock import AsyncMock

import pytest

from talonx_piv.broker import AlpacaPaperClient, PaperGuardError
from talonx_piv.config import PAPER_ENDPOINT, PivConfig
from talonx_piv.decision_engine import DecisionEngine
from talonx_piv.events import EventBus
from talonx_piv.execution_settings import PaperEntrySettings
from talonx_piv.lifecycle import PaperLifecycle
from talonx_piv.session_runner import Bar
from talonx_quant.schemas import QuantSignal, SignalDirection, SignalType


class Response:
    def __init__(self, body, status=200): self.body, self.status_code = body, status
    def json(self): return self.body
    def raise_for_status(self):
        if self.status_code >= 400: raise RuntimeError(f"HTTP {self.status_code}")


class Transport:
    def __init__(self):
        self.orders: list[dict] = []
        self.positions: list[dict] = []

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
            return Response(self.positions)
        return Response({}, 404)

    def post(self, url, **kwargs):
        order = {
            "id": f"order-{len(self.orders) + 1}", "status": "filled", "filled_qty": "1", "filled_avg_price": "100.0",
            **kwargs.get("json", {}),
        }
        self.orders.append(order)
        return Response(order)

    def delete(self, url, **kwargs):
        return Response([])


class FakePubSub:
    def __init__(self, messages: list[bytes] | None = None):
        self._messages = list(messages or [])
        self.subscribed: list[str] = []
        self.closed = False

    async def subscribe(self, channel):
        self.subscribed.append(channel)

    async def unsubscribe(self, channel):
        pass

    async def close(self):
        self.closed = True

    async def get_message(self, ignore_subscribe_messages=True, timeout=0.2):
        if self._messages:
            return {"data": self._messages.pop(0)}
        return None


class FakeRedisClient:
    def __init__(self, pubsub: FakePubSub):
        self._pubsub = pubsub

    def pubsub(self):
        return self._pubsub


def make_signal(direction: SignalDirection, ticker="AAPL", stop=98.0, target=104.0) -> QuantSignal:
    now = datetime.now(timezone.utc)
    return QuantSignal(
        ticker=ticker, signal_type=SignalType.MACD_BULLISH_CROSS if direction == SignalDirection.BULLISH else SignalType.MACD_BEARISH_CROSS,
        direction=direction, message="test", price=100.0, stop_price=stop, target_price=target, bar_timestamp=now,
    )


def config(tmp_path, **overrides):
    values = dict(key_id="key", secret_key="secret", paper_trading=True, real_capital=False,
                  broker_endpoint=PAPER_ENDPOINT, approved_sha="abc", state_dir=tmp_path,
                  universe=("AAPL", "MSFT"))
    values.update(overrides)
    return PivConfig(**values)


def build_engine(tmp_path, messages=None, **cfg_overrides):
    cfg = config(tmp_path, **cfg_overrides)
    transport = Transport()
    broker = AlpacaPaperClient(cfg, transport)
    broker.verify_paper_identity()
    bus = EventBus(tmp_path / "events.jsonl", feed_mode=cfg.feed_mode)
    # Task 76S: TEST_FIXTURE_ONLY -- NOT ALPHA EVIDENCE. AAPL explicitly
    # enabled to preserve this file's pre-existing natural-signal/duplicate/
    # broker-verification test intent under the new fail-closed default.
    life = PaperLifecycle(tmp_path / "state.json", broker, bus, PaperEntrySettings.for_test("AAPL"))
    life.start_session(True, True)
    engine = DecisionEngine(FakeRedisClient(FakePubSub(messages)), bus, life)
    engine.scanner._handle_market_tick = AsyncMock()
    engine.scanner._flush_throttle_window = AsyncMock()
    return engine, transport, bus, life


def bar(price=100.0):
    return Bar(datetime.now(timezone.utc), price, price + 1, price - 1, price, 1000)


@pytest.mark.asyncio
async def test_feeds_bars_into_real_scanner_entrypoint(tmp_path):
    engine, *_ = build_engine(tmp_path)
    b = bar()
    await engine.on_bars({"AAPL": b})
    engine.scanner._handle_market_tick.assert_awaited_once()
    payload = engine.scanner._handle_market_tick.await_args.args[0]
    assert payload["event_type"] == "bar" and payload["symbol"] == "AAPL"
    engine.scanner._flush_throttle_window.assert_awaited_once()


@pytest.mark.asyncio
async def test_natural_bullish_signal_reaches_order_intent_and_broker(tmp_path):
    signal = make_signal(SignalDirection.BULLISH)
    engine, transport, bus, life = build_engine(tmp_path, messages=[signal.model_dump_json().encode()])
    await engine.on_bars({"AAPL": bar()})
    assert transport.orders and transport.orders[0]["side"] == "buy"
    assert transport.orders[0]["symbol"] == "AAPL"


@pytest.mark.asyncio
async def test_bearish_signal_does_not_open_a_position_long_only(tmp_path):
    signal = make_signal(SignalDirection.BEARISH)
    engine, transport, bus, life = build_engine(tmp_path, messages=[signal.model_dump_json().encode()])
    await engine.on_bars({"AAPL": bar()})
    assert transport.orders == []  # SIGNAL still recorded, but no order for LONG_ONLY


@pytest.mark.asyncio
async def test_signal_events_tagged_strategy_and_not_alpha_evidence(tmp_path):
    signal = make_signal(SignalDirection.BULLISH)
    engine, transport, bus, life = build_engine(tmp_path, messages=[signal.model_dump_json().encode()])
    await engine.on_bars({"AAPL": bar()})
    rows = bus.path.read_text(encoding="utf-8")
    assert '"event": "SIGNAL"' in rows
    assert '"source": "STRATEGY"' in rows
    assert '"alpha_evidence": false' in rows


@pytest.mark.asyncio
async def test_stop_hit_triggers_controlled_exit(tmp_path):
    signal = make_signal(SignalDirection.BULLISH, stop=98.0, target=104.0)
    engine, transport, bus, life = build_engine(tmp_path, messages=[signal.model_dump_json().encode()])
    await engine.on_bars({"AAPL": bar(100.0)})  # entry fills at 100
    assert "AAPL" in engine.positions
    stop_bar = Bar(datetime.now(timezone.utc), 99.0, 99.5, 97.0, 98.0, 1000)  # low breaches stop=98
    await engine.on_bars({"AAPL": stop_bar})
    assert "AAPL" not in engine.positions
    assert len(transport.orders) == 2 and transport.orders[1]["side"] == "sell"
    assert '"event": "STOP_TRIGGERED"' in bus.path.read_text(encoding="utf-8")


@pytest.mark.asyncio
async def test_requires_paper_verification_fails_closed_on_broker_error(tmp_path):
    """No verify_paper_identity() call at all -- broker.identity stays None,
    so submit_order's _require_verified() guard trips. DecisionEngine must
    catch this as PaperGuardError and emit BROKER_ERROR, never crash or
    silently drop it."""
    signal = make_signal(SignalDirection.BULLISH)
    cfg = config(tmp_path)
    transport = Transport()
    broker = AlpacaPaperClient(cfg, transport)  # deliberately never verified
    bus = EventBus(tmp_path / "events.jsonl", feed_mode=cfg.feed_mode)
    # Task 76S: TEST_FIXTURE_ONLY -- NOT ALPHA EVIDENCE. AAPL explicitly
    # enabled to preserve this file's pre-existing natural-signal/duplicate/
    # broker-verification test intent under the new fail-closed default.
    life = PaperLifecycle(tmp_path / "state.json", broker, bus, PaperEntrySettings.for_test("AAPL"))
    life.state.session_enabled = True
    engine = DecisionEngine(FakeRedisClient(FakePubSub([signal.model_dump_json().encode()])), bus, life)
    engine.scanner._handle_market_tick = AsyncMock()
    engine.scanner._flush_throttle_window = AsyncMock()
    await engine.on_bars({"AAPL": bar()})
    assert transport.orders == []
    assert '"event": "BROKER_ERROR"' in bus.path.read_text(encoding="utf-8")


def test_real_capital_execution_remains_unsupported(tmp_path):
    cfg = config(tmp_path, real_capital=True)
    transport = Transport()
    broker = AlpacaPaperClient(cfg, transport)
    with pytest.raises(PaperGuardError):
        broker.verify_paper_identity()


def test_duplicate_protection_unchanged_with_source_tagging(tmp_path):
    cfg = config(tmp_path)
    transport = Transport()
    broker = AlpacaPaperClient(cfg, transport)
    broker.verify_paper_identity()
    bus = EventBus(tmp_path / "events.jsonl", feed_mode=cfg.feed_mode)
    # Task 76S: TEST_FIXTURE_ONLY -- NOT ALPHA EVIDENCE. AAPL explicitly
    # enabled to preserve this file's pre-existing natural-signal/duplicate/
    # broker-verification test intent under the new fail-closed default.
    life = PaperLifecycle(tmp_path / "state.json", broker, bus, PaperEntrySettings.for_test("AAPL"))
    life.start_session(True, True)
    life.order_intent("sig", "AAPL", "buy", 1, source="STRATEGY", alpha_evidence=False)
    with pytest.raises(PaperGuardError):
        life.order_intent("sig", "AAPL", "buy", 1, source="STRATEGY", alpha_evidence=False)
    assert len(transport.orders) == 1
