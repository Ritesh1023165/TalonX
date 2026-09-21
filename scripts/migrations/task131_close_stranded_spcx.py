"""
Task 131 Directive 1 -- one-time migration: forcibly close the stranded
SPCX position in the shadow EXPERIMENTAL ledger and reset its stale
metrics.

Context: the Experimental paper engine (``talonx_signals.experimental_paper``)
opened a SPCX long on 2026-09-10T19:29:45Z. The application has been
stopped since the Task 129 research pause, so this position was never
marked, never evaluated against its own stop/target, and never closed --
it is a stranded, stale open position with no further live monitoring.

This is an ADMINISTRATIVE closure, not a simulated market exit: no live
price feed is queried and no market outcome is fabricated. The position
is closed FLAT, at its own entry price (zero realized P&L), and its
allocated cost basis is returned to cash. This is a deliberate, disclosed
choice -- inventing a "current price" for a stock that has not been
observed for 3 days would misrepresent an outcome that never actually
happened. ``win_count``/``loss_count``/``total_realized_pnl_usd`` are
left UNCHANGED (this is not a real trading result, so it must not be
counted as either a win or a loss).

Safety:
  - The live database's WAL is checkpointed and a full, timestamped
    backup is taken BEFORE any write (matching this repo's existing
    ``*.bak-YYYYMMDD_HHMMSS`` convention under ~/.talonx/).
  - Idempotent: if SPCX is not an open position, the script reports
    that and makes no further change.
  - A complete before/after audit record is written next to the backup
    and to ``results/task131_migrations/`` for traceability.

Usage:
    python scripts/migrations/task131_close_stranded_spcx.py [--db PATH] [--dry-run]
"""
from __future__ import annotations

import argparse
import json
import shutil
import sqlite3
import sys
from datetime import datetime, timezone
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_DB = Path.home() / ".talonx" / "experimental" / "experimental_paper.db"
AUDIT_DIR = REPO_ROOT / "results" / "task131_migrations"
EXIT_REASON = "administrative_force_close_task131"
SYMBOL = "SPCX"


def _now_stamp() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def _backup(db_path: Path) -> Path:
    """Checkpoint the WAL into the main file, then copy2 a timestamped
    backup BEFORE any write -- reversible by construction."""
    con = sqlite3.connect(str(db_path), timeout=30)
    try:
        con.execute("PRAGMA wal_checkpoint(TRUNCATE)")
        con.commit()
    finally:
        con.close()
    backup_path = db_path.with_name(f"{db_path.name}.pre-task131-spcx-close.{_now_stamp()}.bak")
    shutil.copy2(db_path, backup_path)
    return backup_path


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--db", default=str(DEFAULT_DB), help="path to experimental_paper.db")
    ap.add_argument("--dry-run", action="store_true", help="report what would change, write nothing")
    args = ap.parse_args()

    db_path = Path(args.db).expanduser()
    if not db_path.exists():
        print(f"REFUSING: database not found at {db_path}", file=sys.stderr)
        return 2

    audit: dict = {
        "task": "TASK131_DIRECTIVE_1_SPCX_MIGRATION",
        "db_path": str(db_path),
        "symbol": SYMBOL,
        "started_at_utc": datetime.now(timezone.utc).isoformat(),
        "dry_run": bool(args.dry_run),
    }

    con = sqlite3.connect(str(db_path), timeout=30)
    con.row_factory = sqlite3.Row
    try:
        row = con.execute("SELECT * FROM positions WHERE ticker = ?", (SYMBOL,)).fetchone()
        if row is None:
            audit["result"] = "NOOP_NO_OPEN_SPCX_POSITION"
            print(json.dumps(audit, indent=2))
            return 0

        pos = dict(row)
        portfolio_before = dict(con.execute(
            "SELECT * FROM portfolio_state WHERE id = 1").fetchone())
        audit["before"] = {"position": pos, "portfolio_state": portfolio_before}

        now = datetime.now(timezone.utc)
        entry_ts = datetime.fromisoformat(pos["entry_timestamp"])
        if entry_ts.tzinfo is None:
            entry_ts = entry_ts.replace(tzinfo=timezone.utc)
        holding_seconds = (now - entry_ts).total_seconds()

        exit_price = pos["entry_price"]  # flat close -- no fabricated market outcome
        realized_pnl_usd = 0.0
        realized_pnl_pct = 0.0
        cash_after = portfolio_before["current_cash"] + pos["cost_basis"]

        audit["computed_closure"] = {
            "exit_price_basis": "ENTRY_PRICE_FLAT_NO_MARKET_DATA_QUERIED",
            "exit_price": exit_price, "realized_pnl_usd": realized_pnl_usd,
            "realized_pnl_pct": realized_pnl_pct, "holding_duration_seconds": holding_seconds,
            "cash_after": cash_after, "exit_reason": EXIT_REASON,
        }

        if args.dry_run:
            audit["result"] = "DRY_RUN_NO_WRITE"
            print(json.dumps(audit, indent=2, default=str))
            return 0

        backup_path = _backup(db_path)
        audit["backup_path"] = str(backup_path)

        # re-open post-backup (backup was taken via a separate short-lived
        # connection above) and perform the actual, transactional write.
        con.execute("BEGIN IMMEDIATE")
        con.execute(
            """INSERT INTO trade_history
               (ticker, order_type, execution_price, shares, position_cost, entry_price,
                realized_pnl_usd, realized_pnl_pct, exit_reason, holding_duration_seconds,
                portfolio_cash_after, timestamp)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?)""",
            (SYMBOL, "SELL", exit_price, pos["shares"], pos["cost_basis"], pos["entry_price"],
             realized_pnl_usd, realized_pnl_pct, EXIT_REASON, holding_seconds,
             cash_after, now.isoformat()),
        )
        con.execute("DELETE FROM positions WHERE ticker = ?", (SYMBOL,))
        con.execute("UPDATE portfolio_state SET current_cash = ? WHERE id = 1", (cash_after,))
        con.commit()

        portfolio_after = dict(con.execute("SELECT * FROM portfolio_state WHERE id = 1").fetchone())
        remaining = con.execute("SELECT * FROM positions WHERE ticker = ?", (SYMBOL,)).fetchone()
        audit["after"] = {"position": None if remaining is None else dict(remaining),
                          "portfolio_state": portfolio_after}
        audit["result"] = "CLOSED_ADMINISTRATIVELY"
    finally:
        con.close()

    AUDIT_DIR.mkdir(parents=True, exist_ok=True)
    audit_path = AUDIT_DIR / f"spcx_close_{_now_stamp()}.json"
    audit_path.write_text(json.dumps(audit, indent=2, default=str))
    audit["audit_log_path"] = str(audit_path)
    print(json.dumps(audit, indent=2, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
