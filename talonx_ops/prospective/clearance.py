"""
talonx_ops.prospective.clearance -- Package 2: reason-type-specific
clearance re-verification, plus the minimal explicit operator clearance
interface (Part 5).

``account_blocks.attempt_clearance()`` deliberately does not decide
*whether* a given block is currently clearable -- see its own
docstring. That domain-specific decision lives here, one branch per
``reason_type``, and every branch re-checks FRESH evidence at
clearance time (never the evidence that was true when the block was
first recorded).

Trust boundary (Part 5's own explicit requirement -- "an arbitrary
operator-name string alone is not an authentication mechanism"):
this module does NOT authenticate the operator. ``operator_id`` is a
self-reported identity recorded into the permanent, append-only
``block_clearances`` audit trail -- exactly the same convention this
project already uses for every other local administrative action
(``python -m talonx_ops.prospective start/close``, the loopback-only
``/admin/config`` endpoint on :8787 -- Task 102). The actual access
control is OS/filesystem access to run this script on the machine
that holds the production ledger file: whoever can run
``python -m talonx_ops.prospective clear-block`` here already has
strictly greater access than this action grants (they could edit the
sqlite file directly). No new authentication platform is introduced;
none is needed for a locally-invoked administrative tool matching the
project's existing trust model. This IS a real limitation for a
future genuinely-remote or multi-operator deployment -- it is
disclosed, not fixed, per Package 2's own scope.
"""
from __future__ import annotations

import sqlite3
from pathlib import Path
from typing import Any


def _read_block(db_path: str | Path, block_id: str):
    from talonx_ops import account_blocks
    con = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
    con.row_factory = sqlite3.Row
    try:
        return account_blocks.get_block(con, block_id)
    finally:
        con.close()


def _verify_exit_unresolved(db_path: str | Path, blk) -> tuple[bool, str]:
    """No supported accounting-correction workflow exists (yet) for an
    EXIT_UNRESOLVED position -- Package 2 does not invent an exit
    price, force settlement, or erase the position to clear this
    block. Allow ONLY if the referenced position is no longer
    EXIT_UNRESOLVED in the ledger (i.e. some legitimate, independent
    mechanism resolved it first)."""
    con = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
    try:
        row = con.execute(
            "SELECT status FROM positions WHERE position_id=?", (blk.reference,)
        ).fetchone()
    finally:
        con.close()
    if row is None:
        return False, f"position {blk.reference} not found -- cannot verify resolution"
    status = row[0]
    if status == "EXIT_UNRESOLVED":
        return False, (
            "position is still EXIT_UNRESOLVED -- no supported accounting-correction "
            "workflow exists to resolve it; Package 2 refuses clearance rather than "
            "invent an exit price or force settlement (explicit limitation)"
        )
    return True, f"position {blk.reference} status is now {status!r} (no longer EXIT_UNRESOLVED)"


def _verify_v2_reconcile_assert(assert_key: str, blk) -> tuple[bool, str]:
    """Re-runs the SAME bounded reconciliation `_v2_reconcile()` performs
    (fresh, at clearance time) and checks only the specific assert this
    block was raised for -- never the evidence attached to the block at
    detection time."""
    from talonx_ops.prospective.close import _v2_reconcile
    _, asserts, _ = _v2_reconcile()
    val = asserts.get(assert_key)
    if val == "PASS":
        return True, f"fresh re-check of {assert_key} now PASSES"
    return False, f"fresh re-check of {assert_key} is still {val!r} -- underlying integrity condition unresolved"


_V2_ASSERT_BY_REASON = {
    "LEDGER_MISMATCH": "cash_plus_open_cost_reconciles",
    "CASH_DEFICIT": "no_negative_cash",
}


