"""
NOTIFICATION_WORKER -- attention routing ONLY (REQ S14-02). Single writer of notification.db and of its own
RESEARCH outbox. It reads candidate_events (opportunity.db, read-only) through a durable cursor and NEVER writes
the candidate store: exhausting the budget, disabling Lab or crashing this worker cannot change detection,
persistence or lifecycle.

Policy (``LAB_NOTIFY_POLICY_V1``, versioned + fingerprinted, configurable; values are not evidence-derived):
  * budget per trading window for NEW surfacing: ``total_new_per_window`` (25 = V1's total, for comparison);
    WATCH may use at most ``total - setup_reserved`` so later BULLISH/BEARISH setups always stay deliverable;
  * priority inside one discovery evaluation: BULLISH/BEARISH before WATCH, then score, then symbol;
  * WATCH->SETUP upgrade of a surfaced candidate: delivered (not budgeted, as in V1); of an unsurfaced candidate:
    treated as a NEW setup surfacing (setup budget);
  * MATERIAL_UPDATE / INVALIDATED: delivered only if the candidate was surfaced (V1 frozen deltas decide whether
    a MATERIAL_UPDATE exists at all);
  * EXPIRED / REFERENCE_ROLLED: never notified (bookkeeping).
Every decision is persisted (SELECTED / BUDGET_EXHAUSTED_* / NOT_SURFACED_PARENT / POLICY_SILENT / PHASE_DISABLED)
together with the real outbox delivery state (ENQUEUED is not SENT).
"""
from __future__ import annotations

import os
from datetime import datetime, timedelta
from pathlib import Path

from talonx_opportunity.config import LAB_NOTIFY_POLICY_V1, NotificationPolicy

# Named, closed-list live overrides (selected per process via TALONX_OPP_NOTIFY_POLICY; unknown name -> refuse to
# start). Each is its own version + fingerprint, so starting one is a forced ROUTING_FIX boundary. 2026-09-25: the
# 25 NEW budget was exhausted during PREMARKET; +15 slots usable ONLY by BULLISH/BEARISH (WATCH stays 40-25 = 15).
# Counters are never reset: budget use is read from durable decisions, and decided events are never re-evaluated.
NOTIFY_POLICY_OVERRIDES: dict[str, NotificationPolicy] = {
    "LAB_NOTIFY_POLICY_V1_LIVE_OVERRIDE_20260925": NotificationPolicy(
        version="LAB_NOTIFY_POLICY_V1_LIVE_OVERRIDE_20260925", total_new_per_window=40, setup_reserved=25),
}


def selected_policy(env=None) -> NotificationPolicy:
    name = (env if env is not None else os.environ).get("TALONX_OPP_NOTIFY_POLICY", "").strip()
    if not name or name == LAB_NOTIFY_POLICY_V1.version:
        return LAB_NOTIFY_POLICY_V1
    if name not in NOTIFY_POLICY_OVERRIDES:
        raise SystemExit(f"unknown TALONX_OPP_NOTIFY_POLICY {name!r}; allowed: {sorted(NOTIFY_POLICY_OVERRIDES)}")
    return NOTIFY_POLICY_OVERRIDES[name]
from talonx_opportunity.db import PROTECTED_DB_NAMES, connect, iso, j, root_dir, unj, utcnow
from talonx_opportunity.store import OpportunityStore, opportunity_db

RESEARCH_FOOTER = "Research alert only. Not a V2 trade event. Paper execution not started."
PRODUCER = "talonx_opportunity.notifier"
SETUPS = ("BULLISH", "BEARISH")

SCHEMA = """
CREATE TABLE IF NOT EXISTS cursor (name TEXT PRIMARY KEY, last_seq INTEGER, updated_utc TEXT);
CREATE TABLE IF NOT EXISTS decisions (
    event_id TEXT PRIMARY KEY, seq INTEGER, candidate_id TEXT, window_id TEXT, symbol TEXT, event_type TEXT,
    classification TEXT, phase TEXT, priority INTEGER, decision TEXT, reason TEXT, counted_new INTEGER,
    budget_json TEXT, policy_version TEXT, policy_fp TEXT, decided_utc TEXT, routed TEXT, outbox_event_id TEXT,
    delivery_state TEXT, delivery_updated_utc TEXT);
CREATE INDEX IF NOT EXISTS ix_dec_window ON decisions(window_id);
CREATE TABLE IF NOT EXISTS surfaced (candidate_id TEXT PRIMARY KEY, window_id TEXT, first_surfaced_utc TEXT,
    event_id TEXT);
"""


def notification_db(root=None) -> Path:
    return root_dir(root) / "notification.db"


def outbox_path(root=None) -> Path:
    p = root_dir(root) / "opportunity_research_notifications.db"
    assert p.name not in PROTECTED_DB_NAMES
    return p


