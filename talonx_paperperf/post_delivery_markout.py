"""
POST_DELIVERY_ALERT_MARKOUT_V1 -- post-delivery price markout under stated cost assumptions (INACTIVE package).

Protocol: docs/research/protocols/POST_DELIVERY_ALERT_MARKOUT_V1.md (revision 2, exact targets). One descriptive
question: after a Telegram research alert became available, how did the price move over a fixed post-delivery
interval, gross and under an explicit spread-based cost approximation? NOT executable profit, NOT a paper portfolio,
NOT a strategy verdict. Separate from promotion paper_outcomes (data-time markouts), VR_PAPER_V1, V2 forward and every
frozen study.

Isolation:
* DISABLED unless TALONX_PDM_ENABLED=1 AND an approved activation config (matching this code's protocol fingerprint,
  a future full trading session) is supplied. Nothing is scheduled or registered anywhere.
* Production alert stores are read mode=ro; this package writes only its own store (``results/post_delivery_markout``).
  Telegram delivery is never delayed, gated or modified.
* Price/quote acquisition is an injected ``Acquirer`` (talonx_paperperf.post_delivery_acquisition); measurement and
  costs are pure functions of the stored, hashed inputs.
* Waiting is finite and calendar-defined; deadlines are reconciled first on every invocation (downtime never extends
  them) and terminal observations are never reopened.
"""
from __future__ import annotations

import hashlib
import json
import math
import os
import sqlite3
import statistics
from dataclasses import asdict, dataclass
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

UTC = timezone.utc
REPO = Path(__file__).resolve().parents[1]
ENABLE_ENV = "TALONX_PDM_ENABLED"
CONFIG_ENV = "TALONX_PDM_CONFIG"           # path to the approved activation config (JSON)
EVENT_TYPE = "RESEARCH_OPPORTUNITY"
REVIEW_REASON = "RESEARCH_REVIEW_ALERT"
DELIVERED_STATES = ("SENT", "AMBIGUOUS")  # records that may have reached Telegram (FAILED/EXPIRED/PENDING never did)

# ---- observation states ------------------------------------------------------------------------------------------
SELECTED_WAITING = "WAITING_FOR_DATA"
MEASURED = "MEASURED"                                    # gross markout measured (cost may still be unavailable)
MISSING_ENTRY = "MISSING_ENTRY_BAR"
MISSING_EXIT = "MISSING_EXIT_BAR"
EXPIRED = "EXPIRED_NO_DATA"                              # deadline passed before the target bars were obtained
AMBIGUOUS = "AMBIGUOUS_DELIVERY"
REPEAT = "REPEAT_SAME_SESSION"
INELIGIBLE = "SESSION_INELIGIBLE"
CLOCK = "CLOCK_UNVERIFIED"
INVALID = "INVALID_SOURCE"
SELECTED = {SELECTED_WAITING, MEASURED, MISSING_ENTRY, MISSING_EXIT, EXPIRED}
TERMINAL = {MEASURED, MISSING_ENTRY, MISSING_EXIT, EXPIRED, AMBIGUOUS, REPEAT, INELIGIBLE, CLOCK, INVALID}

# cost states (independent of the gross state)
COST_OK, COST_NO_QUOTE, COST_ACQ_FAILED, COST_PENDING = ("COST_OK", "QUOTE_UNAVAILABLE", "QUOTE_ACQUISITION_FAILED",
                                                         "COST_PENDING")


@dataclass(frozen=True)
class PDMConfig:
    version: str = "POST_DELIVERY_ALERT_MARKOUT_V1"
    revision: int = 2
    anchor: str = ("API-acceptance acknowledgement time: local, timezone-aware time recorded after a successful "
                   "Telegram API response (outbox sent_at_utc; trace response_utc when deployed)")
    reaction_delay_s: int = 300
    horizon_min: int = 30
    quote_max_age_s: int = 60
    assumed_additional_cost: float = 0.0005     # 5 bps TOTAL round trip, subtracted once (unsupported assumption)
    maturity_lag_min: int = 60                  # acquisition not before session close + 60 min
    expiry_sessions: int = 2                    # deadline = close of the 2nd subsequent session + 60 min
    observation_sessions: int = 20
    clock_tolerance_s: float = 2.0              # |local response - Telegram server date| (1 s resolution) bound
    price_adjustment: str = "raw"
    feed: str = "sip"
    label: str = "Post-delivery price markout under stated cost assumptions"

    def fingerprint(self) -> str:
        return hashlib.sha256(json.dumps(asdict(self), sort_keys=True).encode()).hexdigest()[:16]


PDM_V1 = PDMConfig()


def ts(s) -> datetime:
    t = datetime.fromisoformat(str(s).replace("Z", "+00:00"))
    if t.tzinfo is None:
        raise ValueError(f"timestamp without timezone: {s!r}")
    return t


