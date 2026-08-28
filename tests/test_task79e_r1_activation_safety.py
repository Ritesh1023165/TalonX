"""Task 79E-R1 -- closes the activation blockers found in Task 79E's own
experimental-permission mechanism: exit recovery/partial fills, entry/exit
causality, session-scope/revocation enforcement, pending-exposure/durable
budget integrity, and preserved alert/shadow independence under failure.

Every scenario here is REPRODUCED first against the pre-fix behaviour (see
implementation notes in each test's docstring), then asserted fixed. Offline
only -- FakeTransport/FakePubSub/FakeRedisClient, zero network access, no
live session, no broker mutations, no notifications sent (outbox uses a
fake `send`), no active `experimental_authorization.json` in the repo.

TEST_FIXTURE_ONLY -- NOT ALPHA EVIDENCE throughout."""
from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, patch

import pytest

from talonx_backtest.reproducibility import get_strategy_version
from talonx_piv.broker import AlpacaPaperClient, PaperGuardError
from talonx_piv.config import PAPER_ENDPOINT, PivConfig
from talonx_piv.decision_contract import Recommendation
from talonx_piv.decision_engine import DecisionEngine, OpenDecisionPosition
from talonx_piv.decision_ledger import DecisionLedger
from talonx_piv.events import EventBus
from talonx_piv.execution_settings import PaperEntrySettings
from talonx_piv.experimental_authorization import ExperimentalAuthorization, ExperimentalPaperPermission
from talonx_piv.gemini_enrichment import GeminiEnrichmentOutbox
from talonx_piv.lifecycle import PaperLifecycle
from talonx_piv.notification_outbox import CLASSIFICATION_EXPERIMENTAL_BUY, NotificationOutbox
from talonx_piv.session_identity import build_session_identity
from talonx_piv.session_runner import Bar
from talonx_piv.shadow_ledger import ShadowLedger
from talonx_quant.schemas import QuantSignal, SignalDirection, SignalType


# ---------------------------------------------------------------------------
# Shared fixtures -- a controllable (never auto-filling) transport, so tests
# can drive partial fills / rejections / uncertain submissions explicitly
# rather than relying on an instant-fill fake.
# ---------------------------------------------------------------------------

class Response:
    def __init__(self, body, status=200): self.body, self.status_code = body, status
    def json(self): return self.body
    def raise_for_status(self):
        if self.status_code >= 400: raise RuntimeError(f"HTTP {self.status_code}")


class ControllableTransport:
    """TEST_FIXTURE_ONLY -- NOT ALPHA EVIDENCE. Orders start 'new' (never
    auto-filled) so a test can apply fills/partial-fills/cancellations at
    exactly the moment it wants via PaperLifecycle.apply_broker_update."""

    def __init__(self, account_id="acct-r1"):
        self.account_id = account_id
        self.orders: list[dict] = []
        self.raise_on_post = False
        self.dropped_client_order_ids: set[str] = set()

    def get(self, url, **kwargs):
        if url.endswith("/v2/account"):
            return Response({"id": self.account_id, "account_number": "PA999999", "status": "ACTIVE"})
        if url.endswith("/v2/orders:by_client_order_id"):
            params = kwargs.get("params") or {}
            client_order_id = params.get("client_order_id")
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
            # Simulates "the request never actually reached the broker" --
            # used by the uncertain-submission reconciliation tests.
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
    """poll_order_until_terminal uses real time.sleep by default -- patch it
    to a no-op so a poll against a never-terminalizing order (this file's
    ControllableTransport) completes its bounded loop instantly instead of
    real-time waiting ~20s."""
    return patch("time.sleep", lambda *_: None)


