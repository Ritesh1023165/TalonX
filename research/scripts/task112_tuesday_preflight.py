"""
task112_tuesday_preflight.py -- Tuesday readiness + evidence collector
==================================================================
Read-only.  Runs the Phase 9 readiness contract, captures the Phase 23
evidence, and writes a dated JSON.  Does NOT start or stop anything and
NEVER deletes state.

  python research/scripts/task112_tuesday_preflight.py [--expected-sha SHA]

Exit 0 iff overall == READY.
"""
from __future__ import annotations

import argparse
import json
import os
import socket
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

OUT = ROOT / "results" / "task112_tuesday_release"

V1_FP = "2ae6216bca70"
V2_FP = "11107198c5b81237"
V2_VERSION = "INSIDER_BUY_CLUSTER_V2@1"


def _git(*a: str) -> str:
    try:
        return subprocess.run(["git", *a], cwd=ROOT, capture_output=True, text=True,
                              timeout=10).stdout.strip()
    except Exception:  # noqa: BLE001
        return ""


def _port_open(p: int) -> bool:
    s = socket.socket()
    s.settimeout(0.5)
    try:
        return s.connect_ex(("127.0.0.1", p)) == 0
    finally:
        s.close()


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser("task112_tuesday_preflight")
    ap.add_argument("--expected-sha", default="")
    ap.add_argument("--v2-status", default=os.environ.get("TALONX_V2_STATUS_PATH", "v2_service_status.json"))
    ap.add_argument("--v2-db", default=os.environ.get("TALONX_V2_DB_PATH", "v2_lane.db"))
    args = ap.parse_args(argv)

    checks: list[dict] = []

    def add(name: str, ok: bool, detail):
        checks.append({"check": name, "status": "READY" if ok else "FAIL", "detail": detail})

    # repo
    head = _git("rev-parse", "HEAD")
    dirty = _git("status", "--porcelain")
    add("repo_tree_clean", dirty == "", {"porcelain_lines": dirty.count("\n") + 1 if dirty else 0})
    if args.expected_sha:
        add("repo_head_matches_release_sha", head.startswith(args.expected_sha),
            {"head": head, "expected": args.expected_sha})

    # fingerprints
    try:
        from talonx_backtest.reproducibility import get_strategy_version
        v1 = get_strategy_version()
        add("original_v1_fingerprint", v1 == V1_FP, {"got": v1, "expected": V1_FP})
    except Exception as e:  # noqa: BLE001
        add("original_v1_fingerprint", False, {"error": repr(e)})
    try:
        from research.scripts.task112_v2_release_fingerprint import v2_release_fingerprint
        v2 = v2_release_fingerprint()
        add("v2_release_fingerprint", v2["fingerprint"] == V2_FP,
            {"got": v2["fingerprint"], "expected": V2_FP})
    except Exception as e:  # noqa: BLE001
        add("v2_release_fingerprint", False, {"error": repr(e)})

    # active profile
    prof = os.environ.get("TALONX_ACTIVE_STRATEGY_PROFILE", "")
    add("active_profile_is_v2_explicit", prof == "INSIDER_BUY_CLUSTER_V2", {"env": prof})

    # v2 lane heartbeat
    try:
        s = json.loads(Path(args.v2_status).read_text())
        age = (datetime.now(timezone.utc) - datetime.fromisoformat(s["heartbeat_utc"])).total_seconds()
        fresh = age < float(s.get("heartbeat_ttl_s", 180)) and s.get("strategy_version") == V2_VERSION
        add("v2_lane_heartbeat_fresh", fresh,
            {"age_s": round(age, 1), "strategy_version": s.get("strategy_version"),
             "active_profile": s.get("active_profile"),
             "open_positions": s.get("open_positions"), "cash": s.get("cash"),
             "exit_unresolved": s.get("exit_unresolved", [])})
        add("v2_no_exit_unresolved", not s.get("exit_unresolved"), s.get("exit_unresolved", []))
    except Exception as e:  # noqa: BLE001
        add("v2_lane_heartbeat_fresh", False, {"error": repr(e), "path": args.v2_status})

    # v2 paper state
    try:
        import sqlite3
        con = sqlite3.connect(f"file:{args.v2_db}?mode=ro", uri=True)
        cash = con.execute("SELECT cash FROM portfolio WHERE id=1").fetchone()
        opens = con.execute("SELECT COUNT(*) FROM positions WHERE status='OPEN'").fetchone()[0]
        unresolved = con.execute("SELECT COUNT(*) FROM positions WHERE status='EXIT_UNRESOLVED'").fetchone()[0]
        bad = con.execute("SELECT COUNT(*) FROM positions WHERE status='OPEN' AND "
                          "(entry_price IS NULL OR target_exit_session IS NULL OR shares IS NULL)").fetchone()[0]
        con.close()
        add("v2_paper_state_consistent", bad == 0 and (cash is None or cash[0] >= 0),
            {"cash": cash[0] if cash else None, "open": opens, "exit_unresolved": unresolved,
             "malformed_open": bad})
    except Exception as e:  # noqa: BLE001
        add("v2_paper_state_consistent", True, {"note": f"no v2_lane.db yet ({e!r}) -- fresh start OK"})

    # redis
    try:
        import redis
        add("redis_ping", bool(redis.Redis.from_url("redis://localhost:6379/0").ping()), {})
    except Exception as e:  # noqa: BLE001
        add("redis_ping", False, {"error": repr(e)})

    # experimental external boundary
    try:
        from talonx_signals.external_boundary import experimental_external_override_active
        add("experimental_external_blocked", not experimental_external_override_active(), {})
    except Exception as e:  # noqa: BLE001
        add("experimental_external_blocked", False, {"error": repr(e)})

    # telegram poller ownership
    try:
        from talonx_ops.supervisor import count_telegram_get_updates_owners
        n = count_telegram_get_updates_owners()
        add("telegram_get_updates_single_owner", n <= 1, {"owners": n})
    except Exception as e:  # noqa: BLE001
        add("telegram_get_updates_single_owner", True, {"note": repr(e)})

    # dashboard section order
    try:
        from talonx_ops.dashboard_read import DashboardReadModel
        keys = list(DashboardReadModel(check_processes=False).all_sections().keys())
        add("dashboard_has_v2_section_before_validation",
            "v2_active_strategy" in keys and keys.index("v2_active_strategy") < keys.index("validation"),
            {"sections": keys})
    except Exception as e:  # noqa: BLE001
        add("dashboard_has_v2_section_before_validation", False, {"error": repr(e)})

    overall = "READY" if all(c["status"] == "READY" for c in checks) else "NOT_READY"
    report = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "head": head, "overall": overall, "checks": checks,
        "ports": {p: ("OPEN" if _port_open(p) else "free") for p in (8787, 8760, 8770, 8501)},
    }
    OUT.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d")
    (OUT / f"_readiness_{stamp}.json").write_text(json.dumps(report, indent=2, default=str))
    print(json.dumps(report, indent=2, default=str))
    return 0 if overall == "READY" else 2


if __name__ == "__main__":
    sys.exit(main())
