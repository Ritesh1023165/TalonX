"""2026-10-08 paper-execution realism audit: CHARACTERISATION tests on synthetic bars. They pin what each lane's fill
model actually does today (no accounting / cost / rule change), so the audit's findings are reproducible."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

from talonx_opportunity.promotion import measure_long
from talonx_paper.engine import apply_spread, check_stop_take
from talonx_paperperf import vr_paper as V
from talonx_v2.sizing import size_whole_shares_fee_inclusive

UTC = timezone.utc
T0 = datetime(2026, 10, 6, 14, 0, tzinfo=UTC)


def bars(prices, start=T0):
    return [{"t": (start + timedelta(minutes=i)).isoformat(), "o": o, "h": h, "l": lo, "c": c, "v": 100}
            for i, (o, h, lo, c) in enumerate(prices)]


def test_promotion_markout_starts_at_the_data_timestamp_not_the_alert():
    """Promotion paper outcomes are markouts from the reference price at data_as_of (~15-20 min before the decision /
    Telegram send): a move that happened before anyone could act is counted. No cost is applied."""
    path = [(10, 10, 10, 10)] * 16 + [(11, 11, 11, 11)] * 60          # +10% jump at minute 16 (before a 16-min-late alert)
    m = measure_long(T0, 10.0, bars(path), T0 + timedelta(hours=6))
    assert m["ret_30m_pct"] == 10.0 and m["status"] == "CONFIRMED"     # credited although not actionable after the alert


def test_promotion_missing_bars_leave_the_horizon_pending_not_filled():
    m = measure_long(T0, 10.0, bars([(10, 10, 10, 10)] * 5), T0 + timedelta(hours=6))
    assert m["px_30m"] is None and m["ret_30m_pct"] is None and m["status"] == "OUTCOME_PENDING"


def test_vr_long_stop_gapped_through_fills_at_the_open_not_the_trigger():
    entry = T0
    path = [(10, 10.05, 9.98, 10)] * 3 + [(9.0, 9.1, 8.9, 9.0)]       # opens 10% below a 9.80 stop
    tr = V.Trade("X", "VIRTUAL_REALTIME", "LONG", entry, 10.0, 9.80, 10.50)
    r = V.run_exit(tr, V.VirtualClock(bars(path)), entry + timedelta(hours=5))
    assert r["exit_reason"] == "STOP_HIT" and r["exit_px"] == 9.0      # the worse gap price, not 9.80


def test_vr_intrabar_stop_fills_exactly_at_the_level_and_stop_wins_ties():
    path = [(10, 10.05, 9.98, 10), (10, 10.60, 9.70, 10.2)]             # same bar touches stop and target
    tr = V.Trade("X", "VIRTUAL_REALTIME", "LONG", T0, 10.0, 9.80, 10.50)
    r = V.run_exit(tr, V.VirtualClock(bars(path)), T0 + timedelta(hours=5))
    assert (r["exit_reason"], r["exit_px"]) == ("STOP_HIT", 9.80)      # level fill, no slippage beyond the level


def test_vr_no_bars_never_creates_an_exit():
    tr = V.Trade("X", "VIRTUAL_REALTIME", "LONG", T0, 10.0, 9.80, 10.50)
    assert V.run_exit(tr, V.VirtualClock([]), T0 + timedelta(hours=5)) == {"exit_reason": "NO_BARS"}


def test_original_exit_checks_the_tick_close_only_and_fills_at_close_less_half_spread():
    """Original (talonx_paper) evaluates stop/target on each market tick's CLOSE: an intrabar touch that closes back
    inside the band is not an exit; a gap-through close fills at that close (minus half the 5 bps simulated spread)."""
    assert check_stop_take(10.0, 9.85, 0.005, 0.01, stop_price=9.80, target_price=10.50) is None
    assert check_stop_take(10.0, 9.00, 0.005, 0.01, stop_price=9.80, target_price=10.50) == "STOP_LOSS"
    assert apply_spread(9.00, 5.0, "SELL") == 9.00 - 9.00 * 0.00025


def test_v2_live_paper_has_zero_fee_and_no_volume_cap():
    s = size_whole_shares_fee_inclusive(price=10.0, allocation_usd=10_000.0, available_cash=100_000.0)
    assert s.entry_fee == 0 and s.shares == 1000                         # 1000 shares regardless of the day's volume
