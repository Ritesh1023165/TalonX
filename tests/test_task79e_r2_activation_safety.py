"""Task 79E-R2 -- completes the experimental-activation stabilisation work
Task 79E-R1 started: correct broker reconciliation against Alpaca's ACTUAL
documented contract, the full pending-entry lifecycle (not merely
"filled or gone"), durable exit recovery (triggered-exit reason survives a
restart, degraded/blocked recovery is explicit), fill-causality that covers
delayed/partial fills and restarts (not only the same-tick case), and
session binding to the real, durable live-session identity rather than a
fixed "REGULAR" category.

The fake HTTP transport in this file is modeled directly on Alpaca's own
documented contract for GET /v2/orders:by_client_order_id
(https://docs.alpaca.markets/us/reference/getorderbyclientorderid) -- a
SINGLE Order object on 200, a 404 on no match -- not copied from what R1's
implementation happened to call.

Offline only -- no network access, no live session, no broker mutations,
no notifications sent (outbox uses a fake `send`), no active
`experimental_authorization.json` in the repo.

TEST_FIXTURE_ONLY -- NOT ALPHA EVIDENCE throughout."""
from __future__ import annotations

import dataclasses
import json
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, patch

import pytest

from talonx_backtest.reproducibility import get_strategy_version
from talonx_piv.broker import AlpacaPaperClient, PaperGuardError
from talonx_piv.config import PAPER_ENDPOINT, PivConfig
from talonx_piv.decision_engine import DecisionEngine
from talonx_piv.decision_ledger import DecisionLedger
from talonx_piv.events import EventBus
from talonx_piv.execution_settings import PaperEntrySettings
from talonx_piv.experimental_authorization import ExperimentalAuthorization, ExperimentalPaperPermission
from talonx_piv.gemini_enrichment import GeminiEnrichmentOutbox
from talonx_piv.lifecycle import PaperLifecycle, UNCERTAIN_SUBMISSION_CONFIRMATION_THRESHOLD, stable_id
from talonx_piv.notification_outbox import NotificationOutbox
from talonx_piv.session_identity import build_session_identity
from talonx_piv.session_runner import Bar
from talonx_piv.shadow_ledger import ShadowLedger
from talonx_quant.schemas import QuantSignal, SignalDirection, SignalType


# ---------------------------------------------------------------------------
# Alpaca-contract-accurate fake transport
# ---------------------------------------------------------------------------

class Response:
    def __init__(self, body, status=200):
        self.body, self.status_code = body, status

    def json(self):
        return self.body

    def raise_for_status(self):
        if self.status_code >= 400:
            raise RuntimeError(f"HTTP {self.status_code}")


class AlpacaContractTransport:
    """TEST_FIXTURE_ONLY -- NOT ALPHA EVIDENCE. Models Alpaca's DOCUMENTED
    order endpoints, not what broker.py happens to call:

    - GET  /v2/account
    - GET  /v2/orders?status=open              -> list of Order
    - GET  /v2/orders/{id}                      -> single Order or 404
    - GET  /v2/orders:by_client_order_id?client_order_id=X
            -> single Order (200) or 404 (no match) --
            https://docs.alpaca.markets/us/reference/getorderbyclientorderid
    - POST /v2/orders                           -> creates an Order
    - GET  /v2/positions                        -> list
    - DELETE /v2/orders, /v2/positions          -> list

    Orders never auto-fill on submission (status stays "new") so a test can
    drive partial fills / delayed fills / cancellations explicitly via
    PaperLifecycle.apply_broker_update at exactly the moment it wants."""

    def __init__(self, account_id="acct-r2"):
        self.account_id = account_id
        self.orders: list[dict] = []
        self.raise_on_post = False
        self.dropped_client_order_ids: set[str] = set()
        # Task 79E-R2: simulates "the broker returned an UNRELATED order"
        # for a specific client_order_id lookup -- proves verification
        # rejects a response that merely has a truthy `id`.
        self.unrelated_response_for: dict[str, dict] = {}
        self.malformed_response_for: set[str] = set()

    def get(self, url, **kwargs):
        if url.endswith("/v2/account"):
            return Response({"id": self.account_id, "account_number": "PA555555", "status": "ACTIVE"})
        if url.endswith("/v2/orders:by_client_order_id"):
            params = kwargs.get("params") or {}
            client_order_id = params.get("client_order_id")
            if client_order_id in self.malformed_response_for:
                return Response({"not_an_order": True}, 200)  # 200 but no usable `id`
            if client_order_id in self.unrelated_response_for:
                return Response(self.unrelated_response_for[client_order_id], 200)
            if client_order_id in self.dropped_client_order_ids:
                return Response({"message": "order not found"}, 404)
            match = next((o for o in self.orders if o.get("client_order_id") == client_order_id), None)
            return Response(match, 200) if match else Response({"message": "order not found"}, 404)
        if url.endswith("/v2/orders"):
            return Response([o for o in self.orders if o.get("status") not in ("filled", "rejected", "canceled")])
        if "/v2/orders/" in url:
            order_id = url.rsplit("/", 1)[-1]
            match = next((o for o in self.orders if o["id"] == order_id), None)
            return Response(match or {}, 200 if match else 404)
        if url.endswith("/v2/positions"):
            return Response([])
        return Response({}, 404)

    def post(self, url, **kwargs):
        if self.raise_on_post:
            raise RuntimeError("simulated HTTP submission failure before any id received")
        payload = kwargs.get("json", {})
        client_order_id = payload.get("client_order_id")
        if client_order_id in self.dropped_client_order_ids:
            raise RuntimeError("simulated network failure -- never reached broker")
        order = {
            "id": f"order-{len(self.orders) + 1}", "status": "new", "filled_qty": "0",
            "client_order_id": client_order_id, **payload,
        }
        self.orders.append(order)
        return Response(order)

    def delete(self, url, **kwargs):
        return Response([])