def iso(t: datetime | None) -> str | None:
    return t.astimezone(UTC).isoformat() if t else None


def ts_ns(s) -> int:
    """Exact integer nanoseconds since the epoch (provider quote times carry 9 fractional digits; datetime keeps 6 and
    would silently floor a quote 300 ns AFTER a target onto the target itself)."""
    raw = str(s).replace("Z", "+00:00")
    frac = ""
    if "." in raw:
        head, rest = raw.split(".", 1)
        digits = ""
        for ch in rest:
            if ch.isdigit():
                digits += ch
            else:
                break
        frac, raw = digits, head + rest[len(digits):]
    base = ts(raw)
    return int(base.timestamp()) * 1_000_000_000 + int((frac + "000000000")[:9])


def ceil_minute(t: datetime) -> datetime:
    f = t.replace(second=0, microsecond=0)
    return f if f == t else f + timedelta(minutes=1)


# ============================================================================================ calendar
def _window(d: date):
    from talonx_opportunity.phases import trading_window
    try:
        return trading_window(d)
    except ValueError:
        return None


def session_of(t: datetime):
    """The XNYS regular session containing ``t`` (open <= t < close), else None."""
    from talonx_opportunity.phases import phase_at
    phase, w = phase_at(t)
    return w if (w is not None and phase == "REGULAR") else None


def next_sessions(d: date, n: int) -> list:
    out, cur = [], d
    while len(out) < n:
        cur += timedelta(days=1)
        w = _window(cur)
        if w is not None:
            out.append(w)
    return out


def study_sessions(first: date, n: int) -> list:
    w = _window(first)
    if w is None:
        raise ValueError(f"{first} is not an XNYS session")
    return [w] + next_sessions(first, n - 1)


def maturity(w, cfg: PDMConfig = PDM_V1) -> datetime:
    return w.close_utc + timedelta(minutes=cfg.maturity_lag_min)


def deadline(w, cfg: PDMConfig = PDM_V1) -> datetime:
    """Close of the ``expiry_sessions``-th subsequent trading session + maturity lag (half days/DST via XNYS)."""
    return next_sessions(w.session, cfg.expiry_sessions)[-1].close_utc + timedelta(minutes=cfg.maturity_lag_min)


# ============================================================================================ targets (pure)
def targets(anchor: datetime, cfg: PDMConfig = PDM_V1) -> dict:
    """E = ceil_minute(anchor + R) (kept if already on a boundary); X = E + 30 min. Both inside ONE regular session,
    X <= close. Ineligible alerts are never shifted or shortened."""
    w = session_of(anchor)
    if w is None:
        return {"eligible": False, "reason": "DELIVERED_OUTSIDE_REGULAR_SESSION"}
    e = ceil_minute(anchor + timedelta(seconds=cfg.reaction_delay_s))
    x = e + timedelta(minutes=cfg.horizon_min)
    if e >= w.close_utc:
        return {"eligible": False, "reason": "ENTRY_AT_OR_AFTER_CLOSE", "session": w.window_id}
    if x > w.close_utc:
        return {"eligible": False, "reason": "EXIT_AFTER_CLOSE", "session": w.window_id}
    return {"eligible": True, "session": w.window_id, "entry_utc": e, "exit_utc": x,
            "entry_bar_start": e, "exit_bar_start": x - timedelta(minutes=1),
            "matures_utc": maturity(w, cfg), "deadline_utc": deadline(w, cfg)}


def _finite_pos(x) -> float | None:
    try:
        v = float(x)
    except (TypeError, ValueError):
        return None
    return v if math.isfinite(v) and v > 0 else None


def target_bar(bars: list[dict], start: datetime) -> tuple[dict | None, str]:
    """The ONE bar whose interval is [start, start + 1 min). No neighbour is ever substituted."""
    hits = []
    for b in bars:
        try:
            bt = ts(b["t"])
        except (KeyError, ValueError):
            continue
        if bt == start:
            hits.append(b)
    if not hits:
        return None, "ABSENT"
    if len(hits) > 1:
        return None, "DUPLICATE_BARS"
    b = hits[0]
    o, c, v = _finite_pos(b.get("o")), _finite_pos(b.get("c")), b.get("v")
    try:
        vol = float(v)
    except (TypeError, ValueError):
        return None, "INVALID_VOLUME"
    if not math.isfinite(vol) or vol <= 0:
        return None, "ZERO_VOLUME"
    if o is None or c is None:
        return None, "INVALID_PRICE"
    return b, "OK"


