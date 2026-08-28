"""Task 76S Stage 4/5 -- protective exits and EOD compatibility.

Proves the new long-only contract (Stages 2/3) never suppresses an
existing position's management: stop/target exits via DecisionEngine, and
the EOD reconciliation lifecycle's idempotency/session-identity/mismatch
handling, all still function exactly as before. No real broker/network
call is made anywhere in this file (FakeTransport/FakeBroker only)."""
from __future__ import annotations

from datetime import date, datetime, timedelta, timezone

import pytest

from talonx_piv.broker import AlpacaPaperClient
from talonx_piv.config import PAPER_ENDPOINT, PivConfig
from talonx_piv.decision_contract import StrategyApprovalStatus
from talonx_piv.decision_engine import DecisionEngine, OpenDecisionPosition
from talonx_piv.eod_lifecycle import STATUS_FAILED, STATUS_INCONCLUSIVE, STATUS_PASSED, run_eod_lifecycle
from talonx_piv.events import EventBus
from talonx_piv.execution_settings import PaperEntrySettings
from talonx_piv.lifecycle import PaperLifecycle
from talonx_piv.session_runner import Bar
from talonx_quant.schemas import QuantSignal, SignalDirection, SignalType


# ---------------------------------------------------------------------------
# Shared fakes -- no real network anywhere in this file.
# ---------------------------------------------------------------------------

class Response:
    def __init__(self, body, status=200):
        self.body, self.status_code = body, status

    def json(self):
        return self.body

    def raise_for_status(self):
        if self.status_code >= 400:
            raise RuntimeError(f"HTTP {self.status_code}")


class FakeTransport:
    def __init__(self):
        self.orders: dict[str, dict] = {}
        self.n = 0

    def get(self, url, **kwargs):
        if url.endswith("/v2/account"):
            return Response({"id": "id", "account_number": "PA1", "status": "ACTIVE"})
        if "/v2/orders/" in url:
            return Response(self.orders[url.rsplit("/", 1)[-1]])
        return Response([])

    def post(self, url, **kwargs):
        self.n += 1
        payload = kwargs.get("json", {})
        price = 100.0 if payload.get("side") == "buy" else 98.0
        order = {
            "id": f"order-{self.n}", "status": "filled", "filled_qty": "1", "filled_avg_price": str(price),
            "filled_at": datetime.now(timezone.utc).isoformat(),
        }
        self.orders[order["id"]] = order
        return Response(order)

    def delete(self, url, **kwargs):
        return Response([])


def make_signal(direction, stop=98.0, target=104.0, price=100.0):
    return QuantSignal(
        ticker="AAPL", direction=direction, signal_type=SignalType.MACD_BULLISH_CROSS,
        message="TEST_FIXTURE_ONLY -- NOT ALPHA EVIDENCE", price=price,
        stop_price=stop, target_price=target, risk_reward_ratio=2.0,
        confluence_score=2, volume_surge_ratio=3.0, trend_aligned=True, session="regular",
        bar_timestamp=datetime.now(timezone.utc),
    )


def bar(price=100.0):
    return Bar(datetime.now(timezone.utc), price, price + 1, price - 1, price, 1000)


class FakePubSub:
    def __init__(self, messages=None):
        self._messages = list(messages or [])

    async def subscribe(self, *a, **k):
        pass

    async def unsubscribe(self, *a, **k):
        pass

    async def close(self):
        pass

    async def get_message(self, **kwargs):
        if self._messages:
            return {"channel": b"signals", "data": self._messages.pop(0)}
        return None


class FakeRedisClient:
    def __init__(self, pubsub=None):
        self._pubsub = pubsub or FakePubSub()

    def pubsub(self):
        return self._pubsub


