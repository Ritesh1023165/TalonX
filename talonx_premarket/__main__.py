"""
python -m talonx_premarket {universe | replay | run | status}

  universe                 build + save the broad universe (Alpaca assets x SEC tickers)
  replay --date D          causal shadow replay of session D (read-only; nothing routed)
  run [--deliver]          LIVE pre-market canary for today's XNYS session; research alerts only.
                           Without --deliver alerts are recorded, never sent. With --deliver they are
                           enqueued to the isolated RESEARCH destination and drained -- and sent only if
                           RESEARCH resolves as enabled (explicit double opt-in, distinct bot AND chat).
  status                   print today's status file

Never trades. Never writes a V2 ledger/outbox. Never emits a V2 TRADE_EVENT.
"""
from __future__ import annotations

import argparse
import json
import logging
import os
import sys
import time
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
OUT_ROOT = REPO_ROOT / "results" / "premarket_research"
UNIVERSE_PATH = OUT_ROOT / "universe.json"
RESEARCH_NOTIFY_DB = OUT_ROOT / "premarket_research_notifications.db"
DEFAULT_LEDGER = Path.home() / ".talonx" / "ingestion_ledger.db"
PROTECTED_DB_NAMES = {"v2_release_rc1.db", "v2_release_rc1_notifications.db", "v2_lane.db", "notifications.db"}

logger = logging.getLogger("talonx_premarket")


def _env(env_file: str | None = None):
    """Loads .env with override=False (a process-scoped value always wins). ``--env-file`` lets the engine run
    from a separate worktree while reading the main checkout's .env in place (never copied)."""
    try:
        from dotenv import load_dotenv
        load_dotenv(Path(env_file) if env_file else REPO_ROOT / ".env", override=False)
    except Exception:  # noqa: BLE001
        pass


def _data():
    from talonx_premarket.alpaca_data import AlpacaData
    kid, sec = os.environ.get("APCA_API_KEY_ID", ""), os.environ.get("APCA_API_SECRET_KEY", "")
    if not (kid and sec):
        raise SystemExit("APCA_API_KEY_ID / APCA_API_SECRET_KEY not configured")
    return AlpacaData(key_id=kid, secret=sec)


def _sec():
    from talonx_premarket.catalysts import SecSubmissions
    ua = os.environ.get("TALONX_SEC_USER_AGENT", "").strip()
    if not ua:
        logger.warning("TALONX_SEC_USER_AGENT not set -- SEC catalyst lookup disabled")
        return None
    return SecSubmissions(user_agent=ua)


def _v2_scope(explicit: str | None) -> set[str]:
    from talonx_premarket.engine import v2_scope_from_log
    if explicit:
        return v2_scope_from_log(explicit)
    logs = sorted(REPO_ROOT.glob("results/prospective_*/logs/v2_companion.log"))
    for p in reversed(logs):
        s = v2_scope_from_log(p)
        if s:
            return s
    return set()


def cmd_universe(args) -> int:
    from talonx_premarket.universe import build_universe, save, summarize
    data = _data()
    assets = data.assets()
    ct_path = Path.home() / ".talonx" / "intelligence" / "company_tickers.json"
    members = build_universe(assets, json.loads(ct_path.read_text(encoding="utf-8")))
    save(members, Path(args.out))
    print(json.dumps(summarize(members), indent=1))
    return 0


def _load_universe(path: Path, *, max_age_h: float = 24.0):
    from talonx_premarket.universe import load
    if not path.exists() or (time.time() - path.stat().st_mtime) > max_age_h * 3600:
        raise SystemExit(f"universe file missing or older than {max_age_h:.0f}h: run `python -m talonx_premarket "
                         f"universe` first ({path})")
    return load(path)