def select_quote(quotes: list[dict], target: datetime, cfg: PDMConfig = PDM_V1) -> tuple[dict | None, str]:
    """Latest VALID NBBO quote with target - 60 s <= t <= target (never after). Valid: finite bid, ask > 0 and
    ask >= bid (locked ask == bid allowed, flagged). Equal timestamps: the WIDEST valid spread (conservative), then the
    highest ask (deterministic)."""
    tgt_ns = int(target.timestamp()) * 1_000_000_000 + target.microsecond * 1000
    lo_ns = tgt_ns - cfg.quote_max_age_s * 1_000_000_000
    valid = []
    for q in quotes or []:
        try:
            qns = ts_ns(q["t"])
            qt = ts(q["t"])
        except (KeyError, ValueError):
            continue
        if not (lo_ns <= qns <= tgt_ns):
            continue
        bid, ask = _finite_pos(q.get("bp")), _finite_pos(q.get("ap"))
        if bid is None or ask is None or ask < bid:
            continue
        valid.append((qns, ask - bid, ask, bid, q))
    if not valid:
        return None, "NO_VALID_QUOTE_WITHIN_60S"
    latest = max(v[0] for v in valid)
    qns, spr, ask, bid, q = max((v for v in valid if v[0] == latest), key=lambda v: (v[1], v[2]))
    return {"t": str(q["t"]), "t_ns": qns, "bid": bid, "ask": ask, "locked": ask == bid}, "OK"


def half_spread(q: dict) -> float:
    mid = (q["ask"] + q["bid"]) / 2.0
    return (q["ask"] - q["bid"]) / (2.0 * mid)


def compute(entry_bar: dict, exit_bar: dict, q_entry: dict | None, q_exit: dict | None,
            cfg: PDMConfig = PDM_V1) -> dict:
    """gross = exit close / entry open - 1; cost-adjusted = gross - (half spread at E + half spread at X) - 0.0005."""
    gross = float(exit_bar["c"]) / float(entry_bar["o"]) - 1.0
    out = {"entry_px": float(entry_bar["o"]), "exit_px": float(exit_bar["c"]), "gross": gross}
    if q_entry is None or q_exit is None:
        out.update(spread_cost=None, cost_adjusted=None)
        return out
    sc = half_spread(q_entry) + half_spread(q_exit)
    out.update(spread_cost=sc, cost_adjusted=gross - sc - cfg.assumed_additional_cost)
    return out


# ============================================================================================ activation config
class NotApproved(Exception):
    pass


def load_activation(path: str | Path | None, cfg: PDMConfig = PDM_V1, now: datetime | None = None) -> dict:
    """The owner-approved activation config. Required keys: approved (true), approved_by, approved_utc (aware),
    protocol_fingerprint (== this code), first_session (a future XNYS session, approved before its window opens),
    delivery_trace_policy (REQUIRED | NOT_AVAILABLE_ACCEPTED)."""
    if not path or not Path(path).exists():
        raise NotApproved("NO_ACTIVATION_CONFIG")
    d = json.loads(Path(path).read_text(encoding="utf-8"))
    if d.get("approved") is not True or not d.get("approved_by"):
        raise NotApproved("NOT_APPROVED")
    if d.get("protocol_fingerprint") != cfg.fingerprint():
        raise NotApproved(f"PROTOCOL_FINGERPRINT_MISMATCH (config {d.get('protocol_fingerprint')} != code "
                          f"{cfg.fingerprint()})")
    if d.get("delivery_trace_policy") not in ("REQUIRED", "NOT_AVAILABLE_ACCEPTED"):
        raise NotApproved("DELIVERY_TRACE_POLICY_MISSING")
    approved = ts(d["approved_utc"])
    first = date.fromisoformat(d["first_session"])
    w = _window(first)
    if w is None:
        raise NotApproved("FIRST_SESSION_NOT_A_TRADING_SESSION")
    start = datetime(first.year, first.month, first.day, tzinfo=UTC)    # the window opens at 00:00Z of its date
    if approved >= start:
        raise NotApproved("ACTIVATION_NOT_BEFORE_A_FULL_SESSION")         # no partial activation day
    sessions = study_sessions(first, cfg.observation_sessions)
    return {**d, "boundary_utc": start, "sessions": [s.window_id for s in sessions],
            "last_session": sessions[-1].window_id,
            "endpoint_utc": deadline(sessions[-1], cfg)}


