"""Task 77I Stage 2 -- NotificationOutbox unit tests. TEST_FIXTURE_ONLY --
NOT ALPHA EVIDENCE (all decisions/adapters here are synthetic fixtures;
`FakeSender` never touches a real socket)."""
from __future__ import annotations

from talonx_piv.decision_contract import DataReadiness, MarketView, StrategyApprovalStatus, decide
from talonx_piv.notification_outbox import (
    CLASSIFICATION_ACTIONABLE_BUY, CLASSIFICATION_ACTIONABLE_SELL, CLASSIFICATION_WATCH, NotificationOutbox, classify,
)


def _buy_decision(decision_id="d1", **overrides):
    kwargs = dict(
        decision_id=decision_id, session_id="s1", trading_date_et="2026-08-27", ticker="AAPL",
        market_view=MarketView.BULLISH, has_open_long=False, approved_exit_condition=False,
        strategy_approval_status=StrategyApprovalStatus.APPROVED, data_readiness=DataReadiness.READY,
        paper_entry_enabled=True,
    )
    kwargs.update(overrides)
    return decide(**kwargs)


def _unvalidated_bullish_decision(decision_id="d2"):
    return decide(
        decision_id=decision_id, session_id="s1", trading_date_et="2026-08-27", ticker="MSFT",
        market_view=MarketView.BULLISH, has_open_long=False, approved_exit_condition=False,
        strategy_approval_status=StrategyApprovalStatus.UNVALIDATED, data_readiness=DataReadiness.READY,
        paper_entry_enabled=True,
    )


def _hold_decision(decision_id="d3"):
    return decide(
        decision_id=decision_id, session_id="s1", trading_date_et="2026-08-27", ticker="GOOG",
        market_view=MarketView.NEUTRAL, has_open_long=True, approved_exit_condition=False,
        strategy_approval_status=StrategyApprovalStatus.APPROVED, data_readiness=DataReadiness.READY,
        paper_entry_enabled=True,
    )


def _bearish_flat_decision(decision_id="d4"):
    return decide(
        decision_id=decision_id, session_id="s1", trading_date_et="2026-08-27", ticker="TSLA",
        market_view=MarketView.BEARISH, has_open_long=False, approved_exit_condition=False,
        strategy_approval_status=StrategyApprovalStatus.UNVALIDATED, data_readiness=DataReadiness.READY,
        paper_entry_enabled=True,
    )


class FakeSender:
    """TEST_FIXTURE_ONLY -- NOT ALPHA EVIDENCE. Never touches a real socket."""

    def __init__(self, outcomes=None):
        self.sent: list[str] = []
        self._outcomes = list(outcomes or [])

    def __call__(self, message: str) -> bool:
        self.sent.append(message)
        if self._outcomes:
            outcome = self._outcomes.pop(0)
            if outcome == "raise":
                raise RuntimeError("simulated adapter failure")
            return outcome
        return True


def test_classify_buy_and_sell_and_watch_and_none():
    assert classify(_buy_decision()) == CLASSIFICATION_ACTIONABLE_BUY
    assert classify(_unvalidated_bullish_decision()) == CLASSIFICATION_WATCH
    assert classify(_hold_decision()) is None
    assert classify(_bearish_flat_decision()) is None


def test_enqueue_actionable_buy_creates_a_pending_record(tmp_path):
    outbox = NotificationOutbox(tmp_path / "outbox.json", FakeSender())
    record = outbox.enqueue(_buy_decision())
    assert record["classification"] == CLASSIFICATION_ACTIONABLE_BUY
    assert record["status"] == "PENDING"


def test_enqueue_non_actionable_creates_nothing(tmp_path):
    outbox = NotificationOutbox(tmp_path / "outbox.json", FakeSender())
    assert outbox.enqueue(_hold_decision()) is None
    assert outbox.enqueue(_bearish_flat_decision()) is None
    assert outbox.records == {}


def test_watch_and_actionable_have_distinct_classifications_and_both_dispatch(tmp_path):
    outbox = NotificationOutbox(tmp_path / "outbox.json", FakeSender())
    buy_record = outbox.enqueue(_buy_decision())
    watch_record = outbox.enqueue(_unvalidated_bullish_decision())
    assert buy_record["classification"] != watch_record["classification"]
    counts = outbox.dispatch_pending()
    assert counts["sent"] == 2
    assert all(r["status"] == "SENT" for r in outbox.records.values())


def test_unchanged_evaluations_are_deduplicated(tmp_path):
    """Two decisions for the same ticker/date with the identical
    classification/recommendation/reason_codes (e.g. still-bullish-but-
    unvalidated on consecutive ticks) collapse into ONE queued
    notification, not one per tick."""
    outbox = NotificationOutbox(tmp_path / "outbox.json", FakeSender())
    first = outbox.enqueue(_unvalidated_bullish_decision(decision_id="tick1"))
    second = outbox.enqueue(_unvalidated_bullish_decision(decision_id="tick2"))
    assert first["notification_id"] == second["notification_id"]
    assert len(outbox.records) == 1


def test_bounded_retries_then_failed(tmp_path):
    sender = FakeSender(outcomes=[False, False, False])
    outbox = NotificationOutbox(tmp_path / "outbox.json", sender)
    outbox.enqueue(_buy_decision())
    outbox.dispatch_pending()  # attempt 1 -> RETRY
    outbox.dispatch_pending()  # attempt 2 -> RETRY
    outbox.dispatch_pending()  # attempt 3 -> FAILED (max_attempts reached)
    record = next(iter(outbox.records.values()))
    assert record["status"] == "FAILED"
    assert record["attempts"] == 3
    assert len(sender.sent) == 3


def test_adapter_exception_recorded_as_uncertain_not_failed_or_sent(tmp_path):
    sender = FakeSender(outcomes=["raise"])
    outbox = NotificationOutbox(tmp_path / "outbox.json", sender)
    outbox.enqueue(_buy_decision())
    outbox.dispatch_pending()
    record = next(iter(outbox.records.values()))
    assert record["status"] == "UNCERTAIN"


def test_no_adapter_configured_records_failed_never_fabricated_sent(tmp_path):
    outbox = NotificationOutbox(tmp_path / "outbox.json", None)
    outbox.enqueue(_buy_decision())
    outbox.dispatch_pending()
    record = next(iter(outbox.records.values()))
    assert record["status"] == "FAILED"


def test_states_persist_across_restart(tmp_path):
    path = tmp_path / "outbox.json"
    outbox1 = NotificationOutbox(path, FakeSender())
    outbox1.enqueue(_buy_decision())
    outbox1.dispatch_pending()
    outbox2 = NotificationOutbox(path, FakeSender())  # simulates a restart
    record = next(iter(outbox2.records.values()))
    assert record["status"] == "SENT"


def test_restart_does_not_create_duplicate_work_for_the_same_situation(tmp_path):
    path = tmp_path / "outbox.json"
    outbox1 = NotificationOutbox(path, FakeSender())
    outbox1.enqueue(_buy_decision(decision_id="d1"))
    outbox2 = NotificationOutbox(path, FakeSender())  # simulates a restart
    outbox2.enqueue(_buy_decision(decision_id="d1"))  # the exact same decision re-processed
    assert len(outbox2.records) == 1