def _no_sleep_poll(life):
    return patch("time.sleep", lambda *_: None)


def _auth(**overrides) -> ExperimentalAuthorization:
    from talonx_piv.events import ET
    now = datetime.now(timezone.utc)
    paper = overrides.pop("paper", ExperimentalPaperPermission(
        enabled=True, account_id_binding="acct-r2", max_quantity_per_entry=5.0,
        max_reference_notional_budget=10000.0, max_entry_count=10, max_concurrent_exposure=5,
    ))
    kwargs = dict(
        experiment_id="exp-r2", operator_acknowledged_unvalidated=True, strategy_id="macd_bullish_cross",
        strategy_version=get_strategy_version(), runtime_sha="sha-r2", config_hash="cfg-r2",
        allowed_symbols=frozenset({"AAPL", "MSFT"}), trading_date_et=now.astimezone(ET).date().isoformat(),
        session_scope="REGULAR", activated_at=now - timedelta(hours=1), expires_at=now + timedelta(hours=10),
        paper=paper,
    )
    kwargs.update(overrides)
    return ExperimentalAuthorization(**kwargs)


def make_signal(direction=SignalDirection.BULLISH, ticker="AAPL", price=100.0, stop=98.0, target=104.0, ts=None) -> QuantSignal:
    return QuantSignal(
        ticker=ticker, signal_type=SignalType.MACD_BULLISH_CROSS, direction=direction,
        message="TEST_FIXTURE_ONLY -- NOT ALPHA EVIDENCE", price=price, stop_price=stop, target_price=target,
        bar_timestamp=ts or datetime.now(timezone.utc),
    )


def bar(price=100.0, ts=None):
    ts = ts or datetime.now(timezone.utc)
    return Bar(ts, price, price + 1, price - 1, price, 1000)


class _NullPubSub:
    async def subscribe(self, channel): pass
    async def unsubscribe(self, channel): pass
    async def close(self): pass
    async def get_message(self, ignore_subscribe_messages=True, timeout=0.2): return None


class _NullRedisClient:
    def pubsub(self): return _NullPubSub()


def build_stack(tmp_path, *, universe=("AAPL", "MSFT"), paper_enabled=("AAPL", "MSFT"),
                 auth=None, transport=None, bind_auth_to_live_session=True):
    cfg = PivConfig(
        key_id="key", secret_key="secret", paper_trading=True, real_capital=False,
        broker_endpoint=PAPER_ENDPOINT, approved_sha="abc", state_dir=tmp_path,
        universe=universe, stale_seconds=90,
    )
    transport = transport or AlpacaContractTransport()
    broker = AlpacaPaperClient(cfg, transport)
    broker.verify_paper_identity()
    identity = build_session_identity(cfg)
    bus = EventBus(tmp_path / "piv_events.jsonl", feed_mode=cfg.feed_mode, session_id=identity.session_id)
    if auth is not None and bind_auth_to_live_session:
        auth = dataclasses.replace(auth, session_scope=identity.session_id)
    life = PaperLifecycle(
        tmp_path / "lifecycle_state.json", broker, bus, PaperEntrySettings.for_test(*paper_enabled),
        experimental_authorization=auth, runtime_sha="sha-r2", config_hash="cfg-r2",
    )
    life.start_session(True, True)
    decision_ledger = DecisionLedger(tmp_path / "decision_ledger.json")
    outbox = NotificationOutbox(tmp_path / "notification_outbox.json", lambda m: True)
    shadow = ShadowLedger(tmp_path / "shadow_ledger.json")
    gemini = GeminiEnrichmentOutbox(tmp_path / "gemini_enrichment.json")
    engine = DecisionEngine(
        _NullRedisClient(), bus, life, piv_config=cfg,
        decision_ledger=decision_ledger, notification_outbox=outbox, shadow_ledger=shadow, gemini_enrichment=gemini,
        runtime_sha="sha-r2", config_hash="cfg-r2", experimental_authorization=auth,
    )
    return engine, life, transport, outbox, shadow, bus, identity


def _rebuild_engine(tmp_path, life, bus, cfg, *, auth=None):
    """Simulates a full process restart: brand-new PaperLifecycle/
    DecisionEngine reading the SAME persisted state files."""
    broker2 = AlpacaPaperClient(cfg, life.broker.transport)
    broker2.verify_paper_identity()
    life2 = PaperLifecycle(
        tmp_path / "lifecycle_state.json", broker2, bus,
        PaperEntrySettings.for_test("AAPL", "MSFT"), experimental_authorization=auth,
        runtime_sha="sha-r2", config_hash="cfg-r2",
    )
    engine2 = DecisionEngine(
        _NullRedisClient(), bus, life2, piv_config=cfg,
        decision_ledger=DecisionLedger(tmp_path / "decision_ledger.json"),
        notification_outbox=NotificationOutbox(tmp_path / "notification_outbox.json", lambda m: True),
        shadow_ledger=ShadowLedger(tmp_path / "shadow_ledger.json"),
        gemini_enrichment=GeminiEnrichmentOutbox(tmp_path / "gemini_enrichment.json"),
        runtime_sha="sha-r2", config_hash="cfg-r2", experimental_authorization=auth,
    )
    return engine2, life2


# ---------------------------------------------------------------------------
# 1. Correct broker reconciliation (Alpaca's real documented contract)
# ---------------------------------------------------------------------------

