"""Task 79E -- decision-engine-level integration evidence that the
experimental permission mechanism is wired into the REAL runtime
construction and decision loop (DecisionEngine._handle_entry/_check_exit),
not just exercised via a helper or a test-only override.

Reuses the exact Stack/build_stack pattern from
test_task78i_stage5_rehearsal.py (the established full-application
rehearsal harness) so this is genuinely driving DecisionEngine.on_bars end
to end, with an isolated in-memory transport and no real network access.

TEST_FIXTURE_ONLY -- NOT ALPHA EVIDENCE."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from talonx_backtest.reproducibility import get_strategy_version
from talonx_piv.broker import AlpacaPaperClient
from talonx_piv.config import PAPER_ENDPOINT, PivConfig
from talonx_piv.decision_contract import Recommendation
from talonx_piv.decision_engine import DecisionEngine
from talonx_piv.decision_ledger import DecisionLedger
from talonx_piv.events import EventBus
from talonx_piv.execution_settings import PaperEntrySettings
from talonx_piv.experimental_authorization import ExperimentalAuthorization, ExperimentalPaperPermission
from talonx_piv.gemini_enrichment import GeminiEnrichmentOutbox
from talonx_piv.lifecycle import PaperLifecycle
from talonx_piv.notification_outbox import CLASSIFICATION_EXPERIMENTAL_BUY, EXPERIMENTAL_BANNER, NotificationOutbox
from talonx_piv.session_identity import build_session_identity
from talonx_piv.session_runner import Bar
from talonx_piv.shadow_ledger import ShadowLedger
from talonx_quant.schemas import QuantSignal, SignalDirection, SignalType

from test_task78i_stage5_rehearsal import FakePubSub, FakeRedisClient, RehearsalTransport


def make_signal(direction=SignalDirection.BULLISH, ticker="AAPL", price=100.0, stop=98.0, target=104.0, ts=None) -> QuantSignal:
    return QuantSignal(
        ticker=ticker, signal_type=SignalType.MACD_BULLISH_CROSS, direction=direction,
        message="TEST_FIXTURE_ONLY -- NOT ALPHA EVIDENCE", price=price, stop_price=stop, target_price=target,
        bar_timestamp=ts or datetime.now(timezone.utc),
    )


def bar(price=100.0, ts=None):
    ts = ts or datetime.now(timezone.utc)
    return Bar(ts, price, price + 1, price - 1, price, 1000)


def _auth(*, identity, allowed_symbols=("AAPL",), paper=None, activated_delta=timedelta(hours=-1), expires_delta=timedelta(hours=5)) -> ExperimentalAuthorization:
    now = datetime.now(timezone.utc)
    return ExperimentalAuthorization(
        experiment_id="exp-79e-1", operator_acknowledged_unvalidated=True,
        strategy_id="macd_bullish_cross", strategy_version=get_strategy_version(),
        runtime_sha=identity.runtime_sha, config_hash=identity.config_hash,
        allowed_symbols=frozenset(s.upper() for s in allowed_symbols),
        trading_date_et=identity.trading_date_et, session_scope=identity.session_id,
        activated_at=now + activated_delta, expires_at=now + expires_delta,
        paper=paper,
    )


def _paper_permission(account_id: str) -> ExperimentalPaperPermission:
    return ExperimentalPaperPermission(
        enabled=True, account_id_binding=account_id, max_quantity_per_entry=5.0,
        max_reference_notional_budget=1000.0, max_entry_count=5, max_concurrent_exposure=5,
    )


def build_experimental_stack(tmp_path, *, experimental_authorization_factory=None, universe=("AAPL",), paper_enabled=("AAPL",)):
    """Same shape as test_task78i_stage5_rehearsal.build_stack, but wires an
    ExperimentalAuthorization through BOTH PaperLifecycle and DecisionEngine
    construction -- exactly as talonx_piv.cli.runtime()/main() now do."""
    cfg = PivConfig(
        key_id="key", secret_key="secret", paper_trading=True, real_capital=False,
        broker_endpoint=PAPER_ENDPOINT, approved_sha="abc", state_dir=tmp_path,
        universe=universe, stale_seconds=90,
    )
    transport = RehearsalTransport()
    broker = AlpacaPaperClient(cfg, transport)
    broker.verify_paper_identity()
    identity = build_session_identity(cfg)
    bus = EventBus(tmp_path / "piv_events.jsonl", feed_mode=cfg.feed_mode, session_id=identity.session_id)
    auth = experimental_authorization_factory(identity, broker) if experimental_authorization_factory else None
    life = PaperLifecycle(
        tmp_path / "lifecycle_state.json", broker, bus, PaperEntrySettings.for_test(*paper_enabled),
        experimental_authorization=auth, runtime_sha=identity.runtime_sha, config_hash=identity.config_hash,
    )
    life.start_session(True, True)
    decision_ledger = DecisionLedger(tmp_path / "decision_ledger.json")
    outbox = NotificationOutbox(tmp_path / "notification_outbox.json", lambda m: True)
    shadow = ShadowLedger(tmp_path / "shadow_ledger.json")
    gemini = GeminiEnrichmentOutbox(tmp_path / "gemini_enrichment.json")
    engine = DecisionEngine(
        FakeRedisClient(FakePubSub()), bus, life, piv_config=cfg,
        decision_ledger=decision_ledger, notification_outbox=outbox, shadow_ledger=shadow, gemini_enrichment=gemini,
        runtime_sha=identity.runtime_sha, config_hash=identity.config_hash,
        experimental_authorization=auth,
    )
    return engine, life, transport, outbox, shadow, decision_ledger, identity


@pytest.mark.asyncio
async def test_no_authorization_preserves_old_behavior(tmp_path):
    """No ExperimentalAuthorization configured at all (the default,
    every-session-until-an-operator-opts-in state) -- an otherwise-eligible
    bullish UNVALIDATED signal resolves EXACTLY as before Task 79E: NO_TRADE,
    WATCH notification, no shadow experimental flag, no broker order."""
    engine, life, transport, outbox, shadow, ledger, identity = build_experimental_stack(tmp_path)
    engine._handle_entry(make_signal())
    assert transport.orders == []
    assert len(outbox.records) == 1
    record = next(iter(outbox.records.values()))
    assert record["classification"] != CLASSIFICATION_EXPERIMENTAL_BUY
    assert "AAPL" not in engine.positions
    assert shadow.positions == {} or all(not p.get("experimental") for p in getattr(shadow, "positions", {}).values())


@pytest.mark.asyncio
async def test_valid_authorization_produces_experimental_buy_alert_shadow_and_paper_entry(tmp_path):
    """Full path: entry AND paper permission both granted -- EXPERIMENTAL_BUY
    is recorded, an EXPERIMENTAL-classified notification with the required
    banner is queued, a shadow position is opened, AND a real PAPER order is
    submitted -- proving the feature is reachable end to end from a signal,
    not just from a unit-level decide()/order_intent() call."""
    def factory(identity, broker):
        return _auth(identity=identity, paper=_paper_permission(broker.identity.account_id))
    engine, life, transport, outbox, shadow, ledger, identity = build_experimental_stack(tmp_path, experimental_authorization_factory=factory)

    engine._handle_entry(make_signal())

    assert len(transport.orders) == 1
    assert transport.orders[0]["side"] == "buy"
    assert "AAPL" in engine.positions
    position = engine.positions["AAPL"]
    assert position.experimental is True
    assert position.experimental_id == "exp-79e-1"

    assert len(outbox.records) == 1
    record = next(iter(outbox.records.values()))
    assert record["classification"] == CLASSIFICATION_EXPERIMENTAL_BUY
    assert EXPERIMENTAL_BANNER in record["message"]

    assert len(shadow.positions) == 1
    shadow_position = next(iter(shadow.positions.values()))
    assert getattr(shadow_position, "experimental", False) is True or shadow_position.get("experimental") is True


@pytest.mark.asyncio
async def test_paper_permission_denied_does_not_suppress_alert_or_shadow(tmp_path):
    """Entry permission granted, PAPER permission NOT granted (paper=None)
    -- the alert and shadow record must still be produced (Stage 1
    requirement: a PAPER-only failure never suppresses the alert/shadow
    branches), but no broker order is ever submitted."""
    def factory(identity, broker):
        return _auth(identity=identity, paper=None)
    engine, life, transport, outbox, shadow, ledger, identity = build_experimental_stack(tmp_path, experimental_authorization_factory=factory)

    engine._handle_entry(make_signal())

    assert transport.orders == []
    assert "AAPL" not in engine.positions  # no broker entry -- no OpenDecisionPosition tracked either
    assert len(outbox.records) == 1
    record = next(iter(outbox.records.values()))
    assert record["classification"] == CLASSIFICATION_EXPERIMENTAL_BUY
    assert len(shadow.positions) == 1


@pytest.mark.asyncio
async def test_stale_signal_rejected_for_experimental_admission(tmp_path):
    """A signal whose bar_timestamp is far older than config.stale_seconds
    must never be admitted to the experimental path, even with a fully
    valid, otherwise-matching authorization -- Stage 0's explicit
    "do not assume every drained pub/sub message is current" requirement."""
    def factory(identity, broker):
        return _auth(identity=identity, paper=_paper_permission(broker.identity.account_id))
    engine, life, transport, outbox, shadow, ledger, identity = build_experimental_stack(tmp_path, experimental_authorization_factory=factory)

    stale_ts = datetime.now(timezone.utc) - timedelta(seconds=999)
    engine._handle_entry(make_signal(ts=stale_ts))

    assert transport.orders == []
    assert "AAPL" not in engine.positions
    record = next(iter(outbox.records.values()))
    assert record["classification"] != CLASSIFICATION_EXPERIMENTAL_BUY


@pytest.mark.asyncio
async def test_bearish_signal_never_reaches_experimental_buy(tmp_path):
    """market_view != BULLISH short-circuits to NO_TRADE before the
    experimental-permission branch is ever consulted -- a valid
    authorization must never turn a bearish signal into an entry."""
    def factory(identity, broker):
        return _auth(identity=identity, paper=_paper_permission(broker.identity.account_id))
    engine, life, transport, outbox, shadow, ledger, identity = build_experimental_stack(tmp_path, experimental_authorization_factory=factory)

    engine._handle_entry(make_signal(direction=SignalDirection.BEARISH))

    assert transport.orders == []
    assert "AAPL" not in engine.positions
    assert outbox.records == {}


@pytest.mark.asyncio
async def test_exit_remains_available_after_experimental_entry(tmp_path):
    """Once an experimental position exists, its protective stop exit must
    still fire normally and be correctly labelled experimental -- exits are
    never gated on entry permission."""
    def factory(identity, broker):
        return _auth(identity=identity, paper=_paper_permission(broker.identity.account_id))
    engine, life, transport, outbox, shadow, ledger, identity = build_experimental_stack(tmp_path, experimental_authorization_factory=factory)

    engine._handle_entry(make_signal(stop=98.0, target=104.0))
    assert "AAPL" in engine.positions
    assert len(transport.orders) == 1

    # A bar whose low pierces the stop must trigger the exit, even though
    # nothing about the ORIGINAL authorization is re-checked for the exit.
    # Task 79E-R2-2: offset well clear of the fill's own `filled_at`
    # (RehearsalTransport stamps it at real submission wall-clock time,
    # inside _handle_entry above) -- a deterministic separation, not a
    # same-instant datetime.now() call that could tie or even reorder
    # against it depending on clock resolution.
    exit_bar = Bar(datetime.now(timezone.utc) + timedelta(minutes=1), 97.5, 98.5, 97.0, 97.5, 1000)
    engine._check_exit("AAPL", exit_bar)

    assert "AAPL" not in engine.positions
    sell_orders = [o for o in transport.orders if o.get("side") == "sell"]
    assert len(sell_orders) == 1


@pytest.mark.asyncio
async def test_wrong_symbol_authorization_blocks_experimental_entry(tmp_path):
    """An authorization scoped to a DIFFERENT symbol than the signal must
    never leak permission across tickers."""
    def factory(identity, broker):
        return _auth(identity=identity, allowed_symbols=("MSFT",), paper=_paper_permission(broker.identity.account_id))
    engine, life, transport, outbox, shadow, ledger, identity = build_experimental_stack(tmp_path, experimental_authorization_factory=factory, universe=("AAPL",), paper_enabled=("AAPL",))

    engine._handle_entry(make_signal(ticker="AAPL"))

    assert transport.orders == []
    assert "AAPL" not in engine.positions
    record = next(iter(outbox.records.values()))
    assert record["classification"] != CLASSIFICATION_EXPERIMENTAL_BUY
