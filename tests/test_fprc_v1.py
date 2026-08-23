from __future__ import annotations

from dataclasses import replace
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import pytest

from talonx_quant.fprc_v1 import (
    FPRC_V1_NAME,
    FprcV1Bar,
    FprcV1Candidate,
    FprcV1Config,
    FprcV1ShadowNamespace,
    FprcV1Telemetry,
    FprcV1Trend,
    actual_cost_r_5bps,
    estimated_cost_r_5bps,
    rank_fprc_v1_candidates,
)
from talonx_quant.fprc_v1_shadow import FprcV1ShadowController


ET = ZoneInfo("America/New_York")
TEST_CONFIG = replace(FprcV1Config(), sma_period=2, sma_slope_lookback=1)


def bar(ts: datetime, close: float, *, open_: float | None = None, low: float | None = None,
        high: float | None = None, volume: float = 100.0) -> FprcV1Bar:
    open_ = close if open_ is None else open_
    low = min(open_, close) - 0.1 if low is None else low
    high = max(open_, close) + 0.1 if high is None else high
    return FprcV1Bar(ts, open_, high, low, close, volume)


def seed_ready(controller: FprcV1ShadowController, ticker: str = "AAA") -> datetime:
    prior = datetime(2026, 7, 6, 9, 30, tzinfo=ET)
    for minute in range(45):
        price = 90.0 + (minute // 15) * 0.1
        controller.on_completed_bar_batch({ticker: bar(prior + timedelta(minutes=minute), price)}, state_only=True)
    current = datetime(2026, 7, 7, 9, 30, tzinfo=ET)
    for minute in range(15):
        controller.on_completed_bar_batch({ticker: bar(current + timedelta(minutes=minute), 100.0)}, state_only=True)
    return current + timedelta(minutes=15)


def build_candidate(controller: FprcV1ShadowController, ticker: str = "AAA") -> tuple[datetime, FprcV1Candidate]:
    start = seed_ready(controller, ticker)
    assert controller.on_completed_bar_batch({ticker: bar(start, 99.0, low=98.8, high=99.2)}) == []
    assert controller.on_completed_bar_batch({ticker: bar(start + timedelta(minutes=1), 99.1, low=98.9, high=99.3)}) == []
    assert controller.on_completed_bar_batch({ticker: bar(start + timedelta(minutes=2), 101.0, low=99.0, high=101.2)}) == []
    released = controller.on_completed_bar_batch(
        {ticker: bar(start + timedelta(minutes=3), 101.5, low=100.8, high=101.7)}
    )
    assert len(released) == 1
    return start, released[0]


def test_causal_vwap_two_below_reclaim_and_immediate_confirmation():
    controller = FprcV1ShadowController(TEST_CONFIG)
    start, candidate = build_candidate(controller)
    assert candidate.architecture == FPRC_V1_NAME
    assert candidate.confirmation_timestamp == start + timedelta(minutes=3)
    assert candidate.pullback_low == pytest.approx(98.8)
    assert candidate.stop_price == pytest.approx(98.79)
    assert candidate.estimated_cost_r_5bps <= 0.20
    assert "AAA" in controller.pending_entries  # publication close; next bar is the fill


def test_confirmation_has_no_grace_period():
    controller = FprcV1ShadowController(TEST_CONFIG)
    start = seed_ready(controller)
    for offset, price in ((0, 99.0), (1, 99.1), (2, 101.0)):
        controller.on_completed_bar_batch({"AAA": bar(start + timedelta(minutes=offset), price)})
    failed = controller.on_completed_bar_batch({"AAA": bar(start + timedelta(minutes=3), 100.5)})
    later = controller.on_completed_bar_batch({"AAA": bar(start + timedelta(minutes=4), 102.0)})
    assert failed == [] and later == []


def test_next_bar_actual_fill_feasibility_fails_closed():
    controller = FprcV1ShadowController(TEST_CONFIG)
    start, candidate = build_candidate(controller)
    fill_bar = bar(start + timedelta(minutes=4), 99.0, open_=99.0, low=98.9, high=99.2)
    controller.on_completed_bar_batch({"AAA": fill_bar})
    assert candidate.stop_price < fill_bar.open
    assert estimated_cost_r_5bps(fill_bar.open, candidate.stop_price) > 0.20
    assert "AAA" not in controller.positions
    assert controller.rejections[-1].reason == "ACTUAL_FILL_COST_OR_GEOMETRY_INFEASIBLE"


def test_no_target_hard_stop_and_same_entry_bar_stop_first():
    controller = FprcV1ShadowController(TEST_CONFIG)
    start, candidate = build_candidate(controller)
    entry = bar(start + timedelta(minutes=4), 101.4, open_=101.4, low=candidate.stop_price - 0.01, high=104.0)
    controller.on_completed_bar_batch({"AAA": entry})
    trade = controller.trades[-1]
    assert trade.exit_reason == "STOP"
    assert trade.gross_r == pytest.approx(-1.0)
    assert trade.mfe_r > 0


def test_completed_5m_below_vwap_exits_at_next_1m_open():
    controller = FprcV1ShadowController(TEST_CONFIG)
    start, _ = build_candidate(controller)
    controller.on_completed_bar_batch({"AAA": bar(start + timedelta(minutes=4), 101.4, open_=101.4, low=100.5)})
    for offset in range(5, 9):
        controller.on_completed_bar_batch({"AAA": bar(start + timedelta(minutes=offset), 101.0, low=100.5)})
    failure_close = start + timedelta(minutes=9)  # 09:54 completes the 5m bucket
    controller.on_completed_bar_batch({"AAA": bar(failure_close, 99.0, low=98.9)})
    assert "AAA" in controller.positions and "AAA" in controller.pending_thesis_exits
    exit_bar = bar(start + timedelta(minutes=10), 99.2, open_=99.2, low=99.0, high=99.4)
    controller.on_completed_bar_batch({"AAA": exit_bar})
    assert controller.trades[-1].exit_reason == "THESIS_FAILURE"
    assert controller.trades[-1].exit_timestamp == exit_bar.timestamp
    assert controller.trades[-1].exit_price == pytest.approx(99.2)


def test_cost_first_ranking_then_timestamp_then_ticker():
    trend = FprcV1Trend(True, True, 100, 99, 98)
    ts = datetime(2026, 7, 7, 11, 0, tzinfo=ET)
    def candidate(ticker: str, cost: float, seconds: int = 0):
        return FprcV1Candidate(ticker, FPRC_V1_NAME, ts + timedelta(seconds=seconds), 100, 99,
                               99.01, ts, 100, 99.5, cost, trend, FprcV1Telemetry())
    ranked = rank_fprc_v1_candidates([
        candidate("ZZZ", .15), candidate("BBB", .10), candidate("AAA", .10), candidate("EARLY", .10, -1)
    ])
    assert [item.ticker for item in ranked] == ["EARLY", "AAA", "BBB", "ZZZ"]


def test_telemetry_is_observational_only_and_namespaces_are_isolated():
    left = FprcV1ShadowController(TEST_CONFIG)
    right = FprcV1ShadowController(TEST_CONFIG)
    start_left = seed_ready(left)
    start_right = seed_ready(right)
    assert start_left == start_right
    prices = [99.0, 99.1, 101.0, 101.5]
    left_out = right_out = []
    for offset, price in enumerate(prices):
        current = bar(start_left + timedelta(minutes=offset), price)
        left_out = left.on_completed_bar_batch({"AAA": current}, {"AAA": FprcV1Telemetry(rsi_14=-999, atr_15m_pct=0)})
        right_out = right.on_completed_bar_batch({"AAA": current}, {"AAA": FprcV1Telemetry(rsi_14=999, atr_15m_pct=999)})
    assert len(left_out) == len(right_out) == 1
    assert replace(left_out[0], telemetry=FprcV1Telemetry()) == replace(right_out[0], telemetry=FprcV1Telemetry())
    left.signals.machine("AAA").reset_setup()
    assert right.signals.machine("AAA") is not left.signals.machine("AAA")


def test_state_only_preroll_cannot_publish_or_arm_controls():
    controller = FprcV1ShadowController(TEST_CONFIG)
    seed_ready(controller)
    assert controller.published == []
    assert controller.pending_entries == {}
    assert controller.cooldown_until == {}
    assert controller.loss_lockout_until == {}


def test_live_shadow_and_research_adapter_use_identical_shared_semantics():
    live_shadow = FprcV1ShadowController(TEST_CONFIG)
    research = FprcV1ShadowController(TEST_CONFIG)
    start = seed_ready(live_shadow)
    assert seed_ready(research) == start
    sequence = [
        bar(start, 99.0), bar(start + timedelta(minutes=1), 99.1),
        bar(start + timedelta(minutes=2), 101.0), bar(start + timedelta(minutes=3), 101.5),
        bar(start + timedelta(minutes=4), 101.4, open_=101.4, low=100.5),
    ]
    for current in sequence:
        live_shadow.on_completed_bar_batch({"AAA": current})
        research.on_completed_bar_batch({"AAA": current})
    assert live_shadow.published == research.published
    assert live_shadow.positions == research.positions
    assert live_shadow.rejections == research.rejections


def test_cost_formulas_use_expected_and_actual_exit_notional():
    assert estimated_cost_r_5bps(100, 99) == pytest.approx(0.1)
    assert actual_cost_r_5bps(100, 102, 99) == pytest.approx(0.101)


def test_capacity_is_three_and_uses_cost_first_order():
    controller = FprcV1ShadowController(TEST_CONFIG)
    starts = {ticker: seed_ready(controller, ticker) for ticker in ("AAA", "BBB", "CCC", "DDD")}
    # Seeding sequentially advances each ticker independently; all four setups
    # then confirm at the same timestamps and enter the one batch ranking.
    for offset, price in enumerate((99.0, 99.1, 101.0)):
        controller.on_completed_bar_batch({
            ticker: bar(start + timedelta(minutes=offset), price)
            for ticker, start in starts.items()
        })
    released = controller.on_completed_bar_batch({
        ticker: bar(start + timedelta(minutes=3), 101.5)
        for ticker, start in starts.items()
    })
    assert [candidate.ticker for candidate in released] == ["AAA", "BBB", "CCC"]
    assert controller.rejections[-1].ticker == "DDD"
    assert controller.rejections[-1].reason == "CAPACITY"


def test_loss_arms_75_minute_lockout_and_1550_flattens():
    controller = FprcV1ShadowController(TEST_CONFIG)
    start, candidate = build_candidate(controller)
    controller.on_completed_bar_batch({
        "AAA": bar(start + timedelta(minutes=4), 101.4, open_=101.4,
                   low=candidate.stop_price - 0.01, high=101.5)
    })
    assert controller.loss_lockout_until["AAA"] == start + timedelta(minutes=79)

    second = FprcV1ShadowController(TEST_CONFIG)
    start2, _ = build_candidate(second)
    second.on_completed_bar_batch({
        "AAA": bar(start2 + timedelta(minutes=4), 101.4, open_=101.4, low=100.5)
    })
    flatten = start2.replace(hour=15, minute=50)
    second.on_completed_bar_batch({"AAA": bar(flatten, 102.0, low=101.5)})
    assert second.trades[-1].exit_reason == "END_OF_SESSION"
    assert "AAA" not in second.positions
