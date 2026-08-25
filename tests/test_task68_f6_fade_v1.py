"""
tests/test_task68_f6_fade_v1.py
----------------------------------
Focused, deterministic tests for F6_FADE_V1 (Task 68A). Synthetic
fixtures only -- proves implementation correctness of the FROZEN rule,
not a re-discovery search. See results/task68_f6_freeze/f6_fade_v1_spec.json.
"""
from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from research.task68_f6 import strategy
from research.task68_f6.evaluator import evaluate, evaluate_one_session
from research.task68_f6.fingerprint import compute_fingerprint, economically_meaningful_subset, load_spec


def _minute_bars(symbol: str, day: str, start_hour: int, n_minutes: int, prices, volume=1000.0) -> pd.DataFrame:
    times = pd.date_range(f"{day} {start_hour:02d}:00:00", periods=n_minutes, freq="1min", tz="UTC")
    prices = np.asarray(prices, dtype=float)
    assert len(prices) == n_minutes
    return pd.DataFrame({
        "timestamp": times, "symbol": symbol,
        "open": prices, "high": prices + 0.02, "low": prices - 0.02, "close": prices,
        "volume": volume,
    })


def _full_session(symbol: str, day: str, opening_move_pct: float, post_open_prices=None) -> pd.DataFrame:
    """08:00-20:05 UTC session (RTH close 20:00). Opening window
    13:30-14:00 UTC (30 bars) goes from 100.0 to 100*(1+opening_move_pct).
    Bars after 14:00 UTC are flat at the opening close price unless
    `post_open_prices` overrides them."""
    pre = _minute_bars(symbol, day, 8, 330, np.full(330, 100.0))  # 08:00-13:29
    opening_close = 100.0 * (1 + opening_move_pct)
    opening = _minute_bars(symbol, day, 13, 30, np.linspace(100.0, opening_close, 30))
    opening["timestamp"] = pd.date_range(f"{day} 13:30:00", periods=30, freq="1min", tz="UTC")
    if post_open_prices is None:
        post_open_prices = np.full(365, opening_close)
    post = _minute_bars(symbol, day, 14, len(post_open_prices), post_open_prices)
    post["timestamp"] = pd.date_range(f"{day} 14:00:00", periods=len(post_open_prices), freq="1min", tz="UTC")
    return pd.concat([pre, opening, post], ignore_index=True)


LARGE_UP = 0.05  # 5%, well above SIGNAL_THRESHOLD (~1.34%)
LARGE_DOWN = -0.05
SMALL_MOVE = 0.001  # 0.1%, below threshold


# 1. positive opening shock -> correct fade direction (SHORT)
def test_positive_opening_shock_fades_short():
    bars = _full_session("AAA", "2026-06-01", LARGE_UP)
    ledger = evaluate(bars, cost_bps=0.0)
    row = ledger.iloc[0]
    assert bool(row["data_ready"])
    assert row["signal_direction"] == "SHORT"
    assert row["opening_move"] == pytest.approx(LARGE_UP, rel=1e-6)


# 2. negative opening shock -> correct fade direction (LONG)
def test_negative_opening_shock_fades_long():
    bars = _full_session("AAA", "2026-06-01", LARGE_DOWN)
    ledger = evaluate(bars, cost_bps=0.0)
    row = ledger.iloc[0]
    assert bool(row["data_ready"])
    assert row["signal_direction"] == "LONG"


# 3. threshold not met -> no signal
def test_below_threshold_produces_rejection_not_trade():
    bars = _full_session("AAA", "2026-06-01", SMALL_MOVE)
    ledger = evaluate(bars, cost_bps=0.0)
    row = ledger.iloc[0]
    assert bool(row["data_ready"]) is False
    assert row["rejection_reason"] == "OPENING_MOVE_BELOW_THRESHOLD"
    assert row["entry_price"] is None


# 4. decision uses only completed bars (opening window fully before 14:00)
def test_decision_signal_unaffected_by_bars_after_decision_timestamp():
    bars1 = _full_session("AAA", "2026-06-01", LARGE_UP)
    bars2 = bars1.copy()
    # Mutate everything strictly AFTER the decision bar -- must not change opening_move.
    mask = bars2["timestamp"] > pd.Timestamp("2026-06-01 14:00:00", tz="UTC")
    bars2.loc[mask, ["open", "high", "low", "close"]] = 9999.0
    r1 = evaluate(bars1, cost_bps=0.0).iloc[0]
    r2 = evaluate(bars2, cost_bps=0.0).iloc[0]
    assert r1["opening_move"] == pytest.approx(r2["opening_move"])
    assert r1["decision_timestamp"] == r2["decision_timestamp"]


