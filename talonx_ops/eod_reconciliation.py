"""talonx_ops.eod_reconciliation -- Task 100B Phase 13.

Task 100A found no authoritative end-of-day reconciliation store: it was ad-hoc
per forensic script (Task 92 / 99F / 99I). This module gives it one explicit,
lightweight, durable owner.

What it does NOT do: redesign trading, place or cancel any order, merge
Experimental state into Original, or fabricate a zero where a value is simply
unknown.

What it does:

* ``EodReconciliationStore`` -- a small durable SQLite store at
  ``~/.talonx/eod_reconciliation.db`` (one row per session date, idempotent
  upsert -- re-running a session overwrites, never duplicates).
* ``build_reconciliation`` -- a pure read-only pass over the two paper ledgers
  (``paper_trading.db``, ``experimental/experimental_paper.db``), the alert
  stores, and -- only if an explicit ``piv_reader`` is injected -- a read-only
  PIV/Alpaca PAPER position/order count. When PIV is not queried it is recorded
  as ``NOT_CHECKED``, never ``0``.
* ``run_and_persist`` -- build + upsert in one call. Idempotent per session.

``AuthoritativeReadModel.eod()`` consumes this store.
"""
from __future__ import annotations

import json
import sqlite3
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

_HOME = Path.home() / ".talonx"

# component check outcomes
CHECKED = "CHECKED"
NOT_CHECKED = "NOT_CHECKED"
UNKNOWN = "UNKNOWN"

# reconciliation status
STATUS_RECONCILED = "RECONCILED"
STATUS_MISMATCH = "RECONCILED_WITH_MISMATCH"
STATUS_PARTIAL = "PARTIAL"
STATUS_UNKNOWN = "UNKNOWN"


def reconciled_to_available_scope(rec: "EodReconciliation | dict") -> bool:
    """Task 137: a `PARTIAL` status has exactly one structural cause in
    this deployment -- ``piv_paper`` is permanently ``NOT_CHECKED`` (PIV/
    Alpaca is a read-only, opt-in-only component that is never injected
    here; this V2 campaign does not use it at all). That makes ``status
    == PARTIAL`` for THIS deployment a standing, permanent condition, not
    a signal of something actually missing/broken -- `eod_reconciled_
    today`/`today_reconciled` (which both require `RECONCILED`/
    `RECONCILED_WITH_MISMATCH`) can therefore never become true here, a
    reporting defect distinct from the genuine "reconciled too early,
    before session close" case Task 118A P3 already guards against.

    Returns True only for the NARROW case this fix actually addresses:
    ``status == PARTIAL``, no mismatches, every component OTHER than
    ``piv_paper`` is ``CHECKED``, and ``piv_paper`` itself is
    ``NOT_CHECKED`` (not e.g. ``UNKNOWN`` from a broker-read error, which
    is a genuinely different, real problem). Deliberately a SEPARATE,
    explicitly-named signal -- it does not change `status`, does not
    change `today_reconciled`'s existing strict meaning, and does not
    retroactively rewrite any persisted record; a caller that wants "did
    this deployment reconcile everything it actually checks" reads this
    in addition to, not instead of, the existing field."""
    d = rec.to_dict() if hasattr(rec, "to_dict") else rec
    if d.get("status") != STATUS_PARTIAL or d.get("mismatches"):
        return False
    comps = {c["name"]: c["outcome"] for c in d.get("component_status", [])}
    if comps.get("piv_paper") != NOT_CHECKED:
        return False
    return all(outcome == CHECKED for name, outcome in comps.items() if name != "piv_paper")

_DDL = """
CREATE TABLE IF NOT EXISTS eod_sessions (
    session_date       TEXT PRIMARY KEY,
    status             TEXT NOT NULL,
    generated_at_utc   TEXT NOT NULL,
    original_positions INTEGER,
    original_trades    INTEGER,
    experimental_positions INTEGER,
    experimental_trades    INTEGER,
    piv_positions      INTEGER,
    piv_orders         INTEGER,
    official_alerts    INTEGER,
    experimental_alerts INTEGER,
    intelligence_events INTEGER,
    payload_json       TEXT NOT NULL
);
"""


