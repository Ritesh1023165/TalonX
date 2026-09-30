"""VR_PAPER_V1: virtual clock causality, entry convention, stop/target/session-close fills, cost, capital, determinism."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from talonx_paperperf import vr_paper as V

UTC = timezone.utc
OPEN = datetime(2026, 9, 28, 13, 30, tzinfo=UTC)
FLAT = datetime(2026, 9, 28, 19, 50, tzinfo=UTC)


def bar(i, o, h, l, c, base=OPEN):
    return {"t": (base + timedelta(minutes=i)).isoformat(), "o": o, "h": h, "l": l, "c": c, "v": 100}


def flat_bars(n, px=10.0, base=OPEN):
    return [bar(i, px, px, px, px, base) for i in range(n)]


def test_policy_fingerprint_is_stable():
    assert V.VR_PAPER_VERSION == "VR_PAPER_V1"
    assert V.policy_fingerprint() == V.policy_fingerprint()
    assert len(V.policy_fingerprint()) == 16


def test_virtual_clock_hides_unclosed_and_future_bars():
    c = V.VirtualClock(flat_bars(10))
    T = OPEN + timedelta(minutes=4)                        # bars 13:30..13:33 are closed; 13:34 is not
    vis = c.visible(T)
    assert len(vis) == 4 and all(V.ts(b["t"]) + timedelta(minutes=1) <= T for b in vis)
    assert c.visible(T + timedelta(seconds=59)) == vis    # the 13:34 bar still open


def test_future_bars_cannot_change_geometry_at_decision():
    past = [bar(i, 10, 10.05, 9.95, 10) for i in range(40)]
    fut_calm = past + [bar(40 + i, 10, 10.01, 9.99, 10) for i in range(30)]
    fut_wild = past + [bar(40 + i, 10, 15, 5, 10) for i in range(30)]
    T = OPEN + timedelta(minutes=40)
    g1 = V.geometry(10.0, V.VirtualClock(fut_calm).visible(T), None)
    g2 = V.geometry(10.0, V.VirtualClock(fut_wild).visible(T), None)
    assert g1 == g2 and g1 is not None


def test_entry_is_next_bar_open_never_an_already_closed_bar():
    bars = [bar(i, 10 + i, 10 + i, 10 + i, 10 + i) for i in range(20)]
    c = V.VirtualClock(bars)
    M = OPEN + timedelta(minutes=5, seconds=10)            # decision mid-bar -> next bar starting >= M = 13:36
    eb = c.next_bar_starting_at_or_after(M)
    assert V.ts(eb["t"]) == OPEN + timedelta(minutes=6) and eb["o"] == 16


def _trade(stop, target, entry=10.0, direction="LONG"):
    return V.Trade("X", "VIRTUAL_REALTIME", direction, OPEN + timedelta(minutes=1), entry, stop, target)


def test_stop_hit_fills_at_stop_and_before_target_in_same_bar():
    bars = flat_bars(1) + [bar(1, 10, 10.2, 9.8, 10), bar(2, 10, 12, 8, 10)]
    r = V.run_exit(_trade(9.5, 11.0), V.VirtualClock(bars), FLAT)
    assert r["exit_reason"] == "STOP_HIT" and r["exit_px"] == 9.5 and r["holding_bars"] == 2


def test_target_hit_and_gap_through_fills_at_open():
    bars = flat_bars(1) + [bar(1, 10, 10.1, 9.9, 10), bar(2, 11.5, 11.6, 11.4, 11.5)]
    r = V.run_exit(_trade(9.0, 11.0), V.VirtualClock(bars), FLAT)
    assert r["exit_reason"] == "TARGET_HIT" and r["exit_px"] == 11.5      # gapped above: filled at the open
    assert r["gross"] == pytest.approx(0.15)


def test_session_close_exit_at_last_bar_before_flatten():
    bars = flat_bars(1) + [bar(i, 10, 10.1, 9.9, 10 + 0.001 * i) for i in range(1, 30)]
    flat = OPEN + timedelta(minutes=10)
    r = V.run_exit(_trade(9.0, 11.0), V.VirtualClock(bars), flat)
    assert r["exit_reason"] == "SESSION_CLOSE" and r["exit_t"] == flat
    assert r["exit_px"] == pytest.approx(10.009)


def test_flatten_time_is_1550_et():
    assert V.flatten_utc(datetime(2026, 9, 28, 20, 0, tzinfo=UTC)) == datetime(2026, 9, 28, 19, 50, tzinfo=UTC)
    assert V.flatten_utc(datetime(2026, 11, 27, 18, 0, tzinfo=UTC)) == datetime(2026, 11, 27, 18, 0, tzinfo=UTC)


def test_short_reference_is_mirror():
    bars = flat_bars(1) + [bar(1, 10, 10.1, 8.9, 9)]
    r = V.run_exit(_trade(11.0, 9.0, direction="SHORT"), V.VirtualClock(bars), FLAT)
    assert r["exit_reason"] == "TARGET_HIT" and r["gross"] == pytest.approx(0.1)


def test_cost_model_matches_forensic_contract():
    from talonx_paperperf import vr_replay as R
    assert R.V_cost(None) == pytest.approx(0.002)
    assert R.V_cost(10) == pytest.approx(0.002)
    assert R.V_cost(60) == pytest.approx(0.006)


def test_capital_reservation_and_max_positions():
    t0 = OPEN
    rows = [{"entry_t": t0 + timedelta(seconds=i), "exit_t": t0 + timedelta(hours=1), "gross": 0.01, "net": 0.008}
            for i in range(15)]
    p = V.portfolio(rows)
    assert p["trades_taken"] == 10 and p["skipped_capacity"] == 5
    assert p["capital_utilization_mean"] <= 1.0
    assert p["ending_capital"] == pytest.approx(100_000 + 10 * 10_000 * 0.008)


def test_cash_released_only_after_exit():
    t0 = OPEN
    rows = [{"entry_t": t0, "exit_t": t0 + timedelta(minutes=5), "gross": 0.0, "net": 0.0}] * 10 + \
           [{"entry_t": t0 + timedelta(minutes=5, seconds=1), "exit_t": t0 + timedelta(minutes=9), "gross": 0, "net": 0}]
    assert V.portfolio(rows)["trades_taken"] == 11


def test_pullback_entry_is_causal_and_deterministic():
    bars = [bar(i, 10, 10, 10, 10) for i in range(10)] + [bar(10, 10, 10.2, 10, 10.2), bar(11, 10.2, 10.2, 10.0, 10.05),
                                                         bar(12, 10.05, 10.3, 10.05, 10.25), bar(13, 11, 11, 11, 11)]
    c = V.VirtualClock(bars)
    M = OPEN + timedelta(minutes=10)
    pe = V.pullback_entry(c, M, 10.0, 0.01, "RECLAIM_PRIOR_BAR_HIGH", OPEN, FLAT)
    assert pe == (OPEN + timedelta(minutes=13), 10.25)     # decided at the 13:42 bar's close; entry next bar open
    assert pe == V.pullback_entry(c, M, 10.0, 0.01, "RECLAIM_PRIOR_BAR_HIGH", OPEN, FLAT)


def test_same_input_deterministic_trade():
    bars = [bar(i, 10, 10.05, 9.95, 10) for i in range(60)]
    c = V.VirtualClock(bars)
    a = V.open_trade("X", "VIRTUAL_REALTIME", c, OPEN + timedelta(minutes=30), 10.0, None, OPEN, FLAT)
    b = V.open_trade("X", "VIRTUAL_REALTIME", c, OPEN + timedelta(minutes=30), 10.0, None, OPEN, FLAT)
    assert a == b and a["status"] == "OPENED"
