"""
talonx_ops.prospective.campaign_cash -- RI-1 (RI1-C): the ONE
authoritative starting-cash resolver, shared by ``close.py`` and
``ledger_guard.py`` (extracted to its own module to avoid the circular
import a direct close<->ledger_guard dependency would create -- close
already imports checkpoint, which imports ledger_guard).
"""
from __future__ import annotations

import sqlite3

from talonx_ops.prospective import CAMPAIGN_STARTING_CASH


def authoritative_starting_cash(con: sqlite3.Connection) -> float:
    """Resolves the pre-RI-1 ambiguity between this module's own
    hardcoded ``CAMPAIGN_STARTING_CASH`` (300_000.0, the EXISTING
    production campaign's own known, documented value -- see that
    constant's own comment in ``talonx_ops/prospective/__init__.py``)
    and ``V2Config.starting_cash_usd`` (the NEW-campaign default,
    100_000.0, used only to seed a genuinely fresh ledger -- see
    ``V2Store._init``).

    Prefers the campaign's own DURABLY PERSISTED, seeded-once
    ``campaign.starting_cash_usd`` (RI1-B) -- the actual amount THIS
    specific campaign was capitalized with, authoritative regardless of
    what any module-level default currently says. Falls back to the
    pre-RI-1 ``CAMPAIGN_STARTING_CASH`` constant ONLY when that column is
    unavailable (a `campaign` table that predates RI-1) or NULL (a
    legacy campaign not yet explicitly backfilled, RI1-K) -- preserving
    the EXISTING production campaign's reconciliation byte-for-byte
    unless/until it is explicitly migrated. Never guesses a number that
    isn't already durably recorded somewhere."""
    try:
        row = con.execute("SELECT starting_cash_usd FROM campaign WHERE id=1").fetchone()
    except sqlite3.OperationalError:
        row = None  # pre-RI-1 ledger file, no `campaign` table yet
    if row is not None and row["starting_cash_usd"] is not None:
        return float(row["starting_cash_usd"])
    return CAMPAIGN_STARTING_CASH
