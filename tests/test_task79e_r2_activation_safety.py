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
from talonx_piv.lifecycle import PaperLifecycle, UNCERTAIN_SUBMISSION_BACKOFF_SCHEDULE_SECONDS, stable_id
from talonx_piv.notification_outbox import NotificationOutbox
from talonx_piv.session_identity import (
    RECOVERY_REQUIRED, SessionRecoveryRequired, assess_session_recovery,
    build_session_identity, resolve_session_identity,
)
from talonx_piv.session_runner import ET, Bar, SessionRunner
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
        self.positions: list[dict] = []
        self.raise_on_post = False
        self.dropped_client_order_ids: set[str] = set()
        # Task 79E-R2: simulates "the broker returned an UNRELATED order"
        # for a specific client_order_id lookup -- proves verification
        # rejects a response that merely has a truthy `id`.
        self.unrelated_response_for: dict[str, dict] = {}
        self.malformed_response_for: set[str] = set()
        # Task 79E-R2-2: simulates "the order genuinely reached the broker
        # (it exists in self.orders) but a lookup by client_order_id
        # doesn't show it YET" -- eventual-consistency delay, distinct
        # from dropped_client_order_ids (which means the order was NEVER
        # created at all). Removing an id from this set is what makes the
        # SAME real order become discoverable later, without ever
        # duplicating it.
        self.hidden_from_lookup_client_order_ids: set[str] = set()
        # Task 79E-R2-2 Requirement 4: enables driving a REAL
        # SessionRunner.process_tick loop (fetch_bars_latest calls
        # GET .../bars/latest) through this SAME transport, so the
        # combined restart/recovery scenario test exercises actual runtime
        # wiring rather than manually invoking recovery helpers.
        self.bar_batches: list[dict] = []

    def get(self, url, **kwargs):
        if url.endswith("/v2/account"):
            return Response({"id": self.account_id, "account_number": "PA555555", "status": "ACTIVE"})
        if "bars/latest" in url:
            body = self.bar_batches.pop(0) if self.bar_batches else {}
            return Response({"bars": body})
        if url.endswith("/v2/orders:by_client_order_id"):
            params = kwargs.get("params") or {}
            client_order_id = params.get("client_order_id")
            if client_order_id in self.malformed_response_for:
                return Response({"not_an_order": True}, 200)  # 200 but no usable `id`
            if client_order_id in self.unrelated_response_for:
                return Response(self.unrelated_response_for[client_order_id], 200)
            if client_order_id in self.hidden_from_lookup_client_order_ids:
                return Response({"message": "order not found"}, 404)
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
            return Response(self.positions)
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


