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
import os
import sqlite3
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

# Task 132: load the shared .env into THIS process's os.environ before
# anything spawns -- same resolution approach as dashboard.py /
# talonx_ops/supervisor.py. proc._spawn() merges {**os.environ, **env} for
# EVERY child (supervisor, V2 companion, checkpoint daemon), so whatever is
# in THIS process's environment at spawn time is what reaches all three;
# resolve_env() below only resolves its own 4 named vars from .env as a
# fallback, it does not load secrets (TELEGRAM_*) or the broader TALONX_*
# toggles into this process's own os.environ. Without this, those settings
# were only ever visible if the invoking shell happened to export them
# first -- a real, silent gap this closes. override=False: a real env var
# already set in the shell always wins.
try:
    from dotenv import load_dotenv
    _shared_env = Path(__file__).resolve().parents[2] / ".env"
    if _shared_env.is_file():
        load_dotenv(_shared_env, override=False)
except ImportError:  # pragma: no cover
    pass

from talonx_ops.prospective import RELEASE_SHA_EXPECTED
from talonx_ops.prospective.paths import (V2_DB_PATH, atomic_write, ensure_session_dir, now_pair,
                                          resolve_env, session_dir)


_VERDICT_LINE = {
    "READY": "READY -- stack up. Dashboard: http://localhost:8787  --  no intervention needed.",
    "STARTING": "STARTING -- mandatory components not all confirmed yet; re-check with "
                "'python -m talonx_ops.prospective status' shortly.",
    "NOT_STARTED": "NOT_STARTED -- nothing was spawned (resolve the STOP rows above).",
    "FAILED_WITH_RESIDUALS": "FAILED_WITH_RESIDUALS -- a mandatory component did not come up; "
                             "what was spawned has been cleaned up (see start_cleanup.json). "
                             "Do NOT re-run blindly.",
}


def _print_morning(pre, verify, session, env, *, verdict: str = "READY"):
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
    print(f"  startup verdict  : {verdict}")
    print(f"  {_VERDICT_LINE.get(verdict, verdict)}")
    print("  Evening:  python -m talonx_ops.prospective close")
    print("=" * 66)