# ============================================================================================ store
SCHEMA = """
CREATE TABLE IF NOT EXISTS meta (k TEXT PRIMARY KEY, v TEXT);
CREATE TABLE IF NOT EXISTS deliveries (
    event_id TEXT PRIMARY KEY, symbol TEXT, session TEXT, promotion_id TEXT, promotion_policy_fp TEXT,
    outbox_state TEXT, attempts INTEGER, last_error TEXT, created_utc TEXT, anchor_utc TEXT, anchor_source TEXT,
    trace_json TEXT, delivery_class TEXT, delivery_reason TEXT, source_sha256 TEXT, registered_utc TEXT);
CREATE TABLE IF NOT EXISTS observations (
    obs_id TEXT PRIMARY KEY, event_id TEXT UNIQUE, symbol TEXT, session TEXT, segment TEXT, protocol_fp TEXT,
    state TEXT, reason TEXT, anchor_utc TEXT, entry_utc TEXT, exit_utc TEXT, matures_utc TEXT, deadline_utc TEXT,
    cost_state TEXT, attempts INTEGER DEFAULT 0, created_utc TEXT, updated_utc TEXT, terminal_utc TEXT);
CREATE TABLE IF NOT EXISTS inputs (
    obs_id TEXT, part TEXT, scope_json TEXT, outcome TEXT, payload_json TEXT, sha256 TEXT, retrieved_utc TEXT,
    provider TEXT, PRIMARY KEY (obs_id, part));
CREATE TABLE IF NOT EXISTS acquisition_errors (
    id INTEGER PRIMARY KEY AUTOINCREMENT, obs_id TEXT, part TEXT, error_class TEXT, detail TEXT, at_utc TEXT);
CREATE TABLE IF NOT EXISTS results (
    obs_id TEXT PRIMARY KEY, protocol_fp TEXT, entry_bar_json TEXT, exit_bar_json TEXT, q_entry_json TEXT,
    q_exit_json TEXT, entry_px REAL, exit_px REAL, gross REAL, spread_cost REAL, cost_adjusted REAL,
    inputs_sha256 TEXT, computed_utc TEXT);
CREATE TABLE IF NOT EXISTS runs (id INTEGER PRIMARY KEY AUTOINCREMENT, started_utc TEXT, finished_utc TEXT,
    summary_json TEXT);
"""
PARTS = ("entry_bar", "exit_bar", "entry_quote", "exit_quote")


class Store:
    def __init__(self, root: Path):
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)
        self.con = sqlite3.connect(self.root / "pdm.db", timeout=30)
        self.con.row_factory = sqlite3.Row
        self.con.executescript(SCHEMA)

    def q(self, sql, args=()):
        return [dict(r) for r in self.con.execute(sql, args)]


def _ro(p: Path):
    if not Path(p).exists():
        return None
    c = sqlite3.connect(f"file:{p}?mode=ro", uri=True, timeout=10)
    c.row_factory = sqlite3.Row
    return c


def segment_key(cfg: PDMConfig, promotion_policy_fp: str | None, dtu_policy_fp: str | None, delivery_mode: str) -> str:
    return "|".join([cfg.version, f"r{cfg.revision}", cfg.fingerprint(), promotion_policy_fp or "UNKNOWN",
                     dtu_policy_fp or "UNKNOWN", delivery_mode])


# ============================================================================================ delivery classification
def classify_delivery(row: dict, trace: dict | None, trace_policy: str, cfg: PDMConfig = PDM_V1) -> tuple[str, str]:
    """DELIVERED_CLEAN | AMBIGUOUS | CLOCK_UNVERIFIED -- conservative: any uncertainty is never 'definitely
    delivered'. A message_id confirms THAT message only; it cannot prove an earlier timed-out request failed."""
    if row["state"] == "AMBIGUOUS":
        return AMBIGUOUS, "outbox state AMBIGUOUS"
    if (row.get("attempts") or 0) > 1 or row.get("last_error"):
        return AMBIGUOUS, f"worker attempts={row.get('attempts')} last_error={bool(row.get('last_error'))}"
    if trace is None:
        if trace_policy == "REQUIRED":
            return AMBIGUOUS, "TRACE_MISSING (hidden client retries cannot be excluded)"
        return "DELIVERED_CLEAN", "trace not available (owner-accepted limitation)"
    if trace.get("trace_state", "TRACE_OK") != "TRACE_OK":
        return AMBIGUOUS, f"{trace.get('trace_state')} (incomplete delivery trace)"
    if trace.get("hidden_retries", 0) > 0 or trace.get("ambiguous_prior_attempt"):
        return AMBIGUOUS, f"client-level retries={trace.get('hidden_retries')} (a timed-out send may have delivered)"
    try:
        start, resp, server = ts(trace["send_start_utc"]), ts(trace["response_utc"]), ts(trace["server_date_utc"])
    except (KeyError, ValueError):
        return CLOCK, "trace timestamps missing or naive"
    if not start <= resp:
        return CLOCK, "response before send start"
    if row.get("sent_at_utc") and ts(row["sent_at_utc"]) < resp - timedelta(seconds=cfg.clock_tolerance_s):
        return CLOCK, "outbox sent_at_utc precedes the traced API response (timestamp ordering violated)"
    # Telegram's date has 1-second resolution (floor): local response must be within [server, server + 1 s + tol]
    if not (server - timedelta(seconds=cfg.clock_tolerance_s) <= resp <=
            server + timedelta(seconds=1 + cfg.clock_tolerance_s)):
        return CLOCK, f"local response {iso(resp)} vs Telegram server {iso(server)} beyond tolerance"
    return "DELIVERED_CLEAN", "trace consistent"