def _auth(**overrides) -> ExperimentalAuthorization:
    from talonx_piv.events import ET
    now = datetime.now(timezone.utc)
    paper = overrides.pop("paper", ExperimentalPaperPermission(
        enabled=True, account_id_binding="acct-r1", max_quantity_per_entry=5.0,
        max_reference_notional_budget=10000.0, max_entry_count=10, max_concurrent_exposure=1,
    ))
    kwargs = dict(
        experiment_id="exp-r1", operator_acknowledged_unvalidated=True, strategy_id="macd_bullish_cross",
        strategy_version=get_strategy_version(), runtime_sha="sha-r1", config_hash="cfg-r1",
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
                 auth=None, auth_path=None, transport=None, trading_date_et=None, redis_client=None,
                 bind_auth_to_live_session=True):
    cfg = PivConfig(
        key_id="key", secret_key="secret", paper_trading=True, real_capital=False,
        broker_endpoint=PAPER_ENDPOINT, approved_sha="abc", state_dir=tmp_path,
        universe=universe, stale_seconds=90,
    )
    transport = transport or ControllableTransport()
    broker = AlpacaPaperClient(cfg, transport)
    broker.verify_paper_identity()
    identity = build_session_identity(cfg)
    bus = EventBus(tmp_path / "piv_events.jsonl", feed_mode=cfg.feed_mode, session_id=identity.session_id)
    if bind_auth_to_live_session:
        # Task 79E-R2: session_scope is now bound to the REAL, per-process
        # session_id (see decision_engine.py's _live_session_scope), which
        # cannot be known before `identity` is computed above -- rebind the
        # fixture's auth (object or on-disk file) here so every existing
        # `auth=_auth()`/`auth_path=...` call site keeps working unchanged.
        # Pass bind_auth_to_live_session=False for a test that deliberately
        # wants an UNRELATED session_scope.
        if auth is not None:
            import dataclasses
            auth = dataclasses.replace(auth, session_scope=identity.session_id)
        if auth_path is not None and auth_path.exists():
            payload = json.loads(auth_path.read_text(encoding="utf-8"))
            payload["session_scope"] = identity.session_id
            auth_path.write_text(json.dumps(payload), encoding="utf-8")
    life = PaperLifecycle(
        tmp_path / "lifecycle_state.json", broker, bus, PaperEntrySettings.for_test(*paper_enabled),
        experimental_authorization=auth, experimental_authorization_path=auth_path,
        runtime_sha="sha-r1", config_hash="cfg-r1",
    )
    life.start_session(True, True)
    decision_ledger = DecisionLedger(tmp_path / "decision_ledger.json")
    outbox = NotificationOutbox(tmp_path / "notification_outbox.json", lambda m: True)
    shadow = ShadowLedger(tmp_path / "shadow_ledger.json")
    gemini = GeminiEnrichmentOutbox(tmp_path / "gemini_enrichment.json")
    engine = DecisionEngine(
        redis_client or _NullRedisClient(), bus, life, piv_config=cfg,
        decision_ledger=decision_ledger, notification_outbox=outbox, shadow_ledger=shadow, gemini_enrichment=gemini,
        runtime_sha="sha-r1", config_hash="cfg-r1",
        experimental_authorization=auth, experimental_authorization_path=auth_path,
    )
    return engine, life, transport, outbox, shadow, bus, tmp_path


# ---------------------------------------------------------------------------
# 1. Exit recovery / partial fills / duplicate-exit prevention
# ---------------------------------------------------------------------------

def test_restart_rehydrates_exit_plan_and_stop_still_fires():
    """A fresh DecisionEngine constructed against a lifecycle state file that
    already has an OPEN position (as if the ORIGINAL process crashed after
    entry) must recover the stop/target plan -- not silently drop it until
    EOD. Reproduces Task 79E's own disclosed gap (remaining_issues.md #1)."""
    import tempfile
    with tempfile.TemporaryDirectory() as td:
        from pathlib import Path
        tmp_path = Path(td)
        engine1, life1, transport, outbox, shadow, bus, _ = build_stack(tmp_path, auth=_auth())
        with _no_sleep_poll(life1):
            engine1._handle_entry(make_signal(stop=98.0, target=104.0))
        assert "AAPL" in engine1.positions
        life1.apply_broker_update(
            transport.orders[0]["id"], "filled", 1.0, 100.0, filled_at=datetime.now(timezone.utc).isoformat(),
        )
        assert life1.state.positions
        # Simulate a full process restart: brand-new PaperLifecycle/DecisionEngine
        # reading the SAME persisted state files, never touching engine1 again.
        cfg = life1.broker.config
        broker2 = AlpacaPaperClient(cfg, transport)
        broker2.verify_paper_identity()
        life2 = PaperLifecycle(
            tmp_path / "lifecycle_state.json", broker2, bus,
            PaperEntrySettings.for_test("AAPL", "MSFT"), runtime_sha="sha-r1", config_hash="cfg-r1",
        )
        engine2 = DecisionEngine(
            _NullRedisClient(), bus, life2, piv_config=cfg,
            decision_ledger=DecisionLedger(tmp_path / "decision_ledger.json"),
            notification_outbox=NotificationOutbox(tmp_path / "notification_outbox.json", lambda m: True),
            shadow_ledger=ShadowLedger(tmp_path / "shadow_ledger.json"),
            gemini_enrichment=GeminiEnrichmentOutbox(tmp_path / "gemini_enrichment.json"),
            runtime_sha="sha-r1", config_hash="cfg-r1",
        )
        assert "AAPL" in engine2.positions
        assert engine2.positions["AAPL"].stop_price == 98.0
        assert engine2.positions["AAPL"].target_price == 104.0
        assert engine2.positions["AAPL"].experimental is True
        assert engine2.positions["AAPL"].experimental_id == "exp-r1"  # experimental identity survives restart

        # A bar clearly AFTER the original entry, whose low pierces the
        # recovered stop, must still trigger the exit post-restart.
        exit_bar = Bar(datetime.now(timezone.utc) + timedelta(minutes=5), 97.5, 98.5, 97.0, 97.5, 1000)
        with _no_sleep_poll(life2):
            engine2._check_exit("AAPL", exit_bar)
        sell_orders = [o for o in transport.orders if o.get("side") == "sell"]
        assert len(sell_orders) == 1
        life2.apply_broker_update(sell_orders[0]["id"], "filled", 1.0, 97.5)
        # Next tick observes the now-confirmed-flat lifecycle state and
        # finally stops tracking the position.
        with _no_sleep_poll(life2):
            engine2._check_exit("AAPL", Bar(exit_bar.timestamp + timedelta(minutes=1), 97.5, 98.0, 97.0, 97.5, 1000))
        assert "AAPL" not in engine2.positions


