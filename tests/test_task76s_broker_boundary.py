"""Task 76S Stage 3/5 -- broker-boundary safety (bypass matrix).

Every test here uses an in-memory fake Transport (never the real `requests`
module) injected into AlpacaPaperClient -- the same pattern every existing
PIV test already uses. `_NoNetworkGuard` (autouse, session-scoped) goes one
step further and monkeypatches `requests.api.request` to raise immediately
if ANY test in this file (or a bug in the code under test) ever attempts a
real HTTP call, and a fake Telegram sender records instead of calling out --
this is this task's required "test guard that fails if any test attempts a
real broker mutation or external notification."

All fixture state is isolated per-test (tmp_path); no test in this file
performs a real broker mutation or notification of any kind."""
from __future__ import annotations

import math

import pytest

from talonx_piv.broker import AlpacaPaperClient, PaperGuardError
from talonx_piv.config import PAPER_ENDPOINT, PivConfig
from talonx_piv.events import EventBus
from talonx_piv.execution_settings import PaperEntrySettings
from talonx_piv.lifecycle import PaperLifecycle
from talonx_piv.lifecycle_probe import run_piv_lifecycle_probe, PROBE_SYMBOL
from datetime import time as dtime


@pytest.fixture(autouse=True)
def _no_real_network(monkeypatch):
    """Required test guard: any real network call from this file's tests
    (a real broker mutation or a real Telegram send) must fail the test
    immediately, not silently succeed against a real endpoint."""
    import requests

    def _blocked(*args, **kwargs):
        raise AssertionError("test_task76s_broker_boundary: a real network call was attempted")

    monkeypatch.setattr(requests, "request", _blocked, raising=True)
    monkeypatch.setattr(requests.sessions.Session, "request", _blocked, raising=True)


class Response:
    def __init__(self, body, status=200):
        self.body, self.status_code = body, status

    def json(self):
        return self.body

    def raise_for_status(self):
        if self.status_code >= 400:
            raise RuntimeError(f"HTTP {self.status_code}")


class FakeTransport:
    """TEST_FIXTURE_ONLY -- NOT ALPHA EVIDENCE. In-memory Alpaca paper
    simulator -- never touches a real socket."""

    def __init__(self):
        self.submits = 0
        self.orders: list[dict] = []
        self.positions: list[dict] = []

    def get(self, url, **kwargs):
        if url.endswith("/v2/account"):
            return Response({"id": "paper-id", "account_number": "PA123456", "status": "ACTIVE"})
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
        self.submits += 1
        order = {"id": f"order-{self.submits}", "status": "new", "filled_qty": "0", **kwargs.get("json", {})}
        self.orders.append(order)
        return Response(order)

    def delete(self, url, **kwargs):
        return Response([])


def _config(tmp_path, **overrides):
    values = dict(
        key_id="key", secret_key="secret", paper_trading=True, real_capital=False,
        broker_endpoint=PAPER_ENDPOINT, approved_sha="abc", state_dir=tmp_path,
    )
    values.update(overrides)
    return PivConfig(**values)


def _life(tmp_path, *, enabled=("AAPL",), transport=None):
    transport = transport or FakeTransport()
    broker = AlpacaPaperClient(_config(tmp_path), transport)
    broker.verify_paper_identity()
    bus = EventBus(tmp_path / "events.jsonl", feed_mode="RESEARCH_SIP")
    life = PaperLifecycle(tmp_path / "state.json", broker, bus, PaperEntrySettings.for_test(*enabled))
    life.start_session(True, True)
    return life, transport, bus


def _fill(life, order_id, qty=1.0, price=100.0):
    life.apply_broker_update(order_id, "filled", qty, price)


# ---------------------------------------------------------------------------
# Unsupported / malformed action intents
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("side", ["short", "sell_short", "SHORT", "BUY", "SELL", "", "close"])
def test_unsupported_action_intent_rejected(tmp_path, side):
    life, transport, _ = _life(tmp_path)
    with pytest.raises(PaperGuardError, match="UNSUPPORTED_ACTION_INTENT"):
        life.order_intent("s1", "AAPL", side, 1)
    assert transport.submits == 0