def render(ev: dict, cand: dict | None) -> str:
    f = unj(ev.get("features_json"), {}) or {}
    sc = unj(ev.get("score_json"), {}) or {}
    typ = ev["event_type"]
    head = f"[OPPORTUNITY RESEARCH] {ev['symbol']} — {ev['classification']}"
    head += "" if typ == "NEW" else f" ({typ.replace('_', ' ')})"
    lines = [head + f" · {ev['phase']}"]
    if f:
        lines.append(f"Move: {f['gap_pct']:+.2f}% vs previous close {f['prev_close']:.4g} (last {f['last_price']:.4g})")
        lines.append(f"Session-to-date volume: {f['pm_volume']:,.0f} sh (${f['pm_dollars']:,.0f}), "
                     f"{f['activity_adv_fraction'] * 100:.1f}% of 20d ADV")
    if ev.get("catalyst"):
        lines.append(f"Catalyst: {ev['catalyst']}")
    if sc:
        lines.append(f"Score: {sc['total']:.1f}/100")
    lines.append(f"Why: {ev.get('reason') or '-'}")
    prov = unj(ev.get("provenance_json"), {}) or {}
    asof = (ev.get("data_as_of_utc") or "")[11:16]
    scope = cand and cand.get("in_v2_scope")
    lines.append(f"Data: {prov.get('provider', 'alpaca')} {str(prov.get('feed', 'sip')).upper()} 1-min, "
                 f"{prov.get('delay_minutes', 15)}-min delayed, as of {asof} UTC · "
                 + ("in V2 39-name scope" if scope else "outside V2 scope"))
    lines.append(RESEARCH_FOOTER)
    return "\n".join(lines)


def _priority(ev: dict) -> tuple:
    cls, typ = ev.get("classification"), ev["event_type"]
    rank = 0 if cls in SETUPS and typ in ("NEW", "UPGRADE") else 1 if typ in ("UPGRADE", "MATERIAL_UPDATE",
                                                                             "INVALIDATED") else 2
    return (rank, -(ev.get("score") or 0.0), ev["symbol"])


