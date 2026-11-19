"""Offline replay of one trading window's Lab notification decisions: LEGACY (one message per SELECTED decision) vs
LAB_DELIVERY_POLICY_V1 (IMMEDIATE + 30-min DIGEST). NOTHING is sent: deliver=True writes a TEMP outbox, the drain is a
no-op. Live DBs are copied with the SQLite backup API from read-only connections into a temp root.

Stepping: the window's events are released to the notifier minute by minute in the order and at the minute the LIVE
notifier decided them (notification.db decided_utc), so digest buckets fall where they would have live.
Validation: the LEGACY replay must reproduce the live decisions exactly (event_id, decision, counted_new, SELECTED set).

Signal: promotion eligibility is proven unchanged structurally (AST of every promotion.py definition except the
renderer is identical to BASE_SHA) and every live-sent Signal is re-rendered with the new format.
usage: python replay_lab_delivery.py [WINDOW_ID] [BASE_SHA] > out.json"""
from __future__ import annotations

import ast
import collections as C
import json
import shutil
import sqlite3
import subprocess
import sys
import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path

REPO = Path(__file__).resolve().parents[5]
sys.path.insert(0, str(REPO))
from talonx_opportunity import lab_delivery as LD  # noqa: E402
from talonx_opportunity import notifier as N  # noqa: E402
from talonx_opportunity import promotion as P  # noqa: E402
from talonx_opportunity import store as S  # noqa: E402
from talonx_opportunity.phases import trading_window  # noqa: E402

LIVE = REPO / "results" / "opportunity"
WID = sys.argv[1] if len(sys.argv) > 1 else "2026-09-28"
BASE = sys.argv[2] if len(sys.argv) > 2 else "6cfde8f"
SETUPS = ("BULLISH", "BEARISH")


def ro(p):
    c = sqlite3.connect(f"file:{p}?mode=ro", uri=True, timeout=30)
    c.row_factory = sqlite3.Row
    return c


def snapshot(src: Path, dst: Path):
    s, d = ro(src), sqlite3.connect(dst)
    s.backup(d)
    d.close()
    s.close()


def ts(s):
    return datetime.fromisoformat(s.replace("Z", "+00:00"))


class Clock:
    t = None

    def __call__(self):
        return self.t


def prepare(root: Path, live_dec: list[dict]):
    """Temp root = opportunity.db + promotion.db snapshots and a notification.db holding every decision BEFORE this
    window's first event (so budgets / surfaced parents from earlier windows are exactly the live ones)."""
    for name in ("opportunity.db", "promotion.db"):
        snapshot(LIVE / name, root / name)
    first_seq = min(d["seq"] for d in live_dec)
    n = sqlite3.connect(root / "notification.db")
    n.executescript(N.SCHEMA)
    src = ro(LIVE / "notification.db")
    cols = [r[1] for r in src.execute("PRAGMA table_info(decisions)")]
    for r in src.execute("SELECT * FROM decisions WHERE seq < ?", (first_seq,)):
        n.execute(f"INSERT INTO decisions ({','.join(cols)}) VALUES ({','.join('?' * len(cols))})", tuple(r))
    for r in src.execute("SELECT s.* FROM surfaced s JOIN decisions d ON d.event_id = s.event_id WHERE d.seq < ?",
                         (first_seq,)):
        n.execute("INSERT INTO surfaced VALUES (?,?,?,?)", tuple(r))
    n.execute("INSERT INTO cursor VALUES ('events', ?, ?)", (first_seq - 1, "replay"))
    n.commit()
    n.close()