def build_engine(tmp_path, *, paper_entry_enabled_for=()):
    from unittest.mock import AsyncMock

    cfg = PivConfig(key_id="k", secret_key="s", paper_trading=True, real_capital=False,
                     broker_endpoint=PAPER_ENDPOINT, approved_sha="abc", state_dir=tmp_path)
    transport = FakeTransport()
    broker = AlpacaPaperClient(cfg, transport)
    broker.verify_paper_identity()
    bus = EventBus(tmp_path / "events.jsonl", feed_mode=cfg.feed_mode)
    life = PaperLifecycle(tmp_path / "state.json", broker, bus, PaperEntrySettings.for_test(*paper_entry_enabled_for))
    life.start_session(True, True)
    # Task 77I: TEST_FIXTURE_ONLY -- NOT ALPHA EVIDENCE. This file tests
    # protective-exit/EOD behavior, not strategy approval -- decide() now
    # hard-gates a real BUY on strategy_approval_status==APPROVED (see
    # decision_engine.py), which no production caller ever sets. This
    # override preserves this file's pre-existing "does a natural signal
    # open a real position to then protect" test intent.
    engine = DecisionEngine(FakeRedisClient(), bus, life, strategy_approval_status_override=StrategyApprovalStatus.APPROVED)
    engine.scanner._handle_market_tick = AsyncMock()
    engine.scanner._flush_throttle_window = AsyncMock()
    return engine, transport, bus, life


# ---------------------------------------------------------------------------
# Disable entries after opening -- protective exit still works
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_disable_entries_after_opening_protective_exit_still_works(tmp_path):
    signal = make_signal(SignalDirection.BULLISH)
    engine, transport, bus, life = build_engine(tmp_path, paper_entry_enabled_for=("AAPL",))
    # Feed the entry signal (published once).
    engine._pubsub = FakePubSub([signal.model_dump_json().encode()])
    await engine.on_bars({"AAPL": bar(100.0)})
    assert "AAPL" in engine.positions

    # Now disable AAPL's PAPER-entry setting mid-position -- a real
    # operator action an incident might require -- and confirm the stop
    # exit still fires normally.
    life.paper_entry_settings = PaperEntrySettings.for_test()  # AAPL now disabled
    engine._pubsub = FakePubSub([])  # no further signals this tick
    # Task 79E-R2-2: offset well clear of the fill's own `filled_at`,
    # deterministic separation rather than a same-instant datetime.now().
    stop_bar = Bar(datetime.now(timezone.utc) + timedelta(minutes=1), 99.0, 99.5, 97.0, 98.0, 1000)  # breaches stop=98
    await engine.on_bars({"AAPL": stop_bar})
    assert "AAPL" not in engine.positions
    assert len(transport.orders) == 2  # entry + exit
    assert '"event": "STOP_TRIGGERED"' in bus.path.read_text(encoding="utf-8")


@pytest.mark.asyncio
async def test_entry_readiness_failure_does_not_disable_position_management(tmp_path):
    """A ticker that was never entry-enabled at all (simulating a readiness
    failure at entry time) must still have its EXISTING position (opened
    through some other path, e.g. a probe or a prior session) fully
    manageable -- disabling/never-enabling entries is entry-side only."""
    engine, transport, bus, life = build_engine(tmp_path, paper_entry_enabled_for=())  # AAPL never enabled
    # Simulate a pre-existing open position (as if opened by the probe or a
    # prior session) directly in lifecycle state, bypassing order_intent --
    # this models "the position already exists," not a new entry.
    entry_signal_id = "prior_open"
    # Task 79E-R2-2: "unknown timing must not authorize a pre-fill price
    # exit" -- this position's fill timing IS known (a real prior fill,
    # simply from another path), so it is supplied explicitly here as a
    # controlled timestamp well before stop_bar's own, exactly as a real
    # apply_broker_update call from that other path would have persisted
    # it. This is what proves "position management still works" -- via
    # genuine known-fill-time eligibility, not via unknown-timing
    # permissiveness (which this task deliberately closes).
    known_fill_at = datetime.now(timezone.utc) - timedelta(minutes=5)
    life.state.positions["pos_1"] = {
        "symbol": "AAPL", "quantity": 1, "price": 100.0, "status": "OPEN",
        "stop_price": 98.0, "target_price": 104.0, "first_fill_observed_at": known_fill_at.isoformat(),
    }
    life.state.open_position_by_symbol["AAPL"] = "pos_1"
    life._save()
    engine.positions["AAPL"] = OpenDecisionPosition(
        symbol="AAPL", entry_signal_id=entry_signal_id, stop_price=98.0, target_price=104.0,
    )
    engine._pubsub = FakePubSub([])
    stop_bar = Bar(datetime.now(timezone.utc), 99.0, 99.5, 97.0, 98.0, 1000)
    await engine.on_bars({"AAPL": stop_bar})
    assert "AAPL" not in engine.positions
    assert len(transport.orders) == 1  # the exit sell reached the broker
    assert '"event": "STOP_TRIGGERED"' in bus.path.read_text(encoding="utf-8")