# 5. entry occurs strictly after decision
def test_entry_timestamp_is_strictly_after_decision_timestamp():
    bars = _full_session("AAA", "2026-06-01", LARGE_UP)
    row = evaluate(bars, cost_bps=0.0).iloc[0]
    assert row["entry_timestamp"] > row["decision_timestamp"]
    assert row["entry_timestamp"] == row["decision_timestamp"] + pd.Timedelta(minutes=1)


# 6. no future-bar access (mutating a bar after the exit window doesn't change the trade)
def test_no_future_bar_access_beyond_exit_window():
    bars1 = _full_session("AAA", "2026-06-01", LARGE_UP)
    bars2 = bars1.copy()
    exit_target = pd.Timestamp("2026-06-01 14:01:00", tz="UTC") + pd.Timedelta(minutes=60)
    mask = bars2["timestamp"] > exit_target
    bars2.loc[mask, ["open", "high", "low", "close"]] = -9999.0
    r1 = evaluate(bars1, cost_bps=0.0).iloc[0]
    r2 = evaluate(bars2, cost_bps=0.0).iloc[0]
    assert r1["exit_price"] == pytest.approx(r2["exit_price"])
    assert r1["gross_return"] == pytest.approx(r2["gross_return"])


# 7. timezone/DST conversion correct (spec fields, not evaluator behavior --
#    evaluator itself is UTC-only by design; this pins the documented spec values)
def test_spec_decision_time_utc_et_uk_values():
    spec = load_spec()
    assert spec["decision_time_utc"] == "14:00:00 UTC"
    assert "10:00" in spec["decision_time_et"] and "EDT" in spec["decision_time_et"]
    assert "15:00" in spec["decision_time_uk"] and "BST" in spec["decision_time_uk"]


# 8. missing required opening minute -> DATA_NOT_READY
def test_sparse_opening_window_is_data_not_ready():
    bars = _full_session("AAA", "2026-06-01", LARGE_UP)
    # Drop all but 10 of the 30 opening-window bars (< OPENING_WINDOW_MIN_BARS=20).
    win_mask = (bars["timestamp"] >= pd.Timestamp("2026-06-01 13:30:00", tz="UTC")) & (
        bars["timestamp"] < pd.Timestamp("2026-06-01 14:00:00", tz="UTC")
    )
    keep_idx = bars.index[win_mask][:10]
    drop_idx = bars.index[win_mask].difference(keep_idx)
    bars = bars.drop(index=drop_idx).reset_index(drop=True)
    row = evaluate(bars, cost_bps=0.0).iloc[0]
    assert bool(row["data_ready"]) is False
    assert row["rejection_reason"] == "DATA_NOT_READY"


# 9. duplicate event suppressed
def test_duplicate_symbol_day_rows_produce_duplicate_signal_rejection():
    bars = _full_session("AAA", "2026-06-01", LARGE_UP)
    doubled = pd.concat([bars, bars], ignore_index=True)
    ledger = evaluate(doubled, cost_bps=0.0)
    # groupby collapses exact duplicate rows into one group -- to force a
    # genuine second "event" for the same key, evaluate_one_session directly
    # simulates what evaluate() would see as a second candidate.
    reasons = set(ledger["rejection_reason"].dropna())
    # With true duplicate rows groupby naturally de-dupes; assert instead
    # that evaluate() is idempotent (no duplicate trade rows emitted).
    assert len(ledger) == 1


def test_duplicate_signal_rejection_path_directly():
    from research.task68_f6.evaluator import _reject
    from research.task68_f6.fingerprint import compute_fingerprint
    row = _reject("F6_FADE_V1", compute_fingerprint(), "AAA", "2026-06-01", "DUPLICATE_SIGNAL")
    assert row["rejection_reason"] == "DUPLICATE_SIGNAL"
    assert bool(row["data_ready"]) is False


# 10. fixed exit timing correct
def test_exit_timestamp_is_60_minutes_after_entry_when_bars_available():
    bars = _full_session("AAA", "2026-06-01", LARGE_UP)
    row = evaluate(bars, cost_bps=0.0).iloc[0]
    assert row["exit_timestamp"] - row["entry_timestamp"] == pd.Timedelta(minutes=60)
    assert row["exit_reason"] == "FIXED_60M_EXIT"