# ============================================================================================ registration / selection
def register(store: Store, *, act: dict, outbox_path: Path, promotion_path: Path, cfg: PDMConfig = PDM_V1,
             now: datetime | None = None, trace_lookup=None, dtu_policy_fp_for=None,
             delivery_mode: str = "RESEARCH_REVIEW") -> dict:
    """Register prospective deliveries in the study period (read-only sources; idempotent) and select ONE observation
    per (session, symbol): the earliest record by anchor (tie: event_id), BEFORE any price data is read."""
    now = now or datetime.now(UTC)
    b = iso(act["boundary_utc"])
    sessions = set(act["sessions"])
    ob, pc = _ro(outbox_path), _ro(promotion_path)
    if ob is None or pc is None:
        return {"registered": 0, "note": "SOURCE_STORE_MISSING"}
    rows = [dict(r) for r in ob.execute(
        "SELECT event_id, destination, event_type, producer, state, attempts, last_error, created_at_utc, sent_at_utc,"
        " updated_at_utc FROM ops_notification_outbox WHERE event_type=? AND created_at_utc>=? ORDER BY event_id",
        (EVENT_TYPE, b))]
    ob.close()
    new = 0
    for r in rows:
        if r["state"] not in DELIVERED_STATES:
            continue                                           # never reached Telegram (or not yet): not a delivery
        if store.con.execute("SELECT 1 FROM deliveries WHERE event_id=?", (r["event_id"],)).fetchone():
            continue
        p = pc.execute("SELECT promotion_id, symbol, window_id, state, reason_code, policy_fp FROM promotions WHERE "
                       "signal_event_id=?", (r["event_id"],)).fetchone()
        trace = trace_lookup(r["event_id"]) if trace_lookup else None
        anchor, src = (r["sent_at_utc"], "outbox.sent_at_utc") if r["sent_at_utc"] else (r["created_at_utc"],
                                                                                         "outbox.created_at_utc (ordering only)")
        if p is None or r["destination"] != "TRADE_EVENT" or p["reason_code"] != REVIEW_REASON:
            cls, why = INVALID, "source row failed validation"
        else:
            try:
                ts(anchor)
                cls, why = classify_delivery(r, trace, act["delivery_trace_policy"], cfg)
            except ValueError:
                cls, why = INVALID, "anchor not timezone-aware"
        sess = p["window_id"] if p else None
        if sess not in sessions:
            continue                                           # outside the fixed 20-session period: not registered
        src_blob = json.dumps({"outbox": r, "promotion": dict(p) if p else None}, sort_keys=True, default=str)
        with store.con:
            store.con.execute(
                "INSERT OR IGNORE INTO deliveries VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (r["event_id"], p["symbol"] if p else None, sess, p["promotion_id"] if p else None,
                 p["policy_fp"] if p else None, r["state"], r["attempts"], r["last_error"], r["created_at_utc"],
                 anchor, src, json.dumps(trace) if trace else None, cls, why,
                 hashlib.sha256(src_blob.encode()).hexdigest(), iso(now)))
        new += 1
    pc.close()
    sel = _select(store, cfg, now, dtu_policy_fp_for, delivery_mode)
    return {"registered": new, **sel}


