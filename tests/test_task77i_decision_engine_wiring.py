"""Task 77I Stage 1 -- decision_contract wired into the ACTUAL runtime
decision path (talonx_piv.decision_engine.DecisionEngine), proven via
integration tests (not just direct decide() calls). TEST_FIXTURE_ONLY --
NOT ALPHA EVIDENCE throughout -- every signal/bar here is synthetic, every
broker call goes through an in-memory Transport, never a real socket."""
from __future__ import annotations

from datetime import datetime, timezone
from unittest.mock import AsyncMock

import pytest

from talonx_piv.broker import AlpacaPaperClient
from talonx_piv.config import PAPER_ENDPOINT, PivConfig
from talonx_piv.decision_contract import Recommendation, StrategyApprovalStatus
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


def make_signal(direction: SignalDirection, ticker="AAPL", stop=98.0, target=104.0) -> QuantSignal:
    now = datetime.now(timezone.utc)
    return QuantSignal(
        ticker=ticker, signal_type=SignalType.MACD_BULLISH_CROSS if direction == SignalDirection.BULLISH else SignalType.MACD_BEARISH_CROSS,
        direction=direction, message="TEST_FIXTURE_ONLY -- NOT ALPHA EVIDENCE", price=100.0,
        stop_price=stop, target_price=target, bar_timestamp=now,
    )


def bar(price=100.0, *, offset_seconds=0.0):
    # offset_seconds lets a test build a SECOND, later bar with a distinct
    # timestamp deterministically -- two back-to-back datetime.now(utc)
    # calls can otherwise land on the identical wall-clock value under
    # Windows' clock resolution, which would collide decision_id (a real
    # market data feed never emits two distinct bars with an identical
    # timestamp for the same symbol, so this is a test-fixture-only
    # concern, not a production one -- see this file's own investigation
    # note in the git history for Task 77I).
    from datetime import timedelta
    return Bar(datetime.now(timezone.utc) + timedelta(seconds=offset_seconds), price, price + 1, price - 1, price, 1000)


def _config(tmp_path, **overrides):
    values = dict(key_id="key", secret_key="secret", paper_trading=True, real_capital=False,
                  broker_endpoint=PAPER_ENDPOINT, approved_sha="abc", state_dir=tmp_path,
                  universe=("AAPL", "MSFT"))
    values.update(overrides)
    return PivConfig(**values)


def build_engine(tmp_path, *, messages=None, enabled=("AAPL",), approval_override=None):
    cfg = _config(tmp_path)
    transport = Transport()
    broker = AlpacaPaperClient(cfg, transport)
    broker.verify_paper_identity()
    bus = EventBus(tmp_path / "events.jsonl", feed_mode=cfg.feed_mode, session_id="s1")
    life = PaperLifecycle(tmp_path / "state.json", broker, bus, PaperEntrySettings.for_test(*enabled))
    life.start_session(True, True)
    decision_ledger = DecisionLedger(tmp_path / "decisions.json")
    outbox = NotificationOutbox(tmp_path / "outbox.json", lambda msg: True)
    shadow = ShadowLedger(tmp_path / "shadow.json")
    engine = DecisionEngine(
        FakeRedisClient(FakePubSub(messages)), bus, life,
        decision_ledger=decision_ledger, notification_outbox=outbox, shadow_ledger=shadow,
        strategy_approval_status_override=approval_override,
    )
    engine.scanner._handle_market_tick = AsyncMock()
    engine.scanner._flush_throttle_window = AsyncMock()
    return engine, transport, bus, life, decision_ledger, outbox, shadow


# ---------------------------------------------------------------------------
# Required behaviour-table rows -- integration level
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_bearish_while_flat_cannot_create_a_short(tmp_path):
    signal = make_signal(SignalDirection.BEARISH)
    engine, transport, bus, life, ledger, outbox, shadow = build_engine(tmp_path, messages=[signal.model_dump_json().encode()])
    await engine.on_bars({"AAPL": bar()})
    assert transport.orders == []
    decision = next(iter(ledger.records.values()))
    assert decision["recommendation"] == "NO_TRADE"


