"""
POST_DELIVERY_ALERT_MARKOUT_V1 -- post-delivery price markout under stated cost assumptions (INACTIVE).

Protocol: docs/research/protocols/POST_DELIVERY_ALERT_MARKOUT_V1.md. Answers ONE question: after a Telegram research
opportunity was delivered, did a useful price move remain under declared timing and cost assumptions? It is NOT
realised profit, an executable fill or a portfolio return, and it is separate from promotion paper_outcomes (which
start at the market-data timestamp), VR_PAPER_V1, the V2 forward tracker and every frozen study.

Isolation / safety:
* DISABLED by default: ``run`` does nothing unless ``TALONX_PDM_ENABLED=1`` AND an explicit timezone-aware
  activation boundary is configured. No scheduler / supervisor / runtime registration exists for this module.
* Source stores (promotion outbox, promotion.db) are opened ``mode=ro``; the only writable store is its own
  ``results/post_delivery_markout/pdm.db``. Telegram delivery is never read-modified, delayed or gated.
* Price acquisition is a separate, injected ``fetch`` callable (none is wired: the inactive module issues no provider
  request and holds no subscription). ``measure`` is a pure function of the stored inputs.
* Idempotent: one row per outbox ``event_id``; re-registration and re-processing are no-ops for settled rows.
"""
from __future__ import annotations

import hashlib
import json
import os
import sqlite3
import statistics
from dataclasses import asdict, dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path

UTC = timezone.utc
REPO = Path(__file__).resolve().parents[1]
ENABLE_ENV = "TALONX_PDM_ENABLED"
ACTIVATION_ENV = "TALONX_PDM_ACTIVATION_UTC"
EVENT_TYPE = "RESEARCH_OPPORTUNITY"
REVIEW_REASON = "RESEARCH_REVIEW_ALERT"

# observation states
WAITING, MATURE = "WAITING_FOR_DATA", "MATURE"
MISSING_ENTRY, MISSING_EXIT, MISSING_TIMEOUT = "MISSING_ENTRY", "MISSING_EXIT", "MISSING_DATA_TIMEOUT"
AMBIGUOUS, REPEAT, LATE, OUT_SESSION, INVALID = ("AMBIGUOUS_DELIVERY", "REPEAT_SAME_WINDOW", "LATE_SESSION_INELIGIBLE",
                                                 "OUT_OF_SESSION", "INVALID")
TERMINAL = {MATURE, MISSING_ENTRY, MISSING_EXIT, MISSING_TIMEOUT, AMBIGUOUS, REPEAT, LATE, OUT_SESSION, INVALID}
EXCLUDED = {AMBIGUOUS, REPEAT, LATE, OUT_SESSION, INVALID}
COST_UNAVAILABLE = "COST_UNAVAILABLE"


@dataclass(frozen=True)
class PDMConfig:
    version: str = "POST_DELIVERY_ALERT_MARKOUT_V1"
    anchor: str = "outbox.sent_at_utc (local persistence after Telegram API acceptance)"
    reaction_delay_s: int = 300
    horizon_min: int = 30
    entry_window_min: int = 5           # first traded bar starting in [T_e, T_e + 5 min)
    exit_window_min: int = 5            # last traded bar starting in [T_x - 5 min, T_x - 1 min]
    quote_window_s: int = 60            # spread = median quoted spread over [T_e, T_e + 60 s)
    cost_allowance_bps: float = 5.0
    maturity_lag_min: int = 60          # after the regular close
    max_wait_sessions: int = 2
    observation_sessions: int = 20
    price_adjustment: str = "raw"
    feed: str = "sip"
    label: str = "Post-delivery price markout under stated cost assumptions"

    def fingerprint(self) -> str:
        return hashlib.sha256(json.dumps(asdict(self), sort_keys=True).encode()).hexdigest()[:16]


PDM_V1 = PDMConfig()


def ts(s) -> datetime:
    return datetime.fromisoformat(str(s).replace("Z", "+00:00"))


def iso(t: datetime | None) -> str | None:
    return t.astimezone(UTC).isoformat() if t else None


def ceil_minute(t: datetime) -> datetime:
    f = t.replace(second=0, microsecond=0)
    return f if f == t else f + timedelta(minutes=1)