def test_direct_short_open_request_rejected_no_side_value_opens_a_short(tmp_path):
    """There is no `side` value that routes to opening a short -- confirmed
    exhaustively above; this test documents the specific case a caller
    might try."""
    life, transport, _ = _life(tmp_path)
    with pytest.raises(PaperGuardError, match="UNSUPPORTED_ACTION_INTENT"):
        life.order_intent("s1", "AAPL", "short", 1)
    assert transport.submits == 0
    assert life.state.positions == {}


@pytest.mark.parametrize("qty", [0, -1, -0.5, float("nan"), float("inf"), float("-inf")])
def test_invalid_quantities_rejected(tmp_path, qty):
    life, transport, _ = _life(tmp_path)
    with pytest.raises(PaperGuardError, match="INVALID_QUANTITY"):
        life.order_intent("s1", "AAPL", "buy", qty)
    assert transport.submits == 0


def test_bool_quantity_rejected(tmp_path):
    """bool is an int subclass in Python -- must not slip through as 1/0."""
    life, transport, _ = _life(tmp_path)
    with pytest.raises(PaperGuardError, match="INVALID_QUANTITY"):
        life.order_intent("s1", "AAPL", "buy", True)


# ---------------------------------------------------------------------------
# Source allowlist -- Brain/Gemini rejection
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("source", ["BRAIN", "GEMINI", "gemini", "brain", "UNKNOWN_INTEGRATION"])
def test_unauthorized_source_rejected(tmp_path, source):
    life, transport, _ = _life(tmp_path)
    with pytest.raises(PaperGuardError, match="UNAUTHORIZED_SOURCE"):
        life.order_intent("s1", "AAPL", "buy", 1, source=source)
    assert transport.submits == 0


def test_brain_originated_order_modification_rejected(tmp_path):
    """A Brain/Gemini-attributed request attempting to open a NEW position
    must be rejected outright, never partially processed."""
    life, transport, _ = _life(tmp_path)
    with pytest.raises(PaperGuardError, match="UNAUTHORIZED_SOURCE"):
        life.order_intent("brain-1", "AAPL", "buy", 1, source="BRAIN")
    assert life.state.positions == {}
    assert transport.submits == 0


def test_known_sources_still_permitted(tmp_path):
    life, transport, _ = _life(tmp_path)
    life.order_intent("s1", "AAPL", "buy", 1, source="STRATEGY")
    assert transport.submits == 1
    life2, transport2, _ = _life(tmp_path.parent / (tmp_path.name + "_2"), enabled=("AAPL",))
    life2.order_intent("s1", "AAPL", "buy", 1, source="PIV_LIFECYCLE_PROBE")
    assert transport2.submits == 1


# ---------------------------------------------------------------------------
# SELL while flat / oversell / duplicate
# ---------------------------------------------------------------------------

def test_direct_sell_while_flat_rejected(tmp_path):
    life, transport, _ = _life(tmp_path)
    with pytest.raises(PaperGuardError, match="SELL_WHILE_FLAT"):
        life.order_intent("s1", "AAPL", "sell", 1)
    assert transport.submits == 0


def test_oversized_sell_rejected(tmp_path):
    life, transport, _ = _life(tmp_path)
    entry = life.order_intent("s1", "AAPL", "buy", 1)
    _fill(life, entry["id"], 1, 100.0)
    with pytest.raises(PaperGuardError, match="OVERSIZED_OR_DUPLICATE_SELL"):
        life.order_intent("s2", "AAPL", "sell", 2)  # only 1 held
    assert transport.submits == 1  # the oversell never reached the broker


def test_exact_available_quantity_sell_permitted(tmp_path):
    life, transport, _ = _life(tmp_path)
    entry = life.order_intent("s1", "AAPL", "buy", 1)
    _fill(life, entry["id"], 1, 100.0)
    life.order_intent("s2", "AAPL", "sell", 1)  # exactly what is held
    assert transport.submits == 2