def test_repeated_404s_never_auto_confirm_not_submitted_then_order_appears_and_is_adopted_once(tmp_path):
    """Task 79E-R2-2 Requirement 1 (supersedes R2's own now-corrected
    threshold design -- see the report's addendum): NO count of "not
    found" results, however large, may ever auto-declare an intent
    confirmed-not-submitted -- absence is never proof of non-submission.
    Exposure (pyramiding block) is retained across every one of several
    404s; once the ORIGINAL order finally becomes discoverable (e.g. a
    broker-side eventual-consistency delay resolves), it is adopted --
    exactly once, with no duplicate entry ever submitted."""
    transport = AlpacaContractTransport()
    engine, life, transport, outbox, shadow, bus, identity = build_stack(tmp_path, transport=transport)
    intent_id = stable_id("intent", "s1", "AAPL", "buy", 1.0)
    # The order DOES genuinely reach the broker (a real record is created),
    # but the local response is lost -- AND a lookup by client_order_id
    # does not show it yet either (eventual-consistency delay), so several
    # reconcile() passes must observe "not found" before it clears up.
    real_post = transport.post

    def _post_but_hide_from_lookup(url, **kwargs):
        response = real_post(url, **kwargs)
        transport.hidden_from_lookup_client_order_ids.add(intent_id)
        raise RuntimeError("simulated response lost after broker accepted it")

    transport.post = _post_but_hide_from_lookup
    with pytest.raises(RuntimeError):
        life.order_intent("s1", "AAPL", "buy", 1.0, source="STRATEGY", reference_price=100.0)
    assert len(transport.orders) == 1  # it DID reach the broker

    # Deterministic, explicit "controlled" timestamps -- never datetime.now()
    # ordering assumptions -- spaced far enough apart to clear even the
    # LONGEST backoff interval, so every one of these calls genuinely
    # re-queries the broker (proving the "never auto-resolve" behaviour is
    # not merely masked by backoff skipping the check).
    base = datetime(2026, 1, 1, tzinfo=timezone.utc)
    max_backoff = max(UNCERTAIN_SUBMISSION_BACKOFF_SCHEDULE_SECONDS)
    for attempt in range(1, 6):  # far more than R2's old threshold of 2
        moment = base + timedelta(seconds=attempt * (max_backoff + 1))
        life.reconcile(now=moment)
        assert life.state.intents[intent_id]["status"] == "SUBMIT_FAILED_UNCERTAIN", f"wrongly auto-resolved at attempt {attempt}"
        assert life.state.intents[intent_id]["not_found_confirmations"] == attempt
        with pytest.raises(PaperGuardError, match="PENDING_ENTRY_EXISTS"):
            life.order_intent(f"retry-{attempt}", "AAPL", "buy", 1.0, source="STRATEGY", reference_price=100.0)

    # The original order finally becomes discoverable (broker-side eventual
    # consistency resolved, or a transient lookup issue cleared up).
    transport.hidden_from_lookup_client_order_ids.discard(intent_id)
    real_order = next(o for o in transport.orders if o.get("client_order_id") == intent_id)
    life.reconcile(now=base + timedelta(seconds=6 * (max_backoff + 1)))
    assert life.state.intents[intent_id]["status"] == "SUBMITTED"
    assert real_order["id"] in life.state.orders

    # Adopted exactly once -- a further reconcile() pass is a no-op (the
    # intent is no longer SUBMIT_FAILED_UNCERTAIN, so it is not re-queried
    # at all), and no duplicate order was ever created.
    orders_before = len(transport.orders)
    life.reconcile(now=base + timedelta(seconds=7 * (max_backoff + 1)))
    assert len(transport.orders) == orders_before
    assert len([o for o in life.state.orders.values() if o.get("intent_id") == intent_id]) == 1
    # Still correctly blocks a same-symbol retry -- the ADOPTED order is
    # itself now a real, non-terminal outstanding order (status "new"),
    # never a duplicate entry.
    with pytest.raises(PaperGuardError, match="PENDING_ENTRY_EXISTS"):
        life.order_intent("s2-new", "AAPL", "buy", 1.0, source="STRATEGY", reference_price=100.0)


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
    life.apply_broker_update(
        transport.orders[0]["id"], "filled", 1.0, 100.0, filled_at=datetime.now(timezone.utc).isoformat(),
    )
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
    life.apply_broker_update(
        transport.orders[0]["id"], "filled", 1.0, 100.0, filled_at=datetime.now(timezone.utc).isoformat(),
    )

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