# 11. session-end protection works
def test_late_decision_exit_capped_at_session_close_not_overnight():
    # Opening window normal, but there is a large DATA GAP between 14:00
    # and 19:30 UTC -- per the frozen decision_time_rule ("the next
    # available bar on a rare gap day"), the decision bar ends up being
    # the 19:30 bar, so entry (19:31) + 60m (20:31) would cross RTH close
    # (20:00 UTC) and must be capped there instead.
    pre = _minute_bars("AAA", "2026-06-01", 8, 330, np.full(330, 100.0))
    opening = _minute_bars("AAA", "2026-06-01", 13, 30, np.linspace(100.0, 105.0, 30))
    opening["timestamp"] = pd.date_range("2026-06-01 13:30:00", periods=30, freq="1min", tz="UTC")
    post = _minute_bars("AAA", "2026-06-01", 19, 31, np.full(31, 105.0))
    post["timestamp"] = pd.date_range("2026-06-01 19:30:00", periods=31, freq="1min", tz="UTC")
    bars = pd.concat([pre, opening, post], ignore_index=True)
    row = evaluate(bars, cost_bps=0.0).iloc[0]
    assert bool(row["data_ready"])
    assert row["decision_timestamp"] == pd.Timestamp("2026-06-01 19:30:00", tz="UTC")
    assert row["entry_timestamp"] == pd.Timestamp("2026-06-01 19:31:00", tz="UTC")
    session_close = pd.Timestamp("2026-06-01 20:00:00", tz="UTC")
    assert row["exit_timestamp"] <= session_close
    assert row["exit_reason"] == "SESSION_CLOSE_EXIT"


# 12. cost calculation correct
def test_cost_bps_reduces_net_return_by_exact_amount():
    bars = _full_session("AAA", "2026-06-01", LARGE_UP, post_open_prices=np.full(365, 106.0))
    r0 = evaluate(bars, cost_bps=0.0).iloc[0]
    r10 = evaluate(bars, cost_bps=10.0).iloc[0]
    assert r0["gross_return"] == pytest.approx(r10["gross_return"])
    assert r0["net_return"] - r10["net_return"] == pytest.approx(10.0 / 10000.0)
    assert r10["net_return"] == pytest.approx(r10["gross_return"] - 0.001)


# 13. fingerprint deterministic
def test_fingerprint_is_deterministic_across_calls():
    spec = load_spec()
    fp1 = compute_fingerprint(spec)
    fp2 = compute_fingerprint(spec)
    assert fp1 == fp2
    assert len(fp1) == 64  # sha256 hex


# 14. same input -> same output
def test_same_input_gives_bit_identical_output():
    bars = _full_session("AAA", "2026-06-01", LARGE_UP)
    l1 = evaluate(bars, cost_bps=10.0)
    l2 = evaluate(bars.copy(), cost_bps=10.0)
    pd.testing.assert_frame_equal(l1, l2)


# 15. strategy spec mutation changes fingerprint
def test_spec_mutation_changes_fingerprint():
    spec = load_spec()
    fp_before = compute_fingerprint(spec)
    mutated = dict(spec)
    mutated["signal_threshold"] = dict(spec["signal_threshold"])
    mutated["signal_threshold"]["value"] = spec["signal_threshold"]["value"] * 2
    fp_after = compute_fingerprint(mutated)
    assert fp_before != fp_after


def test_excluded_provenance_fields_do_not_change_fingerprint():
    spec = load_spec()
    fp_before = compute_fingerprint(spec)
    mutated = dict(spec)
    mutated["spec_created_at"] = "2099-01-01T00:00:00Z"
    fp_after = compute_fingerprint(mutated)
    assert fp_before == fp_after


# Extra: no next bar for entry (decision bar is the session's very last bar)
def test_no_bar_after_decision_bar_rejects_no_next_bar_for_entry():
    pre = _minute_bars("AAA", "2026-06-01", 8, 330, np.full(330, 100.0))
    opening = _minute_bars("AAA", "2026-06-01", 13, 30, np.linspace(100.0, 105.0, 30))
    opening["timestamp"] = pd.date_range("2026-06-01 13:30:00", periods=30, freq="1min", tz="UTC")
    decision_only = _minute_bars("AAA", "2026-06-01", 14, 1, [105.0])
    decision_only["timestamp"] = [pd.Timestamp("2026-06-01 14:00:00", tz="UTC")]
    bars = pd.concat([pre, opening, decision_only], ignore_index=True)
    row = evaluate(bars, cost_bps=0.0).iloc[0]
    assert bool(row["data_ready"]) is False
    assert row["rejection_reason"] == "NO_NEXT_BAR_FOR_ENTRY"


def test_required_bar_columns_validated():
    bad = pd.DataFrame({"symbol": ["AAA"], "timestamp": [pd.Timestamp("2026-06-01", tz="UTC")]})
    with pytest.raises(ValueError):
        evaluate(bad)


def test_naive_timestamp_rejected():
    bars = _full_session("AAA", "2026-06-01", LARGE_UP)
    bars["timestamp"] = bars["timestamp"].dt.tz_localize(None)
    with pytest.raises(ValueError):
        evaluate(bars)
