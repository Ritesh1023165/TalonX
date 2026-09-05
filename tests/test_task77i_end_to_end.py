"""Task 77I Stage 4 -- accelerated end-to-end scenarios, driving the ACTUAL
runtime integration (SessionRunner + the real DecisionEngine, wired to the
real decision_contract, decision_ledger, notification_outbox, shadow_ledger,
and lifecycle.PaperLifecycle) with a fake clock, deterministic synthetic
bars, and fake services throughout. TEST_FIXTURE_ONLY -- NOT ALPHA EVIDENCE.
No test in this file starts a real application service or makes any real
network call (see the autouse `_no_real_network` guard below).

Only QuantScanner's own internal gating is mocked out (its
_handle_market_tick/_flush_throttle_window) -- same posture as
test_task65b_decision_engine.py, whose own docstring explains why:
QuantScanner's gating is tested elsewhere (test_quant_consumer.py); this
file, like that one, tests whether a signal DecisionEngine is told about
correctly flows through decide() -> ledgers -> (maybe) the broker."""
from __future__ import annotations

import csv
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import AsyncMock
from zoneinfo import ZoneInfo

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
from talonx_piv.observability import build_integrated_projection
from talonx_piv.session_identity import build_session_identity
from talonx_piv.session_runner import SessionRunner
from talonx_piv.shadow_ledger import ShadowLedger
from talonx_quant.schemas import QuantSignal, SignalDirection, SignalType

ET = ZoneInfo("America/New_York")
SESSION_DATE = date(2026, 8, 27)

_SCENARIO_RESULTS: list[dict] = []


@pytest.fixture(scope="module", autouse=True)
def _write_scenarios_csv_after_module():
    yield
    _write_scenarios_csv()


@pytest.fixture(autouse=True)
def _no_real_network(monkeypatch):
    import requests

    def _blocked(*args, **kwargs):
        raise AssertionError("test_task77i_end_to_end: a real network call was attempted")

    monkeypatch.setattr(requests, "request", _blocked, raising=True)
    monkeypatch.setattr(requests.sessions.Session, "request", _blocked, raising=True)


class Response:
    def __init__(self, body, status=200): self.body, self.status_code = body, status
    def json(self): return self.body
    def raise_for_status(self):
        if self.status_code >= 400: raise RuntimeError(f"HTTP {self.status_code}")


class FullTransport:
    """TEST_FIXTURE_ONLY -- NOT ALPHA EVIDENCE. Combined bars-fetch +
    order-lifecycle fake transport, isolated per test (tmp_path-scoped
    caller-owned instance), never touches a real socket."""

    def __init__(self, bar_batches: list[dict] | None = None):
        self.bar_batches = list(bar_batches or [])
        self.orders: list[dict] = []
        self.fail_next_bars_fetch = False
        # Task 79E-R2-2: the fill-time causality gate needs a `filled_at`
        # consistent with whatever timeline THIS test is using for its own
        # bars -- real wall-clock `datetime.now()` is the sane default
        # (matches most tests' own bar() helper), but a test driving a
        # FIXED/historical bar timeline (e.g. entry_ts = datetime(2026, 8,
        # 27, ...)) must set this explicitly before triggering an entry,
        # or its own later, still-historical bars would appear to be
        # BEFORE a real-wall-clock fill and never become causally eligible.
        self.next_fill_at: str | None = None

    def get(self, url, **kwargs):
        if url.endswith("/v2/account"):
            return Response({"id": "id", "account_number": "PA1", "status": "ACTIVE"}, 200)
        if url.endswith("/v2/orders"):
            return Response([o for o in self.orders if o.get("status") not in ("filled", "rejected", "canceled")])
        if "/v2/orders/" in url:
            order_id = url.rsplit("/", 1)[-1]
            match = next((o for o in self.orders if o["id"] == order_id), None)
            return Response(match or {}, 200 if match else 404)
        if url.endswith("/v2/positions"):
            return Response([])
        if "bars/latest" in url:
            if self.fail_next_bars_fetch:
                self.fail_next_bars_fetch = False
                return Response({}, 500)
            body = self.bar_batches.pop(0) if self.bar_batches else {}
            return Response({"bars": body})
        return Response({}, 404)

    def post(self, url, **kwargs):
        order = {"id": f"order-{len(self.orders) + 1}", "status": "filled", "filled_qty": "1",
                 "filled_avg_price": "100.0", "filled_at": self.next_fill_at or datetime.now(timezone.utc).isoformat(),
                 **kwargs.get("json", {})}
        self.orders.append(order)
        return Response(order)

    def delete(self, url, **kwargs):
        return Response([])