def _select(store: Store, cfg, now, dtu_policy_fp_for, delivery_mode) -> dict:
    made = 0
    for d in store.q("SELECT * FROM deliveries WHERE event_id NOT IN (SELECT event_id FROM observations) "
                     "ORDER BY anchor_utc, event_id"):
        first = store.con.execute(
            "SELECT event_id FROM deliveries WHERE session=? AND symbol=? ORDER BY anchor_utc, event_id LIMIT 1",
            (d["session"], d["symbol"])).fetchone()[0]
        seg = segment_key(cfg, d["promotion_policy_fp"],
                          dtu_policy_fp_for(d["session"]) if dtu_policy_fp_for else None, delivery_mode)
        base = {"obs_id": f"{cfg.version}:{d['event_id']}", "event_id": d["event_id"], "symbol": d["symbol"],
                "session": d["session"], "segment": seg, "protocol_fp": cfg.fingerprint(), "anchor_utc": d["anchor_utc"],
                "entry_utc": None, "exit_utc": None, "matures_utc": None, "deadline_utc": None, "cost_state": None,
                "created_utc": iso(now), "updated_utc": iso(now), "terminal_utc": None}
        if d["event_id"] != first:
            st, why = REPEAT, f"first delivery for {d['symbol']} in {d['session']} is {first}"
        elif d["delivery_class"] != "DELIVERED_CLEAN":
            st, why = d["delivery_class"], d["delivery_reason"]
        else:
            tg = targets(ts(d["anchor_utc"]), cfg)
            if not tg["eligible"]:
                st, why = INELIGIBLE, tg["reason"]
            else:
                st, why = SELECTED_WAITING, "selected before any price data was read"
                base.update(entry_utc=iso(tg["entry_utc"]), exit_utc=iso(tg["exit_utc"]),
                            matures_utc=iso(tg["matures_utc"]), deadline_utc=iso(tg["deadline_utc"]),
                            cost_state=COST_PENDING)
        if st in TERMINAL:
            base["terminal_utc"] = iso(now)
        with store.con:
            store.con.execute("INSERT OR IGNORE INTO observations (obs_id, event_id, symbol, session, segment, "
                              "protocol_fp, state, reason, anchor_utc, entry_utc, exit_utc, matures_utc, deadline_utc, "
                              "cost_state, created_utc, updated_utc, terminal_utc) VALUES (:obs_id,:event_id,:symbol,"
                              ":session,:segment,:protocol_fp,:state,:reason,:anchor_utc,:entry_utc,:exit_utc,"
                              ":matures_utc,:deadline_utc,:cost_state,:created_utc,:updated_utc,:terminal_utc)",
                              {**base, "state": st, "reason": why})
        made += 1
    return {"observations_created": made}


# ============================================================================================ deadlines / acquisition
def reconcile_deadlines(store: Store, now: datetime) -> int:
    """FIRST on every invocation: anything still waiting at/after its ORIGINAL deadline becomes terminal (attempts and
    partial inputs are kept). Downtime never extends a deadline."""
    n = 0
    for o in store.q("SELECT * FROM observations WHERE state=? AND deadline_utc<=?", (SELECTED_WAITING, iso(now))):
        have = {r["part"]: r["outcome"] for r in store.q("SELECT part, outcome FROM inputs WHERE obs_id=?", (o["obs_id"],))}
        bars_done = have.get("entry_bar") == "RETRIEVED" and have.get("exit_bar") == "RETRIEVED"
        if bars_done:                                          # gross complete; only quotes failed -> keep the gross
            _finalise(store, o, now, quote_failure_terminal=True)
        else:
            with store.con:
                store.con.execute("UPDATE observations SET state=?, reason=?, updated_utc=?, terminal_utc=? WHERE "
                                  "obs_id=? AND state=?", (EXPIRED, f"deadline {o['deadline_utc']} passed; parts "
                                                           f"retrieved={sorted(k for k, v in have.items() if v == 'RETRIEVED')}",
                                                           iso(now), iso(now), o["obs_id"], SELECTED_WAITING))
        n += 1
    return n


def _store_part(store, obs_id, part, res, now):
    with store.con:
        if res["outcome"] == "RETRIEVED":
            blob = json.dumps(res["payload"], sort_keys=True)
            store.con.execute("INSERT OR IGNORE INTO inputs VALUES (?,?,?,?,?,?,?,?)",
                              (obs_id, part, json.dumps(res.get("scope"), sort_keys=True), "RETRIEVED", blob,
                               hashlib.sha256(blob.encode()).hexdigest(), iso(now), res.get("provider")))
        else:
            store.con.execute("INSERT INTO acquisition_errors (obs_id, part, error_class, detail, at_utc) VALUES "
                              "(?,?,?,?,?)", (obs_id, part, res["outcome"], str(res.get("detail"))[:300], iso(now)))


def acquire(store: Store, acquirer, now: datetime, *, max_observations: int = 200) -> dict:
    """Request ONLY missing parts of matured, non-terminal, selected observations, inside the acquirer's permitted
    window. Never requests anything for excluded/terminal observations or outside the activated population."""
    out = {"requested": 0, "errors": 0, "skipped_not_matured": 0, "skipped_window": 0}
    if acquirer is None:
        return {"acquirer": "NOT_CONFIGURED"}
    for o in store.q("SELECT * FROM observations WHERE state=? ORDER BY matures_utc, obs_id LIMIT ?",
                     (SELECTED_WAITING, max_observations)):
        if now < ts(o["matures_utc"]):
            out["skipped_not_matured"] += 1
            continue
        if not acquirer.permitted(now):
            out["skipped_window"] += 1
            continue
        have = {r["part"] for r in store.q("SELECT part FROM inputs WHERE obs_id=? AND outcome='RETRIEVED'",
                                          (o["obs_id"],))}
        e, x = ts(o["entry_utc"]), ts(o["exit_utc"])
        wants = {"entry_bar": ("bar", e), "exit_bar": ("bar", x - timedelta(minutes=1)),
                 "entry_quote": ("quote", e), "exit_quote": ("quote", x)}
        for part, (kind, t) in wants.items():
            if part in have:
                continue
            res = acquirer.bar(o["symbol"], t) if kind == "bar" else acquirer.quote(o["symbol"], t)
            out["requested"] += 1
            out["errors"] += res["outcome"] != "RETRIEVED"
            _store_part(store, o["obs_id"], part, res, now)
        with store.con:
            store.con.execute("UPDATE observations SET attempts=attempts+1, updated_utc=? WHERE obs_id=?",
                              (iso(now), o["obs_id"]))
        _finalise(store, store.q("SELECT * FROM observations WHERE obs_id=?", (o["obs_id"],))[0], now)
    return out


