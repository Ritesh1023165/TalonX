"""Task 99A S4.3 -- reply-for-details resolver for the restored alert families.

Registered on the existing single ``TelegramReplyListener`` via its additive
``extra_resolvers`` hook -- so there is still exactly ONE ``get_updates``
poller per bot token (no HTTP 409).

Prefixes (session-safe, deterministic, non-colliding with the numeric /
``LT`` ids the Original listener already owns):
    D…  directional setup   -> render_directional_details
    X…  experimental trade  -> render_experimental_trade
    R…  earnings radar      -> render_radar
    E…  event/fundamental   -> render_event_update

Returns ``None`` for anything that is not one of these prefixes, so the
Original numeric-id path still runs unchanged.
"""

from __future__ import annotations

import re
from typing import Callable

from talonx_signals.alert_store import ExperimentalAlertStore
from talonx_signals.renderers import (
    render_directional_details,
    render_event_update_details,
    render_experimental_trade,
    render_radar_details,
)

_PATTERN = re.compile(r"^\s*/?(?:details\s+)?#?([DXRE])([0-9a-fA-F]{6,32})\s*$", re.IGNORECASE)
_RETENTION_HINT = "either it never existed, or it has aged out of the retention window"


def make_reply_resolver(store: ExperimentalAlertStore) -> Callable[[str], str | None]:
    def resolve(text: str) -> str | None:
        m = _PATTERN.match(text or "")
        if not m:
            return None
        prefix = m.group(1).upper()
        public_id = prefix + m.group(2)

        if prefix == "D":
            row = store.get_directional(public_id)
            return render_directional_details(row) if row else _missing("directional alert", public_id)
        if prefix == "X":
            row = store.get_trade(public_id)
            return render_experimental_trade(row) if row else _missing("experimental trade", public_id)
        if prefix == "R":
            row = store.get_radar(public_id)
            return render_radar_details(row) if row else _missing("earnings radar item", public_id)
        if prefix == "E":
            row = store.get_event_update(public_id)
            return render_event_update_details(row) if row else _missing("event update", public_id)
        return None  # unreachable

    return resolve


def _missing(kind: str, public_id: str) -> str:
    return f"{kind.capitalize()} `{public_id}` not found -- {_RETENTION_HINT}."
