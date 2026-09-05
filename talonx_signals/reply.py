"""Task 99A S4.3 -- reply-for-details resolver for the restored alert families.

Registered on the existing single ``TelegramReplyListener`` via its additive
``extra_resolvers`` hook -- so there is still exactly ONE ``get_updates``
poller per bot token (no HTTP 409).

Prefixes (session-safe, deterministic, non-colliding with the numeric /
``LT`` ids the Original listener already owns):
    D…  directional setup   -> render_directional_details
    X…  experimental trade  -> render_experimental_trade
    R…  earnings radar      -> render_radar_details
    E…  event/fundamental   -> render_event_update_details

Returns ``None`` for anything that is not one of these prefixes, so the
Original numeric-id path still runs unchanged.
"""

from __future__ import annotations

import re
import sqlite3
from pathlib import Path
from typing import Callable

from talonx_signals.alert_store import ExperimentalAlertStore, ReadOnlyExperimentalAlertStore
from talonx_signals.renderers import (
    render_directional_details,
    render_event_update_details,
    render_experimental_trade,
    render_radar_details,
)

_PATTERN = re.compile(r"^\s*/?(?:details\s+)?#?([DXRE])([0-9a-fA-F]{6,32})\s*$", re.IGNORECASE)
_RETENTION_HINT = "either it never existed, or it has aged out of the retention window"


def make_reply_resolver(
    store: ExperimentalAlertStore | ReadOnlyExperimentalAlertStore,
) -> Callable[[str], str | None]:
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


_LOCK_FALLBACK = (
    "Experimental alert detail is temporarily unavailable -- please try again in a moment."
)


def build_experimental_dxre_resolver(
    db_path: str | Path | None = None,
    on_error: Callable[[BaseException], None] | None = None,
) -> tuple[ReadOnlyExperimentalAlertStore | None, Callable[[str], str | None] | None]:
    """Task 100B Phase 5 -- build the single D/X/R/E ``extra_resolver`` that
    ``run_talonx.py``'s ONE ``TelegramReplyListener`` registers (Task 99L Option A).

    ``db_path`` defaults to ``ExperimentalConfig().state_dir / "exp_alerts.db"``.
    The store is opened **read-only** (``file:...?mode=ro``) so no write path can
    ever exist from reply resolution; a concurrent WAL writer (the Experimental
    lane) is unaffected. Returns ``(store_handle, resolver)`` -- keep the handle
    to ``.close()`` it in the shutdown ``finally`` block. On any construction
    failure returns ``(None, None)`` and the caller simply does not register a
    D/X/R/E resolver (Original's numeric/LT path is untouched).

    The returned resolver wraps :func:`make_reply_resolver` so that a transient
    ``sqlite3.OperationalError`` (``database is locked``) yields a graceful
    "temporarily unavailable" string instead of propagating, and any other
    unexpected error is routed to ``on_error`` and swallowed (returns ``None`` so
    the listener falls through to Original's numeric path unchanged).
    """
    try:
        if db_path is None:
            from talonx_signals.config import ExperimentalConfig

            db_path = ExperimentalConfig().state_dir / "exp_alerts.db"
        store = ReadOnlyExperimentalAlertStore(db_path)
        raw = make_reply_resolver(store)
    except Exception as exc:  # noqa: BLE001 -- never block run_talonx.py startup
        if on_error is not None:
            on_error(exc)
        return None, None

    def resolver(text: str) -> str | None:
        try:
            return raw(text)
        except sqlite3.OperationalError:
            return _LOCK_FALLBACK
        except Exception as exc:  # noqa: BLE001 -- a resolver bug must never kill the poller
            if on_error is not None:
                on_error(exc)
            return None

    return store, resolver
