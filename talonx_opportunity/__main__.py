"""
python -m talonx_opportunity <command>

  up [--deliver] [--supervise] [--only a,b]   start missing components (each its own process); --supervise keeps
                                              restarting ONLY a component that died
  status [--json]                             components, data/capability per phase, discovery, horizons,
                                              notification, reporting, paper (read-only)
  restart <component>                         stop + start exactly one component (others keep running)
  stop <component> | down                     graceful stop via the component's stop flag
  component <name>                            run one component in the foreground (what `up` spawns)
  declare-change <component> --class C --reason "..."   classify the NEXT start of a component (B7)
  declare-shared-runtime [--apply] [--component X]      F-P2: verified OPERATIONS_ONLY declarations for components
                                              whose ONLY source change since their last boundary is shared runtime
  deployments [--window D]                    deployment / change boundaries
  report [--window D]                         write the boundary-aware session report
  capabilities                                provider capability per phase
  universe-report [--window D] [--preview DIR]   the live-universe (DTU) report of a window: from the live market.db
                                              snapshot (read-only), or --preview: build the window's inputs +
                                              snapshot in a scratch DIR (operational fetch; never the live stores)

Lab delivery is double opt-in: `up --deliver` AND TALONX_NOTIFY_RESEARCH_ENABLED=1 in THIS process environment only
(never in the V2 window). Research only: never trades, never emits a V2 TRADE_EVENT.
"""
from __future__ import annotations

import argparse
import json
import os
import sys


def _root():
    return os.environ.get("TALONX_OPP_ROOT")


def cmd_component(name: str) -> int:
    if name == "ingestion":
        from talonx_opportunity.ingestion import main
        return main()
    if name == "discovery":
        from talonx_opportunity.discovery import main
        return main()
    if name == "notifier":
        from talonx_opportunity.notifier import main
        return main()
    if name == "outcomes":
        from talonx_opportunity.outcome_tracker import main
        return main()
    if name == "reporting":
        from talonx_opportunity.reporting import main
        return main()
    if name == "promotion":                    # 2026-09-25: separate downstream paper-promotion lane (SHADOW default)
        from talonx_opportunity.promotion import main
        return main()
    if name == "sentinel":                     # 2026-09-26: Sentinel operator-command poller (off unless enabled)
        from talonx_opportunity.sentinel_component import main
        return main()
    if name.startswith("evaluator:"):
        from talonx_opportunity.evaluators import main
        return main(name.split(":", 1)[1])
    raise SystemExit(f"unknown component {name!r}")


def _print_status(as_json: bool) -> int:
    from talonx_ops.opportunity_read import read_opportunity_status
    s = read_opportunity_status(_root())
    if as_json:
        print(json.dumps(s, indent=1, default=str))
        return 0
    print(f"SYSTEM   overall={s['system']['overall']} commit={s['system']['commit']}")
    ld = s["system"]["latest_deployment"]
    if ld:
        print(f"         latest deployment {ld['at_utc'][:19]}Z {ld['component']} {ld['classification']}: {ld['reason']}")
    print("COMPONENTS")
    for c in s["components"]:
        print(f"  {c['logical']:<22} {c['component']:<22} {c['health']:<11} hb_age={c['heartbeat_age_s']} "
              f"restarts={c['restarts']} v={c['version']}"
              + (f" pid={c['pid']} mode={c.get('mode')}" if c.get("mode") else "")
              + (f" universe={c['mutation_mode']}" if c.get("mutation_mode") else "")
              + (f" last_error={c['last_error']}" if c.get("last_error") else ""))
    d = s["data"]
    print(f"DATA     ingestion={d.get('ingestion')}")
    for ph, p in (d.get("probes") or {}).items():
        print(f"         probe {ph}: ok={p['ok']} at {p['at_utc'][:19]} {p['detail'][:60]}")
    if d.get("capability"):
        cap = d["capability"]
        print(f"         capability {cap.get('phase')}: {cap.get('provider')}/{cap.get('feed')} "
              f"{cap.get('availability')} delay={cap.get('delay_minutes')} usable={cap.get('usable_for_discovery')}")
    print(f"DISCOVERY {s['discovery']}")
    for h, v in s["horizons"].items():
        print(f"HORIZON  {h:<10} {v['health']:<11} state={v['state']} records={v['records']} buy_sell={v['buy_sell']}")
    print(f"NOTIFY   {s['notification']['lab']} policy={s['notification']['policy']}")
    print(f"REPORT   {s['reporting']}")
    print(f"PAPER    {s['paper']}")
    return 0


