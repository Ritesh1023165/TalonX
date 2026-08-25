"""Task72 Part 5 -- frozen strategy contract for
IDIOSYNCRATIC_RESIDUAL_MOMENTUM_LONG_V1. Every field here was chosen from
already-computed Task71 DEVELOPMENT evidence (see
results/task71_structural_discovery/family_c_residual_momentum_summary.csv
and risk_stop_diagnostics.csv) -- NOTHING here was tuned against any
holdout outcome. Do not modify after fingerprint.py's hash is committed;
any semantic change after that point requires a new version (V2), per the
overnight task's own rule.
"""
from __future__ import annotations

STRATEGY_ID = "IDIOSYNCRATIC_RESIDUAL_MOMENTUM_LONG"
STRATEGY_VERSION = "V1"

DIRECTION = "LONG_ONLY"

# --- Signal --------------------------------------------------------------
DECISION_TIME_ET_HOUR = 11
DECISION_TIME_ET_MINUTE = 0
BETA_LOOKBACK_TRADING_DAYS = 20
MARKET_BENCHMARK_SYMBOL = "SPY"
RESIDUAL_THRESHOLD_PCT = 0.75
# Reason (Part 2): 0.75% was chosen over 1.50% for breadth/parameter
# stability/less selection pressure -- Task71 development: 0.75% => 217
# trades/35 symbols/26 days vs 1.50% => 93 trades/31 symbols/22 days, and
# ALL 8 cells (both bands x 4 horizons) were positive, so this is not
# cherry-picking the higher band, it is preferring the broader one.

# --- Entry -----------------------------------------------------------------
ENTRY_RULE = "FIRST_BAR_OPEN_STRICTLY_AFTER_DECISION_TIME"

# --- Exit horizon ----------------------------------------------------------
EXIT_HORIZON_MINUTES = 180
# Reason (Part 3): Task71's own family_c_residual_momentum_summary.csv shows
# EOD (net_10bps=0.1265%, PF=1.314, day-cluster ci_low=-0.120) and 180m
# (net_10bps=0.1302%, PF=1.390, day-cluster ci_low=-0.142) are both in the
# same broad positive plateau at threshold=0.75% with materially similar
# breadth (217 trades/35 symbols/26 days, identical -- both horizons share
# the same entry population). 180m is chosen over EOD for a strictly
# structural (not P&L-driven) reason: a fixed 180-minute holding period is
# deterministic and independent of the closing-auction mechanism, gives
# simpler offline/live parity and slippage measurement, and creates no
# overnight exposure -- matching the task's own stated preference. Day-
# cluster ci_low is marginally worse for 180m (-0.142 vs -0.120) and top1_day
# share is marginally higher (0.224 vs 0.155); neither is judged a MATERIAL
# robustness disadvantage (both remain inside the same broad positive
# plateau, both symbol-cluster CIs exclude zero, both signs are stable
# across all 3 regimes/segments per Task71), so the structural
# simplicity argument controls per the task's explicit tie-break rule.

# --- Stop --------------------------------------------------------------
STOP_DISTANCE_PCT = 2.5
# Reason (Part 4): Task71 DEVELOPMENT 90th-percentile MAE (across the
# already-computed primary-cell diagnostic, risk_stop_diagnostics.csv) is
# ~2.19%. 2.5% is a conservative rounded buffer above that observed
# DEVELOPMENT distribution, intended purely as catastrophic intraday risk
# containment -- NOT a profit-maximizing target/stop pair, and NOT
# searched/optimized against any P&L. No trailing stop. No take-profit
# target.
STOP_FILL_SEMANTICS = "CONSERVATIVE_GAP_AWARE"
# If the first subsequent 1m bar whose LOW breaches the stop price also
# gapped below it at its OPEN, fill at that bar's OPEN (never assume a
# fill better than the bar's own open permits). Otherwise fill exactly at
# the stop price. Stop is checked starting from the bar immediately AFTER
# the entry bar (the entry bar itself establishes the position; "first
# SUBSEQUENT bar" per the task's own wording).

# --- Session / eligibility ------------------------------------------------
RTH_ONLY = True
NO_OVERNIGHT_HOLDING = True
ONE_TRADE_PER_SYMBOL_PER_SESSION = True
# Guaranteed by construction: decision fires at most once per (symbol, day).