def cmd_start(args) -> int:
    from talonx_ops.prospective.preflight import run_preflight
    from talonx_ops.prospective.proc import (
        ConcurrentStartError, start_stack, startup_verdict, verify_running,
    )

    sd = ensure_session_dir()
    env = resolve_env()

    from talonx_v2.release_gate import evaluate_release_readiness, resolve_pricing_mode
    try:
        args.pricing_mode = resolve_pricing_mode(args.pricing_mode, release=args.release)
    except ValueError as exc:
        print(f"START REFUSED: {exc}")
        return 2
    if args.release:
        gate = evaluate_release_readiness(db_path=V2_DB_PATH, pricing_mode=args.pricing_mode,
                                          deliver=args.deliver, transport=args.transport,
                                          env={**os.environ, **env})
        atomic_write(sd / "release_gate.json", json.dumps(gate.to_dict(), indent=2, default=str))
        # Session 03 A1: the operator sees the EFFECTIVE Intelligence delivery state, not the pre-start env.
        from talonx_v2.release_gate import intelligence_delivery_state
        _ids = intelligence_delivery_state({**os.environ, **env}, deliver=args.deliver, transport=args.transport)
        print(f"INTELLIGENCE DELIVERY: configured={_ids['configured']} "
              f"runtime_requested_by_start={'ON' if _ids['runtime_requested'] else 'OFF'} "
              f"effective={_ids['effective']}")
        if gate.status != "READY":
            print("START REFUSED: release readiness gate NOT_READY")
            for c in gate.failed:
                print(f"  - {c.name}: {c.detail}")
            return 2
    pre = run_preflight(expected_sha=args.expected_sha, require_stack_up=False)
    atomic_write(sd / "preflight.json", json.dumps(pre.to_dict(), indent=2, default=str))
    atomic_write(sd / "preflight.md", pre.to_markdown())

    if pre.overall == "NOT_READY" and not args.force:
        _print_morning(pre, None, sd, env, verdict="NOT_STARTED")
        return 2

    try:
        info = start_stack(sd, env=env, tick_seconds=args.tick_seconds,
                           heartbeat_seconds=args.heartbeat_seconds,
                           live_lookback_days=args.live_lookback_days,
                           checkpoint_every_s=args.every,
                           pricing_mode=args.pricing_mode,
                           execution_scope=args.execution_scope,
                           deliver=args.deliver, transport=args.transport,
                           enable_broad_discovery=args.enable_broad_discovery,
                           allow_when_running=getattr(args, "force", False),
                           release=args.release)
    except ConcurrentStartError as exc:
        print("=" * 66)
        print("  PROSPECTIVE V2 -- START REFUSED (a stack is already running)")
        print(f"  {exc}")
        print("  Use 'python -m talonx_ops.prospective close' first, or --force to override.")
        print("=" * 66)
        atomic_write(sd / "start_verify.json", json.dumps(
            {"verdict": "REFUSED_ALREADY_RUNNING", "detail": str(exc)}, indent=2))
        return 3

    # RI-2 RI2-M: durable STARTUP notification (OPERATIONS). Best-effort --
    # a failure here never blocks or unwinds the already-successful start.
    try:
        from talonx_ops.notify.producers import enqueue_lifecycle_event
        from talonx_ops.prospective.close import _default_ops_notify_store
        campaign_id = _campaign_label(env)
        enqueue_lifecycle_event(
            _default_ops_notify_store(), event_type="STARTUP", campaign_id=campaign_id,
            detail=f"prospective start: deliver={args.deliver} transport={args.transport}")
    except Exception:  # noqa: BLE001
        pass

    # D4 / Section 3: bounded readiness wait -> a FIRST-CLASS verdict from the
    # actual process + heartbeat + dashboard state. READY needs EVERY mandatory
    # component (supervisor, companion, :8787) AND a fresh first tick.
    # The mechanism that resolves STARTING -> READY within the deadline is THIS
    # loop: it re-polls verify_running() + the heartbeat file every 3s until all
    # mandatory signals are up or the 120s grace elapses.
    GRACE_S = 120
    deadline = time.monotonic() + GRACE_S
    heartbeat_fresh = False
    verify = verify_running(sd, retries=1)
    while time.monotonic() < deadline:
        try:
            s = json.loads(Path(env["TALONX_V2_STATUS_PATH"]).read_text())
            age = (datetime.now(timezone.utc) - datetime.fromisoformat(s["heartbeat_utc"])).total_seconds()
            heartbeat_fresh = age < 180 and bool(s.get("strategy_version"))
        except Exception:  # noqa: BLE001
            heartbeat_fresh = False
        verify = verify_running(sd, retries=1)
        if heartbeat_fresh and all(verify.get(k) for k in ("supervisor_alive",
                                                           "v2_companion_alive",
                                                           "dashboard_8787")):
            break
        time.sleep(3)

    within_grace = time.monotonic() < deadline
    post = run_preflight(expected_sha=args.expected_sha, require_stack_up=True)
    atomic_write(sd / "preflight_poststart.json", json.dumps(post.to_dict(), indent=2, default=str))
    verify = verify_running(sd)
    verdict = startup_verdict(info, verify, heartbeat_fresh=heartbeat_fresh,
                              within_grace=within_grace)

    if verdict == "FAILED_WITH_RESIDUALS":
        # ownership-safe cleanup of what we just spawned
        try:
            from talonx_ops.prospective.proc import stop_stack
            cleanup = stop_stack(sd)
        except Exception as exc:  # noqa: BLE001
            cleanup = {"error": repr(exc)}
        atomic_write(sd / "start_cleanup.json", json.dumps(cleanup, indent=2, default=str))

    atomic_write(sd / "start_verify.json", json.dumps(
        {"procs": info, "verify": verify, "poststart_overall": post.overall,
         "verdict": verdict, "heartbeat_fresh": heartbeat_fresh}, indent=2, default=str))
    _print_morning(post, verify, sd, env, verdict=verdict)
    return {"READY": 0, "STARTING": 0, "NOT_STARTED": 2,
            "FAILED_WITH_RESIDUALS": 4}.get(verdict, 2)


SHUTDOWN_NOTICE_DRAIN_TIMEOUT_S = 20.0


def drain_operations_bounded(store, *, timeout_s: float = SHUTDOWN_NOTICE_DRAIN_TIMEOUT_S, drain=None) -> dict:
    """Drain the OPERATIONS destination once, in a daemon thread with a hard wall-clock bound, so a
    slow/unreachable Telegram can never hang `prospective close`. Disabled destination -> rows stay
    PENDING (worker.drain semantics); a timeout leaves the row for its normal deadline expiry."""
    import threading

    from talonx_ops.notify import OPERATIONS
    if drain is None:
        from talonx_ops.notify.worker import drain
    out: dict = {"status": "TIMEOUT", "timeout_s": timeout_s}

    def _run() -> None:
        try:
            summary = drain(store, destination=OPERATIONS)
            out.update(status="DRAINED", summary=summary)
        except Exception as exc:  # noqa: BLE001
            out.update(status="ERROR", error=type(exc).__name__)

    t = threading.Thread(target=_run, name="shutdown-notice-drain", daemon=True)
    t.start()
    t.join(timeout_s)
    return dict(out)