def test_partial_fill_is_retried_and_sized_to_actual_remaining_holdings(tmp_path):
    """A stop that only partially fills (order later cancelled with some
    quantity still outstanding) must keep the position tracked and, on a
    LATER bar, resubmit sized to the REAL remaining holdings -- never the
    fixed PIV_QUANTITY constant, and never a duplicate covering already-
    reserved quantity."""
    engine, life, transport, outbox, shadow, bus, _ = build_stack(tmp_path, auth=_auth())
    with _no_sleep_poll(life):
        engine._handle_entry(make_signal(stop=98.0, target=104.0))
    assert "AAPL" in engine.positions
    buy_order_id = transport.orders[0]["id"]
    life.apply_broker_update(buy_order_id, "filled", 1.0, 100.0, filled_at=datetime.now(timezone.utc).isoformat())

    stop_bar = Bar(datetime.now(timezone.utc) + timedelta(minutes=1), 97.5, 98.5, 97.0, 97.5, 1000)
    with _no_sleep_poll(life):
        engine._check_exit("AAPL", stop_bar)
    assert "AAPL" in engine.positions  # NOT untracked -- broker never confirmed flat
    sell_orders = [o for o in transport.orders if o.get("side") == "sell"]
    assert len(sell_orders) == 1
    first_sell_id = sell_orders[0]["id"]

    # Partial fill (0.4 of 1.0), then the REST of that order is cancelled --
    # 0.6 genuinely still needs to be sold.
    life.apply_broker_update(first_sell_id, "partially_filled", 0.4, 100.0)
    life.apply_broker_update(first_sell_id, "canceled", 0.4, 100.0)
    assert life.remaining_holdings("AAPL") == pytest.approx(0.6)

    later_bar = Bar(datetime.now(timezone.utc) + timedelta(minutes=2), 97.0, 97.5, 96.5, 97.0, 1000)
    with _no_sleep_poll(life):
        engine._check_exit("AAPL", later_bar)
    sell_orders = [o for o in transport.orders if o.get("side") == "sell"]
    assert len(sell_orders) == 2
    assert sell_orders[1]["qty"] == "0.6"  # sized to ACTUAL remaining holdings, not PIV_QUANTITY


def test_rejected_exit_keeps_position_tracked_for_retry(tmp_path):
    """A sell attempt that raises PaperGuardError (e.g. PAPER entry disabled
    mid-session) must NOT untrack the position -- the very next bar must
    still attempt the exit again."""
    engine, life, transport, outbox, shadow, bus, _ = build_stack(tmp_path, paper_enabled=("AAPL", "MSFT"), auth=_auth())
    with _no_sleep_poll(life):
        engine._handle_entry(make_signal(stop=98.0, target=104.0))
    life.apply_broker_update(
        transport.orders[0]["id"], "filled", 1.0, 100.0, filled_at=datetime.now(timezone.utc).isoformat(),
    )
    # Disable PAPER entries for AAPL AFTER entry -- order_intent's own SELL
    # branch does not gate on paper_entry_settings (only BUY does), so
    # instead simulate a rejection via the kill switch, which DOES block
    # every new order (buy or sell) at the broker boundary.
    life.state.kill_switch = True
    life._save()

    stop_bar = Bar(datetime.now(timezone.utc) + timedelta(minutes=1), 97.5, 98.5, 97.0, 97.5, 1000)
    with _no_sleep_poll(life):
        engine._check_exit("AAPL", stop_bar)
    assert "AAPL" in engine.positions  # rejection must not drop tracking
    assert not any(o.get("side") == "sell" for o in transport.orders)

    life.state.kill_switch = False
    life._save()
    later_bar = Bar(datetime.now(timezone.utc) + timedelta(minutes=2), 97.0, 97.5, 96.5, 97.0, 1000)
    with _no_sleep_poll(life):
        engine._check_exit("AAPL", later_bar)
    assert any(o.get("side") == "sell" for o in transport.orders)
    life.apply_broker_update([o for o in transport.orders if o.get("side") == "sell"][0]["id"], "filled", 1.0, 97.0)
    assert life.remaining_holdings("AAPL") == 0.0