class FakePubSub:
    def __init__(self):
        self._messages: list[bytes] = []

    async def subscribe(self, channel): pass
    async def unsubscribe(self, channel): pass
    async def close(self): pass

    async def get_message(self, ignore_subscribe_messages=True, timeout=0.2):
        if self._messages:
            return {"data": self._messages.pop(0)}
        return None


class FakeRedisClient:
    def __init__(self):
        self._pubsub = FakePubSub()

    def pubsub(self):
        return self._pubsub


def bar_row(ts: str, price: float = 100.0, low=None, high=None) -> dict:
    return {"t": ts, "o": price, "h": high if high is not None else price + 1,
            "l": low if low is not None else price - 1, "c": price, "v": 1000}


def to_utc_iso(local: datetime) -> str:
    return local.astimezone(ZoneInfo("UTC")).isoformat().replace("+00:00", "Z")


def make_signal(direction=SignalDirection.BULLISH, ticker="AAPL", price=100.0, stop=98.0, target=104.0, ts=None) -> QuantSignal:
    return QuantSignal(
        ticker=ticker, signal_type=SignalType.MACD_BULLISH_CROSS, direction=direction,
        message="TEST_FIXTURE_ONLY -- NOT ALPHA EVIDENCE", price=price, stop_price=stop, target_price=target,
        bar_timestamp=ts or datetime.now(timezone.utc),
    )


def build_stack(tmp_path, *, universe=("AAPL",), paper_enabled=(), approval_override=None, bar_batches=None):
    cfg = PivConfig(
        key_id="key", secret_key="secret", paper_trading=True, real_capital=False,
        broker_endpoint=PAPER_ENDPOINT, approved_sha="abc", state_dir=tmp_path,
        universe=universe, stale_seconds=90,
    )
    transport = FullTransport(bar_batches)
    broker = AlpacaPaperClient(cfg, transport)
    broker.verify_paper_identity()
    identity = build_session_identity(cfg)
    bus = EventBus(tmp_path / "piv_events.jsonl", feed_mode=cfg.feed_mode, session_id=identity.session_id)
    life = PaperLifecycle(tmp_path / "lifecycle_state.json", broker, bus, PaperEntrySettings.for_test(*paper_enabled))
    life.start_session(True, True)
    decision_ledger = DecisionLedger(tmp_path / "decision_ledger.json")
    outbox = NotificationOutbox(tmp_path / "notification_outbox.json", lambda msg: True)
    shadow = ShadowLedger(tmp_path / "shadow_ledger.json")
    (tmp_path / "session_identity.json").write_text(
        __import__("json").dumps(identity.to_dict(), sort_keys=True), encoding="utf-8",
    )
    engine = DecisionEngine(
        FakeRedisClient(), bus, life, piv_config=cfg,
        decision_ledger=decision_ledger, notification_outbox=outbox, shadow_ledger=shadow,
        runtime_sha=identity.runtime_sha, config_hash=identity.config_hash,
        strategy_approval_status_override=approval_override,
    )
    engine.scanner._handle_market_tick = AsyncMock()
    engine.scanner._flush_throttle_window = AsyncMock()
    engine.warmup_ready_symbols = set(universe)  # skip warmup for this test's purposes
    runner = SessionRunner(cfg, bus, life, transport, decision_engine=engine, poll_interval_seconds=60.0)
    return dict(cfg=cfg, transport=transport, broker=broker, bus=bus, life=life, engine=engine,
                decision_ledger=decision_ledger, outbox=outbox, shadow=shadow, runner=runner, identity=identity)


