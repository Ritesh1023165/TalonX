"""Task 79E -- lifecycle.py's EXPERIMENTAL order_intent boundary and the
submission-timeout-before-ID safety net. TEST_FIXTURE_ONLY -- NOT ALPHA
EVIDENCE throughout."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from talonx_piv.broker import AlpacaPaperClient, PaperGuardError
from talonx_piv.config import PAPER_ENDPOINT, PivConfig
from talonx_piv.events import EventBus
from talonx_piv.execution_settings import PaperEntrySettings
from talonx_piv.experimental_authorization import ExperimentalAuthorization, ExperimentalPaperPermission
from talonx_piv.lifecycle import PaperLifecycle


class Response:
    def __init__(self, body, status=200): self.body, self.status_code = body, status
    def json(self): return self.body
    def raise_for_status(self):
        if self.status_code >= 400: raise RuntimeError(f"HTTP {self.status_code}")


class FakeTransport:
    def __init__(self):
        self.orders = []
        self.raise_on_post = False

    def get(self, url, **kwargs):
        if url.endswith("/v2/account"):
            return Response({"id": "acct-exp-1", "account_number": "PA123456", "status": "ACTIVE"})
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
        order = {"id": f"order-{len(self.orders) + 1}", "status": "new", "filled_qty": "0", **kwargs.get("json", {})}
        self.orders.append(order)
        return Response(order)

    def delete(self, url, **kwargs):
        return Response([])


def _auth(**overrides) -> ExperimentalAuthorization:
    """Task 79E: `_enforce_experimental_paper_guards` deliberately re-checks
    against the REAL wall clock (`datetime.now(timezone.utc)`) every call --
    "revalidated fresh" is a safety requirement, not merely a test
    convenience -- so these fixtures anchor activation/expiry to the actual
    current time, not a fixed historical constant."""
    now = datetime.now(timezone.utc)
    paper = ExperimentalPaperPermission(
        enabled=True, account_id_binding="acct-exp-1", max_quantity_per_entry=2.0,
        max_reference_notional_budget=500.0, max_entry_count=2, max_concurrent_exposure=1,
    )
    kwargs = dict(
        experiment_id="exp-1", operator_acknowledged_unvalidated=True, strategy_id="STRAT",
        strategy_version="v1", runtime_sha="sha1", config_hash="cfg1", allowed_symbols=frozenset({"AAPL"}),
        trading_date_et="2026-08-28", session_scope="REGULAR", activated_at=now - timedelta(hours=1),
        expires_at=now + timedelta(hours=10), paper=paper,
    )
    kwargs.update(overrides)
    return ExperimentalAuthorization(**kwargs)


def _life(tmp_path, *, auth=None, enabled=("AAPL",), transport=None):
    transport = transport or FakeTransport()
    broker = AlpacaPaperClient(PivConfig(key_id="k", secret_key="s", paper_trading=True, real_capital=False,
                                          broker_endpoint=PAPER_ENDPOINT, approved_sha="abc", state_dir=tmp_path), transport)
    broker.verify_paper_identity()
    bus = EventBus(tmp_path / "events.jsonl", feed_mode="RESEARCH_SIP")
    life = PaperLifecycle(
        tmp_path / "state.json", broker, bus, PaperEntrySettings.for_test(*enabled),
        experimental_authorization=auth, runtime_sha="sha1", config_hash="cfg1",
    )
    life.start_session(True, True)
    return life, transport, bus


def _order(life, **overrides):
    kwargs = dict(
        signal_id="s1", symbol="AAPL", side="buy", quantity=1.0, source="EXPERIMENTAL",
        reference_price=100.0, experimental_id="exp-1", experimental_trading_date_et="2026-08-28",
        strategy_id="STRAT", experimental_strategy_version="v1",
    )
    kwargs.update(overrides)
    return life.order_intent(**kwargs)


# ---------------------------------------------------------------------------
# Core experimental order_intent guards
# ---------------------------------------------------------------------------

def test_no_authorization_configured_rejected(tmp_path):
    life, transport, _ = _life(tmp_path, auth=None)
    with pytest.raises(PaperGuardError, match="EXPERIMENTAL_AUTHORIZATION_NOT_CONFIGURED"):
        _order(life)
    assert transport.orders == []


def test_valid_authorization_succeeds_and_reserves_budget(tmp_path):
    life, transport, _ = _life(tmp_path, auth=_auth())
    _order(life)
    assert transport.orders and transport.orders[0]["side"] == "buy"
    budget = life.state.experimental_budgets["exp-1"]
    assert budget["entries_used"] == 1
    assert budget["notional_used"] == pytest.approx(100.0)


def test_experimental_id_mismatch_rejected(tmp_path):
    life, transport, _ = _life(tmp_path, auth=_auth())
    with pytest.raises(PaperGuardError, match="EXPERIMENTAL_ID_MISMATCH"):
        _order(life, experimental_id="wrong-id")
    assert transport.orders == []


def test_wrong_account_rejected(tmp_path):
    auth = _auth(paper=ExperimentalPaperPermission(
        enabled=True, account_id_binding="SOME-OTHER-ACCOUNT", max_quantity_per_entry=2.0,
        max_reference_notional_budget=500.0, max_entry_count=2, max_concurrent_exposure=1,
    ))
    life, transport, _ = _life(tmp_path, auth=auth)
    with pytest.raises(PaperGuardError, match="EXPERIMENTAL_WRONG_PAPER_ACCOUNT"):
        _order(life)
    assert transport.orders == []


def test_wrong_symbol_rejected(tmp_path):
    life, transport, _ = _life(tmp_path, auth=_auth(), enabled=("MSFT",))
    with pytest.raises(PaperGuardError, match="EXPERIMENTAL_SYMBOL_NOT_IN_ALLOWED_SET"):
        _order(life, symbol="MSFT")
    assert transport.orders == []


def test_wrong_trading_date_rejected(tmp_path):
    life, transport, _ = _life(tmp_path, auth=_auth())
    with pytest.raises(PaperGuardError, match="EXPERIMENTAL_WRONG_TRADING_DATE"):
        _order(life, experimental_trading_date_et="2026-08-29")
    assert transport.orders == []


def test_wrong_strategy_version_rejected(tmp_path):
    life, transport, _ = _life(tmp_path, auth=_auth())
    with pytest.raises(PaperGuardError, match="EXPERIMENTAL_WRONG_STRATEGY_VERSION"):
        _order(life, experimental_strategy_version="v2")
    assert transport.orders == []


def test_wrong_runtime_sha_rejected(tmp_path):
    life, transport, _ = _life(tmp_path, auth=_auth())
    life.runtime_sha = "different-sha"
    with pytest.raises(PaperGuardError, match="EXPERIMENTAL_WRONG_RUNTIME_SHA"):
        _order(life)
    assert transport.orders == []


def test_expired_permission_rejected(tmp_path):
    now = datetime.now(timezone.utc)
    auth = _auth(activated_at=now - timedelta(hours=5), expires_at=now - timedelta(hours=1))
    life, transport, _ = _life(tmp_path, auth=auth)
    with pytest.raises(PaperGuardError, match="EXPERIMENTAL_PERMISSION_EXPIRED"):
        _order(life)
    assert transport.orders == []


def test_quantity_exceeds_limit_rejected(tmp_path):
    life, transport, _ = _life(tmp_path, auth=_auth())
    with pytest.raises(PaperGuardError, match="EXPERIMENTAL_QUANTITY_EXCEEDS_LIMIT"):
        _order(life, quantity=3.0)
    assert transport.orders == []


def test_missing_reference_price_rejected(tmp_path):
    """Reference-price budget check ONLY -- never a hard cap on realised
    fill value; but with none supplied at all, the notional cannot be
    estimated -- fails closed rather than treating it as free."""
    life, transport, _ = _life(tmp_path, auth=_auth())
    with pytest.raises(PaperGuardError, match="EXPERIMENTAL_REFERENCE_PRICE_REQUIRED_FOR_BUDGET_CHECK"):
        _order(life, reference_price=None)
    assert transport.orders == []


def test_notional_budget_exhausted_rejected(tmp_path):
    auth = _auth(paper=ExperimentalPaperPermission(
        enabled=True, account_id_binding="acct-exp-1", max_quantity_per_entry=2.0,
        max_reference_notional_budget=150.0, max_entry_count=5, max_concurrent_exposure=5,
    ))
    life, transport, _ = _life(tmp_path, auth=auth)
    _order(life, signal_id="s1")  # consumes 100.0 of 150.0
    life.apply_broker_update(transport.orders[0]["id"], "filled", 1, 100.0)
    sell = life.order_intent("exit1", "AAPL", "sell", 1.0, source="EXPERIMENTAL", experimental_id="exp-1")
    life.apply_broker_update(sell["id"], "filled", 1, 101.0)
    with pytest.raises(PaperGuardError, match="EXPERIMENTAL_NOTIONAL_BUDGET_EXHAUSTED"):
        _order(life, signal_id="s2", symbol="AAPL")  # would need another 100.0, only 50.0 left
    assert len(transport.orders) == 2


def test_entry_count_exhausted_rejected(tmp_path):
    auth = _auth(paper=ExperimentalPaperPermission(
        enabled=True, account_id_binding="acct-exp-1", max_quantity_per_entry=2.0,
        max_reference_notional_budget=10000.0, max_entry_count=1, max_concurrent_exposure=5,
    ))
    life, transport, _ = _life(tmp_path, auth=auth)
    _order(life, signal_id="s1")
    life.apply_broker_update(transport.orders[0]["id"], "filled", 1, 100.0)
    life.apply_broker_update(transport.orders[0]["id"], "filled", 1, 100.0)  # idempotent-ish re-apply irrelevant here
    # Close it out so the ONLY blocker left is entry-count, not pyramiding:
    sell = life.order_intent("exit1", "AAPL", "sell", 1.0, source="EXPERIMENTAL", experimental_id="exp-1")
    life.apply_broker_update(sell["id"], "filled", 1, 101.0)
    with pytest.raises(PaperGuardError, match="EXPERIMENTAL_ENTRY_COUNT_EXHAUSTED"):
        _order(life, signal_id="s2")
    assert len(transport.orders) == 2


def test_budget_survives_restart(tmp_path):
    auth = _auth()
    life1, transport, _ = _life(tmp_path, auth=auth)
    _order(life1)
    life2 = PaperLifecycle(tmp_path / "state.json", life1.broker, life1.events,
                            PaperEntrySettings.for_test("AAPL"), experimental_authorization=auth,
                            runtime_sha="sha1", config_hash="cfg1")
    assert life2.state.experimental_budgets["exp-1"]["entries_used"] == 1


def test_budget_not_reset_by_reloading_a_fresh_authorization_object(tmp_path):
    """A newly re-loaded ExperimentalAuthorization for the SAME experiment_id
    (e.g. after a process restart re-reads the config file) must not zero
    the durable budget already spent."""
    auth1 = _auth()  # default max_entry_count=2
    life, transport, _ = _life(tmp_path, auth=auth1)
    _order(life, signal_id="s1")
    life.apply_broker_update(transport.orders[0]["id"], "filled", 1, 100.0)
    sell1 = life.order_intent("exit1", "AAPL", "sell", 1.0, source="EXPERIMENTAL", experimental_id="exp-1")
    life.apply_broker_update(sell1["id"], "filled", 1, 101.0)

    auth2 = _auth()  # a fresh, distinct Python object, same experiment_id -- simulates a restart re-load
    life.experimental_authorization = auth2
    assert life.state.experimental_budgets["exp-1"]["entries_used"] == 1  # carried over, not reset

    _order(life, signal_id="s2")  # 2nd entry -- still within max_entry_count=2
    life.apply_broker_update(transport.orders[-1]["id"], "filled", 1, 100.0)
    sell2 = life.order_intent("exit2", "AAPL", "sell", 1.0, source="EXPERIMENTAL", experimental_id="exp-1")
    life.apply_broker_update(sell2["id"], "filled", 1, 101.0)

    with pytest.raises(PaperGuardError, match="EXPERIMENTAL_ENTRY_COUNT_EXHAUSTED"):
        _order(life, signal_id="s3")  # 3rd entry -- exceeds max_entry_count=2, proving the counter carried over


def test_normal_strategy_source_unaffected_by_experimental_guards(tmp_path):
    """No experimental authorization configured at all -- an ordinary
    STRATEGY-sourced order is completely unaffected (backward compatible)."""
    life, transport, _ = _life(tmp_path, auth=None)
    result = life.order_intent("s1", "AAPL", "buy", 1.0, source="STRATEGY", reference_price=100.0)
    assert result["id"]
    assert transport.orders


# ---------------------------------------------------------------------------
# Submission-timeout-before-ID safety net
# ---------------------------------------------------------------------------

def test_submission_failure_before_id_marks_uncertain_and_blocks_pyramiding(tmp_path):
    """The ORIGINAL exception type propagates unwrapped (Task 78I's
    pre-existing contract: DecisionEngine._handle_entry only catches
    PaperGuardError, so a raw transport failure must reach SessionRunner's
    own outer per-tick guard -- test_task78i_stage5_rehearsal.py::
    test_05_broker_failure_does_not_block_alert_shadow proves this at the
    engine layer). Only the SECOND, pyramiding-guard rejection is a genuine
    PaperGuardError, since PENDING_ENTRY_EXISTS is this module's own guard."""
    transport = FakeTransport()
    transport.raise_on_post = True
    life, transport, _ = _life(tmp_path, auth=_auth(), transport=transport)
    with pytest.raises(RuntimeError, match="simulated HTTP submission failure"):
        _order(life, signal_id="s1")
    # A DIFFERENT signal_id for the SAME symbol must still be blocked --
    # the first attempt's true outcome is genuinely unknown.
    transport.raise_on_post = False
    with pytest.raises(PaperGuardError, match="PENDING_ENTRY_EXISTS"):
        _order(life, signal_id="s2")
    assert transport.orders == []


def test_submission_failure_does_not_refund_experimental_budget(tmp_path):
    transport = FakeTransport()
    transport.raise_on_post = True
    life, transport, _ = _life(tmp_path, auth=_auth(), transport=transport)
    with pytest.raises(RuntimeError):
        _order(life, signal_id="s1")
    budget = life.state.experimental_budgets["exp-1"]
    assert budget["entries_used"] == 1  # NOT refunded -- conservative, matches "no blind assumption of zero exposure"