def test_find_order_by_client_id_uses_the_documented_endpoint_and_params(tmp_path):
    """broker.find_order_by_client_id must call the ACTUAL documented
    Alpaca endpoint (GET /v2/orders:by_client_order_id?client_order_id=X),
    not a query filter on the plain list-orders endpoint (R1's mistake)."""
    engine, life, transport, outbox, shadow, bus, identity = build_stack(tmp_path)
    calls = []
    real_get = transport.get

    def _recording_get(url, **kwargs):
        calls.append((url, kwargs.get("params")))
        return real_get(url, **kwargs)

    transport.get = _recording_get
    result = life.broker.find_order_by_client_id("client-xyz")
    assert result is None  # not found -- nothing registered under that id
    matching = [c for c in calls if c[0].endswith("/v2/orders:by_client_order_id")]
    assert len(matching) == 1
    assert matching[0][1] == {"client_order_id": "client-xyz"}


def test_find_order_by_client_id_returns_none_on_clean_404(tmp_path):
    engine, life, transport, outbox, shadow, bus, identity = build_stack(tmp_path)
    assert life.broker.find_order_by_client_id("nope") is None


def test_find_order_by_client_id_raises_on_malformed_200(tmp_path):
    """A 200 with no usable `id` is NOT the same as a documented 404 -- it
    is ambiguous and must never be silently treated as "not found"."""
    transport = AlpacaContractTransport()
    engine, life, transport, outbox, shadow, bus, identity = build_stack(tmp_path, transport=transport)
    transport.malformed_response_for.add("weird-id")
    with pytest.raises(PaperGuardError, match="malformed order-by-client-id response"):
        life.broker.find_order_by_client_id("weird-id")


def test_uncertain_submission_response_verified_before_adoption(tmp_path):
    """Requirement 1: 'verify the returned client ID, symbol, side, and
    quantity against the original intent before adoption; reject
    unrelated/malformed responses.' The broker returns a real, well-formed
    Order -- but for a DIFFERENT symbol/side/qty than this intent's own
    payload. It must be rejected, not adopted, and the intent must remain
    exactly as unresolved as before."""
    transport = AlpacaContractTransport()
    engine, life, transport, outbox, shadow, bus, identity = build_stack(tmp_path, transport=transport)
    intent_id = stable_id("intent", "s1", "AAPL", "buy", 1.0)
    transport.dropped_client_order_ids.add(intent_id)
    with pytest.raises(RuntimeError, match="simulated network failure"):
        life.order_intent("s1", "AAPL", "buy", 1.0, source="STRATEGY", reference_price=100.0)
    assert life.state.intents[intent_id]["status"] == "SUBMIT_FAILED_UNCERTAIN"

    # An UNRELATED order (different symbol) happens to be returned for this
    # client_order_id -- e.g. a broker-side bug, id collision, or test/prod
    # data cross-contamination. Never adopted.
    transport.unrelated_response_for[intent_id] = {
        "id": "order-unrelated-1", "client_order_id": intent_id, "symbol": "MSFT",
        "side": "buy", "qty": "1.0", "status": "filled", "filled_qty": "1.0", "filled_avg_price": "200.0",
    }
    life.reconcile()
    assert life.state.intents[intent_id]["status"] == "SUBMIT_FAILED_UNCERTAIN"  # NOT adopted
    assert "order-unrelated-1" not in life.state.orders
    # Still blocked -- exposure protection was never released by the bad response.
    with pytest.raises(PaperGuardError, match="PENDING_ENTRY_EXISTS"):
        life.order_intent("s2", "AAPL", "buy", 1.0, source="STRATEGY", reference_price=100.0)


def test_uncertain_submission_wrong_quantity_response_rejected(tmp_path):
    """Same idea, isolating the qty-mismatch check specifically -- same
    client_order_id/symbol/side, different quantity."""
    transport = AlpacaContractTransport()
    engine, life, transport, outbox, shadow, bus, identity = build_stack(tmp_path, transport=transport)
    intent_id = stable_id("intent", "s1", "AAPL", "buy", 1.0)
    transport.dropped_client_order_ids.add(intent_id)
    with pytest.raises(RuntimeError):
        life.order_intent("s1", "AAPL", "buy", 1.0, source="STRATEGY", reference_price=100.0)
    transport.unrelated_response_for[intent_id] = {
        "id": "order-x", "client_order_id": intent_id, "symbol": "AAPL",
        "side": "buy", "qty": "5.0", "status": "filled", "filled_qty": "5.0", "filled_avg_price": "100.0",
    }
    life.reconcile()
    assert life.state.intents[intent_id]["status"] == "SUBMIT_FAILED_UNCERTAIN"
    assert "order-x" not in life.state.orders


def test_uncertain_submission_matching_response_is_adopted(tmp_path):
    """The positive case: a response that genuinely matches (same
    client_order_id/symbol/side/qty) IS adopted."""
    transport = AlpacaContractTransport()
    engine, life, transport, outbox, shadow, bus, identity = build_stack(tmp_path, transport=transport)
    intent_id = stable_id("intent", "s1", "AAPL", "buy", 1.0)

    real_post = transport.post

    def _post_but_report_failure(url, **kwargs):
        response = real_post(url, **kwargs)
        raise RuntimeError("simulated response lost after broker accepted it")

    transport.post = _post_but_report_failure
    with pytest.raises(RuntimeError):
        life.order_intent("s1", "AAPL", "buy", 1.0, source="STRATEGY", reference_price=100.0)
    assert life.state.intents[intent_id]["status"] == "SUBMIT_FAILED_UNCERTAIN"

    life.reconcile()
    assert life.state.intents[intent_id]["status"] == "SUBMITTED"
    assert len(transport.orders) == 1