# ============================================================================================ pure timing / measure
def schedule(delivered: datetime, cfg: PDMConfig = PDM_V1, window_for=None) -> dict:
    """Entry / exit times for a delivery anchor. ``window_for(t) -> (phase, TradingWindow|None)`` (default:
    talonx_opportunity.phases.phase_at). Never moves the anchor earlier; never extends past the regular close."""
    if window_for is None:
        from talonx_opportunity.phases import phase_at as window_for
    phase, w = window_for(delivered)
    if w is None or phase != "REGULAR":
        return {"state": OUT_SESSION, "phase": phase}
    react = delivered + timedelta(seconds=cfg.reaction_delay_s)
    if react >= w.close_utc:
        return {"state": LATE, "reason": "reaction delay reaches the regular close", "window_id": w.window_id}
    t_e = ceil_minute(react)
    t_x = t_e + timedelta(minutes=cfg.horizon_min)
    if t_x > w.close_utc:
        return {"state": LATE, "reason": "exit after the regular close (no extension)", "window_id": w.window_id}
    return {"state": WAITING, "window_id": w.window_id, "entry_utc": t_e, "exit_utc": t_x, "close_utc": w.close_utc,
            "matures_utc": w.close_utc + timedelta(minutes=cfg.maturity_lag_min)}


def measure(entry_utc: datetime, exit_utc: datetime, bars: list[dict], quotes: list[dict] | None,
            cfg: PDMConfig = PDM_V1) -> dict:
    """Pure: entry = open of the first traded bar starting in [T_e, T_e+5m); exit = close of the last traded bar
    starting in [T_x-5m, T_x-1m]; cost = median quoted spread in [T_e, T_e+60s) (bps of mid) + allowance, once.
    Bars are keyed by MARKET time (start), never by arrival time. Missing data is a state, never a zero return."""
    by = sorted((b for b in bars if float(b.get("v") or 0) > 0), key=lambda b: ts(b["t"]))
    e_lo, e_hi = entry_utc, entry_utc + timedelta(minutes=cfg.entry_window_min)
    entry = next((b for b in by if e_lo <= ts(b["t"]) < e_hi), None)
    if entry is None:
        return {"state": MISSING_ENTRY}
    x_lo, x_hi = exit_utc - timedelta(minutes=cfg.exit_window_min), exit_utc - timedelta(minutes=1)
    exits = [b for b in by if x_lo <= ts(b["t"]) <= x_hi and ts(b["t"]) > ts(entry["t"])]
    if not exits:
        return {"state": MISSING_EXIT, "entry_bar_utc": entry["t"], "entry_px": float(entry["o"])}
    ex = exits[-1]
    e_px, x_px = float(entry["o"]), float(ex["c"])
    gross = (x_px / e_px - 1.0) * 1e4
    spreads = []
    for q in quotes or []:
        try:
            t, bid, ask = ts(q["t"]), float(q["bp"]), float(q["ap"])
        except (KeyError, TypeError, ValueError):
            continue
        if entry_utc <= t < entry_utc + timedelta(seconds=cfg.quote_window_s) and bid > 0 and ask >= bid:
            spreads.append((ask - bid) / ((ask + bid) / 2) * 1e4)
    out = {"state": MATURE, "entry_bar_utc": entry["t"], "entry_px": e_px, "exit_bar_utc": ex["t"], "exit_px": x_px,
           "gross_bps": round(gross, 4), "n_quotes": len(spreads)}
    if spreads:
        cost = statistics.median(spreads) + cfg.cost_allowance_bps
        out.update(spread_bps=round(statistics.median(spreads), 4), cost_bps=round(cost, 4),
                   net_bps=round(gross - cost, 4))
    else:
        out.update(spread_bps=None, cost_bps=None, net_bps=None, cost_state=COST_UNAVAILABLE)
    return out


# ============================================================================================ store
SCHEMA = """
CREATE TABLE IF NOT EXISTS meta (k TEXT PRIMARY KEY, v TEXT);
CREATE TABLE IF NOT EXISTS observations (
    event_id TEXT PRIMARY KEY, segment TEXT, protocol_fp TEXT, symbol TEXT, window_id TEXT, promotion_id TEXT,
    promotion_policy_fp TEXT, data_as_of_utc TEXT, decision_utc TEXT, outbox_created_utc TEXT, delivered_utc TEXT,
    attempts INTEGER, last_error TEXT, state TEXT, reason TEXT, entry_utc TEXT, exit_utc TEXT, matures_utc TEXT,
    source_sha256 TEXT, registered_utc TEXT, updated_utc TEXT);
CREATE TABLE IF NOT EXISTS inputs (event_id TEXT PRIMARY KEY, fetched_utc TEXT, bars_json TEXT, quotes_json TEXT,
    sha256 TEXT, provider TEXT);
CREATE TABLE IF NOT EXISTS results (event_id TEXT PRIMARY KEY, protocol_fp TEXT, state TEXT, entry_bar_utc TEXT,
    entry_px REAL, exit_bar_utc TEXT, exit_px REAL, gross_bps REAL, spread_bps REAL, cost_bps REAL, net_bps REAL,
    n_quotes INTEGER, cost_state TEXT, inputs_sha256 TEXT, measured_utc TEXT);
"""