async def _tick(runner, when: datetime) -> None:
    await runner.process_tick(when.astimezone(ZoneInfo("UTC")))


def _record(scenario: str, result: str, note: str = "") -> None:
    _SCENARIO_RESULTS.append({"scenario": scenario, "result": result, "note": note})


def _write_scenarios_csv():
    # Task 81 §6 (E3): never overwrite the historical evidence directory
    # during a routine test run. Default to a run-specific temp location;
    # an operator can opt in to a real evidence dir via TALONX_TEST_EVIDENCE_DIR.
    import os
    import tempfile
    base = Path(os.environ.get("TALONX_TEST_EVIDENCE_DIR", tempfile.gettempdir()))
    path = base / "task77i_integrated_application" / "end_to_end_scenarios.csv"
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=["scenario", "result", "note"])
        writer.writeheader()
        for row in _SCENARIO_RESULTS:
            writer.writerow(row)


# ---------------------------------------------------------------------------
# 1. Approved test setup -> decision -> alert -> shadow, PAPER disabled
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_01_approved_decision_alert_shadow_paper_disabled(tmp_path):
    stack = build_stack(tmp_path, paper_enabled=(), approval_override=StrategyApprovalStatus.APPROVED)
    ts = datetime(2026, 8, 27, 10, 5, tzinfo=ET)
    stack["engine"]._pubsub._messages.append(make_signal(ts=ts).model_dump_json().encode())
    bar = {"AAPL": bar_row(to_utc_iso(ts), 100.0)}
    stack["engine"].warmup_ready_symbols = {"AAPL"}
    await stack["engine"].on_bars({"AAPL": __import__("talonx_piv.session_runner", fromlist=["Bar"]).Bar(ts.astimezone(timezone.utc), 100.0, 101.0, 99.0, 100.0, 1000)})
    assert stack["transport"].orders == []  # PAPER disabled -- no broker mutation
    assert len(stack["outbox"].records) == 1
    assert len(stack["shadow"].positions) == 1
    _record("01_approved_paper_disabled", "PASSED", "decision+alert+shadow created, zero broker orders")


# ---------------------------------------------------------------------------
# 2. Same setup, PAPER enabled -> linked but separate fake-PAPER lifecycle
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_02_approved_decision_paper_enabled_linked_but_separate(tmp_path):
    from talonx_piv.session_runner import Bar
    stack = build_stack(tmp_path, paper_enabled=("AAPL",), approval_override=StrategyApprovalStatus.APPROVED)
    ts = datetime(2026, 8, 27, 10, 5, tzinfo=ET)
    stack["engine"]._pubsub._messages.append(make_signal(ts=ts).model_dump_json().encode())
    stack["engine"].warmup_ready_symbols = {"AAPL"}
    await stack["engine"].on_bars({"AAPL": Bar(ts.astimezone(timezone.utc), 100.0, 101.0, 99.0, 100.0, 1000)})
    assert stack["transport"].orders and stack["transport"].orders[0]["side"] == "buy"
    decision_id = next(iter(stack["decision_ledger"].records.values()))["decision_id"]
    shadow_record = stack["shadow"].get_by_decision(decision_id)
    assert shadow_record is not None  # linked via decision_id
    assert stack["life"]._open_position_for("AAPL") is not None  # real PAPER position
    # separate: shadow's own simulated fill need not equal the real fill (different bars can drive them)
    assert "simulated_entry_price_raw" in shadow_record
    _record("02_approved_paper_enabled_linked", "PASSED", "real PAPER position + linked shadow, both present, distinct records")


