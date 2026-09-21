"""
talonx_ops.account_blocks -- Package 2: durable, auditable account-wide
admission blocks (closes OPS-012 / OPS-015's own described gap: genuine
detection existed with NO enforcement connected to it).

Storage-layer-agnostic: operates on a raw ``sqlite3.Connection`` (or the
active connection inside a caller's own transaction) against two small,
additive tables. Any store that already manages its own connection/
transaction lifecycle (``talonx_v2.store.V2Store``, ``talonx_paper.
store``) embeds ``SCHEMA`` into its own schema string and calls the
functions here with its own live connection -- this module never opens
a connection of its own for a write, so every block/clearance write is
naturally inside whatever transaction the caller already holds.

Design contract (Package 2's own explicit requirements):
  * Persist MULTIPLE INDEPENDENT block reasons per account -- clearing
    one reason must never clear another, and must never touch a
    separate user pause (which is NOT modelled here at all; Package 2
    is scoped to serious INTEGRITY blocks only, not the pre-existing
    Pause New Entries control).
  * Stable block identity: ``block_id`` is a deterministic function of
    (account_id, reason_type, reference) -- repeated detection of the
    SAME underlying issue is idempotent (no duplicate active block; no
    perturbation of an already-ACTIVE block's own detected_at_utc).
  * Restart-durable: both tables are ordinary rows in the account's own
    persistent ledger file, not in-memory state.
  * Clearance is a distinct, audited event, never a silent status flip:
    every clearance ATTEMPT (approved or refused) is appended to
    ``block_clearances`` -- prior incident history is never overwritten.
  * This module never fabricates a resolution. It does not decide
    WHETHER a given block is currently clearable -- that is reason-
    type-specific domain logic the caller supplies (see ``clear_block``'s
    own docstring) -- it only provides the durable, atomic bookkeeping
    around that decision.
"""
from __future__ import annotations

import hashlib
import sqlite3
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

# ---- reason types (Package 2 §2's own four, no others invented) ---------
REASON_EXIT_UNRESOLVED = "EXIT_UNRESOLVED"
REASON_LEDGER_MISMATCH = "LEDGER_MISMATCH"
REASON_CASH_DEFICIT = "CASH_DEFICIT"
REASON_IDENTITY_MISMATCH = "IDENTITY_MISMATCH"

VALID_REASON_TYPES = frozenset({
    REASON_EXIT_UNRESOLVED, REASON_LEDGER_MISMATCH, REASON_CASH_DEFICIT, REASON_IDENTITY_MISMATCH,
})

STATUS_ACTIVE = "ACTIVE"
STATUS_CLEARED = "CLEARED"

OUTCOME_CLEARED = "CLEARED"
OUTCOME_REFUSED = "REFUSED"

# Additive, IF NOT EXISTS -- embedded into each account store's own
# schema string by that store (V2Store, talonx_paper.store), never
# created by this module opening its own connection.
SCHEMA = """
CREATE TABLE IF NOT EXISTS account_blocks (
    block_id        TEXT PRIMARY KEY,
    account_id      TEXT NOT NULL,
    reason_type     TEXT NOT NULL,
    reference       TEXT NOT NULL,
    detail          TEXT,
    status          TEXT NOT NULL,
    detected_at_utc TEXT NOT NULL,
    updated_at_utc  TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_account_blocks_account_status
    ON account_blocks(account_id, status);
CREATE TABLE IF NOT EXISTS block_clearances (
    clearance_id    TEXT PRIMARY KEY,
    block_id        TEXT NOT NULL,
    operator_id     TEXT NOT NULL,
    reason          TEXT NOT NULL,
    evidence_ref    TEXT NOT NULL,
    outcome         TEXT NOT NULL,
    detail          TEXT,
    attempted_at_utc TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_block_clearances_block_id
    ON block_clearances(block_id);
"""


def _utcnow() -> str:
    return datetime.now(timezone.utc).isoformat()


def block_id(account_id: str, reason_type: str, reference: str) -> str:
    """Deterministic, stable identity for (account, reason, reference) --
    the SAME underlying issue always maps to the SAME block_id, which is
    what makes repeated detection idempotent (an upsert, never a second
    row)."""
    raw = f"{account_id}|{reason_type}|{reference}".encode()
    return hashlib.sha256(raw).hexdigest()[:24]


@dataclass(frozen=True)
class Block:
    block_id: str
    account_id: str
    reason_type: str
    reference: str
    detail: str | None
    status: str
    detected_at_utc: str
    updated_at_utc: str

    # Positional, not name-keyed: some callers' connections (e.g.
    # talonx_paper.store's) never set row_factory=sqlite3.Row, so this
    # module must not assume dict/name-style row access -- only that
    # ``SELECT *`` returns columns in the table's own definition order,
    # which is true for a plain tuple row exactly as much as a Row.
    _COLUMNS = ("block_id", "account_id", "reason_type", "reference",
               "detail", "status", "detected_at_utc", "updated_at_utc")

    @classmethod
    def from_row(cls, row) -> "Block":
        return cls(**dict(zip(cls._COLUMNS, row)))


