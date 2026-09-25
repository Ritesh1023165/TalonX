"""/scanned: read-only summaries + CSV export from the Opportunity Engine's authoritative stores (mode=ro)."""
from __future__ import annotations

import csv
import io
import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
SETUPS = ("BULLISH", "BEARISH")


def _ro(p: Path):
    if not p.exists():
        return None
    c = sqlite3.connect(f"file:{p}?mode=ro", uri=True, timeout=5)
    c.row_factory = sqlite3.Row
    return c


class ScannedReader:
    def __init__(self, root=None, *, window_id: str | None = None, excluded: set[str] | None = None,
                 added: set[str] | None = None):
        self.root = Path(root) if root else REPO_ROOT / "results" / "opportunity"
        self.o, self.m, self.p = (_ro(self.root / n) for n in ("opportunity.db", "market.db", "promotion.db"))
        self.excluded, self.added = excluded or set(), added or set()
        if window_id is None and self.o is not None:
            r = self.o.execute("SELECT window_id FROM scans ORDER BY decision_utc DESC LIMIT 1").fetchone()
            window_id = r[0] if r else None
        self.wid = window_id or datetime.now(timezone.utc).date().isoformat()

    def summary(self) -> dict:
        out = {"window": self.wid}
        if self.o is None:
            return {**out, "available": False}
        last = self.o.execute("SELECT decision_utc, phase, duration_s, funnel_json FROM scans WHERE window_id=? "
                              "ORDER BY decision_utc DESC LIMIT 1", (self.wid,)).fetchone()
        f = json.loads(last["funnel_json"] or "{}") if last else {}
        seen = self.m.execute("SELECT COUNT(*) FROM aggregates WHERE window_id=? AND json_extract(agg_json,'$.bars')>0",
                              (self.wid,)).fetchone()[0] if self.m else None
        evaluated = self.o.execute("SELECT COUNT(*) FROM symbol_latest WHERE window_id=?", (self.wid,)).fetchone()[0]
        cands = self.o.execute("SELECT COUNT(*) FROM candidates WHERE window_id=?", (self.wid,)).fetchone()[0]
        setups = self.o.execute("SELECT COUNT(DISTINCT candidate_id) FROM candidate_events WHERE window_id=? AND "
                                "classification IN ('BULLISH','BEARISH')", (self.wid,)).fetchone()[0]
        sig = shadow = 0
        if self.p is not None:
            sig = self.p.execute("SELECT COUNT(*) FROM promotions WHERE state='PROMOTED_SIGNAL' AND window_id=?",
                                 (self.wid,)).fetchone()[0]
            shadow = self.p.execute("SELECT COUNT(*) FROM promotions WHERE state='PROMOTED_SHADOW' AND window_id=?",
                                    (self.wid,)).fetchone()[0]
        return {**out, "available": True, "unique_symbols_seen": seen, "symbols_evaluated_last_scan": evaluated,
                "data_ready_last_scan": f.get("DATA_READY"), "candidates": cands, "setups": setups,
                "paper_signal_promotions": sig, "shadow_promotions": shadow,
                "current_phase": last["phase"] if last else None,
                "last_scan_utc": last["decision_utc"] if last else None,
                "last_scan_s": round(last["duration_s"] or 0) if last else None}

    def candidates(self, limit: int = 15) -> tuple[int, list[dict]]:
        rows = [dict(r) for r in self.o.execute(
            "SELECT symbol, state, max_score, last_gap_pct FROM candidates WHERE window_id=? AND state IN "
            "('WATCH','BULLISH_SETUP','BEARISH_SETUP') ORDER BY max_score DESC", (self.wid,))] if self.o else []
        return len(rows), rows[:limit]

    def setups(self, limit: int = 15) -> tuple[int, list[dict]]:
        rows = [dict(r) for r in self.o.execute(
            "SELECT symbol, state, max_score, last_gap_pct FROM candidates WHERE window_id=? AND state IN "
            "('BULLISH_SETUP','BEARISH_SETUP') ORDER BY max_score DESC", (self.wid,))] if self.o else []
        return len(rows), rows[:limit]

    def signals(self, limit: int = 15) -> tuple[int, list[dict]]:
        rows = [dict(r) for r in self.p.execute(
            "SELECT symbol, score, reference_price, decision_utc, promotion_mode, state FROM promotions WHERE "
            "window_id=? AND state IN ('PROMOTED_SIGNAL','PROMOTED_SHADOW') ORDER BY decision_utc", (self.wid,))] \
            if self.p else []
        return len(rows), rows[:limit]

    def export_csv(self) -> tuple[str, int]:
        cols = ["symbol", "first_seen", "last_seen", "lifecycle_events", "max_move", "max_score", "candidate",
                "setup", "signal_promoted", "final_state", "excluded", "universe_source"]
        rows: dict[str, dict] = {}
        if self.o is not None:
            for r in self.o.execute("SELECT symbol, decision_utc, cls, gap_pct, score FROM symbol_latest WHERE window_id=?",
                                    (self.wid,)):
                rows[r["symbol"]] = {"symbol": r["symbol"], "first_seen": "", "last_seen": r["decision_utc"],
                                     "lifecycle_events": 0, "max_move": r["gap_pct"], "max_score": r["score"],
                                     "candidate": "N", "setup": "N", "signal_promoted": "N", "final_state": r["cls"]}
            for c in self.o.execute("SELECT candidate_id, symbol, first_seen_utc, last_observed_utc, max_score, state "
                                    "FROM candidates WHERE window_id=?", (self.wid,)):
                ev = self.o.execute("SELECT COUNT(*), MAX(ABS(gap_pct)), SUM(classification IN ('BULLISH','BEARISH')) "
                                    "FROM candidate_events WHERE candidate_id=?", (c["candidate_id"],)).fetchone()
                d = rows.setdefault(c["symbol"], {"symbol": c["symbol"], "max_move": None, "max_score": None})
                d.update(first_seen=min(filter(None, [d.get("first_seen") or None, c["first_seen_utc"]])),
                         last_seen=max(filter(None, [d.get("last_seen") or None, c["last_observed_utc"] or ""])),
                         lifecycle_events=(d.get("lifecycle_events") or 0) + (ev[0] or 0),
                         max_move=max(filter(lambda x: x is not None, [abs(d.get("max_move") or 0), ev[1] or 0])),
                         max_score=max(filter(lambda x: x is not None, [d.get("max_score") or 0, c["max_score"] or 0])),
                         candidate="Y", setup="Y" if (ev[2] or 0) > 0 or d.get("setup") == "Y" else "N",
                         final_state=c["state"])
        if self.p is not None:
            for r in self.p.execute("SELECT symbol FROM promotions WHERE state IN ('PROMOTED_SIGNAL','PROMOTED_SHADOW') "
                                    "AND window_id=?", (self.wid,)):
                if r["symbol"] in rows:
                    rows[r["symbol"]]["signal_promoted"] = "Y"
        buf = io.StringIO()
        w = csv.DictWriter(buf, fieldnames=cols, extrasaction="ignore")
        w.writeheader()
        for s in sorted(rows):
            d = rows[s]
            d["excluded"] = "Y" if s in self.excluded else "N"
            d["universe_source"] = "OPERATOR" if s in self.added else "BASE"
            w.writerow(d)
        return buf.getvalue(), len(rows)
