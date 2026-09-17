"""
Day-2+ ledger continuity guard (Task 114 B2).

READ-ONLY.  Verifies ``v2_lane.db`` is a healthy authoritative prospective
campaign ledger that can be carried forward.  Fails CLOSED -- it never
creates, resets, truncates, archives or reseeds the ledger.  Genuine
corruption recovery is a separate manual administrative procedure
(``docs/`` / this module's ``ADMIN_RECOVERY_NOTE``).
"""
from __future__ import annotations

import sqlite3
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from talonx_ops.prospective import CAMPAIGN_STARTING_CASH

ADMIN_RECOVERY_NOTE = (
    "If ledger integrity genuinely fails: STOP.  Do NOT let the operator create a new "
    "ledger.  Manually inspect v2_lane.db, restore from the most recent "
    "results/prospective_*/v2_lane.db.eod-copy or results/task113_v2_full_day/v2_lane.db.eod-copy, "
    "reconcile by hand, and only then resume.  A fresh $300k ledger would destroy the "
    "prospective sample."
)

_REQUIRED_TABLES = {"portfolio", "positions", "trades", "processed_episodes", "cooldowns"}


@dataclass
class LedgerCheck:
    ok: bool
    db_path: str
    exists: bool = False
    cash: float | None = None
    n_open: int = 0
    n_closed: int = 0
    n_trades: int = 0
    n_buys: int = 0
    n_sells: int = 0
    n_unresolved: int = 0
    n_processed_episodes: int = 0
    stale_skipped_episodes: list[str] = field(default_factory=list)
    problems: list[str] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {k: getattr(self, k) for k in self.__dataclass_fields__}


def check_ledger_continuity(db_path: str | Path) -> LedgerCheck:
    p = Path(db_path)
    r = LedgerCheck(ok=False, db_path=str(p))
    if not p.exists():
        r.problems.append("v2_lane.db DOES NOT EXIST -- fail closed, do NOT create it")
        return r
    r.exists = True
    try:
        con = sqlite3.connect(f"file:{p}?mode=ro", uri=True)
        con.row_factory = sqlite3.Row
    except sqlite3.Error as exc:
        r.problems.append(f"cannot open ledger read-only: {exc}")
        return r
    try:
        tables = {row[0] for row in con.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        missing = _REQUIRED_TABLES - tables
        if missing:
            r.problems.append(f"missing tables: {sorted(missing)}")
            return r

        row = con.execute("SELECT cash FROM portfolio WHERE id=1").fetchone()
        r.cash = None if row is None else float(row[0])
        r.n_open = con.execute("SELECT COUNT(*) FROM positions WHERE status='OPEN'").fetchone()[0]
        r.n_closed = con.execute("SELECT COUNT(*) FROM positions WHERE status='CLOSED'").fetchone()[0]
        r.n_unresolved = con.execute(
            "SELECT COUNT(*) FROM positions WHERE status='EXIT_UNRESOLVED'").fetchone()[0]
        r.n_trades = con.execute("SELECT COUNT(*) FROM trades").fetchone()[0]
        r.n_buys = con.execute("SELECT COUNT(*) FROM trades WHERE action='BUY'").fetchone()[0]
        r.n_sells = con.execute("SELECT COUNT(*) FROM trades WHERE action='SELL'").fetchone()[0]
        r.n_processed_episodes = con.execute("SELECT COUNT(*) FROM processed_episodes").fetchone()[0]
        r.stale_skipped_episodes = [
            row[0] for row in con.execute(
                "SELECT episode_id FROM processed_episodes WHERE disposition='SKIPPED_ENTRY_STALE'")]

        # ---- invariants (fail closed) ----
        if r.cash is None:
            r.problems.append("portfolio.cash row missing")
        elif r.cash < 0:
            r.problems.append(f"NEGATIVE CASH: {r.cash}")
        if r.n_buys != r.n_sells + r.n_open + r.n_unresolved:
            r.problems.append(
                f"ledger equation broken: buys({r.n_buys}) != sells({r.n_sells}) + "
                f"open({r.n_open}) + unresolved({r.n_unresolved})")
        dup = con.execute(
            "SELECT episode_id, COUNT(*) c FROM trades WHERE action='BUY' "
            "GROUP BY episode_id HAVING c > 1").fetchall()
        if dup:
            r.problems.append(f"duplicate BUY episode_id(s): {[d[0] for d in dup]}")
        dup_pos = con.execute(
            "SELECT episode_id, COUNT(*) c FROM positions GROUP BY episode_id HAVING c > 1").fetchall()
        if dup_pos:
            r.problems.append(f"duplicate position episode_id(s): {[d[0] for d in dup_pos]}")

        # an OPEN position must have entry price + target exit
        bad_open = con.execute(
            "SELECT episode_id FROM positions WHERE status='OPEN' AND "
            "(entry_price IS NULL OR target_exit_session IS NULL OR shares IS NULL)").fetchall()
        if bad_open:
            r.problems.append(f"OPEN position(s) with no entry price / target / size: {[b[0] for b in bad_open]}")

        # sanity: cash cannot exceed starting + realized gains beyond reason
        realized = con.execute(
            "SELECT COALESCE(SUM(realized_pnl_usd),0) FROM positions WHERE status='CLOSED'").fetchone()[0] or 0.0
        expected_cash_if_flat = CAMPAIGN_STARTING_CASH + realized
        open_cost = con.execute(
            "SELECT COALESCE(SUM(position_cost),0) FROM positions WHERE status='OPEN'").fetchone()[0] or 0.0
        # Package 1 Settlement Integrity (bounded correction, found during
        # Package 2's own prerequisite verification): an EXIT_UNRESOLVED
        # position's cash debit at entry is never returned -- its cost
        # basis must be included here too, or this restart-continuity
        # guard fabricates a "cash accounting mismatch" finding purely
        # because that cost was omitted, exactly the same defect already
        # fixed in talonx_ops/prospective/close.py::_v2_reconcile().
        unresolved_cost = con.execute(
            "SELECT COALESCE(SUM(position_cost),0) FROM positions "
            "WHERE status='EXIT_UNRESOLVED'").fetchone()[0] or 0.0
        if r.cash is not None and abs((r.cash + open_cost + unresolved_cost) - expected_cash_if_flat) > 1.0:
            r.problems.append(
                f"cash accounting mismatch: cash({r.cash:.2f}) + open_cost({open_cost:.2f}) + "
                f"unresolved_cost({unresolved_cost:.2f}) != start({CAMPAIGN_STARTING_CASH:.2f}) "
                f"+ realized({realized:.2f})")

        if not r.stale_skipped_episodes:
            r.notes.append("no SKIPPED_ENTRY_STALE record yet (fine on a truly fresh carry-forward; "
                           "the ABCL episode 07242bc857569f60 is re-recorded on the first live tick)")
        r.notes.append(f"carry-forward: cash={r.cash} open={r.n_open} closed={r.n_closed} "
                       f"trades={r.n_trades} processed_episodes={r.n_processed_episodes}")
    finally:
        con.close()

    r.ok = not r.problems
    return r