def cmd_replay(args) -> int:
    from talonx_premarket.replay import run_replay
    day = date.fromisoformat(args.date)
    out = Path(args.out or (OUT_ROOT / f"replay_{day.isoformat()}"))
    universe = _load_universe(Path(args.universe), max_age_h=args.universe_max_age_h)
    res = run_replay(day=day, universe=universe, data=_data(), sec=_sec(), ledger_path=str(DEFAULT_LEDGER),
                     v2_scope=_v2_scope(args.v2_scope_log), out_dir=out)
    (out / "replay_result.json").write_text(json.dumps(res, indent=1, default=str), encoding="utf-8")
    print(f"replay complete: {len(res['alerts'])} alert events, {len(res['candidates'])} candidates -> {out}")
    return 0


def _router(deliver: bool, notify_db: Path):
    """RESEARCH routing only. The destination constant is fixed here; there is no fallback.

    Returns ``(route, drain, sync, info)``. ``route`` returns the ROUTING result (``RECORDED_NOT_DELIVERED`` /
    ``ENQUEUED_RESEARCH`` / ``ENQUEUED_RESEARCH_DESTINATION_DISABLED``) -- enqueued is NOT sent. ``sync`` copies the
    outbox's real delivery state (PENDING / SENT / RETRY / FAILED / EXPIRED / HELD / AMBIGUOUS) back onto the
    research alerts; a candidate is ``delivered`` only once one of its alerts is actually SENT."""
    from talonx_ops.notify import RESEARCH, resolve_destination_config
    from talonx_ops.notify.outbox import NotifyStore
    if notify_db.name in PROTECTED_DB_NAMES:
        raise SystemExit(f"refusing to use a protected notification DB for research alerts: {notify_db}")
    cfg = resolve_destination_config(RESEARCH)
    store = NotifyStore(str(notify_db)) if deliver else None

    def route(alert: dict) -> str:
        if not deliver:
            return "RECORDED_NOT_DELIVERED"
        deliver_by = (datetime.fromisoformat(alert["decision_utc"]) + timedelta(minutes=30)).isoformat()
        store.enqueue(event_id=alert["alert_id"], destination=RESEARCH,
                      event_type=f"PREMARKET_RESEARCH_{alert['alert_type']}", producer="talonx_premarket",
                      dedup_key=alert["alert_id"], payload_text=alert["text"],
                      provenance={"candidate_id": alert["candidate_id"], "symbol": alert["symbol"],
                                  "lane": "PREMARKET_RESEARCH", "not_a_trade_event": True},
                      deliver_by_utc=deliver_by)
        return "ENQUEUED_RESEARCH" if cfg.enabled else "ENQUEUED_RESEARCH_DESTINATION_DISABLED"

    def drain() -> dict | None:
        if not deliver:
            return None
        from talonx_ops.notify.worker import drain as _drain
        return _drain(store, destination=RESEARCH)

    def sync(research_store, session_date: str) -> dict:
        """Returns counts by delivery state for this session's alerts."""
        import sqlite3
        counts: dict[str, int] = {}
        alerts = research_store.alerts_for(session_date)
        states: dict[str, str] = {}
        if deliver:
            ids = [a["alert_id"] for a in alerts if str(a["routed"]).startswith("ENQUEUED")]
            if ids:
                con = sqlite3.connect(f"file:{notify_db}?mode=ro", uri=True, timeout=5.0)
                try:
                    for i in range(0, len(ids), 500):
                        chunk = ids[i:i + 500]
                        for eid, st in con.execute(
                                "SELECT event_id, state FROM ops_notification_outbox WHERE destination=? AND "
                                f"event_id IN ({','.join('?' * len(chunk))})", [RESEARCH, *chunk]):
                            states[eid] = st
                finally:
                    con.close()
        now = datetime.now(timezone.utc).isoformat()
        for a in alerts:
            r = str(a["routed"])
            st = (states.get(a["alert_id"], "UNKNOWN") if r.startswith("ENQUEUED")
                  else "SUPPRESSED" if r.startswith("SUPPRESSED") else r)
            if st != a.get("delivery_state"):
                research_store.set_delivery_state(a["alert_id"], st, now)
            counts[st] = counts.get(st, 0) + 1
        return counts

    return route, drain, sync, {"deliver_flag": deliver, "destination": RESEARCH,
                                "bot": "LAB" if cfg.enabled else None,        # identity label only, never the token
                                "research_destination_enabled": cfg.enabled,
                                "research_destination_reason": cfg.reason}