def record_block(conn: sqlite3.Connection, *, account_id: str, reason_type: str,
                 reference: str, detail: str = "") -> str:
    """Idempotently records (or re-activates) a block. Must be called on
    a connection that is part of the caller's own protected transaction
    (the caller commits; this function never commits/rolls back itself).

    Idempotency: if a block with this exact (account_id, reason_type,
    reference) already exists and is ACTIVE, this is a genuine no-op --
    ``detected_at_utc`` is NOT perturbed, only ``updated_at_utc``/
    ``detail`` refresh. If it exists and was CLEARED (the underlying
    issue recurred after a prior clearance), it is re-activated as a
    NEW active incident -- the full clearance history for the prior
    occurrence remains in ``block_clearances``, untouched.
    """
    if reason_type not in VALID_REASON_TYPES:
        raise ValueError(f"unknown reason_type: {reason_type!r}")
    bid = block_id(account_id, reason_type, reference)
    now = _utcnow()
    conn.execute(
        """INSERT INTO account_blocks
             (block_id, account_id, reason_type, reference, detail, status,
              detected_at_utc, updated_at_utc)
           VALUES (?,?,?,?,?,?,?,?)
           ON CONFLICT(block_id) DO UPDATE SET
             detail=excluded.detail, updated_at_utc=excluded.updated_at_utc,
             status='ACTIVE',
             detected_at_utc=CASE WHEN account_blocks.status='ACTIVE'
                                   THEN account_blocks.detected_at_utc
                                   ELSE excluded.detected_at_utc END""",
        (bid, account_id, reason_type, reference, detail[:2000], STATUS_ACTIVE, now, now),
    )
    return bid


def active_blocks(conn: sqlite3.Connection, account_id: str) -> list[Block]:
    rows = conn.execute(
        "SELECT * FROM account_blocks WHERE account_id=? AND status=? "
        "ORDER BY detected_at_utc", (account_id, STATUS_ACTIVE)).fetchall()
    return [Block.from_row(r) for r in rows]


def blocked_reason(conn: sqlite3.Connection, account_id: str) -> str | None:
    """The single authoritative admission-gate check: returns a compact,
    human-readable summary of every ACTIVE block for this account, or
    None if the account currently has none. Callers gate admission on
    this return value being None -- this MUST be called from inside the
    same protected transaction as the admission mutation it gates (see
    talonx_v2.paper.enter_position / talonx_paper.store.execute_buy)."""
    blocks = active_blocks(conn, account_id)
    if not blocks:
        return None
    return "; ".join(f"{b.reason_type}:{b.reference}" for b in blocks)


def get_block(conn: sqlite3.Connection, block_id_: str) -> Block | None:
    row = conn.execute("SELECT * FROM account_blocks WHERE block_id=?", (block_id_,)).fetchone()
    return Block.from_row(row) if row else None


_CLEARANCE_COLUMNS = ("clearance_id", "block_id", "operator_id", "reason", "evidence_ref",
                     "outcome", "detail", "attempted_at_utc")


def clearance_history(conn: sqlite3.Connection, block_id_: str) -> list[dict[str, Any]]:
    rows = conn.execute(
        "SELECT * FROM block_clearances WHERE block_id=? ORDER BY attempted_at_utc",
        (block_id_,)).fetchall()
    # positional, not dict(row) -- see Block._COLUMNS' own comment: not
    # every caller's connection sets row_factory=sqlite3.Row.
    return [dict(zip(_CLEARANCE_COLUMNS, r)) for r in rows]


def attempt_clearance(conn: sqlite3.Connection, *, block_id_: str, operator_id: str,
                      reason: str, evidence_ref: str, allow: bool, detail: str = "") -> dict[str, Any]:
    """Records ONE clearance attempt, atomically, inside the caller's own
    transaction. This function does NOT decide whether the underlying
    integrity condition is actually resolved -- that decision (``allow``)
    is the caller's, made by re-checking reason-type-specific evidence
    BEFORE calling this (see each integration site's own re-verification
    logic). Always appends to ``block_clearances`` (approved or refused
    alike -- prior incident history, including refusals, is preserved).
    Only flips the block's own status to CLEARED when ``allow`` is True.
    Clearing this block never touches any OTHER block for the same or a
    different account -- callers only ever pass one block_id_ per call.

    Raises ValueError if ``operator_id``, ``reason``, or ``evidence_ref``
    is empty -- clearance always requires an identified operator, a
    stated reason, and a reference to the supporting evidence, never a
    bare boolean."""
    if not operator_id or not reason or not evidence_ref:
        raise ValueError(
            "clearance requires a non-empty operator_id, reason, and evidence_ref")
    blk = get_block(conn, block_id_)
    if blk is None:
        raise ValueError(f"no such block: {block_id_!r}")
    now = _utcnow()
    cid = hashlib.sha256(f"{block_id_}|{operator_id}|{now}".encode()).hexdigest()[:24]
    outcome = OUTCOME_CLEARED if allow else OUTCOME_REFUSED
    conn.execute(
        """INSERT INTO block_clearances
             (clearance_id, block_id, operator_id, reason, evidence_ref, outcome, detail, attempted_at_utc)
           VALUES (?,?,?,?,?,?,?,?)""",
        (cid, block_id_, operator_id, reason[:500], evidence_ref[:500], outcome, detail[:2000], now),
    )
    if allow:
        conn.execute(
            "UPDATE account_blocks SET status=?, updated_at_utc=? WHERE block_id=?",
            (STATUS_CLEARED, now, block_id_),
        )
    return {"clearance_id": cid, "block_id": block_id_, "outcome": outcome, "attempted_at_utc": now}