def test_forced_eod_exit_unaffected_by_unknown_fill_timing(tmp_path):
    """Requirement 2: 'Preserve legitimate post-fill and forced EOD
    exits.' A forced EOD flatten is time-based, never price-based -- it
    must still flatten a position even with COMPLETELY UNKNOWN fill
    timing (no first_fill_observed_at at all), which is exactly the case
    the natural price-based gate now correctly refuses to act on. Proves
    `force_reason` genuinely bypasses the fill-time causality gate."""
    engine, life, transport, outbox, shadow, bus, identity = build_stack(tmp_path, auth=_auth())
    with _no_sleep_poll(life):
        engine._handle_entry(make_signal(stop=98.0, target=104.0))
    assert "AAPL" in engine.positions
    # Filled, but with NO filled_at at all -- unknown timing.
    life.apply_broker_update(transport.orders[0]["id"], "filled", 1.0, 100.0)
    assert life._open_position_for("AAPL") is not None

    # A NATURAL price-based check must NOT trigger -- unknown timing.
    stop_bar = bar(97.5)
    with _no_sleep_poll(life):
        engine._check_exit("AAPL", stop_bar)
    assert "AAPL" in engine.positions
    assert not any(o.get("side") == "sell" for o in transport.orders)

    # A FORCED (EOD) exit, via flatten_all, DOES still act despite the
    # exact same unknown timing.
    with _no_sleep_poll(life):
        engine.flatten_all({"AAPL": bar(97.5)})
    sell_orders = [o for o in transport.orders if o.get("side") == "sell"]
    assert len(sell_orders) == 1
    assert engine.positions["AAPL"].exit_reason == "END_OF_SESSION"
    life.apply_broker_update(sell_orders[0]["id"], "filled", 1.0, 97.5)
    with _no_sleep_poll(life):
        engine._check_exit("AAPL", bar(97.5))  # observes confirmed-flat, stops tracking
    assert "AAPL" not in engine.positions


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
    # `filled_at` is a CONTROLLED timestamp (never datetime.now()),
    # explicitly placed between tick 2 and tick 3's own bar timestamps.
    life.apply_broker_update(
        transport.orders[0]["id"], "filled", 1.0, 97.0,
        filled_at=(ts + timedelta(minutes=1, seconds=30)).isoformat(),
    )

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
async def test_restart_mid_pending_entry_restores_plan_and_applies_causality_correctly(tmp_path):
    """Task 79E-R2-2 Requirement 4: 'full-process restart also fails to
    restore pending-entry plans' -- CLOSED this task (see
    DecisionEngine._rehydrate_pending_entries). A restart occurring WHILE
    an entry is still merely pending (not yet filled) now DOES restore a
    plan for it (stop/target from the durable intent record), and once the
    fill finally lands and is confirmed, causality is still correctly
    applied -- a bar BEFORE the fill was ever confirmed by the NEW process
    must not retroactively trigger, exactly like the pre-restart case."""
    transport = AlpacaContractTransport()
    engine, life, transport, outbox, shadow, bus, identity = build_stack(tmp_path, auth=_auth())
    with _no_sleep_poll(life):
        engine._handle_entry(make_signal(stop=98.0, target=104.0))
    assert transport.orders[0]["status"] == "new"  # not filled at "crash" time

    cfg = life.broker.config
    engine2, life2 = _rebuild_engine(tmp_path, life, bus, cfg, auth=life.experimental_authorization)
    # Now RESTORED -- the pending entry's own plan, from the durable intent
    # record (never invented).
    assert "AAPL" in engine2.positions
    assert engine2.positions["AAPL"].stop_price == 98.0
    assert engine2.positions["AAPL"].target_price == 104.0

    # A bar arrives on the new process BEFORE the fill is ever confirmed --
    # must not trigger (nothing confirmed-held yet).
    pre_fill_bar = Bar(datetime.now(timezone.utc), 97.0, 97.5, 96.0, 97.0, 1000)
    with _no_sleep_poll(life2):
        engine2._check_exit("AAPL", pre_fill_bar)
    assert "AAPL" in engine2.positions
    assert not any(o.get("side") == "sell" for o in transport.orders)

    # The fill lands, confirmed with a controlled timestamp strictly AFTER
    # pre_fill_bar's own.
    life2.apply_broker_update(
        transport.orders[0]["id"], "filled", 1.0, 100.0,
        filled_at=(pre_fill_bar.timestamp + timedelta(seconds=30)).isoformat(),
    )
    assert life2._open_position_for("AAPL") is not None

    # A bar STRICTLY after the confirmed fill now correctly triggers.
    post_fill_bar = Bar(pre_fill_bar.timestamp + timedelta(minutes=1), 97.0, 97.5, 96.0, 97.0, 1000)
    with _no_sleep_poll(life2):
        engine2._check_exit("AAPL", post_fill_bar)
    assert any(o.get("side") == "sell" for o in transport.orders)


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


def test_broker_boundary_ignores_a_contradictory_caller_supplied_session_scope(tmp_path):
    """Requirement 3's own exact reproduction: 'lifecycle.events.session_id
    is session-B, authorization permits session-A, and the caller supplies
    session-A; the broker-entry guard accepts it.' This is the R2 (round
    1) defect: order_intent's own `experimental_session_scope` parameter
    was what got checked, so a caller (bug or otherwise) claiming a
    DIFFERENT session than the lifecycle's own REAL one was silently
    trusted. Called directly at the true broker boundary (order_intent)
    to isolate this from decision_engine.py's own separate, independent
    pre-check -- proving THIS layer alone no longer trusts the caller."""
    auth = _auth(session_scope="session-B")
    engine, life, transport, outbox, shadow, bus, identity = build_stack(
        tmp_path, auth=dataclasses.replace(auth, session_scope="session-B"), bind_auth_to_live_session=False,
    )
    # The lifecycle's OWN real session_id is `identity.session_id` (call it
    # "session-A" in the reproduction's own naming) -- NOT "session-B".
    assert bus.session_id != "session-B"
    with pytest.raises(PaperGuardError, match="EXPERIMENTAL_WRONG_SESSION_SCOPE"):
        life.order_intent(
            "s1", "AAPL", "buy", 1.0, source="EXPERIMENTAL", reference_price=100.0,
            experimental_id="exp-r2", experimental_trading_date_et=_auth().trading_date_et,
            strategy_id="macd_bullish_cross", experimental_strategy_version=get_strategy_version(),
            # The caller CLAIMS "session-B" (matching the authorization) --
            # this must be IGNORED; only lifecycle's own real session_id
            # (bus.session_id, which is neither "session-A" nor
            # "session-B" here) is ever actually checked.
            experimental_session_scope="session-B",
        )
    assert transport.orders == []


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
    life.apply_broker_update(
        transport.orders[0]["id"], "filled", 1.0, 100.0, filled_at=datetime.now(timezone.utc).isoformat(),
    )

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
# Task 79E-R2-3: recovery-state integrity regressions
# ---------------------------------------------------------------------------

