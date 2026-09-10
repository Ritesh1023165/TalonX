"""CLI for the autonomous prospective V2 operator (Task 114B).

  python -m talonx_ops.prospective start        # morning: preflight + start + verify + daemon
  python -m talonx_ops.prospective close        # evening: reconcile + report + shutdown
  python -m talonx_ops.prospective checkpoint   # one-shot checkpoint -> stdout
  python -m talonx_ops.prospective status       # quick health/data/activity
  python -m talonx_ops.prospective preflight    # preflight only (read-only)
  python -m talonx_ops.prospective session-loop --session-dir DIR   # (internal) checkpoint daemon
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

from talonx_ops.prospective import RELEASE_SHA_EXPECTED
from talonx_ops.prospective.paths import (atomic_write, ensure_session_dir, now_pair,
                                          resolve_env, session_dir)


def _print_morning(pre, verify, session, env):
    tp = now_pair()
    print("=" * 66)
    print(f"  PROSPECTIVE V2 -- MORNING START   {tp['europe_london']} (Europe/London)")
    print("=" * 66)
    print(f"  preflight overall : {pre.overall}")
    for r in pre.rows:
        if r.status != "READY":
            print(f"    [{r.status:7}] {r.check}  {r.detail}")
    if verify:
        print(f"  base stack alive : {verify.get('supervisor_alive')}")
        print(f"  V2 companion     : {verify.get('v2_companion_alive')}")
        print(f"  checkpoint daemon: {verify.get('checkpoint_daemon_alive')}")
        print(f"  dashboard :8787  : {verify.get('dashboard_8787')}")
    print(f"  session dir      : {session}")
    print(f"  env (non-secret) : profile={env['TALONX_ACTIVE_STRATEGY_PROFILE']} "
          f"cash={env['TALONX_V2_STARTING_CASH_USD']}")
    print("=" * 66)
    if pre.overall == "NOT_READY":
        print("  NO-GO -- session NOT started. Resolve the STOP rows above.")
    elif pre.overall == "READY_WITH_FINDINGS":
        print("  STARTED (with findings). Dashboard: http://localhost:8787")
    else:
        print("  STARTED. Dashboard: http://localhost:8787  --  no intervention needed.")
    print("  Evening:  python -m talonx_ops.prospective close")
    print("=" * 66)


def cmd_start(args) -> int:
    from talonx_ops.prospective.preflight import run_preflight
    from talonx_ops.prospective.proc import start_stack, verify_running

    sd = ensure_session_dir()
    env = resolve_env()

    pre = run_preflight(expected_sha=args.expected_sha, require_stack_up=False)
    atomic_write(sd / "preflight.json", json.dumps(pre.to_dict(), indent=2, default=str))
    atomic_write(sd / "preflight.md", pre.to_markdown())

    if pre.overall == "NOT_READY" and not args.force:
        _print_morning(pre, None, sd, env)
        return 2

    info = start_stack(sd, env=env, tick_seconds=args.tick_seconds,
                       heartbeat_seconds=args.heartbeat_seconds,
                       live_lookback_days=args.live_lookback_days,
                       checkpoint_every_s=args.every,
                       pricing_mode=args.pricing_mode,
                       execution_scope=args.execution_scope,
                       deliver=args.deliver, transport=args.transport)
    # wait for the companion's first heartbeat
    deadline = time.monotonic() + 90
    while time.monotonic() < deadline:
        try:
            s = json.loads(Path(env["TALONX_V2_STATUS_PATH"]).read_text())
            age = (datetime.now(timezone.utc) - datetime.fromisoformat(s["heartbeat_utc"])).total_seconds()
            if age < 180 and s.get("strategy_version"):
                break
        except Exception:  # noqa: BLE001
            pass
        time.sleep(3)

    post = run_preflight(expected_sha=args.expected_sha, require_stack_up=True)
    atomic_write(sd / "preflight_poststart.json", json.dumps(post.to_dict(), indent=2, default=str))
    verify = verify_running(sd)
    atomic_write(sd / "start_verify.json", json.dumps({"procs": info, "verify": verify,
                                                       "poststart_overall": post.overall}, indent=2, default=str))
    _print_morning(post, verify, sd, env)
    return 0 if post.overall != "NOT_READY" else 2


def cmd_close(args) -> int:
    from talonx_ops.prospective.close import render_report, run_close
    sd = session_dir()
    if args.session_dir:
        sd = Path(args.session_dir)
    if not sd.exists():
        sd = session_dir()  # fall back to today's
    sd.mkdir(parents=True, exist_ok=True)
    res = run_close(sd, force=args.force, do_shutdown=not args.no_shutdown)
    atomic_write(sd / "eod.json", json.dumps(res.to_dict(), indent=2, default=str))
    report = render_report(res, sd)
    atomic_write(sd / "final_report.md", report)
    ts = _terminal_summary(res, sd)
    atomic_write(sd / "terminal_summary.txt", ts)
    print(ts)
    code = {"PASS": 0, "PASS_WITH_FINDINGS": 0, "NOT_DUE_YET": 3, "FAIL": 1}.get(res.verdict, 1)
    # residual stack children after a shutdown attempt -> distinct non-zero
    # exit (Task 117 Phase 0 4.3) so automation does not read it as clean.
    if res.shutdown.get("performed") and res.shutdown.get("shutdown_clean") is False and code == 0:
        code = 4
    return code


def _terminal_summary(res, sd) -> str:
    ck = res.final_checkpoint
    v2 = res.v2_reconciliation
    fn = ck.get("funnel", {})
    cl = fn.get("clusters", {}) or {}
    tm = fn.get("terminal", {}) or {}
    tp = now_pair()
    L = ["=" * 60, "  PROSPECTIVE V2 -- EVENING CLOSE", "=" * 60,
         f"  time            : {tp['europe_london']}",
         f"  verdict         : {res.verdict}",
         f"  V2 health       : {ck.get('service_health', {}).get('health')}",
         f"  market feed     : {ck.get('market', {}).get('state')}",
         f"  cash            : {v2.get('cash')}  (start {v2.get('starting_cash')})",
         f"  open / closed   : {v2.get('open')} / {v2.get('closed')}   unresolved {v2.get('exit_unresolved')}",
         f"  BUY / SELL      : {tm.get('buys')} / {tm.get('sells')}",
         f"  clusters(>=2)   : {cl.get('clusters_ge2_distinct_insiders')}  "
         f"fresh-eligible {cl.get('fresh_eligible_clusters')}  stale {cl.get('stale_historical_clusters')}",
         f"  interpretation  : {fn.get('interpretation')}",
         "  asserts:"]
    for k, v in res.asserts.items():
        L.append(f"    {k}: {v}")
    L.append("  findings:")
    for f in res.findings or ["none"]:
        L.append(f"    - {f}")
    L.append(f"  shutdown        : {json.dumps(res.shutdown, default=str)[:400]}")
    L.append(f"  evidence        : {sd}")
    L.append("=" * 60)
    return "\n".join(L)


def cmd_checkpoint(args) -> int:
    from talonx_ops.prospective.checkpoint import capture
    print(json.dumps(capture(), indent=2, default=str))
    return 0


# flags that always mean "something is genuinely wrong" (independent of whether a session is up)
_HARD_INVARIANTS = ("negative_cash", "ledger_equation_broken", "duplicate_buy", "duplicate_position",
                    "stale_episode_entered", "experimental_external_send", "experimental_override_active")


def cmd_status(args) -> int:
    from talonx_ops.prospective.checkpoint import capture
    ck = capture()
    crit = [k for k, v in ck["invariants"].items() if v and k != "any_critical"]
    hard = [k for k in crit if k in _HARD_INVARIANTS]
    print(json.dumps({
        "time": ck["time"], "service_health": ck["service_health"]["health"],
        "data_state": ck["data_state"], "business_activity": ck["business_activity"],
        "v2_cash": ck["v2"].get("cash"), "open_positions": ck["v2"].get("open_positions"),
        "funnel_interpretation": ck["funnel"].get("interpretation"),
        "eod": ck["eod"]["state"],
        "critical_flags": crit,
        "hard_invariant_breach": hard,
    }, indent=2, default=str))
    return 1 if hard else 0


def cmd_preflight(args) -> int:
    from talonx_ops.prospective.preflight import run_preflight
    pre = run_preflight(expected_sha=args.expected_sha, require_stack_up=args.stack_up)
    print(pre.to_markdown())
    return 0 if pre.overall != "NOT_READY" else 2


def cmd_session_loop(args) -> int:
    from talonx_ops.prospective.session_loop import run_loop
    return run_loop(args.session_dir, checkpoint_every_s=args.every,
                    until_close=not args.no_until_close, max_iterations=args.max_iterations)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser("talonx_ops.prospective")
    sub = ap.add_subparsers(dest="cmd", required=True)

    s = sub.add_parser("start"); s.set_defaults(fn=cmd_start)
    s.add_argument("--expected-sha", default=RELEASE_SHA_EXPECTED)
    s.add_argument("--tick-seconds", type=int, default=300)
    s.add_argument("--heartbeat-seconds", type=int, default=30)
    s.add_argument("--live-lookback-days", type=int, default=45)
    s.add_argument("--every", type=int, default=1800)
    s.add_argument("--force", action="store_true")
    # Task 117 final activation: the V2 companion deployment config, passed
    # straight through to `talonx_v2.run` so `prospective start` launches the
    # ONE correctly-configured companion.
    s.add_argument("--pricing-mode", default="csv",
                   choices=["csv", "composite-yf", "composite-iex"])
    s.add_argument("--execution-scope", default="none",
                   choices=["none", "resolved-active-watchlist"])
    s.add_argument("--deliver", action="store_true")
    s.add_argument("--transport", default="dryrun", choices=["dryrun", "telegram"])

    c = sub.add_parser("close"); c.set_defaults(fn=cmd_close)
    c.add_argument("--session-dir", default="")
    c.add_argument("--force", action="store_true", help="close even if before XNYS close")
    c.add_argument("--no-shutdown", action="store_true")

    for name, fn in (("checkpoint", cmd_checkpoint), ("status", cmd_status)):
        p = sub.add_parser(name); p.set_defaults(fn=fn)

    p = sub.add_parser("preflight"); p.set_defaults(fn=cmd_preflight)
    p.add_argument("--expected-sha", default=RELEASE_SHA_EXPECTED)
    p.add_argument("--stack-up", action="store_true")

    sl = sub.add_parser("session-loop"); sl.set_defaults(fn=cmd_session_loop)
    sl.add_argument("--session-dir", required=True)
    sl.add_argument("--every", type=int, default=1800)
    sl.add_argument("--no-until-close", action="store_true")
    sl.add_argument("--max-iterations", type=int, default=None)

    args = ap.parse_args(argv)
    return args.fn(args)


if __name__ == "__main__":
    sys.exit(main())