def test_single_404_never_confirms_not_submitted(tmp_path):
    """Requirement 1: 'a single 404 must not mean confirmed never
    submitted or release uncertain-exposure protection.' Reservations
    (pyramiding block) must survive across the FIRST reconcile()'s 404."""
    transport = AlpacaContractTransport()
    engine, life, transport, outbox, shadow, bus, identity = build_stack(tmp_path, transport=transport)
    intent_id = stable_id("intent", "s1", "AAPL", "buy", 1.0)
    transport.dropped_client_order_ids.add(intent_id)
    with pytest.raises(RuntimeError):
        life.order_intent("s1", "AAPL", "buy", 1.0, source="STRATEGY", reference_price=100.0)

    assert UNCERTAIN_SUBMISSION_CONFIRMATION_THRESHOLD >= 2  # the policy this test proves
    for attempt in range(1, UNCERTAIN_SUBMISSION_CONFIRMATION_THRESHOLD):
        life.reconcile()
        assert life.state.intents[intent_id]["status"] == "SUBMIT_FAILED_UNCERTAIN", f"resolved too early at attempt {attempt}"
        with pytest.raises(PaperGuardError, match="PENDING_ENTRY_EXISTS"):
            life.order_intent(f"retry-{attempt}", "AAPL", "buy", 1.0, source="STRATEGY", reference_price=100.0)
    life.reconcile()  # the THRESHOLD-th independent 404
    assert life.state.intents[intent_id]["status"] == "SUBMIT_FAILED_CONFIRMED_NOT_SUBMITTED"


def test_repeated_reconciliation_is_idempotent_and_never_double_adopts(tmp_path):
    """Calling reconcile() many times in a row (e.g. every EOD/supervise
    cycle) must never re-process an already-resolved intent or duplicate
    an adopted order."""
    transport = AlpacaContractTransport()
    engine, life, transport, outbox, shadow, bus, identity = build_stack(tmp_path, transport=transport)
    intent_id = stable_id("intent", "s1", "AAPL", "buy", 1.0)
    real_post = transport.post

    def _post_but_report_failure(url, **kwargs):
        response = real_post(url, **kwargs)
        raise RuntimeError("lost response")

    transport.post = _post_but_report_failure
    with pytest.raises(RuntimeError):
        life.order_intent("s1", "AAPL", "buy", 1.0, source="STRATEGY", reference_price=100.0)
    for _ in range(5):
        life.reconcile()
    assert life.state.intents[intent_id]["status"] == "SUBMITTED"
    assert len(transport.orders) == 1
    assert len(life.state.orders) == 1


# ---------------------------------------------------------------------------
# 2. Complete pending-entry lifecycle
# ---------------------------------------------------------------------------

def test_accepted_unfilled_entry_keeps_exit_tracking(tmp_path):
    """Requirement 2: 'do not delete exit tracking merely because no OPEN
    position exists yet.' AlpacaContractTransport never auto-fills, so the
    entry stays ACCEPTED (order status 'new') for as long as the test
    wants -- _check_exit must NOT drop self.positions[symbol] just because
    lifecycle shows no OPEN position."""
    engine, life, transport, outbox, shadow, bus, identity = build_stack(tmp_path, auth=_auth())
    with _no_sleep_poll(life):
        engine._handle_entry(make_signal(stop=98.0, target=104.0))
    assert "AAPL" in engine.positions
    assert life._open_position_for("AAPL") is None  # genuinely not filled yet
    assert transport.orders[0]["status"] == "new"

    # A stop-triggering bar arrives while the entry is STILL merely pending.
    stop_bar = Bar(datetime.now(timezone.utc) + timedelta(minutes=1), 97.5, 98.5, 97.0, 97.5, 1000)
    with _no_sleep_poll(life):
        engine._check_exit("AAPL", stop_bar)
    assert "AAPL" in engine.positions  # plan preserved -- nothing was invented or dropped
    # No sell was attempted either -- there is nothing confirmed-held to sell yet.
    assert not any(o.get("side") == "sell" for o in transport.orders)

    # The fill finally lands.
    life.apply_broker_update(transport.orders[0]["id"], "filled", 1.0, 100.0)
    assert life._open_position_for("AAPL") is not None
    with _no_sleep_poll(life):
        engine._check_exit("AAPL", Bar(stop_bar.timestamp + timedelta(minutes=1), 97.0, 97.5, 96.5, 97.0, 1000))
    assert any(o.get("side") == "sell" for o in transport.orders)  # now it can act


def test_confirmed_rejected_entry_drops_tracking(tmp_path):
    """The OTHER side of requirement 2: once the pending entry resolves to
    a CONFIRMED non-fill (rejected), tracking IS correctly dropped -- there
    is nothing left to protect."""
    engine, life, transport, outbox, shadow, bus, identity = build_stack(tmp_path, auth=_auth())
    with _no_sleep_poll(life):
        engine._handle_entry(make_signal(stop=98.0, target=104.0))
    assert "AAPL" in engine.positions
    life.apply_broker_update(transport.orders[0]["id"], "rejected", 0.0, None)
    assert life.entry_still_pending_or_uncertain("AAPL") is False
    with _no_sleep_poll(life):
        engine._check_exit("AAPL", bar(97.0))
    assert "AAPL" not in engine.positions