def _verify_original_intraday_reconcile(db_path: str | Path, blk) -> tuple[bool, str]:
    """Re-runs eod_reconciliation.build_reconciliation() fresh (at
    clearance time) and checks whether an ``original_paper:`` mismatch
    is still present -- the same source
    ``_record_original_intraday_reconciliation_blocks`` reads from."""
    from talonx_ops.eod_reconciliation import build_reconciliation
    home = Path(db_path).parent
    rec = build_reconciliation(home=home)
    still_mismatched = [m for m in rec.mismatches if m.startswith("original_paper:")]
    if still_mismatched:
        return False, f"fresh re-check still finds: {still_mismatched}"
    return True, "fresh re-check of original_paper reconciliation now finds no mismatch"


def verify_clearance_eligible(db_path: str | Path, account_kind: str, blk) -> tuple[bool, str]:
    """Returns (allow, detail). Pure decision logic -- no persistence.
    ``account_kind`` in {"V2", "ORIGINAL_INTRADAY", "ORIGINAL_LONGTERM"}."""
    from talonx_ops import account_blocks
    if blk.status != account_blocks.STATUS_ACTIVE:
        return False, f"block is not ACTIVE (status={blk.status!r}) -- nothing to clear"
    if blk.reason_type == account_blocks.REASON_EXIT_UNRESOLVED:
        return _verify_exit_unresolved(db_path, blk)
    if blk.reason_type in _V2_ASSERT_BY_REASON and account_kind == "V2":
        return _verify_v2_reconcile_assert(_V2_ASSERT_BY_REASON[blk.reason_type], blk)
    if (blk.reason_type == account_blocks.REASON_LEDGER_MISMATCH and account_kind == "ORIGINAL_INTRADAY"
            and blk.reference == "original_paper_open_with_no_trades"):
        return _verify_original_intraday_reconcile(db_path, blk)
    # CASH_DEFICIT on an Original account, or IDENTITY_MISMATCH
    # anywhere: no automated detector or re-verification workflow
    # exists in this package for these combinations (Package 2
    # deliberately did not invent one -- see module docstring / final
    # report). Leave uncleared rather than
    # bypass.
    return False, (
        f"no automated re-verification workflow exists for reason_type="
        f"{blk.reason_type!r} on account_kind={account_kind!r}; Package 2 leaves "
        f"this block uncleared by design rather than create an unsafe bypass"
    )


def clear_block(db_path: str | Path, account_kind: str, *, block_id: str,
                operator_id: str, reason: str, evidence_ref: str) -> dict[str, Any]:
    """The one entry point the CLI (and any future interface) calls.
    Re-verifies fresh evidence, then persists exactly one clearance
    attempt -- approved or refused -- atomically, via the owning
    store's own ``attempt_block_clearance``, which re-evaluates
    nothing else: clearing this block never touches any other block or
    a user pause (account_blocks' own contract)."""
    blk = _read_block(db_path, block_id)
    if blk is None:
        raise ValueError(f"no such block: {block_id!r}")
    if blk.account_id != {
        "V2": "V2", "ORIGINAL_INTRADAY": "ORIGINAL_INTRADAY", "ORIGINAL_LONGTERM": "ORIGINAL_LONGTERM",
    }.get(account_kind):
        raise ValueError(
            f"block {block_id!r} belongs to account_id={blk.account_id!r}, "
            f"not account_kind={account_kind!r}")

    allow, detail = verify_clearance_eligible(db_path, account_kind, blk)

    if account_kind == "V2":
        from talonx_v2.store import V2Store
        store = V2Store(str(db_path))
    else:
        from talonx_paper.store import PaperTradingStore
        store = PaperTradingStore(str(db_path))

    result = store.attempt_block_clearance(
        block_id=block_id, operator_id=operator_id, reason=reason,
        evidence_ref=evidence_ref, allow=allow, detail=detail,
    )
    result["allow"] = allow
    result["verification_detail"] = detail
    result["block"] = {"reason_type": blk.reason_type, "reference": blk.reference,
                       "account_id": blk.account_id}
    return result
