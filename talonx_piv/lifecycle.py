"""Persistent, idempotent Alpaca-paper order lifecycle and reconciliation."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
from typing import Any

from .broker import AlpacaPaperClient, PaperGuardError
from .events import EventBus, PivEvent


def stable_id(prefix: str, *parts: object) -> str:
    body = "|".join(str(part) for part in parts)
    return f"{prefix}_{hashlib.sha256(body.encode()).hexdigest()[:20]}"


@dataclass
class LifecycleState:
    session_enabled: bool = False
    kill_switch: bool = False
    intents: dict[str, dict[str, Any]] = field(default_factory=dict)
    orders: dict[str, dict[str, Any]] = field(default_factory=dict)
    positions: dict[str, dict[str, Any]] = field(default_factory=dict)


class PaperLifecycle:
    def __init__(self, state_path: Path, broker: AlpacaPaperClient, events: EventBus) -> None:
        self.state_path = state_path
        self.broker = broker
        self.events = events
        self.state = self._load()

    def _load(self) -> LifecycleState:
        if not self.state_path.exists():
            return LifecycleState()
        return LifecycleState(**json.loads(self.state_path.read_text(encoding="utf-8")))

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

    def order_intent(self, signal_id: str, symbol: str, side: str, quantity: float, client_order_id: str | None = None) -> dict[str, Any]:
        intent_id = stable_id("intent", signal_id, symbol, side, quantity)
        if intent_id in self.state.intents:
            self.events.emit(PivEvent.build("BROKER_ERROR", symbol=symbol, correlation_id=intent_id, reason="DUPLICATE_ORDER_INTENT"))
            raise PaperGuardError("duplicate order intent")
        if not self.state.session_enabled or self.state.kill_switch:
            raise PaperGuardError("new paper orders are disabled")
        payload = {
            "symbol": symbol, "side": side, "qty": str(quantity), "type": "market",
            "time_in_force": "day", "client_order_id": client_order_id or intent_id,
        }
        self.state.intents[intent_id] = {"signal_id": signal_id, "payload": payload, "status": "ORDER_INTENT"}
        self._save()
        self.events.emit(PivEvent.build("ORDER_INTENT", symbol=symbol, signal_id=signal_id, order_intent_id=intent_id, correlation_id=intent_id, quantity=quantity))
        result = self.broker.submit_order(payload)
        broker_id = str(result.get("id") or "")
        if not broker_id:
            self.state.intents[intent_id]["status"] = "REJECTED"
            self._save()
            self.events.emit(PivEvent.build("PAPER_ORDER_REJECTED", symbol=symbol, order_intent_id=intent_id, correlation_id=intent_id, reason="MISSING_BROKER_ORDER_ID"))
            raise PaperGuardError("paper broker did not return an order id")
        self.state.intents[intent_id]["status"] = "SUBMITTED"
        self.state.orders[broker_id] = {"intent_id": intent_id, "symbol": symbol, "status": "SUBMITTED", "filled_qty": 0.0}
        self._save()
        self.events.emit(PivEvent.build("PAPER_ORDER_SUBMITTED", symbol=symbol, order_intent_id=intent_id, broker_order_id=broker_id, correlation_id=intent_id, quantity=quantity))
        return result

    def apply_broker_update(self, broker_order_id: str, status: str, filled_qty: float = 0.0, fill_price: float | None = None) -> None:
        order = self.state.orders[broker_order_id]
        order.update(status=status, filled_qty=filled_qty, fill_price=fill_price)
        intent_id, symbol = order["intent_id"], order["symbol"]
        event = {
            "accepted": "PAPER_ORDER_ACCEPTED", "partially_filled": "PARTIAL_FILL",
            "filled": "FILLED", "rejected": "PAPER_ORDER_REJECTED", "canceled": "PAPER_ORDER_CANCELLED",
        }.get(status)
        if event:
            self.events.emit(PivEvent.build(event, symbol=symbol, correlation_id=intent_id, order_intent_id=intent_id, broker_order_id=broker_order_id, quantity=filled_qty, price=fill_price, status=status))
        if status in {"partially_filled", "filled"} and filled_qty > 0:
            position_id = stable_id("position", intent_id, symbol)
            first = position_id not in self.state.positions
            self.state.positions[position_id] = {"symbol": symbol, "quantity": filled_qty, "price": fill_price, "status": "OPEN"}
            if first:
                self.events.emit(PivEvent.build("POSITION_OPENED", symbol=symbol, correlation_id=intent_id, broker_order_id=broker_order_id, position_id=position_id, quantity=filled_qty, price=fill_price))
        self._save()

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
        return {
            "broker_open_orders": len(broker_orders), "broker_positions": len(broker_positions),
            "internal_positions": len(internal_open), "matched": internal_open == broker_open,
            "unexpected_broker_symbols": sorted(broker_open - internal_open),
            "missing_broker_symbols": sorted(internal_open - broker_open),
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
