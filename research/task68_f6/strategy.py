"""
research/task68_f6/strategy.py
--------------------------------
Frozen constants for F6_FADE_V1. These MUST match
results/task68_f6_freeze/f6_fade_v1_spec.json exactly -- this module is a
convenience for the evaluator/tests, the JSON spec is the source of truth
(see f6_fade_v1_fingerprint.json's mutation-detection contract).

Do not tune, retune, or parameter-sweep any value here after the spec was
frozen (results/task68_f6_freeze/f6_fade_v1_fingerprint.json). Changing
any of these constants changes the fingerprint.
"""
from __future__ import annotations

STRATEGY_ID = "F6_FADE_V1"
STRATEGY_VERSION = "1.0.0"

# Opening information window: [13:30, 14:00) UTC.
OPENING_START_MINUTES = 13 * 60 + 30
OPENING_END_MINUTES = 14 * 60
OPENING_WINDOW_MIN_BARS = 20  # of a nominal 30 -- identical to Task 67B family_06

# Frozen signal threshold: exact 2/3 (top-tertile) quantile of
# |opening_return| across the DEVELOPMENT dataset, computed once and
# frozen -- NEVER recomputed against whatever dataset the evaluator is
# later pointed at. See f6_fade_v1_spec.json's signal_threshold.derivation.
SIGNAL_THRESHOLD = 0.013391316345271645

# Decision anchor: first bar at/after 14:00:00 UTC for a given
# (symbol, trading_day).
DECISION_ANCHOR_MINUTES = 14 * 60

# Fixed holding period, minutes, from entry (see spec's holding_period_rationale).
HOLDING_PERIOD_MINUTES = 60

# RTH close, UTC hour -- no position held past this (session-end protection).
SESSION_CLOSE_UTC_HOUR = 20

# No stop-loss (see spec's stop_rule). Pure fixed-time exit.
STOP_RULE = None

# Normalized notional sizing -- no risk-based position sizing model exists.
SIZING_UNIT = 1.0

MAX_POSITIONS_PER_SYMBOL_SESSION = 1
PYRAMIDING_ALLOWED = False
OVERNIGHT_ALLOWED = False

PRIMARY_COST_BPS = 10.0
DIAGNOSTIC_COST_BPS = (0.0, 5.0, 10.0)

REQUIRED_BAR_COLUMNS = ("symbol", "timestamp", "open", "high", "low", "close", "volume")

REJECTION_REASONS = (
    "DATA_NOT_READY",
    "OPENING_MOVE_BELOW_THRESHOLD",
    "NO_NEXT_BAR_FOR_ENTRY",
    "NO_VALID_EXIT",
    "DUPLICATE_SIGNAL",
)


def trade_direction(opening_return: float) -> int:
    """FADE semantics: +1 (long) when opening_return < 0 (fade a down-open),
    -1 (short) when opening_return > 0 (fade an up-open). 0 (no trade) only
    if opening_return is exactly 0.0 (should never fire -- would fail the
    |signal| >= SIGNAL_THRESHOLD > 0 condition first)."""
    if opening_return > 0:
        return -1
    if opening_return < 0:
        return 1
    return 0
