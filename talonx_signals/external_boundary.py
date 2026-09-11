"""Task 100B Phase 6 -- STRUCTURAL Experimental external-send boundary.

P0 invariant: Experimental V1 (BULLISH/BEARISH, WOULD_PASS/WOULD_REJECT,
Experimental BUY/EXIT, gate diagnostics, forward telemetry) is **internal
only**. It must NOT become externally dispatchable merely because Task 100B
consolidated runtime ownership, nor because someone flips a single boolean.

This module is the one structural choke point. ``ExperimentalDispatcher``
calls :func:`assert_experimental_send_allowed` immediately before *any* real
network send. Reaching an external send therefore requires **three**
independent conditions, not one:

  1. ``ExperimentalDispatcher.enable_external_send=True``  (the existing flag)
  2. the sender reports ``configured``                    (real transport present)
  3. ``TALONX_EXPERIMENTAL_EXTERNAL_SEND_OVERRIDE`` == ``"i-understand"``
     in the environment                                   (this module)

Absent (3), a send attempt raises :class:`ExperimentalExternalBoundaryError`
and nothing leaves the process -- so "we didn't pass --enable-external-send"
is *not* the only thing standing between Experimental and Telegram.

The Original / approved-Task-96 families are unaffected: they never route
through this module. :func:`is_external_eligible` states the routing rule
explicitly for any code that needs to ask.
"""
from __future__ import annotations

import os

#: Frozen posture. Experimental external sends are structurally disallowed.
EXPERIMENTAL_EXTERNAL_SENDS_ALLOWED = False

#: The loud, explicit, deliberately awkward override. Mirrors the intelligence
#: service's ``--i-understand-external-send`` double-gate.
_OVERRIDE_ENV = "TALONX_EXPERIMENTAL_EXTERNAL_SEND_OVERRIDE"
_OVERRIDE_VALUE = "i-understand"

#: Experimental alert families -- never externally eligible.
EXPERIMENTAL_FAMILIES = frozenset(
    {"directional", "directional_alerts", "experimental_trade", "experimental_trades",
     "trade", "gate_diagnostic", "forward_outcome", "would_pass", "would_reject"}
)

#: Families that MAY join the one official external dispatch path (Original's
#: own policy decides per-alert; the approved Task 96 intelligence/RADAR
#: families are allowed here only where a locked contract already authorises).
#: Task 110: ``insider_buy_cluster_v2`` is the ACTIVE_PAPER_V2 lane
#: (INSIDER_BUY_CLUSTER_V2@1), an OFFICIAL Original-flow strategy profile,
#: NOT an Experimental family -- it routes through the one official path.
EXTERNAL_ELIGIBLE_FAMILIES = frozenset(
    {"original", "official", "actionable_alert", "long_term_alert",
     "intelligence_card", "radar", "radar_alerts", "event_update", "event_updates",
     "insider_buy_cluster_v2"}
)


class ExperimentalExternalBoundaryError(RuntimeError):
    """Raised when Experimental code attempts a real external send without the
    explicit environment override. This is a safety stop, not a normal error."""


def experimental_external_override_active() -> bool:
    return os.environ.get(_OVERRIDE_ENV, "").strip().lower() == _OVERRIDE_VALUE


def assert_experimental_send_allowed(context: str = "") -> None:
    """Raise unless the explicit override is present. Call this immediately
    before any real network send from Experimental code."""
    if EXPERIMENTAL_EXTERNAL_SENDS_ALLOWED:  # pragma: no cover - constant is False
        return
    if experimental_external_override_active():
        return
    where = f" ({context})" if context else ""
    raise ExperimentalExternalBoundaryError(
        "Experimental external Telegram send is structurally disabled"
        f"{where}. Experimental V1 is internal-only (Task 99I/99L/100B Phase 6). "
        f"Set {_OVERRIDE_ENV}={_OVERRIDE_VALUE} only with explicit authorisation."
    )


def is_external_eligible(family: str) -> bool:
    """The explicit routing rule. Experimental families are always False.

    Anything not positively listed as eligible is treated as NOT eligible
    (fail-closed)."""
    f = (family or "").strip().lower()
    if f in EXPERIMENTAL_FAMILIES:
        return False
    return f in EXTERNAL_ELIGIBLE_FAMILIES