def test_reconcile_mismatch_blocks_entries_until_a_later_matched_pass(tmp_path):
    engine, life, transport, outbox, shadow, bus, identity = build_stack(tmp_path)
    transport.positions = [{"symbol": "NFLX", "qty": "1", "side": "long"}]

    result = life.reconcile()
    assert result["matched"] is False
    assert life.state.reconciliation_flags["entry_admission_blocked"] is True
    with pytest.raises(PaperGuardError, match="RECONCILIATION_BLOCKS_NEW_ENTRIES"):
        life.order_intent("blocked", "AAPL", "buy", 1.0, source="STRATEGY")

    transport.positions = []
    result = life.reconcile()
    assert result["matched"] is True
    assert life.state.reconciliation_flags["entry_admission_blocked"] is False
    assert life.order_intent("recovered", "AAPL", "buy", 1.0, source="STRATEGY")["id"]


def test_periodic_reconcile_exception_blocks_new_entries_but_preserves_exits(tmp_path):
    engine, life, transport, outbox, shadow, bus, identity = build_stack(tmp_path)
    entry = life.order_intent("open", "AAPL", "buy", 1.0, source="STRATEGY")
    life.apply_broker_update(entry["id"], "filled", 1.0, 100.0, filled_at=datetime.now(timezone.utc).isoformat())
    runner = SessionRunner(life.broker.config, bus, life, transport)

    def fail_reconcile(*, now=None):
        raise ConnectionError("broker read unavailable")

    life.reconcile = fail_reconcile
    runner._maybe_reconcile(datetime.now(timezone.utc))
    assert life.state.reconciliation_flags["entry_admission_blocked"] is True
    with pytest.raises(PaperGuardError, match="RECONCILIATION_BLOCKS_NEW_ENTRIES"):
        life.order_intent("blocked", "MSFT", "buy", 1.0, source="STRATEGY")

    # Entry admission is blocked, but reducing known long exposure remains
    # available and correctly sized.
    exit_order = life.order_intent("protective", "AAPL", "sell", 1.0, source="STRATEGY")
    assert exit_order["side"] == "sell"

    reloaded = PaperLifecycle(
        tmp_path / "lifecycle_state.json", life.broker, bus,
        PaperEntrySettings.for_test("AAPL", "MSFT"),
    )
    assert reloaded.state.reconciliation_flags["entry_admission_blocked"] is True


def test_restart_rehydrates_actual_pending_order_not_older_same_symbol_intent(tmp_path):
    engine, life, transport, outbox, shadow, bus, identity = build_stack(tmp_path)
    old = life.order_intent(
        "old", "AAPL", "buy", 1.0, source="STRATEGY",
        stop_price=90.0, target_price=130.0,
    )
    life.apply_broker_update(old["id"], "rejected", 0.0, None)
    new = life.order_intent(
        "new", "AAPL", "buy", 1.0, source="STRATEGY",
        stop_price=98.0, target_price=104.0,
    )
    assert new["status"] == "new"

    engine2, life2 = _rebuild_engine(tmp_path, life, bus, life.broker.config)
    assert engine2.positions["AAPL"].stop_price == 98.0
    assert engine2.positions["AAPL"].target_price == 104.0
    assert engine2.positions["AAPL"].entry_signal_id == (
        f"rehydrated_pending_{stable_id('intent', 'new', 'AAPL', 'buy', 1.0)}"
    )


