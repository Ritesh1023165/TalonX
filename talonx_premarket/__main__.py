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


def _env():
    try:
        from dotenv import load_dotenv
        load_dotenv(REPO_ROOT / ".env", override=False)
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
    """RESEARCH routing only. The destination constant is fixed here; there is no fallback."""
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

    return route, drain, {"deliver_flag": deliver, "research_destination_enabled": cfg.enabled,
                          "research_destination_reason": cfg.reason}


def cmd_run(args) -> int:
    from talonx_premarket.config import PREMARKET_RESEARCH_V1 as cfg
    from talonx_premarket.engine import Engine, LiveSource, write_status
    from talonx_premarket.session import is_session, phase_at, scan_schedule, session_day
    from talonx_premarket.store import ResearchStore
    now = datetime.now(timezone.utc)
    day = now.astimezone(__import__("zoneinfo").ZoneInfo("America/New_York")).date()
    if not is_session(day):
        print(f"{day} is not an XNYS session -- nothing to do")
        return 0
    sd = session_day(day, cfg)
    out = OUT_ROOT / day.isoformat()
    out.mkdir(parents=True, exist_ok=True)
    stop_flag = out / "stop.flag"
    universe = _load_universe(Path(args.universe))
    data = _data()
    route, drain, delivery = _router(args.deliver, Path(args.notify_db))
    store = ResearchStore(out / "premarket_research.db")
    symbols = sorted(m.symbol for m in universe if m.status == "ELIGIBLE")
    eng = Engine(universe=universe, source=LiveSource(data, symbols, sd, cfg), store=store, sd=sd, mode="live",
                 v2_scope=_v2_scope(args.v2_scope_log), sec=_sec(), ledger_path=str(DEFAULT_LEDGER), cfg=cfg,
                 route=route)
    status_path = out / "status.json"
    base = {"engine": "PREMARKET_RESEARCH", "mode": "live", "session": day.isoformat(),
            "config_version": cfg.version, "config_fingerprint": cfg.fingerprint(), "delivery": delivery,
            "universe_eligible": len(symbols), "v2_scope_size": len(eng.v2_scope), "pid": os.getpid()}
    print(json.dumps(base, indent=1))
    sched = [t for t in scan_schedule(day, cfg) if t >= now - timedelta(seconds=30)]
    last = None
    for t in sched:
        while datetime.now(timezone.utc) < t:
            if stop_flag.exists():
                print("stop.flag present -- exiting")
                return 0
            write_status(status_path, {**base, "heartbeat_utc": datetime.now(timezone.utc).isoformat(),
                                       "state": "WAITING_FOR_SCAN", "next_scan_utc": t.isoformat(), "last_scan": last})
            time.sleep(min(15.0, max(0.5, (t - datetime.now(timezone.utc)).total_seconds())))
        r = eng.scan(datetime.now(timezone.utc))
        dr = drain()
        last = {"decision_utc": r.decision_utc, "data_as_of_utc": r.data_as_of_utc, "phase": r.phase,
                "funnel": r.funnel, "alerts": [(a["symbol"], a["alert_type"], a["routed"]) for a in r.alerts],
                "duration_s": r.duration_s, "requests_total": data.requests, "data_errors_total": len(data.errors),
                "drain": dr}
        print(f"{r.decision_utc[11:19]}Z {r.phase} ready={r.funnel.get('DATA_READY', 0)} "
              f"worthy={r.funnel.get('ALERT_WORTHY', 0)} alerts={len(r.alerts)} {r.duration_s}s", flush=True)
        write_status(status_path, {**base, "heartbeat_utc": datetime.now(timezone.utc).isoformat(),
                                   "state": "SCANNED", "last_scan": last})
    # post-open tracking until the close is visible through the SIP delay
    end = sd.close_utc + timedelta(minutes=cfg.sip_delay_minutes + 2)
    while datetime.now(timezone.utc) < end and not stop_flag.exists():
        if phase_at(datetime.now(timezone.utc), cfg) != "CLOSED":
            outs = eng.track_outcomes(datetime.now(timezone.utc))
            write_status(status_path, {**base, "heartbeat_utc": datetime.now(timezone.utc).isoformat(),
                                       "state": "TRACKING_OUTCOMES", "last_scan": last,
                                       "outcomes": {o["symbol"]: o["status"] for o in outs}})
        time.sleep(600)
    outs = eng.track_outcomes(datetime.now(timezone.utc))
    write_status(status_path, {**base, "heartbeat_utc": datetime.now(timezone.utc).isoformat(), "state": "DONE",
                               "last_scan": last, "outcomes": {o["symbol"]: o["status"] for o in outs}})
    return 0


def cmd_status(args) -> int:
    from zoneinfo import ZoneInfo
    day = datetime.now(timezone.utc).astimezone(ZoneInfo("America/New_York")).date()
    p = OUT_ROOT / day.isoformat() / "status.json"
    print(p.read_text(encoding="utf-8") if p.exists() else f"no status for {day}")
    return 0


def main(argv=None) -> int:
    import talonx_ops.log_redaction  # noqa: F401  (process-wide secret redaction before any HTTP/logging)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    _env()
    ap = argparse.ArgumentParser(prog="python -m talonx_premarket")
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
    sub.add_parser("status")
    a = ap.parse_args(argv)
    return {"universe": cmd_universe, "replay": cmd_replay, "run": cmd_run, "status": cmd_status}[a.cmd](a)


if __name__ == "__main__":
    sys.exit(main())
