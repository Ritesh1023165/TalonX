from __future__ import annotations

from dataclasses import replace
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import pytest

from talonx_quant.orpb_v1 import (
    ORPB_V1_NAME,
    OrpbV1Bar,
    OrpbV1Config,
    OrpbV1Telemetry,
    actual_cost_r_5bps,
    estimated_cost_r_5bps,
    rank_orpb_v1_candidates,
)
from talonx_quant.orpb_v1_shadow import OrpbV1ShadowController


ET = ZoneInfo("America/New_York")


def bar(
    timestamp: datetime,
    close: float,
    *,
    open_: float | None = None,
    high: float | None = None,
    low: float | None = None,
    volume: float = 100.0,
) -> OrpbV1Bar:
    open_ = close if open_ is None else open_
    high = max(open_, close) + 0.1 if high is None else high
    low = min(open_, close) - 0.1 if low is None else low
    return OrpbV1Bar(timestamp, open_, high, low, close, volume)


def feed_opening_range(controller: OrpbV1ShadowController, tickers=("AAA",)) -> datetime:
    start = datetime(2026, 7, 7, 9, 30, tzinfo=ET)
    for minute in range(30):
        controller.on_completed_bar_batch(
            {
                ticker: bar(
                    start + timedelta(minutes=minute), 99.5,
                    open_=99.5, high=100.0, low=99.0, volume=100.0,
                )
                for ticker in tickers
            }
        )
    return start + timedelta(minutes=30)


def create_candidate(
    controller: OrpbV1ShadowController,
    tickers=("AAA",),
    *,
    breakout_volume: float = 150.0,
):
    start = feed_opening_range(controller, tickers)
    for minute in range(5):
        controller.on_completed_bar_batch(
            {
                ticker: bar(
                    start + timedelta(minutes=minute), 101.0,
                    open_=100.1, high=101.2, low=99.8, volume=breakout_volume,
                )
                for ticker in tickers
            }
        )
    released = controller.on_completed_bar_batch(
        {
            ticker: bar(
                start + timedelta(minutes=5), 101.4,
                open_=101.1, high=101.5, low=101.0,
            )
            for ticker in tickers
        }
    )
    return start, released


def test_opening_range_participation_breakout_and_immediate_confirmation() -> None:
    controller = OrpbV1ShadowController()
    start, released = create_candidate(controller)
    assert len(released) == 1
    candidate = released[0]
    assert candidate.architecture == ORPB_V1_NAME
    assert candidate.opening_range_high == pytest.approx(100.0)
    assert candidate.opening_range_low == pytest.approx(99.0)
    assert candidate.opening_volume_median == pytest.approx(500.0)
    assert candidate.breakout_volume == pytest.approx(750.0)
    assert candidate.breakout_timestamp == start + timedelta(minutes=4)
    assert candidate.confirmation_timestamp == start + timedelta(minutes=5)
    assert candidate.stop_price == pytest.approx(99.79)
    assert candidate.estimated_cost_r_5bps <= 0.20
    assert "AAA" in controller.pending_entries


def test_participation_is_strictly_above_opening_median_and_one_attempt_only() -> None:
    controller = OrpbV1ShadowController()
    start, released = create_candidate(controller, breakout_volume=100.0)
    assert released == []
    assert controller.rejections[-1].reason == "PARTICIPATION_INSUFFICIENT"
    for minute in range(6, 11):
        later = controller.on_completed_bar_batch(
            {"AAA": bar(start + timedelta(minutes=minute), 102.0, volume=1000.0)}
        )
    assert later == []
    assert controller.published == []


def test_confirmation_has_no_grace_period() -> None:
    controller = OrpbV1ShadowController()
    start = feed_opening_range(controller)
    for minute in range(5):
        controller.on_completed_bar_batch(
            {"AAA": bar(start + timedelta(minutes=minute), 101.0, high=101.2, low=99.8, volume=150)}
        )
    failed = controller.on_completed_bar_batch(
        {"AAA": bar(start + timedelta(minutes=5), 101.1, high=101.2)}
    )
    later = controller.on_completed_bar_batch(
        {"AAA": bar(start + timedelta(minutes=6), 102.0)}
    )
    assert failed == [] and later == []
    assert controller.published == []


def test_entry_is_next_bar_and_actual_fill_cost_rechecks() -> None:
    controller = OrpbV1ShadowController()
    start, released = create_candidate(controller)
    candidate = released[0]
    fill = bar(
        start + timedelta(minutes=6), candidate.stop_price + 0.25,
        open_=candidate.stop_price + 0.25,
        high=candidate.stop_price + 0.3,
        low=candidate.stop_price + 0.2,
    )
    controller.on_completed_bar_batch({"AAA": fill})
    assert estimated_cost_r_5bps(fill.open, candidate.stop_price) > 0.20
    assert "AAA" not in controller.positions
    assert controller.rejections[-1].reason == "ACTUAL_FILL_COST_OR_GEOMETRY_INFEASIBLE"


def test_no_target_hard_stop_and_entry_bar_stop_first() -> None:
    controller = OrpbV1ShadowController()
    start, released = create_candidate(controller)
    candidate = released[0]
    entry = bar(
        start + timedelta(minutes=6), 101.4, open_=101.4,
        high=105.0, low=candidate.stop_price - 0.01,
    )
    controller.on_completed_bar_batch({"AAA": entry})
    trade = controller.trades[-1]
    assert trade.exit_reason == "STOP"
    assert trade.gross_r == pytest.approx(-1.0)
    assert trade.mfe_r > 0