def _finalise(store: Store, o: dict, now: datetime, quote_failure_terminal: bool = False) -> None:
    """Terminal as soon as the gross is decided; cost from quotes when retrieved, else per the quote outcome."""
    if o["state"] != SELECTED_WAITING:
        return
    parts = {r["part"]: r for r in store.q("SELECT * FROM inputs WHERE obs_id=? AND outcome='RETRIEVED'",
                                           (o["obs_id"],))}
    if "entry_bar" not in parts or "exit_bar" not in parts:
        return
    e, x = ts(o["entry_utc"]), ts(o["exit_utc"])
    eb, ewhy = target_bar(json.loads(parts["entry_bar"]["payload_json"]), e)
    xb, xwhy = target_bar(json.loads(parts["exit_bar"]["payload_json"]), x - timedelta(minutes=1))
    if eb is None or xb is None:
        st = MISSING_ENTRY if eb is None else MISSING_EXIT
        with store.con:
            store.con.execute("UPDATE observations SET state=?, reason=?, cost_state=NULL, updated_utc=?, terminal_utc=? "
                              "WHERE obs_id=? AND state=?", (st, f"entry={ewhy} exit={xwhy}", iso(now), iso(now),
                                                             o["obs_id"], SELECTED_WAITING))
        return
    qs = {}
    for part, t in (("entry_quote", e), ("exit_quote", x)):
        if part in parts:
            qs[part] = select_quote(json.loads(parts[part]["payload_json"]), t)
    if len(qs) < 2 and not quote_failure_terminal:
        return                                                 # bars done, quotes still being acquired: wait
    if len(qs) == 2 and all(q[0] for q in qs.values()):
        cost_state = COST_OK
    elif len(qs) == 2:
        cost_state = COST_NO_QUOTE                             # retrieved, but no valid quote within 60 s
    else:
        cost_state = COST_ACQ_FAILED                           # quotes never obtained before the deadline
    qe = qs.get("entry_quote", (None,))[0] if cost_state == COST_OK else None
    qx = qs.get("exit_quote", (None,))[0] if cost_state == COST_OK else None
    r = compute(eb, xb, qe, qx)
    h = hashlib.sha256("".join(p["sha256"] for k, p in sorted(parts.items())).encode()).hexdigest()
    with store.con:
        store.con.execute("INSERT OR IGNORE INTO results VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
                          (o["obs_id"], o["protocol_fp"], json.dumps(eb), json.dumps(xb), json.dumps(qe),
                           json.dumps(qx), r["entry_px"], r["exit_px"], r["gross"], r["spread_cost"],
                           r["cost_adjusted"], h, iso(now)))
        store.con.execute("UPDATE observations SET state=?, reason=?, cost_state=?, updated_utc=?, terminal_utc=? "
                          "WHERE obs_id=? AND state=?", (MEASURED, "exact target bars retrieved", cost_state, iso(now),
                                                         iso(now), o["obs_id"], SELECTED_WAITING))


# ============================================================================================ reporting
def health(store: Store, act: dict, now: datetime) -> dict:
    """Operational health ONLY (no return values): counts by state, per session, acquisition errors by class."""
    st = {r["state"]: r["n"] for r in store.q("SELECT state, COUNT(*) n FROM observations GROUP BY 1")}
    deliv = {r["delivery_class"]: r["n"] for r in store.q("SELECT delivery_class, COUNT(*) n FROM deliveries GROUP BY 1")}
    per = {s: {} for s in act["sessions"]}
    for r in store.q("SELECT session, state, COUNT(*) n FROM observations GROUP BY 1, 2"):
        per.setdefault(r["session"], {})[r["state"]] = r["n"]
    errs = {r["error_class"]: r["n"] for r in store.q("SELECT error_class, COUNT(*) n FROM acquisition_errors GROUP BY 1")}
    gaps = [s for s, v in per.items() if v and set(v) <= {EXPIRED}]
    return {"now": iso(now), "deliveries_by_class": deliv, "observations_by_state": st, "per_session": per,
            "acquisition_errors": errs, "sessions_where_every_selected_observation_expired": gaps,
            "endpoint_utc": iso(act["endpoint_utc"]), "complete": study_complete(store, act, now)}


