"""Local V3 renders of real delivered review alerts (nothing is sent). Read-only on the live stores.

usage: python render_v3_examples.py <live repo root> <promotion_id> [<promotion_id> ...]
For each promotion: rebuilds the render-time context exactly as Promoter._review_context does (read-only), checks that
the V2 render reproduces the payload that was actually sent, then prints the V3 render and its sizes."""
from __future__ import annotations

import html
import json
import re
import sqlite3
import sys
from datetime import date
from pathlib import Path

from talonx_opportunity import promotion as P
from talonx_opportunity.db import utcnow  # noqa: F401  (import parity with the component)
from talonx_opportunity.phases import trading_window


def ro(p: Path) -> sqlite3.Connection:
    c = sqlite3.connect(f"file:{p.as_posix()}?mode=ro", uri=True, timeout=5)
    c.row_factory = sqlite3.Row
    return c


def main(root: Path, ids: list[str]) -> int:
    opp = root / "results" / "opportunity"
    pr, op, ob = ro(opp / "promotion.db"), ro(opp / "opportunity.db"), ro(opp / "promotion_signal_notifications.db")
    sched = json.loads((opp / "control" / "dtu_policy_schedule.json").read_text(encoding="utf-8"))
    ok = True
    for pid in ids:
        q = dict(pr.execute("SELECT * FROM promotions WHERE promotion_id=?", (pid,)).fetchone())
        sent = ob.execute("SELECT payload_text, created_at_utc FROM ops_notification_outbox WHERE event_id=?",
                          (q["signal_event_id"],)).fetchone()
        ev = op.execute("SELECT features_json, score_json, catalyst, provenance_json, at_utc FROM candidate_events "
                        "WHERE event_id=?", (q["event_id"],)).fetchone()
        ids_prior = [r[0] for r in pr.execute(
            "SELECT signal_event_id FROM promotions WHERE symbol=? AND promotion_id!=? AND state='PROMOTED_SIGNAL' "
            "AND signal_event_id IS NOT NULL", (q["symbol"], pid))]
        prior = None
        if ids_prior:
            last = ob.execute(f"SELECT MAX(sent_at_utc) FROM ops_notification_outbox WHERE state='SENT' AND event_id IN "
                              f"({','.join('?' * len(ids_prior))}) AND sent_at_utc < ?",
                              [*ids_prior, sent["created_at_utc"]]).fetchone()[0]
            prior = P._ts(last).astimezone(P._ET).date().isoformat() if last else None
        uni = None
        for e in sorted(sched["schedule"], key=lambda e: e["effective_from_window"]):
            if e["effective_from_window"] <= q["window_id"]:
                uni = str(e["policy"])
        ctx = {"event": dict(ev) if ev else None,
               "close_utc": trading_window(date.fromisoformat(q["window_id"])).close_utc,
               "prior_delivery_date": prior, "universe": uni}
        now = P._ts(q["decision_utc"])
        v2 = P.render_review_compact(q, now, "OPPORTUNITY_PROMOTION_V1", ctx)
        same = v2 == sent["payload_text"]
        ok &= same
        v3 = P.render_review_expandable(q, now, "OPPORTUNITY_PROMOTION_V1", ctx)
        vis = html.unescape(re.sub(r"<[^>]*>", "", v3))
        collapsed = v3.split(P.HTML_DETAILS_OPEN)[0].rstrip("\n")
        print(f"## {pid}\n\nV2 re-render == sent payload: {same}  |  V3: {len(v3)} chars raw, {len(vis)} visible; "
              f"tags {sorted(set(re.findall(r'<[^>]*>', v3)))}\n")
        print("### Collapsed view (what shows before tapping)\n```\n" + html.unescape(re.sub(r"</?b>", "", collapsed))
              + "\n▸ (tap to expand)\n```\n")
        print("### Raw HTML payload (sent with parse_mode=HTML)\n```html\n" + v3 + "\n```\n")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main(Path(sys.argv[1]), sys.argv[2:]))
