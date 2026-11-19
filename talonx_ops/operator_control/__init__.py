"""
TalonX Sentinel operator control plane (2026-09-25).

Owner-only Telegram commands on the TalonX **Sentinel** (OPERATIONS) bot: ``/help``, ``/universe``, ``/exclude`` and
``/scanned``. Durable operator intent lives in ``operator_control.db`` (repo root, or ``TALONX_OPERATOR_DB``).

Mutation mode ``OPERATOR_UNIVERSE_MUTATION_MODE``:
* ``DRY_RUN`` (default): commands validate and persist operator INTENT as PENDING_ACTIVATION; every provider /
  discovery / promotion gate is an exact identity -- live fetch batches, discovery input, the candidate population,
  Lab and Signal are untouched.
* ``ACTIVE`` (post-EOD, explicit authorisation only): the effective fetch universe is
  ``BASE + operator-added - removed - excluded``; excluded symbols are dropped BEFORE the yfinance and Alpaca batches
  are built (never fetched to be discarded), skipped by discovery (no scoring / SEC work / candidates / lifecycle),
  refused by promotion (queued unsent promotions expire OPERATOR_EXCLUDED; already-sent outcomes keep tracking).
  Restoring or re-adding never replays history.
"""
from __future__ import annotations

import os

MODE_ENV = "OPERATOR_UNIVERSE_MUTATION_MODE"
DRY_RUN, ACTIVE = "DRY_RUN", "ACTIVE"


def mutation_mode(env=None) -> str:
    m = str((env if env is not None else os.environ).get(MODE_ENV, DRY_RUN)).strip().upper() or DRY_RUN
    return ACTIVE if m == ACTIVE else DRY_RUN          # anything unrecognised fails safe to DRY_RUN