def run(mode: str, live_dec: list[dict]) -> dict:
    tmp = Path(tempfile.mkdtemp(prefix=f"labreplay_{mode}_"))
    try:
        prepare(tmp, live_dec)
        clock = Clock()
        lab = None if mode == "LEGACY" else LD.LAB_DELIVERY_POLICY_V1
        nt = N.Notifier(root=tmp, policy=N.NOTIFY_POLICY_OVERRIDES["LAB_NOTIFY_POLICY_V1_REGULAR_EXT_20260925"],
                        deliver=True, drain=lambda store: {"sent": 0}, lab_delivery=lab, clock=clock)
        cap = {"seq": 0}
        orig = S.OpportunityStore.events_after
        S.OpportunityStore.events_after = lambda self, seq, limit=500: [e for e in orig(self, seq, limit)
                                                                         if e["seq"] <= cap["seq"]]
        try:
            by_min = C.defaultdict(int)
            for d in live_dec:
                m = d["decided_utc"][:16]
                by_min[m] = max(by_min[m], d["seq"])
            last = None
            for m in sorted(by_min):
                cap["seq"] = max(cap["seq"], by_min[m])
                clock.t = ts(m + ":59+00:00")
                nt.tick()
                last = clock.t
            end = last + timedelta(minutes=31)                     # flush the final digest bucket
            clock.t = end
            nt.tick()
        finally:
            S.OpportunityStore.events_after = orig
        dec = [dict(r) for r in nt.con.execute("SELECT * FROM decisions WHERE window_id=? ORDER BY seq", (WID,))]
        dig = [dict(r) for r in nt.con.execute("SELECT * FROM digests ORDER BY period_end_utc")]
        ob = [dict(r) for r in ro(N.outbox_path(tmp)).execute("SELECT event_id, event_type, destination, payload_text "
                                                                "FROM ops_notification_outbox")]
        return {"decisions": dec, "digests": dig, "outbox": ob}
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def independent_high_info(dec: list[dict], window_close: datetime) -> set[str]:
    """Spec section 4 HIGH-information events, computed WITHOUT lab_delivery.route: new/upgraded setups, invalidation
    of a setup previously sent to Lab, invalidation of a Signal-promoted candidate while its SAME_DAY horizon is open."""
    pr = ro(LIVE / "promotion.db")
    prom = {r["candidate_id"]: dict(r) for r in pr.execute("SELECT candidate_id, decision_utc, window_id FROM promotions "
                                                            "WHERE state='PROMOTED_SIGNAL'")}
    sent_setup: set[str] = set()
    live_n = ro(LIVE / "notification.db")
    first = min(d["seq"] for d in dec)
    for r in live_n.execute("SELECT candidate_id FROM decisions WHERE seq < ? AND decision='SELECTED' AND "
                            "event_type IN ('NEW','UPGRADE') AND classification IN ('BULLISH','BEARISH')", (first,)):
        sent_setup.add(r[0])
    opp = ro(LIVE / "opportunity.db")
    high = set()
    for d in dec:
        if d["decision"] == "SELECTED" and d["event_type"] in ("NEW", "UPGRADE") and d["classification"] in SETUPS:
            high.add(d["event_id"])
            sent_setup.add(d["candidate_id"])
        elif d["event_type"] == "INVALIDATED":
            at = ts(opp.execute("SELECT at_utc FROM candidate_events WHERE event_id=?", (d["event_id"],)).fetchone()[0])
            p = prom.get(d["candidate_id"])
            open_sig = p is not None and ts(p["decision_utc"]) <= at < trading_window(
                datetime.fromisoformat(p["window_id"]).date()).close_utc
            if (d["decision"] == "SELECTED" and d["candidate_id"] in sent_setup) or open_sig:
                high.add(d["event_id"])
    return high


def signal_structural_check() -> dict:
    old = subprocess.run(["git", "show", f"{BASE}:talonx_opportunity/promotion.py"], cwd=REPO, capture_output=True,
                         text=True, encoding="utf-8").stdout
    new = (REPO / "talonx_opportunity" / "promotion.py").read_text(encoding="utf-8")

    def defs(src):
        out = {}
        for node in ast.parse(src).body:
            name = getattr(node, "name", None) or (node.targets[0].id if isinstance(node, ast.Assign)
                                                   and isinstance(node.targets[0], ast.Name) else None)
            if name:
                out[name] = ast.dump(node)
        return out
    a, b = defs(old), defs(new)
    presentation = {"render", "_ref", "SIGNAL_FOOTER"}
    changed = sorted(k for k in set(a) | set(b) if a.get(k) != b.get(k))
    pr = ro(LIVE / "promotion.db")
    sg = ro(LIVE / "promotion_signal_notifications.db")
    sent = [r[0] for r in sg.execute("SELECT event_id FROM ops_notification_outbox WHERE created_at_utc LIKE ? AND "
                                     "state='SENT'", (WID + "%",))]
    rendered = 0
    for pid in sent:
        row = pr.execute("SELECT * FROM promotions WHERE promotion_id=?", (pid,)).fetchone()
        txt = P.render(dict(row))
        rendered += txt.startswith("🚨 TALONX SIGNAL — PAPER") and row["symbol"] in txt and "no order placed" in txt
    return {"base_sha": BASE, "changed_definitions": changed,
            "only_presentation_changed": set(changed) <= presentation,
            "PROMOTION_POLICY_fingerprint": P.PROMOTION_V1.fingerprint(),
            "CURRENT_SIGNAL_MESSAGES": len(sent), "NEW_SIGNAL_MESSAGES": rendered,
            "REPLAY_SIGNAL_COUNT_MATCH": "PASS" if set(changed) <= presentation and rendered == len(sent) else "FAIL",
            "sample_new_signal": P.render(dict(pr.execute("SELECT * FROM promotions WHERE promotion_id=?",
                                                          (sent[0],)).fetchone())) if sent else None}


