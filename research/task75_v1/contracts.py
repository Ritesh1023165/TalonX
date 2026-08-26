"""Task75A Part 2 -- frozen strategy contract for
CROSS_SECTIONAL_EXTREME_WINNER_SHORT_REVERSION_V1. Every field was
chosen from already-computed Task74B DEVELOPMENT evidence
(results/task74_alpha_discovery_v2/cell_results.csv, anchor cell
FAMILY_B_MULTIDAY/REVERSAL/SHORT/loose/3D). No new development P&L was
optimized to pick these. Do not modify after fingerprint.py's hash is
committed -- any semantic change requires a new version (V2).
"""
from __future__ import annotations

STRATEGY_ID = "CROSS_SECTIONAL_EXTREME_WINNER_SHORT_REVERSION"
STRATEGY_VERSION = "V1"
DIRECTION = "SHORT_ONLY"
HORIZON_PRODUCT_MAPPING = "MULTI_DAY"

# --- Universe / benchmark ---------------------------------------------
MARKET_SYMBOL = "SPY"
UNIVERSE = [
    "AAPL", "MSFT", "NVDA", "AMZN", "META", "AMD", "TSLA", "GOOGL", "PYPL", "STX",
    "ADBE", "ADI", "AMAT", "AVGO", "BKNG", "CMCSA", "COST", "CSCO", "GILD", "HON",
    "INTC", "INTU", "ISRG", "KLAC", "LRCX", "MDLZ", "MU", "NFLX", "PANW", "PEP",
    "QCOM", "REGN", "SBUX", "TXN", "VRTX",
]

# --- Signal --------------------------------------------------------------
LOOKBACK_TRADING_DAYS = 3
# Reason: Task74B's own predeclared, non-tuned choice (research_design_lock_v2.json) --
# not re-optimized here.
RANK_METHOD = "average"  # pandas .rank(pct=True) default: ties share the mean rank
UPPER_PERCENTILE = 0.80
# "TOP 20%" (Task74B's own "loose" band) -- inclusive boundary: rank >= 0.80 qualifies.
BOUNDARY_INCLUSIVE = True
MIN_CROSS_SECTIONAL_BREADTH = 10
# Below this many symbols with a valid value on a given Day0, that day's rank
# is not computed at all (DATA_NOT_READY for every symbol that day) -- a
# degenerate small cross-section is never used to rank.

# --- Decision / entry / exit --------------------------------------------
DECISION_POINT = "Day0 close (after the session is complete)"
ENTRY_RULE = "Day1 (the FIRST canonical SPY trading session strictly after Day0) OPEN, SHORT"
EXIT_HORIZON_TRADING_DAYS = 3
# "3rd canonical trading day inclusive of the entry day" -- i.e. exit at the
# close of entry_day + 2 additional canonical sessions (positions 0,1,2 of a
# 3-day span starting at the entry day).
EXIT_RULE = "Close of the 3rd canonical trading day counting the entry day as day 1"
ENTRY_PRICE_SOURCE = "First regular-session (09:30 ET) bar OPEN of the canonical entry day"
EXIT_PRICE_SOURCE = "Last regular-session bar CLOSE of the canonical exit day"

# --- Calendar --------------------------------------------------------------
TIMEZONE = "America/New_York"
CANONICAL_CALENDAR_SOURCE = "SPY's own observed regular-session trading-day set within the materialized dataset -- see calendar_session_contract.json"
ONE_SIGNAL_PER_SYMBOL_PER_DECISION_DAY = True

# --- Missing-data / fail-closed semantics -----------------------------------
REJECTION_REASONS = (
    "DATA_NOT_READY",                     # trailing lookback or SPY window incomplete
    "INSUFFICIENT_CROSS_SECTIONAL_BREADTH",  # fewer than MIN_CROSS_SECTIONAL_BREADTH valid symbols that day
    "THRESHOLD_NOT_MET",                  # rank < UPPER_PERCENTILE
    "SYMBOL_MISSING_REQUIRED_SESSION",    # a required canonical session is absent for this symbol
    "SPY_CALENDAR_NOT_ESTABLISHED",       # SPY itself lacks a session at a boundary
)
FAIL_CLOSED = True
NO_SYNTHETIC_BARS = True

# --- Risk / portfolio (see risk_policy.json / portfolio_construction.json) --
STOP_STATUS = "CATASTROPHIC_STOP_FROZEN"
STOP_DISTANCE_PCT = 15.0
# Reason: Task74B's own risk_diagnostics.csv (anchor cell) shows MAE (in units
# of 1% of entry price) at the 95th percentile ~10.07 and 99th ~16.28 -- 15%
# is a conservative round buffer just above the 95th percentile, sized as
# catastrophic short-squeeze containment, NOT selected by maximizing
# DEVELOPMENT P&L (no stop grid was run).

# --- Costs (see execution_cost_contract.json) -------------------------------
PRIMARY_ALL_IN_COST_BPS = 25.0
DIAGNOSTIC_COST_LEVELS_BPS = (0, 5, 10, 15, 20)

# --- Provider ----------------------------------------------------------
PROVIDER = "alpaca"
PROVIDER_FEED_RESEARCH = "SIP (account default)"
PROVIDER_FEED_LIVE = "IEX"
PROVIDER_PARITY_PROVEN = False
DATA_ADJUSTMENT = "raw (UNADJUSTED -- see corporate_action_policy.json; Task75B is BLOCKED pending a corporate-action-safe dataset)"


def contract_dict() -> dict:
    return {
        "strategy_id": STRATEGY_ID,
        "strategy_version": STRATEGY_VERSION,
        "direction": DIRECTION,
        "horizon_product_mapping": HORIZON_PRODUCT_MAPPING,
        "market_symbol": MARKET_SYMBOL,
        "universe": list(UNIVERSE),
        "lookback_trading_days": LOOKBACK_TRADING_DAYS,
        "rank_method": RANK_METHOD,
        "upper_percentile": UPPER_PERCENTILE,
        "boundary_inclusive": BOUNDARY_INCLUSIVE,
        "min_cross_sectional_breadth": MIN_CROSS_SECTIONAL_BREADTH,
        "decision_point": DECISION_POINT,
        "entry_rule": ENTRY_RULE,
        "exit_horizon_trading_days": EXIT_HORIZON_TRADING_DAYS,
        "exit_rule": EXIT_RULE,
        "entry_price_source": ENTRY_PRICE_SOURCE,
        "exit_price_source": EXIT_PRICE_SOURCE,
        "timezone": TIMEZONE,
        "canonical_calendar_source": CANONICAL_CALENDAR_SOURCE,
        "one_signal_per_symbol_per_decision_day": ONE_SIGNAL_PER_SYMBOL_PER_DECISION_DAY,
        "rejection_reasons": list(REJECTION_REASONS),
        "fail_closed": FAIL_CLOSED,
        "no_synthetic_bars": NO_SYNTHETIC_BARS,
        "stop_status": STOP_STATUS,
        "stop_distance_pct": STOP_DISTANCE_PCT,
        "primary_all_in_cost_bps": PRIMARY_ALL_IN_COST_BPS,
        "diagnostic_cost_levels_bps": list(DIAGNOSTIC_COST_LEVELS_BPS),
        "provider": PROVIDER,
        "provider_feed_research": PROVIDER_FEED_RESEARCH,
        "provider_feed_live": PROVIDER_FEED_LIVE,
        "provider_parity_proven": PROVIDER_PARITY_PROVEN,
        "data_adjustment": DATA_ADJUSTMENT,
    }