def default_root() -> Path:
    return REPO / "results" / "post_delivery_markout"


class Store:
    def __init__(self, root: Path | None = None):
        self.root = Path(root or default_root())
        self.root.mkdir(parents=True, exist_ok=True)
        self.con = sqlite3.connect(self.root / "pdm.db", timeout=30)
        self.con.row_factory = sqlite3.Row
        self.con.executescript(SCHEMA)

    def rows(self, where: str = "1=1", args=()) -> list[dict]:
        return [dict(r) for r in self.con.execute(f"SELECT * FROM observations WHERE {where}", args)]


def _ro(p: Path):
    if not Path(p).exists():
        return None
    c = sqlite3.connect(f"file:{p}?mode=ro", uri=True, timeout=10)
    c.row_factory = sqlite3.Row
    return c


def segment_key(cfg: PDMConfig, promotion_policy_fp: str | None, dtu_policy_fp: str | None, delivery_mode: str | None):
    return "|".join([cfg.version, cfg.fingerprint(), promotion_policy_fp or "UNKNOWN", dtu_policy_fp or "UNKNOWN",
                     delivery_mode or "UNKNOWN"])


def register(store: Store, *, activation_utc: datetime, outbox_path: Path, promotion_path: Path,
             cfg: PDMConfig = PDM_V1, now: datetime | None = None, dtu_policy_fp_for=None,
             delivery_mode: str = "RESEARCH_REVIEW", window_for=None) -> dict:
    """Register newly delivered review alerts at/after ``activation_utc`` (read-only sources; idempotent)."""
    if activation_utc is None or activation_utc.tzinfo is None:
        raise ValueError("an explicit timezone-aware activation boundary is required")
    now = now or datetime.now(UTC)
    ob, pc = _ro(outbox_path), _ro(promotion_path)
    if ob is None or pc is None:
        return {"registered": 0, "note": "source store missing"}
    a = iso(activation_utc)
    rows = [dict(r) for r in ob.execute(
        "SELECT event_id, destination, event_type, producer, state, attempts, last_error, created_at_utc, sent_at_utc "
        "FROM ops_notification_outbox WHERE event_type=? AND created_at_utc>=? AND sent_at_utc>=? "
        "ORDER BY sent_at_utc, event_id", (EVENT_TYPE, a, a))]
    ob.close()
    scheduled = (WAITING, MATURE, MISSING_ENTRY, MISSING_EXIT, MISSING_TIMEOUT)
    seen_first = {(r["window_id"], r["symbol"]) for r in store.rows(
        f"state IN ({','.join('?' * len(scheduled))})", scheduled)}
    new = 0
    for r in rows:
        if store.con.execute("SELECT 1 FROM observations WHERE event_id=?", (r["event_id"],)).fetchone():
            continue
        p = pc.execute("SELECT promotion_id, symbol, window_id, state, reason_code, policy_fp, data_as_of_utc, "
                       "decision_utc FROM promotions WHERE signal_event_id=?", (r["event_id"],)).fetchone()
        src = json.dumps({"outbox": r, "promotion": dict(p) if p else None}, sort_keys=True, default=str)
        rec = {"event_id": r["event_id"], "symbol": p["symbol"] if p else None, "window_id": p["window_id"] if p else None,
               "promotion_id": p["promotion_id"] if p else None, "promotion_policy_fp": p["policy_fp"] if p else None,
               "data_as_of_utc": p["data_as_of_utc"] if p else None, "decision_utc": p["decision_utc"] if p else None,
               "outbox_created_utc": r["created_at_utc"], "delivered_utc": r["sent_at_utc"],
               "attempts": r["attempts"], "last_error": r["last_error"], "entry_utc": None, "exit_utc": None,
               "matures_utc": None, "reason": None}
        if (p is None or r["state"] != "SENT" or r["destination"] != "TRADE_EVENT" or p["state"] != "PROMOTED_SIGNAL"
                or p["reason_code"] != REVIEW_REASON):
            rec["state"], rec["reason"] = INVALID, "source row failed validation"
        elif (r["attempts"] or 0) > 1 or r["last_error"]:
            rec["state"], rec["reason"] = AMBIGUOUS, f"attempts={r['attempts']} last_error={bool(r['last_error'])}"
        else:
            sch = schedule(ts(r["sent_at_utc"]), cfg, window_for)
            rec["state"], rec["reason"] = sch["state"], sch.get("reason")
            if sch["state"] == WAITING:
                key = (p["window_id"], p["symbol"])
                if key in seen_first:
                    rec["state"], rec["reason"] = REPEAT, "first delivered alert for this symbol/window kept"
                else:
                    seen_first.add(key)
                    rec.update(entry_utc=iso(sch["entry_utc"]), exit_utc=iso(sch["exit_utc"]),
                               matures_utc=iso(sch["matures_utc"]))
        dtu = dtu_policy_fp_for(rec["window_id"]) if dtu_policy_fp_for and rec["window_id"] else None
        with store.con:
            store.con.execute(
                "INSERT OR IGNORE INTO observations VALUES (:event_id,:segment,:protocol_fp,:symbol,:window_id,"
                ":promotion_id,:promotion_policy_fp,:data_as_of_utc,:decision_utc,:outbox_created_utc,:delivered_utc,"
                ":attempts,:last_error,:state,:reason,:entry_utc,:exit_utc,:matures_utc,:source_sha256,:registered_utc,"
                ":updated_utc)",
                {**rec, "segment": segment_key(cfg, rec["promotion_policy_fp"], dtu, delivery_mode),
                 "protocol_fp": cfg.fingerprint(), "source_sha256": hashlib.sha256(src.encode()).hexdigest(),
                 "registered_utc": iso(now), "updated_utc": iso(now)})
        new += 1
    pc.close()
    return {"registered": new}


