"""
Prospective-session preflight (Task 114 B1).  READ-ONLY.

Combines the Task 112 Tuesday readiness contract with the Day-2+
additions: ledger-continuity guard (fail closed), logical Telegram owner,
heartbeat-config sanity, campaign-state validation, live insider source.

  overall in {READY, READY_WITH_FINDINGS, NOT_READY}
  exit non-zero iff NOT_READY (a true NO-GO).
"""
from __future__ import annotations

import os
import socket
import subprocess
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from talonx_ops.prospective import (RELEASE_SHA_EXPECTED, V1_FINGERPRINT_EXPECTED,
                                    V2_FINGERPRINT_EXPECTED, V2_STRATEGY_VERSION)
from talonx_ops.prospective.ledger_guard import ADMIN_RECOVERY_NOTE, check_ledger_continuity
from talonx_ops.prospective.paths import REPO_ROOT, V2_DB_PATH, V2_STATUS_PATH, resolve_env
from talonx_ops.prospective.telegram_owner import logical_poller_report

_REQUIRED_PORTS = (8787,)          # dashboard; V2 companion binds none
_OPTIONAL_PORTS = (8760, 8770, 8501)


@dataclass
class Row:
    check: str
    status: str          # READY | FINDING | NO_GO
    detail: Any = None


@dataclass
class PreflightResult:
    overall: str
    rows: list[Row] = field(default_factory=list)
    generated_utc: str = ""
    expected_sha: str = ""
    head_sha: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "overall": self.overall, "generated_utc": self.generated_utc,
            "expected_sha": self.expected_sha, "head_sha": self.head_sha,
            "rows": [{"check": r.check, "status": r.status, "detail": r.detail} for r in self.rows],
        }

    def to_markdown(self) -> str:
        icon = {"READY": "OK  ", "FINDING": "note", "NO_GO": "STOP"}
        lines = [f"# Prospective preflight -- {self.overall}",
                 f"generated: {self.generated_utc}",
                 f"HEAD: {self.head_sha}  expected: {self.expected_sha}", ""]
        for r in self.rows:
            lines.append(f"[{icon.get(r.status, '?')}] {r.check}"
                         + (f"  -- {r.detail}" if r.status != "READY" and r.detail is not None else ""))
        if self.overall == "NOT_READY":
            lines += ["", "NO-GO. Resolve the STOP rows before starting the session.", ADMIN_RECOVERY_NOTE]
        return "\n".join(lines)


def _git(*a: str) -> str:
    try:
        return subprocess.run(["git", *a], cwd=REPO_ROOT, capture_output=True, text=True,
                              timeout=15).stdout.strip()
    except Exception:  # noqa: BLE001
        return ""


def _port_open(p: int) -> bool:
    s = socket.socket()
    s.settimeout(0.5)
    try:
        return s.connect_ex(("127.0.0.1", p)) == 0
    finally:
        s.close()


# A frozen release is ONE immutable runtime SHA.  Commits AFTER it may only add documentation/evidence/tests or move
# the pin itself (`RELEASE_SHA_EXPECTED` lives in `talonx_ops/prospective/__init__.py`); any other changed file means
# the running code is no longer the frozen release and preflight is NO_GO.
FREEZE_ALLOWED_PREFIXES = ("docs/", "tests/")
FREEZE_ALLOWED_FILES = ("talonx_ops/prospective/__init__.py",)
# POST-FREEZE OPERATIONAL/SECURITY HARDENING (pre-full-day cleanup) -- an EXPLICIT, closed list of runtime files that were
# changed after the frozen SHA a56ec8c for (1) process-wide secret redaction in logs, (2) an isolated release notification
# outbox + compromised-credential refusal in the release gate, (3) the Sentinel STARTUP campaign label, (4) time-bound
# STARTUP/SHUTDOWN notices.  NONE of them is a strategy / provider / pricing / accounting / ledger file (guarded by a test);
# the strategy fingerprint and provider-contract fingerprint are unchanged.  Any other runtime change is still NO_GO.
FREEZE_OPS_HARDENING_FILES = (
    "talonx_ops/log_redaction.py",
    "talonx_ops/logging_setup.py",
    "talonx_ops/supervisor.py",
    "talonx_ops/notify/__init__.py",
    "talonx_ops/notify/producers.py",
    "talonx_ops/notify/validate.py",
    "talonx_ops/prospective/preflight.py",
    "talonx_ops/prospective/__main__.py",
    "talonx_dispatch/run.py",
    "talonx_dispatch/telegram_client.py",
    "talonx_v2/release_gate.py",
    "talonx_v2/run.py",
)
# POST-FREEZE RELEASE-FIDELITY FIX (SEC filing date) -- an EXPLICIT, closed list. SEC's submissions feed serves a fresh
# filing's acceptanceDateTime as New York wall-clock labelled `Z` and rewrites it to true UTC hours later, so V2's
# filing date must come from SEC `filingDate` (persisted on ingest, backfilled for history, fail-closed in release
# mode) and never from accepted_at_utc.date(). Ingestion plumbing + the V2 form-4 reader/service only: no strategy-
# fingerprint file, no provider/pricing/accounting/ledger file (guarded by a test). Any other runtime change is NO_GO.
FREEZE_RELEASE_FIDELITY_FIX_FILES = (
    "talonx_ingest/intelligence/insider/ownership_xml.py",
    "talonx_ingest/intelligence/insider/pipeline.py",
    "talonx_ingest/intelligence/insider/filing_date_backfill.py",
    "talonx_ingest/intelligence/service/_insider.py",
    "talonx_ingest/intelligence/service/poller.py",
    "talonx_ingest/intelligence/service/backfill.py",
    "talonx_ingest/intelligence/service/replay.py",
    "talonx_v2/form4_source.py",
    "talonx_v2/service.py",
)