class Notifier:
    def __init__(self, *, root=None, policy: NotificationPolicy = LAB_NOTIFY_POLICY_V1, deliver: bool = False,
                 drain=None, batch: int = 2000):
        self.root, self.policy, self.deliver, self.batch = root, policy, deliver, batch
        self.con = connect(notification_db(root), schema=SCHEMA)
        from talonx_ops.notify.outbox import NotifyStore
        self.outbox = NotifyStore(str(outbox_path(root)))
        self._drain = drain
        self.last: dict = {}

    # -- durable cursor --------------------------------------------------------------------------------------------
    def cursor(self) -> int:
        r = self.con.execute("SELECT last_seq FROM cursor WHERE name='events'").fetchone()
        return int(r["last_seq"]) if r else 0

    def _used(self, window_id: str) -> tuple[int, int]:
        r = self.con.execute("SELECT COUNT(*) AS n, SUM(classification='WATCH') AS w FROM decisions "
                             "WHERE window_id=? AND decision='SELECTED' AND counted_new=1", (window_id,)).fetchone()
        return int(r["n"] or 0), int(r["w"] or 0)

    def _surfaced(self, cid: str) -> bool:
        return self.con.execute("SELECT 1 FROM surfaced WHERE candidate_id=?", (cid,)).fetchone() is not None

    def decide(self, ev: dict) -> tuple[str, str, int]:
        """(decision, reason, counted_new) -- pure policy over durable notification state."""
        p, typ, cls = self.policy, ev["event_type"], ev.get("classification")
        if typ in ("EXPIRED", "REFERENCE_ROLLED"):
            return "POLICY_SILENT", f"{typ} is lifecycle bookkeeping", 0
        if ev["phase"] not in p.phases_enabled:
            return "PHASE_DISABLED", f"notifications disabled in {ev['phase']}", 0
        surfaced = self._surfaced(ev["candidate_id"])
        new_surface = typ == "NEW" or (typ == "UPGRADE" and not surfaced and p.upgrade_of_unsurfaced_counts_as_new)
        if new_surface:
            used, used_w = self._used(ev["window_id"])
            if used >= p.total_new_per_window:
                return "BUDGET_EXHAUSTED_TOTAL", f"{used}/{p.total_new_per_window} new surfacings used", 0
            if cls == "WATCH" and used_w >= p.total_new_per_window - p.setup_reserved:
                return ("BUDGET_EXHAUSTED_WATCH", f"WATCH share {used_w}/{p.total_new_per_window - p.setup_reserved} "
                        f"used; {p.setup_reserved} kept for BULLISH/BEARISH", 0)
            return "SELECTED", "new surfacing within budget", 1
        if typ == "UPGRADE":
            return "SELECTED", "upgrade of a surfaced candidate", 0
        if typ == "MATERIAL_UPDATE":
            if p.material_update_only_if_surfaced and not surfaced:
                return "NOT_SURFACED_PARENT", "material update of a never-surfaced candidate", 0
            return "SELECTED", "material update of a surfaced candidate", 0
        if typ == "INVALIDATED":
            if p.invalidated_only_if_surfaced and not surfaced:
                return "NOT_SURFACED_PARENT", "invalidation of a never-surfaced candidate", 0
            return "SELECTED", "invalidation of a surfaced candidate", 0
        return "POLICY_SILENT", f"unhandled event type {typ}", 0

    def tick(self) -> float:
        cur = self.cursor()
        opp = OpportunityStore(self.root, readonly=True) if opportunity_db(self.root).exists() else None
        processed = selected = 0
        if opp is not None:
            try:
                evs = opp.events_after(cur, limit=self.batch)
                # priority within one discovery evaluation (same at_utc); evaluations stay chronological
                evs.sort(key=lambda e: (e["at_utc"], _priority(e)))
                for ev in evs:
                    if self.con.execute("SELECT 1 FROM decisions WHERE event_id=?", (ev["event_id"],)).fetchone():
                        continue                     # idempotent re-processing after a restart
                    dec, why, counted = self.decide(ev)
                    routed, obid = None, None
                    if dec == "SELECTED":
                        cand = opp.candidate(ev["candidate_id"])
                        if self.deliver:
                            obid = ev["event_id"]
                            deliver_by = (datetime.fromisoformat(ev["at_utc"])
                                          + timedelta(minutes=self.policy.deliver_by_minutes)).isoformat()
                            from talonx_ops.notify import RESEARCH
                            self.outbox.enqueue(event_id=obid, destination=RESEARCH,
                                                event_type=f"OPPORTUNITY_RESEARCH_{ev['event_type']}",
                                                producer=PRODUCER, dedup_key=obid, payload_text=render(ev, cand),
                                                provenance={"candidate_id": ev["candidate_id"], "symbol": ev["symbol"],
                                                            "lane": "OPPORTUNITY_RESEARCH",
                                                            "not_a_trade_event": True},
                                                deliver_by_utc=deliver_by)
                            routed = "ENQUEUED_RESEARCH"
                        else:
                            routed = "RECORDED_NOT_DELIVERED"
                        selected += 1
                    used, used_w = self._used(ev["window_id"])
                    with self.con:
                        self.con.execute(
                            "INSERT OR IGNORE INTO decisions VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                            (ev["event_id"], ev["seq"], ev["candidate_id"], ev["window_id"], ev["symbol"],
                             ev["event_type"], ev.get("classification"), ev["phase"], _priority(ev)[0], dec, why,
                             counted, j({"used_new": used + counted, "used_watch": used_w + (
                                 counted if ev.get("classification") == "WATCH" else 0)}),
                             self.policy.version, self.policy.fingerprint(), iso(), routed, obid,
                             "PENDING" if obid else None, None))
                        if dec == "SELECTED":
                            self.con.execute("INSERT OR IGNORE INTO surfaced VALUES (?,?,?,?)",
                                             (ev["candidate_id"], ev["window_id"], iso(), ev["event_id"]))
                    processed += 1
                if evs:
                    # advance only after the whole batch is decided (events were re-ordered by priority)
                    with self.con:
                        self.con.execute("INSERT OR REPLACE INTO cursor VALUES ('events', ?, ?)",
                                         (max(e["seq"] for e in evs), iso()))
            finally:
                opp.close()
        drained = self.drain()
        synced = self.sync()
        self.last = {"cursor": self.cursor(), "processed": processed, "selected": selected, "drain": drained,
                     "delivery": synced, "deliver": self.deliver, "policy": self.policy.version}
        return 15.0

    def drain(self) -> dict | None:
        if not self.deliver:
            return None
        if self._drain is not None:
            return self._drain(self.outbox)
        from talonx_ops.notify import RESEARCH
        from talonx_ops.notify.worker import drain as _drain
        return _drain(self.outbox, destination=RESEARCH)

    def sync(self) -> dict:
        states = {r["event_id"]: r["state"] for r in self.outbox.all_outbox()}
        counts: dict[str, int] = {}
        with self.con:
            for r in self.con.execute("SELECT event_id, outbox_event_id, delivery_state FROM decisions "
                                      "WHERE outbox_event_id IS NOT NULL").fetchall():
                st = states.get(r["outbox_event_id"], r["delivery_state"])
                if st != r["delivery_state"]:
                    self.con.execute("UPDATE decisions SET delivery_state=?, delivery_updated_utc=? WHERE event_id=?",
                                     (st, iso(), r["event_id"]))
                counts[st] = counts.get(st, 0) + 1
        return counts

    def detail(self) -> dict:
        return dict(self.last)


def main(argv=None) -> int:
    from talonx_opportunity.runtime import run_component
    from talonx_premarket import __main__ as M
    M._env()
    root = os.environ.get("TALONX_OPP_ROOT")
    deliver = os.environ.get("TALONX_OPP_DELIVER", "0").strip() == "1"
    policy = selected_policy()
    n = Notifier(root=root, policy=policy, deliver=deliver)
    run_component("notifier", tick=n.tick, root=root, detail=n.detail,
                  config_fps={"LAB_NOTIFY_POLICY": policy.fingerprint(),
                              "deliver": "1" if deliver else "0"})
    return 0