def session_dir_for(day: date) -> Path:
    """Research session directories are keyed by the XNYS (America/New_York) session date, never UTC/UK."""
    return OUT_ROOT / day.isoformat()


def run_session(*, eng, sd, cfg, data, base: dict, out: Path, drain, sync, clock=None, sleep=time.sleep,
                track_interval_s: float = 600.0) -> str:
    """The live loop, dependency-injectable for rehearsal/tests. Returns the end state."""
    from talonx_premarket.engine import write_status
    from talonx_premarket.session import scan_schedule
    clock = clock or (lambda: datetime.now(timezone.utc))
    stop_flag = out / "stop.flag"
    status_path = out / "status.json"
    session = sd.day.isoformat()
    state = {"last_scan": None, "delivery": {}, "outcomes": {}}

    def status(st: str, **extra) -> None:
        write_status(status_path, {**base, "heartbeat_utc": clock().isoformat(), "state": st, **state, **extra})

    resumed = eng.resume_pending_routes()
    if resumed:
        print(f"re-routed {resumed} alert(s) persisted before a restart (idempotent)")
    start = clock()
    sched = [t for t in scan_schedule(sd.day, cfg) if t >= start - timedelta(seconds=30)]
    for t in sched:
        while clock() < t:
            if stop_flag.exists():
                status("STOPPED_BY_FLAG")
                return "STOPPED_BY_FLAG"
            status("WAITING_FOR_SCAN", next_scan_utc=t.isoformat())
            sleep(min(15.0, max(0.5, (t - clock()).total_seconds())))
        now = clock()
        if now >= sd.open_utc:
            break                                   # never run a PRE-MARKET scan at/after the regular open
        if stop_flag.exists():
            status("STOPPED_BY_FLAG")
            return "STOPPED_BY_FLAG"
        r = eng.scan(now)
        dr = drain()
        state["delivery"] = sync(eng.store, session)
        state["last_scan"] = {"decision_utc": r.decision_utc, "data_as_of_utc": r.data_as_of_utc, "phase": r.phase,
                              "funnel": r.funnel, "alerts": [(a["symbol"], a["alert_type"], a["routed"])
                                                             for a in r.alerts],
                              "duration_s": r.duration_s, "requests_total": data.requests,
                              "data_errors_total": len(data.errors), "drain": dr}
        print(f"{r.decision_utc[11:19]}Z {r.phase} ready={r.funnel.get('DATA_READY', 0)} "
              f"gaps={r.funnel['provider']['DATA_GAPS']} worthy={r.funnel.get('ALERT_WORTHY', 0)} "
              f"alerts={len(r.alerts)} {r.duration_s}s", flush=True)
        status("SCANNED")
    # post-open outcome tracking (evaluation only) until the close is visible through the SIP delay
    end = sd.close_utc + timedelta(minutes=cfg.sip_delay_minutes + 2)
    while clock() < end:
        if stop_flag.exists():
            status("STOPPED_BY_FLAG")
            return "STOPPED_BY_FLAG"
        if clock() >= sd.open_utc:
            outs = eng.track_outcomes(clock())
            state["outcomes"] = _count([o["status"] for o in outs])
            state["delivery"] = sync(eng.store, session)
            status("TRACKING_OUTCOMES")
        sleep(track_interval_s)
    outs = eng.track_outcomes(clock())
    state["outcomes"] = _count([o["status"] for o in outs])
    state["delivery"] = sync(eng.store, session)
    status("DONE")
    return "DONE"


def _count(xs) -> dict:
    out: dict = {}
    for x in xs:
        out[x] = out.get(x, 0) + 1
    return out