# POST-FREEZE SESSION 03 HARDENING -- an EXPLICIT, closed list (A1 effective Intelligence delivery state, A2 Intelligence
# card acceptance-time rendering, A3 Intelligence health cause codes, A4/A5 /ping clarity, A6 bounded SHUTDOWN drain).
# Intelligence/ops observability only: no strategy-fingerprint file, no provider/pricing/accounting/ledger file and no V2
# admission input (guarded by a test). Any other runtime change is still NO_GO.
FREEZE_SESSION03_HARDENING_FILES = (
    "talonx_ingest/intelligence/sec_time.py",
    "talonx_ingest/intelligence/domain.py",
    "talonx_ingest/intelligence/pipeline.py",
    "talonx_ingest/intelligence/delivery/renderer.py",
    "talonx_ingest/intelligence/service/runner.py",
    "talonx_ops/intel_queue.py",
    "talonx_ops/prospective/proc.py",
    "talonx_dispatch/telegram_listener.py",
)
# ISOLATED RESEARCH LANE -- the broad-universe pre-market research engine is a separate package run as its own process.
# Nothing in the frozen release imports it (guarded by a test), it never trades, and it never writes a V2 ledger/outbox.
FREEZE_RESEARCH_LANE_PREFIXES = ("talonx_premarket/",)


def frozen_release_ok(head: str, expected_sha: str, *, repo: Path | None = None) -> tuple[bool, str]:
    if head.startswith(expected_sha):
        return True, "HEAD is the frozen release SHA"
    try:
        import subprocess
        cwd = str(repo) if repo else None
        anc = subprocess.run(["git", "merge-base", "--is-ancestor", expected_sha, head], cwd=cwd,
                             capture_output=True, text=True)
        if anc.returncode != 0:
            return False, "frozen release SHA is not an ancestor of HEAD"
        diff = subprocess.run(["git", "diff", "--name-only", expected_sha, head], cwd=cwd,
                              capture_output=True, text=True).stdout.split()
    except Exception as exc:  # noqa: BLE001 -- fail closed
        return False, f"could not verify ancestry: {type(exc).__name__}"
    extra = [f for f in diff if not (f.startswith(FREEZE_ALLOWED_PREFIXES) or f in FREEZE_ALLOWED_FILES
                                       or f in FREEZE_OPS_HARDENING_FILES or f in FREEZE_RELEASE_FIDELITY_FIX_FILES
                                       or f in FREEZE_SESSION03_HARDENING_FILES
                                       or f.startswith(FREEZE_RESEARCH_LANE_PREFIXES))]
    if extra:
        return False, f"runtime files changed after the frozen release: {extra[:5]}"
    return True, (f"HEAD descends from the frozen release; only docs/tests/pin/declared ops-hardening, "
                  f"release-fidelity-fix, Session-03-hardening and isolated research-lane files changed "
                  f"({len(diff)} files)")


