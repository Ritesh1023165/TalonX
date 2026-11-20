"""Read-only replay of one past session's review alerts, before vs after the 2026-11-20 thinning (nothing is sent).

usage: python replay_session.py <live repo root> <window YYYY-MM-DD> [cap=10]

The session cap is a delivery filter applied after unchanged release decisions, so applying it to the RECORDED release
order (decision_utc, then queue_rank) is exact: the first ``cap`` PROMOTED_SIGNAL rows would still be sent, the rest
would be recorded PROMOTED_SHADOW / THINNED_SESSION_CAP. Also re-renders the first alert of the session with THIS
checkout's template (V4) next to the payload that was actually sent, to show the wording change on real data."""
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


def visible(t: str) -> str:
    return html.unescape(re.sub(r"<[^>]*>", "", t))


def main(root: Path, window: str, cap: int = 10) -> int:
    opp = root / "results" / "opportunity"
    pr, op, ob = ro(opp / "promotion.db"), ro(opp / "opportunity.db"), ro(opp / "promotion_signal_notifications.db")
    rows = [dict(r) for r in pr.execute(
        "SELECT promotion_id, symbol, score, decision_utc, queue_rank, signal_event_id FROM promotions "
        "WHERE window_id=? AND state='PROMOTED_SIGNAL' ORDER BY decision_utc, queue_rank", (window,))]
    print(f"# Replay {window}: review alerts before vs after the session cap ({cap})\n")
    print(f"- Delivered that session (before): **{len(rows)}**")
    print(f"- Would be delivered with the cap (after): **{min(cap, len(rows))}**")
    print(f"- Would be recorded THINNED_SESSION_CAP (never sent): **{max(0, len(rows) - cap)}**\n")
    print("| # | Released (UTC) | Symbol | Rule score | After thinning |")
    print("|---|---|---|---|---|")
    for i, r in enumerate(rows, 1):
        print(f"| {i} | {r['decision_utc'][11:19]} | {r['symbol']} | {r['score']:.1f} | "
              f"{'SENT' if i <= cap else 'THINNED (record-only)'} |")
    if rows:                                                     # wording before vs after, on the first real alert
        q = dict(pr.execute("SELECT * FROM promotions WHERE promotion_id=?", (rows[0]["promotion_id"],)).fetchone())
        sent = ob.execute("SELECT payload_text FROM ops_notification_outbox WHERE event_id=?",
                          (q["signal_event_id"],)).fetchone()[0]
        ev = op.execute("SELECT features_json, score_json, catalyst, provenance_json, at_utc FROM candidate_events "
                        "WHERE event_id=?", (q["event_id"],)).fetchone()
        sched = json.loads((opp / "control" / "dtu_policy_schedule.json").read_text(encoding="utf-8"))
        uni = None
        for e in sorted(sched["schedule"], key=lambda e: e["effective_from_window"]):
            if e["effective_from_window"] <= window:
                uni = str(e["policy"])
        ctx = {"event": dict(ev) if ev else None, "close_utc": trading_window(date.fromisoformat(window)).close_utc,
               "prior_delivery_date": None, "universe": uni}
        new = P.render_review_expandable(q, P._ts(q["decision_utc"]), "OPPORTUNITY_PROMOTION_V1", ctx)
        print(f"\n## Wording: first alert of the session ({q['symbol']})\n")
        print("Collapsed summary as SENT (V3):\n```\n" + visible(sent.split(P.HTML_DETAILS_OPEN)[0]).rstrip() + "\n```")
        print("Collapsed summary with this change (V4, local render, not sent):\n```\n"
              + visible(new.split(P.HTML_DETAILS_OPEN)[0]).rstrip() + "\n```")
        def body(t):
            return [x for x in visible(t.split(P.HTML_DETAILS_OPEN, 1)[1]).split("\n") if not x.startswith("🔁")]
        old_d, new_d = body(sent), body(new)
        changed = [(a, b) for a, b in zip(old_d, new_d) if a != b]
        print("Expanded-detail lines that change (prior-delivery line omitted in the local render):")
        for a, b in changed:
            print(f"- `{a}` → `{b}`")
    return 0


if __name__ == "__main__":
    sys.exit(main(Path(sys.argv[1]), sys.argv[2], int(sys.argv[3]) if len(sys.argv) > 3 else 10))