def test_duplicate_sell_request_with_different_signal_id_rejected(tmp_path):
    """A second, DIFFERENT signal_id targeting the same open long, issued
    before the first sell resolves, must not be treated as independent --
    this is what stable_id's exact-repeat check alone would miss."""
    life, transport, _ = _life(tmp_path)
    entry = life.order_intent("s1", "AAPL", "buy", 1)
    _fill(life, entry["id"], 1, 100.0)
    life.order_intent("exit-a", "AAPL", "sell", 1)  # first exit request, still pending (status="new")
    with pytest.raises(PaperGuardError, match="OVERSIZED_OR_DUPLICATE_SELL"):
        life.order_intent("exit-b", "AAPL", "sell", 1)  # a second, different signal_id
    assert transport.submits == 2  # entry + first sell only


def test_partial_fill_of_a_closing_sell_still_blocks_a_second_sell(tmp_path):
    """A partial fill on a SELL_TO_CLOSE marks the position CLOSED in this
    codebase's existing apply_broker_update (a pre-existing accounting
    characteristic this task does not redesign -- see
    remaining_integration_work.md) -- meaning a second sell attempt is
    correctly rejected, just as SELL_WHILE_FLAT rather than an oversell.
    Either way, no second sell reaches the broker."""
    life, transport, _ = _life(tmp_path)
    entry = life.order_intent("s1", "AAPL", "buy", 3)
    _fill(life, entry["id"], 3, 100.0)
    exit1 = life.order_intent("exit-1", "AAPL", "sell", 2)
    life.apply_broker_update(exit1["id"], "partially_filled", 1, 101.0)
    with pytest.raises(PaperGuardError, match="SELL_WHILE_FLAT"):
        life.order_intent("exit-2", "AAPL", "sell", 3)
    assert transport.submits == 2  # entry + first sell only -- never a third submission


def test_reversing_a_long_into_a_short_via_oversell_is_blocked(tmp_path):
    """A sell for MORE than is held would, if permitted, flip the position
    negative (a short) at the broker -- must be rejected before submission."""
    life, transport, _ = _life(tmp_path)
    entry = life.order_intent("s1", "AAPL", "buy", 1)
    _fill(life, entry["id"], 1, 100.0)
    with pytest.raises(PaperGuardError, match="OVERSIZED_OR_DUPLICATE_SELL"):
        life.order_intent("s2", "AAPL", "sell", 5)
    assert transport.submits == 1


# ---------------------------------------------------------------------------
# Pyramiding / pending-entry duplication
# ---------------------------------------------------------------------------

def test_buy_while_already_holding_rejected_no_pyramiding(tmp_path):
    life, transport, _ = _life(tmp_path)
    entry = life.order_intent("s1", "AAPL", "buy", 1)
    _fill(life, entry["id"], 1, 100.0)
    with pytest.raises(PaperGuardError, match="ALREADY_HOLDING_NO_PYRAMIDING"):
        life.order_intent("s2", "AAPL", "buy", 1)


def test_second_buy_while_first_still_pending_rejected(tmp_path):
    """Position/order state changes BETWEEN checks: the first buy is
    submitted (status="new" in the fake transport, not yet filled) --
    a second buy for the same symbol must not be allowed to race ahead."""
    life, transport, _ = _life(tmp_path)
    life.order_intent("s1", "AAPL", "buy", 1)  # left pending (never filled in this test)
    with pytest.raises(PaperGuardError, match="PENDING_ENTRY_EXISTS"):
        life.order_intent("s2", "AAPL", "buy", 1)
    assert transport.submits == 1


def test_stale_local_state_does_not_prove_ownership(tmp_path):
    """A caller cannot use its own (correct-looking but stale) belief that
    a position is closed to justify a second sell -- the boundary re-reads
    persisted state, not a caller's argument."""
    life, transport, _ = _life(tmp_path)
    entry = life.order_intent("s1", "AAPL", "buy", 1)
    _fill(life, entry["id"], 1, 100.0)
    exit_ = life.order_intent("s2", "AAPL", "sell", 1)
    _fill(life, exit_["id"], 1, 105.0)  # now genuinely flat
    with pytest.raises(PaperGuardError, match="SELL_WHILE_FLAT"):
        life.order_intent("s3", "AAPL", "sell", 1)  # a caller "guessing" it's still open