def main():
    live = ro(LIVE / "notification.db")
    live_dec = [dict(r) for r in live.execute("SELECT * FROM decisions WHERE window_id=? ORDER BY seq", (WID,))]
    legacy, v1 = run("LEGACY", live_dec), run("V1", live_dec)
    key = lambda d: (d["event_id"], d["decision"], d["counted_new"])  # noqa: E731
    legacy_match = [key(d) for d in legacy["decisions"]] == [key(d) for d in live_dec]
    v1_same_decisions = [key(d) for d in v1["decisions"]] == [key(d) for d in live_dec]
    live_sel = [d for d in live_dec if d["decision"] == "SELECTED"]
    imm = [d for d in v1["decisions"] if d["lab_route"] == "IMMEDIATE"]
    dig = [d for d in v1["decisions"] if d["lab_route"] == "DIGEST"]
    high = independent_high_info(live_dec, None)
    imm_ids = {d["event_id"] for d in imm}
    old_n = len(legacy["outbox"])
    new_n = len(imm) + len(v1["digests"])
    by = C.Counter((d["info_class"], d["route_reason"]) for d in v1["decisions"] if d["lab_route"])
    # spec section 4 classes over the messages actually SENT today (live SELECTED)
    sent_class = C.Counter()
    v1_by_id = {d["event_id"]: d for d in v1["decisions"]}
    for d in live_sel:
        sent_class[v1_by_id[d["event_id"]]["info_class"]] += 1
    out = {
        "window_id": WID,
        "validation": {"LEGACY_REPLAY_REPRODUCES_LIVE_DECISIONS": legacy_match,
                       "LEGACY_REPLAY_MESSAGES": old_n, "LIVE_SELECTED": len(live_sel),
                       "V1_DECISIONS_IDENTICAL_TO_LIVE": v1_same_decisions},
        "LAB": {"CURRENT_LAB_MESSAGES": len(live_sel), "NEW_IMMEDIATE_LAB_MESSAGES": len(imm),
                "NEW_DIGEST_MESSAGES": len(v1["digests"]), "SUPPRESSED_LOW_INFO_MESSAGES": len(dig),
                "NEW_TOTAL_LAB_MESSAGES": new_n,
                "LAB_MESSAGE_REDUCTION_PERCENT": round(100 * (len(live_sel) - new_n) / len(live_sel), 1),
                "immediate_not_in_legacy (open-Signal invalidations never surfaced in Lab)":
                    sum(1 for d in imm if d["decision"] != "SELECTED"),
                "sent_today_by_info_class": dict(sent_class),
                "routes_by_class_reason": {f"{a}:{b}": v for (a, b), v in sorted(by.items())},
                "independent_high_info_events": len(high),
                "high_info_immediate": len(high & imm_ids),
                "REPLAY_HIGH_INFO_LAB_CAPTURE": "PASS" if high <= imm_ids else "FAIL",
                "high_info_missed": sorted(high - imm_ids)},
        "digests": [{"period": f"{d['period_start_utc'][11:16]}-{d['period_end_utc'][11:16]}Z", "n": d["n_events"],
                     "counts": json.loads(d["counts_json"])} for d in v1["digests"]],
        "sample_digest": v1["digests"][len(v1["digests"]) // 2]["payload_text"] if v1["digests"] else None,
        "sample_immediate": {r: next((o["payload_text"] for o in v1["outbox"] if o["event_id"] == d["event_id"]), None)
                             for r, d in {d["route_reason"]: d for d in imm}.items()},
        "destinations": sorted({o["destination"] for o in v1["outbox"]} | {o["destination"] for o in legacy["outbox"]}),
        "SIGNAL": signal_structural_check(),
        "_note": "digest 'Active setups' lines use the end-of-window candidate snapshot (display only; counts unaffected)",
    }
    print(json.dumps(out, indent=1, ensure_ascii=False, default=str))


if __name__ == "__main__":
    main()
