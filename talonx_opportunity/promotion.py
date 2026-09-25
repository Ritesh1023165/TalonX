"""
OPPORTUNITY PROMOTION -- Opportunity Engine setup -> PAPER opportunity (OPPORTUNITY_PROMOTION_V1, 2026-09-25).

A separate downstream component (own process ``python -m talonx_opportunity component promotion``, own store
``promotion.db``, own heartbeat). It reads the durable candidate store READ-ONLY through its own cursor and NEVER
writes discovery / lifecycle / notifier / V2 state. A crash here cannot affect discovery, Lab delivery or V2.

v1 contract (deliberately narrow; no new alpha threshold, no change to classification):
* only a candidate's FIRST setup surfacing after ``PROMOTION_START_UTC`` (event NEW or UPGRADE, classification
  BULLISH) -- nothing that predates the boundary is ever considered (the cursor starts at the store's max seq);
* processing phase REGULAR and data phase REGULAR (the causal bar horizon is inside the regular session);
* long-only: BEARISH is recorded as REJECTED_BEARISH and never becomes actionable; WATCH is REJECTED_WATCH;
* the candidate is still an active BULLISH_SETUP when promoted (invalidated / stale / faded / expired -> REJECTED);
* the data is fresh under the existing 15-min provider-lag contract and causal (data_as_of <= event time <= now);
* reference price > 0;
* at most ONE promotion per candidate identity, ever (promotion_id = ``OPPORTUNITY_ENGINE:<candidate_id>``).

Delivery: a durable queue ordered score-descending, max 3 promotions per rolling 5 min, queue expiry 30 min.
Mode (``TALONX_OPPORTUNITY_PROMOTION_MODE``): SHADOW (default) records PROMOTED_SHADOW / WOULD_SIGNAL and sends
NOTHING; PAPER_SIGNAL enqueues a "PAPER OPPORTUNITY" message to the TRADE_EVENT (TalonX Signal) destination via
``talonx_ops.notify`` -- never the Lab bot, never the legacy default client. Never a broker order, never V2.

This is NOT proven profitable and NOT BUY/SELL advice: it creates a measurable paper Signal-quality cohort.
Paper outcomes (+15m/+30m/+1h/close/MFE/MAE, long direction) are tracked for every promotion.
"""
from __future__ import annotations

import hashlib
import json
import os
from dataclasses import asdict, dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path

from talonx_opportunity.db import connect, iso, j, root_dir, utcnow
from talonx_opportunity.phases import phase_at, trading_window
from talonx_opportunity.store import OpportunityStore, opportunity_db

MODE_ENV = "TALONX_OPPORTUNITY_PROMOTION_MODE"
SHADOW, PAPER_SIGNAL = "SHADOW", "PAPER_SIGNAL"
SOURCE = "OPPORTUNITY_ENGINE"
PRODUCER = "talonx_opportunity.promotion"
ACTIVE_SETUP = "BULLISH_SETUP"


@dataclass(frozen=True)
class PromotionPolicy:
    version: str = "OPPORTUNITY_PROMOTION_V1"
    processing_phases: tuple[str, ...] = ("REGULAR",)
    data_phases: tuple[str, ...] = ("REGULAR",)
    long_only: bool = True
    classes: tuple[str, ...] = ("BULLISH",)
    surfacing_events: tuple[str, ...] = ("NEW", "UPGRADE")
    freshness_s: int = 900                  # discovery's PROVIDER_LAG_LIMIT: data older than this vs the SIP as-of
    rate_max: int = 3
    rate_window_s: int = 300
    queue_expiry_s: int = 1800
    queue_order: str = "SCORE_DESC"
    one_promotion_per_candidate: bool = True

    def fingerprint(self) -> str:
        return hashlib.sha256(json.dumps(asdict(self), sort_keys=True).encode()).hexdigest()[:16]


PROMOTION_V1 = PromotionPolicy()