# ---------------------------------------------------------------------------
# 3. Unvalidated real-strategy configuration -> no actionable entry
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_03_unvalidated_strategy_no_actionable_entry(tmp_path):
    from talonx_piv.session_runner import Bar
    stack = build_stack(tmp_path, paper_enabled=("AAPL",), approval_override=None)  # production default
    ts = datetime(2026, 8, 27, 10, 5, tzinfo=ET)
    stack["engine"]._pubsub._messages.append(make_signal(ts=ts).model_dump_json().encode())
    stack["engine"].warmup_ready_symbols = {"AAPL"}
    await stack["engine"].on_bars({"AAPL": Bar(ts.astimezone(timezone.utc), 100.0, 101.0, 99.0, 100.0, 1000)})
    assert stack["transport"].orders == []
    assert len(stack["shadow"].positions) == 0  # shadow also gated on the same actionability bar
    _record("03_unvalidated_no_entry", "PASSED", "zero broker orders, zero shadow positions")


# ---------------------------------------------------------------------------
# 4. Bearish while flat -> no short
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_04_bearish_while_flat_no_short(tmp_path):
    from talonx_piv.session_runner import Bar
    stack = build_stack(tmp_path, paper_enabled=("AAPL",), approval_override=StrategyApprovalStatus.APPROVED)
    ts = datetime(2026, 8, 27, 10, 5, tzinfo=ET)
    stack["engine"]._pubsub._messages.append(make_signal(SignalDirection.BEARISH, ts=ts).model_dump_json().encode())
    stack["engine"].warmup_ready_symbols = {"AAPL"}
    await stack["engine"].on_bars({"AAPL": Bar(ts.astimezone(timezone.utc), 100.0, 101.0, 99.0, 100.0, 1000)})
    assert stack["transport"].orders == []
    _record("04_bearish_flat_no_short", "PASSED", "zero broker orders")


# ---------------------------------------------------------------------------
# 5. Existing long plus authorised exit
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_05_existing_long_plus_authorised_exit(tmp_path):
    from talonx_piv.session_runner import Bar
    stack = build_stack(tmp_path, paper_enabled=("AAPL",), approval_override=StrategyApprovalStatus.APPROVED)
    entry_ts = datetime(2026, 8, 27, 10, 5, tzinfo=ET)
    # Task 79E-R2-2: this test drives a FIXED, historical bar timeline --
    # the fill must be timestamped consistently with it (a controlled
    # timestamp, not real wall-clock "now") for the fill-time causality
    # gate to ever treat the later, still-historical exit bar as eligible.
    stack["transport"].next_fill_at = entry_ts.astimezone(timezone.utc).isoformat()
    stack["engine"]._pubsub._messages.append(make_signal(ts=entry_ts, stop=98.0, target=104.0).model_dump_json().encode())
    stack["engine"].warmup_ready_symbols = {"AAPL"}
    await stack["engine"].on_bars({"AAPL": Bar(entry_ts.astimezone(timezone.utc), 100.0, 100.5, 99.5, 100.0, 1000)})
    assert "AAPL" in stack["engine"].positions
    exit_ts = entry_ts + timedelta(minutes=1)
    await stack["engine"].on_bars({"AAPL": Bar(exit_ts.astimezone(timezone.utc), 99.0, 99.5, 97.0, 98.0, 1000)})  # stop hit
    assert "AAPL" not in stack["engine"].positions
    assert stack["transport"].orders[-1]["side"] == "sell"
    _record("05_long_authorised_exit", "PASSED", "sell reaches broker on stop hit")


# ---------------------------------------------------------------------------
# 6. Partial fills and concurrent exit requests
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_06_partial_fills_and_concurrent_exit_requests(tmp_path):
    stack = build_stack(tmp_path, paper_enabled=("AAPL",))
    life = stack["life"]
    entry = life.order_intent("s1", "AAPL", "buy", 3)
    life.apply_broker_update(entry["id"], "filled", 3, 100.0)
    exit1 = life.order_intent("exit1", "AAPL", "sell", 2)
    life.apply_broker_update(exit1["id"], "partially_filled", 1, 101.0)
    from talonx_piv.broker import PaperGuardError
    with pytest.raises(PaperGuardError, match="OVERSIZED_OR_DUPLICATE_SELL"):
        life.order_intent("exit2", "AAPL", "sell", 3)  # concurrent, competing exit for more than truly available
    assert life._open_position_for("AAPL")["remaining_quantity"] == 2
    _record("06_partial_fill_concurrent_exit", "PASSED", "competing oversized exit correctly rejected; remaining_quantity correct")