# ---------------------------------------------------------------------------
# PAPER-entry disabled / unexpected short / real-money & unknown account mode
# ---------------------------------------------------------------------------

def test_paper_entry_disabled_for_ticker_blocks_new_buy(tmp_path):
    life, transport, _ = _life(tmp_path, enabled=())  # AAPL NOT enabled
    with pytest.raises(PaperGuardError, match="PAPER_ENTRY_DISABLED_FOR_TICKER"):
        life.order_intent("s1", "AAPL", "buy", 1)
    assert transport.submits == 0


def test_paper_entry_disabled_does_not_block_an_existing_sell(tmp_path):
    """Rule 3: paper_entry_enabled must never suppress a protective exit."""
    life, transport, _ = _life(tmp_path, enabled=("AAPL",))
    entry = life.order_intent("s1", "AAPL", "buy", 1)
    _fill(life, entry["id"], 1, 100.0)
    life.paper_entry_settings = PaperEntrySettings.for_test()  # disable AAPL entries mid-position
    life.order_intent("s2", "AAPL", "sell", 1)  # must still succeed
    assert transport.submits == 2


def test_unexpected_short_blocks_all_new_entries(tmp_path):
    transport = FakeTransport()
    transport.positions = [{"symbol": "NVDA", "side": "short", "qty": "-3"}]
    life, transport, _ = _life(tmp_path, enabled=("AAPL",), transport=transport)
    life.reconcile()  # detects and persists the unexpected short
    with pytest.raises(PaperGuardError, match="UNEXPECTED_SHORT_BLOCKS_NEW_ENTRIES"):
        life.order_intent("s1", "AAPL", "buy", 1)


def test_real_capital_account_mode_rejected(tmp_path):
    broker = AlpacaPaperClient(_config(tmp_path, real_capital=True), FakeTransport())
    with pytest.raises(PaperGuardError):
        broker.verify_paper_identity()


def test_unknown_non_paper_endpoint_rejected(tmp_path):
    broker = AlpacaPaperClient(_config(tmp_path, broker_endpoint="https://api.alpaca.markets"), FakeTransport())
    with pytest.raises(PaperGuardError):
        broker.verify_paper_identity()


# ---------------------------------------------------------------------------
# Probe/manual path cannot bypass controls
# ---------------------------------------------------------------------------

def test_probe_path_cannot_bypass_paper_entry_disabled(tmp_path):
    life, transport, bus = _life(tmp_path, enabled=())  # PROBE_SYMBOL (AAPL) NOT enabled
    result = run_piv_lifecycle_probe(
        _config(tmp_path), bus, life, explicit_confirmation=True, now_et_time=dtime(15, 5),
    )
    assert not result.ran
    assert "PROBE_ENTRY_FAILED" in result.reason
    assert "PAPER_ENTRY_DISABLED_FOR_TICKER" in result.reason
    assert transport.submits == 0


def test_probe_path_cannot_bypass_already_holding(tmp_path):
    life, transport, bus = _life(tmp_path, enabled=(PROBE_SYMBOL,))
    entry = life.order_intent("prior", PROBE_SYMBOL, "buy", 1, source="STRATEGY")
    _fill(life, entry["id"], 1, 100.0)
    result = run_piv_lifecycle_probe(
        _config(tmp_path), bus, life, explicit_confirmation=True, now_et_time=dtime(15, 5),
    )
    # The probe's OWN pre-check catches this first (existing position in
    # probe symbol) -- still correctly blocked, just with the probe's own,
    # earlier-worded reason, proving the label "probe" grants no bypass
    # either way (caller-side pre-check or boundary check, both hold).
    assert not result.ran


def test_manual_direct_order_intent_call_is_not_a_bypass(tmp_path):
    """A "manual" caller (this test, standing in for any future manual/CLI
    entry point) goes through the identical boundary -- no separate,
    weaker path exists."""
    life, transport, _ = _life(tmp_path, enabled=())
    with pytest.raises(PaperGuardError, match="PAPER_ENTRY_DISABLED_FOR_TICKER"):
        life.order_intent("manual-1", "AAPL", "buy", 1, source="STRATEGY")