def sessions_after(t: datetime, n: int) -> datetime:
    """The regular close of the n-th trading session strictly after ``t``'s date (XNYS calendar, half days)."""
    from talonx_opportunity.phases import trading_window
    d, left = t.date(), n
    while True:
        d += timedelta(days=1)
        try:
            w = trading_window(d)
        except ValueError:
            continue
        if w is not None:
            left -= 1
            if left == 0:
                return w.close_utc


def process(store: Store, *, fetch, now: datetime | None = None, cfg: PDMConfig = PDM_V1,
            sessions_after=sessions_after) -> dict:
    """Measure matured WAITING observations. ``fetch(symbol, start_utc, end_utc) -> (bars, quotes, provider)`` or
    None when unavailable. Bounded: after ``max_wait_sessions`` sessions past maturity -> MISSING_DATA_TIMEOUT."""
    now = now or datetime.now(UTC)
    out = {"measured": 0, "timeout": 0, "waiting": 0, "acquisition_not_configured": 0}
    for o in store.rows("state=?", (WAITING,)):
        mat = ts(o["matures_utc"])
        if now < mat:
            out["waiting"] += 1
            continue
        got = None
        have = store.con.execute("SELECT bars_json, quotes_json, sha256 FROM inputs WHERE event_id=?",
                                 (o["event_id"],)).fetchone()
        if have is not None:
            got = (json.loads(have[0]), json.loads(have[1]) if have[1] else None, have[2])
        elif fetch is not None:
            res = fetch(o["symbol"], ts(o["entry_utc"]), ts(o["exit_utc"]))
            if res is not None:
                bars, quotes, provider = res
                blob = json.dumps({"bars": bars, "quotes": quotes}, sort_keys=True)
                h = hashlib.sha256(blob.encode()).hexdigest()
                with store.con:
                    store.con.execute("INSERT OR IGNORE INTO inputs VALUES (?,?,?,?,?,?)",
                                      (o["event_id"], iso(now), json.dumps(bars), json.dumps(quotes) if quotes is not None
                                       else None, h, provider))
                got = (bars, quotes, h)
        if got is None and fetch is None:
            out["acquisition_not_configured"] += 1      # never a timeout: no provider is wired (inactive build)
            continue
        if got is None:
            limit = sessions_after(mat, cfg.max_wait_sessions)
            if now >= limit:
                with store.con:
                    store.con.execute("UPDATE observations SET state=?, reason=?, updated_utc=? WHERE event_id=? AND "
                                      "state=?", (MISSING_TIMEOUT, "no price data within the bounded wait", iso(now),
                                                  o["event_id"], WAITING))
                out["timeout"] += 1
            else:
                out["waiting"] += 1
            continue
        m = measure(ts(o["entry_utc"]), ts(o["exit_utc"]), got[0], got[1], cfg)
        with store.con:
            store.con.execute("INSERT OR IGNORE INTO results VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                              (o["event_id"], cfg.fingerprint(), m["state"], m.get("entry_bar_utc"), m.get("entry_px"),
                               m.get("exit_bar_utc"), m.get("exit_px"), m.get("gross_bps"), m.get("spread_bps"),
                               m.get("cost_bps"), m.get("net_bps"), m.get("n_quotes"), m.get("cost_state"), got[2],
                               iso(now)))
            store.con.execute("UPDATE observations SET state=?, updated_utc=? WHERE event_id=? AND state=?",
                              (m["state"], iso(now), o["event_id"], WAITING))
        out["measured"] += 1
    return out