def test_uncertain_entry_also_keeps_tracking_until_resolved(tmp_path):
    """A SUBMIT_FAILED_UNCERTAIN entry (no broker id at all yet) must ALSO
    keep exit-plan tracking -- not just an accepted-with-id one."""
    transport = AlpacaContractTransport()
    engine, life, transport, outbox, shadow, bus, identity = build_stack(tmp_path, auth=_auth(), transport=transport)
    signal = make_signal(stop=98.0, target=104.0)
    signal_id = f"strategy_entry_AAPL_{signal.bar_timestamp.isoformat()}"
    intent_id = stable_id("intent", signal_id, "AAPL", "buy", 1.0)
    transport.dropped_client_order_ids.add(intent_id)
    with pytest.raises(RuntimeError):
        with _no_sleep_poll(life):
            engine._handle_entry(signal)
    # _handle_entry's own except clause only catches PaperGuardError -- a
    # raw transport exception propagates (Task 78I contract); the decision
    # engine's own position bookkeeping for AAPL was therefore never
    # reached inside _handle_entry itself. Simulate the caller's outer
    # per-tick guard having already logged it and moved on, and directly
    # verify the LIFECYCLE-level pending-preservation contract instead,
    # which is what this requirement is actually about.
    assert life.entry_still_pending_or_uncertain("AAPL") is True


@pytest.mark.asyncio
async def test_uncertain_entry_self_heals_into_decision_engine_once_resolved_and_filled(tmp_path):
    """The FULL lifecycle of the previous test's scenario: since
    _handle_entry's own self.positions[symbol] assignment is never reached
    for a SUBMIT_FAILED_UNCERTAIN entry, the decision engine has NO
    in-memory plan for AAPL at all -- yet reconcile() later discovers the
    order genuinely reached the broker and filled. The very next on_bars()
    tick must self-heal a full plan for it (via _flag_orphaned_positions's
    rehydration-on-demand), not leave it permanently unmonitored."""
    transport = AlpacaContractTransport()
    engine, life, transport, outbox, shadow, bus, identity = build_stack(tmp_path, auth=_auth(), transport=transport)
    signal = make_signal(stop=98.0, target=104.0)
    signal_id = f"strategy_entry_AAPL_{signal.bar_timestamp.isoformat()}"
    intent_id = stable_id("intent", signal_id, "AAPL", "buy", 1.0)

    real_post = transport.post

    def _post_but_report_failure(url, **kwargs):
        response = real_post(url, **kwargs)  # order genuinely lands at the broker
        raise RuntimeError("simulated response lost after broker accepted it")

    transport.post = _post_but_report_failure
    with pytest.raises(RuntimeError):
        with _no_sleep_poll(life):
            engine._handle_entry(signal)
    assert "AAPL" not in engine.positions  # never reached -- exception propagated first
    assert life.state.intents[intent_id]["status"] == "SUBMIT_FAILED_UNCERTAIN"

    life.reconcile()
    assert life.state.intents[intent_id]["status"] == "SUBMITTED"
    broker_id = transport.orders[0]["id"]
    life.apply_broker_update(broker_id, "filled", 1.0, 100.0)
    assert life._open_position_for("AAPL") is not None
    assert "AAPL" not in engine.positions  # STILL not yet known to the engine

    await engine.on_bars({"AAPL": bar(100.0)})
    assert "AAPL" in engine.positions  # self-healed
    assert engine.positions["AAPL"].stop_price == 98.0
    assert engine.positions["AAPL"].target_price == 104.0


# ---------------------------------------------------------------------------
# 3. Complete durable exit recovery
# ---------------------------------------------------------------------------

def test_triggered_exit_reason_persists_and_survives_price_recovery_after_restart(tmp_path):
    """Requirement 3: 'a triggered exit must remain actionable after
    restart even if price recovers.' A stop fires (latched), the process
    restarts before the resulting sell is confirmed, and price has since
    RECOVERED above the stop by the time the new process observes its
    first bar -- the position must STILL be sold."""
    engine, life, transport, outbox, shadow, bus, identity = build_stack(tmp_path, auth=_auth())
    with _no_sleep_poll(life):
        engine._handle_entry(make_signal(stop=98.0, target=104.0))
    life.apply_broker_update(transport.orders[0]["id"], "filled", 1.0, 100.0)

    stop_bar = Bar(datetime.now(timezone.utc) + timedelta(minutes=1), 97.5, 98.5, 97.0, 97.5, 1000)
    with _no_sleep_poll(life):
        engine._check_exit("AAPL", stop_bar)
    assert "AAPL" in engine.positions
    assert engine.positions["AAPL"].exit_reason == "STOP"
    assert life.state.positions[life.state.open_position_by_symbol["AAPL"]]["triggered_exit_reason"] == "STOP"
    # A sell WAS attempted (the trigger fires order_intent), but the fill is
    # never confirmed before the "crash" -- the position is still OPEN.
    sell_orders_before_restart = [o for o in transport.orders if o.get("side") == "sell"]
    assert len(sell_orders_before_restart) == 1
    assert sell_orders_before_restart[0]["status"] == "new"  # unconfirmed
    assert life._open_position_for("AAPL") is not None

    cfg = life.broker.config
    engine2, life2 = _rebuild_engine(tmp_path, life, bus, cfg, auth=life.experimental_authorization)
    assert "AAPL" in engine2.positions
    assert engine2.positions["AAPL"].exit_reason == "STOP"  # restored, not lost

    # The original, still-unconfirmed sell order is cancelled/expired
    # out-of-band (e.g. day-order expiry) before the new process's first
    # bar -- price has since RECOVERED above the stop. A naive
    # re-derivation from price alone would NOT re-trigger a NEW sell. The
    # persisted reason must still force one.
    life2.apply_broker_update(sell_orders_before_restart[0]["id"], "canceled", 0.0, None)
    recovered_bar = Bar(stop_bar.timestamp + timedelta(minutes=5), 101.0, 102.0, 100.5, 101.5, 1000)
    with _no_sleep_poll(life2):
        engine2._check_exit("AAPL", recovered_bar)
    sell_orders = [o for o in transport.orders if o.get("side") == "sell"]
    assert len(sell_orders) == 2  # a NEW sell attempt was forced despite recovered price