def cmd_run(args) -> int:
    from zoneinfo import ZoneInfo

    from talonx_premarket.config import PREMARKET_RESEARCH_V1 as cfg
    from talonx_premarket.engine import Engine, LiveSource
    from talonx_premarket.session import is_session, session_day
    from talonx_premarket.store import ResearchStore
    now = datetime.now(timezone.utc)
    day = now.astimezone(ZoneInfo("America/New_York")).date()
    if not is_session(day):
        print(f"{day} is not an XNYS session -- nothing to do")
        return 0
    sd = session_day(day, cfg)
    if now >= sd.close_utc + timedelta(minutes=cfg.sip_delay_minutes + 2):
        print(f"XNYS session {day} is already over -- nothing to do")
        return 0
    out = session_dir_for(day)
    out.mkdir(parents=True, exist_ok=True)
    if (out / "stop.flag").exists():
        print(f"REFUSED: {out / 'stop.flag'} exists for THIS session ({day}). It was placed to stop this session's "
              f"canary. To restart deliberately, rename it (e.g. stop.flag.<time>) -- it is never deleted "
              f"automatically. (A stop.flag from any other session date lives in a different directory and is ignored.)")
        return 3
    universe = _load_universe(Path(args.universe))
    data = _data()
    route, drain, sync, delivery = _router(args.deliver, Path(args.notify_db))
    store = ResearchStore(out / "premarket_research.db")
    symbols = sorted(m.symbol for m in universe if m.status == "ELIGIBLE")
    eng = Engine(universe=universe, source=LiveSource(data, symbols, sd, cfg), store=store, sd=sd, mode="live",
                 v2_scope=_v2_scope(args.v2_scope_log), sec=_sec(), ledger_path=str(DEFAULT_LEDGER), cfg=cfg,
                 route=route)
    run_id = store.start_run(day.isoformat(), os.getpid(), now.isoformat(), "live", cfg.fingerprint(), delivery)
    base = {"engine": "PREMARKET_RESEARCH", "mode": "live", "session": day.isoformat(), "run_id": run_id,
            "runs_this_session": len(store.runs_for(day.isoformat())), "config_version": cfg.version,
            "config_fingerprint": cfg.fingerprint(), "delivery_mode": delivery,
            "universe_total": len(universe), "universe_eligible": len(symbols), "v2_scope_size": len(eng.v2_scope),
            "sip_delay_minutes": cfg.sip_delay_minutes, "pid": os.getpid(),
            "open_utc": sd.open_utc.isoformat(), "close_utc": sd.close_utc.isoformat()}
    print(json.dumps(base, indent=1))
    end_state = "CRASHED"
    try:
        end_state = run_session(eng=eng, sd=sd, cfg=cfg, data=data, base=base, out=out, drain=drain, sync=sync)
    except KeyboardInterrupt:
        end_state = "INTERRUPTED"
    finally:
        store.end_run(run_id, datetime.now(timezone.utc).isoformat(), end_state)
    return 0


