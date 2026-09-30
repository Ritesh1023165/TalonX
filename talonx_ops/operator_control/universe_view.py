"""Read-only Dynamic Tradable Universe view for Sentinel (/universe summary | status SYM | excluded [file]).
Reads market.db (mode=ro) DTU tables written by DATA_INGESTION; never mutates anything; no symbol floods."""
from __future__ import annotations

import csv
import io
import json
import sqlite3
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
ACTIVE_STATES = ("ACTIVE_CORE", "EVENT_PROMOTED", "OPERATOR_ADDED")


class UniverseView:
    def __init__(self, root=None, window_id: str | None = None):
        self.root = Path(root) if root else REPO_ROOT / "results" / "opportunity"
        p = self.root / "market.db"
        self.m = sqlite3.connect(f"file:{p}?mode=ro", uri=True, timeout=5) if p.exists() else None
        self.wid = window_id
        if self.m is not None and self.wid is None:
            try:
                r = self.m.execute("SELECT window_id FROM dtu_snapshots ORDER BY window_id DESC LIMIT 1").fetchone()
                self.wid = r[0] if r else None
            except sqlite3.Error:
                self.wid = None

    def available(self) -> bool:
        return self.m is not None and self.wid is not None

    def latest(self) -> dict:
        r = self.m.execute("SELECT cycle_utc, n_active, counts_json, fallback_reason FROM dtu_active WHERE window_id=? "
                           "ORDER BY cycle_utc DESC LIMIT 1", (self.wid,)).fetchone()
        return {} if r is None else {"cycle_utc": r[0], "n_active": r[1], "counts": json.loads(r[2] or "{}"),
                                     "fallback": r[3]}

    def summary(self) -> dict:
        snap = self.m.execute("SELECT snapshot_version, created_utc, counts_json FROM dtu_snapshots WHERE window_id=?",
                              (self.wid,)).fetchone()
        return {"window": self.wid, "snapshot_version": snap[0] if snap else None,
                "snapshot_created_utc": snap[1] if snap else None,
                "snapshot_counts": json.loads(snap[2]) if snap else {}, **self.latest()}

    def status(self, sym: str) -> dict:
        r = self.m.execute("SELECT state, reason, core_rank, price, adv20 FROM dtu_snapshot WHERE window_id=? AND "
                           "symbol=?", (self.wid, sym)).fetchone()
        prom = self.m.execute("SELECT reason, started_utc, expires_utc, source_event_id FROM dtu_promotions WHERE "
                              "symbol=? ORDER BY started_utc DESC LIMIT 3", (sym,)).fetchall()
        return {"symbol": sym, "snapshot_state": r[0] if r else "NOT_IN_UNIVERSE", "reason": r[1] if r else None,
                "core_rank": r[2] if r else None, "price": r[3] if r else None, "adv20": r[4] if r else None,
                "promotions": [{"reason": p[0], "started_utc": p[1], "expires_utc": p[2], "source": p[3]}
                               for p in prom]}

    def excluded_rows(self) -> list[dict]:
        rows = self.m.execute("SELECT symbol, state, reason, price, adv20, core_rank FROM dtu_snapshot WHERE "
                              "window_id=? AND state NOT IN ('ACTIVE_CORE') ORDER BY state, symbol",
                              (self.wid,)).fetchall()
        return [{"symbol": r[0], "state": r[1], "reason": r[2], "price": r[3], "adv20": r[4], "core_rank": r[5],
                 "promotion_eligible": r[1] == "EVENT_ELIGIBLE", "snapshot_date": self.wid} for r in rows]

    def excluded_csv(self) -> bytes:
        buf = io.StringIO()
        rows = self.excluded_rows()
        w = csv.DictWriter(buf, fieldnames=["symbol", "state", "reason", "price", "adv20", "core_rank",
                                            "promotion_eligible", "snapshot_date"])
        w.writeheader()
        w.writerows(rows)
        return buf.getvalue().encode()


def summary_text(v: UniverseView, head: str) -> str:
    if not v.available():
        return f"{head} — UNIVERSE\nDTU snapshot not available (DTU mode OFF or not built yet): full universe in use."
    s = v.summary()
    c, sc = s.get("counts", {}), s["snapshot_counts"]
    fb = s.get("fallback")
    return "\n".join([
        f"{head} — UNIVERSE ({s['window']})",
        f"Core: {c.get('ACTIVE_CORE', sc.get('ACTIVE_CORE', 0))}",
        f"Event-promoted: {c.get('EVENT_PROMOTED', 0)} (protected {c.get('protected', 0)})",
        f"Event-eligible: {c.get('EVENT_ELIGIBLE', sc.get('EVENT_ELIGIBLE', 0))}",
        f"Auto-excluded: {c.get('AUTO_EXCLUDED', sc.get('AUTO_EXCLUDED', 0))}",
        f"Operator-added: {c.get('OPERATOR_ADDED', 0)} · Operator-excluded: {c.get('OPERATOR_EXCLUDED', 0)}",
        f"Structurally excluded: {sc.get('STRUCTURALLY_EXCLUDED', 0)}",
        f"Effective active: {s.get('n_active', 'n/a')}" + (f" ⚠️ FALLBACK full universe: {fb}" if fb else ""),
        f"Snapshot: {s['snapshot_version']}"])


def status_text(v: UniverseView, sym: str, head: str) -> str:
    if not v.available():
        return f"{head} — {sym}\nDTU not available: full universe in use."
    s = v.status(sym)
    p = s["promotions"][0] if s["promotions"] else None
    lines = [f"{head} — {sym} (universe {v.wid})", f"Snapshot state: {s['snapshot_state']}",
             f"Why: {s['reason'] or '-'}", f"Core rank: {s['core_rank'] or '-'}"]
    if p:
        lines.append(f"Promotion: {p['reason']} since {str(p['started_utc'])[11:16]}Z · expires "
                     f"{str(p['expires_utc'])[:16] if p['expires_utc'] else 'never'}")
    return "\n".join(lines)


def excluded_text(v: UniverseView, head: str) -> str:
    if not v.available():
        return f"{head} — EXCLUDED\nDTU not available."
    rows = v.excluded_rows()
    by: dict[str, int] = {}
    for r in rows:
        k = f"{r['state']}:{(r['reason'] or '').split('_RANK_')[0] if r['state'] != 'EVENT_ELIGIBLE' else 'outside Core'}"
        by[k] = by.get(k, 0) + 1
    top = sorted(by.items(), key=lambda kv: -kv[1])[:12]
    return "\n".join([f"{head} — NOT IN CORE ({len(rows)}) · {v.wid}"] + [f"• {n} {k}" for k, n in top] +
                     ["Full list: /universe excluded file"])
