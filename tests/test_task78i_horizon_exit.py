"""Task 78I Stage 1B -- horizon-based shadow exits. TEST_FIXTURE_ONLY --
NOT ALPHA EVIDENCE throughout: every horizon_policy used here is an
explicit test-only injection; production (cli.py) never supplies one, so
every real Decision's horizon has no entry (see shadow_ledger.py's own
DEFAULT_HORIZON_POLICY docstring)."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

import pytest

from talonx_piv.decision_contract import DataReadiness, MarketView, StrategyApprovalStatus, decide
from talonx_piv.shadow_ledger import DEFAULT_HORIZON_POLICY, ShadowLedger


@dataclass(frozen=True)
class Bar:
    timestamp: datetime
    open: float
    high: float
    low: float
    close: float


T0 = datetime(2026, 8, 27, 14, 30, tzinfo=timezone.utc)


def _bar(minute, o, h, l, c) -> Bar:
    return Bar(T0 + timedelta(minutes=minute), o, h, l, c)


def _decision(decision_id="d1", ticker="AAPL", stop=None, target=None, horizon="INTRADAY_SHORT"):
    return decide(
        decision_id=decision_id, session_id="s1", trading_date_et="2026-08-27", ticker=ticker,
        market_view=MarketView.BULLISH, has_open_long=False, approved_exit_condition=False,
        strategy_approval_status=StrategyApprovalStatus.APPROVED, data_readiness=DataReadiness.READY,
        paper_entry_enabled=True, stop_price=stop, target_price=target, horizon=horizon, now=T0,
    )


def test_default_policy_has_no_entries_missing_horizon_never_gets_an_arbitrary_deadline():
    assert DEFAULT_HORIZON_POLICY == {}


def test_no_policy_configured_means_no_horizon_deadline(tmp_path):
    ledger = ShadowLedger(tmp_path / "shadow.json")  # no horizon_policy -- production default
    ledger.consider_entry(_decision(), source="STRATEGY")
    ledger.on_bar("AAPL", _bar(1, 100.0, 100.5, 99.5, 100.2))  # fills
    position = ledger.get_by_decision("d1")
    assert position["status"] == "OPEN"
    assert position["horizon_deadline"] is None


def test_horizon_deadline_computed_from_fill_time_not_decision_time(tmp_path):
    policy = {"INTRADAY_SHORT": timedelta(minutes=30)}
    ledger = ShadowLedger(tmp_path / "shadow.json", horizon_policy=policy)
    ledger.consider_entry(_decision(), source="STRATEGY")
    ledger.on_bar("AAPL", _bar(5, 100.0, 100.5, 99.5, 100.2))  # fills at T0+5min
    position = ledger.get_by_decision("d1")
    fill_time = datetime.fromisoformat(position["hypothetical_fill_time"])
    deadline = datetime.fromisoformat(position["horizon_deadline"])
    assert deadline == fill_time + timedelta(minutes=30)


def test_exact_deadline_boundary_exits_at_first_bar_reaching_it(tmp_path):
    policy = {"INTRADAY_SHORT": timedelta(minutes=10)}
    ledger = ShadowLedger(tmp_path / "shadow.json", horizon_policy=policy)
    ledger.consider_entry(_decision(stop=None, target=None), source="STRATEGY")
    ledger.on_bar("AAPL", _bar(1, 100.0, 100.5, 99.5, 100.2))  # fills at T0+1min -> deadline T0+11min
    ledger.on_bar("AAPL", _bar(10, 100.5, 101.0, 100.0, 100.8))  # T0+10min -- before deadline
    assert ledger.get_by_decision("d1")["status"] == "OPEN"
    ledger.on_bar("AAPL", _bar(11, 100.8, 101.2, 100.5, 101.0))  # T0+11min -- exactly the deadline
    position = ledger.get_by_decision("d1")
    assert position["status"] == "CLOSED"
    assert position["exit_reason"] == "HORIZON"
    assert position["simulated_exit_price_raw"] == 101.0  # this bar's real close, not an interpolated price


def test_horizon_checked_after_stop_target_same_bar(tmp_path):
    policy = {"INTRADAY_SHORT": timedelta(minutes=1)}
    ledger = ShadowLedger(tmp_path / "shadow.json", horizon_policy=policy)
    ledger.consider_entry(_decision(stop=99.0, target=105.0), source="STRATEGY")
    ledger.on_bar("AAPL", _bar(1, 100.0, 100.5, 99.5, 100.2))  # fills at T0+1min -> deadline T0+2min
    # T0+2min bar: BOTH stop breach AND deadline reached -- stop/target must win
    ledger.on_bar("AAPL", _bar(2, 100.0, 100.1, 98.5, 98.8))
    position = ledger.get_by_decision("d1")
    assert position["exit_reason"] == "STOP"


def test_late_arriving_bar_after_gap_still_exits_causally_not_backdated(tmp_path):
    policy = {"INTRADAY_SHORT": timedelta(minutes=5)}
    ledger = ShadowLedger(tmp_path / "shadow.json", horizon_policy=policy)
    ledger.consider_entry(_decision(stop=None, target=None), source="STRATEGY")
    ledger.on_bar("AAPL", _bar(1, 100.0, 100.5, 99.5, 100.2))  # fills -> deadline T0+6min
    # gap: no bars between minute 1 and minute 40
    ledger.on_bar("AAPL", _bar(40, 103.0, 103.5, 102.5, 103.2))  # first bar after the gap, well past deadline
    position = ledger.get_by_decision("d1")
    assert position["status"] == "CLOSED"
    assert position["exit_reason"] == "HORIZON"
    assert position["simulated_exit_price_raw"] == 103.2  # the real, late-observed close
    fill_time = datetime.fromisoformat(position["hypothetical_fill_time"])
    exit_time = datetime.fromisoformat(position["exit_time"])
    assert (exit_time - fill_time) > timedelta(minutes=30)  # holding period reflects the TRUE late exit, not the nominal 5-min horizon


def test_horizon_expiry_with_no_executable_observation_before_session_end(tmp_path):
    """Deadline passes; NO bar ever arrives before force_close (EOD) --
    resolves with a distinct, explicit reason, not fabricated."""
    policy = {"INTRADAY_SHORT": timedelta(minutes=5)}
    ledger = ShadowLedger(tmp_path / "shadow.json", horizon_policy=policy)
    ledger.consider_entry(_decision(stop=None, target=None), source="STRATEGY")
    ledger.on_bar("AAPL", _bar(1, 100.0, 100.5, 99.5, 100.2))  # fills -> deadline T0+6min
    # no further bars at all -- session ends
    eod_time = T0 + timedelta(hours=6)
    ledger.force_close("AAPL", eod_time, 102.0, "END_OF_SESSION")
    position = ledger.get_by_decision("d1")
    assert position["status"] == "CLOSED"
    assert position["exit_reason"] == "HORIZON_EXPIRED_NO_EXECUTABLE_OBSERVATION"
    assert position["simulated_exit_price_raw"] == 102.0  # still a REAL observed flatten price


def test_ordinary_eod_close_before_horizon_expiry_keeps_end_of_session_reason(tmp_path):
    policy = {"INTRADAY_SHORT": timedelta(hours=5)}  # long horizon, won't expire intraday
    ledger = ShadowLedger(tmp_path / "shadow.json", horizon_policy=policy)
    ledger.consider_entry(_decision(stop=None, target=None), source="STRATEGY")
    ledger.on_bar("AAPL", _bar(1, 100.0, 100.5, 99.5, 100.2))
    ledger.force_close("AAPL", T0 + timedelta(hours=1), 101.0, "END_OF_SESSION")
    position = ledger.get_by_decision("d1")
    assert position["exit_reason"] == "END_OF_SESSION"  # unchanged -- horizon never expired


def test_missing_data_at_expiry_yields_pending_state_not_fabricated_fill(tmp_path):
    """A PENDING_FILL position (never even opened) whose recommendation
    time is long past, with no fill ever observed, remains PENDING_FILL
    until force_close resolves it UNRESOLVED -- never silently treated as
    if it had opened and immediately hit its horizon."""
    policy = {"INTRADAY_SHORT": timedelta(minutes=5)}
    ledger = ShadowLedger(tmp_path / "shadow.json", horizon_policy=policy)
    ledger.consider_entry(_decision(), source="STRATEGY")
    assert ledger.get_by_decision("d1")["status"] == "PENDING_FILL"
    ledger.force_close("AAPL", T0 + timedelta(hours=6), None, "END_OF_SESSION")
    position = ledger.get_by_decision("d1")
    assert position["status"] == "UNRESOLVED"
    assert position["outcome_quality"] == "UNRESOLVED_NO_FILL_BEFORE_HORIZON_END"


def test_restart_preserves_horizon_deadline_and_resumes_correctly(tmp_path):
    policy = {"INTRADAY_SHORT": timedelta(minutes=5)}
    path = tmp_path / "shadow.json"
    ledger1 = ShadowLedger(path, horizon_policy=policy)
    ledger1.consider_entry(_decision(stop=None, target=None), source="STRATEGY")
    ledger1.on_bar("AAPL", _bar(1, 100.0, 100.5, 99.5, 100.2))  # fills -> deadline T0+6min
    deadline_before = ledger1.get_by_decision("d1")["horizon_deadline"]

    ledger2 = ShadowLedger(path, horizon_policy=policy)  # simulates a restart, same policy
    assert ledger2.get_by_decision("d1")["horizon_deadline"] == deadline_before
    ledger2.on_bar("AAPL", _bar(10, 101.0, 101.5, 100.5, 101.2))  # past deadline, post-restart
    position = ledger2.get_by_decision("d1")
    assert position["status"] == "CLOSED"
    assert position["exit_reason"] == "HORIZON"


def test_shadow_deadline_never_touches_broker_or_lifecycle():
    import inspect
    import talonx_piv.shadow_ledger as module
    source = inspect.getsource(module)
    for forbidden in ("PaperLifecycle", "AlpacaPaperClient", "order_intent", "\nimport talonx_piv.lifecycle", "\nimport talonx_piv.broker"):
        assert forbidden not in source