def test_later_buy_fill_preserves_prior_exits_remaining_holdings_and_exit_latch(tmp_path):
    engine, life, transport, outbox, shadow, bus, identity = build_stack(tmp_path)
    buy = life.order_intent(
        "entry", "AAPL", "buy", 2.0, source="STRATEGY",
        reference_price=100.0, stop_price=98.0, target_price=104.0,
    )
    life.apply_broker_update(
        buy["id"], "partially_filled", 1.0, 100.0,
        filled_at="2026-08-28T14:00:00+00:00",
    )
    life.mark_exit_triggered("AAPL", "STOP_HIT")
    sell = life.order_intent(
        "partial-exit", "AAPL", "sell", 0.4, source="STRATEGY", reference_price=99.0,
    )
    life.apply_broker_update(sell["id"], "filled", 0.4, 99.0)

    before = dict(life._open_position_for("AAPL"))
    assert before["exit_quantity"] == pytest.approx(0.4)
    assert before["remaining_quantity"] == pytest.approx(0.6)
    assert before["triggered_exit_reason"] == "STOP_HIT"

    # The original BUY order later completes. Only its newly-filled 1 share
    # is added to current holdings; the 0.4 already sold is not resurrected.
    life.apply_broker_update(
        buy["id"], "filled", 2.0, 100.5,
        filled_at="2026-08-28T14:05:00+00:00",
    )
    after = life._open_position_for("AAPL")
    assert after["quantity"] == pytest.approx(2.0)
    assert after["exit_quantity"] == pytest.approx(0.4)
    assert after["remaining_quantity"] == pytest.approx(1.6)
    assert after["triggered_exit_reason"] == "STOP_HIT"
    assert after["exit_price"] == pytest.approx(99.0)
    assert after["first_fill_observed_at"] == "2026-08-28T14:00:00+00:00"


def test_session_identity_reuse_requires_current_config_and_runtime_bindings(tmp_path):
    now = datetime(2026, 8, 28, 14, 0, tzinfo=timezone.utc)
    # Explicit paper bindings like every other verify_paper_identity() call
    # in this file -- otherwise the config falls back to ambient TALONX_PIV_*
    # env vars, which a sanitized clean-room run strips (paper_trading=False
    # -> PaperGuardError at the broker boundary below).
    cfg = PivConfig(
        key_id="key", secret_key="secret", paper_trading=True, real_capital=False,
        broker_endpoint=PAPER_ENDPOINT, state_dir=tmp_path,
        universe=("AAPL",), feed_mode="IEX_PAPER_PIV",
    )
    pending_intent_id = stable_id("intent", "pending-before-rebind", "AAPL", "buy", 1.0)
    with patch("talonx_piv.session_identity.runtime_sha", return_value="sha-old"):
        saved = build_session_identity(cfg, now=now)
    (tmp_path / "session_identity.json").write_text(json.dumps(saved.to_dict()), encoding="utf-8")
    (tmp_path / "lifecycle_state.json").write_text(
        json.dumps({
            "session_enabled": True,
            "kill_switch": False,
            "intents": {
                pending_intent_id: {
                    "status": "ORDER_INTENT",
                    "payload": {"symbol": "AAPL", "side": "buy", "qty": "1.0"},
                    "experimental_id": "exp-r2-3",
                },
            },
            "experimental_budgets": {
                "exp-r2-3": {"entries_used": 1, "notional_used": 100.0},
            },
        }),
        encoding="utf-8",
    )

    with patch("talonx_piv.session_identity.runtime_sha", return_value="sha-old"):
        same = resolve_session_identity(cfg, now=now + timedelta(minutes=1))
    assert same.session_id == saved.session_id

    # Task 81 §3 (supersedes R2-3's "silently mint a fresh identity" here):
    # a CHANGED binding while an unresolved ORDER_INTENT (pending entry
    # exposure) still exists must NOT silently create a replacement
    # session. It raises SessionRecoveryRequired, preserving recovery
    # context and naming the operator action.
    changed_cfg = dataclasses.replace(cfg, universe=("AAPL", "MSFT"))
    with patch("talonx_piv.session_identity.runtime_sha", return_value="sha-old"):
        with pytest.raises(SessionRecoveryRequired) as ei_config:
            resolve_session_identity(changed_cfg, now=now + timedelta(minutes=2))
    assert any("BINDINGS_CHANGED" in r for r in ei_config.value.reasons)
    assert any("UNRESOLVED_SUBMISSION" in r for r in ei_config.value.reasons)
    assert "eod" in ei_config.value.required_action
    assert ei_config.value.preserved_identity["session_id"] == saved.session_id

    with patch("talonx_piv.session_identity.runtime_sha", return_value="sha-new"):
        with pytest.raises(SessionRecoveryRequired) as ei_sha:
            resolve_session_identity(cfg, now=now + timedelta(minutes=3))
    assert any("runtime_sha" in r for r in ei_sha.value.reasons)

    # The recovery-required condition must not have rewritten durable
    # lifecycle truth. Budget use and unresolved exposure are intact and
    # still block a same-symbol retry at the broker boundary.
    transport = AlpacaContractTransport()
    broker = AlpacaPaperClient(changed_cfg, transport)
    broker.verify_paper_identity()
    bus = EventBus(tmp_path / "rebound_events.jsonl", session_id=saved.session_id)
    life = PaperLifecycle(
        tmp_path / "lifecycle_state.json", broker, bus,
        PaperEntrySettings.for_test("AAPL", "MSFT"),
    )
    assert life.state.experimental_budgets["exp-r2-3"] == {
        "entries_used": 1, "notional_used": 100.0,
    }
    assert life.entry_still_pending_or_uncertain("AAPL") is True
    with pytest.raises(PaperGuardError, match="PENDING_ENTRY_EXISTS"):
        life.order_intent("retry-after-rebind", "AAPL", "buy", 1.0, source="STRATEGY")

    # The defined, verified transition: once the pending exposure is
    # resolved (here: the intent reaches a terminal state) a changed
    # binding cleanly mints a fresh session -- no recovery block.
    state = json.loads((tmp_path / "lifecycle_state.json").read_text())
    state["intents"][pending_intent_id]["status"] = "REJECTED"
    state["session_enabled"] = False
    (tmp_path / "lifecycle_state.json").write_text(json.dumps(state), encoding="utf-8")
    with patch("talonx_piv.session_identity.runtime_sha", return_value="sha-old"):
        clean = assess_session_recovery(changed_cfg, now=now + timedelta(minutes=4))
    assert clean.mode != RECOVERY_REQUIRED
    assert clean.identity.session_id != saved.session_id


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