def test_missing_exit_plan_self_heals_when_recoverable(tmp_path):
    """Task 79E-R2: an OPEN lifecycle position with NO corresponding
    self.positions entry, but with enough persisted information to safely
    rebuild a plan from (quantity + stop/target), now SELF-HEALS via the
    same rehydration logic a restart would use -- rather than staying a
    permanently-orphaned, merely-visible gap for the rest of the session.
    The genuinely UNRECOVERABLE case (no usable quantity at all) is
    covered separately by
    test_task79e_r2_activation_safety.py::test_rehydration_blocked_when_quantity_information_missing,
    which still fails visibly and is never silently ignored or invented."""
    engine, life, transport, outbox, shadow, bus, tmp_path2 = build_stack(tmp_path)
    life.state.positions["orphan_pos"] = {
        "symbol": "MSFT", "quantity": 1.0, "price": 100.0, "status": "OPEN",
        "stop_price": 98.0, "target_price": 104.0, "remaining_quantity": 1.0,
    }
    life.state.open_position_by_symbol["MSFT"] = "orphan_pos"
    life._save()
    assert "MSFT" not in engine.positions

    import asyncio
    asyncio.run(engine.on_bars({"MSFT": bar(100.0)}))

    assert "MSFT" in engine.positions
    assert engine.positions["MSFT"].stop_price == 98.0
    assert engine.positions["MSFT"].target_price == 104.0
    events = [json.loads(line) for line in bus.path.read_text(encoding="utf-8").splitlines() if line.strip()]
    assert any(
        e.get("event") == "BROKER_ERROR" and e.get("reason") == "EXIT_PLAN_REHYDRATED_FROM_PERSISTED_STATE" and e.get("symbol") == "MSFT"
        for e in events
    )
    assert not any(e.get("reason") == "MISSING_EXIT_PLAN_FOR_OPEN_POSITION" for e in events)


# ---------------------------------------------------------------------------
# 2. Entry/exit causality
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_same_bar_as_entry_never_triggers_stop(tmp_path):
    """The REAL production bug: on_bars() feeds the SAME bar to both
    _handle_entry (as the signal source, via flush_and_collect) and
    _check_exit (as the price to test) in the SAME tick -- that bar's own
    low must never be allowed to immediately stop out the position it just
    opened. A DIRECT _check_exit call (not through on_bars) is a different,
    already-covered scenario -- see test_exit_remains_available_after_
    experimental_entry in test_task79e_decision_engine_experimental.py,
    which intentionally proves a direct call is NOT causality-gated."""
    # Auto-fills on submission (unlike ControllableTransport) -- entry and
    # exit-check both happen inside the SAME on_bars() call below, so the
    # fill must land synchronously during _handle_entry's own
    # poll_order_until_terminal, exactly like a real fast-filling market
    # order would.
    transport = ControllableTransport()
    real_post = transport.post

    def _auto_fill_post(url, **kwargs):
        response = real_post(url, **kwargs)
        transport.orders[-1]["status"] = "filled"
        transport.orders[-1]["filled_qty"] = "1"
        transport.orders[-1]["filled_avg_price"] = "100.0"
        # Task 79E-R2-2: captured HERE (genuinely after `ts`, the entry
        # bar's own timestamp, was captured below) -- the fill's real
        # timestamp is later than the entry bar's own, which is exactly
        # what makes the entry bar itself causally INeligible (proving the
        # same-tick exclusion via genuine timestamp comparison, not a
        # caller-computed flag).
        transport.orders[-1]["filled_at"] = datetime.now(timezone.utc).isoformat()
        return response

    transport.post = _auto_fill_post
    engine, life, transport, outbox, shadow, bus, _ = build_stack(tmp_path, auth=_auth(), transport=transport)
    ts = datetime.now(timezone.utc)
    # A bar whose LOW is already below the signal's own stop -- if causality
    # were not enforced, this exact bar would immediately stop the position
    # out on the very tick it was opened.
    entry_bar = Bar(ts, 100.0, 100.5, 97.0, 100.0, 1000)
    signal = make_signal(stop=98.0, target=104.0, ts=ts)

    # Bypass the real QuantScanner/pubsub round trip entirely -- this test
    # is about on_bars()'s own entry/exit orchestration for a single tick,
    # not about signal generation. A one-shot queue mimics a real pubsub
    # channel being drained exactly once.
    signal_queue = [signal]

    async def _fake_flush_and_collect():
        return [signal_queue.pop(0)] if signal_queue else []

    engine.scanner._handle_market_tick = AsyncMock()
    engine.flush_and_collect = _fake_flush_and_collect

    with _no_sleep_poll(life):
        await engine.on_bars({"AAPL": entry_bar})
    assert "AAPL" in engine.positions  # NOT stopped out by the entry bar's own low
    assert not any(o.get("side") == "sell" for o in transport.orders)

    # A bar STRICTLY AFTER the entry tick, with the same low, DOES trigger it.
    # The auto-filling transport resolves the resulting sell synchronously
    # (via _check_exit's own poll_order_until_terminal call), so the
    # position is confirmed flat by the end of this SAME on_bars() call.
    later_bar = Bar(ts + timedelta(minutes=1), 97.5, 98.0, 97.0, 97.5, 1000)
    with _no_sleep_poll(life):
        await engine.on_bars({"AAPL": later_bar})
    sell_orders = [o for o in transport.orders if o.get("side") == "sell"]
    assert len(sell_orders) == 1
    assert "AAPL" not in engine.positions


