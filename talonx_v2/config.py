"""
talonx_v2.config -- FROZEN Task 109 contract constants.

Every value here is copied from
``results/task109_v2_freeze/v2_strategy_contract.md`` and must NOT be
tuned.  Changing any of these is a NEW_HYPOTHESIS_ONLY act and is out of
scope for Task 110 (and forbidden by the Task 110 hard research freeze).
"""
from __future__ import annotations

import os
from dataclasses import dataclass, field

V2_VERSION = "INSIDER_BUY_CLUSTER_V2@1"
V2_RESEARCH_SOURCE = "Task107B TASK107B_FORM4_PAPER_CANDIDATE (prereg a9ceefc, eval 625325a)"
V2_STATUS = "PAPER_CANDIDATE"
V2_FROZEN_CONTRACT = "results/task109_v2_freeze/v2_strategy_contract.md"


@dataclass(frozen=True)
class V2Config:
    # --- signal (FROZEN) ---
    cluster_window_trading_days: int = 10
    min_distinct_owners: int = 2
    transaction_code: str = "P"                 # open-market purchase only
    direction: str = "BULLISH"                  # long only, never short

    # --- entry (FROZEN) ---
    # BUY at the OPEN of the first NYSE session STRICTLY AFTER the episode fires.
    entry_offset_sessions: int = 1

    # --- exit (FROZEN) ---
    # SELL at the CLOSE of the +10th trading session after entry.
    hold_trading_days: int = 10
    telemetry_horizons: tuple[int, ...] = (5, 10, 15)
    stop_loss_enabled: bool = False            # none in the frozen primary
    # data-availability handling ONLY (Task 111 F2 / Task 112 Phase 5):
    # if the exact +10-td session has no bar, take the FIRST available close
    # in the next N sessions.  Never backwards, never best-price.  All N
    # missing -> explicit EXIT_UNRESOLVED state, never a silent hold.
    exit_fallforward_max_sessions: int = 5

    # --- risk rules (FROZEN) ---
    max_concurrent_positions: int = 20
    reentry_cooldown_trading_days: int = 5     # after a SELL, per issuer
    allow_adds: bool = False
    allow_shorts: bool = False
    allow_real_capital: bool = False

    # --- eligibility / liquidity gate (FROZEN) ---
    liquidity_lookback_sessions: int = 20
    liquidity_min_median_dollar_volume: float = 5_000_000.0
    liquidity_min_close: float = 5.0

    # --- paper sizing (operational, NOT a research lever -- Phase 11) ---
    # equal notional per episode; taken from the existing paper allocation
    # unless overridden.  Default mirrors the Original intraday allocation.
    per_position_allocation_usd: float = field(
        default_factory=lambda: float(os.environ.get("TALONX_V2_ALLOCATION_USD", "10000"))
    )
    starting_cash_usd: float = field(
        default_factory=lambda: float(os.environ.get("TALONX_V2_STARTING_CASH_USD", "100000"))
    )
    friction_bps: float = 20.0                 # research primary friction (reporting only)

    # --- campaign identity (RI-1, operational -- NOT a research lever,
    # same treatment as starting_cash_usd/per_position_allocation_usd
    # above: distinguishes WHICH economic paper-capital lifecycle a trade
    # belongs to, never the strategy's own semantics). Default "V2"
    # reproduces the existing, single, pre-RI-1 production campaign's
    # identity exactly -- opening it with no override is a no-op.
    campaign_id: str = field(
        default_factory=lambda: os.environ.get("TALONX_V2_CAMPAIGN_ID", "V2")
    )
    execution_mode: str = field(
        default_factory=lambda: os.environ.get("TALONX_V2_EXECUTION_MODE", "PAPER")
    )

    # --- live operational guard (NOT strategy semantics) ---
    # the frozen rule is "enter at the OPEN of the first session strictly
    # after the cluster fires".  If the live service is started cold with a
    # backlog, it must NOT chase a stale entry at a historical price -- an
    # episode whose eligible_entry_session is more than this many trading
    # sessions before 'today' is recorded SKIPPED_ENTRY_STALE, not entered.
    max_entry_staleness_sessions: int = 3

    # --- infra ---
    redis_channel_signal: str = "talonx:v2:signal"
    redis_channel_decision: str = "talonx:v2:decision"
    redis_channel_alert: str = "talonx:v2:alert"
    redis_channel_trade: str = "talonx:v2:trade"
    db_path: str = field(
        default_factory=lambda: os.environ.get("TALONX_V2_DB_PATH", "v2_lane.db")
    )

    def validate_frozen(self) -> None:
        """Guard: assert the frozen contract values are intact."""
        assert self.cluster_window_trading_days == 10
        assert self.min_distinct_owners == 2
        assert self.transaction_code == "P"
        assert self.hold_trading_days == 10
        assert self.entry_offset_sessions == 1
        assert self.max_concurrent_positions == 20
        assert self.reentry_cooldown_trading_days == 5
        assert self.allow_shorts is False
        assert self.allow_real_capital is False
        assert self.stop_loss_enabled is False
        assert self.liquidity_min_median_dollar_volume == 5_000_000.0
        assert self.liquidity_min_close == 5.0
        assert self.liquidity_lookback_sessions == 20
        assert self.exit_fallforward_max_sessions == 5
        assert self.max_entry_staleness_sessions >= 0
