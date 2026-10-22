"""Read-only regression check for the 2026-10-22 SEC-context length fix (nothing is sent).

usage: python verify_sec_length_fix.py <live repo root> <failed promotion_id>
1. Re-renders every V3 review alert in the live Signal outbox from the live records (same context as
   Promoter._review_context) with THIS checkout's code and compares it byte-for-byte with what was sent.
2. Renders the failed promotion with the fix and reports its Telegram length (UTF-16 of the visible text)."""
from __future__ import annotations

import html
import json
import re
import sqlite3
import sys
from datetime import date
from pathlib import Path

from talonx_opportunity import promotion as P
from talonx_opportunity.phases import trading_window


def ro(p: Path) -> sqlite3.Connection:
    c = sqlite3.connect(f"file:{p.as_posix()}?mode=ro", uri=True, timeout=5)
    c.row_factory = sqlite3.Row
    return c


def u16(s: str) -> int:
    return len(s.encode("utf-16-le")) // 2


def render(pr, op, ob, sched, pid):
    q = dict(pr.execute("SELECT * FROM promotions WHERE promotion_id=?", (pid,)).fetchone())
    sent = ob.execute("SELECT payload_text, created_at_utc FROM ops_notification_outbox WHERE event_id=?",
                      (q["signal_event_id"],)).fetchone()
    ev = op.execute("SELECT features_json, score_json, catalyst, provenance_json, at_utc FROM candidate_events "
                    "WHERE event_id=?", (q["event_id"],)).fetchone()
    ids = [r[0] for r in pr.execute("SELECT signal_event_id FROM promotions WHERE symbol=? AND promotion_id!=? AND "
                                    "state='PROMOTED_SIGNAL' AND signal_event_id IS NOT NULL", (q["symbol"], pid))]
    prior = None
    if ids:
        last = ob.execute(f"SELECT MAX(sent_at_utc) FROM ops_notification_outbox WHERE state='SENT' AND event_id IN "
                          f"({','.join('?' * len(ids))}) AND sent_at_utc < ?", [*ids, sent["created_at_utc"]]).fetchone()[0]
        prior = P._ts(last).astimezone(P._ET).date().isoformat() if last else None
    uni = None
    for e in sorted(sched["schedule"], key=lambda e: e["effective_from_window"]):
        if e["effective_from_window"] <= q["window_id"]:
            uni = str(e["policy"])
    ctx = {"event": dict(ev) if ev else None, "close_utc": trading_window(date.fromisoformat(q["window_id"])).close_utc,
           "prior_delivery_date": prior, "universe": uni}
    return P.render_review_expandable(q, P._ts(q["decision_utc"]), "OPPORTUNITY_PROMOTION_V1", ctx), sent["payload_text"]


def main(root: Path, failed: str) -> int:
    opp = root / "results" / "opportunity"
    pr, op, ob = ro(opp / "promotion.db"), ro(opp / "opportunity.db"), ro(opp / "promotion_signal_notifications.db")
    sched = json.loads((opp / "control" / "dtu_policy_schedule.json").read_text(encoding="utf-8"))
    rows = [r[0] for r in ob.execute("SELECT event_id FROM ops_notification_outbox WHERE provenance_json LIKE "
                                     "'%EXPANDABLE_V3%' ORDER BY created_at_utc")]
    same, diff = 0, []
    for pid in rows:
        new, old = render(pr, op, ob, sched, pid)
        if new == old:
            same += 1
        else:
            diff.append(pid)
    print(f"V3 alerts in outbox: {len(rows)}; re-rendered byte-identical: {same}; different: {len(diff)} {diff}")
    new, _ = render(pr, op, ob, sched, failed)
    vis = html.unescape(re.sub(r"<[^>]*>", "", new))
    sec = next((ln for ln in vis.split("\n") if "SEC context" in ln), "")
    print(f"{failed}: fixed render {u16(vis)} UTF-16 units visible (limit {P.TELEGRAM_TEXT_LIMIT}); "
          f"truncation marker: {P._TRUNCATED in vis}")
    print("SEC line:", sec)
    return 0


if __name__ == "__main__":
    sys.exit(main(Path(sys.argv[1]), sys.argv[2]))