def cmd_close(args) -> int:
    from talonx_ops.prospective.close import render_report, run_close
    sd = session_dir()
    if args.session_dir:
        sd = Path(args.session_dir)
    if not sd.exists():
        sd = session_dir()  # fall back to today's
    sd.mkdir(parents=True, exist_ok=True)
    res = run_close(sd, force=args.force, do_shutdown=not args.no_shutdown)
    # RI-2 RI2-M: durable SHUTDOWN notification (OPERATIONS). Best-effort.
    try:
        from talonx_ops.notify.producers import enqueue_lifecycle_event
        from talonx_ops.prospective.close import _default_ops_notify_store
        campaign_id = (res.v2_reconciliation or {}).get("campaign_id", "V2")
        _ops_store = _default_ops_notify_store()
        enqueue_lifecycle_event(
            _ops_store, event_type="SHUTDOWN", campaign_id=campaign_id,
            detail=f"prospective close: verdict={res.verdict} shutdown_performed="
                   f"{res.shutdown.get('performed')}")
        # Session 03 A6: the V2 companion (the only Operations drainer) is already stopped here, so
        # SHUTDOWN used to sit PENDING until it expired. One bounded drain of OPERATIONS only.
        res.shutdown["shutdown_notice"] = drain_operations_bounded(_ops_store)
    except Exception:  # noqa: BLE001
        pass
    eod_evidence = dict(res.to_dict(), reconciled_at_utc=now_pair()["utc"])
    atomic_write(sd / "eod.json", json.dumps(eod_evidence, indent=2, default=str))
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


def cmd_list_blocks(args) -> int:
    """Package 2 Part 5: minimal explicit operator interface -- list
    ACTIVE account blocks so an operator can find a block_id to act on."""
    from talonx_ops import account_blocks
    from talonx_ops.prospective.paths import V2_DB_PATH
    db_path = args.db_path or str(V2_DB_PATH)
    con = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
    con.row_factory = sqlite3.Row
    try:
        blocks = account_blocks.active_blocks(con, args.account)
    finally:
        con.close()
    print(json.dumps([b.__dict__ for b in blocks], indent=2, default=str))
    return 0


def cmd_clear_block(args) -> int:
    """Package 2 Part 5: minimal explicit operator clearance interface.
    Re-verifies fresh evidence for the specific block/reason (see
    talonx_ops.prospective.clearance) and persists exactly one
    clearance attempt -- approved or refused -- with a full audit
    trail. See clearance.py's own docstring for the operator trust
    boundary (this is NOT an authentication mechanism)."""
    from talonx_ops.prospective.clearance import clear_block
    from talonx_ops.prospective.paths import V2_DB_PATH
    db_path = args.db_path or (str(V2_DB_PATH) if args.account == "V2" else None)
    if not db_path:
        print("error: --db-path is required for a non-V2 --account", file=sys.stderr)
        return 2
    result = clear_block(db_path, args.account, block_id=args.block_id,
                         operator_id=args.operator, reason=args.reason,
                         evidence_ref=args.evidence_ref)
    print(json.dumps(result, indent=2, default=str))
    return 0 if result["allow"] else 1


def _campaign_label(env: dict) -> str:
    """The campaign id shown in Sentinel lifecycle notices: the REAL configured campaign (``resolve_env()`` only carries 4
    variables and never includes it, which made the canary STARTUP say ``V2`` instead of ``V2-PAPER-RC1``)."""
    return os.environ.get("TALONX_V2_CAMPAIGN_ID") or env.get("TALONX_V2_CAMPAIGN_ID") or "V2"


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
    s.add_argument("--pricing-mode", default=None,
                   choices=["csv", "composite-yf", "composite-iex", "sip"])
    # FINAL ACCEPTANCE: the explicit FIRST-RELEASE profile (SIP, paper, Signal delivery); refuses to start
    # unless the read-only release readiness gate is READY.  --force never bypasses it.
    s.add_argument("--release", action="store_true")
    s.add_argument("--execution-scope", default="none",
                   choices=["none", "resolved-active-watchlist"])
    s.add_argument("--deliver", action="store_true")
    s.add_argument("--transport", default="dryrun", choices=["dryrun", "telegram"])
    # Task 132: additively union the frozen 626-name Discovery Universe v1
    # into the V2 companion's execution scope + tag those symbols'
    # trading-lane alerts BROAD_DISCOVERY origin (talonx_v2.run's own
    # --enable-broad-discovery flag -- see its help text). OFF by default;
    # the original watchlist scope is unaffected unless explicitly set.
    s.add_argument("--enable-broad-discovery", action="store_true")

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

    # Package 2 Durable Account Blocks -- Part 5 minimal operator interface.
    _ACCOUNT_CHOICES = ["V2", "ORIGINAL_INTRADAY", "ORIGINAL_LONGTERM"]
    lb = sub.add_parser("list-blocks"); lb.set_defaults(fn=cmd_list_blocks)
    lb.add_argument("--account", required=True, choices=_ACCOUNT_CHOICES)
    lb.add_argument("--db-path", default="", help="defaults to v2_lane.db for --account V2")

    cb = sub.add_parser("clear-block"); cb.set_defaults(fn=cmd_clear_block)
    cb.add_argument("--account", required=True, choices=_ACCOUNT_CHOICES)
    cb.add_argument("--block-id", required=True)
    cb.add_argument("--operator", required=True, help="self-reported operator identity (audit trail, not authentication)")
    cb.add_argument("--reason", required=True)
    cb.add_argument("--evidence-ref", required=True, help="reference to the supporting reconciliation/resolution evidence")
    cb.add_argument("--db-path", default="", help="required for a non-V2 --account")

    args = ap.parse_args(argv)
    return args.fn(args)


if __name__ == "__main__":
    sys.exit(main())