def build_status(out: Path, *, now: datetime | None = None) -> dict:
    """Operator status: the heartbeat file plus durable counts from the research DB (read-only)."""
    import sqlite3
    now = now or datetime.now(timezone.utc)
    st: dict = {}
    p = out / "status.json"
    if p.exists():
        st = json.loads(p.read_text(encoding="utf-8"))
    hb = st.get("heartbeat_utc")
    last = st.get("last_scan") or {}
    funnel = last.get("funnel") or {}
    prov = funnel.get("provider") or {}
    rep = {"SESSION": out.name, "PID": st.get("pid"), "STATE": st.get("state", "NO_STATUS"),
           "HEARTBEAT_AGE_S": round((now - datetime.fromisoformat(hb)).total_seconds(), 1) if hb else None,
           "CONFIG_FP": st.get("config_fingerprint"), "UNIVERSE": st.get("universe_total"),
           "ELIGIBLE": st.get("universe_eligible"), "CURRENT_PHASE": last.get("phase"),
           "LAST_SCAN": last.get("decision_utc"), "NEXT_SCAN": st.get("next_scan_utc"),
           "SCAN_DURATION_S": last.get("duration_s"), "DATA_AS_OF": last.get("data_as_of_utc"),
           "EFFECTIVE_SIP_DELAY": "15-16 min (as-of = now-15min floored to the minute; last complete bar ends at as-of)",
           "PROVIDER_REQUESTS": last.get("requests_total"), "PROVIDER_ERRORS": last.get("data_errors_total"),
           "FAILED_BATCHES": prov.get("FAILED_BATCHES_TOTAL"), "PROVIDER_COMPLETE": prov.get("PROVIDER_COMPLETE"),
           "DATA_GAPS": prov.get("DATA_GAPS"), "LAST_SUCCESSFUL_PROVIDER_FETCH": prov.get("LAST_SUCCESSFUL_PROVIDER_FETCH"),
           "CATALYST_UNKNOWN": prov.get("CATALYST_UNKNOWN"),
           **{k: funnel.get(k, 0) for k in ("DATA_READY", "HARD_REJECTED", "SCORED", "WATCH", "BULLISH_SETUP",
                                            "BEARISH_SETUP", "PROVIDER_INCOMPLETE")},
           "DELIVERY_MODE": st.get("delivery_mode"), "DELIVERY_STATES": st.get("delivery"),
           "OUTCOMES": st.get("outcomes"), "RUNS_THIS_SESSION": st.get("runs_this_session")}
    db = out / "premarket_research.db"
    if db.exists():
        con = sqlite3.connect(f"file:{db}?mode=ro", uri=True, timeout=5.0)
        try:
            rep["NEW_ALERTS_USED"] = f"{con.execute('SELECT COUNT(*) FROM candidates WHERE first_alert_utc IS NOT NULL').fetchone()[0]}/25"
            rep["SUPPRESSED_BY_CAP"] = con.execute("SELECT COUNT(*) FROM candidates WHERE state LIKE 'SUPPRESSED_%'").fetchone()[0]
            rep["ALERT_EVENTS_BY_TYPE"] = dict(con.execute("SELECT alert_type, COUNT(*) FROM alerts GROUP BY 1").fetchall())
            rep["OUTCOMES"] = dict(con.execute("SELECT status, COUNT(*) FROM outcomes GROUP BY 1").fetchall()) or rep["OUTCOMES"]
            rep["RUNS_THIS_SESSION"] = con.execute("SELECT COUNT(*) FROM runs").fetchone()[0]
        finally:
            con.close()
    return rep


def cmd_status(args) -> int:
    from zoneinfo import ZoneInfo
    day = date.fromisoformat(args.date) if args.date else \
        datetime.now(timezone.utc).astimezone(ZoneInfo("America/New_York")).date()
    out = session_dir_for(day)
    if not out.exists():
        print(f"no research session directory for {day}")
        return 1
    for k, v in build_status(out).items():
        print(f"{k:32s} {v}")
    return 0


