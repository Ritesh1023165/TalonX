"""LOCAL, READ-ONLY re-render of already-delivered review alerts with the compact template (deployment evidence only).

Nothing is sent, written or replayed: production databases are opened with read-only URIs and the output is printed.
Each example is rendered "as of" its ORIGINAL render instant (outbox created_at), so the Repeat lookup only sees
deliveries confirmed before that instant. Context is gathered with the same queries as Promoter._review_context.

usage: python render_examples.py [ROOT] [SYMBOL ...]
"""
from __future__ import annotations

import json
import sqlite3
import sys
from datetime import date
from pathlib import Path

CODE = Path(__file__).resolve().parents[4]          # renderer from THIS checkout
ROOT = Path(sys.argv[1]) if len(sys.argv) > 1 else CODE   # data (read-only) from ROOT
sys.path.insert(0, str(CODE))
from talonx_opportunity import promotion as P  # noqa: E402
from talonx_opportunity.phases import trading_window  # noqa: E402

SYMS = sys.argv[2:] or ["TWLO", "CF", "PBR", "PANW", "XYZ"]
OPP = ROOT / "results" / "opportunity"


def ro(p):
    c = sqlite3.connect(f"file:{p}?mode=ro", uri=True)
    c.row_factory = sqlite3.Row
    return c


def main():
    pc, op, ob = ro(OPP / "promotion.db"), ro(OPP / "opportunity.db"), ro(OPP / "promotion_signal_notifications.db")
    sched = json.loads((OPP / "control" / "dtu_policy_schedule.json").read_text(encoding="utf-8"))
    sys.stdout.reconfigure(encoding="utf-8")
    for sym in SYMS:
        q = pc.execute("SELECT * FROM promotions WHERE symbol=? AND window_id='2026-10-09' AND state='PROMOTED_SIGNAL' "
                       "AND reason_code='RESEARCH_REVIEW_ALERT' ORDER BY decision_utc DESC LIMIT 1", (sym,)).fetchone()
        if q is None:
            continue
        q = dict(q)
        o = ob.execute("SELECT payload_text, created_at_utc FROM ops_notification_outbox WHERE event_id=?",
                       (q["signal_event_id"],)).fetchone()
        now = P._ts(o["created_at_utc"])
        ev = op.execute("SELECT features_json, score_json, catalyst, provenance_json, at_utc FROM candidate_events "
                        "WHERE event_id=?", (q["event_id"],)).fetchone()
        ids = [r[0] for r in pc.execute("SELECT signal_event_id FROM promotions WHERE symbol=? AND promotion_id!=? AND "
                                        "state='PROMOTED_SIGNAL' AND signal_event_id IS NOT NULL",
                                        (sym, q["promotion_id"]))]
        last = ob.execute(f"SELECT MAX(sent_at_utc) FROM ops_notification_outbox WHERE state='SENT' AND sent_at_utc<? "
                          f"AND event_id IN ({','.join('?' * len(ids)) or 'NULL'})",
                          [o["created_at_utc"], *ids]).fetchone()[0] if ids else None
        uni = None
        for e in sorted(sched["schedule"], key=lambda e: e["effective_from_window"]):
            if e["effective_from_window"] <= q["window_id"]:
                uni = e["policy"]
        ctx = {"event": dict(ev) if ev else None,
               "close_utc": trading_window(date.fromisoformat(q["window_id"])).close_utc,
               "prior_delivery_date": P._ts(last).astimezone(P._ET).date().isoformat() if last else None,
               "universe": uni}
        new = P.render_review_compact(q, now, q["policy_version"], ctx)
        print(f"### {sym}\n\nEXISTING (as delivered):\n```\n{o['payload_text']}\n```\n\nCOMPACT "
              f"({P.REVIEW_TEMPLATE_VERSION}, local render as of {o['created_at_utc']}; {len(new)} chars):\n```\n{new}\n```\n")


if __name__ == "__main__":
    main()
