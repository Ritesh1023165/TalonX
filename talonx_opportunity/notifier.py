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

Telegram delivery (2026-09-28, ``LAB_DELIVERY_POLICY_V1`` in ``lab_delivery.py``, selected by TALONX_LAB_DELIVERY,
default V1; ``LEGACY`` restores one message per SELECTED decision): AFTER the unchanged V1 decision, each event gets
``lab_route`` IMMEDIATE (individual message) / DIGEST (counted in the next 30-min digest) / NULL (not delivered). The
decision, budget, reserve and ``surfaced`` bookkeeping are identical in both modes.
"""
from __future__ import annotations

import os
import sqlite3
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from functools import lru_cache
from pathlib import Path

from talonx_opportunity.config import LAB_NOTIFY_POLICY_V1, NotificationPolicy
from talonx_opportunity.phases import AFTER_HOURS, OVERNIGHT, PREMARKET, REGULAR, trading_window

# Named, closed-list live overrides (selected per process via TALONX_OPP_NOTIFY_POLICY; unknown name -> refuse to
# start). Each is its own version + fingerprint, so starting one is a forced ROUTING_FIX boundary. 2026-09-25: the
# 25 NEW budget was exhausted during PREMARKET; +15 slots usable ONLY by BULLISH/BEARISH (WATCH stays 40-25 = 15).
# Counters are never reset: budget use is read from durable decisions, and decided events are never re-evaluated.
@dataclass(frozen=True)
class PhaseReservedPolicy(NotificationPolicy):
    """Delivery reserve per later phase: a NEW setup surfacing from phase-P DATA is selected only if the NEW budget left
    AFTER it still covers ``later_phase_reserve[P]`` (the capacity kept for phases that have not begun). Unused
    capacity rolls forward automatically; an earlier phase can never consume a later phase's reserve.

    P is the event's causal DATA_PHASE (``data_phase``), not the wall-clock phase it was processed in: with the SIP
    delay the first ~16 min after a transition still carry previous-phase data (2026-09-25: three REGULAR-data setups
    processed at 20:01Z consumed all three AFTER_HOURS slots)."""
    later_phase_reserve: tuple[tuple[str, int], ...] = ()


NOTIFY_POLICY_OVERRIDES: dict[str, NotificationPolicy] = {
    "LAB_NOTIFY_POLICY_V1_LIVE_OVERRIDE_20260925": NotificationPolicy(
        version="LAB_NOTIFY_POLICY_V1_LIVE_OVERRIDE_20260925", total_new_per_window=40, setup_reserved=25),
    # 2026-09-25 second live ROUTING_FIX: of the 15 extra setup slots, PREMARKET may use at most 5 (40-25-10), REGULAR
    # keeps >=7 and AFTER_HOURS >=3 until they begin. WATCH unchanged (40-25 = 15).
    "LAB_NOTIFY_POLICY_V1_PHASE_RESERVED_20260925": PhaseReservedPolicy(
        version="LAB_NOTIFY_POLICY_V1_PHASE_RESERVED_20260925", total_new_per_window=40, setup_reserved=25,
        later_phase_reserve=(("OVERNIGHT", 10), ("PREMARKET", 10), ("REGULAR", 3), ("AFTER_HOURS", 0))),
    # 2026-09-25 third live ROUTING_FIX: the market-open burst exhausted REGULAR at 13:51Z; total 75 for FUTURE
    # REGULAR setups (setup_reserved 60 keeps WATCH at 75-60 = 15), AFTER_HOURS still keeps its last 3.
    "LAB_NOTIFY_POLICY_V1_REGULAR_EXT_20260925": PhaseReservedPolicy(
        version="LAB_NOTIFY_POLICY_V1_REGULAR_EXT_20260925", total_new_per_window=75, setup_reserved=60,
        later_phase_reserve=(("OVERNIGHT", 10), ("PREMARKET", 10), ("REGULAR", 3), ("AFTER_HOURS", 0))),
}


# reserve accounting basis (recorded in the notifier config fingerprint)
RESERVE_PHASE_BASIS = "CAUSAL_DATA_PHASE_V1"
DATA_PHASE_ORDER = (OVERNIGHT, PREMARKET, REGULAR, AFTER_HOURS)


@lru_cache(maxsize=64)
def _window(window_id: str):
    return trading_window(date.fromisoformat(window_id))


def data_phase(ev: dict) -> str | None:
    """Causal DATA_PHASE of an event: the phase of the newest bar it could have used (``data_as_of - 1 min``) in the
    event's own trading window -- the engine convention shared with promotion and the outcome tracker. None when it
    cannot be determined (no data time / unknown window / outside the window's phases)."""
    try:
        asof = datetime.fromisoformat(ev["data_as_of_utc"])
        ph = _window(ev["window_id"]).phase_at(asof - timedelta(minutes=1))
    except Exception:  # noqa: BLE001 -- missing/invalid data time or window: undeterminable, caller fails closed
        return None
    return ph if ph in DATA_PHASE_ORDER else None


def reserve_for(policy, ev: dict) -> tuple[int, str]:
    """(capacity that must remain after this surfacing, basis). Unknown data phase fails CLOSED: the event is treated as
    the earliest phase up to its processing phase, i.e. it can never consume any reserve kept for a later phase."""
    reserves = dict(getattr(policy, "later_phase_reserve", ()) or ())
    dph = data_phase(ev)
    if dph is not None:
        return reserves.get(dph, 0), dph
    upto = DATA_PHASE_ORDER[:DATA_PHASE_ORDER.index(ev["phase"]) + 1] if ev["phase"] in DATA_PHASE_ORDER \
        else DATA_PHASE_ORDER
    return max((reserves.get(ph, 0) for ph in upto), default=0), "UNKNOWN"


def selected_policy(env=None) -> NotificationPolicy:
    name = (env if env is not None else os.environ).get("TALONX_OPP_NOTIFY_POLICY", "").strip()
    if not name or name == LAB_NOTIFY_POLICY_V1.version:
        return LAB_NOTIFY_POLICY_V1
    if name not in NOTIFY_POLICY_OVERRIDES:
        raise SystemExit(f"unknown TALONX_OPP_NOTIFY_POLICY {name!r}; allowed: {sorted(NOTIFY_POLICY_OVERRIDES)}")
    return NOTIFY_POLICY_OVERRIDES[name]
from talonx_opportunity.db import PROTECTED_DB_NAMES, connect, iso, j, root_dir, unj, utcnow
from talonx_opportunity.store import OpportunityStore, opportunity_db

from talonx_opportunity import lab_delivery as LD

RESEARCH_FOOTER = "Research alert only. Not a V2 trade event. Paper execution not started."
LAB_DELIVERY_ENV = "TALONX_LAB_DELIVERY"
# additive decision columns (2026-09-28 Lab delivery policy); rows decided before keep NULL (= legacy: SELECTED sent)
ROUTE_COLUMNS = (("lab_route", "TEXT"), ("info_class", "TEXT"), ("route_reason", "TEXT"), ("digest_id", "TEXT"),
                 ("gap_pct", "REAL"), ("lab_policy_version", "TEXT"))
PRODUCER = "talonx_opportunity.notifier"
SETUPS = ("BULLISH", "BEARISH")

SCHEMA = """
CREATE TABLE IF NOT EXISTS cursor (name TEXT PRIMARY KEY, last_seq INTEGER, updated_utc TEXT);
CREATE TABLE IF NOT EXISTS decisions (
    event_id TEXT PRIMARY KEY, seq INTEGER, candidate_id TEXT, window_id TEXT, symbol TEXT, event_type TEXT,
    classification TEXT, phase TEXT, priority INTEGER, decision TEXT, reason TEXT, counted_new INTEGER,
    budget_json TEXT, policy_version TEXT, policy_fp TEXT, decided_utc TEXT, routed TEXT, outbox_event_id TEXT,
    delivery_state TEXT, delivery_updated_utc TEXT, data_phase TEXT);
CREATE INDEX IF NOT EXISTS ix_dec_window ON decisions(window_id);
CREATE INDEX IF NOT EXISTS ix_dec_cand ON decisions(candidate_id);
CREATE TABLE IF NOT EXISTS digests (digest_id TEXT PRIMARY KEY, window_id TEXT, period_start_utc TEXT,
    period_end_utc TEXT, created_utc TEXT, n_events INTEGER, counts_json TEXT, payload_text TEXT, routed TEXT,
    outbox_event_id TEXT, delivery_state TEXT, delivery_updated_utc TEXT, policy_version TEXT, policy_fp TEXT);
CREATE TABLE IF NOT EXISTS surfaced (candidate_id TEXT PRIMARY KEY, window_id TEXT, first_surfaced_utc TEXT,
    event_id TEXT);
"""


def lab_delivery_from_env(env=None):
    """The Lab delivery policy for this process: V1 (default) or LEGACY (None = one message per SELECTED decision)."""
    name = str((env if env is not None else os.environ).get(LAB_DELIVERY_ENV, "V1")).strip().upper() or "V1"
    if name == "LEGACY":
        return None
    if name != "V1":
        raise SystemExit(f"{LAB_DELIVERY_ENV}={name!r}: allowed V1 | LEGACY")
    return LD.LAB_DELIVERY_POLICY_V1


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
                 drain=None, batch: int = 2000, lab_delivery: LD.LabDeliveryPolicy | None = None, clock=None):
        self.root, self.policy, self.deliver, self.batch = root, policy, deliver, batch
        self.lab_delivery, self.clock = lab_delivery, clock or utcnow
        self.con = connect(notification_db(root), schema=SCHEMA)
        cols = {r[1] for r in self.con.execute("PRAGMA table_info(decisions)")}
        if "data_phase" not in cols:                     # additive migration (2026-09-26); older rows keep NULL
            with self.con:
                self.con.execute("ALTER TABLE decisions ADD COLUMN data_phase TEXT")
        for col, typ in ROUTE_COLUMNS:                   # additive migration (2026-09-28); older rows keep NULL
            if col not in cols:
                with self.con:
                    self.con.execute(f"ALTER TABLE decisions ADD COLUMN {col} {typ}")
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
            reserve, basis = reserve_for(p, ev)
            if cls != "WATCH" and p.total_new_per_window - used - 1 < reserve:
                where = basis if basis == ev["phase"] else (
                    f"{basis} data (processed in {ev['phase']})" if basis != "UNKNOWN"
                    else f"UNKNOWN data phase, fail-closed (processed in {ev['phase']})")
                return ("BUDGET_RESERVED_LATER_PHASE", f"{used}/{p.total_new_per_window} used; {reserve} kept for "
                        f"phases after {where}", 0)
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
                    lroute = info = rreason = None
                    if self.lab_delivery is not None:
                        lroute, info, rreason, payload = self._route(ev, dec, opp)
                        if lroute == LD.IMMEDIATE:
                            if self.deliver:
                                obid = ev["event_id"]
                                self._enqueue(obid, f"OPPORTUNITY_RESEARCH_{ev['event_type']}", payload, ev,
                                              datetime.fromisoformat(ev["at_utc"]))
                                routed = "ENQUEUED_RESEARCH"
                            else:
                                routed = "RECORDED_NOT_DELIVERED"
                        elif lroute == LD.DIGEST:
                            routed = "DIGEST"
                        if dec == "SELECTED":
                            selected += 1
                    elif dec == "SELECTED":
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
                            "INSERT OR IGNORE INTO decisions (event_id, seq, candidate_id, window_id, symbol, "
                            "event_type, classification, phase, priority, decision, reason, counted_new, budget_json, "
                            "policy_version, policy_fp, decided_utc, routed, outbox_event_id, delivery_state, "
                            "delivery_updated_utc, data_phase, lab_route, info_class, route_reason, gap_pct, "
                            "lab_policy_version) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                            (ev["event_id"], ev["seq"], ev["candidate_id"], ev["window_id"], ev["symbol"],
                             ev["event_type"], ev.get("classification"), ev["phase"], _priority(ev)[0], dec, why,
                             counted, j({"used_new": used + counted, "used_watch": used_w + (
                                 counted if ev.get("classification") == "WATCH" else 0)}),
                             self.policy.version, self.policy.fingerprint(), iso(self.clock()), routed, obid,
                             "PENDING" if obid else None, None, data_phase(ev), lroute, info, rreason,
                             ev.get("gap_pct"), self.lab_delivery.version if self.lab_delivery else None))
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
        digest = self.digest() if self.lab_delivery is not None else None
        drained = self.drain()
        synced = self.sync()
        self.last = {"cursor": self.cursor(), "processed": processed, "selected": selected, "drain": drained,
                     "delivery": synced, "deliver": self.deliver, "policy": self.policy.version,
                     "after_hours_reserve": self.reserve_status(),
                     "lab_delivery": (self.lab_delivery.version if self.lab_delivery else "LEGACY"),
                     "lab_routes": self.route_status(), "digest": digest}
        return 15.0

    # -- Lab delivery routing (LAB_DELIVERY_POLICY_V1) ------------------------------------------------------------------
    def _enqueue(self, obid: str, event_type: str, payload: str, ev: dict | None, at: datetime,
                 provenance: dict | None = None) -> None:
        from talonx_ops.notify import RESEARCH
        self.outbox.enqueue(event_id=obid, destination=RESEARCH, event_type=event_type, producer=PRODUCER,
                            dedup_key=obid, payload_text=payload,
                            provenance=provenance or {"candidate_id": ev["candidate_id"], "symbol": ev["symbol"],
                                                      "lane": "OPPORTUNITY_RESEARCH", "not_a_trade_event": True},
                            deliver_by_utc=(at + timedelta(minutes=self.policy.deliver_by_minutes)).isoformat())

    def setup_sent(self, cid: str) -> bool:
        """A BULLISH/BEARISH surfacing (NEW or UPGRADE) of this candidate was delivered individually to Lab."""
        return self.con.execute(
            "SELECT 1 FROM decisions WHERE candidate_id=? AND decision='SELECTED' AND event_type IN ('NEW','UPGRADE') "
            "AND classification IN ('BULLISH','BEARISH') AND COALESCE(lab_route,'IMMEDIATE')='IMMEDIATE' LIMIT 1",
            (cid,)).fetchone() is not None

    def last_shown_gap(self, cid: str, opp) -> float | None:
        """Signed gap of the last message the reader saw individually for this candidate (legacy rows: SELECTED)."""
        r = self.con.execute(
            "SELECT event_id, gap_pct FROM decisions WHERE candidate_id=? AND (lab_route='IMMEDIATE' OR "
            "(lab_route IS NULL AND decision='SELECTED')) ORDER BY seq DESC LIMIT 1", (cid,)).fetchone()
        if r is None:
            return None
        if r["gap_pct"] is not None:
            return float(r["gap_pct"])
        e = opp.con.execute("SELECT gap_pct FROM candidate_events WHERE event_id=?", (r["event_id"],)).fetchone()
        return float(e[0]) if e and e[0] is not None else None

    def signal_promotion(self, cid: str) -> dict | None:
        """The candidate's PROMOTED_SIGNAL row in promotion.db (read-only), or None. Missing/unreadable -> None."""
        p = root_dir(self.root) / "promotion.db"          # promotion's store, read-only (no import of promotion.py)
        if not p.exists():
            return None
        try:
            c = sqlite3.connect(f"file:{p}?mode=ro", uri=True, timeout=5)
            try:
                r = c.execute("SELECT window_id, decision_utc FROM promotions WHERE candidate_id=? "
                              "AND state='PROMOTED_SIGNAL'", (cid,)).fetchone()
            finally:
                c.close()
        except sqlite3.Error:
            return None
        return {"window_id": r[0], "decision_utc": r[1]} if r else None

    def signal_open(self, ev: dict, promo: dict | None) -> bool:
        """The promoted paper opportunity's SAME_DAY horizon is still open at this event (before its window's close)."""
        if not promo or not promo.get("decision_utc"):
            return False
        at = LD.to_utc(ev["at_utc"])
        try:
            close = _window(promo["window_id"]).close_utc
        except Exception:  # noqa: BLE001 -- unknown window: the conservative side is "not open" (digest, as before)
            return False
        return LD.to_utc(promo["decision_utc"]) <= at < close

    def _route(self, ev: dict, dec: str, opp) -> tuple:
        promo = self.signal_promotion(ev["candidate_id"]) if ev["event_type"] == "INVALIDATED" else None
        sent = self.setup_sent(ev["candidate_id"])
        last = self.last_shown_gap(ev["candidate_id"], opp) if ev["event_type"] == "MATERIAL_UPDATE" else None
        r, info, why = LD.route(ev, dec, setup_sent=sent, last_shown_abs_gap=None if last is None else abs(last),
                                signal_open=self.signal_open(ev, promo))
        payload = None
        if r == LD.IMMEDIATE:
            payload = LD.render_lab(ev, opp.candidate(ev["candidate_id"]), why, last_shown_gap=last,
                                    signal_sent_utc=(promo or {}).get("decision_utc"))
        return r, info, why, payload

    def digest(self, now: datetime | None = None) -> dict | None:
        """One Lab digest for every DIGEST-routed decision decided before the current 30-min bucket (built once >= the
        policy's minimum are pending or the oldest has waited the maximum hold). Crash-safe: the
        digest row + the decision->digest links are written in ONE transaction first (a decision belongs to at most
        one digest), then the digest is enqueued under its deterministic id (outbox enqueue is idempotent)."""
        pol = self.lab_delivery
        now = now or self.clock()
        cut = LD.digest_bucket(now, pol.digest_interval_s)
        rows = [dict(r) for r in self.con.execute(
            "SELECT * FROM decisions WHERE lab_route='DIGEST' AND digest_id IS NULL AND decided_utc < ? ORDER BY seq",
            (iso(cut),))]
        if rows and len(rows) < pol.digest_min_events and                 (cut - LD.to_utc(rows[0]["decided_utc"])).total_seconds() < pol.digest_max_hold_s:
            rows = []                                    # too few to be worth a message yet: hold (state stays in DB)
        if rows:
            start = LD.digest_bucket(LD.to_utc(rows[0]["decided_utc"]), pol.digest_interval_s)
            did = f"LAB_DIGEST:{iso(cut)}"
            counts: dict[str, int] = {}
            for r in rows:
                counts[r["route_reason"]] = counts.get(r["route_reason"], 0) + 1
            immediate = {"BULLISH": 0, "BEARISH": 0, "INVALIDATED": 0}
            for r in self.con.execute(
                    "SELECT event_type, classification, COUNT(*) AS n FROM decisions WHERE lab_route='IMMEDIATE' AND "
                    "decided_utc >= ? AND decided_utc < ? GROUP BY 1, 2", (iso(start), iso(cut))).fetchall():
                if r["event_type"] in ("NEW", "UPGRADE") and r["classification"] in SETUPS:
                    immediate[r["classification"]] += r["n"]
                elif r["event_type"] == "INVALIDATED":
                    immediate["INVALIDATED"] += r["n"]
            sig = sum(1 for r in rows if r["event_type"] == "INVALIDATED" and self.signal_promotion(r["candidate_id"]))
            payload = LD.render_digest(phase=rows[-1]["phase"], start=start, end=cut, counts=counts,
                                       active=self._active_setups(), immediate=immediate, signal_affected=sig)
            with self.con:
                self.con.execute("INSERT OR IGNORE INTO digests (digest_id, window_id, period_start_utc, "
                                 "period_end_utc, created_utc, n_events, counts_json, payload_text, routed, "
                                 "policy_version, policy_fp) VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                                 (did, rows[-1]["window_id"], iso(start), iso(cut), iso(now), len(rows), j(counts),
                                  payload, "ENQUEUED_RESEARCH" if self.deliver else "RECORDED_NOT_DELIVERED",
                                  pol.version, pol.fingerprint()))
                self.con.executemany("UPDATE decisions SET digest_id=? WHERE event_id=? AND digest_id IS NULL",
                                     [(did, r["event_id"]) for r in rows])
        enq = 0
        if self.deliver:
            for d in self.con.execute("SELECT * FROM digests WHERE outbox_event_id IS NULL AND "
                                      "routed='ENQUEUED_RESEARCH'").fetchall():
                self._enqueue(d["digest_id"], "OPPORTUNITY_RESEARCH_DIGEST", d["payload_text"], None,
                              LD.to_utc(d["created_utc"]),
                              provenance={"lane": "OPPORTUNITY_RESEARCH", "digest_id": d["digest_id"],
                                          "n_events": d["n_events"], "not_a_trade_event": True})
                with self.con:
                    self.con.execute("UPDATE digests SET outbox_event_id=?, delivery_state='PENDING' WHERE digest_id=?",
                                     (d["digest_id"], d["digest_id"]))
                enq += 1
        return {"built": bool(rows), "events": len(rows), "enqueued": enq}

    def _active_setups(self) -> dict[str, int]:
        if not opportunity_db(self.root).exists():
            return {}
        s = OpportunityStore(self.root, readonly=True)
        try:
            return {r[0]: r[1] for r in s.con.execute(
                "SELECT classification, COUNT(*) FROM candidates WHERE state IN ('BULLISH_SETUP','BEARISH_SETUP') "
                "GROUP BY 1")}
        finally:
            s.close()

    def route_status(self, window_id: str | None = None) -> dict:
        if window_id is None:
            r = self.con.execute("SELECT window_id FROM decisions ORDER BY seq DESC LIMIT 1").fetchone()
            window_id = r["window_id"] if r else None
        routes = dict(self.con.execute("SELECT lab_route, COUNT(*) FROM decisions WHERE window_id=? "
                                       "AND lab_route IS NOT NULL GROUP BY 1", (window_id,)).fetchall())
        dg = self.con.execute("SELECT COUNT(*), COALESCE(SUM(n_events),0) FROM digests WHERE window_id=?",
                              (window_id,)).fetchone()
        return {"window_id": window_id, "routes": routes, "digests": dg[0], "digested_events": dg[1]}

    def reserve_status(self, window_id: str | None = None) -> dict:
        """AFTER_HOURS reserve accounting for one window (default: the latest decided window). Counts only rows decided
        with the data-phase basis (data_phase recorded); earlier rows are never re-interpreted."""
        reserves = dict(getattr(self.policy, "later_phase_reserve", ()) or ())
        if not reserves:
            return {}
        if window_id is None:
            r = self.con.execute("SELECT window_id FROM decisions ORDER BY seq DESC LIMIT 1").fetchone()
            window_id = r["window_id"] if r else None
        if window_id is None:
            return {}
        total = reserves.get(REGULAR, 0)             # capacity kept after REGULAR data = the AFTER_HOURS reserve
        used, _ = self._used(window_id)
        q = ("SELECT decision, counted_new, classification FROM decisions WHERE window_id=? AND data_phase=? "
             "AND phase=?")
        true_ah = self.con.execute(q, (window_id, AFTER_HOURS, AFTER_HOURS)).fetchall()
        reg_after = self.con.execute(q, (window_id, REGULAR, AFTER_HOURS)).fetchall()
        setups = [r for r in true_ah if r["classification"] in SETUPS]
        return {"window_id": window_id, "basis": RESERVE_PHASE_BASIS, "AH_RESERVED_TOTAL": total,
                "AH_RESERVED_USED_BY_TRUE_AH": sum(r["counted_new"] or 0 for r in true_ah),
                "AH_RESERVED_REMAINING": max(0, min(total, self.policy.total_new_per_window - used)),
                "REGULAR_DATA_AFTER_CLOSE": {d: sum(1 for r in reg_after if r["decision"] == d)
                                             for d in sorted({r["decision"] for r in reg_after})},
                "REGULAR_DATA_AFTER_CLOSE_COUNTED_NEW": sum(r["counted_new"] or 0 for r in reg_after),
                "TRUE_AH_SENT": sum(1 for r in setups if r["decision"] == "SELECTED" and r["counted_new"]),
                "TRUE_AH_HELD": sum(1 for r in setups if r["decision"].startswith("BUDGET"))}

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
            for r in self.con.execute("SELECT digest_id, outbox_event_id, delivery_state FROM digests "
                                      "WHERE outbox_event_id IS NOT NULL").fetchall():
                st = states.get(r["outbox_event_id"], r["delivery_state"])
                if st != r["delivery_state"]:
                    self.con.execute("UPDATE digests SET delivery_state=?, delivery_updated_utc=? WHERE digest_id=?",
                                     (st, iso(), r["digest_id"]))
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
    lab = lab_delivery_from_env()
    n = Notifier(root=root, policy=policy, deliver=deliver, lab_delivery=lab)
    fps = {"LAB_NOTIFY_POLICY": policy.fingerprint(), "deliver": "1" if deliver else "0",
           "reserve_phase_basis": RESERVE_PHASE_BASIS}
    if lab is not None:                  # LEGACY keeps the exact pre-2026-09-28 fingerprint set (rollback = no change)
        fps["LAB_DELIVERY_POLICY"] = lab.fingerprint()
    run_component("notifier", tick=n.tick, root=root, detail=n.detail, config_fps=fps)
    return 0