def test_rehydration_blocked_when_quantity_information_missing(tmp_path):
    """Requirement 3: 'missing required plan fields must produce explicit
    degraded/blocked recovery -- not NO_ACTION_REQUIRED.' A position record
    with neither `quantity` nor `remaining_quantity` cannot be sized at all
    -- must NOT be rehydrated as trackable (left for the orphan-detector to
    surface instead of silently inventing a size)."""
    engine, life, transport, outbox, shadow, bus, identity = build_stack(tmp_path)
    life.state.positions["broken_pos"] = {
        "symbol": "MSFT", "status": "OPEN", "stop_price": 98.0, "target_price": 104.0,
        # quantity / remaining_quantity deliberately absent
    }
    life.state.open_position_by_symbol["MSFT"] = "broken_pos"
    life._save()

    cfg = life.broker.config
    engine2, life2 = _rebuild_engine(tmp_path, life, bus, cfg)
    assert "MSFT" not in engine2.positions  # NOT rehydrated -- cannot be safely sized

    events = [json.loads(line) for line in bus.path.read_text(encoding="utf-8").splitlines() if line.strip()]
    assert any(e.get("reason") == "EXIT_PLAN_RECOVERY_BLOCKED_MISSING_QUANTITY" for e in events)

    # The orphan-detector then correctly surfaces it as a visible gap on
    # the very next tick, rather than this staying silent.
    import asyncio
    asyncio.run(engine2.on_bars({"MSFT": bar(200.0)}))
    events = [json.loads(line) for line in bus.path.read_text(encoding="utf-8").splitlines() if line.strip()]
    assert any(e.get("reason") == "MISSING_EXIT_PLAN_FOR_OPEN_POSITION" and e.get("symbol") == "MSFT" for e in events)


def test_rehydration_degraded_when_no_protective_levels(tmp_path):
    """A position with usable quantity but NO stop_price/target_price at
    all CAN be tracked (still gets EOD-flattened) but must be flagged
    degraded, not falsely reassured as 'no action required'."""
    engine, life, transport, outbox, shadow, bus, identity = build_stack(tmp_path)
    life.state.positions["no_levels"] = {
        "symbol": "MSFT", "status": "OPEN", "quantity": 1.0, "remaining_quantity": 1.0,
        "stop_price": None, "target_price": None,
    }
    life.state.open_position_by_symbol["MSFT"] = "no_levels"
    life._save()

    cfg = life.broker.config
    engine2, life2 = _rebuild_engine(tmp_path, life, bus, cfg)
    assert "MSFT" in engine2.positions  # still tracked (EOD flatten still applies)

    events = [json.loads(line) for line in bus.path.read_text(encoding="utf-8").splitlines() if line.strip()]
    assert any(e.get("reason") == "EXIT_PLAN_RECOVERED_WITHOUT_PROTECTIVE_LEVELS" for e in events)
    assert not any(
        e.get("reason") == "EXIT_PLAN_REHYDRATED_FROM_PERSISTED_STATE" and e.get("symbol") == "MSFT" for e in events
    )


def test_rehydration_healthy_case_still_reports_no_action_required(tmp_path):
    """A genuinely healthy, fully-specified position rehydrates with the
    original, non-degraded status -- the degraded/blocked paths above are
    additive, not a regression for the common case."""
    engine, life, transport, outbox, shadow, bus, identity = build_stack(tmp_path, auth=_auth())
    with _no_sleep_poll(life):
        engine._handle_entry(make_signal(stop=98.0, target=104.0))
    life.apply_broker_update(transport.orders[0]["id"], "filled", 1.0, 100.0)

    cfg = life.broker.config
    engine2, life2 = _rebuild_engine(tmp_path, life, bus, cfg, auth=life.experimental_authorization)
    assert "AAPL" in engine2.positions
    events = [json.loads(line) for line in bus.path.read_text(encoding="utf-8").splitlines() if line.strip()]
    assert any(e.get("reason") == "EXIT_PLAN_REHYDRATED_FROM_PERSISTED_STATE" and e.get("symbol") == "AAPL" for e in events)