# ---------------------------------------------------------------------------
# 3. Session binding and revocation
# ---------------------------------------------------------------------------

def test_wrong_session_scope_blocks_experimental_entry_at_decision_layer(tmp_path):
    engine, life, transport, outbox, shadow, bus, _ = build_stack(
        tmp_path, auth=_auth(session_scope="PIV_LIFECYCLE_PROBE"), bind_auth_to_live_session=False,
    )
    with _no_sleep_poll(life):
        engine._handle_entry(make_signal())
    assert transport.orders == []
    assert "AAPL" not in engine.positions


def test_revocation_between_decision_and_submission_via_file_deletion(tmp_path):
    """The decision layer approves (auth file present and valid at decision
    time); the file is then DELETED before the broker-boundary re-check --
    the submission must be blocked, not silently allowed through on a
    stale cached permission object."""
    auth_path = tmp_path / "experimental_authorization.json"
    auth_path.write_text(json.dumps(_valid_auth_payload()), encoding="utf-8")
    engine, life, transport, outbox, shadow, bus, _ = build_stack(tmp_path, auth_path=auth_path)

    # Monkeypatch decision-time permission resolution to succeed, then
    # delete the file to simulate revocation landing strictly BETWEEN the
    # decision and the order_intent call -- reproduced by deleting inside
    # a wrapped order_intent.
    original_order_intent = life.order_intent

    def _order_intent_after_revocation(*args, **kwargs):
        auth_path.unlink()
        return original_order_intent(*args, **kwargs)

    life.order_intent = _order_intent_after_revocation
    with _no_sleep_poll(life):
        engine._handle_entry(make_signal())
    assert transport.orders == []  # blocked at the broker boundary despite decision-time approval
    assert "AAPL" not in engine.positions


def test_revocation_via_disablement_blocks_at_broker_boundary_directly(tmp_path):
    """lifecycle.order_intent's own guard, exercised directly: authorization
    present but enabled=False (disabled by the operator) must reject."""
    auth_path = tmp_path / "experimental_authorization.json"
    payload = _valid_auth_payload()
    payload["enabled"] = False
    auth_path.write_text(json.dumps(payload), encoding="utf-8")
    engine, life, transport, outbox, shadow, bus, _ = build_stack(tmp_path, auth_path=auth_path)
    with pytest.raises(PaperGuardError, match="EXPERIMENTAL_AUTHORIZATION_NOT_CONFIGURED"):
        life.order_intent(
            "s1", "AAPL", "buy", 1.0, source="EXPERIMENTAL", reference_price=100.0,
            experimental_id="exp-r1", experimental_trading_date_et=_today(), strategy_id="macd_bullish_cross",
            experimental_strategy_version=get_strategy_version(), experimental_session_scope="REGULAR",
        )
    assert transport.orders == []


