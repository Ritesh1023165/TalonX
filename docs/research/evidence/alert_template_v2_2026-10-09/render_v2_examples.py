"""LOCAL renders of RESEARCH_REVIEW_COMPACT_V2 (evidence only; nothing is sent, written or replayed).

UP: the real KKR review alert (2026-10-09), re-rendered from its generation-time records AS OF its original render
instant. DOWN / UNCHANGED: the SAME records with only ``gap_pct`` overridden -- SYNTHETIC, local, never sent; they show
formatting only (the promotion policy is long-only and this does not authorise bearish alerts).

usage: python render_v2_examples.py [DATA_ROOT] > EXAMPLES.md
"""
from __future__ import annotations

import json
import sqlite3
import sys
from datetime import date
from pathlib import Path

CODE = Path(__file__).resolve().parents[4]
ROOT = Path(sys.argv[1]) if len(sys.argv) > 1 else CODE
sys.path.insert(0, str(CODE))
from talonx_opportunity import promotion as P  # noqa: E402
from talonx_opportunity.phases import trading_window  # noqa: E402

OPP = ROOT / "results" / "opportunity"


def ro(p):
    c = sqlite3.connect(f"file:{p}?mode=ro", uri=True)
    c.row_factory = sqlite3.Row
    return c


def main():
    pc, op, ob = ro(OPP / "promotion.db"), ro(OPP / "opportunity.db"), ro(OPP / "promotion_signal_notifications.db")
    q = dict(pc.execute("SELECT * FROM promotions WHERE promotion_id='OPPORTUNITY_ENGINE:2026-10-09:KKR:GAP_UP'")
             .fetchone())
    o = ob.execute("SELECT payload_text, created_at_utc FROM ops_notification_outbox WHERE event_id=?",
                   (q["signal_event_id"],)).fetchone()
    ev = dict(op.execute("SELECT features_json, score_json, catalyst, provenance_json, at_utc FROM candidate_events "
                         "WHERE event_id=?", (q["event_id"],)).fetchone())
    base = {"event": ev, "close_utc": trading_window(date.fromisoformat(q["window_id"])).close_utc,
            "prior_delivery_date": None, "universe": "DTU_V3_TOP600"}
    now = P._ts(o["created_at_utc"])
    out = [f"# {P.REVIEW_TEMPLATE_VERSION}: local renders (not sent)", "",
           "## Delivered with V1 (KKR, 2026-10-09 12:55 ET)", "```", o["payload_text"], "```", ""]
    for label, gap in (("UP: real KKR record", None), ("DOWN: SYNTHETIC (gap_pct overridden to -3.18)", -3.18),
                       ("UNCHANGED: SYNTHETIC (gap_pct overridden to 0.0)", 0.0)):
        ctx = dict(base)
        if gap is not None:
            f = json.loads(ev["features_json"])
            f["gap_pct"] = gap
            ctx["event"] = {**ev, "features_json": json.dumps(f)}
        txt = P.render_review_compact(q, now, q["policy_version"], ctx)
        out += [f"## {label} ({len(txt)} chars)", "```", txt, "```", ""]
    out += ["## Last-resort fallback (render_review_minimal)", "```",
            P.render_review_minimal(q, q["policy_version"]), "```"]
    sys.stdout.reconfigure(encoding="utf-8")
    print("\n".join(out))


if __name__ == "__main__":
    main()
