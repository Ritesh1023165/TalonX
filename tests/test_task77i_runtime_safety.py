"""Task 77I Stage 1 -- runtime safety: timed-out submissions, restart
recovery, and (with tests/test_task76s_broker_boundary.py's own partial-fill
tests) the partial-fill accounting fix. Same isolated-fake-transport pattern
as test_task76s_broker_boundary.py -- no test in this file performs a real
broker mutation or notification of any kind."""
from __future__ import annotations

import pytest

from talonx_piv.broker import AlpacaPaperClient, PaperGuardError
from talonx_piv.config import PAPER_ENDPOINT, PivConfig
from talonx_piv.events import EventBus
from talonx_piv.execution_settings import PaperEntrySettings
from talonx_piv.lifecycle import PaperLifecycle


@pytest.fixture(autouse=True)
def _no_real_network(monkeypatch):
    import requests

    def _blocked(*args, **kwargs):
        raise AssertionError("test_task77i_runtime_safety: a real network call was attempted")

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


class StuckTransport:
    """TEST_FIXTURE_ONLY -- NOT ALPHA EVIDENCE. Every order accepted but
    NEVER progresses past 'accepted' -- simulates an order whose true
    outcome is never observed within a polling window."""

    def __init__(self):
        self.submits = 0
        self.orders: list[dict] = []
        self.get_order_calls = 0

    def get(self, url, **kwargs):
        if url.endswith("/v2/account"):
            return Response({"id": "paper-id", "account_number": "PA123456", "status": "ACTIVE"})
        if url.endswith("/v2/orders"):
            return Response([o for o in self.orders if o.get("status") not in ("filled", "rejected", "canceled")])
        if "/v2/orders/" in url:
            self.get_order_calls += 1
            order_id = url.rsplit("/", 1)[-1]
            match = next((o for o in self.orders if o["id"] == order_id), None)
            return Response(match or {}, 200 if match else 404)
        if url.endswith("/v2/positions"):
            return Response([])
        return Response({}, 404)

    def post(self, url, **kwargs):
        self.submits += 1
        order = {"id": f"order-{self.submits}", "status": "accepted", "filled_qty": "0", **kwargs.get("json", {})}
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


def _life(tmp_path, transport, *, enabled=("AAPL",)):
    broker = AlpacaPaperClient(_config(tmp_path), transport)
    broker.verify_paper_identity()
    bus = EventBus(tmp_path / "events.jsonl", feed_mode="RESEARCH_SIP")
    life = PaperLifecycle(tmp_path / "state.json", broker, bus, PaperEntrySettings.for_test(*enabled))
    life.start_session(True, True)
    return life, bus


# ---------------------------------------------------------------------------
# Timed-out submission -- uncertain, not blindly resubmitted
# ---------------------------------------------------------------------------

def test_timeout_marks_order_unconfirmed_not_terminal(tmp_path):
    transport = StuckTransport()
    life, _ = _life(tmp_path, transport)
    entry = life.order_intent("s1", "AAPL", "buy", 1)
    result = life.poll_order_until_terminal(entry["id"], timeout_seconds=0, poll_interval_seconds=1.0, sleep=lambda s: None)
    assert result.get("status") == "accepted"  # last observed broker status, not fabricated as terminal
    assert life.state.orders[entry["id"]]["status"] == "UNCONFIRMED_TIMEOUT"


def test_unconfirmed_timeout_blocks_a_duplicate_entry_for_the_same_symbol(tmp_path):
    """Fail-closed: an entry whose true broker outcome is unknown must
    still count as 'outstanding' for the no-pyramiding/pending-entry guard
    -- a second BUY for the same symbol must not slip through just because
    the first order never reached a terminal status."""
    transport = StuckTransport()
    life, _ = _life(tmp_path, transport)
    entry = life.order_intent("s1", "AAPL", "buy", 1)
    life.poll_order_until_terminal(entry["id"], timeout_seconds=0, poll_interval_seconds=1.0, sleep=lambda s: None)
    with pytest.raises(PaperGuardError, match="PENDING_ENTRY_EXISTS"):
        life.order_intent("s2", "AAPL", "buy", 1)
    assert transport.submits == 1  # the second buy never reached the broker