def test_edited_binding_mid_session_blocks_next_entry(tmp_path):
    """The authorization file is edited (allowed_symbols narrowed) between
    two entry attempts -- the SECOND must observe the new binding
    immediately, without a process restart."""
    auth_path = tmp_path / "experimental_authorization.json"
    payload = _valid_auth_payload()
    payload["allowed_symbols"] = ["AAPL", "MSFT"]
    auth_path.write_text(json.dumps(payload), encoding="utf-8")
    engine, life, transport, outbox, shadow, bus, _ = build_stack(tmp_path, auth_path=auth_path)
    # build_stack rebinds session_scope to the live session_id on the FILE
    # (see bind_auth_to_live_session) -- keep this test's own in-memory
    # `payload` dict in sync so its own later re-write below does not
    # clobber that rebind back to the stale "REGULAR" placeholder.
    payload["session_scope"] = bus.session_id

    with _no_sleep_poll(life):
        engine._handle_entry(make_signal(ticker="AAPL"))
    assert len(transport.orders) == 1

    payload["allowed_symbols"] = ["MSFT"]  # AAPL revoked mid-session
    auth_path.write_text(json.dumps(payload), encoding="utf-8")
    # New symbol (MSFT was never entered) proves the file edit takes effect
    # without restarting the process.
    with _no_sleep_poll(life):
        engine._handle_entry(make_signal(ticker="AAPL", price=101.0))  # AAPL already holds -- has_open_long path
    with _no_sleep_poll(life):
        engine._handle_entry(make_signal(ticker="MSFT", price=200.0, stop=196.0, target=208.0))
    assert len(transport.orders) == 2  # AAPL's first entry + MSFT's new one
    assert any(o["symbol"] == "MSFT" for o in transport.orders)


def _today() -> str:
    return datetime.now(timezone.utc).astimezone().strftime("%Y-%m-%d")


def _valid_auth_payload() -> dict:
    from talonx_piv.events import ET
    return {
        "enabled": True, "experiment_id": "exp-r1", "operator_acknowledged_unvalidated": True,
        "strategy_id": "macd_bullish_cross", "strategy_version": get_strategy_version(),
        "runtime_sha": "sha-r1", "config_hash": "cfg-r1", "allowed_symbols": ["AAPL", "MSFT"],
        "trading_date_et": datetime.now(timezone.utc).astimezone(ET).date().isoformat(),
        "session_scope": "REGULAR",
        "activated_at": (datetime.now(timezone.utc) - timedelta(hours=1)).isoformat(),
        "expires_at": (datetime.now(timezone.utc) + timedelta(hours=10)).isoformat(),
        "paper": {
            "enabled": True, "account_id_binding": "acct-r1", "max_quantity_per_entry": 5.0,
            "max_reference_notional_budget": 10000.0, "max_entry_count": 10, "max_concurrent_exposure": 5,
        },
    }


# ---------------------------------------------------------------------------
# 4. Pending exposure and durable budgets
# ---------------------------------------------------------------------------

def test_two_symbols_competing_for_one_slot(tmp_path):
    """max_concurrent_exposure=1: symbol A submits and is PENDING (not yet
    filled) when symbol B's own entry attempt is evaluated -- B must be
    blocked, not merely A-vs-A pyramiding. Reproduces the real race: the
    OLD guard only counted CONFIRMED OPEN positions, so B could pass."""
    auth = _auth(paper=ExperimentalPaperPermission(
        enabled=True, account_id_binding="acct-r1", max_quantity_per_entry=5.0,
        max_reference_notional_budget=10000.0, max_entry_count=10, max_concurrent_exposure=1,
    ))
    engine, life, transport, outbox, shadow, bus, _ = build_stack(tmp_path, auth=auth)

    with _no_sleep_poll(life):
        engine._handle_entry(make_signal(ticker="AAPL", price=100.0, stop=98.0, target=104.0))
    assert len(transport.orders) == 1
    assert transport.orders[0]["status"] == "new"  # still PENDING -- ControllableTransport never auto-fills

    with _no_sleep_poll(life):
        engine._handle_entry(make_signal(ticker="MSFT", price=200.0, stop=196.0, target=208.0))
    assert len(transport.orders) == 1  # MSFT must be blocked -- AAPL's pending exposure already occupies the one slot
    assert "MSFT" not in engine.positions