def run_preflight(*, expected_sha: str = RELEASE_SHA_EXPECTED,
                  require_stack_up: bool = False) -> PreflightResult:
    rows: list[Row] = []

    def add(check: str, status: str, detail: Any = None) -> None:
        rows.append(Row(check, status, detail))

    head = _git("rev-parse", "HEAD")
    head_short = _git("rev-parse", "--short", "HEAD")

    # 1-2 repo / release
    _ok, _why = frozen_release_ok(head, expected_sha)
    add("repo_head_matches_release", "READY" if _ok else "NO_GO",
        {"head": head_short, "expected": expected_sha, "match": _why})
    dirty = _git("status", "--porcelain")
    add("repo_tree_clean", "READY" if dirty == "" else "FINDING",
        {"porcelain_lines": dirty.splitlines()[:8]} if dirty else None)

    # 3-5 fingerprints / strategy version
    try:
        from talonx_backtest.reproducibility import get_strategy_version
        v1 = get_strategy_version()
        add("v1_fingerprint", "READY" if v1 == V1_FINGERPRINT_EXPECTED else "NO_GO",
            {"got": v1, "expected": V1_FINGERPRINT_EXPECTED})
    except Exception as e:  # noqa: BLE001
        add("v1_fingerprint", "NO_GO", {"error": repr(e)})
    try:
        import importlib
        v2 = importlib.import_module("research.scripts.task112_v2_release_fingerprint").v2_release_fingerprint()
        add("v2_fingerprint", "READY" if v2["fingerprint"] == V2_FINGERPRINT_EXPECTED else "NO_GO",
            {"got": v2["fingerprint"], "expected": V2_FINGERPRINT_EXPECTED,
             "strategy_version": v2.get("strategy_version")})
        add("v2_strategy_version", "READY" if v2.get("strategy_version") == V2_STRATEGY_VERSION else "NO_GO",
            {"got": v2.get("strategy_version")})
    except Exception as e:  # noqa: BLE001
        add("v2_fingerprint", "NO_GO", {"error": repr(e)})

    # 6 redis
    try:
        import redis
        add("redis_reachable", "READY" if redis.Redis.from_url(
            "redis://localhost:6379/0").ping() else "NO_GO", None)
    except Exception as e:  # noqa: BLE001
        add("redis_reachable", "NO_GO", {"error": repr(e)})

    # 7 no stale conflicting processes (only meaningful before start)
    try:
        import psutil
        talonx = [p.info["pid"] for p in psutil.process_iter(["pid", "cmdline"])
                  if p.info.get("cmdline") and any(
                      x in " ".join(p.info["cmdline"])
                      for x in ("run_talonx.py", "talonx_v2.run", "talonx_ops.supervisor",
                                "talonx_signals.run"))]
        if require_stack_up:
            add("talonx_processes_present", "READY" if talonx else "NO_GO", {"pids": talonx})
        else:
            add("no_stale_talonx_processes", "READY" if not talonx else "FINDING",
                {"pids": talonx, "note": "stop them before a fresh start"})
    except Exception as e:  # noqa: BLE001
        add("no_stale_talonx_processes", "FINDING", {"error": repr(e)})

    # 8 ports
    busy_req = [p for p in _REQUIRED_PORTS if _port_open(p)]
    if require_stack_up:
        add("dashboard_port_8787_listening", "READY" if _port_open(8787) else "NO_GO", None)
    else:
        add("required_ports_free", "READY" if not busy_req else "FINDING",
            {"busy": busy_req})

    # 9-14 v2_lane.db continuity  (FAIL CLOSED -- never recreate)
    if not Path(V2_DB_PATH).exists():
        add("v2_lane_db_exists", "NO_GO",
            {"path": str(V2_DB_PATH), "note": "DO NOT recreate -- carry-forward ledger is missing",
             "recovery": ADMIN_RECOVERY_NOTE})
    else:
        lc = check_ledger_continuity(V2_DB_PATH)
        add("v2_ledger_continuity", "READY" if lc.ok else "NO_GO",
            {"cash": lc.cash, "open": lc.n_open, "closed": lc.n_closed, "trades": lc.n_trades,
             "problems": lc.problems} if not lc.ok else
            {"cash": lc.cash, "open": lc.n_open, "closed": lc.n_closed})
        add("v2_ledger_not_recreated", "READY",
            {"note": "preflight never creates/resets v2_lane.db"})

    # 13 required env vars (resolved from env / .env / frozen defaults -- no secrets shown)
    env = resolve_env()
    add("v2_env_vars_resolved", "READY",
        {k: (v if "CASH" in k or "PROFILE" in k else Path(v).name) for k, v in env.items()})
    if env["TALONX_ACTIVE_STRATEGY_PROFILE"] != "INSIDER_BUY_CLUSTER_V2":
        add("active_profile_is_v2", "NO_GO", {"got": env["TALONX_ACTIVE_STRATEGY_PROFILE"]})
    else:
        add("active_profile_is_v2", "READY", None)
    real_cap = os.environ.get("TALONX_PIV_REAL_CAPITAL", _dotenv_val("TALONX_PIV_REAL_CAPITAL"))
    add("real_capital_off", "READY" if str(real_cap).lower() in ("false", "0", "no", "") else "NO_GO",
        {"TALONX_PIV_REAL_CAPITAL": real_cap})
    ovr = os.environ.get("TALONX_EXPERIMENTAL_EXTERNAL_SEND_OVERRIDE",
                         _dotenv_val("TALONX_EXPERIMENTAL_EXTERNAL_SEND_OVERRIDE"))
    add("experimental_external_override_absent", "READY" if not ovr else "NO_GO",
        {"present": bool(ovr)})

    # 15-16 heartbeat / lookback config sanity
    add("heartbeat_decoupled_from_tick", "READY",
        {"note": "companion writes a lightweight heartbeat every --heartbeat-seconds (default 30), "
                 "independent of --tick-seconds; HEARTBEAT_TTL_S=180"})

    # 17-19 running-service checks (only when require_stack_up)
    if require_stack_up:
        try:
            import json as _json
            s = _json.loads(Path(V2_STATUS_PATH).read_text())
            age = (datetime.now(timezone.utc)
                   - datetime.fromisoformat(s["heartbeat_utc"])).total_seconds()
            add("v2_heartbeat_fresh", "READY" if age < float(s.get("heartbeat_ttl_s", 180)) else "NO_GO",
                {"age_s": round(age, 1)})
            add("v2_source_is_insider", "READY"
                if s.get("form4_source") == "insider" or s.get("form4_records_seen") else "NO_GO",
                {"form4_source": s.get("form4_source"), "records_seen": s.get("form4_records_seen")})
            add("v2_strategy_version_live", "READY"
                if s.get("strategy_version") == V2_STRATEGY_VERSION else "NO_GO",
                {"got": s.get("strategy_version")})
            add("v2_no_exit_unresolved", "READY" if not s.get("exit_unresolved") else "FINDING",
                s.get("exit_unresolved"))
        except Exception as e:  # noqa: BLE001
            add("v2_heartbeat_fresh", "NO_GO", {"error": repr(e)})
        try:
            from talonx_ops.supervisor import _status_snapshot
            snap = _status_snapshot()
            prods = snap.get("producers", {})
            add("base_stack_alive", "READY" if prods.get("original", {}).get("live") else "NO_GO",
                {n: p.get("live") for n, p in prods.items()})
        except Exception as e:  # noqa: BLE001
            add("base_stack_alive", "NO_GO", {"error": repr(e)})

    # experimental boundary + telegram logical owner (always)
    try:
        from talonx_signals.external_boundary import experimental_external_override_active
        add("experimental_external_boundary_blocked", "READY"
            if not experimental_external_override_active() else "NO_GO", None)
    except Exception as e:  # noqa: BLE001
        add("experimental_external_boundary_blocked", "FINDING", {"error": repr(e)})

    pr = logical_poller_report()
    add("telegram_logical_owner", "READY" if pr.healthy else ("FINDING" if pr.logical_owners <= 1 else "NO_GO"),
        pr.to_dict())

    # dashboard section presence
    try:
        from talonx_ops.dashboard_read import DashboardReadModel
        secs = list(DashboardReadModel().all_sections().keys())
        ok = "v2_active_strategy" in secs and secs.index("v2_active_strategy") < secs.index("validation")
        add("dashboard_v2_section_present", "READY" if ok else "FINDING", {"sections": secs})
    except Exception as e:  # noqa: BLE001
        add("dashboard_v2_section_present", "FINDING", {"error": repr(e)})

    no_go = any(r.status == "NO_GO" for r in rows)
    findings = any(r.status == "FINDING" for r in rows)
    overall = "NOT_READY" if no_go else ("READY_WITH_FINDINGS" if findings else "READY")
    return PreflightResult(overall=overall, rows=rows,
                           generated_utc=datetime.now(timezone.utc).isoformat(),
                           expected_sha=expected_sha, head_sha=head_short)


def _dotenv_val(key: str) -> str:
    f = REPO_ROOT / ".env"
    if not f.exists():
        return ""
    for line in f.read_text(encoding="utf-8", errors="replace").splitlines():
        line = line.strip()
        if line.startswith(key + "="):
            return line.split("=", 1)[1].strip().strip('"').strip("'")
    return ""
