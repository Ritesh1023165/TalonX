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
from .experimental_authorization import ExperimentalAuthorization

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
ALLOWED_ORDER_SOURCES: frozenset[str | None] = frozenset({None, "STRATEGY", "PIV_LIFECYCLE_PROBE", "EXPERIMENTAL"})

# Alpaca order-status vocabulary this module observes via apply_broker_update
# plus this module's own pre-broker-ack "SUBMITTED" -- anything NOT in this
# terminal set is treated as still-pending/outstanding for oversell and
# duplicate-entry detection below.
_TERMINAL_ORDER_STATUSES = frozenset({"filled", "rejected", "canceled", "expired"})

# Task 79E-R2: a SUBMIT_FAILED_UNCERTAIN intent is only ever declared
# SUBMIT_FAILED_CONFIRMED_NOT_SUBMITTED after find_order_by_client_id has
# returned "not found" this many SEPARATE times, across separate
# reconcile() calls -- "a single 404 must not mean confirmed never
# submitted." Every uncertain-exposure protection (pyramiding block,
# experimental concurrent-exposure/budget reservation) is retained for the
# full duration, never released early.
UNCERTAIN_SUBMISSION_CONFIRMATION_THRESHOLD = 2


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
    # Task 79E: keyed by experiment_id -- durable, restart-safe usage
    # counters for the experimental PAPER budget. Deliberately part of THIS
    # persisted state (not recomputed from the authorization object, which
    # can be reloaded/toggled/re-minted across process restarts without
    # resetting spend already committed against the SAME experiment_id).
    # Absent/empty on an old state file, exactly like reconciliation_flags.
    experimental_budgets: dict[str, dict[str, Any]] = field(default_factory=dict)