SCHEMA = """
CREATE TABLE IF NOT EXISTS meta (k TEXT PRIMARY KEY, v TEXT);
CREATE TABLE IF NOT EXISTS cursor (name TEXT PRIMARY KEY, last_seq INTEGER, updated_utc TEXT);
CREATE TABLE IF NOT EXISTS evaluations (
    event_id TEXT PRIMARY KEY, seq INTEGER, candidate_id TEXT, symbol TEXT, event_type TEXT, classification TEXT,
    processing_phase TEXT, data_phase TEXT, data_as_of_utc TEXT, event_utc TEXT, evaluated_utc TEXT,
    decision TEXT, reason_code TEXT, policy_fp TEXT
);
CREATE TABLE IF NOT EXISTS promotions (
    promotion_id TEXT PRIMARY KEY, candidate_id TEXT UNIQUE, event_id TEXT, symbol TEXT, direction TEXT,
    classification TEXT, score REAL, processing_phase TEXT, data_phase TEXT, data_as_of_utc TEXT,
    event_utc TEXT, queued_utc TEXT, decision_utc TEXT, reference_price REAL, horizons_json TEXT,
    lifecycle_state TEXT, promotion_mode TEXT, state TEXT, reason_code TEXT, queue_rank INTEGER,
    policy_version TEXT, policy_fp TEXT, source_strategy TEXT, source_candidate_version TEXT,
    signal_event_id TEXT, family TEXT, window_id TEXT
);
CREATE INDEX IF NOT EXISTS ix_promotions_state ON promotions(state);
CREATE TABLE IF NOT EXISTS paper_outcomes (
    promotion_id TEXT PRIMARY KEY, candidate_id TEXT, symbol TEXT, ref_time_utc TEXT, ref_price REAL,
    px_15m REAL, ret_15m_pct REAL, px_30m REAL, ret_30m_pct REAL, px_1h REAL, ret_1h_pct REAL, close_px REAL,
    close_ret_pct REAL, mfe_pct REAL, mae_pct REAL, status TEXT, lifecycle_end_state TEXT, session_complete INTEGER,
    updated_utc TEXT
);
"""
# promotion states: QUEUED -> PROMOTED_SHADOW | PROMOTED_SIGNAL | EXPIRED | REJECTED_WHILE_QUEUED


def promotion_db(root=None) -> Path:
    return root_dir(root) / "promotion.db"


def signal_outbox_path(root=None) -> Path:
    return root_dir(root) / "promotion_signal_notifications.db"


def mode_from_env(env=None) -> str:
    m = str((env if env is not None else os.environ).get(MODE_ENV, SHADOW)).strip().upper() or SHADOW
    if m not in (SHADOW, PAPER_SIGNAL):
        raise SystemExit(f"{MODE_ENV}={m!r}: allowed {SHADOW} | {PAPER_SIGNAL}")
    return m


def _ts(s):
    return datetime.fromisoformat(s.replace("Z", "+00:00")) if s else None


def render(p: dict) -> str:
    return "\n".join([
        "[TALONX SIGNAL - PAPER OPPORTUNITY]",
        f"Source: Opportunity Engine  |  Mode: PAPER (no order placed)",
        f"Symbol: {p['symbol']}  Direction: BULLISH (long-only)  Score: {round(p['score'] or 0, 1)}",
        f"Phase: REGULAR  Data as of: {(p['data_as_of_utc'] or '')[11:16]}Z  Reference: {p['reference_price']}",
        f"Horizon: {', '.join(json.loads(p['horizons_json'] or '[]')) or 'SAME_DAY'}",
        "Reason: valid REGULAR setup promoted from the Opportunity Engine (paper development output; "
        "not proven profitable; not BUY/SELL advice)",
    ])