@pytest.mark.asyncio
async def test_unvalidated_strategy_cannot_generate_actionable_buy_even_when_approved_and_bullish_market(tmp_path):
    """Default construction (no approval override) -- the ACTUAL production
    posture. A genuine BULLISH signal, PAPER entry enabled for the ticker,
    everything else favorable -- STILL produces zero broker orders, because
    strategy_approval_status is hardcoded UNVALIDATED for every real caller."""
    signal = make_signal(SignalDirection.BULLISH)
    engine, transport, bus, life, ledger, outbox, shadow = build_engine(
        tmp_path, messages=[signal.model_dump_json().encode()], enabled=("AAPL",), approval_override=None,
    )
    await engine.on_bars({"AAPL": bar()})
    assert transport.orders == []
    decision = next(iter(ledger.records.values()))
    assert decision["recommendation"] == "NO_TRADE"
    assert "STRATEGY_UNVALIDATED_NO_ACTIONABLE_BUY_PROMOTION" in decision["reason_codes"]
    assert decision["strategy_approval_status"] == "UNVALIDATED"


@pytest.mark.asyncio
async def test_approved_strategy_bullish_signal_produces_actionable_buy_and_reaches_broker(tmp_path):
    signal = make_signal(SignalDirection.BULLISH)
    engine, transport, bus, life, ledger, outbox, shadow = build_engine(
        tmp_path, messages=[signal.model_dump_json().encode()],
        approval_override=StrategyApprovalStatus.APPROVED,
    )
    await engine.on_bars({"AAPL": bar()})
    assert transport.orders and transport.orders[0]["side"] == "buy"
    decision = next(iter(ledger.records.values()))
    assert decision["recommendation"] == "BUY"


@pytest.mark.asyncio
async def test_paper_entry_disabled_preserves_buy_decision_but_blocks_broker_entry(tmp_path):
    """decision.recommendation stays BUY (never downgraded), only the
    broker entry itself is withheld -- and it is still fully recorded."""
    signal = make_signal(SignalDirection.BULLISH)
    engine, transport, bus, life, ledger, outbox, shadow = build_engine(
        tmp_path, messages=[signal.model_dump_json().encode()], enabled=(),  # AAPL NOT enabled
        approval_override=StrategyApprovalStatus.APPROVED,
    )
    await engine.on_bars({"AAPL": bar()})
    assert transport.orders == []
    decision = next(iter(ledger.records.values()))
    assert decision["recommendation"] == "BUY"
    assert decision["decision_execution_status"] == "ENTRY_BLOCKED_PAPER_DISABLED"


@pytest.mark.asyncio
async def test_existing_long_with_no_approved_exit_holds_no_sell(tmp_path):
    """An open position, fed a bar that hits neither stop nor target --
    decide() must resolve HOLD and order_intent must never be called for
    a sell."""
    entry_signal = make_signal(SignalDirection.BULLISH, stop=90.0, target=110.0)
    engine, transport, bus, life, ledger, outbox, shadow = build_engine(
        tmp_path, messages=[entry_signal.model_dump_json().encode()],
        approval_override=StrategyApprovalStatus.APPROVED,
    )
    await engine.on_bars({"AAPL": bar(100.0)})  # opens
    assert "AAPL" in engine.positions
    orders_after_entry = len(transport.orders)
    idle_bar = bar(100.2, offset_seconds=60.0)  # neither stop nor target, a full minute later
    await engine.on_bars({"AAPL": idle_bar})
    assert "AAPL" in engine.positions  # still held
    assert len(transport.orders) == orders_after_entry  # no new order
    hold_decisions = [r for r in ledger.records.values() if r["recommendation"] == "HOLD"]
    assert hold_decisions


@pytest.mark.asyncio
async def test_existing_long_plus_authorised_exit_sells(tmp_path):
    entry_signal = make_signal(SignalDirection.BULLISH, stop=98.0, target=104.0)
    engine, transport, bus, life, ledger, outbox, shadow = build_engine(
        tmp_path, messages=[entry_signal.model_dump_json().encode()],
        approval_override=StrategyApprovalStatus.APPROVED,
    )
    await engine.on_bars({"AAPL": bar(100.0)})  # opens
    stop_bar = bar(98.0, offset_seconds=60.0)  # low breaches stop=98, a full minute later
    await engine.on_bars({"AAPL": stop_bar})
    assert "AAPL" not in engine.positions
    assert transport.orders[-1]["side"] == "sell"
    sell_decisions = [r for r in ledger.records.values() if r["recommendation"] == "SELL_TO_CLOSE"]
    assert sell_decisions