# --- Position sizing --------------------------------------------------------
POSITION_SIZING = "EQUAL_NOTIONAL_PER_TRADE_RESEARCH_ONLY"
# Research ledger reports PERCENT returns per trade (no compounding, no
# capital-at-risk model) -- this is a research/statistical evaluation, not
# a portfolio simulation. No real capital, no live sizing decision made
# here.

# --- Missing-data / fail-closed behavior ------------------------------------
REJECTION_REASONS = (
    "DATA_NOT_READY",           # beta not yet estimable (< BETA_LOOKBACK_TRADING_DAYS prior sessions)
    "NO_NEXT_BAR_FOR_ENTRY",    # no bar exists strictly after the decision timestamp that session
    "RESIDUAL_BELOW_THRESHOLD",  # signal did not fire (includes negative residual -- LONG_ONLY, no SHORT)
    "NO_VALID_EXIT",            # zero bars observed in [entry, horizon_end)
)
FAIL_CLOSED = True
# Any ambiguous/missing input causes a REJECTION row, never a fabricated
# trade. No interpolation, no forward-filling, no synthetic prices,
# anywhere in this pipeline.

# --- Costs -------------------------------------------------------------
PRIMARY_COST_BPS = 10
COST_DIAGNOSTIC_LEVELS_BPS = (0, 5, 10, 15, 20)

# --- Provider ----------------------------------------------------------
PROVIDER = "alpaca"
PROVIDER_FEED_RESEARCH = "SIP (account default, per Task63R/Task71 provider_semantics_assessment.json)"
PROVIDER_FEED_LIVE = "IEX"
PROVIDER_PARITY_PROVEN = False

UNIVERSE = [
    "AAPL", "MSFT", "NVDA", "AMZN", "META", "AMD", "TSLA", "GOOGL", "PYPL", "STX",
    "ADBE", "ADI", "AMAT", "AVGO", "BKNG", "CMCSA", "COST", "CSCO", "GILD", "HON",
    "INTC", "INTU", "ISRG", "KLAC", "LRCX", "MDLZ", "MU", "NFLX", "PANW", "PEP",
    "QCOM", "REGN", "SBUX", "TXN", "VRTX",
]


def contract_dict() -> dict:
    """Canonical, ordered dict of every frozen contract field -- the
    fingerprint hashes exactly this (via fingerprint.py's canonical JSON
    serialization). Keep key order stable; fingerprint.py sorts keys
    anyway, but stability here aids human diffing."""
    return {
        "strategy_id": STRATEGY_ID,
        "strategy_version": STRATEGY_VERSION,
        "direction": DIRECTION,
        "decision_time_et": f"{DECISION_TIME_ET_HOUR:02d}:{DECISION_TIME_ET_MINUTE:02d}",
        "beta_lookback_trading_days": BETA_LOOKBACK_TRADING_DAYS,
        "market_benchmark_symbol": MARKET_BENCHMARK_SYMBOL,
        "residual_threshold_pct": RESIDUAL_THRESHOLD_PCT,
        "entry_rule": ENTRY_RULE,
        "exit_horizon_minutes": EXIT_HORIZON_MINUTES,
        "stop_distance_pct": STOP_DISTANCE_PCT,
        "stop_fill_semantics": STOP_FILL_SEMANTICS,
        "rth_only": RTH_ONLY,
        "no_overnight_holding": NO_OVERNIGHT_HOLDING,
        "one_trade_per_symbol_per_session": ONE_TRADE_PER_SYMBOL_PER_SESSION,
        "position_sizing": POSITION_SIZING,
        "rejection_reasons": list(REJECTION_REASONS),
        "fail_closed": FAIL_CLOSED,
        "primary_cost_bps": PRIMARY_COST_BPS,
        "cost_diagnostic_levels_bps": list(COST_DIAGNOSTIC_LEVELS_BPS),
        "provider": PROVIDER,
        "provider_feed_research": PROVIDER_FEED_RESEARCH,
        "provider_feed_live": PROVIDER_FEED_LIVE,
        "provider_parity_proven": PROVIDER_PARITY_PROVEN,
        "universe": list(UNIVERSE),
    }