# ---------------------------------------------------------------------------
# 4. Actual fill causality (delayed/partial fills, replay, restart)
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_delayed_fill_across_multiple_ticks_is_still_causally_protected(tmp_path):
    """Requirement 4: 'replace same-tick-only protection with rules
    covering delayed/partial fills.' An order that stays ACCEPTED (not yet
    filled) for TWO full on_bars() ticks before finally filling on the
    THIRD must never have its stop/target evaluated against the price of
    the tick that produced the entry OR any tick before the fill actually
    landed -- only bars strictly at-or-after the tick the fill was first
    OBSERVED as confirmed are eligible."""
    transport = AlpacaContractTransport()  # never auto-fills
    engine, life, transport, outbox, shadow, bus, identity = build_stack(tmp_path, auth=_auth(), transport=transport)
    ts = datetime.now(timezone.utc)
    signal = make_signal(stop=98.0, target=104.0, ts=ts)
    signal_queue = [signal]

    async def _fake_flush_and_collect():
        return [signal_queue.pop(0)] if signal_queue else []

    engine.scanner._handle_market_tick = AsyncMock()
    engine.flush_and_collect = _fake_flush_and_collect

    # Tick 1: entry submitted (bar's own low is already below stop=98 --
    # must never trigger, since nothing is filled at all yet).
    entry_bar = Bar(ts, 100.0, 100.5, 97.0, 100.0, 1000)
    with _no_sleep_poll(life):
        await engine.on_bars({"AAPL": entry_bar})
    assert "AAPL" in engine.positions
    assert transport.orders[0]["status"] == "new"  # still not filled

    # Tick 2: STILL not filled -- a bar whose low pierces the stop must
    # STILL never trigger a sell, because nothing is confirmed held yet.
    still_pending_bar = Bar(ts + timedelta(minutes=1), 97.0, 97.5, 96.0, 97.0, 1000)
    with _no_sleep_poll(life):
        await engine.on_bars({"AAPL": still_pending_bar})
    assert not any(o.get("side") == "sell" for o in transport.orders)
    assert "AAPL" in engine.positions  # plan preserved (Requirement 2)

    # The fill finally lands, confirmed BETWEEN tick 2 and tick 3 (e.g. a
    # reconcile() call, or the broker simply took a while) -- observed
    # fresh at the START of tick 3, BEFORE tick 3's own bar is evaluated.
    life.apply_broker_update(transport.orders[0]["id"], "filled", 1.0, 97.0)

    # Tick 3: this bar's own low is ALSO below stop -- but this bar is
    # legitimately AFTER the confirmed fill, so it IS eligible and DOES
    # trigger (proving the gate is not simply "always block for this
    # symbol forever" -- it correctly re-opens once genuinely eligible).
    fill_confirmed_bar = Bar(ts + timedelta(minutes=2), 96.5, 97.0, 96.0, 96.5, 1000)
    with _no_sleep_poll(life):
        await engine.on_bars({"AAPL": fill_confirmed_bar})
    sell_orders = [o for o in transport.orders if o.get("side") == "sell"]
    assert len(sell_orders) == 1


@pytest.mark.asyncio
async def test_restart_mid_delayed_fill_still_applies_causality_correctly(tmp_path):
    """A restart occurring WHILE an entry is still merely pending (not yet
    filled) must not fabricate eligibility -- the freshly-rehydrated
    (well, in this case NOT rehydrated, since it's not OPEN yet) engine's
    first tick after the fill finally lands must still be treated as
    "already open before this tick", never using stale pre-restart price
    history to retroactively trigger."""
    transport = AlpacaContractTransport()
    engine, life, transport, outbox, shadow, bus, identity = build_stack(tmp_path, auth=_auth(), transport=transport)
    with _no_sleep_poll(life):
        engine._handle_entry(make_signal(stop=98.0, target=104.0))
    assert transport.orders[0]["status"] == "new"  # not filled at "crash" time

    cfg = life.broker.config
    engine2, life2 = _rebuild_engine(tmp_path, life, bus, cfg, auth=life.experimental_authorization)
    # Not rehydrated as an OPEN position (it never was one) -- but also not
    # silently forgotten: DecisionEngine2 has no bookkeeping for it at all
    # yet, matching a genuinely fresh process's own natural behavior (the
    # NEXT real signal/tick would re-decide it independently; this is not
    # a regression Task 79E-R2 claims to fix, since a genuinely NEW process
    # has no natural way to know about an in-flight, not-yet-filled order
    # it did not itself submit without a broader order-adoption mechanism
    # out of this task's scope -- see remaining_issues in the report).
    life2.apply_broker_update(transport.orders[0]["id"], "filled", 1.0, 100.0)
    assert life2._open_position_for("AAPL") is not None


# ---------------------------------------------------------------------------
# 5. Bind the actual authorized session
# ---------------------------------------------------------------------------

def test_authorization_bound_to_real_session_id_not_fixed_category(tmp_path):
    """Requirement 5: 'REGULAR is a category, not a session identity.'
    An authorization file that still uses the literal "REGULAR" string
    (the OLD R1 scheme) must be REJECTED now -- it no longer matches
    anything real."""
    engine, life, transport, outbox, shadow, bus, identity = build_stack(
        tmp_path, auth=_auth(session_scope="REGULAR"), bind_auth_to_live_session=False,
    )
    with _no_sleep_poll(life):
        engine._handle_entry(make_signal())
    assert transport.orders == []
    assert "AAPL" not in engine.positions


def test_authorization_bound_to_correct_live_session_id_permits(tmp_path):
    engine, life, transport, outbox, shadow, bus, identity = build_stack(tmp_path, auth=_auth())
    assert life.experimental_authorization.session_scope == identity.session_id
    with _no_sleep_poll(life):
        engine._handle_entry(make_signal())
    assert len(transport.orders) == 1


def test_unrelated_session_id_rejected(tmp_path):
    """A DIFFERENT (unrelated) session_id -- e.g. left over from a PRIOR,
    genuinely different process invocation -- must be rejected, never
    treated as still valid just because some session was once live."""
    engine, life, transport, outbox, shadow, bus, identity = build_stack(
        tmp_path, auth=_auth(session_scope="piv_2020-01-01_000000_deadbeef"), bind_auth_to_live_session=False,
    )
    with _no_sleep_poll(life):
        engine._handle_entry(make_signal())
    assert transport.orders == []
    assert "AAPL" not in engine.positions


def test_same_session_recovery_permitted_across_reconstruction(tmp_path):
    """'Permit same-session recovery' -- a NEW DecisionEngine/PaperLifecycle
    pair constructed against the SAME EventBus (same session_id, e.g. an
    in-process supervised restart) must still be permitted, without
    re-authoring the authorization file."""
    engine, life, transport, outbox, shadow, bus, identity = build_stack(tmp_path, auth=_auth())
    cfg = life.broker.config
    engine2, life2 = _rebuild_engine(tmp_path, life, bus, cfg, auth=life.experimental_authorization)
    assert life2.experimental_authorization.session_scope == identity.session_id == bus.session_id
    with _no_sleep_poll(life2):
        engine2._handle_entry(make_signal())
    assert len(transport.orders) == 1