@pytest.mark.asyncio
async def test_bearish_observation_while_holding_does_not_invent_an_exit(tmp_path):
    """A BEARISH incoming signal while already holding a long must resolve
    HOLD (via _handle_entry's own decide() call, approved_exit_condition
    always False there) -- never SELL_TO_CLOSE from market_view alone."""
    entry_signal = make_signal(SignalDirection.BULLISH, ticker="AAPL", stop=90.0, target=110.0)
    bearish_signal = make_signal(SignalDirection.BEARISH, ticker="AAPL", stop=90.0, target=110.0)
    engine, transport, bus, life, ledger, outbox, shadow = build_engine(
        tmp_path, messages=[entry_signal.model_dump_json().encode()],
        approval_override=StrategyApprovalStatus.APPROVED,
    )
    await engine.on_bars({"AAPL": bar(100.0)})  # opens
    orders_after_entry = len(transport.orders)
    engine._pubsub._messages.append(bearish_signal.model_dump_json().encode())
    await engine.on_bars({"AAPL": bar(100.0, offset_seconds=60.0)})  # feeds the bearish signal while holding, a minute later
    assert "AAPL" in engine.positions  # still held -- no exit invented
    assert len(transport.orders) == orders_after_entry


@pytest.mark.asyncio
async def test_data_insufficient_would_be_no_trade_with_explicit_reason(tmp_path):
    """DataReadiness is architecturally always READY at this call site
    (session_runner.py gates readiness before ever calling on_bars) --
    verified directly via decide() (unit-level, not integration, since the
    integration path structurally cannot produce a non-READY call here;
    this documents that invariant rather than fabricating an unreachable
    integration scenario)."""
    from talonx_piv.decision_contract import DataReadiness, MarketView, decide
    decision = decide(
        decision_id="x", session_id="s1", trading_date_et="2026-08-27", ticker="AAPL",
        market_view=MarketView.BULLISH, has_open_long=False, approved_exit_condition=False,
        strategy_approval_status=StrategyApprovalStatus.APPROVED, data_readiness=DataReadiness.DATA_NOT_READY,
        paper_entry_enabled=True,
    )
    assert decision.recommendation == Recommendation.NO_TRADE
    assert any(r.startswith("DATA_INSUFFICIENT_FOR_ENTRY") for r in decision.reason_codes)


@pytest.mark.asyncio
async def test_synthetic_approved_fixture_never_reachable_from_production_construction(tmp_path):
    """cli.py never passes strategy_approval_status_override -- confirmed
    here by constructing DecisionEngine the same way cli.py's runtime()
    does (no override argument at all) and observing UNVALIDATED."""
    signal = make_signal(SignalDirection.BULLISH)
    engine, transport, bus, life, ledger, outbox, shadow = build_engine(
        tmp_path, messages=[signal.model_dump_json().encode()],
    )  # approval_override defaults to None
    await engine.on_bars({"AAPL": bar()})
    decision = next(iter(ledger.records.values()))
    assert decision["strategy_approval_status"] == "UNVALIDATED"


# ---------------------------------------------------------------------------
# Decision/notification/shadow independence
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_approved_buy_creates_decision_notification_and_shadow_records(tmp_path):
    signal = make_signal(SignalDirection.BULLISH)
    engine, transport, bus, life, ledger, outbox, shadow = build_engine(
        tmp_path, messages=[signal.model_dump_json().encode()],
        approval_override=StrategyApprovalStatus.APPROVED,
    )
    await engine.on_bars({"AAPL": bar()})
    # Two decision records this tick: the entry decision (BUY) and an
    # immediate exit-check decision for the position just opened (HOLD,
    # since neither stop nor target can be hit on the same bar it opened)
    # -- both correctly recorded, but only the BUY is alert/shadow-worthy.
    recommendations = sorted(r["recommendation"] for r in ledger.records.values())
    assert recommendations == ["BUY", "HOLD"]
    assert len(outbox.records) == 1
    assert len(shadow.positions) == 1


@pytest.mark.asyncio
async def test_paper_disabled_actionable_decision_still_creates_alert_and_shadow(tmp_path):
    signal = make_signal(SignalDirection.BULLISH)
    engine, transport, bus, life, ledger, outbox, shadow = build_engine(
        tmp_path, messages=[signal.model_dump_json().encode()], enabled=(),
        approval_override=StrategyApprovalStatus.APPROVED,
    )
    await engine.on_bars({"AAPL": bar()})
    assert transport.orders == []  # broker entry withheld
    assert len(outbox.records) == 1  # alert still produced
    assert len(shadow.positions) == 1  # shadow tracking still created


@pytest.mark.asyncio
async def test_grep_confirms_cli_never_sets_the_test_only_override():
    """cli.py may reference the field name in a comment (documenting that it
    never sets it), but must never actually pass it as a keyword argument."""
    from pathlib import Path
    text = Path("talonx_piv/cli.py").read_text(encoding="utf-8")
    assert "strategy_approval_status_override=" not in text