def study_complete(store: Store, act: dict, now: datetime) -> bool:
    if now < act["endpoint_utc"]:
        return False
    return not store.q("SELECT 1 FROM observations WHERE state=? LIMIT 1", (SELECTED_WAITING,))


def final_report(store: Store, act: dict, now: datetime) -> dict:
    """Descriptive outcome report -- REFUSED before the fixed endpoint (no rolling judgements)."""
    if not study_complete(store, act, now):
        return {"status": "NOT_AVAILABLE_BEFORE_ENDPOINT", "endpoint_utc": iso(act["endpoint_utc"])}
    out = {}
    for seg in [r["segment"] for r in store.q("SELECT DISTINCT segment FROM observations")]:
        obs = store.q("SELECT * FROM observations WHERE segment=?", (seg,))
        res = {r["obs_id"]: r for r in store.q("SELECT r.* FROM results r JOIN observations o USING(obs_id) "
                                               "WHERE o.segment=?", (seg,))}
        sel = [o for o in obs if o["state"] in SELECTED]
        g = [res[o["obs_id"]]["gross"] for o in sel if o["obs_id"] in res]
        c = [res[o["obs_id"]]["cost_adjusted"] for o in sel if o["obs_id"] in res
             and res[o["obs_id"]]["cost_adjusted"] is not None]

        def summ(xs):
            if not xs:
                return None
            q = sorted(xs)
            return {"n": len(xs), "mean": statistics.fmean(xs), "median": statistics.median(xs),
                    "positive_fraction": sum(x > 0 for x in xs) / len(xs),
                    "p05": q[int(0.05 * (len(q) - 1))], "p10": q[int(0.10 * (len(q) - 1))], "worst5": q[:5]}
        by_sym, by_sess = {}, {}
        for o in sel:
            if o["obs_id"] in res:
                by_sym[o["symbol"]] = by_sym.get(o["symbol"], 0) + 1
                by_sess[o["session"]] = by_sess.get(o["session"], 0) + 1
        out[seg] = {"label": PDM_V1.label,
                    "counts": {s: sum(1 for o in obs if o["state"] == s) for s in sorted({o["state"] for o in obs})},
                    "selected": len(sel), "gross_measured": len(g), "cost_adjusted_measured": len(c),
                    "gross_coverage": len(g) / len(sel) if sel else None,
                    "cost_coverage": len(c) / len(sel) if sel else None,
                    "gross": summ(g), "cost_adjusted": summ(c),
                    "concentration": {"sessions": len(by_sess), "symbols": len(by_sym),
                                      "max_session_share": max(by_sess.values()) / len(g) if g else None},
                    "note": ("alert-level averages, NOT portfolio performance; alerts within a session share market "
                             "moves -- the effective sample is closer to the number of sessions; no PASS threshold")}
    return out


# ============================================================================================ entry point
def run(env=None, *, store_root: Path | None = None, acquirer=None, now: datetime | None = None,
        outbox_path: Path | None = None, promotion_path: Path | None = None, trace_lookup=None) -> dict:
    """Disabled by default. When enabled with an approved config: reconcile deadlines FIRST, then register/select,
    then acquire (bounded), then reconcile again. Never touches anything when disabled or unapproved."""
    env = os.environ if env is None else env
    if str(env.get(ENABLE_ENV, "")).strip() != "1":
        return {"state": "DISABLED"}
    now = now or datetime.now(UTC)
    try:
        act = load_activation(env.get(CONFIG_ENV))
    except NotApproved as exc:
        return {"state": "NOT_APPROVED", "reason": str(exc)}
    if now < act["boundary_utc"]:
        return {"state": "BEFORE_ACTIVATION", "boundary_utc": iso(act["boundary_utc"])}
    opp = REPO / "results" / "opportunity"
    store = Store(store_root or REPO / "results" / "post_delivery_markout")
    with store.con:
        rid = store.con.execute("INSERT INTO runs (started_utc) VALUES (?)", (iso(now),)).lastrowid
    expired_first = reconcile_deadlines(store, now)
    reg = register(store, act=act, outbox_path=outbox_path or opp / "promotion_signal_notifications.db",
                   promotion_path=promotion_path or opp / "promotion.db", now=now, trace_lookup=trace_lookup)
    acq = acquire(store, acquirer, now)
    expired_after = reconcile_deadlines(store, now)
    summary = {"state": "ENABLED", "expired_before": expired_first, **reg, "acquisition": acq,
               "expired_after": expired_after, "health": health(store, act, now)}
    with store.con:
        store.con.execute("UPDATE runs SET finished_utc=?, summary_json=? WHERE id=?",
                          (iso(datetime.now(UTC)), json.dumps(summary, default=str), rid))
    return summary