class Promoter:
    def __init__(self, *, root=None, policy: PromotionPolicy = PROMOTION_V1, mode: str = SHADOW, clock=None,
                 drain=None, data=None):
        self.root, self.policy, self.mode = root, policy, mode
        self.clock = clock or utcnow
        self.con = connect(promotion_db(root))
        self.con.executescript(SCHEMA)
        self._drain, self._data = drain, data
        self.outbox = None
        if mode == PAPER_SIGNAL:
            from talonx_ops.notify.outbox import NotifyStore
            self.outbox = NotifyStore(str(signal_outbox_path(root)))
        self.last: dict = {}
        self._init_boundary()

    # -- activation boundary: never replay anything that predates the first start -------------------------------------
    def _init_boundary(self) -> None:
        if self.con.execute("SELECT 1 FROM cursor WHERE name='events'").fetchone():
            return
        start_seq = 0
        if opportunity_db(self.root).exists():
            s = OpportunityStore(self.root, readonly=True)
            try:
                r = s.con.execute("SELECT MAX(seq) FROM candidate_events").fetchone()
                start_seq = int(r[0] or 0)
            finally:
                s.close()
        with self.con:
            self.con.execute("INSERT INTO cursor VALUES ('events', ?, ?)", (start_seq, iso(self.clock())))
            self.con.execute("INSERT OR IGNORE INTO meta VALUES ('PROMOTION_START_UTC', ?)", (iso(self.clock()),))
            self.con.execute("INSERT OR IGNORE INTO meta VALUES ('PROMOTION_START_SEQ', ?)", (str(start_seq),))

    def meta(self, k: str) -> str | None:
        r = self.con.execute("SELECT v FROM meta WHERE k=?", (k,)).fetchone()
        return r[0] if r else None

    def cursor(self) -> int:
        return int(self.con.execute("SELECT last_seq FROM cursor WHERE name='events'").fetchone()[0])

    # -- eligibility (pure over the event + current candidate row) ------------------------------------------------------
    def eligibility(self, ev: dict, cand: dict | None, now: datetime) -> tuple[str, str]:
        p = self.policy
        if ev["event_type"] not in p.surfacing_events:
            return "IGNORED", "NOT_A_SURFACING_EVENT"
        cls = ev.get("classification")
        if cls == "WATCH":
            return "REJECTED", "WATCH"
        if cls == "BEARISH":
            return "REJECTED", "BEARISH"
        if cls not in p.classes:
            return "REJECTED", "CLASSIFICATION"
        if ev["phase"] not in p.processing_phases:
            return "REJECTED", "PHASE"
        asof = _ts(ev.get("data_as_of_utc"))
        if asof is None:
            return "REJECTED", "NO_DATA_AS_OF"
        if phase_at(asof - timedelta(minutes=1))[0] not in p.data_phases:
            return "REJECTED", "DATA_PHASE"
        evt = _ts(ev["at_utc"])
        if asof > evt or evt > now + timedelta(seconds=5):
            return "REJECTED", "CAUSALITY"
        if self.con.execute("SELECT 1 FROM promotions WHERE candidate_id=?", (ev["candidate_id"],)).fetchone():
            return "REJECTED", "DUPLICATE"
        if cand is None:
            return "REJECTED", "NO_CANDIDATE"
        return self.still_valid(ev, cand, now)

    def still_valid(self, ev: dict, cand: dict, now: datetime) -> tuple[str, str]:
        st = cand.get("state")
        if st != ACTIVE_SETUP:
            why = (cand.get("closed_reason") or "").lower()
            if "stale" in why:
                return "REJECTED", "STALE"
            if "fade" in why:
                return "REJECTED", "FADED"
            if st in ("INVALIDATED",):
                return "REJECTED", "INVALIDATED"
            if st in ("EXPIRED",):
                return "REJECTED", "EXPIRED"
            return "REJECTED", f"NOT_ACTIVE_SETUP:{st}"
        from talonx_premarket.alpaca_data import data_as_of
        asof = _ts(ev.get("data_as_of_utc"))
        if (data_as_of(now) - asof).total_seconds() > self.policy.freshness_s:
            return "REJECTED", "STALE"
        if not (ev.get("last_price") or 0) > 0:
            return "REJECTED", "BAD_PRICE"
        return "ELIGIBLE", "OK"

    # -- one tick -------------------------------------------------------------------------------------------------------
    def tick(self) -> float:
        now = self.clock()
        evaluated = queued = 0
        if opportunity_db(self.root).exists():
            s = OpportunityStore(self.root, readonly=True)
            try:
                evs = s.events_after(self.cursor(), limit=2000)
                for ev in evs:
                    if self.con.execute("SELECT 1 FROM evaluations WHERE event_id=?", (ev["event_id"],)).fetchone():
                        continue
                    cand = s.candidate(ev["candidate_id"])
                    dec, why = self.eligibility(ev, cand, now)
                    if dec == "IGNORED":
                        continue
                    asof = _ts(ev.get("data_as_of_utc"))
                    dph = phase_at(asof - timedelta(minutes=1))[0] if asof else None
                    with self.con:
                        self.con.execute("INSERT OR IGNORE INTO evaluations VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                                         (ev["event_id"], ev["seq"], ev["candidate_id"], ev["symbol"], ev["event_type"],
                                          ev.get("classification"), ev["phase"], dph, ev.get("data_as_of_utc"),
                                          ev["at_utc"], iso(now), dec, why, self.policy.fingerprint()))
                        if dec == "ELIGIBLE":
                            self.con.execute(
                                "INSERT OR IGNORE INTO promotions VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                                (f"{SOURCE}:{ev['candidate_id']}", ev["candidate_id"], ev["event_id"], ev["symbol"],
                                 "LONG", ev.get("classification"), ev.get("score"), ev["phase"], dph,
                                 ev.get("data_as_of_utc"), ev["at_utc"], iso(now), None, ev.get("last_price"),
                                 cand.get("horizons_json"), cand.get("state"), self.mode, "QUEUED", "OK", None,
                                 self.policy.version, self.policy.fingerprint(), SOURCE, cand.get("config_fp"), None,
                                 cand.get("family"), ev.get("window_id")))
                            queued += 1
                    evaluated += 1
                if evs:
                    with self.con:
                        self.con.execute("UPDATE cursor SET last_seq=?, updated_utc=? WHERE name='events'",
                                         (max(e["seq"] for e in evs), iso(now)))
                released = self._release(s, now)
            finally:
                s.close()
        else:
            released = {}
        drained = self._drain_signal()
        outc = self._outcomes(now)
        self.last = {"mode": self.mode, "cursor": self.cursor(), "evaluated": evaluated, "queued": queued,
                     "released": released, "drain": drained, "outcomes": outc, "policy": self.policy.version}
        return 30.0

    def _release(self, s: OpportunityStore, now: datetime) -> dict:
        """Expire, re-validate and release queued promotions: score-desc, <= rate_max per rolling window."""
        p = self.policy
        out = {"expired": 0, "rejected_while_queued": 0, "promoted": 0, "held_by_rate": 0}
        for r in self.con.execute("SELECT promotion_id, queued_utc FROM promotions WHERE state='QUEUED'").fetchall():
            if (now - _ts(r[1])).total_seconds() > p.queue_expiry_s:
                with self.con:
                    self.con.execute("UPDATE promotions SET state='EXPIRED', reason_code='QUEUE_EXPIRY_30M', "
                                     "decision_utc=? WHERE promotion_id=?", (iso(now), r[0]))
                out["expired"] += 1
        since = iso(now - timedelta(seconds=p.rate_window_s))
        used = self.con.execute("SELECT COUNT(*) FROM promotions WHERE state IN ('PROMOTED_SHADOW','PROMOTED_SIGNAL') "
                                "AND decision_utc > ?", (since,)).fetchone()[0]
        queue = [dict(zip([d[0] for d in self.con.execute("SELECT * FROM promotions LIMIT 0").description], row))
                 for row in self.con.execute("SELECT * FROM promotions WHERE state='QUEUED' "
                                             "ORDER BY score DESC, queued_utc ASC, promotion_id ASC").fetchall()]
        for rank, q in enumerate(queue, start=1):
            with self.con:
                self.con.execute("UPDATE promotions SET queue_rank=? WHERE promotion_id=?", (rank, q["promotion_id"]))
            if used >= p.rate_max:
                out["held_by_rate"] += 1
                continue
            cand = s.candidate(q["candidate_id"])
            ev = {"data_as_of_utc": q["data_as_of_utc"], "last_price": q["reference_price"]}
            dec, why = self.still_valid(ev, cand or {"state": None}, now)
            if dec != "ELIGIBLE":
                with self.con:
                    self.con.execute("UPDATE promotions SET state='REJECTED_WHILE_QUEUED', reason_code=?, "
                                     "decision_utc=?, lifecycle_state=? WHERE promotion_id=?",
                                     (why, iso(now), (cand or {}).get("state"), q["promotion_id"]))
                out["rejected_while_queued"] += 1
                continue
            state, sig = "PROMOTED_SHADOW", None
            if self.mode == PAPER_SIGNAL and self.outbox is not None:
                from talonx_ops.notify import TRADE_EVENT
                sig = q["promotion_id"]
                self.outbox.enqueue(event_id=sig, destination=TRADE_EVENT, event_type="PAPER_OPPORTUNITY",
                                    producer=PRODUCER, dedup_key=sig, payload_text=render(q),
                                    provenance={"source_strategy": SOURCE, "candidate_id": q["candidate_id"],
                                                "symbol": q["symbol"], "mode": PAPER_SIGNAL, "paper_only": True,
                                                "not_a_v2_trade_event": True, "policy": self.policy.version},
                                    deliver_by_utc=iso(now + timedelta(minutes=30)))
                state = "PROMOTED_SIGNAL"
            with self.con:
                self.con.execute("UPDATE promotions SET state=?, decision_utc=?, promotion_mode=?, signal_event_id=?, "
                                 "lifecycle_state=? WHERE promotion_id=?",
                                 (state, iso(now), self.mode, sig, cand.get("state"), q["promotion_id"]))
            used += 1
            out["promoted"] += 1
        return out

    def _drain_signal(self):
        if self.mode != PAPER_SIGNAL or self.outbox is None:
            return None
        if self._drain is not None:
            return self._drain(self.outbox)
        from talonx_ops.notify import TRADE_EVENT
        from talonx_ops.notify.worker import drain
        return drain(self.outbox, destination=TRADE_EVENT)

    # -- paper outcomes (long only; reference = the causal data time + price of the promoted event) --------------------
    def _outcomes(self, now: datetime) -> dict:
        rows = self.con.execute("SELECT p.promotion_id, p.candidate_id, p.symbol, p.data_as_of_utc, p.reference_price, "
                                "p.window_id FROM promotions p LEFT JOIN paper_outcomes o USING(promotion_id) "
                                "WHERE p.state IN ('PROMOTED_SHADOW','PROMOTED_SIGNAL') "
                                "AND (o.session_complete IS NULL OR o.session_complete=0)").fetchall()
        if not rows:
            return {"tracked": 0}
        data = self._data
        if data is None:
            try:
                from talonx_premarket import __main__ as M
                M._env()
                data = self._data = M._data()
            except Exception as exc:  # noqa: BLE001 -- outcomes are hindsight only; retry next tick
                return {"error": f"{type(exc).__name__}"}
        from talonx_premarket.alpaca_data import data_as_of
        asof = data_as_of(now)
        n = 0
        for pid, cid, sym, ref_t, ref_px, wid in rows:
            w = trading_window(datetime.fromisoformat(wid).date() if len(wid) == 10 else _ts(ref_t).date())
            end = min(asof, w.close_utc)
            ref = _ts(ref_t)
            if end <= ref:
                continue
            res = data.bars_ex([sym], timeframe="1Min", start=ref, end=end - timedelta(seconds=1))
            if sym in res.failed:
                continue
            m = measure_long(ref, float(ref_px), res.bars.get(sym, []), w.close_utc)
            s = OpportunityStore(self.root, readonly=True)
            try:
                life = (s.candidate(cid) or {}).get("state")
            finally:
                s.close()
            with self.con:
                self.con.execute("INSERT OR REPLACE INTO paper_outcomes VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                                 (pid, cid, sym, ref_t, ref_px, m["px_15m"], m["ret_15m_pct"], m["px_30m"],
                                  m["ret_30m_pct"], m["px_1h"], m["ret_1h_pct"], m["close_px"], m["close_ret_pct"],
                                  m["mfe_pct"], m["mae_pct"], m["status"], life, int(m["session_complete"]), iso(now)))
            n += 1
        return {"tracked": n}

    def detail(self) -> dict:
        return dict(self.last)