def test_completed_5m_range_failure_exits_at_next_1m_open() -> None:
    controller = OrpbV1ShadowController()
    start, _ = create_candidate(controller)
    controller.on_completed_bar_batch(
        {"AAA": bar(start + timedelta(minutes=6), 101.4, open_=101.4, low=100.5)}
    )
    for minute in range(7, 14):
        controller.on_completed_bar_batch(
            {"AAA": bar(start + timedelta(minutes=minute), 101.0, low=100.5)}
        )
    failure = bar(start + timedelta(minutes=14), 99.9, low=99.8, high=100.1)
    controller.on_completed_bar_batch({"AAA": failure})
    assert "AAA" in controller.positions and "AAA" in controller.pending_thesis_exits
    exit_bar = bar(start + timedelta(minutes=15), 100.0, open_=100.0)
    controller.on_completed_bar_batch({"AAA": exit_bar})
    assert controller.trades[-1].exit_reason == "THESIS_FAILURE"
    assert controller.trades[-1].exit_price == pytest.approx(100.0)


def test_telemetry_cannot_change_eligibility_and_namespaces_are_isolated() -> None:
    left = OrpbV1ShadowController()
    right = OrpbV1ShadowController()
    start = datetime(2026, 7, 7, 9, 30, tzinfo=ET)
    for minute in range(36):
        if minute < 30:
            current = bar(start + timedelta(minutes=minute), 99.5, high=100, low=99, volume=100)
        elif minute < 35:
            current = bar(start + timedelta(minutes=minute), 101, high=101.2, low=99.8, volume=150)
        else:
            current = bar(start + timedelta(minutes=minute), 101.4, high=101.5, low=101)
        left_out = left.on_completed_bar_batch(
            {"AAA": current}, {"AAA": OrpbV1Telemetry(rsi_14=-999, atr_15m_pct=0)}
        )
        right_out = right.on_completed_bar_batch(
            {"AAA": current}, {"AAA": OrpbV1Telemetry(rsi_14=999, atr_15m_pct=999)}
        )
    assert len(left_out) == len(right_out) == 1
    assert replace(left_out[0], telemetry=OrpbV1Telemetry()) == replace(
        right_out[0], telemetry=OrpbV1Telemetry()
    )
    assert left.signals.machine("AAA") is not right.signals.machine("AAA")


def test_state_only_warmup_never_publishes_or_arms_controls() -> None:
    controller = OrpbV1ShadowController()
    start = datetime(2026, 7, 6, 9, 30, tzinfo=ET)
    for minute in range(390):
        controller.on_completed_bar_batch(
            {"AAA": bar(start + timedelta(minutes=minute), 100.0)}, state_only=True
        )
    assert controller.published == []
    assert controller.positions == {}
    assert controller.pending_entries == {}
    assert controller.cooldown_until == {}
    assert controller.loss_lockout_until == {}


def test_capacity_is_three_and_ranking_is_cost_first_then_ticker() -> None:
    controller = OrpbV1ShadowController()
    _, released = create_candidate(controller, ("DDD", "CCC", "BBB", "AAA"))
    assert [item.ticker for item in released] == ["AAA", "BBB", "CCC"]
    assert controller.rejections[-1].ticker == "DDD"
    assert controller.rejections[-1].reason == "CAPACITY"
    assert rank_orpb_v1_candidates(list(reversed(released))) == released


def test_loss_lockout_and_1550_flatten() -> None:
    stopped = OrpbV1ShadowController()
    start, released = create_candidate(stopped)
    candidate = released[0]
    stopped.on_completed_bar_batch(
        {"AAA": bar(start + timedelta(minutes=6), 101.4, open_=101.4, low=candidate.stop_price - 0.01)}
    )
    assert stopped.loss_lockout_until["AAA"] == start + timedelta(minutes=81)

    flattened = OrpbV1ShadowController()
    start2, _ = create_candidate(flattened)
    flattened.on_completed_bar_batch(
        {"AAA": bar(start2 + timedelta(minutes=6), 101.4, open_=101.4, low=100.5)}
    )
    flatten = start2.replace(hour=15, minute=50)
    flattened.on_completed_bar_batch({"AAA": bar(flatten, 102.0, low=101.5)})
    assert flattened.trades[-1].exit_reason == "END_OF_SESSION"


def test_live_shadow_and_research_use_same_controller_semantics() -> None:
    live = OrpbV1ShadowController()
    research = OrpbV1ShadowController()
    start = datetime(2026, 7, 7, 9, 30, tzinfo=ET)
    sequence = []
    for minute in range(30):
        sequence.append(bar(start + timedelta(minutes=minute), 99.5, high=100, low=99, volume=100))
    for minute in range(30, 35):
        sequence.append(bar(start + timedelta(minutes=minute), 101, high=101.2, low=99.8, volume=150))
    sequence.append(bar(start + timedelta(minutes=35), 101.4, high=101.5, low=101))
    sequence.append(bar(start + timedelta(minutes=36), 101.4, open_=101.4, low=100.5))
    for current in sequence:
        live.on_completed_bar_batch({"AAA": current})
        research.on_completed_bar_batch({"AAA": current})
    assert live.published == research.published
    assert live.positions == research.positions
    assert live.rejections == research.rejections


def test_cost_formulas_and_frozen_config() -> None:
    assert estimated_cost_r_5bps(100, 99) == pytest.approx(0.1)
    assert actual_cost_r_5bps(100, 102, 99) == pytest.approx(0.101)
    with pytest.raises(ValueError):
        OrpbV1Config(opening_range_minutes=15)