# ---------------------------------------------------------------------------
# 7. Combined recovery scenario -- REAL SessionRunner/supervisor wiring,
#    across simulated full-process restarts, fake external services only.
# ---------------------------------------------------------------------------

def bar_row(ts_iso: str, price: float = 100.0) -> dict:
    return {"t": ts_iso, "o": price, "h": price + 1, "l": price - 1, "c": price, "v": 1000}


def to_utc_iso(local: datetime) -> str:
    return local.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def build_runner_stack(tmp_path, transport, *, redis_messages=None):
    """Task 79E-R2-2 Requirement 4: builds a REAL SessionRunner (not a bare
    DecisionEngine/PaperLifecycle pair) against the SAME shared transport
    and tmp_path -- called once per simulated "process" in the combined
    scenario below, exactly like test_task78i_stage5_rehearsal.py's own
    established pattern. Uses resolve_session_identity (not
    build_session_identity) so a "restart" (a second/third call against
    the SAME tmp_path, with the prior session still session_enabled=True)
    genuinely proves Requirement 3's full-process session recovery, not
    merely an in-memory EventBus reconstruction."""
    cfg = PivConfig(
        key_id="key", secret_key="secret", paper_trading=True, real_capital=False,
        broker_endpoint=PAPER_ENDPOINT, approved_sha="abc", state_dir=tmp_path,
        universe=("AAPL",), stale_seconds=90,
    )
    broker = AlpacaPaperClient(cfg, transport)
    broker.verify_paper_identity()
    identity = resolve_session_identity(cfg)
    (tmp_path / "session_identity.json").write_text(json.dumps(identity.to_dict(), sort_keys=True), encoding="utf-8")
    bus = EventBus(tmp_path / "piv_events.jsonl", feed_mode=cfg.feed_mode, session_id=identity.session_id)
    life = PaperLifecycle(tmp_path / "lifecycle_state.json", broker, bus, PaperEntrySettings.for_test("AAPL"))
    life.start_session(True, True)
    from talonx_piv.decision_contract import StrategyApprovalStatus
    engine = DecisionEngine(
        _FakeRedisClient(_FakePubSub(redis_messages)), bus, life, piv_config=cfg,
        decision_ledger=DecisionLedger(tmp_path / "decision_ledger.json"),
        notification_outbox=NotificationOutbox(tmp_path / "notification_outbox.json", lambda m: True),
        shadow_ledger=ShadowLedger(tmp_path / "shadow_ledger.json"),
        gemini_enrichment=GeminiEnrichmentOutbox(tmp_path / "gemini_enrichment.json"),
        runtime_sha=identity.runtime_sha, config_hash=identity.config_hash,
        # TEST_FIXTURE_ONLY -- NOT ALPHA EVIDENCE. This combined scenario is
        # about the RUNTIME RECOVERY machinery (Requirement 4), not the
        # experimental-authorization path already covered elsewhere in
        # this file -- an approved-strategy fixture keeps the scenario
        # focused, matching test_task78i_stage5_rehearsal.py's own
        # established pattern.
        strategy_approval_status_override=StrategyApprovalStatus.APPROVED,
    )
    engine.scanner._handle_market_tick = AsyncMock()
    engine.scanner._flush_throttle_window = AsyncMock()
    engine.warmup_ready_symbols = {"AAPL"}
    runner = SessionRunner(cfg, bus, life, transport, decision_engine=engine, poll_interval_seconds=60.0)
    return cfg, broker, identity, bus, life, engine, runner