def measure_long(ref_time: datetime, ref_price: float, bars: list[dict], close_utc: datetime) -> dict:
    """Long-only paper outcome from the causal reference. +h values use the last bar COMPLETED by ref+h."""
    after = sorted((b for b in bars if _ts(b["t"]) >= ref_time and _ts(b["t"]) < close_utc), key=lambda b: b["t"])
    ret = lambda px: None if px is None else round((px / ref_price - 1.0) * 100.0, 3)  # noqa: E731
    out = {"px_15m": None, "px_30m": None, "px_1h": None, "close_px": None, "mfe_pct": None, "mae_pct": None,
           "status": "OUTCOME_PENDING", "session_complete": False}
    if after:
        last_end = _ts(after[-1]["t"]) + timedelta(minutes=1)

        def at(m):
            t = ref_time + timedelta(minutes=m)
            if last_end < t:
                return None
            px = None
            for b in after:
                if _ts(b["t"]) + timedelta(minutes=1) <= t:
                    px = float(b["c"])
            return px
        out.update(px_15m=at(15), px_30m=at(30), px_1h=at(60))
        out["session_complete"] = last_end >= close_utc
        out["close_px"] = float(after[-1]["c"]) if out["session_complete"] else None
        out["mfe_pct"] = ret(max(float(b["h"]) for b in after))
        out["mae_pct"] = ret(min(float(b["l"]) for b in after))
        if out["px_30m"] is not None:
            out["status"] = "CONFIRMED" if out["px_30m"] >= ref_price else "FAILED_CONFIRMATION"
    out.update(ret_15m_pct=ret(out["px_15m"]), ret_30m_pct=ret(out["px_30m"]), ret_1h_pct=ret(out["px_1h"]),
               close_ret_pct=ret(out["close_px"]))
    return out


def main(argv=None) -> int:
    from talonx_opportunity.runtime import run_component
    root = os.environ.get("TALONX_OPP_ROOT")
    mode = mode_from_env()
    pr = Promoter(root=root, mode=mode)
    src = hashlib.sha256(Path(__file__).read_bytes().replace(b"\r\n", b"\n")).hexdigest()[:12]
    run_component("promotion", tick=pr.tick, root=root, detail=pr.detail,
                  config_fps={"PROMOTION_POLICY": PROMOTION_V1.fingerprint(), "mode": mode, "promotion_src": src})
    return 0