def test_reconcile_resolves_an_unconfirmed_order_against_a_fresh_broker_read(tmp_path):
    """reconcile() re-queries the broker for any UNCONFIRMED_TIMEOUT order
    and applies its real (now-known) status -- restart-safe: this scan
    reads persisted state, not in-memory-only bookkeeping."""
    transport = StuckTransport()
    life, _ = _life(tmp_path, transport)
    entry = life.order_intent("s1", "AAPL", "buy", 1)
    life.poll_order_until_terminal(entry["id"], timeout_seconds=0, poll_interval_seconds=1.0, sleep=lambda s: None)
    assert life.state.orders[entry["id"]]["status"] == "UNCONFIRMED_TIMEOUT"
    # The broker eventually did fill it -- reconcile() must discover this.
    for order in transport.orders:
        if order["id"] == entry["id"]:
            order.update(status="filled", filled_qty="1", filled_avg_price="100.0")
    life.reconcile()
    assert life.state.orders[entry["id"]]["status"] == "filled"
    assert life._open_position_for("AAPL") is not None  # position correctly opened from the resolved fill


def test_reconcile_leaves_order_unresolved_if_broker_read_still_fails(tmp_path):
    """A broker-read failure during resolution must not crash reconcile()
    or fabricate a resolved status -- the order stays UNCONFIRMED_TIMEOUT
    (still fail-closed/outstanding) for the next reconcile() attempt.

    Task 81 §2: an unresolved UNCONFIRMED_TIMEOUT order means the pass is
    NOT complete, so reconcile() must report matched=False and durably
    block new BUY admission -- an incomplete read is never treated as a
    clean, matched pass merely because the position symbol sets agree.
    """
    class FlakyGetOrderTransport(StuckTransport):
        def get(self, url, **kwargs):
            if "/v2/orders/" in url:
                raise RuntimeError("simulated transient broker read failure")
            return super().get(url, **kwargs)

    transport = FlakyGetOrderTransport()
    life, _ = _life(tmp_path, transport)
    entry = life.order_intent("s1", "AAPL", "buy", 1)
    # poll_order_until_terminal's own get_order call would also raise here;
    # simulate the timeout path having already been reached by directly
    # setting the sentinel status (equivalent end state).
    life.state.orders[entry["id"]]["status"] = "UNCONFIRMED_TIMEOUT"
    life._save()
    result = life.reconcile()  # must not raise
    assert life.state.orders[entry["id"]]["status"] == "UNCONFIRMED_TIMEOUT"
    assert result["matched"] is False  # incomplete: an unresolved order outcome
    assert result["complete"] is False
    assert entry["id"] in result["unconfirmed_timeout_orders"]
    assert life.state.reconciliation_flags["entry_admission_blocked"] is True


# ---------------------------------------------------------------------------
# Restart safety
# ---------------------------------------------------------------------------

def test_restart_preserves_pending_reservations_and_guards(tmp_path):
    """A fresh PaperLifecycle instance pointed at the SAME state file (as
    happens on a process restart) must see exactly the same outstanding
    reservations as the original instance -- no reservation is lost or
    silently dropped across a restart."""
    transport = StuckTransport()
    life, bus = _life(tmp_path, transport)
    life.order_intent("s1", "AAPL", "buy", 1)  # left non-terminal ("accepted", never polled to terminal)

    restarted = PaperLifecycle(tmp_path / "state.json", life.broker, bus, PaperEntrySettings.for_test("AAPL"))
    with pytest.raises(PaperGuardError, match="PENDING_ENTRY_EXISTS"):
        restarted.order_intent("s2", "AAPL", "buy", 1)
    assert transport.submits == 1


def test_restart_preserves_open_position_and_oversell_guard(tmp_path):
    transport = StuckTransport()
    life, bus = _life(tmp_path, transport)
    entry = life.order_intent("s1", "AAPL", "buy", 3)
    life.apply_broker_update(entry["id"], "filled", 3, 100.0)

    restarted = PaperLifecycle(tmp_path / "state.json", life.broker, bus, PaperEntrySettings.for_test("AAPL"))
    assert restarted._open_position_for("AAPL")["remaining_quantity"] == 3
    with pytest.raises(PaperGuardError, match="OVERSIZED_OR_DUPLICATE_SELL"):
        restarted.order_intent("exit1", "AAPL", "sell", 5)
