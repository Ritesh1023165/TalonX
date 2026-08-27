"""Task 76S -- typed, product-level long-only decision contract.

Deliberately separate from the broker-execution boundary (see lifecycle.py's
hardened `order_intent`, Task 76S Stage 3) and from talonx_quant's protected
strategy code (untouched). This module answers ONE question -- "given the
current market view, position state, strategy-approval status, data
readiness, and the per-ticker PAPER-entry setting, what SHOULD happen?" --
and records that answer as a stable, inspectable `Decision`. It does not
submit orders, does not send notifications, and does not maintain a shadow
ledger; those are later components this record is designed to feed (see
results/task76s_long_only_execution_contract/remaining_integration_work.md).

Kept distinct on purpose (never conflated):
  - market_view            -- what the signal/indicator observed (bullish/
                               bearish/neutral), independent of any position.
  - recommendation          -- what the PRODUCT would like to happen next
                               (BUY / HOLD / SELL_TO_CLOSE / NO_TRADE).
  - strategy approval status -- whether this strategy/version is validated
                               for actionable promotion at all (independent
                               of today's market_view).
  - execution eligibility    -- whether a recommended BUY may actually reach
                               the broker right now (PAPER-entry enabled,
                               session state, etc.) -- see `execution_status`.
  - execution result         -- NOT part of this contract; that is whatever
                               lifecycle.order_intent / apply_broker_update
                               later records, keyed by this decision_id.

No level (entry/stop/target) is ever invented here -- they are passed
through unchanged from whatever already-existing deterministic rule (a
QuantSignal, a probe's fixed levels) supplied them, or omitted (None) if
none exists yet.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum


class MarketView(str, Enum):
    BULLISH = "BULLISH"
    BEARISH = "BEARISH"
    NEUTRAL = "NEUTRAL"


class Recommendation(str, Enum):
    BUY = "BUY"
    HOLD = "HOLD"
    SELL_TO_CLOSE = "SELL_TO_CLOSE"
    NO_TRADE = "NO_TRADE"


class StrategyApprovalStatus(str, Enum):
    """No production strategy-approval registry exists anywhere in this
    repository today (confirmed by Stage 0's inventory) -- UNVALIDATED is
    therefore the only status a real strategy may carry until a separate,
    explicit approval mechanism is built and populated. APPROVED exists
    only for isolated test fixtures (see tests/test_task76s_decision_contract.py's
    own TEST_FIXTURE_ONLY -- NOT ALPHA EVIDENCE cases) and must never leak
    into production configuration -- there is no code path anywhere in this
    module, or in cli.py/decision_engine.py, that sets a real strategy to
    APPROVED."""
    UNVALIDATED = "UNVALIDATED"
    APPROVED = "APPROVED"


class DataReadiness(str, Enum):
    """Mirrors readiness.py's own vocabulary (READY/DATA_NOT_READY/PENDING)
    so a caller can pass that module's status through unchanged rather than
    collapsing it to a bool prematurely."""
    READY = "READY"
    DATA_NOT_READY = "DATA_NOT_READY"
    PENDING = "PENDING"


class ExecutionStatus(str, Enum):
    """What this decision's recommendation may/may not do at the broker
    boundary -- NOT the eventual fill outcome (that is recorded separately,
    by lifecycle.py, keyed by decision_id)."""
    NO_ACTION = "NO_ACTION"
    ENTRY_ELIGIBLE = "ENTRY_ELIGIBLE"
    ENTRY_BLOCKED_PAPER_DISABLED = "ENTRY_BLOCKED_PAPER_DISABLED"
    ENTRY_BLOCKED_UNVALIDATED_STRATEGY = "ENTRY_BLOCKED_UNVALIDATED_STRATEGY"
    EXIT_ELIGIBLE = "EXIT_ELIGIBLE"


@dataclass(frozen=True)
class Decision:
    decision_id: str
    session_id: str
    trading_date_et: str
    ticker: str
    market_view: MarketView
    recommendation: Recommendation
    reason_codes: tuple[str, ...]
    strategy_id: str | None
    strategy_version: str | None
    strategy_approval_status: StrategyApprovalStatus
    data_readiness: DataReadiness
    paper_entry_enabled: bool
    execution_status: ExecutionStatus
    timestamp: str
    entry_price: float | None = None
    stop_price: float | None = None
    target_price: float | None = None
    horizon: str | None = None

    def to_dict(self) -> dict:
        return {
            "decision_id": self.decision_id, "session_id": self.session_id,
            "trading_date_et": self.trading_date_et, "ticker": self.ticker,
            "market_view": self.market_view.value, "recommendation": self.recommendation.value,
            "reason_codes": list(self.reason_codes),
            "strategy_id": self.strategy_id, "strategy_version": self.strategy_version,
            "strategy_approval_status": self.strategy_approval_status.value,
            "data_readiness": self.data_readiness.value,
            "paper_entry_enabled": self.paper_entry_enabled,
            "execution_status": self.execution_status.value,
            "timestamp": self.timestamp,
            "entry_price": self.entry_price, "stop_price": self.stop_price,
            "target_price": self.target_price, "horizon": self.horizon,
        }


def decide(
    *,
    decision_id: str,
    session_id: str,
    trading_date_et: str,
    ticker: str,
    market_view: MarketView,
    has_open_long: bool,
    approved_exit_condition: bool,
    strategy_approval_status: StrategyApprovalStatus,
    data_readiness: DataReadiness,
    paper_entry_enabled: bool,
    strategy_id: str | None = None,
    strategy_version: str | None = None,
    entry_price: float | None = None,
    stop_price: float | None = None,
    target_price: float | None = None,
    horizon: str | None = None,
    now: datetime | None = None,
) -> Decision:
    """Pure function -- no I/O, no broker/event-bus access. Implements the
    Task 76S required behaviour table exactly; see the module docstring for
    why `approved_exit_condition` (not `market_view == BEARISH`) is the only
    thing that can ever produce SELL_TO_CLOSE while holding."""
    reason_codes: list[str] = []

    if has_open_long:
        if approved_exit_condition:
            recommendation = Recommendation.SELL_TO_CLOSE
            reason_codes.append("EXISTING_LONG_APPROVED_EXIT_CONDITION")
        else:
            recommendation = Recommendation.HOLD
            reason_codes.append("EXISTING_LONG_NO_APPROVED_EXIT_CONDITION")
    else:
        if market_view != MarketView.BULLISH:
            recommendation = Recommendation.NO_TRADE
            reason_codes.append("BEARISH_OR_NEUTRAL_VIEW_NO_HOLDING")
        elif data_readiness != DataReadiness.READY:
            recommendation = Recommendation.NO_TRADE
            reason_codes.append(f"DATA_INSUFFICIENT_FOR_ENTRY:{data_readiness.value}")
        elif strategy_approval_status != StrategyApprovalStatus.APPROVED:
            recommendation = Recommendation.NO_TRADE
            reason_codes.append("STRATEGY_UNVALIDATED_NO_ACTIONABLE_BUY_PROMOTION")
        else:
            recommendation = Recommendation.BUY
            reason_codes.append("ELIGIBLE_APPROVED_BULLISH_SETUP_NO_HOLDING")

    if recommendation == Recommendation.BUY:
        if not paper_entry_enabled:
            execution_status = ExecutionStatus.ENTRY_BLOCKED_PAPER_DISABLED
            reason_codes.append("PAPER_ENTRY_DISABLED_FOR_TICKER")
            # Recommendation is preserved as BUY -- only the broker entry is
            # blocked (Task 76S required behaviour: "Preserve BUY decision;
            # block broker entry").
        else:
            execution_status = ExecutionStatus.ENTRY_ELIGIBLE
    elif recommendation == Recommendation.SELL_TO_CLOSE:
        execution_status = ExecutionStatus.EXIT_ELIGIBLE
    else:
        execution_status = ExecutionStatus.NO_ACTION

    timestamp = (now or datetime.now(timezone.utc)).isoformat()
    return Decision(
        decision_id=decision_id, session_id=session_id, trading_date_et=trading_date_et,
        ticker=ticker.upper(), market_view=market_view, recommendation=recommendation,
        reason_codes=tuple(reason_codes), strategy_id=strategy_id, strategy_version=strategy_version,
        strategy_approval_status=strategy_approval_status, data_readiness=data_readiness,
        paper_entry_enabled=paper_entry_enabled, execution_status=execution_status, timestamp=timestamp,
        entry_price=entry_price, stop_price=stop_price, target_price=target_price, horizon=horizon,
    )