def report(store: Store) -> dict:
    """Descriptive per-segment summary (no PASS threshold; alert-level, not portfolio)."""
    segs: dict[str, dict] = {}
    for o in store.rows():
        s = segs.setdefault(o["segment"], {"states": {}, "gross": [], "net": [], "by_symbol": {}, "by_window": {}})
        s["states"][o["state"]] = s["states"].get(o["state"], 0) + 1
        r = store.con.execute("SELECT gross_bps, net_bps FROM results WHERE event_id=?", (o["event_id"],)).fetchone()
        if r and o["state"] == MATURE:
            s["gross"].append(r[0])
            if r[1] is not None:
                s["net"].append(r[1])
            s["by_symbol"][o["symbol"]] = s["by_symbol"].get(o["symbol"], 0) + 1
            s["by_window"][o["window_id"]] = s["by_window"].get(o["window_id"], 0) + 1

    def summ(xs):
        if not xs:
            return None
        q = sorted(xs)
        return {"n": len(xs), "mean": round(statistics.fmean(xs), 3), "median": round(statistics.median(xs), 3),
                "positive_fraction": round(sum(x > 0 for x in xs) / len(xs), 4),
                "p05": q[int(0.05 * (len(q) - 1))], "p10": q[int(0.10 * (len(q) - 1))], "worst5": q[:5]}
    out = {}
    for k, s in segs.items():
        eligible = sum(v for st, v in s["states"].items() if st not in EXCLUDED)
        out[k] = {"label": PDM_V1.label, "states": s["states"], "eligible": eligible,
                  "measured": s["states"].get(MATURE, 0),
                  "coverage": round(s["states"].get(MATURE, 0) / eligible, 4) if eligible else None,
                  "gross_bps": summ(s["gross"]), "net_bps": summ(s["net"]),
                  "net_missing_cost": len(s["gross"]) - len(s["net"]),
                  "concentration": {"windows": len(s["by_window"]), "symbols": len(s["by_symbol"]),
                                    "top5_symbol_share": round(sum(sorted(s["by_symbol"].values())[-5:]) /
                                                               max(1, sum(s["by_symbol"].values())), 4)},
                  "note": "alert-level averages, not portfolio performance; alerts within a session are correlated"}
    return out


def config_from_env(env=None) -> tuple[bool, datetime | None, str]:
    env = os.environ if env is None else env
    if str(env.get(ENABLE_ENV, "")).strip() != "1":
        return False, None, "DISABLED"
    raw = str(env.get(ACTIVATION_ENV, "")).strip()
    try:
        a = ts(raw) if raw else None
    except ValueError:
        a = None
    if a is None or a.tzinfo is None:
        return False, None, "NO_VALID_ACTIVATION_BOUNDARY"
    return True, a, "ENABLED"


def run(env=None, *, store_root: Path | None = None, fetch=None, now: datetime | None = None,
        outbox_path: Path | None = None, promotion_path: Path | None = None) -> dict:
    """Entry point. Disabled by default: returns without opening, creating or fetching anything."""
    enabled, activation, why = config_from_env(env)
    if not enabled:
        return {"state": why}
    opp = REPO / "results" / "opportunity"
    store = Store(store_root)
    reg = register(store, activation_utc=activation, outbox_path=outbox_path or opp / "promotion_signal_notifications.db",
                   promotion_path=promotion_path or opp / "promotion.db", now=now)
    proc = process(store, fetch=fetch, now=now)
    return {"state": "ENABLED", "activation_utc": iso(activation), **reg, **proc}
