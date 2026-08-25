"""
research/task68_f6/evaluator.py
----------------------------------
F6_FADE_V1 evaluator. Isolated research code -- NOT wired into any
production runtime path. See results/task68_f6_freeze/f6_fade_v1_spec.json
for the frozen contract this implements exactly.

INPUT CONTRACT: a pandas DataFrame with at least symbol/timestamp/open/
high/low/close/volume, timestamp UTC tz-aware, deterministically orderable.
Any symbol/session is evaluated independently of any other -- no
cross-session state.

OUTPUT CONTRACT: evaluate() returns one row per (symbol, trading_day)
candidate -- either a completed trade (data_ready=True, rejection_reason
=None) or an explicit rejection (data_ready=False, rejection_reason set).
Never a fabricated trade.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from research.task68_f6 import strategy
from research.task68_f6.fingerprint import compute_fingerprint, load_spec

_LEDGER_COLUMNS = [
    "strategy_id", "strategy_fingerprint", "symbol", "session_date", "opening_move",
    "signal_direction", "decision_timestamp", "entry_timestamp", "entry_price",
    "exit_timestamp", "exit_price", "gross_return", "cost_bps", "net_return",
    "exit_reason", "data_ready", "rejection_reason",
]


def _require_columns(bars: pd.DataFrame) -> None:
    missing = [c for c in strategy.REQUIRED_BAR_COLUMNS if c not in bars.columns]
    if missing:
        raise ValueError(f"Input bars missing required columns: {missing}")
    if bars["timestamp"].dt.tz is None:
        raise ValueError("Input bars['timestamp'] must be tz-aware (UTC).")


def _minutes_of_day(ts: pd.Series) -> pd.Series:
    return ts.dt.hour * 60 + ts.dt.minute


def _session_close_utc(day: pd.Timestamp) -> pd.Timestamp:
    return pd.Timestamp(day).normalize() + pd.Timedelta(hours=strategy.SESSION_CLOSE_UTC_HOUR)


def _row(**kwargs) -> dict:
    base = {c: None for c in _LEDGER_COLUMNS}
    base.update(kwargs)
    return base


def _reject(strategy_id, fingerprint, symbol, session_date, reason: str, opening_move=None) -> dict:
    return _row(
        strategy_id=strategy_id, strategy_fingerprint=fingerprint, symbol=symbol,
        session_date=session_date, opening_move=opening_move, data_ready=False,
        rejection_reason=reason,
    )


def evaluate_one_session(
    day_bars: pd.DataFrame, *, symbol: str, session_date, strategy_id: str, fingerprint: str,
    cost_bps: float,
) -> dict:
    """Evaluates ONE (symbol, trading_day)'s worth of bars (already
    restricted to that single symbol/day by the caller) against the
    frozen F6_FADE_V1 rule. Uses ONLY bars within `day_bars` -- never
    reaches into another day, never looks at a bar after the one it is
    currently reasoning about being "future" relative to a decision
    already made. Returns exactly one ledger row (trade or rejection).
    """
    day_bars = day_bars.sort_values("timestamp").reset_index(drop=True)
    mod = _minutes_of_day(day_bars["timestamp"])

    # 1. Opening window aggregate: [13:30, 14:00) UTC only.
    win_mask = (mod >= strategy.OPENING_START_MINUTES) & (mod < strategy.OPENING_END_MINUTES)
    window = day_bars.loc[win_mask]
    if len(window) < strategy.OPENING_WINDOW_MIN_BARS:
        return _reject(strategy_id, fingerprint, symbol, session_date, "DATA_NOT_READY")

    window_open = float(window["open"].iloc[0])
    window_close = float(window["close"].iloc[-1])
    if window_open == 0 or not np.isfinite(window_open) or not np.isfinite(window_close):
        return _reject(strategy_id, fingerprint, symbol, session_date, "DATA_NOT_READY")
    opening_move = (window_close - window_open) / window_open

    # 2. Threshold.
    if abs(opening_move) < strategy.SIGNAL_THRESHOLD:
        return _reject(strategy_id, fingerprint, symbol, session_date, "OPENING_MOVE_BELOW_THRESHOLD", opening_move)

    direction = strategy.trade_direction(opening_move)
    direction_label = "LONG" if direction == 1 else "SHORT"

    # 3. Decision bar: first bar at/after 14:00:00 UTC, uses only the
    #    already-completed opening-window signal above -- no lookahead.
    post_mask = mod >= strategy.DECISION_ANCHOR_MINUTES
    post = day_bars.loc[post_mask]
    if post.empty:
        return _reject(strategy_id, fingerprint, symbol, session_date, "DATA_NOT_READY", opening_move)
    decision_bar = post.iloc[0]
    decision_ts = decision_bar["timestamp"]

    # 4. Entry bar: STRICTLY the next bar after decision_bar (no same-bar
    #    lookahead -- decision and entry are never the same bar/price).
    after_decision = day_bars.loc[day_bars["timestamp"] > decision_ts]
    if after_decision.empty:
        return _reject(strategy_id, fingerprint, symbol, session_date, "NO_NEXT_BAR_FOR_ENTRY", opening_move)
    entry_bar = after_decision.iloc[0]
    entry_ts = entry_bar["timestamp"]
    entry_price = float(entry_bar["open"])

    # 5. Exit: fixed 60m from entry, capped at RTH close.
    session_close = _session_close_utc(entry_ts)
    exit_target = min(entry_ts + pd.Timedelta(minutes=strategy.HOLDING_PERIOD_MINUTES), session_close)
    exit_window = day_bars.loc[(day_bars["timestamp"] > entry_ts) & (day_bars["timestamp"] <= exit_target)]
    if exit_window.empty:
        return _reject(strategy_id, fingerprint, symbol, session_date, "NO_VALID_EXIT", opening_move)
    exit_bar = exit_window.iloc[-1]
    exit_ts = exit_bar["timestamp"]
    exit_price = float(exit_bar["close"])
    exit_reason = "SESSION_CLOSE_EXIT" if exit_target == session_close and exit_ts >= session_close else "FIXED_60M_EXIT"

    # 6. Returns.
    if direction == 1:
        gross_return = (exit_price - entry_price) / entry_price
    else:
        gross_return = (entry_price - exit_price) / entry_price
    net_return = gross_return - (cost_bps / 10000.0)

    return _row(
        strategy_id=strategy_id, strategy_fingerprint=fingerprint, symbol=symbol,
        session_date=session_date, opening_move=opening_move, signal_direction=direction_label,
        decision_timestamp=decision_ts, entry_timestamp=entry_ts, entry_price=entry_price,
        exit_timestamp=exit_ts, exit_price=exit_price, gross_return=gross_return,
        cost_bps=cost_bps, net_return=net_return, exit_reason=exit_reason,
        data_ready=True, rejection_reason=None,
    )


def evaluate(bars: pd.DataFrame, *, cost_bps: float = strategy.PRIMARY_COST_BPS) -> pd.DataFrame:
    """Top-level entry point: input contract -> output contract (ledger
    DataFrame, one row per symbol/trading_day candidate). Deterministic --
    same `bars` + same `cost_bps` always yields the same ledger."""
    _require_columns(bars)
    spec = load_spec()
    fingerprint = compute_fingerprint(spec)
    strategy_id = spec["strategy_id"]

    working = bars.copy()
    working["_trading_day"] = working["timestamp"].dt.normalize()

    rows: list[dict] = []
    seen_keys: set[tuple] = set()
    for (symbol, day), group in working.groupby(["symbol", "_trading_day"], sort=True):
        key = (symbol, day)
        if key in seen_keys:
            rows.append(_reject(strategy_id, fingerprint, symbol, day.date().isoformat(), "DUPLICATE_SIGNAL"))
            continue
        seen_keys.add(key)
        rows.append(evaluate_one_session(
            group, symbol=symbol, session_date=day.date().isoformat(),
            strategy_id=strategy_id, fingerprint=fingerprint, cost_bps=cost_bps,
        ))

    ledger = pd.DataFrame(rows, columns=_LEDGER_COLUMNS)
    return ledger