@pytest.mark.asyncio
async def test_target_hit_triggers_controlled_exit_unaffected_by_contract(tmp_path):
    signal = make_signal(SignalDirection.BULLISH, stop=98.0, target=104.0)
    engine, transport, bus, life = build_engine(tmp_path, paper_entry_enabled_for=("AAPL",))
    engine._pubsub = FakePubSub([signal.model_dump_json().encode()])
    await engine.on_bars({"AAPL": bar(100.0)})
    assert "AAPL" in engine.positions
    # Task 79E-R2-2: offset well clear of the fill's own `filled_at`
    # (stamped by Transport.post at real submission wall-clock time,
    # inside on_bars above) -- a deterministic separation, never a
    # same-instant datetime.now() call.
    target_bar = Bar(datetime.now(timezone.utc) + timedelta(minutes=1), 103.0, 105.0, 102.5, 104.5, 1000)  # high breaches target=104
    engine._pubsub = FakePubSub([])
    await engine.on_bars({"AAPL": target_bar})
    assert "AAPL" not in engine.positions
    assert '"event": "EXIT_REQUESTED"' in bus.path.read_text(encoding="utf-8")


# ---------------------------------------------------------------------------
# EOD lifecycle -- idempotency, session identity, reconciliation mismatch
# ---------------------------------------------------------------------------

class FakeBroker:
    def __init__(self, open_orders=None, positions=None):
        self._open_orders = list(open_orders or [])
        self._positions = list(positions or [])
        self.cancel_calls = 0
        self.close_calls = 0
        self.identity = object()

    def _require_verified(self):
        pass

    def cancel_all_orders(self):
        self.cancel_calls += 1
        cancelled = list(self._open_orders)
        self._open_orders = []
        return cancelled

    def close_all_positions(self):
        self.close_calls += 1
        closed = list(self._positions)
        self._positions = []
        return closed

    def open_orders(self):
        return list(self._open_orders)

    def positions(self):
        return list(self._positions)


def make_eod_lifecycle(tmp_path, broker, internal_positions_open=None):
    cfg = PivConfig(key_id="k", secret_key="s", paper_trading=True, real_capital=False,
                     broker_endpoint=PAPER_ENDPOINT, approved_sha="abc", state_dir=tmp_path)
    bus = EventBus(tmp_path / "events.jsonl", feed_mode=cfg.feed_mode)
    life = PaperLifecycle(tmp_path / "lifecycle_state.json", broker, bus)
    life.start_session(True, True)
    for symbol in (internal_positions_open or []):
        life.state.positions[f"pos_{symbol}"] = {"symbol": symbol, "status": "OPEN"}
        life.state.open_position_by_symbol[symbol] = f"pos_{symbol}"
    return cfg, bus, life