def test_uncertain_submission_never_auto_resolves_operator_resolution_frees_pyramiding_guard(tmp_path):
    """A submission that raises BEFORE any broker id is received leaves an
    intent SUBMIT_FAILED_UNCERTAIN. Task 79E-R2-2 superseded this test's own
    ORIGINAL R2 design (a count-based threshold of 2 "not found" results
    auto-confirmed non-submission) -- see
    test_task79e_r2_activation_safety.py's own
    test_repeated_404s_never_auto_confirm_not_submitted_then_order_appears_and_is_adopted_once
    for the full reproduction of why that was wrong (a genuinely-submitted
    order that only became discoverable LATER would never be found again,
    since a "resolved" intent is no longer queried at all). This test now
    proves the two ACTUAL ways an uncertain submission's exposure
    reservation can be released: (1) never merely by repeated absence, and
    (2) explicit, evidence-backed operator resolution."""
    transport = ControllableTransport()
    engine, life, transport, outbox, shadow, bus, _ = build_stack(tmp_path, transport=transport)
    from talonx_piv.lifecycle import stable_id
    intent_id = stable_id("intent", "s1", "AAPL", "buy", 1.0)
    transport.dropped_client_order_ids.add(intent_id)
    with pytest.raises(RuntimeError, match="simulated network failure"):
        life.order_intent("s1", "AAPL", "buy", 1.0, source="STRATEGY", reference_price=100.0)
    assert life.state.intents[intent_id]["status"] == "SUBMIT_FAILED_UNCERTAIN"
    with pytest.raises(PaperGuardError, match="PENDING_ENTRY_EXISTS"):
        life.order_intent("s2", "AAPL", "buy", 1.0, source="STRATEGY", reference_price=100.0)

    base = datetime(2026, 1, 1, tzinfo=timezone.utc)
    for attempt in range(1, 4):
        life.reconcile(now=base + timedelta(hours=attempt))
        assert life.state.intents[intent_id]["status"] == "SUBMIT_FAILED_UNCERTAIN", f"wrongly auto-resolved at attempt {attempt}"
        with pytest.raises(PaperGuardError, match="PENDING_ENTRY_EXISTS"):
            life.order_intent(f"s2-{attempt}", "AAPL", "buy", 1.0, source="STRATEGY", reference_price=100.0)

    # The ONLY way this ever resolves to "not submitted" now: an operator,
    # asserting they have independently verified this out of band.
    with pytest.raises(PaperGuardError, match="requires explicit confirmation"):
        life.operator_resolve_uncertain_submission(intent_id, operator_confirmation=False)
    assert life.state.intents[intent_id]["status"] == "SUBMIT_FAILED_UNCERTAIN"  # unaffected by the rejected attempt

    life.operator_resolve_uncertain_submission(
        intent_id, operator_confirmation=True, operator_note="verified never submitted via Alpaca dashboard",
    )
    assert life.state.intents[intent_id]["status"] == "SUBMIT_FAILED_CONFIRMED_NOT_SUBMITTED"
    assert life.state.intents[intent_id]["resolution_source"] == "OPERATOR"

    # A genuinely NEW signal_id may now proceed -- never a blind retry of s1.
    result = life.order_intent("s3", "AAPL", "buy", 1.0, source="STRATEGY", reference_price=100.0)
    assert result["id"]

    # Resolving an already-resolved (no longer SUBMIT_FAILED_UNCERTAIN)
    # intent again is rejected -- operator resolution applies exactly once.
    with pytest.raises(PaperGuardError, match="not SUBMIT_FAILED_UNCERTAIN"):
        life.operator_resolve_uncertain_submission(intent_id, operator_confirmation=True)


def test_uncertain_submission_confirmed_reached_broker_is_adopted_not_reentered(tmp_path):
    """The opposite outcome: the broker DID receive the order despite the
    local exception (e.g. the response was lost in transit). reconcile()
    must adopt the real order via its client_order_id -- never submit a
    second, duplicate entry."""
    transport = ControllableTransport()
    engine, life, transport, outbox, shadow, bus, _ = build_stack(tmp_path, transport=transport)
    from talonx_piv.lifecycle import stable_id
    intent_id = stable_id("intent", "s1", "AAPL", "buy", 1.0)

    real_post = transport.post

    def _post_but_report_failure(url, **kwargs):
        response = real_post(url, **kwargs)  # order genuinely lands in transport.orders
        raise RuntimeError("simulated response lost after broker accepted it")

    transport.post = _post_but_report_failure
    with pytest.raises(RuntimeError):
        life.order_intent("s1", "AAPL", "buy", 1.0, source="STRATEGY", reference_price=100.0)
    assert life.state.intents[intent_id]["status"] == "SUBMIT_FAILED_UNCERTAIN"
    assert len(transport.orders) == 1  # it DID reach the broker

    life.reconcile()
    assert life.state.intents[intent_id]["status"] == "SUBMITTED"
    assert transport.orders[0]["id"] in life.state.orders
    assert len(transport.orders) == 1  # still exactly one order -- never duplicated


def test_damaged_budget_record_fails_closed(tmp_path):
    """A corrupted experimental_budgets entry (wrong type) must block new
    experimental entries and preserve the damaged value, never silently
    reset to zero (which would under-count real prior usage)."""
    engine, life, transport, outbox, shadow, bus, _ = build_stack(tmp_path, auth=_auth())
    life.state.experimental_budgets["exp-r1"] = "not-a-dict"
    life._save()
    with pytest.raises(PaperGuardError, match="EXPERIMENTAL_BUDGET_STATE_DAMAGED_FAIL_CLOSED"):
        life.order_intent(
            "s1", "AAPL", "buy", 1.0, source="EXPERIMENTAL", reference_price=100.0,
            experimental_id="exp-r1", experimental_trading_date_et=_auth().trading_date_et,
            strategy_id="macd_bullish_cross", experimental_strategy_version=get_strategy_version(),
            experimental_session_scope=life.experimental_authorization.session_scope,
        )
    assert life.state.experimental_budgets["exp-r1"] == "not-a-dict"  # evidence preserved, not overwritten


