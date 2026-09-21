"""Task 65B Part D -- operator-controlled PAPER lifecycle probe.

A zero-natural-signal day is a valid PIV outcome, but it would leave the
full order lifecycle (submit -> broker ack -> fill -> position -> controlled
exit -> reconciliation) untested end-to-end against the live paper broker.
This module provides exactly ONE isolated, explicitly-operator-confirmed
probe trade to close that gap -- never counted as a strategy signal, trade,
or alpha evidence; excluded from all strategy statistics.

Predeclared fallback rule (fixed here, in code, before observing any market
outcome for 2026-08-24 -- not chosen retrospectively): the probe is only
eligible if, by PROBE_CUTOFF_ET, no natural STRATEGY-sourced
PAPER_ORDER_SUBMITTED event has occurred this session. PROBE_CUTOFF_ET is
15:00 ET -- chosen to give the live strategy path its full ~120-bar (~2h)
warmup (market opens 09:30 ET, warmup completes ~11:30 ET) plus roughly
3.5 hours of live evaluation, while still leaving a 50-minute margin before
the 15:50 ET EOD flatten to complete a full probe entry+exit lifecycle if
needed.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, time
import json
from pathlib import Path

from .broker import PaperGuardError
from .config import PAPER_ENDPOINT, PivConfig
from .events import EventBus, PivEvent
from .lifecycle import PaperLifecycle

PROBE_CUTOFF_ET = time(15, 0)
# Deterministic, pre-declared: AAPL is first in the configured 35-symbol PIV
# universe and one of the most liquid names in it -- not chosen from today's
# price action.
PROBE_SYMBOL = "AAPL"
PROBE_QUANTITY = 1.0


def natural_strategy_lifecycle_observed(events_path: Path) -> bool:
    """True if a STRATEGY-sourced PAPER_ORDER_SUBMITTED event already
    exists in today's event log."""
    if not events_path.exists():
        return False
    for line in events_path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        row = json.loads(line)
        if row.get("event") == "PAPER_ORDER_SUBMITTED" and row.get("source") == "STRATEGY":
            return True
    return False


@dataclass
class LifecycleProbeResult:
    ran: bool
    reason: str
    entry_order: dict | None = None


def run_piv_lifecycle_probe(
    config: PivConfig, events: EventBus, lifecycle: PaperLifecycle, *, explicit_confirmation: bool, now_et_time: time,
) -> LifecycleProbeResult:
    if not explicit_confirmation:
        return LifecycleProbeResult(False, "PROBE_REQUIRES_EXPLICIT_OPERATOR_CONFIRMATION")
    if config.real_capital or not config.paper_trading:
        return LifecycleProbeResult(False, "PROBE_BLOCKED_REAL_CAPITAL_OR_NON_PAPER_STATE")
    if config.broker_endpoint.rstrip("/") != PAPER_ENDPOINT:
        return LifecycleProbeResult(False, "PROBE_BLOCKED_NON_PAPER_ENDPOINT")
    if now_et_time < PROBE_CUTOFF_ET:
        return LifecycleProbeResult(False, "PROBE_CUTOFF_NOT_YET_REACHED")
    if natural_strategy_lifecycle_observed(events.path):
        return LifecycleProbeResult(False, "NATURAL_STRATEGY_LIFECYCLE_ALREADY_OBSERVED_PROBE_NOT_NEEDED")

    reconciliation = lifecycle.reconcile()
    if not reconciliation["matched"]:
        return LifecycleProbeResult(False, "PROBE_BLOCKED_UNRECONCILED_STATE")
    open_symbols = {v["symbol"] for v in lifecycle.state.positions.values() if v.get("status") == "OPEN"}
    if PROBE_SYMBOL in open_symbols:
        return LifecycleProbeResult(False, "PROBE_BLOCKED_EXISTING_POSITION_IN_PROBE_SYMBOL")

    signal_id = f"piv_probe_entry_{date.today().isoformat()}"
    events.emit(PivEvent.build(
        "SIGNAL", symbol=PROBE_SYMBOL, signal_id=signal_id, status="PIV_LIFECYCLE_PROBE_ENTRY",
        source="PIV_LIFECYCLE_PROBE", alpha_evidence=False,
    ))
    try:
        entry = lifecycle.order_intent(signal_id, PROBE_SYMBOL, "buy", PROBE_QUANTITY, source="PIV_LIFECYCLE_PROBE", alpha_evidence=False)
    except PaperGuardError as exc:
        events.emit(PivEvent.build("BROKER_ERROR", symbol=PROBE_SYMBOL, reason=str(exc), source="PIV_LIFECYCLE_PROBE"))
        return LifecycleProbeResult(False, f"PROBE_ENTRY_FAILED: {exc}")
    broker_id = entry.get("id")
    if broker_id:
        lifecycle.poll_order_until_terminal(str(broker_id))
    return LifecycleProbeResult(True, "PROBE_ENTRY_SUBMITTED", entry_order=entry)


def close_piv_lifecycle_probe(events: EventBus, lifecycle: PaperLifecycle) -> dict | None:
    """Controlled exit for the probe's open position, if any."""
    has_open = any(
        v["symbol"] == PROBE_SYMBOL and v.get("status") == "OPEN" for v in lifecycle.state.positions.values()
    )
    if not has_open:
        return None
    signal_id = f"piv_probe_exit_{date.today().isoformat()}"
    events.emit(PivEvent.build(
        "EXIT_REQUESTED", symbol=PROBE_SYMBOL, signal_id=signal_id, status="PIV_LIFECYCLE_PROBE_EXIT",
        source="PIV_LIFECYCLE_PROBE", alpha_evidence=False,
    ))
    try:
        result = lifecycle.order_intent(signal_id, PROBE_SYMBOL, "sell", PROBE_QUANTITY, source="PIV_LIFECYCLE_PROBE", alpha_evidence=False)
    except PaperGuardError as exc:
        events.emit(PivEvent.build("BROKER_ERROR", symbol=PROBE_SYMBOL, reason=str(exc), source="PIV_LIFECYCLE_PROBE"))
        return None
    broker_id = result.get("id")
    if broker_id:
        lifecycle.poll_order_until_terminal(str(broker_id))
    return result