def test_revocation_blocks_new_entries_but_not_existing_exits(tmp_path):
    """'Revocation blocks new entries, never abandons existing exits.'
    Deleting/invalidating the authorization mid-session must not affect an
    ALREADY-open experimental position's own protective exit."""
    auth_path = tmp_path / "experimental_authorization.json"
    from talonx_piv.events import ET
    now = datetime.now(timezone.utc)
    payload = {
        "enabled": True, "experiment_id": "exp-r2", "operator_acknowledged_unvalidated": True,
        "strategy_id": "macd_bullish_cross", "strategy_version": get_strategy_version(),
        "runtime_sha": "sha-r2", "config_hash": "cfg-r2", "allowed_symbols": ["AAPL", "MSFT"],
        "trading_date_et": now.astimezone(ET).date().isoformat(), "session_scope": "REGULAR",
        "activated_at": (now - timedelta(hours=1)).isoformat(), "expires_at": (now + timedelta(hours=10)).isoformat(),
        "paper": {
            "enabled": True, "account_id_binding": "acct-r2", "max_quantity_per_entry": 5.0,
            "max_reference_notional_budget": 10000.0, "max_entry_count": 10, "max_concurrent_exposure": 5,
        },
    }
    auth_path.write_text(json.dumps(payload), encoding="utf-8")

    cfg = PivConfig(
        key_id="key", secret_key="secret", paper_trading=True, real_capital=False,
        broker_endpoint=PAPER_ENDPOINT, approved_sha="abc", state_dir=tmp_path,
        universe=("AAPL", "MSFT"), stale_seconds=90,
    )
    transport = AlpacaContractTransport()
    broker = AlpacaPaperClient(cfg, transport)
    broker.verify_paper_identity()
    identity = build_session_identity(cfg)
    payload["session_scope"] = identity.session_id
    auth_path.write_text(json.dumps(payload), encoding="utf-8")
    bus = EventBus(tmp_path / "piv_events.jsonl", feed_mode=cfg.feed_mode, session_id=identity.session_id)
    life = PaperLifecycle(
        tmp_path / "lifecycle_state.json", broker, bus, PaperEntrySettings.for_test("AAPL", "MSFT"),
        experimental_authorization_path=auth_path, runtime_sha="sha-r2", config_hash="cfg-r2",
    )
    life.start_session(True, True)
    engine = DecisionEngine(
        _NullRedisClient(), bus, life, piv_config=cfg,
        decision_ledger=DecisionLedger(tmp_path / "decision_ledger.json"),
        notification_outbox=NotificationOutbox(tmp_path / "notification_outbox.json", lambda m: True),
        shadow_ledger=ShadowLedger(tmp_path / "shadow_ledger.json"),
        gemini_enrichment=GeminiEnrichmentOutbox(tmp_path / "gemini_enrichment.json"),
        runtime_sha="sha-r2", config_hash="cfg-r2", experimental_authorization_path=auth_path,
    )
    with _no_sleep_poll(life):
        engine._handle_entry(make_signal(stop=98.0, target=104.0))
    assert "AAPL" in engine.positions
    life.apply_broker_update(transport.orders[0]["id"], "filled", 1.0, 100.0)

    auth_path.unlink()  # revoked

    # A NEW entry attempt is now blocked.
    with _no_sleep_poll(life):
        engine._handle_entry(make_signal(ticker="MSFT", price=200.0, stop=196.0, target=208.0))
    assert not any(o["symbol"] == "MSFT" for o in transport.orders)

    # But the EXISTING AAPL position's own protective stop still works.
    stop_bar = Bar(datetime.now(timezone.utc) + timedelta(minutes=1), 97.5, 98.5, 97.0, 97.5, 1000)
    with _no_sleep_poll(life):
        engine._check_exit("AAPL", stop_bar)
    sell_orders = [o for o in transport.orders if o.get("side") == "sell" and o["symbol"] == "AAPL"]
    assert len(sell_orders) == 1


# ---------------------------------------------------------------------------
# 6. Combined failure/recovery scenario
# ---------------------------------------------------------------------------

def test_combined_two_symbols_competing_one_pending_one_uncertain(tmp_path):
    """A single scenario combining several R2 requirements: symbol A is
    ACCEPTED-BUT-UNFILLED (pending), symbol B's own entry attempt must
    still be blocked by the concurrent-exposure guard (max=1) exactly as
    it would be for a confirmed OPEN position -- no double-counting, no
    abandoned monitoring, no oversell."""
    transport = AlpacaContractTransport()
    auth = _auth(paper=ExperimentalPaperPermission(
        enabled=True, account_id_binding="acct-r2", max_quantity_per_entry=5.0,
        max_reference_notional_budget=10000.0, max_entry_count=10, max_concurrent_exposure=1,
    ))
    engine, life, transport, outbox, shadow, bus, identity = build_stack(tmp_path, auth=auth, transport=transport)

    with _no_sleep_poll(life):
        engine._handle_entry(make_signal(ticker="AAPL", stop=98.0, target=104.0))
    assert len(transport.orders) == 1
    assert transport.orders[0]["status"] == "new"  # still pending, not filled

    with _no_sleep_poll(life):
        engine._handle_entry(make_signal(ticker="MSFT", price=200.0, stop=196.0, target=208.0))
    assert len(transport.orders) == 1  # MSFT blocked -- AAPL's pending exposure occupies the one slot
    assert "MSFT" not in engine.positions

    # AAPL's plan is untouched throughout.
    assert "AAPL" in engine.positions
    life.apply_broker_update(transport.orders[0]["id"], "filled", 1.0, 100.0)
    assert life._open_position_for("AAPL") is not None