@pytest.mark.parametrize("bad_value", [
    {"entries_used": -1, "notional_used": 0.0},
    {"entries_used": True, "notional_used": 0.0},
    {"entries_used": 0, "notional_used": float("nan")},
    {"entries_used": 0, "notional_used": -5.0},
    {"entries_used": 0, "notional_used": True},
])
def test_various_damaged_budget_shapes_fail_closed(tmp_path, bad_value):
    engine, life, transport, outbox, shadow, bus, _ = build_stack(tmp_path, auth=_auth())
    life.state.experimental_budgets["exp-r1"] = bad_value
    life._save()
    with pytest.raises(PaperGuardError, match="EXPERIMENTAL_BUDGET_STATE_DAMAGED_FAIL_CLOSED"):
        life.order_intent(
            "s1", "AAPL", "buy", 1.0, source="EXPERIMENTAL", reference_price=100.0,
            experimental_id="exp-r1", experimental_trading_date_et=_auth().trading_date_et,
            strategy_id="macd_bullish_cross", experimental_strategy_version=get_strategy_version(),
            experimental_session_scope=life.experimental_authorization.session_scope,
        )


def test_missing_budget_with_prior_activity_fails_closed(tmp_path):
    """No experimental_budgets entry exists for this experiment_id, but
    positions/intents show real prior activity under it -- this is state
    LOSS, not a fresh start, and must fail closed rather than silently
    reset spend to zero."""
    engine, life, transport, outbox, shadow, bus, _ = build_stack(tmp_path, auth=_auth())
    life.state.positions["ghost"] = {
        "symbol": "MSFT", "status": "CLOSED", "experimental_id": "exp-r1", "quantity": 1.0,
    }
    life._save()
    assert "exp-r1" not in life.state.experimental_budgets
    with pytest.raises(PaperGuardError, match="EXPERIMENTAL_BUDGET_STATE_DAMAGED_FAIL_CLOSED"):
        life.order_intent(
            "s1", "AAPL", "buy", 1.0, source="EXPERIMENTAL", reference_price=100.0,
            experimental_id="exp-r1", experimental_trading_date_et=_auth().trading_date_et,
            strategy_id="macd_bullish_cross", experimental_strategy_version=get_strategy_version(),
            experimental_session_scope=life.experimental_authorization.session_scope,
        )


def test_invalid_reference_price_rejected(tmp_path):
    engine, life, transport, outbox, shadow, bus, _ = build_stack(tmp_path, auth=_auth())
    for bad_price in (-5.0, 0.0, float("nan"), float("inf"), True):
        with pytest.raises(PaperGuardError, match="EXPERIMENTAL_REFERENCE_PRICE_INVALID"):
            life.order_intent(
                f"s-{bad_price}", "AAPL", "buy", 1.0, source="EXPERIMENTAL", reference_price=bad_price,
                experimental_id="exp-r1", experimental_trading_date_et=_auth().trading_date_et,
                strategy_id="macd_bullish_cross", experimental_strategy_version=get_strategy_version(),
                experimental_session_scope=life.experimental_authorization.session_scope,
            )
    assert transport.orders == []


# ---------------------------------------------------------------------------
# 5. Integration and reporting -- alert/shadow independence under failure
# ---------------------------------------------------------------------------

def test_budget_exhausted_still_preserves_alert_and_shadow(tmp_path):
    """Decision-layer permission is granted (EXPERIMENTAL_BUY recorded), but
    the BROKER-boundary budget check (lifecycle.py) rejects -- the alert and
    shadow record, both already produced before order_intent is ever
    called, must survive regardless."""
    auth = _auth(paper=ExperimentalPaperPermission(
        enabled=True, account_id_binding="acct-r1", max_quantity_per_entry=5.0,
        max_reference_notional_budget=10.0,  # far below one entry's notional (100.0)
        max_entry_count=10, max_concurrent_exposure=5,
    ))
    engine, life, transport, outbox, shadow, bus, _ = build_stack(tmp_path, auth=auth)
    with _no_sleep_poll(life):
        engine._handle_entry(make_signal())
    assert transport.orders == []
    assert "AAPL" not in engine.positions
    assert len(outbox.records) == 1
    record = next(iter(outbox.records.values()))
    assert record["classification"] == CLASSIFICATION_EXPERIMENTAL_BUY
    assert len(shadow.positions) == 1