def _universe_report(wid: str | None, preview: str | None) -> int:
    """Live-universe report. Default: the window's snapshot in the live market.db (read-only) -> the local report
    files. --preview DIR: the same ingestion code path (members, V1 daily, as-traded live daily, snapshot, report) in
    a scratch root; reads the live stores only read-only and never saves the shared universe.json."""
    import sqlite3
    import time
    from datetime import date
    from pathlib import Path
    from talonx_opportunity import universe_tiers as U
    from talonx_opportunity.db import REPO_ROOT, root_dir, unj, utcnow
    from talonx_opportunity.phases import trading_window
    policy = U.policy_from_env()
    if preview:
        from talonx_opportunity.ingestion import UNIVERSE_MAX_AGE_H, Ingestion
        from talonx_ops.operator_control.gates import effective_symbols
        from talonx_premarket import __main__ as M
        M._env()
        w = trading_window(date.fromisoformat(wid))

        def load_no_save():
            from talonx_premarket.universe import build_universe, load
            p = REPO_ROOT / "results" / "premarket_research" / "universe.json"
            if p.exists() and (time.time() - p.stat().st_mtime) < UNIVERSE_MAX_AGE_H * 3600:
                return [m.__dict__ for m in load(p)], f"{p.name} (preview, read-only)"
            ct = Path.home() / ".talonx" / "intelligence" / "company_tickers.json"
            return [m.__dict__ for m in build_universe(ing.data.assets(), json.loads(ct.read_text(
                encoding="utf-8")))], "rebuilt from Alpaca assets x SEC company_tickers (preview, NOT saved)"
        ing = Ingestion(root=preview, universe_loader=load_no_save, dtu_mode=U.ACTIVE)
        now = utcnow()
        ing._ensure_window(w)
        symbols = effective_symbols(ing.eligible(w.window_id))
        ing._ensure_daily(w, symbols, now)
        ing._dtu_init(w)
        ing._dtu.root = None                         # protection readers: the LIVE stores (read-only)
        ing._dtu_prepare(w, symbols, now)
        print(json.dumps({"preview_root": preview, "requests": ing.data.requests, "prep": ing.dtu_prep}, indent=1,
                         default=str))
        out = U.report_dir(preview, w.window_id) / f"universe_{w.window_id}_summary.txt"
        if out.exists():
            print(out.read_text(encoding="utf-8"))
        return 0 if out.exists() else 1
    p = root_dir(_root()) / "market.db"
    con = sqlite3.connect(f"file:{p}?mode=ro", uri=True, timeout=10)
    if wid is None:
        r = con.execute("SELECT window_id FROM dtu_snapshots ORDER BY window_id DESC LIMIT 1").fetchone()
        wid = r[0] if r else None
    if wid is None:
        print("no DTU snapshot in market.db")
        return 2
    w = trading_window(date.fromisoformat(wid))
    row = con.execute("SELECT members_json FROM universe WHERE window_id=?", (wid,)).fetchone()
    members = unj(row[0], []) if row else []
    daily = {r[0]: unj(r[1], []) for r in con.execute("SELECT symbol, bars_json FROM daily WHERE window_id=?", (wid,))}
    d = U.DTU.__new__(U.DTU)                         # read-only use: no schema, no writer handle
    d.con, d.root, d.policy, d.readers, d.clock = con, _root(), policy, {}, utcnow
    from talonx_premarket import __main__ as M
    M._env()
    rep = d.report(w, members, daily, v2_scope=set(M._v2_scope(None)))
    if rep["meta"]["snapshot_policy_fp"] != policy.fingerprint():
        print(f"WARNING: the {wid} snapshot was built under policy {rep['meta']['snapshot_policy_fp']}, not "
              f"{policy.version} ({policy.fingerprint()})")
    paths = U.write_report(rep, U.report_dir(_root(), wid))
    print(json.dumps({"paths": paths, "counts": rep["counts"], "reconciled": rep["reconciled"]}, indent=1,
                     default=str))
    print(U.summary_text(rep))
    return 0


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="python -m talonx_opportunity")
    sub = ap.add_subparsers(dest="cmd", required=True)
    u = sub.add_parser("up")
    u.add_argument("--deliver", action="store_true")
    u.add_argument("--supervise", action="store_true")
    u.add_argument("--only", default="")
    st = sub.add_parser("status")
    st.add_argument("--json", action="store_true")
    for name in ("restart", "stop"):
        p = sub.add_parser(name)
        p.add_argument("component")
    sub.add_parser("down")
    c = sub.add_parser("component")
    c.add_argument("name")
    dc = sub.add_parser("declare-change")
    dc.add_argument("component")
    dc.add_argument("--class", dest="cls", required=True)
    dc.add_argument("--reason", required=True)
    ds = sub.add_parser("declare-shared-runtime")
    ds.add_argument("--apply", action="store_true")
    ds.add_argument("--component", action="append", default=None)
    dp = sub.add_parser("deployments")
    dp.add_argument("--window", default=None)
    rp = sub.add_parser("report")
    rp.add_argument("--window", default=None)
    sub.add_parser("capabilities")
    ur = sub.add_parser("universe-report")
    ur.add_argument("--window", default=None)
    ur.add_argument("--preview", default=None)
    a = ap.parse_args(argv)
    if a.cmd == "universe-report":
        return _universe_report(a.window, a.preview)

    from talonx_opportunity import supervise as SV
    root = _root()
    if a.cmd == "component":
        return cmd_component(a.name)
    if a.cmd == "up":
        env = dict(os.environ)
        env["TALONX_OPP_DELIVER"] = "1" if a.deliver else "0"
        names = tuple(x for x in a.only.split(",") if x) or SV.COMPONENTS
        print(json.dumps(SV.up(root, names, env=env), indent=1))
        if a.deliver:
            # resolve exactly as the notifier will: it loads .env (override=False) before resolving (2026-09-25 fix:
            # this line used to report a false negative because `up` itself never loaded .env)
            from talonx_premarket import __main__ as _M
            _M._env()
            from talonx_ops.notify import RESEARCH, resolve_destination_config
            cfg = resolve_destination_config(RESEARCH)
            print(f"LAB DELIVERY: deliver_flag=true research_destination_enabled={cfg.enabled} ({cfg.reason})")
        if a.supervise:
            try:
                SV.supervise(root, names, env=env)
            except KeyboardInterrupt:
                print("supervisor stopped; components keep running (use `down` to stop them)")
        return 0
    if a.cmd == "status":
        return _print_status(a.json)
    if a.cmd == "restart":
        print(f"restarted {a.component} pid={SV.restart(root, a.component)}")
        return 0
    if a.cmd == "stop":
        print(f"stopped {a.component}: {SV.stop(root, a.component)}")
        return 0
    if a.cmd == "down":
        for n in SV.COMPONENTS:
            SV.request_stop(root, n)
        print({n: SV.wait_stopped(root, n, 60) for n in SV.COMPONENTS})
        return 0
    if a.cmd == "declare-change":
        from talonx_opportunity.runtime import RuntimeStore
        print(f"declaration #{RuntimeStore(root).declare_change(a.component, a.cls, a.reason)} recorded for the next "
              f"start of {a.component}")
        return 0
    if a.cmd == "declare-shared-runtime":
        from talonx_opportunity.runtime import RuntimeStore
        rs = RuntimeStore(root)
        plan = rs.declare_shared_runtime_changes(a.component) if a.apply else rs.plan_shared_runtime_declarations(
            a.component)
        print(json.dumps(plan, indent=1))
        print("APPLIED (version-bound declarations recorded)" if a.apply else "DRY RUN (use --apply to record)")
        return 0
    if a.cmd in ("deployments", "report"):
        from talonx_opportunity.db import utcnow
        from talonx_opportunity.phases import phase_at
        wid = a.window or (phase_at(utcnow())[1].window_id if phase_at(utcnow())[1] else None)
        if wid is None:
            print("no current trading window; pass --window YYYY-MM-DD")
            return 2
        if a.cmd == "report":
            from talonx_opportunity.reporting import write_report
            print(f"report written to {write_report(root, wid)}")
        else:
            from talonx_opportunity.reporting import build_report
            print(json.dumps(build_report(root, wid)["deployment_boundaries"], indent=1, default=str))
        return 0
    if a.cmd == "capabilities":
        from talonx_opportunity.capabilities import capability_table
        print(json.dumps(capability_table(), indent=1))
        return 0
    return 2


if __name__ == "__main__":
    sys.exit(main())