class PaperLifecycle:
    def __init__(
        self, state_path: Path, broker: AlpacaPaperClient, events: EventBus,
        paper_entry_settings: PaperEntrySettings | None = None,
        experimental_authorization: ExperimentalAuthorization | None = None,
        runtime_sha: str | None = None, config_hash: str | None = None,
        experimental_authorization_path: Path | None = None,
    ) -> None:
        self.state_path = state_path
        self.broker = broker
        self.events = events
        # Task 76S Stage 2: fail-closed default -- a caller that does not
        # supply settings gets an ALL-DISABLED PaperEntrySettings, never a
        # permissive one. See execution_settings.py's own module docstring
        # for the migration rationale.
        self.paper_entry_settings = paper_entry_settings or PaperEntrySettings.all_disabled()
        # Task 79E: None (the default -- every pre-Task79E caller/test) means
        # NO experimental authorization at all -- every EXPERIMENTAL-sourced
        # order_intent call is rejected outright (see order_intent's own
        # guard). Never inferred/constructed here; always the caller's
        # explicit choice.
        self.experimental_authorization = experimental_authorization
        # Task 79E-R1: when set, THIS takes priority over the static object
        # above -- every guard call reloads fresh from disk (see
        # _current_experimental_authorization), so an operator deleting,
        # disabling, or editing the file mid-session is observed on the very
        # next order_intent call, not only after a process restart. cli.py's
        # real runtime() always sets this; `experimental_authorization=`
        # (the object) remains supported unchanged for every pre-existing
        # test/caller that constructs a fixed authorization directly.
        self.experimental_authorization_path = experimental_authorization_path
        self.runtime_sha = runtime_sha
        self.config_hash = config_hash
        self.state = self._load()

    def _current_experimental_authorization(self) -> ExperimentalAuthorization | None:
        if self.experimental_authorization_path is not None:
            from .experimental_authorization import load_experimental_authorization
            return load_experimental_authorization(self.experimental_authorization_path)
        return self.experimental_authorization

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

    def _orphaned_uncertain_intents_for(self, symbol: str, side: str) -> list[dict[str, Any]]:
        """Task 79E: an intent whose submit_order call itself raised (see
        order_intent's own try/except) has NO entry in self.state.orders at
        all -- self._non_terminal_orders_for would be blind to it. Without
        this, a same-symbol retry after a submission failure could oversell/
        pyramid against a genuinely-uncertain outstanding request."""
        out = []
        for intent in self.state.intents.values():
            if intent.get("status") != "SUBMIT_FAILED_UNCERTAIN":
                continue
            payload = intent.get("payload", {})
            if payload.get("symbol") == symbol and payload.get("side") == side:
                out.append(intent)
        return out

    def _orphaned_uncertain_intents_for_any_symbol(self, side: str) -> list[dict[str, Any]]:
        """Same as `_orphaned_uncertain_intents_for` but across ALL symbols --
        used by the experimental concurrent-exposure guard (Task 79E-R1),
        which must see uncertain exposure regardless of which symbol it
        landed on."""
        return [
            intent for intent in self.state.intents.values()
            if intent.get("status") == "SUBMIT_FAILED_UNCERTAIN" and intent.get("payload", {}).get("side") == side
        ]

    def _pending_quantity(self, symbol: str, side: str) -> float:
        """Sum of (originally-requested - filled_qty) across every
        non-terminal order of `side` for `symbol` -- what is already
        "spoken for" by an outstanding request, so a second request cannot
        oversell/duplicate against stale (already-terminal-in-reality)
        local state. Also includes any orphaned SUBMIT_FAILED_UNCERTAIN
        intent's full requested quantity (Task 79E) -- an uncertain outcome
        is never treated as zero exposure."""
        total = 0.0
        for order in self._non_terminal_orders_for(symbol, side):
            intent = self.state.intents.get(order.get("intent_id"), {})
            requested = float(intent.get("payload", {}).get("qty", 0.0) or 0.0)
            total += max(0.0, requested - float(order.get("filled_qty") or 0.0))
        for intent in self._orphaned_uncertain_intents_for(symbol, side):
            total += float(intent.get("payload", {}).get("qty", 0.0) or 0.0)
        return total

    def entry_still_pending_or_uncertain(self, symbol: str) -> bool:
        """Task 79E-R2: True iff a BUY for `symbol` has been submitted (or
        its true outcome is still genuinely uncertain -- SUBMIT_FAILED_
        UNCERTAIN, not yet resolved either way) but has not yet resolved to
        either a confirmed fill (an OPEN position) or a confirmed non-fill
        (rejected / SUBMIT_FAILED_CONFIRMED_NOT_SUBMITTED). Used by
        decision_engine.py so exit-plan tracking is never deleted merely
        because `_open_position_for(symbol)` does not show an OPEN
        position YET -- an entry can be legitimately pending (accepted,
        not yet filled) for one or more ticks before its fill lands."""
        return bool(self._non_terminal_orders_for(symbol, "buy") or self._orphaned_uncertain_intents_for(symbol, "buy"))

    def mark_exit_triggered(self, symbol: str, reason: str) -> None:
        """Task 79E-R2: persists the triggered-exit reason onto `symbol`'s
        OPEN position record so a restart AFTER a stop/target has fired --
        but before the resulting sell is confirmed -- does not lose the
        fact that this position MUST still be sold, even if price recovers
        before the process comes back up (see decision_engine.py's
        _rehydrate_positions, which reads this back into
        OpenDecisionPosition.exit_reason). A no-op if there is no OPEN
        position for the symbol, or if a reason is already recorded
        (first-write-wins, matching the in-memory latch's own semantics --
        the ORIGINAL trigger reason is what must survive, never overwritten
        by a later, possibly-different one)."""
        position = self._open_position_for(symbol)
        if position is None or position.get("triggered_exit_reason"):
            return
        position["triggered_exit_reason"] = reason
        self._save()

    def remaining_holdings(self, symbol: str) -> float:
        """Task 79E-R1: actual current holdings for `symbol` minus whatever
        is already spoken for by a non-terminal or uncertain sell -- i.e.
        what a NEW sell attempt could still legitimately request right now.
        0.0 if no OPEN position exists. Used by decision_engine.py so an
        exit is sized to REAL remaining holdings (after any prior partial
        fill) rather than a fixed constant, and so a second exit attempt on
        the same still-partially-filled position never oversells/duplicates
        (mirrors order_intent's own SELL_TO_CLOSE `available` computation
        exactly -- this is the read-only counterpart callers can consult
        BEFORE deciding whether there is anything left to sell)."""
        position = self._open_position_for(symbol)
        if position is None:
            return 0.0
        held = float(position.get("remaining_quantity", position.get("quantity")) or 0.0)
        pending_sell = self._pending_quantity(symbol, "sell")
        return max(0.0, held - pending_sell)

    def _experimental_prior_activity_exists(self, experiment_id: str) -> bool:
        """Task 79E-R1: used to distinguish "this experiment has genuinely
        never spent anything yet" (a fresh, all-zero budget record is
        correct) from "budget bookkeeping for this experiment_id is MISSING
        despite real prior activity" (state damage/loss -- must fail closed,
        never silently treated as zero exposure)."""
        for position in self.state.positions.values():
            if position.get("experimental_id") == experiment_id:
                return True
        for intent in self.state.intents.values():
            if intent.get("experimental_id") == experiment_id:
                return True
        return False

    def _validated_budget_record(self, experiment_id: str) -> dict[str, Any] | None:
        """Task 79E-R1: strict, fail-closed parsing of the durable budget
        record -- mirrors experimental_authorization.py's own strict-parsing
        posture (bool checked before int/float since bool is an int
        subclass; every numeric value must be finite; never negative).
        Returns None (caller must reject/fail closed) for: a missing record
        that nonetheless has prior recorded activity for this experiment_id
        (state loss, not a fresh start), a non-dict record, a boolean/
        negative/non-finite entries_used or notional_used, or any other
        malformed shape. The damaged raw value is deliberately NOT
        overwritten/reset by this method -- only order_intent's own
        `_reject` path is ever reached from here, which raises before any
        write, preserving the damaged state as evidence for an operator to
        inspect (see remaining_issues.md)."""
        raw = self.state.experimental_budgets.get(experiment_id)
        if raw is None:
            if self._experimental_prior_activity_exists(experiment_id):
                return None
            return {"entries_used": 0, "notional_used": 0.0}
        if not isinstance(raw, dict):
            return None
        entries_used = raw.get("entries_used")
        notional_used = raw.get("notional_used")
        if isinstance(entries_used, bool) or not isinstance(entries_used, int) or entries_used < 0:
            return None
        if isinstance(notional_used, bool) or not isinstance(notional_used, (int, float)):
            return None
        if not math.isfinite(notional_used) or notional_used < 0:
            return None
        return {"entries_used": entries_used, "notional_used": float(notional_used)}

    def _reject(self, reason: str, symbol: str, source: str | None, alpha_evidence: bool | None) -> None:
        self.events.emit(PivEvent.build(
            "PAPER_ORDER_REJECTED", symbol=symbol, reason=reason, source=source, alpha_evidence=alpha_evidence,
        ))
        raise PaperGuardError(reason)

    def _enforce_experimental_paper_guards(
        self, *, symbol: str, source: str | None, alpha_evidence: bool | None, quantity: float,
        reference_price: float | None, experimental_id: str | None, trading_date_et: str | None,
        strategy_id: str | None, strategy_version: str | None, session_scope: str | None,
    ) -> None:
        """Task 79E -- re-validated fresh on EVERY EXPERIMENTAL entry
        attempt, never cached from an earlier decision-layer check (Task
        79E-R1: this now includes re-LOADING the authorization object
        itself, not just checking `now` fresh against a cached one -- see
        `_current_experimental_authorization`). Reserves (increments) the
        durable budget atomically with the guard pass -- this method either
        fully succeeds (guards passed AND budget reserved) or raises via
        `_reject` with NO state mutated, since `_reject` always raises
        before any `self.state.experimental_budgets` write below is
        reached."""
        auth = self._current_experimental_authorization()
        if auth is None:
            self._reject("EXPERIMENTAL_AUTHORIZATION_NOT_CONFIGURED", symbol, source, alpha_evidence)
        if self.broker.identity is None:
            self._reject("EXPERIMENTAL_ACCOUNT_NOT_VERIFIED", symbol, source, alpha_evidence)
        ok, reason = auth.permits_paper_execution(
            symbol=symbol, trading_date_et=trading_date_et or "", strategy_id=strategy_id or "",
            strategy_version=strategy_version or "", runtime_sha=self.runtime_sha or "",
            config_hash=self.config_hash or "", now=datetime.now(timezone.utc),
            account_id=self.broker.identity.account_id, session_scope=session_scope,
        )
        if not ok:
            self._reject(f"EXPERIMENTAL_{reason}", symbol, source, alpha_evidence)
        if experimental_id != auth.experiment_id:
            self._reject("EXPERIMENTAL_ID_MISMATCH", symbol, source, alpha_evidence)
        if quantity > auth.paper.max_quantity_per_entry + 1e-9:
            self._reject("EXPERIMENTAL_QUANTITY_EXCEEDS_LIMIT", symbol, source, alpha_evidence)

        # Task 79E-R1: PENDING (submitted, not yet filled) and genuinely
        # UNCERTAIN (SUBMIT_FAILED_UNCERTAIN) experimental buy exposure
        # counts toward concurrent exposure too -- not only CONFIRMED OPEN
        # positions. Without this, two different symbols could each pass a
        # max_concurrent_exposure=1 check back-to-back before either one's
        # order actually fills (the original bug this closes: symbol A's
        # entry is SUBMITTED-but-not-yet-FILLED when symbol B's own guard
        # check runs and sees zero OPEN positions). A per-SYMBOL set (not a
        # raw count) avoids double-counting a single symbol whose order is
        # simultaneously "OPEN position" (a partial fill already landed) AND
        # "non-terminal order" (more of that same fill is still outstanding).
        exposed_symbols: set[str] = set()
        for position in self.state.positions.values():
            if position.get("status") == "OPEN" and position.get("experimental_id") == auth.experiment_id:
                exposed_symbols.add(str(position.get("symbol")))
        for order in self.state.orders.values():
            if order.get("status") in _TERMINAL_ORDER_STATUSES:
                continue
            intent = self.state.intents.get(order.get("intent_id"), {})
            if intent.get("payload", {}).get("side") != "buy" or intent.get("experimental_id") != auth.experiment_id:
                continue
            exposed_symbols.add(str(order.get("symbol")))
        for intent in self._orphaned_uncertain_intents_for_any_symbol("buy"):
            if intent.get("experimental_id") == auth.experiment_id:
                exposed_symbols.add(str(intent.get("payload", {}).get("symbol")))
        if len(exposed_symbols) >= auth.paper.max_concurrent_exposure:
            self._reject("EXPERIMENTAL_CONCURRENT_EXPOSURE_LIMIT", symbol, source, alpha_evidence)

        budget = self._validated_budget_record(auth.experiment_id)
        if budget is None:
            self.events.emit(PivEvent.build(
                "BROKER_ERROR", symbol=symbol, reason="EXPERIMENTAL_BUDGET_STATE_DAMAGED", source=source,
                status=json.dumps(self.state.experimental_budgets.get(auth.experiment_id), sort_keys=True, default=str),
            ))
            self._reject("EXPERIMENTAL_BUDGET_STATE_DAMAGED_FAIL_CLOSED", symbol, source, alpha_evidence)
        if budget["entries_used"] >= auth.paper.max_entry_count:
            self._reject("EXPERIMENTAL_ENTRY_COUNT_EXHAUSTED", symbol, source, alpha_evidence)
        # Reference-price budget check ONLY -- never a hard cap on realised
        # fill value (existing orders are market orders; the eventual fill
        # price can differ from reference_price). If reference_price is
        # unavailable OR not a genuine finite positive price, the requested
        # notional cannot be estimated at all -- fail closed rather than
        # treat it as zero-cost or silently misuse a bad value.
        if (
            reference_price is None or isinstance(reference_price, bool)
            or not isinstance(reference_price, (int, float)) or not math.isfinite(reference_price)
            or reference_price <= 0
        ):
            reason = "EXPERIMENTAL_REFERENCE_PRICE_REQUIRED_FOR_BUDGET_CHECK" if reference_price is None else "EXPERIMENTAL_REFERENCE_PRICE_INVALID"
            self._reject(reason, symbol, source, alpha_evidence)
        requested_notional = float(reference_price) * float(quantity)
        if budget["notional_used"] + requested_notional > auth.paper.max_reference_notional_budget + 1e-9:
            self._reject("EXPERIMENTAL_NOTIONAL_BUDGET_EXHAUSTED", symbol, source, alpha_evidence)

        # All guards passed -- reserve the budget now (conservatively, never
        # refunded on a later submission failure: see order_intent's own
        # submit_order try/except -- an uncertain outcome must not free up
        # budget that might still be consumed at the broker).
        self.state.experimental_budgets[auth.experiment_id] = {
            "entries_used": budget["entries_used"] + 1,
            "notional_used": budget["notional_used"] + requested_notional,
        }

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
        # Task 79E-R1: persisted alongside stop_price so a position's full
        # exit plan survives a process restart -- see decision_engine.py's
        # _rehydrate_positions, which reads this back from the position
        # record apply_broker_update writes on fill (below), rather than
        # inventing/guessing a target for a restored position.
        target_price: float | None = None,
        signal_timestamp: str | None = None, strategy_id: str | None = None,
        horizon: str | None = None,
        # Task 78I Stage 1C: optional cross-reference to the
        # talonx_piv.decision_contract.Decision this order was raised from --
        # never validated/consumed by this method itself (order_intent's own
        # guards are unaffected), purely so a later status projection
        # (observability.py) can join an intent/order back to its decision
        # WITHOUT reconstructing signal_id from decision_id (which happen to
        # share their derivation inputs today only by coincidence, not by any
        # guaranteed contract) -- an explicit field is more robust than an
        # implicit one. Absent on any pre-Task78I intent (old state files),
        # which simply cannot be joined to a decision -- an acceptable,
        # documented restart-compatibility edge case, exactly like
        # open_position_by_symbol's own historical rollout.
        decision_id: str | None = None,
        # Task 79E: only meaningful when source=="EXPERIMENTAL" -- the
        # decision layer's OWN prior permission check (decision_contract
        # .decide()) is never trusted alone; every field needed to
        # re-validate ExperimentalAuthorization.permits_paper_execution
        # fresh, right here at the true broker boundary, must be supplied
        # explicitly by the caller (decision_engine.py) rather than
        # reconstructed or assumed.
        experimental_id: str | None = None, experimental_trading_date_et: str | None = None,
        experimental_strategy_version: str | None = None,
        # Task 79E-R1: see experimental_authorization.py's own docstring --
        # both the decision layer AND this broker-boundary re-check must
        # independently supply the SAME fixed scope identifying "the live
        # natural-strategy decision path" (never the isolated
        # PIV_LIFECYCLE_PROBE lifecycle, which never calls order_intent with
        # source="EXPERIMENTAL" at all).
        experimental_session_scope: str | None = None,
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
            if self._non_terminal_orders_for(symbol, "buy") or self._orphaned_uncertain_intents_for(symbol, "buy"):
                self._reject("PENDING_ENTRY_EXISTS", symbol, source, alpha_evidence)
            if not self.paper_entry_settings.enabled_for(symbol):
                self._reject("PAPER_ENTRY_DISABLED_FOR_TICKER", symbol, source, alpha_evidence)
            if source == "EXPERIMENTAL":
                self._enforce_experimental_paper_guards(
                    symbol=symbol, source=source, alpha_evidence=alpha_evidence, quantity=quantity,
                    reference_price=reference_price, experimental_id=experimental_id,
                    trading_date_et=experimental_trading_date_et, strategy_id=strategy_id,
                    strategy_version=experimental_strategy_version, session_scope=experimental_session_scope,
                )
        else:  # SELL_TO_CLOSE
            position = self._open_position_for(symbol)
            if position is None:
                self._reject("SELL_WHILE_FLAT", symbol, source, alpha_evidence)
            # Task 77I: `remaining_quantity` (set once any closing fill has
            # been applied -- see apply_broker_update) reflects what is
            # ACTUALLY still held after a genuine partial close; a position
            # with no closing fills yet has no such key, so this falls back
            # to the full entry `quantity`, unchanged from before this task.
            held = float(position.get("remaining_quantity", position.get("quantity")) or 0.0)
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
            "reference_price": reference_price, "stop_price": stop_price, "target_price": target_price,
            "signal_timestamp": signal_timestamp, "strategy_id": strategy_id, "horizon": horizon,
            "decision_id": decision_id, "experimental_id": experimental_id,
        }
        self._save()
        self.events.emit(PivEvent.build(
            "ORDER_INTENT", symbol=symbol, signal_id=signal_id, order_intent_id=intent_id, correlation_id=intent_id,
            quantity=quantity, source=source, alpha_evidence=alpha_evidence,
        ))
        try:
            result = self.broker.submit_order(payload)
        except Exception as exc:  # noqa: BLE001 -- Task 79E: an HTTP-level submission failure BEFORE any
            # broker order id was ever received is genuinely uncertain -- the request may or may not have
            # reached/been accepted by the broker. Marked SUBMIT_FAILED_UNCERTAIN (never silently dropped,
            # never treated as "nothing happened") and kept visible to _non_terminal_orders_for/
            # _pending_quantity below so a same-symbol retry cannot oversell/pyramid against an outcome
            # that is still genuinely unknown. This is a DIFFERENT case from poll_order_until_terminal's
            # own UNCONFIRMED_TIMEOUT (Task 77I) -- that happens AFTER a broker order id already exists;
            # this happens BEFORE one ever does. The ORIGINAL exception is re-raised unchanged (never
            # wrapped as PaperGuardError) -- Task 78I's pre-existing contract is that a raw transport/
            # connectivity failure propagates uncaught past DecisionEngine._handle_entry (which only
            # catches PaperGuardError) to SessionRunner's own outer per-tick guard, the actual safety net
            # for a genuine connectivity failure; wrapping it here would silently swallow that signal one
            # layer too early.
            self.state.intents[intent_id]["status"] = "SUBMIT_FAILED_UNCERTAIN"
            self._save()
            self.events.emit(PivEvent.build(
                "BROKER_ERROR", symbol=symbol, order_intent_id=intent_id, correlation_id=intent_id,
                reason=f"SUBMIT_FAILED_UNCERTAIN_{type(exc).__name__}", source=source, alpha_evidence=alpha_evidence,
            ))
            raise
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
        # Task 77I: captured BEFORE this call's own update overwrites it --
        # Alpaca reports `filled_qty` CUMULATIVELY per order, so the amount
        # that actually happened THIS update is the delta since the
        # previously-stored value, not the raw field itself. See
        # partial_fill_before_after.md for the bug this fixes (a second
        # partially_filled/filled transition on the same closing order used
        # to fabricate an orphan phantom OPEN position).
        previous_filled_qty = float(order.get("filled_qty") or 0.0)
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
            target_price = intent.get("target_price")
            strategy_id = intent.get("strategy_id")
            horizon = intent.get("horizon")
            experimental_id = intent.get("experimental_id")
            entry_signal_bar_timestamp = intent.get("signal_timestamp")
            now_iso = datetime.now(timezone.utc).isoformat()
            existing_position_id = self.state.open_position_by_symbol.get(symbol)

            if side == "sell" and existing_position_id is not None and existing_position_id in self.state.positions:
                position = self.state.positions[existing_position_id]
                entry_price = position.get("price")
                entry_quantity = float(position.get("quantity") or 0.0) or filled_qty
                entry_time = position.get("entry_time")
                # Task 77I: incremental exit quantity for THIS update only --
                # never the order's full (possibly still-growing) cumulative
                # filled_qty, and never the position's full original entry
                # size. Accumulated across every closing fill this position
                # has ever seen (possibly from more than one closing order,
                # e.g. a scaled-out partial sell followed by a later sell of
                # the remainder).
                incremental_qty = max(0.0, filled_qty - previous_filled_qty)
                prior_exit_qty = float(position.get("exit_quantity") or 0.0)
                cumulative_exit_qty = prior_exit_qty + incremental_qty
                remaining_qty = max(0.0, entry_quantity - cumulative_exit_qty)
                exit_slippage_abs = (fill_price - reference_price) if (fill_price is not None and reference_price is not None) else None
                exit_slippage_bps = (exit_slippage_abs / reference_price * 10000) if (exit_slippage_abs is not None and reference_price) else None
                fill_gross_pnl = ((fill_price - entry_price) * incremental_qty) if (fill_price is not None and entry_price is not None) else None
                # PAPER broker models zero commissions/fees; net_pnl equals
                # gross_pnl today. estimated_transaction_cost is carried
                # explicitly (rather than omitted) so a future real cost model
                # only has to change this one value, not the schema.
                fill_transaction_cost = 0.0 if fill_gross_pnl is not None else None
                fill_net_pnl = (fill_gross_pnl - fill_transaction_cost) if fill_gross_pnl is not None else None
                prior_gross_pnl = position.get("gross_pnl")
                prior_net_pnl = position.get("net_pnl")
                cumulative_gross_pnl = (
                    (prior_gross_pnl or 0.0) + fill_gross_pnl if fill_gross_pnl is not None
                    else prior_gross_pnl
                )
                cumulative_net_pnl = (
                    (prior_net_pnl or 0.0) + fill_net_pnl if fill_net_pnl is not None
                    else prior_net_pnl
                )
                holding_seconds = None
                if entry_time is not None:
                    try:
                        holding_seconds = (datetime.fromisoformat(now_iso) - datetime.fromisoformat(entry_time)).total_seconds()
                    except ValueError:
                        holding_seconds = None
                position_stop = position.get("stop_price")
                gross_r = net_r = None
                if position_stop is not None and entry_price is not None and entry_price != position_stop and cumulative_gross_pnl is not None:
                    denom = (entry_price - position_stop) * entry_quantity
                    if denom:
                        gross_r, net_r = cumulative_gross_pnl / denom, cumulative_net_pnl / denom
                position.update(
                    exit_price=fill_price, exit_quantity=cumulative_exit_qty,
                    remaining_quantity=remaining_qty,
                    exit_reference_price=reference_price, gross_pnl=cumulative_gross_pnl, net_pnl=cumulative_net_pnl,
                    holding_seconds=holding_seconds,
                )
                fully_closed = remaining_qty <= 1e-9
                if fully_closed:
                    # Only NOW -- once the position's entire remaining size
                    # has actually been sold, possibly across more than one
                    # fill/order -- is it safe to mark CLOSED and free the
                    # symbol for a new entry. A partial fill leaves the
                    # position OPEN with a reduced remaining_quantity, and
                    # (critically) leaves open_position_by_symbol[symbol]
                    # intact, so a second fill-status transition on the SAME
                    # order re-attaches to this SAME position instead of
                    # falling into the open/BUY branch below and fabricating
                    # a phantom second position (the exact bug this fixes).
                    position["status"] = "CLOSED"
                    del self.state.open_position_by_symbol[symbol]
                    self.events.emit(PivEvent.build(
                        "POSITION_CLOSED", symbol=symbol, correlation_id=intent_id, broker_order_id=broker_order_id,
                        position_id=existing_position_id, quantity=cumulative_exit_qty, price=fill_price,
                        source=source, alpha_evidence=alpha_evidence, reference_price=reference_price,
                        slippage_abs=exit_slippage_abs, slippage_bps=exit_slippage_bps,
                        gross_pnl=cumulative_gross_pnl, net_pnl=cumulative_net_pnl, estimated_transaction_cost=fill_transaction_cost,
                        holding_seconds=holding_seconds, gross_r=gross_r, net_r=net_r,
                        horizon=horizon or position.get("horizon"), strategy_id=strategy_id or position.get("strategy_id"),
                    ))
            elif side == "buy":
                # Task 77I: explicitly gated on side=="buy" -- previously this
                # branch was reached for ANY fill lacking a currently-tracked
                # open position, including a sell fill whose position had
                # already been (prematurely) closed by the very bug fixed
                # above. With that bug fixed, a sell fill should never reach
                # here in normal operation; this guard makes it structurally
                # impossible to fabricate a phantom OPEN position from a SELL
                # fill even in an anomalous/out-of-band broker-update case
                # (e.g. a duplicate status callback), rather than relying on
                # that no longer happening in practice.
                position_id = stable_id("position", intent_id, symbol)
                first = position_id not in self.state.positions
                entry_slippage_abs = (fill_price - reference_price) if (fill_price is not None and reference_price is not None) else None
                entry_slippage_bps = (entry_slippage_abs / reference_price * 10000) if (entry_slippage_abs is not None and reference_price) else None
                self.state.positions[position_id] = {
                    "symbol": symbol, "quantity": filled_qty, "price": fill_price, "status": "OPEN",
                    "source": source, "alpha_evidence": alpha_evidence, "entry_time": now_iso,
                    "reference_price": reference_price, "stop_price": stop_price, "target_price": target_price,
                    "strategy_id": strategy_id, "horizon": horizon, "exit_quantity": 0.0,
                    "remaining_quantity": filled_qty, "experimental_id": experimental_id,
                    # Task 79E-R1: the ORIGINAL signal's bar_timestamp (never
                    # the fill's own wall-clock time) -- decision_engine.py's
                    # entry/exit causality guard and _rehydrate_positions both
                    # key off this so a restored position, exactly like a
                    # never-restarted one, can never have its stop/target
                    # evaluated against a bar at or before the one that
                    # produced the entry signal.
                    "entry_signal_bar_timestamp": entry_signal_bar_timestamp,
                }
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
        else:
            # Task 77I: the loop ran out of time without ever observing a
            # terminal status -- the true broker outcome is UNKNOWN, not
            # inert. Marked with a sentinel status deliberately outside
            # _TERMINAL_ORDER_STATUSES so oversell/pyramiding/pending-entry
            # guards keep treating this order as outstanding (fail closed)
            # until reconcile() resolves it against a fresh broker read --
            # never silently dropped, never blindly resubmitted (the
            # existing duplicate-intent-id guard also still applies to the
            # ORIGINAL signal_id regardless).
            if broker_order_id in self.state.orders:
                self.state.orders[broker_order_id]["status"] = "UNCONFIRMED_TIMEOUT"
                self._save()
            self.events.emit(PivEvent.build(
                "BROKER_ERROR", broker_order_id=broker_order_id,
                reason="ORDER_SUBMISSION_TIMEOUT_UNCONFIRMED", status="RECONCILE_REQUIRED",
            ))
        return last

    def _resolve_unconfirmed_orders(self) -> None:
        """Task 77I: called at the top of reconcile() -- any order left
        UNCONFIRMED_TIMEOUT by poll_order_until_terminal is re-queried
        against the broker (a fresh, authoritative read, never trusted from
        stale local state) and its real status applied via
        apply_broker_update, restart-safe since this scans persisted state
        every time reconcile() runs (EOD, probe pre-check, or a manual CLI
        invocation) rather than relying on any in-memory-only bookkeeping."""
        pending_ids = [
            broker_order_id for broker_order_id, order in self.state.orders.items()
            if order.get("status") == "UNCONFIRMED_TIMEOUT"
        ]
        for broker_order_id in pending_ids:
            try:
                current = self.broker.get_order(broker_order_id)
            except Exception as exc:  # noqa: BLE001 -- a broker-read failure here must not crash
                # reconcile(); the order stays UNCONFIRMED_TIMEOUT (still fail-closed/outstanding)
                # and will be retried on the next reconcile() call.
                self.events.emit(PivEvent.build(
                    "BROKER_ERROR", broker_order_id=broker_order_id,
                    reason=f"UNCONFIRMED_ORDER_RECONCILE_READ_FAILED_{type(exc).__name__}", status="STILL_UNRESOLVED",
                ))
                continue
            status = str(current.get("status") or "")
            if not status:
                continue
            filled_qty = float(current.get("filled_qty") or 0.0)
            fill_price = float(current["filled_avg_price"]) if current.get("filled_avg_price") else None
            self.apply_broker_update(broker_order_id, status, filled_qty, fill_price)

    def _order_response_matches_intent(self, found: dict[str, Any], payload: dict[str, Any], client_order_id: str) -> bool:
        """Task 79E-R2: "Reject unrelated/malformed responses" -- adopting a
        found order is a state-mutating trust decision (it creates a
        self.state.orders entry that oversell/pyramiding/exposure guards
        will treat as real), so it must never happen on a response that
        merely LOOKS like a match (has a truthy `id`) without actually
        matching the specific request this intent made. Every field the
        broker's own contract documents for an Order (client_order_id,
        symbol, side, qty) is cross-checked."""
        if str(found.get("client_order_id") or "") != client_order_id:
            return False
        if str(found.get("symbol") or "").upper() != str(payload.get("symbol") or "").upper():
            return False
        if str(found.get("side") or "").lower() != str(payload.get("side") or "").lower():
            return False
        try:
            found_qty = float(found.get("qty"))
            expected_qty = float(payload.get("qty"))
        except (TypeError, ValueError):
            return False
        return math.isfinite(found_qty) and abs(found_qty - expected_qty) <= 1e-6

    def _resolve_uncertain_submissions(self) -> None:
        """Task 79E-R1/R2: a SUBMIT_FAILED_UNCERTAIN intent (order_intent's
        own submit_order call raised BEFORE any broker order id was
        received -- see order_intent's try/except) has NO broker order id
        to poll with get_order, unlike UNCONFIRMED_TIMEOUT above. The only
        way to resolve the genuine ambiguity ("did this actually reach the
        broker or not?") is to look it up by its STABLE, locally-derived
        client_order_id (see broker.find_order_by_client_id) -- never by
        blindly resubmitting the same signal, which could double-enter if
        the original request in fact succeeded.

        Task 79E-R2 hardening over R1:
        - A response IS verified (client_order_id/symbol/side/qty) against
          the ORIGINAL intent before being adopted as evidence of anything
          -- an unrelated or malformed response is rejected outright and
          leaves the intent exactly as unresolved as before this call.
        - A single "not found" (404) is NOT treated as conclusive -- the
          reservation (pyramiding block, experimental exposure/budget) is
          retained until the SAME "not found" outcome has been observed
          across UNCERTAIN_SUBMISSION_CONFIRMATION_THRESHOLD separate
          reconcile() passes, each a fresh, independent broker read.

        Found-and-verified -> the order DID reach the broker despite the
        local exception; adopted into self.state.orders and its real
        status applied via apply_broker_update, exactly as if
        poll_order_until_terminal had originally observed it. Confirmed
        not-found (after the threshold) -> the intent is marked terminal
        so pyramiding/concurrent-exposure guards stop treating it as
        outstanding (the experimental budget reservation, if any, is
        deliberately NOT refunded even now -- conservative in case the
        broker's own repeated "not found" reads are themselves unreliable/
        eventually-consistent)."""
        uncertain_ids = [
            intent_id for intent_id, intent in self.state.intents.items()
            if intent.get("status") == "SUBMIT_FAILED_UNCERTAIN"
        ]
        for intent_id in uncertain_ids:
            intent = self.state.intents[intent_id]
            payload = intent.get("payload", {})
            client_order_id = payload.get("client_order_id") or intent_id
            try:
                found = self.broker.find_order_by_client_id(client_order_id)
            except Exception as exc:  # noqa: BLE001 -- a broker-read failure here must not crash
                # reconcile(); the intent stays SUBMIT_FAILED_UNCERTAIN (still fail-closed/outstanding)
                # and will be retried on the next reconcile() call. Never counted toward the
                # not-found-confirmation threshold below -- an error is not evidence of "not found."
                self.events.emit(PivEvent.build(
                    "BROKER_ERROR", order_intent_id=intent_id, correlation_id=intent_id,
                    reason=f"UNCERTAIN_SUBMISSION_RECONCILE_READ_FAILED_{type(exc).__name__}", status="STILL_UNRESOLVED",
                ))
                continue
            if found is None:
                attempts = int(intent.get("not_found_confirmations") or 0) + 1
                intent["not_found_confirmations"] = attempts
                self._save()
                if attempts < UNCERTAIN_SUBMISSION_CONFIRMATION_THRESHOLD:
                    self.events.emit(PivEvent.build(
                        "BROKER_ERROR", symbol=payload.get("symbol"), order_intent_id=intent_id,
                        correlation_id=intent_id, reason="UNCERTAIN_SUBMISSION_NOT_FOUND_AWAITING_CONFIRMATION",
                        status=f"STILL_UNRESOLVED_ATTEMPT_{attempts}_OF_{UNCERTAIN_SUBMISSION_CONFIRMATION_THRESHOLD}",
                    ))
                    continue
                intent["status"] = "SUBMIT_FAILED_CONFIRMED_NOT_SUBMITTED"
                self._save()
                self.events.emit(PivEvent.build(
                    "BROKER_ERROR", symbol=payload.get("symbol"), order_intent_id=intent_id,
                    correlation_id=intent_id, reason="UNCERTAIN_SUBMISSION_CONFIRMED_NEVER_REACHED_BROKER",
                    status="RESOLVED_NOT_SUBMITTED",
                ))
                continue
            if not self._order_response_matches_intent(found, payload, client_order_id):
                # Task 79E-R2: an unrelated/malformed response -- never
                # adopted, and never counted as a "not found" confirmation
                # either (it is not evidence the order was never submitted;
                # it is evidence the lookup itself returned something
                # untrustworthy). The intent stays exactly as unresolved as
                # it was before this call.
                self.events.emit(PivEvent.build(
                    "BROKER_ERROR", symbol=payload.get("symbol"), order_intent_id=intent_id,
                    correlation_id=intent_id, reason="UNCERTAIN_SUBMISSION_RESPONSE_MISMATCH_REJECTED",
                    status="STILL_UNRESOLVED",
                ))
                continue
            broker_id = str(found.get("id") or "")
            if not broker_id:
                continue
            intent["status"] = "SUBMITTED"
            intent.pop("not_found_confirmations", None)
            symbol = payload.get("symbol")
            self.state.orders[broker_id] = {
                "intent_id": intent_id, "symbol": symbol, "status": "SUBMITTED", "filled_qty": 0.0,
                "source": intent.get("source"), "alpha_evidence": intent.get("alpha_evidence"),
            }
            self._save()
            self.events.emit(PivEvent.build(
                "BROKER_ERROR", symbol=symbol, order_intent_id=intent_id, broker_order_id=broker_id,
                correlation_id=intent_id, reason="UNCERTAIN_SUBMISSION_CONFIRMED_REACHED_BROKER",
                status="RESOLVED_ADOPTED",
            ))
            status = str(found.get("status") or "")
            if status:
                filled_qty = float(found.get("filled_qty") or 0.0)
                fill_price = float(found["filled_avg_price"]) if found.get("filled_avg_price") else None
                self.apply_broker_update(broker_id, status, filled_qty, fill_price)

    def activate_kill_switch(self, cancel_orders: bool = False) -> None:
        self.state.kill_switch = True
        self.state.session_enabled = False
        self._save()
        if cancel_orders:
            self.broker.cancel_all_orders()
        self.events.emit(PivEvent.build("KILL_SWITCH", reason="OPERATOR_ACTIVATED", status="NEW_PAPER_ORDERS_BLOCKED"))

    def reconcile(self) -> dict[str, Any]:
        self._resolve_unconfirmed_orders()
        self._resolve_uncertain_submissions()
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