# ---------------------------------------------------------------------------
# 7. Notification outage
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_07_notification_outage(tmp_path):
    from talonx_piv.session_runner import Bar
    stack = build_stack(tmp_path, paper_enabled=("AAPL",), approval_override=StrategyApprovalStatus.APPROVED)
    stack["outbox"].send = lambda msg: (_ for _ in ()).throw(RuntimeError("simulated Telegram outage"))
    ts = datetime(2026, 8, 27, 10, 5, tzinfo=ET)
    stack["engine"]._pubsub._messages.append(make_signal(ts=ts).model_dump_json().encode())
    stack["engine"].warmup_ready_symbols = {"AAPL"}
    await stack["engine"].on_bars({"AAPL": Bar(ts.astimezone(timezone.utc), 100.0, 101.0, 99.0, 100.0, 1000)})
    assert stack["transport"].orders and stack["transport"].orders[0]["side"] == "buy"  # unaffected
    assert len(stack["shadow"].positions) == 1  # unaffected
    stack["outbox"].dispatch_pending()  # independent step -- must not raise
    assert next(iter(stack["outbox"].records.values()))["status"] == "UNCERTAIN"
    _record("07_notification_outage", "PASSED", "broker entry + shadow unaffected; outbox records UNCERTAIN honestly")


# ---------------------------------------------------------------------------
# 8. Broker outage / uncertain submission
# ---------------------------------------------------------------------------

class _StuckOnceTransport(FullTransport):
    """TEST_FIXTURE_ONLY -- NOT ALPHA EVIDENCE. Every order accepted but
    never progresses past 'accepted' until the test manually flips it --
    simulates a broker outage where the true outcome is unknown for a
    while."""

    def post(self, url, **kwargs):
        order = {"id": f"order-{len(self.orders) + 1}", "status": "accepted", "filled_qty": "0", **kwargs.get("json", {})}
        self.orders.append(order)
        return Response(order)


@pytest.mark.asyncio
async def test_08_broker_outage_uncertain_submission(tmp_path):
    stack = build_stack(tmp_path, paper_enabled=("AAPL",))
    stack["transport"].__class__ = _StuckOnceTransport  # swap behavior in place, same instance
    life = stack["life"]
    entry = life.order_intent("s1", "AAPL", "buy", 1)
    life.poll_order_until_terminal(entry["id"], timeout_seconds=0, poll_interval_seconds=1.0, sleep=lambda s: None)
    assert life.state.orders[entry["id"]]["status"] == "UNCONFIRMED_TIMEOUT"
    from talonx_piv.broker import PaperGuardError
    with pytest.raises(PaperGuardError, match="PENDING_ENTRY_EXISTS"):
        life.order_intent("s2", "AAPL", "buy", 1)  # fail-closed while uncertain
    for order in stack["transport"].orders:
        if order["id"] == entry["id"]:
            order.update(status="filled", filled_qty="1", filled_avg_price="100.0")
    life.reconcile()
    assert life.state.orders[entry["id"]]["status"] == "filled"
    _record("08_broker_outage_uncertain", "PASSED", "uncertain order fails closed then resolves via reconcile()")


# ---------------------------------------------------------------------------
# 9. Sparse / missing data
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_09_sparse_missing_data(tmp_path):
    stack = build_stack(tmp_path, universe=("AAPL", "MSFT"), bar_batches=[{"AAPL": bar_row(to_utc_iso(datetime(2026, 8, 27, 9, 30, tzinfo=ET)))}])
    tick = datetime(2026, 8, 27, 9, 30, tzinfo=ET)
    await _tick(stack["runner"], tick)
    assert "MSFT" not in stack["runner"]._last_bar_ts  # never synthesized
    assert "AAPL" in stack["runner"]._last_bar_ts
    _record("09_sparse_missing_data", "PASSED", "missing symbol never synthesized")


