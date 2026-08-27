"""Task 77I Stage 3 -- causal shadow tracking, independent of PAPER
broker execution.

Reuses `talonx_backtest.execution`'s already-tested pure functions
(`apply_entry_cost`, `apply_exit_cost`, `check_bar_for_exit`) for the actual
cost/ambiguity computation, and replicates `talonx_backtest.engine.py`'s own
`_PendingEntry` next-bar-open fill convention (see that module's docstring:
"a published signal's entry is executed at the OPEN of the NEXT bar...
never a same-bar close") for the same non-lookahead reason -- this is the
SAME causal rule the historical backtest already applies, not a new one.
`TradeSimulator` itself (a stateful class holding a live pydantic
`QuantSignal` + `datetime` objects) is not reused directly since it does not
round-trip through JSON; `ShadowLedger` persists its own primitive-typed
`ShadowPosition` record instead, using the same `_load`/`_save`
full-file-JSON-rewrite pattern already established elsewhere in this
package. See implementation_plan.md's "Reuse decisions" section.

**Deliberately gated on the SAME actionability bar as PAPER execution**:
`consider_entry` only opens a shadow position for `decision.recommendation
== Recommendation.BUY` -- i.e. only when strategy approval + bullish + flat
+ ready data all already held (see decision_contract.decide). This is a
policy choice, not an accident: gating shadow P&L on raw signal direction
alone (ignoring strategy approval) would let an UNVALIDATED strategy
accumulate an informal, unaudited "shadow track record" -- exactly the kind
of accidentally-manufactured evidence Tasks 74S/75S were careful never to
create. See shadow_simulation_policy.md for the full write-up.

Causal fill rule (non-lookahead, spec-required):
  - A decision is evaluated at a specific bar (the signal's trigger bar,
    already CLOSED/observed). The shadow entry is NOT assumed to fill at
    that bar's close (spec: "Do not assume a fill at the already-observed
    signal close").
  - The shadow position sits PENDING_FILL until `on_bar` observes a
    STRICTLY LATER bar for the same symbol -- fills at THAT bar's `open`
    (spec: "the OPEN of the NEXT bar", matching talonx_backtest exactly).
  - If no later bar ever arrives before end of session/horizon (a genuine
    data gap), the position resolves UNRESOLVED_NO_FILL -- never a
    fabricated close/fill price (spec: "Missing data produces an
    unresolved/qualified outcome, not fabricated P&L").
  - Same-bar stop/target ambiguity is resolved via the reused
    `check_bar_for_exit` (stop-first, the conservative default) -- the
    IDENTICAL rule the historical backtest applies.
  - Horizon completion with no executable observation never manufactures a
    closing price -- see `force_close`'s UNRESOLVED handling below.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
from typing import Any

from talonx_backtest.execution import ExecutionConfig, apply_entry_cost, apply_exit_cost, check_bar_for_exit
from talonx_quant.schemas import SignalDirection

from .decision_contract import Decision, Recommendation

STATUS_PENDING_FILL = "PENDING_FILL"
STATUS_OPEN = "OPEN"
STATUS_CLOSED = "CLOSED"
STATUS_UNRESOLVED = "UNRESOLVED"

# Task 78I Stage 1B: horizon labels this codebase actually declares, mapped
# to a concrete deadline duration -- deliberately EMPTY for production. The
# only horizon value any real caller ever attaches to a Decision today is
# `decision_engine.NATURAL_STRATEGY_HORIZON = "INTRADAY_SHORT"`, and no
# existing minute/hour value for it is declared anywhere else in this
# repository (confirmed by search -- see horizon_exit_evidence.json). Per
# this task's own explicit instruction ("Missing horizon policy must not be
# silently replaced with an arbitrary holding period"), this module does
# NOT invent a duration for it. A Decision whose horizon is absent from
# this mapping simply gets NO horizon-based shadow deadline -- it still
# exits normally via stop/target/EOD, exactly as before this stage. Tests
# supply an explicit TEST_FIXTURE_ONLY -- NOT ALPHA EVIDENCE policy via
# ShadowLedger's own `horizon_policy` constructor parameter to exercise the
# mechanism deterministically; production code (cli.py) never supplies one.
DEFAULT_HORIZON_POLICY: dict[str, timedelta] = {}


@dataclass
class ShadowPosition:
    shadow_id: str
    decision_id: str
    symbol: str
    source: str
    recommendation_time: str
    stop_price: float | None
    target_price: float | None
    horizon: str | None
    status: str = STATUS_PENDING_FILL
    horizon_deadline: str | None = None
    hypothetical_fill_time: str | None = None
    planned_entry_price: float | None = None
    simulated_entry_price_raw: float | None = None
    simulated_entry_price_net: float | None = None
    exit_time: str | None = None
    exit_reason: str | None = None
    simulated_exit_price_raw: float | None = None
    simulated_exit_price_net: float | None = None
    gross_result: float | None = None
    estimated_entry_cost: float | None = None
    estimated_exit_cost: float | None = None
    net_result: float | None = None
    initial_risk: float | None = None
    gross_r: float | None = None
    net_r: float | None = None
    holding_seconds: float | None = None
    mfe_price: float | None = None
    mae_price: float | None = None
    coverage_flag: str = "NORMAL"
    outcome_quality: str | None = None
    created_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class ShadowLedger:
    def __init__(
        self, state_path: Path | None, execution_config: ExecutionConfig | None = None,
        horizon_policy: dict[str, timedelta] | None = None,
    ) -> None:
        self.state_path = state_path
        self.config = execution_config or ExecutionConfig()
        # TEST_FIXTURE_ONLY -- NOT ALPHA EVIDENCE when non-empty: production
        # (cli.py) never supplies this, so every real decision's horizon
        # ("INTRADAY_SHORT") has no entry here -- see DEFAULT_HORIZON_POLICY's
        # own docstring for why that is deliberate, not an oversight.
        self.horizon_policy = dict(horizon_policy) if horizon_policy is not None else dict(DEFAULT_HORIZON_POLICY)
        self.positions: dict[str, dict[str, Any]] = self._load()
        self._by_decision: dict[str, str] = {p["decision_id"]: sid for sid, p in self.positions.items()}
        self._pending_by_symbol: dict[str, str] = {
            p["symbol"]: sid for sid, p in self.positions.items() if p["status"] == STATUS_PENDING_FILL
        }
        self._open_by_symbol: dict[str, str] = {
            p["symbol"]: sid for sid, p in self.positions.items() if p["status"] == STATUS_OPEN
        }

    def _load(self) -> dict[str, dict[str, Any]]:
        if self.state_path is None or not self.state_path.exists():
            return {}
        try:
            return json.loads(self.state_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return {}

    def _save(self) -> None:
        if self.state_path is None:
            return
        self.state_path.parent.mkdir(parents=True, exist_ok=True)
        self.state_path.write_text(json.dumps(self.positions, sort_keys=True, indent=2), encoding="utf-8")

    def get_by_decision(self, decision_id: str) -> dict[str, Any] | None:
        shadow_id = self._by_decision.get(decision_id)
        return self.positions.get(shadow_id) if shadow_id else None

    def consider_entry(self, decision: Decision, *, source: str) -> dict[str, Any] | None:
        """Only for decision.recommendation == BUY. Idempotent per
        decision_id -- a duplicate/restarted call for the same decision
        returns the existing record unchanged. At most one PENDING_FILL/OPEN
        shadow position per symbol at a time (mirrors the real one-position-
        per-symbol invariant), never overlapping."""
        if decision.recommendation != Recommendation.BUY:
            return None
        existing = self.get_by_decision(decision.decision_id)
        if existing is not None:
            return existing
        if decision.ticker in self._pending_by_symbol or decision.ticker in self._open_by_symbol:
            return None  # a shadow trade is already live for this symbol -- no overlap
        shadow_id = f"shadow_{decision.decision_id}"
        position = ShadowPosition(
            shadow_id=shadow_id, decision_id=decision.decision_id, symbol=decision.ticker, source=source,
            recommendation_time=decision.timestamp, stop_price=decision.stop_price,
            target_price=decision.target_price, horizon=decision.horizon, planned_entry_price=decision.entry_price,
        )
        self.positions[shadow_id] = position.to_dict()
        self._by_decision[decision.decision_id] = shadow_id
        self._pending_by_symbol[decision.ticker] = shadow_id
        self._save()
        return self.positions[shadow_id]

    def on_bar(self, symbol: str, bar: Any) -> None:
        """Call once per new bar per symbol (same cadence as
        DecisionEngine.on_bars) to advance PENDING_FILL -> OPEN (causal
        next-bar-open fill) and check OPEN -> CLOSED (stop/target)."""
        pending_id = self._pending_by_symbol.get(symbol)
        if pending_id is not None:
            position = self.positions[pending_id]
            if bar.timestamp.isoformat() > position["recommendation_time"]:
                fill_raw = bar.open
                fill_net = apply_entry_cost(fill_raw, SignalDirection.BULLISH, self.config)
                fill_time = bar.timestamp
                horizon_delta = self.horizon_policy.get(position.get("horizon"))
                horizon_deadline = (fill_time + horizon_delta).isoformat() if horizon_delta is not None else None
                position.update(
                    status=STATUS_OPEN, hypothetical_fill_time=fill_time.isoformat(),
                    simulated_entry_price_raw=fill_raw, simulated_entry_price_net=fill_net,
                    mfe_price=fill_raw, mae_price=fill_raw, horizon_deadline=horizon_deadline,
                    initial_risk=(abs(fill_raw - position["stop_price"]) if position.get("stop_price") is not None else None),
                )
                del self._pending_by_symbol[symbol]
                self._open_by_symbol[symbol] = pending_id
                self._save()

        open_id = self._open_by_symbol.get(symbol)
        if open_id is not None:
            position = self.positions[open_id]
            position["mfe_price"] = max(position["mfe_price"], bar.high)
            position["mae_price"] = min(position["mae_price"], bar.low)
            if position.get("stop_price") is not None and position.get("target_price") is not None:
                outcome = check_bar_for_exit(
                    SignalDirection.BULLISH, position["stop_price"], position["target_price"], bar.high, bar.low,
                )
                if outcome is not None:
                    exit_price = position["stop_price"] if outcome == "stop" else position["target_price"]
                    self._close(open_id, bar.timestamp, exit_price, outcome.upper())
                    return
            # Task 78I Stage 1B: horizon deadline checked only AFTER stop/
            # target (price-risk management takes precedence on a same-bar
            # tie) -- a real, OBSERVED price (this bar's close) is used,
            # never a fabricated price interpolated at the exact deadline
            # instant. `bar.timestamp >= deadline` is the first CAUSAL
            # opportunity to act on horizon expiry -- never earlier, and
            # correctly reflects a LATE exit (not backdated to the
            # deadline) when this is the first bar observed after a gap.
            deadline = position.get("horizon_deadline")
            if deadline is not None and bar.timestamp.isoformat() >= deadline:
                self._close(open_id, bar.timestamp, bar.close, "HORIZON")
                return
            self._save()

    def force_close(self, symbol: str, timestamp: Any, price: float | None, reason: str) -> None:
        """END_OF_SESSION (or any other forced flatten) -- an OPEN shadow
        position closes at the given (real, observed) price, exactly like
        the real EOD flatten; a still-PENDING_FILL shadow position (never
        observed a later bar before this) resolves UNRESOLVED_NO_FILL --
        never fabricated as if it had filled and immediately closed.

        Task 78I Stage 1B: if this position's horizon_deadline had already
        passed with NO intervening bar ever observed to causally execute
        the horizon exit (a genuine data/observation gap through end of
        session), the reason is reclassified to make that explicit --
        distinct from an ordinary EOD close that happens before horizon
        ever expired. Still uses the real, observed flatten price (never a
        price fabricated at the deadline instant itself)."""
        open_id = self._open_by_symbol.get(symbol)
        if open_id is not None:
            position = self.positions[open_id]
            deadline = position.get("horizon_deadline")
            if deadline is not None and timestamp.isoformat() >= deadline and reason != "HORIZON":
                reason = "HORIZON_EXPIRED_NO_EXECUTABLE_OBSERVATION"
            if price is not None:
                self._close(open_id, timestamp, price, reason)
            else:
                position = self.positions[open_id]
                position.update(status=STATUS_UNRESOLVED, outcome_quality="UNRESOLVED_MISSING_CLOSE_PRICE", exit_reason=reason)
                del self._open_by_symbol[symbol]
                self._save()
        pending_id = self._pending_by_symbol.get(symbol)
        if pending_id is not None:
            position = self.positions[pending_id]
            position.update(status=STATUS_UNRESOLVED, outcome_quality="UNRESOLVED_NO_FILL_BEFORE_HORIZON_END", exit_reason=reason)
            del self._pending_by_symbol[symbol]
            self._save()

    def _close(self, shadow_id: str, timestamp: Any, exit_price_raw: float, reason: str) -> None:
        position = self.positions[shadow_id]
        exit_price_net = apply_exit_cost(exit_price_raw, SignalDirection.BULLISH, self.config)
        entry_raw = position["simulated_entry_price_raw"]
        entry_net = position["simulated_entry_price_net"]
        gross = exit_price_raw - entry_raw
        net = exit_price_net - entry_net
        risk = position.get("initial_risk")
        gross_r = gross / risk if risk else None
        net_r = net / risk if risk else None
        holding_seconds = None
        fill_time = position.get("hypothetical_fill_time")
        if fill_time is not None:
            try:
                holding_seconds = (timestamp - datetime.fromisoformat(fill_time)).total_seconds()
            except (TypeError, ValueError):
                holding_seconds = None
        position.update(
            status=STATUS_CLOSED, exit_time=timestamp.isoformat() if hasattr(timestamp, "isoformat") else str(timestamp),
            exit_reason=reason, simulated_exit_price_raw=exit_price_raw, simulated_exit_price_net=exit_price_net,
            gross_result=gross, net_result=net,
            estimated_entry_cost=entry_net - entry_raw if entry_raw is not None else None,
            estimated_exit_cost=exit_price_net - exit_price_raw,
            gross_r=gross_r, net_r=net_r, holding_seconds=holding_seconds, outcome_quality="RESOLVED",
        )
        symbol = position["symbol"]
        if self._open_by_symbol.get(symbol) == shadow_id:
            del self._open_by_symbol[symbol]
        self._save()
