"""Deterministic replay of the 2026-09-25 REGULAR -> AFTER_HOURS transition through the FIXED notifier (read-only on the
live stores: both DBs are copied with the sqlite backup API into a scratch root; delivery OFF).

State at the boundary = the live notification.db with every decision processed at/after 20:00Z removed and the cursor
reset to the last pre-20:00Z event, so the replay starts from exactly yesterday's 72/75 budget. Then every event from
20:00Z to the end of the window is decided by the fixed policy (LAB_NOTIFY_POLICY_V1_REGULAR_EXT_20260925, as live).
usage: python ah_replay.py <scratch_dir>  -> prints JSON
"""
from __future__ import annotations

import json
import sqlite3
import sys
from collections import Counter
from pathlib import Path

REPO = Path(r"C:\workspace\TalonX")
sys.path.insert(0, str(REPO))
from talonx_opportunity.notifier import NOTIFY_POLICY_OVERRIDES, Notifier  # noqa: E402

LIVE = REPO / "results" / "opportunity"
WID, CUT = "2026-09-25", "2026-09-25T20:00:00"
POLICY = NOTIFY_POLICY_OVERRIDES["LAB_NOTIFY_POLICY_V1_REGULAR_EXT_20260925"]


def copy(name, dst):
    src = sqlite3.connect(f"file:{LIVE / name}?mode=ro", uri=True)
    out = sqlite3.connect(dst / name)
    src.backup(out)
    out.close()
    src.close()


def main(scratch):
    d = Path(scratch)
    d.mkdir(parents=True, exist_ok=True)
    for f in d.glob("*.db*"):
        f.unlink()
    copy("opportunity.db", d)
    copy("notification.db", d)
    o = sqlite3.connect(d / "opportunity.db")
    last_pre = o.execute("SELECT MAX(seq) FROM candidate_events WHERE window_id=? AND at_utc < ?", (WID, CUT)).fetchone()[0]
    end = o.execute("SELECT MAX(seq) FROM candidate_events WHERE window_id=?", (WID,)).fetchone()[0]
    # only this window's events are replayed: drop later windows from the scratch copy (none decided for 09-25)
    o.execute("DELETE FROM candidate_events WHERE seq > ?", (end,))
    o.commit()
    o.close()
    n0 = sqlite3.connect(d / "notification.db")
    n0.row_factory = sqlite3.Row
    live_after = {r["event_id"]: dict(r) for r in n0.execute("SELECT * FROM decisions WHERE seq > ?", (last_pre,))}
    n0.execute("DELETE FROM decisions WHERE seq > ?", (last_pre,))
    n0.execute("DELETE FROM surfaced WHERE event_id NOT IN (SELECT event_id FROM decisions)")
    n0.execute("INSERT OR REPLACE INTO cursor VALUES ('events', ?, 'replay')", (last_pre,))
    n0.commit()
    used0 = n0.execute("SELECT COUNT(*) FROM decisions WHERE window_id=? AND decision='SELECTED' AND counted_new=1",
                       (WID,)).fetchone()[0]
    n0.close()
    n = Notifier(root=d, policy=POLICY, deliver=False)
    while n.cursor() < end:
        n.tick()
    new = {r["event_id"]: dict(r) for r in n.con.execute("SELECT * FROM decisions WHERE seq > ?", (last_pre,))}
    assert set(new) == set(live_after), "replayed event set differs from live"
    changed = [{"symbol": new[e]["symbol"], "event_type": new[e]["event_type"], "cls": new[e]["classification"],
                "data_phase": new[e]["data_phase"], "live": live_after[e]["decision"], "fixed": new[e]["decision"],
                "live_counted": live_after[e]["counted_new"], "fixed_counted": new[e]["counted_new"],
                "decided_live": live_after[e]["decided_utc"][11:19], "reason_fixed": new[e]["reason"]}
               for e in sorted(new, key=lambda e: new[e]["seq"])
               if (new[e]["decision"], new[e]["counted_new"]) != (live_after[e]["decision"], live_after[e]["counted_new"])]
    counted = [dict(symbol=r["symbol"], data_phase=r["data_phase"], cls=r["classification"], seq=r["seq"])
               for r in sorted(new.values(), key=lambda r: r["seq"]) if r["counted_new"]]
    out = {"window": WID, "boundary_seq": last_pre, "end_seq": end, "used_new_at_boundary": used0,
           "events_replayed": len(new), "policy": POLICY.version,
           "live_counted_after_close": [dict(symbol=r["symbol"], cls=r["classification"]) for r in
                                        sorted(live_after.values(), key=lambda r: r["seq"]) if r["counted_new"]],
           "fixed_counted_after_close": counted,
           "fixed_decisions_by_data_phase": Counter(f"{r['data_phase']}|{r['decision']}" for r in new.values()),
           "decisions_changed": changed, "reserve_status": n.reserve_status(WID)}
    print(json.dumps(out, indent=1, default=str))


if __name__ == "__main__":
    main(sys.argv[1])
