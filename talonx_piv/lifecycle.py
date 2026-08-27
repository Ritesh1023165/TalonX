"""Persistent, idempotent Alpaca-paper order lifecycle and reconciliation.

Task 76S Stage 3: this module's `order_intent` is the single, unavoidable
chokepoint for every per-order PAPER broker mutation in this codebase --
`AlpacaPaperClient.submit_order` has exactly one caller, and `order_intent`
has exactly four (natural strategy entry/exit, PIV lifecycle probe
entry/exit -- see results/task76s_long_only_execution_contract/
execution_path_inventory.md). Hardening it in place, rather than adding a
separate "please validate first" helper, is what makes enforcement
unbypassable: there is no second path to the broker a caller could use
instead."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from enum import Enum
import hashlib
import json
import math
from pathlib import Path
from typing import Any

from .broker import AlpacaPaperClient, PaperGuardError
from .events import EventBus, PivEvent
from .execution_settings import PaperEntrySettings

# Task 76S Stage 3: explicit source allowlist -- `None` is accepted only
# because every pre-existing internal/test caller that omits `source`
# entirely predates this task and is never externally reachable; every
# REAL production caller (decision_engine.py, lifecycle_probe.py) already
# always passes one of the two named sources below. Anything else --
# including a hypothetical "BRAIN"/"GEMINI" source from a future
# integration that has not been authorized to submit or alter orders --
# is rejected. This is a defense-in-depth allowlist, not the only control:
# today, no code path outside this package can even reach `order_intent`
# (see execution_path_inventory.md Stage 0 item 2).
ALLOWED_ORDER_SOURCES: frozenset[str | None] = frozenset({None, "STRATEGY", "PIV_LIFECYCLE_PROBE"})

# Alpaca order-status vocabulary this module observes via apply_broker_update
# plus this module's own pre-broker-ack "SUBMITTED" -- anything NOT in this
# terminal set is treated as still-pending/outstanding for oversell and
# duplicate-entry detection below.
_TERMINAL_ORDER_STATUSES = frozenset({"filled", "rejected", "canceled", "expired"})


class ActionIntent(str, Enum):
    """Explicit, typed action intent -- Task 76S Stage 3 requires enforcing
    against this, not interpreting a raw side string ad hoc at each call
    site. Derived from `side` at the top of `order_intent`; any `side` that
    does not map to one of these two is rejected outright (this is also
    what makes "open a short" structurally impossible -- there is no third
    value this could ever resolve to)."""
    BUY_TO_OPEN = "BUY_TO_OPEN"
    SELL_TO_CLOSE = "SELL_TO_CLOSE"


def stable_id(prefix: str, *parts: object) -> str:
    body = "|".join(str(part) for part in parts)
    return f"{prefix}_{hashlib.sha256(body.encode()).hexdigest()[:20]}"


def _safe_float(value: Any) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0


@dataclass
class LifecycleState:
    session_enabled: bool = False
    kill_switch: bool = False
    intents: dict[str, dict[str, Any]] = field(default_factory=dict)
    orders: dict[str, dict[str, Any]] = field(default_factory=dict)
    positions: dict[str, dict[str, Any]] = field(default_factory=dict)
    # Task 69Q Part 5: maps symbol -> the position_id currently OPEN for it,
    # so a sell fill can be recognized as CLOSING that same logical position
    # rather than becoming an unrelated second "opened" record (see
    # apply_broker_update). Absent/empty on an old state file -- a session
    # resumed mid-position from a pre-Task69Q file simply won't have this
    # entry until its next full open+close cycle, which is an acceptable,
    # documented restart edge case (positions dict itself remains authoritative).
    open_position_by_symbol: dict[str, str] = field(default_factory=dict)
    # Task 76S Stage 3: set by reconcile() when the broker reports a short
    # position (side=="short" or negative qty) with no matching internal
    # OPEN long -- a safety trip-wire only. No automatic remediation is
    # implemented for this (per instruction); it exists purely to block new
    # BUY entries until an operator investigates. Absent/empty on an old
    # state file, exactly like open_position_by_symbol above.
    reconciliation_flags: dict[str, Any] = field(default_factory=dict)


class PaperLifecycle:
    def __init__(
        self, state_path: Path, broker: AlpacaPaperClient, events: EventBus,
        paper_entry_settings: PaperEntrySettings | None = None,
    ) -> None:
        self.state_path = state_path
        self.broker = broker
        self.events = events
        # Task 76S Stage 2: fail-closed default -- a caller that does not
        # supply settings gets an ALL-DISABLED PaperEntrySettings, never a
        # permissive one. See execution_settings.py's own module docstring
        # for the migration rationale.
        self.paper_entry_settings = paper_entry_settings or PaperEntrySettings.all_disabled()
        self.state = self._load()

    def _load(self) -> LifecycleState:
        if not self.state_path.exists():
            return LifecycleState()
        return LifecycleState(**json.loads(self.state_path.read_text(encoding="utf-8")))

    def reload(self) -> None:
        """Re-read persisted state from disk -- lets a long-running session
        loop observe a kill-switch activated by a separate CLI invocation
        in another terminal, which writes to the same state_path."""
        self.state = self._load()

    def _save(self) -> None:
        self.state_path.parent.mkdir(parents=True, exist_ok=True)
        self.state_path.write_text(json.dumps(asdict(self.state), sort_keys=True, indent=2), encoding="utf-8")

    def start_session(self, preflight_passed: bool, explicit_confirmation: bool) -> None:
        if not preflight_passed or not explicit_confirmation:
            raise PaperGuardError("paper session requires PIV_READY and explicit PAPER SESSION START")
        self.broker._require_verified()
        self.state.session_enabled = True
        self.state.kill_switch = False
        self._save()
        self.events.emit(PivEvent.build("PAPER_SESSION_STARTED", status="PAPER MODE / NO REAL CAPITAL"))

    def _open_position_for(self, symbol: str) -> dict[str, Any] | None:
        position_id = self.state.open_position_by_symbol.get(symbol)
        if position_id is None:
            return None
        position = self.state.positions.get(position_id)
        if position is None or position.get("status") != "OPEN":
            return None
        return position

    def _non_terminal_orders_for(self, symbol: str, side: str) -> list[dict[str, Any]]:
        out = []
        for order in self.state.orders.values():
            if order.get("symbol") != symbol or order.get("status") in _TERMINAL_ORDER_STATUSES:
                continue
            intent = self.state.intents.get(order.get("intent_id"), {})
            if intent.get("payload", {}).get("side") != side:
                continue
            out.append(order)
        return out

    def _pending_quantity(self, symbol: str, side: str) -> float:
        """Sum of (originally-requested - filled_qty) across every
        non-terminal order of `side` for `symbol` -- what is already
        "spoken for" by an outstanding request, so a second request cannot
        oversell/duplicate against stale (already-terminal-in-reality)
        local state."""
        total = 0.0
        for order in self._non_terminal_orders_for(symbol, side):
            intent = self.state.intents.get(order.get("intent_id"), {})
            requested = float(intent.get("payload", {}).get("qty", 0.0) or 0.0)
            total += max(0.0, requested - float(order.get("filled_qty") or 0.0))
        return total

    def _reject(self, reason: str, symbol: str, source: str | None, alpha_evidence: bool | None) -> None:
        self.events.emit(PivEvent.build(
            "PAPER_ORDER_REJECTED", symbol=symbol, reason=reason, source=source, alpha_evidence=alpha_evidence,
        ))
        raise PaperGuardError(reason)

    def order_intent(
        self, signal_id: str, symbol: str, side: str, quantity: float, client_order_id: str | None = None,
        source: str | None = None, alpha_evidence: bool | None = None,
        # Task 69Q Part 6 -- execution economics, optional/best-effort. For an
        # entry: reference_price is the signal's trigger price, stop_price is
        # the strategy's defined stop (None if the strategy defines no stop --
        # gross_r/net_r then stay None rather than being fabricated). For an
        # exit: reference_price is the expected exit reference (e.g. the stop
        # or target price that triggered it), stop_price is not meaningful and
        # should be omitted.
        reference_price: float | None = None, stop_price: float | None = None,
        signal_timestamp: str | None = None, strategy_id: str | None = None,
        horizon: str | None = None,
    ) -> dict[str, Any]:
        symbol = symbol.upper()

        # -- Task 76S Stage 3: explicit action-intent + request well-formedness --
        # (checked before anything stateful, so a malformed request is never
        # partially recorded as an intent).
        if side == "buy":
            intent = ActionIntent.BUY_TO_OPEN
        elif side == "sell":
            intent = ActionIntent.SELL_TO_CLOSE
        else:
            self._reject("UNSUPPORTED_ACTION_INTENT", symbol, source, alpha_evidence)
        if not isinstance(quantity, (int, float)) or isinstance(quantity, bool) or not math.isfinite(quantity) or quantity <= 0:
            self._reject("INVALID_QUANTITY", symbol, source, alpha_evidence)
        if source not in ALLOWED_ORDER_SOURCES:
            self._reject("UNAUTHORIZED_SOURCE", symbol, source, alpha_evidence)

        intent_id = stable_id("intent", signal_id, symbol, side, quantity)
        if intent_id in self.state.intents:
            self.events.emit(PivEvent.build("BROKER_ERROR", symbol=symbol, correlation_id=intent_id, reason="DUPLICATE_ORDER_INTENT"))
            raise PaperGuardError("duplicate order intent")
        if not self.state.session_enabled or self.state.kill_switch:
            raise PaperGuardError("new paper orders are disabled")

        # -- Task 76S Stage 3: long-only position/order-state boundary --
        # Revalidated here, against CURRENT persisted state, every single
        # call -- never trusted from a caller's own (possibly stale) local
        # bookkeeping (e.g. lifecycle_probe.py's own pre-check is caller-side
        # discipline; this is the boundary that cannot be bypassed).
        if intent is ActionIntent.BUY_TO_OPEN:
            if self.state.reconciliation_flags.get("unexpected_short_detected"):
                self._reject("UNEXPECTED_SHORT_BLOCKS_NEW_ENTRIES", symbol, source, alpha_evidence)
            if self._open_position_for(symbol) is not None:
                self._reject("ALREADY_HOLDING_NO_PYRAMIDING", symbol, source, alpha_evidence)
            if self._non_terminal_orders_for(symbol, "buy"):
                self._reject("PENDING_ENTRY_EXISTS", symbol, source, alpha_evidence)
            if not self.paper_entry_settings.enabled_for(symbol):
                self._reject("PAPER_ENTRY_DISABLED_FOR_TICKER", symbol, source, alpha_evidence)
        else:  # SELL_TO_CLOSE
            position = self._open_position_for(symbol)
            if position is None:
                self._reject("SELL_WHILE_FLAT", symbol, source, alpha_evidence)
            held = float(position.get("quantity") or 0.0)
            pending_sell = self._pending_quantity(symbol, "sell")
            available = held - pending_sell
            if quantity > available + 1e-9:
                self._reject("OVERSIZED_OR_DUPLICATE_SELL", symbol, source, alpha_evidence)

        payload = {
            "symbol": symbol, "side": side, "qty": str(quantity), "type": "market",
            "time_in_force": "day", "client_order_id": client_order_id or intent_id,
        }
        self.state.intents[intent_id] = {
            "signal_id": signal_id, "payload": payload, "status": "ORDER_INTENT",
            "source": source, "alpha_evidence": alpha_evidence,
            "reference_price": reference_price, "stop_price": stop_price,
            "signal_timestamp": signal_timestamp, "strategy_id": strategy_id, "horizon": horizon,
        }
        self._save()
        self.events.emit(PivEvent.build(
            "ORDER_INTENT", symbol=symbol, signal_id=signal_id, order_intent_id=intent_id, correlation_id=intent_id,
            quantity=quantity, source=source, alpha_evidence=alpha_evidence,
        ))
        result = self.broker.submit_order(payload)
        broker_id = str(result.get("id") or "")
        if not broker_id:
            self.state.intents[intent_id]["status"] = "REJECTED"
            self._save()
            self.events.emit(PivEvent.build(
                "PAPER_ORDER_REJECTED", symbol=symbol, order_intent_id=intent_id, correlation_id=intent_id,
                reason="MISSING_BROKER_ORDER_ID", source=source, alpha_evidence=alpha_evidence,
            ))
            raise PaperGuardError("paper broker did not return an order id")
        self.state.intents[intent_id]["status"] = "SUBMITTED"
        self.state.orders[broker_id] = {
            "intent_id": intent_id, "symbol": symbol, "status": "SUBMITTED", "filled_qty": 0.0,
            "source": source, "alpha_evidence": alpha_evidence,
        }
        self._save()
        self.events.emit(PivEvent.build(
            "PAPER_ORDER_SUBMITTED", symbol=symbol, order_intent_id=intent_id, broker_order_id=broker_id,
            correlation_id=intent_id, quantity=quantity, source=source, alpha_evidence=alpha_evidence,
        ))
        return result

    def apply_broker_update(self, broker_order_id: str, status: str, filled_qty: float = 0.0, fill_price: float | None = None) -> None:
        order = self.state.orders[broker_order_id]
        order.update(status=status, filled_qty=filled_qty, fill_price=fill_price)
        intent_id, symbol = order["intent_id"], order["symbol"]
        source, alpha_evidence = order.get("source"), order.get("alpha_evidence")
        event = {
            "accepted": "PAPER_ORDER_ACCEPTED", "partially_filled": "PARTIAL_FILL",
            "filled": "FILLED", "rejected": "PAPER_ORDER_REJECTED", "canceled": "PAPER_ORDER_CANCELLED",
        }.get(status)
        if event:
            self.events.emit(PivEvent.build(
                event, symbol=symbol, correlation_id=intent_id, order_intent_id=intent_id,
                broker_order_id=broker_order_id, quantity=filled_qty, price=fill_price, status=status,
                source=source, alpha_evidence=alpha_evidence,
            ))
        if status in {"partially_filled", "filled"} and filled_qty > 0:
            # Task 69Q Part 5: a fill is an EXIT (closes the symbol's tracked
            # open position) iff this order is a sell AND open_position_by_
            # symbol has a tracked OPEN position for this symbol -- otherwise
            # it's an entry/open, same as before. This is what prevents an
            # exit fill from emitting a second, misleading POSITION_OPENED
            # (confirmed live in Task69P's raw events: the 19:01:30Z exit fill
            # produced POSITION_OPENED instead of POSITION_CLOSED).
            intent = self.state.intents.get(intent_id, {})
            side = intent.get("payload", {}).get("side")
            reference_price = intent.get("reference_price")
            stop_price = intent.get("stop_price")
            strategy_id = intent.get("strategy_id")
            horizon = intent.get("horizon")
            now_iso = datetime.now(timezone.utc).isoformat()
            existing_position_id = self.state.open_position_by_symbol.get(symbol)

            if side == "sell" and existing_position_id is not None and existing_position_id in self.state.positions:
                position = self.state.positions[existing_position_id]
                entry_price = position.get("price")
                entry_quantity = position.get("quantity") or filled_qty
                entry_time = position.get("entry_time")
                exit_slippage_abs = (fill_price - reference_price) if (fill_price is not None and reference_price is not None) else None
                exit_slippage_bps = (exit_slippage_abs / reference_price * 10000) if (exit_slippage_abs is not None and reference_price) else None
                gross_pnl = ((fill_price - entry_price) * entry_quantity) if (fill_price is not None and entry_price is not None) else None
                # PAPER broker models zero commissions/fees; net_pnl equals
                # gross_pnl today. estimated_transaction_cost is carried
                # explicitly (rather than omitted) so a future real cost model
                # only has to change this one value, not the schema.
                estimated_transaction_cost = 0.0 if gross_pnl is not None else None
                net_pnl = (gross_pnl - estimated_transaction_cost) if gross_pnl is not None else None
                holding_seconds = None
                if entry_time is not None:
                    try:
                        holding_seconds = (datetime.fromisoformat(now_iso) - datetime.fromisoformat(entry_time)).total_seconds()
                    except ValueError:
                        holding_seconds = None
                position_stop = position.get("stop_price")
                gross_r = net_r = None
                if position_stop is not None and entry_price is not None and entry_price != position_stop and gross_pnl is not None:
                    denom = (entry_price - position_stop) * entry_quantity
                    if denom:
                        gross_r, net_r = gross_pnl / denom, net_pnl / denom
                position.update(
                    status="CLOSED", exit_price=fill_price, exit_quantity=filled_qty,
                    exit_reference_price=reference_price, gross_pnl=gross_pnl, net_pnl=net_pnl,
                    holding_seconds=holding_seconds,
                )
                del self.state.open_position_by_symbol[symbol]
                self.events.emit(PivEvent.build(
                    "POSITION_CLOSED", symbol=symbol, correlation_id=intent_id, broker_order_id=broker_order_id,
                    position_id=existing_position_id, quantity=filled_qty, price=fill_price,
                    source=source, alpha_evidence=alpha_evidence, reference_price=reference_price,
                    slippage_abs=exit_slippage_abs, slippage_bps=exit_slippage_bps,
                    gross_pnl=gross_pnl, net_pnl=net_pnl, estimated_transaction_cost=estimated_transaction_cost,
                    holding_seconds=holding_seconds, gross_r=gross_r, net_r=net_r,
                    horizon=horizon or position.get("horizon"), strategy_id=strategy_id or position.get("strategy_id"),
                ))
            else:
                position_id = stable_id("position", intent_id, symbol)
                first = position_id not in self.state.positions
                entry_slippage_abs = (fill_price - reference_price) if (fill_price is not None and reference_price is not None) else None
                entry_slippage_bps = (entry_slippage_abs / reference_price * 10000) if (entry_slippage_abs is not None and reference_price) else None
                self.state.positions[position_id] = {
                    "symbol": symbol, "quantity": filled_qty, "price": fill_price, "status": "OPEN",
                    "source": source, "alpha_evidence": alpha_evidence, "entry_time": now_iso,
                    "reference_price": reference_price, "stop_price": stop_price,
                    "strategy_id": strategy_id, "horizon": horizon,
                }
                if side == "buy":
                    self.state.open_position_by_symbol[symbol] = position_id
                if first:
                    self.events.emit(PivEvent.build(
                        "POSITION_OPENED", symbol=symbol, correlation_id=intent_id, broker_order_id=broker_order_id,
                        position_id=position_id, quantity=filled_qty, price=fill_price, source=source,
                        alpha_evidence=alpha_evidence, reference_price=reference_price,
                        slippage_abs=entry_slippage_abs, slippage_bps=entry_slippage_bps,
                        strategy_id=strategy_id, horizon=horizon,
                    ))
        self._save()

    def poll_order_until_terminal(self, broker_order_id: str, *, timeout_seconds: float = 20.0, poll_interval_seconds: float = 1.0, sleep=None) -> dict[str, Any]:
        """Poll the live PAPER broker for this order's status and apply each
        observed transition via apply_broker_update, until a terminal status
        (filled/rejected/canceled) or timeout_seconds elapses. Nothing in the
        live path previously called apply_broker_update at all -- Task 64's
        tests only ever called it directly -- so without this, a real
        PAPER_ORDER_SUBMITTED would never progress to an ack/fill/position in
        a live session."""
        import time as _time
        sleep = sleep or _time.sleep
        elapsed = 0.0
        last: dict[str, Any] = {}
        seen_status: str | None = None
        terminal = {"filled", "rejected", "canceled", "expired"}
        while elapsed <= timeout_seconds:
            last = self.broker.get_order(broker_order_id)
            status = str(last.get("status") or "")
            filled_qty = float(last.get("filled_qty") or 0.0)
            fill_price = float(last["filled_avg_price"]) if last.get("filled_avg_price") else None
            if status and status != seen_status:
                seen_status = status
                self.apply_broker_update(broker_order_id, status, filled_qty, fill_price)
            if status in terminal:
                break
            sleep(poll_interval_seconds)
            elapsed += poll_interval_seconds
        return last

    def activate_kill_switch(self, cancel_orders: bool = False) -> None:
        self.state.kill_switch = True
        self.state.session_enabled = False
        self._save()
        if cancel_orders:
            self.broker.cancel_all_orders()
        self.events.emit(PivEvent.build("KILL_SWITCH", reason="OPERATOR_ACTIVATED", status="NEW_PAPER_ORDERS_BLOCKED"))

    def reconcile(self) -> dict[str, Any]:
        broker_orders = self.broker.open_orders()
        broker_positions = self.broker.positions()
        internal_open = {v["symbol"] for v in self.state.positions.values() if v.get("status") == "OPEN"}
        broker_open = {str(v.get("symbol")) for v in broker_positions}

        # Task 76S Stage 3: a broker-reported SHORT this system never opened
        # (side=="short" or a negative qty) is an unexpected-state safety
        # trip-wire, not something to silently reconcile away or auto-fix --
        # persisted so order_intent's BUY guard can block new entries until
        # an operator investigates. No remediation is attempted here.
        unexpected_shorts = sorted(
            str(p.get("symbol")) for p in broker_positions
            if str(p.get("side", "")).lower() == "short" or _safe_float(p.get("qty")) < 0
        )
        self.state.reconciliation_flags = {
            "unexpected_short_detected": bool(unexpected_shorts),
            "unexpected_short_symbols": unexpected_shorts,
        }
        self._save()

        return {
            "broker_open_orders": len(broker_orders), "broker_positions": len(broker_positions),
            "internal_positions": len(internal_open), "matched": internal_open == broker_open,
            "unexpected_broker_symbols": sorted(broker_open - internal_open),
            "missing_broker_symbols": sorted(internal_open - broker_open),
            "unexpected_short_symbols": unexpected_shorts,
        }

    def eod_flatten(self) -> dict[str, Any]:
        self.broker.cancel_all_orders()
        self.broker.close_all_positions()
        for position in self.state.positions.values():
            position["status"] = "CLOSED"
        self.state.session_enabled = False
        self._save()
        self.events.emit(PivEvent.build("EOD_FLATTEN", status="PAPER_ORDERS_CANCELLED_AND_POSITIONS_CLOSE_REQUESTED"))
        return self.reconcile()


def paper_cleanup(broker: AlpacaPaperClient, events: EventBus, explicitly_confirmed: bool) -> dict[str, Any]:
    if not explicitly_confirmed:
        raise PaperGuardError("paper cleanup requires explicit confirmation")
    identity = broker.verify_paper_identity()
    cancelled = broker.cancel_all_orders()
    closed = broker.close_all_positions()
    residual_orders = broker.open_orders()
    residual_positions = broker.positions()
    result = {
        "environment": identity.environment, "endpoint": identity.endpoint,
        "cancel_actions": len(cancelled), "close_actions": len(closed),
        "residual_orders": len(residual_orders), "residual_positions": len(residual_positions),
        "clean": not residual_orders and not residual_positions,
    }
    events.emit(PivEvent.build("SESSION_SUMMARY", reason="EXPLICIT_PAPER_CLEANUP", status=json.dumps(result, sort_keys=True)))
    return result
