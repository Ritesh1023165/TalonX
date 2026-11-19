"""PAPER_SIGNAL profitability forensics: horizon resolution, no carry past the close, costs, portfolio capacity,
concentration. No network."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

from talonx_paperperf import signal_forensics as F

UTC = timezone.utc
CLOSE = datetime(2026, 9, 28, 20, 0, tzinfo=UTC)


def bars(start, prices):
    return [{"t": (start + timedelta(minutes=i)).isoformat().replace("+00:00", "Z"), "o": p, "h": p * 1.01,
             "l": p * 0.99, "c": p, "v": 100} for i, p in enumerate(prices)]


def test_horizons_use_bars_completed_by_entry_plus_h_and_never_carry_past_the_close():
    t0 = datetime(2026, 9, 28, 19, 20, tzinfo=UTC)
    b = bars(t0, [10.0 + 0.1 * i for i in range(40)])             # 19:20 .. 19:59
    o = F.outcome(b, t0, 10.0, CLOSE, CLOSE)
    assert round(o["r15"], 6) == round(b[14]["c"] / 10.0 - 1, 6)    # last bar completed by 19:35 = the 19:34 bar
    assert o["r60"] is None and o["s60"] == "UNRESOLVED_AFTER_CLOSE"
    assert round(o["rclose"], 6) == round(b[-1]["c"] / 10.0 - 1, 6)
    assert o["mfe"] > 0 and o["mae"] < 0


def test_live_mode_marks_future_horizons_pending():
    t0 = datetime(2026, 9, 28, 14, 0, tzinfo=UTC)
    b = bars(t0, [10.0] * 20)
    o = F.outcome(b, t0, 10.0, CLOSE, t0 + timedelta(minutes=20))
    assert o["s15"] == "OK" and o["s30"] == "PENDING" and o["sclose"] == "PENDING" and o["rclose"] is None


def test_cost_is_max_of_v2_friction_and_measured_spread():
    r = {"act_r30": 0.01, "cost_frac": max(F.V2_FRICTION_BPS, 60.0) / 1e4}
    assert abs(F.net(r, "act", "30") - (0.01 - 0.006)) < 1e-12
    r2 = {"act_r30": 0.01, "cost_frac": max(F.V2_FRICTION_BPS, 5.0) / 1e4}
    assert abs(F.net(r2, "act", "30") - (0.01 - 0.002)) < 1e-12


def _row(i, ret, minute):
    t = datetime(2026, 9, 28, 14, 0, tzinfo=UTC) + timedelta(minutes=minute)
    return {"symbol": f"S{i}", "window_id": "2026-09-28", "act_entry_utc": t.isoformat(), "act_r30": ret,
            "cost_frac": 0.002, "data_as_of_utc": t.isoformat()}


def test_portfolio_respects_max_concurrent_and_equal_dollar_sizing():
    rows = [_row(i, 0.01, 0) for i in range(12)]                    # 12 simultaneous entries, cap 10
    p = F.portfolio(rows, "30")
    assert p["trades"] == 10 and p["skipped_capacity"] == 2
    assert abs(p["NET_PNL"] - 10 * (0.01 - 0.002) * F.POSITION_USD) < 1e-6
    later = rows + [_row(99, -0.02, 31)]                            # after the first batch exits
    assert F.portfolio(later, "30")["trades"] == 11


def test_concentration_removes_best_trades():
    rows = [_row(0, 0.10, 0), _row(1, -0.01, 1), _row(2, -0.01, 2)]
    c = F.concentration(rows, "30")
    assert c["best"][0] == "S0" and c["total_without_best_1_pct_sum"] < 0 < c["total_net_pct_sum"]