def test_eod_retries_do_not_duplicate_cancel_close(tmp_path):
    broker = FakeBroker(open_orders=[{"id": "o1"}], positions=[])
    cfg, bus, life = make_eod_lifecycle(tmp_path, broker)
    first = run_eod_lifecycle(
        cfg, bus, life, live_session_id="sess-1", trading_date_et="2026-08-28",
        runtime_sha="sha1", config_hash="cfg1", trigger_reason="SCHEDULED",
    )
    assert first["status"] == STATUS_PASSED
    assert broker.cancel_calls == 1 and broker.close_calls == 1

    second = run_eod_lifecycle(
        cfg, bus, life, live_session_id="sess-1", trading_date_et="2026-08-28",
        runtime_sha="sha1", config_hash="cfg1", trigger_reason="MANUAL_CLI_INVOCATION",
    )
    assert second["status"] == STATUS_PASSED
    # Retry must NOT re-issue cancel/close (idempotent) -- only reconcile()
    # (a safe, read-only broker query) may repeat.
    assert broker.cancel_calls == 1 and broker.close_calls == 1


def test_original_session_id_remains_attached_across_retry(tmp_path):
    broker = FakeBroker()
    cfg, bus, life = make_eod_lifecycle(tmp_path, broker)
    first = run_eod_lifecycle(
        cfg, bus, life, live_session_id="sess-original", trading_date_et="2026-08-28",
        runtime_sha="sha1", config_hash="cfg1", trigger_reason="SCHEDULED",
    )
    second = run_eod_lifecycle(
        cfg, bus, life, live_session_id="sess-original", trading_date_et="2026-08-28",
        runtime_sha="sha1", config_hash="cfg1", trigger_reason="MANUAL_CLI_INVOCATION",
    )
    assert first["session_id"] == "sess-original"
    assert second["session_id"] == "sess-original"
    events_text = bus.path.read_text(encoding="utf-8")
    assert events_text.count('"session_id": "sess-original"') >= 2


def test_reconciliation_mismatch_prevents_successful_terminal_verdict(tmp_path):
    """Broker still reports an open (zombie) position even after cancel/
    close was requested -- must resolve FAILED, never PASSED, and
    SESSION_COMPLETED must never fire."""
    class StuckPositionBroker(FakeBroker):
        def close_all_positions(self):
            # Reports a successful close request, but the position
            # stubbornly remains visible on the next reconcile() query --
            # simulates a broker-side reconciliation mismatch, not a
            # cancel/close call failure (that is the separate INCONCLUSIVE
            # case covered by test_broker_failure_during_cancel_... below).
            self.close_calls += 1
            return list(self._positions)

    broker = StuckPositionBroker(open_orders=[], positions=[{"symbol": "AAPL"}])
    cfg, bus, life = make_eod_lifecycle(tmp_path, broker)
    result = run_eod_lifecycle(
        cfg, bus, life, live_session_id="sess-2", trading_date_et="2026-08-28",
        runtime_sha="sha1", config_hash="cfg1", trigger_reason="SCHEDULED",
    )
    assert result["status"] == STATUS_FAILED
    assert result["exit_code"] != 0
    assert '"event": "SESSION_COMPLETED"' not in bus.path.read_text(encoding="utf-8")


def test_broker_failure_during_cancel_resolves_inconclusive_not_passed(tmp_path):
    class RaisingBroker(FakeBroker):
        def cancel_all_orders(self):
            self.cancel_calls += 1
            raise RuntimeError("simulated broker outage")

    broker = RaisingBroker(open_orders=[{"id": "o1"}])
    cfg, bus, life = make_eod_lifecycle(tmp_path, broker)
    result = run_eod_lifecycle(
        cfg, bus, life, live_session_id="sess-3", trading_date_et="2026-08-28",
        runtime_sha="sha1", config_hash="cfg1", trigger_reason="SCHEDULED",
    )
    assert result["status"] == STATUS_INCONCLUSIVE
    assert '"event": "SESSION_COMPLETED"' not in bus.path.read_text(encoding="utf-8")