def cmd_report(args) -> int:
    """Evidence collector: writes <session>/evidence/ (JSON + Markdown) from the durable DB. Read-only on the DB."""
    import sqlite3
    out = session_dir_for(date.fromisoformat(args.date))
    db = out / "premarket_research.db"
    if not db.exists():
        print(f"no research DB for {args.date}")
        return 1
    con = sqlite3.connect(f"file:{db}?mode=ro", uri=True, timeout=5.0)
    con.row_factory = sqlite3.Row
    try:
        q = lambda sql: [dict(r) for r in con.execute(sql)]  # noqa: E731
        scans = q("SELECT decision_utc, data_as_of_utc, phase, duration_s, requests, funnel_json, errors_json "
                  "FROM scans ORDER BY decision_utc")
        ev = {"session": args.date, "status": build_status(out), "runs": q("SELECT * FROM runs ORDER BY run_id"),
              "scans": scans, "alerts": q("SELECT alert_id, candidate_id, symbol, alert_type, decision_utc, "
                                          "data_as_of_utc, score, gap_pct, ref_price, catalyst, routed, delivery_state "
                                          "FROM alerts ORDER BY decision_utc, symbol"),
              "candidates": q("SELECT * FROM candidates ORDER BY first_alert_utc, symbol"),
              "outcomes": q("SELECT * FROM outcomes ORDER BY symbol")}
    finally:
        con.close()
    ed = out / "evidence"
    ed.mkdir(exist_ok=True)
    (ed / "canary_evidence.json").write_text(json.dumps(ev, indent=1, default=str), encoding="utf-8")
    lines = [f"# Pre-market research canary evidence: {args.date}", "",
             "| Status | Value |", "|---|---|"]
    lines += [f"| {k} | {v} |" for k, v in ev["status"].items()]
    lines += ["", "## Scan timeline", "", "| Decision (UTC) | Phase | As-of | Data ready | Gaps | Provider complete | "
              "Worthy | Duration s |", "|---|---|---|---|---|---|---|---|"]
    for s in scans:
        f = json.loads(s["funnel_json"] or "{}")
        pv = f.get("provider") or {}
        lines.append(f"| {s['decision_utc'][11:19]} | {s['phase']} | {s['data_as_of_utc'][11:16]} | "
                     f"{f.get('DATA_READY', 0)} | {pv.get('DATA_GAPS', '?')} | {pv.get('PROVIDER_COMPLETE', '?')} | "
                     f"{f.get('ALERT_WORTHY', 0)} | {s['duration_s']} |")
    lines += ["", "## Alert events", "", "| Time | Symbol | Type | Score | Gap % | Routed | Delivery |",
              "|---|---|---|---|---|---|---|"]
    for a in ev["alerts"]:
        lines.append(f"| {a['decision_utc'][11:19]} | {a['symbol']} | {a['alert_type']} | {a['score']} | "
                     f"{a['gap_pct']:+.2f} | {a['routed']} | {a['delivery_state']} |" if a["gap_pct"] is not None else
                     f"| {a['decision_utc'][11:19]} | {a['symbol']} | {a['alert_type']} | - | - | {a['routed']} | "
                     f"{a['delivery_state']} |")
    lines += ["", "## Post-open outcomes (hindsight / evaluation only)", "",
              "| Symbol | Family | Status | Open | +30m | +1h | Close | MFE | MAE |", "|---|---|---|---|---|---|---|---|---|"]
    for o in ev["outcomes"]:
        lines.append(f"| {o['symbol']} | {o['family']} | {o['status']} | {o['open_ret_pct']} | {o['ret_30m_pct']} | "
                     f"{o['ret_1h_pct']} | {o['close_ret_pct']} | {o['mfe_pct']} | {o['mae_pct']} |")
    lines += ["", f"Runs this session: {len(ev['runs'])} (restarts = runs - 1)."]
    (ed / "CANARY_EVIDENCE.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"evidence written to {ed}")
    return 0


def main(argv=None) -> int:
    import talonx_ops.log_redaction  # noqa: F401  (process-wide secret redaction before any HTTP/logging)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    ap = argparse.ArgumentParser(prog="python -m talonx_premarket")
    ap.add_argument("--env-file", help="path to the .env to load (default: <repo>/.env)")
    sub = ap.add_subparsers(dest="cmd", required=True)
    u = sub.add_parser("universe")
    u.add_argument("--out", default=str(UNIVERSE_PATH))
    r = sub.add_parser("replay")
    r.add_argument("--date", required=True)
    r.add_argument("--out")
    r.add_argument("--universe", default=str(UNIVERSE_PATH))
    r.add_argument("--universe-max-age-h", type=float, default=72.0)
    r.add_argument("--v2-scope-log")
    g = sub.add_parser("run")
    g.add_argument("--deliver", action="store_true")
    g.add_argument("--universe", default=str(UNIVERSE_PATH))
    g.add_argument("--notify-db", default=str(RESEARCH_NOTIFY_DB))
    g.add_argument("--v2-scope-log")
    st = sub.add_parser("status")
    st.add_argument("--date", help="XNYS session date (default: today in America/New_York)")
    rp = sub.add_parser("report")
    rp.add_argument("--date", required=True)
    a = ap.parse_args(argv)
    _env(a.env_file)
    return {"universe": cmd_universe, "replay": cmd_replay, "run": cmd_run, "status": cmd_status,
            "report": cmd_report}[a.cmd](a)


if __name__ == "__main__":
    sys.exit(main())