def _prime_ready(runner: SessionRunner, tick: datetime) -> None:
    """Bypasses the opening-range warmup dance (not this test's own
    concern -- see test_task78i_stage5_rehearsal.py for dedicated
    readiness-path coverage) by hand-setting the SAME session/ready-
    symbols state a natural 09:30-10:00 ET warmup would have finalized to.
    Must set `_session` FIRST -- process_tick's own session-boundary
    check resets `_ready_symbols` to None whenever `_session` does not
    already match the tick's own ET date."""
    runner._session = tick.astimezone(ET).date()
    runner._ready_symbols = {"AAPL"}


class _FakePubSub:
    def __init__(self, messages=None):
        self._messages = list(messages or [])

    async def subscribe(self, channel): pass
    async def unsubscribe(self, channel): pass
    async def close(self): pass

    async def get_message(self, ignore_subscribe_messages=True, timeout=0.2):
        if self._messages:
            return {"data": self._messages.pop(0)}
        return None


class _FakeRedisClient:
    def __init__(self, pubsub):
        self._pubsub = pubsub

    def pubsub(self):
        return self._pubsub


@pytest.mark.asyncio
async def test_combined_restart_recovery_scenario_through_real_session_runner(tmp_path):
    """Task 79E-R2-2 Requirement 4's own required combined scenario, driven
    through REAL SessionRunner.process_tick calls (never a manually-
    invoked recovery helper standing in for runtime wiring):

    accepted entry -> process restart -> delayed fill -> restored
    monitoring -> triggered partial exit -> restart with recovered price
    -> completed exit.

    Three simulated full-process "restarts" share the SAME lifecycle
    state file and the SAME broker transport (its own order history is
    exactly what a real Alpaca paper account would retain across a real
    restart) -- only the SessionRunner/DecisionEngine/PaperLifecycle
    Python objects are torn down and rebuilt each time, exactly mirroring
    what actually happens when this codebase's own process restarts."""
    with patch("time.sleep", lambda *_: None):
        transport = AlpacaContractTransport()
        base = datetime(2026, 8, 27, 9, 30, tzinfo=timezone.utc)

        # -- "Process 1": accepted entry --------------------------------------
        signal = make_signal(stop=98.0, target=104.0, ts=base)
        cfg1, broker1, identity1, bus1, life1, engine1, runner1 = build_runner_stack(
            tmp_path, transport, redis_messages=[signal.model_dump_json().encode()],
        )
        tick1 = base
        _prime_ready(runner1, tick1)
        transport.bar_batches.append({"AAPL": bar_row(to_utc_iso(tick1), 100.0)})
        await runner1.process_tick(tick1)
        assert "AAPL" in engine1.positions
        buy_order = transport.orders[0]
        assert buy_order["status"] == "new"  # accepted, NOT yet filled -- a genuinely pending entry

        # -- "Process 2": restart while still pending, THEN the delayed fill --
        cfg2, broker2, identity2, bus2, life2, engine2, runner2 = build_runner_stack(tmp_path, transport)
        _prime_ready(runner2, tick1)
        assert identity2.session_id == identity1.session_id  # Requirement 3: same-session recovery, full process
        assert "AAPL" in engine2.positions  # Requirement 4: pending-entry plan RESTORED, not lost
        assert engine2.positions["AAPL"].stop_price == 98.0
        assert life2._open_position_for("AAPL") is None  # still genuinely not filled

        delayed_fill_at = tick1 + timedelta(minutes=1, seconds=30)
        life2.apply_broker_update(buy_order["id"], "filled", 1.0, 100.0, filled_at=delayed_fill_at.isoformat())
        assert life2._open_position_for("AAPL") is not None

        # A tick whose bar is BEFORE the confirmed fill must never trigger --
        # proves restored monitoring respects fill-time causality, not merely
        # "is it open now."
        tick2 = tick1 + timedelta(minutes=1)
        transport.bar_batches.append({"AAPL": bar_row(to_utc_iso(tick2), 97.0)})  # low pierces stop, but PRE-fill
        await runner2.process_tick(tick2)
        assert not any(o.get("side") == "sell" for o in transport.orders)
        assert "AAPL" in engine2.positions

        # A tick strictly AFTER the confirmed fill DOES trigger -- a partial exit.
        tick3 = tick1 + timedelta(minutes=2)
        transport.bar_batches.append({"AAPL": bar_row(to_utc_iso(tick3), 96.5)})  # low pierces stop, post-fill
        await runner2.process_tick(tick3)
        sell_orders = [o for o in transport.orders if o.get("side") == "sell"]
        assert len(sell_orders) == 1
        triggered_sell = sell_orders[0]
        # Partially filled, then the rest cancelled -- 0.6 genuinely still owed.
        life2.apply_broker_update(triggered_sell["id"], "partially_filled", 0.4, 97.0)
        life2.apply_broker_update(triggered_sell["id"], "canceled", 0.4, 97.0)
        assert life2.remaining_holdings("AAPL") == pytest.approx(0.6)
        assert engine2.positions["AAPL"].exit_reason == "STOP"

        # -- "Process 3": restart with a triggered-but-unconfirmed partial exit,
        #    and price has since RECOVERED well above the stop -------------
        cfg3, broker3, identity3, bus3, life3, engine3, runner3 = build_runner_stack(tmp_path, transport)
        _prime_ready(runner3, tick1)
        assert identity3.session_id == identity1.session_id  # STILL the same recovered session
        assert "AAPL" in engine3.positions
        assert engine3.positions["AAPL"].exit_reason == "STOP"  # the trigger survived TWO restarts

        # This restarted process's first ordinary tick also suffers a broker
        # reconciliation read failure. The tick must continue, durably block
        # only NEW BUY exposure, and preserve the already-latched protective
        # exit obligation for the verified remaining 0.6 shares.
        def fail_reconcile(*, now=None):
            raise ConnectionError("simulated reconciliation read failure")

        life3.reconcile = fail_reconcile
        tick4 = tick1 + timedelta(minutes=3)
        # Price fully recovered above the stop -- a naive re-derivation from
        # price alone would NOT re-trigger. The persisted reason must still
        # force the remaining 0.6 to be sold.
        transport.bar_batches.append({"AAPL": bar_row(to_utc_iso(tick4), 102.0)})
        await runner3.process_tick(tick4)
        assert life3.state.reconciliation_flags["entry_admission_blocked"] is True
        sell_orders = [o for o in transport.orders if o.get("side") == "sell"]
        assert len(sell_orders) == 2
        completing_sell = sell_orders[1]
        assert completing_sell["qty"] == "0.6"  # sized to ACTUAL remaining holdings, never a fixed constant
        with pytest.raises(PaperGuardError, match="RECONCILIATION_BLOCKS_NEW_ENTRIES"):
            life3.order_intent("blocked-after-reconcile", "MSFT", "buy", 1.0, source="STRATEGY")

        life3.apply_broker_update(completing_sell["id"], "filled", 0.6, 102.0, filled_at=tick4.isoformat())
        assert life3._open_position_for("AAPL") is None  # fully closed

        # One more tick observes the now-confirmed-flat state and stops tracking.
        tick5 = tick1 + timedelta(minutes=4)
        transport.bar_batches.append({"AAPL": bar_row(to_utc_iso(tick5), 102.0)})
        await runner3.process_tick(tick5)
        assert "AAPL" not in engine3.positions