# ---------------------------------------------------------------------------
# 10. Restart with pending notification/shadow/execution work
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_10_restart_with_pending_work(tmp_path):
    from talonx_piv.decision_contract import DataReadiness, MarketView, decide
    stack = build_stack(tmp_path, paper_enabled=("AAPL",))
    decision = decide(
        decision_id="fixed", session_id=stack["identity"].session_id, trading_date_et="2026-08-27", ticker="AAPL",
        market_view=MarketView.BULLISH, has_open_long=False, approved_exit_condition=False,
        strategy_approval_status=StrategyApprovalStatus.APPROVED, data_readiness=DataReadiness.READY,
        paper_entry_enabled=True,
    )
    stack["decision_ledger"].record(decision, event_id="fixed", evidence_category="natural")
    stack["outbox"].enqueue(decision)
    stack["shadow"].consider_entry(decision, source="STRATEGY")

    # restart -- fresh ledger instances, same files
    ledger2 = DecisionLedger(tmp_path / "decision_ledger.json")
    outbox2 = NotificationOutbox(tmp_path / "notification_outbox.json", lambda m: True)
    shadow2 = ShadowLedger(tmp_path / "shadow_ledger.json")
    assert len(ledger2.records) == 1
    assert len(outbox2.records) == 1
    assert len(shadow2.positions) == 1
    outbox2.dispatch_pending()  # pending work resumes correctly after restart
    assert next(iter(outbox2.records.values()))["status"] == "SENT"
    _record("10_restart_pending_work", "PASSED", "all three ledgers correctly resumed post-restart, no duplication")


# ---------------------------------------------------------------------------
# 11. EOD reconciliation and original session identity
# ---------------------------------------------------------------------------

def test_11_eod_reconciliation_and_session_identity(tmp_path):
    from talonx_piv.eod_lifecycle import run_eod_lifecycle
    stack = build_stack(tmp_path, paper_enabled=("AAPL",))
    outcome = run_eod_lifecycle(
        stack["cfg"], stack["bus"], stack["life"], live_session_id=stack["identity"].session_id,
        trading_date_et="2026-08-27", runtime_sha=stack["identity"].runtime_sha,
        config_hash=stack["identity"].config_hash, trigger_reason="TEST_FIXTURE_ONLY",
    )
    assert outcome["session_id"] == stack["identity"].session_id  # original identity preserved, not a new one
    assert outcome["status"] == "PASSED"
    _record("11_eod_session_identity", "PASSED", f"status={outcome['status']}, session_id preserved")


# ---------------------------------------------------------------------------
# 12. Dashboard/report counters match the underlying ledgers
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_12_dashboard_counters_match_ledgers(tmp_path):
    from talonx_piv.session_runner import Bar
    stack = build_stack(tmp_path, paper_enabled=(), approval_override=StrategyApprovalStatus.APPROVED)
    ts = datetime(2026, 8, 27, 10, 5, tzinfo=ET)
    stack["engine"]._pubsub._messages.append(make_signal(ts=ts).model_dump_json().encode())
    stack["engine"].warmup_ready_symbols = {"AAPL"}
    await stack["engine"].on_bars({"AAPL": Bar(ts.astimezone(timezone.utc), 100.0, 101.0, 99.0, 100.0, 1000)})
    projection = build_integrated_projection(tmp_path, session_id=stack["identity"].session_id, trading_date_et="2026-08-27")
    assert projection["decisions"]["total"] == len(stack["decision_ledger"].records)
    assert projection["notifications"]["total"] == len(stack["outbox"].records)
    assert projection["shadow"]["total"] == len(stack["shadow"].positions)
    _record("12_dashboard_counters_match", "PASSED", "projection counts reconcile exactly to underlying ledger sizes")
    _write_scenarios_csv()