@dataclass(frozen=True)
class ComponentStatus:
    name: str
    outcome: str                     # CHECKED / NOT_CHECKED / UNKNOWN
    detail: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class EodReconciliation:
    session_date: str
    status: str
    generated_at_utc: str
    original_paper: dict[str, Any] = field(default_factory=dict)
    experimental_paper: dict[str, Any] = field(default_factory=dict)
    piv_paper: dict[str, Any] = field(default_factory=dict)
    alert_counts: dict[str, Any] = field(default_factory=dict)
    component_status: list[dict[str, Any]] = field(default_factory=list)
    mismatches: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


# --------------------------------------------------------------------------- #
def _ro(path: Path) -> sqlite3.Connection | None:
    if not path.exists():
        return None
    try:
        con = sqlite3.connect(f"file:{path}?mode=ro", uri=True, timeout=1.0)
        con.row_factory = sqlite3.Row
        return con
    except sqlite3.Error:
        return None


def _q1(con: sqlite3.Connection, sql: str, args: tuple = ()) -> Any:
    try:
        row = con.execute(sql, args).fetchone()
        return row[0] if row is not None else None
    except sqlite3.Error:
        return None


def _has_table(con: sqlite3.Connection, name: str) -> bool:
    return _q1(con, "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (name,)) == 1


def _paper_counts(db: Path, session_date: str | None) -> tuple[dict[str, Any], str, str]:
    """Return (values, outcome, detail) for a paper ledger. outcome is
    CHECKED / UNKNOWN (never NOT_CHECKED -- a paper ledger is always local)."""
    con = _ro(db)
    if con is None:
        return {"open_positions": None, "trades_all_time": None, "trades_today": None}, UNKNOWN, f"{db.name} not present"
    try:
        open_pos = _q1(con, "SELECT COUNT(*) FROM positions") if _has_table(con, "positions") else None
        trades = _q1(con, "SELECT COUNT(*) FROM trade_history") if _has_table(con, "trade_history") else None
        trades_today = None
        if _has_table(con, "trade_history") and session_date:
            cols = [r[1] for r in con.execute("PRAGMA table_info(trade_history)")]
            tcol = "timestamp" if "timestamp" in cols else ("ts" if "ts" in cols else None)
            if tcol:
                trades_today = _q1(
                    con, f"SELECT COUNT(*) FROM trade_history WHERE substr({tcol},1,10)=?", (session_date,)
                )
    finally:
        con.close()
    return (
        {"open_positions": open_pos, "trades_all_time": trades, "trades_today": trades_today},
        CHECKED,
        "read-only local ledger",
    )


def _alert_counts(home: Path, exp_home: Path, ledger_path: Path, session_date: str | None) -> dict[str, Any]:
    out: dict[str, Any] = {"official": None, "experimental": None, "intelligence_events": None}
    con = _ro(home / "dispatch_audit.db")
    if con is not None:
        try:
            if _has_table(con, "alerts"):
                if session_date:
                    out["official"] = _q1(
                        con, "SELECT COUNT(*) FROM alerts WHERE substr(received_at,1,10)=?", (session_date,)
                    )
                else:
                    out["official"] = _q1(con, "SELECT COUNT(*) FROM alerts")
        finally:
            con.close()
    con = _ro(exp_home / "exp_alerts.db")
    if con is not None:
        try:
            total = 0
            seen = False
            for t in ("directional_alerts", "experimental_trades", "radar_alerts", "event_updates"):
                if _has_table(con, t):
                    seen = True
                    total += _q1(con, f"SELECT COUNT(*) FROM {t}") or 0
            out["experimental"] = total if seen else None
        finally:
            con.close()
    con = _ro(ledger_path)
    if con is not None:
        try:
            if _has_table(con, "text_events"):
                out["intelligence_events"] = _q1(con, "SELECT COUNT(*) FROM text_events")
        finally:
            con.close()
    return out


def build_reconciliation(
    *,
    session_date: str | None = None,
    home: Path | None = None,
    exp_home: Path | None = None,
    ledger_path: Path | None = None,
    now: datetime | None = None,
    piv_reader: Callable[[], dict[str, Any]] | None = None,
) -> EodReconciliation:
    """Pure read-only reconciliation build. No writes, no orders.

    ``piv_reader`` -- optional zero-arg callable returning e.g.
    ``{"positions": 0, "orders": 0}`` from a read-only Alpaca PAPER query. If
    omitted (offline / not opted in) PIV is recorded ``NOT_CHECKED`` -- never
    fabricated as ``0``.
    """
    now = now or datetime.now(timezone.utc)
    home = home or _HOME
    exp_home = exp_home or (home / "experimental")
    ledger_path = ledger_path or (home / "ingestion_ledger.db")
    session_date = session_date or now.astimezone(timezone.utc).strftime("%Y-%m-%d")

    components: list[ComponentStatus] = []
    mismatches: list[str] = []

    orig_vals, orig_outcome, orig_detail = _paper_counts(home / "paper_trading.db", session_date)
    components.append(ComponentStatus("original_paper", orig_outcome, orig_detail))

    exp_vals, exp_outcome, exp_detail = _paper_counts(exp_home / "experimental_paper.db", session_date)
    components.append(ComponentStatus("experimental_paper", exp_outcome, exp_detail))

    # PIV / broker -- READ ONLY, opt-in
    piv_vals: dict[str, Any] = {"positions": None, "orders": None}
    if piv_reader is None:
        piv_outcome, piv_detail = NOT_CHECKED, "no piv_reader injected (offline / not opted in)"
    else:
        try:
            raw = piv_reader() or {}
            piv_vals = {"positions": raw.get("positions"), "orders": raw.get("orders")}
            if piv_vals["positions"] is None and piv_vals["orders"] is None:
                piv_outcome, piv_detail = UNKNOWN, "piv_reader returned no counts"
            else:
                piv_outcome, piv_detail = CHECKED, "read-only Alpaca PAPER query"
        except Exception as exc:  # noqa: BLE001 -- a broker read failure must never raise here
            piv_outcome, piv_detail = UNKNOWN, f"piv_reader error: {exc!r}"
    components.append(ComponentStatus("piv_paper", piv_outcome, piv_detail))

    alerts = _alert_counts(home, exp_home, ledger_path, session_date)
    components.append(
        ComponentStatus(
            "alert_stores",
            CHECKED if any(v is not None for v in alerts.values()) else UNKNOWN,
            "dispatch_audit.db / exp_alerts.db / ingestion_ledger.db",
        )
    )

    # mismatch detection is intentionally conservative: only flag things that are
    # genuinely inconsistent, never a normal flat book.
    if orig_vals["open_positions"] and orig_vals["trades_today"] == 0 and orig_vals["trades_all_time"] == 0:
        mismatches.append(
            f"original_paper: {orig_vals['open_positions']} open position(s) but 0 trades recorded ever"
        )
    if exp_vals["open_positions"] and exp_vals["trades_all_time"] == 0:
        mismatches.append(
            f"experimental_paper: {exp_vals['open_positions']} open position(s) but 0 trades recorded ever"
        )

    outcomes = {c.outcome for c in components}
    if outcomes == {CHECKED}:
        status = STATUS_MISMATCH if mismatches else STATUS_RECONCILED
    elif CHECKED in outcomes:
        status = STATUS_MISMATCH if mismatches else STATUS_PARTIAL
    else:
        status = STATUS_UNKNOWN

    return EodReconciliation(
        session_date=session_date,
        status=status,
        generated_at_utc=now.astimezone(timezone.utc).isoformat(),
        original_paper=orig_vals,
        experimental_paper=exp_vals,
        piv_paper=piv_vals,
        alert_counts=alerts,
        component_status=[c.to_dict() for c in components],
        mismatches=mismatches,
    )


# --------------------------------------------------------------------------- #
class EodReconciliationStore:
    """Durable, idempotent per-session EOD reconciliation store.

    ``__init__`` runs ``CREATE TABLE IF NOT EXISTS`` (the project convention).
    Pass ``read_only=True`` for a consumer that must not create the file.
    """

    def __init__(self, db_path: str | Path | None = None, *, read_only: bool = False) -> None:
        self.db_path = str(db_path or (_HOME / "eod_reconciliation.db"))
        self._read_only = read_only
        self._conn: sqlite3.Connection | None = None
        if read_only:
            if Path(self.db_path).exists():
                try:
                    self._conn = sqlite3.connect(f"file:{self.db_path}?mode=ro", uri=True, timeout=1.0)
                    self._conn.row_factory = sqlite3.Row
                except sqlite3.Error:
                    self._conn = None
            return
        Path(self.db_path).expanduser().parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(self.db_path, check_same_thread=False, timeout=5.0)
        self._conn.row_factory = sqlite3.Row
        self._conn.executescript(_DDL)
        self._conn.commit()

    def upsert(self, rec: EodReconciliation) -> None:
        if self._conn is None or self._read_only:
            raise RuntimeError("EodReconciliationStore opened read-only")
        p = rec.to_dict()
        self._conn.execute(
            """
            INSERT INTO eod_sessions (
                session_date, status, generated_at_utc,
                original_positions, original_trades,
                experimental_positions, experimental_trades,
                piv_positions, piv_orders,
                official_alerts, experimental_alerts, intelligence_events,
                payload_json
            ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)
            ON CONFLICT(session_date) DO UPDATE SET
                status=excluded.status,
                generated_at_utc=excluded.generated_at_utc,
                original_positions=excluded.original_positions,
                original_trades=excluded.original_trades,
                experimental_positions=excluded.experimental_positions,
                experimental_trades=excluded.experimental_trades,
                piv_positions=excluded.piv_positions,
                piv_orders=excluded.piv_orders,
                official_alerts=excluded.official_alerts,
                experimental_alerts=excluded.experimental_alerts,
                intelligence_events=excluded.intelligence_events,
                payload_json=excluded.payload_json
            """,
            (
                rec.session_date, rec.status, rec.generated_at_utc,
                rec.original_paper.get("open_positions"), rec.original_paper.get("trades_all_time"),
                rec.experimental_paper.get("open_positions"), rec.experimental_paper.get("trades_all_time"),
                rec.piv_paper.get("positions"), rec.piv_paper.get("orders"),
                rec.alert_counts.get("official"), rec.alert_counts.get("experimental"),
                rec.alert_counts.get("intelligence_events"),
                json.dumps(p, default=str),
            ),
        )
        self._conn.commit()

    def get(self, session_date: str) -> EodReconciliation | None:
        if self._conn is None:
            return None
        try:
            row = self._conn.execute(
                "SELECT payload_json FROM eod_sessions WHERE session_date=?", (session_date,)
            ).fetchone()
        except sqlite3.Error:
            return None
        if row is None:
            return None
        return _rec_from_payload(row["payload_json"])

    def latest(self) -> EodReconciliation | None:
        if self._conn is None:
            return None
        try:
            row = self._conn.execute(
                "SELECT payload_json FROM eod_sessions ORDER BY session_date DESC LIMIT 1"
            ).fetchone()
        except sqlite3.Error:
            return None
        if row is None:
            return None
        return _rec_from_payload(row["payload_json"])

    def close(self) -> None:
        if self._conn is not None:
            try:
                self._conn.close()
            except sqlite3.Error:
                pass
            self._conn = None


def _rec_from_payload(payload_json: str) -> EodReconciliation | None:
    try:
        d = json.loads(payload_json)
        return EodReconciliation(
            session_date=d["session_date"],
            status=d["status"],
            generated_at_utc=d["generated_at_utc"],
            original_paper=d.get("original_paper", {}),
            experimental_paper=d.get("experimental_paper", {}),
            piv_paper=d.get("piv_paper", {}),
            alert_counts=d.get("alert_counts", {}),
            component_status=d.get("component_status", []),
            mismatches=d.get("mismatches", []),
        )
    except (ValueError, KeyError):
        return None


def run_and_persist(
    *,
    session_date: str | None = None,
    db_path: str | Path | None = None,
    home: Path | None = None,
    exp_home: Path | None = None,
    ledger_path: Path | None = None,
    now: datetime | None = None,
    piv_reader: Callable[[], dict[str, Any]] | None = None,
) -> EodReconciliation:
    """Build the reconciliation and idempotently persist it. Safe to call more
    than once for the same session (the row is upserted, not duplicated)."""
    rec = build_reconciliation(
        session_date=session_date, home=home, exp_home=exp_home,
        ledger_path=ledger_path, now=now, piv_reader=piv_reader,
    )
    store = EodReconciliationStore(db_path)
    try:
        store.upsert(rec)
    finally:
        store.close()
    return rec
