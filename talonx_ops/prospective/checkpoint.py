"""One machine-readable prospective-session checkpoint (Task 114 B3)."""
from __future__ import annotations

import json
import sqlite3
import subprocess
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from talonx_ops.prospective import (V1_FINGERPRINT_EXPECTED, V2_FINGERPRINT_EXPECTED,
                                    V2_STRATEGY_VERSION, CAMPAIGN_START_DATE)
from talonx_ops.prospective.funnel import build_funnel
from talonx_ops.prospective.ledger_guard import check_ledger_continuity
from talonx_ops.prospective.paths import V2_DB_PATH, V2_STATUS_PATH, now_pair
from talonx_ops.prospective.telegram_owner import logical_poller_report


def _git(*args: str) -> str:
    try:
        return subprocess.run(["git", *args], capture_output=True, text=True,
                              cwd=Path(__file__).resolve().parents[2], timeout=15).stdout.strip()
    except Exception:  # noqa: BLE001
        return ""


def _v1_fp() -> str:
    try:
        from talonx_backtest.reproducibility import get_strategy_version
        return get_strategy_version()
    except Exception:  # noqa: BLE001
        return ""


def _v2_fp() -> str:
    try:
        import importlib
        m = importlib.import_module("research.scripts.task112_v2_release_fingerprint")
        return m.v2_release_fingerprint().get("fingerprint", "")
    except Exception:  # noqa: BLE001
        try:
            r = subprocess.run(
                ["python", "research/scripts/task112_v2_release_fingerprint.py"],
                capture_output=True, text=True, cwd=Path(__file__).resolve().parents[2], timeout=30)
            return json.loads(r.stdout).get("fingerprint", "")
        except Exception:  # noqa: BLE001
            return ""


def _v2_status() -> dict[str, Any]:
    try:
        return json.loads(Path(V2_STATUS_PATH).read_text())
    except Exception:  # noqa: BLE001
        return {}


def _age_s(ts: str | None, now: datetime) -> float | None:
    if not ts:
        return None
    try:
        return (now - datetime.fromisoformat(ts)).total_seconds()
    except Exception:  # noqa: BLE001
        return None


# Task 117 Phase 0 L1: bounded first-checkpoint warmup.  A just-started service
# has no status file yet -- without a grace window it is indistinguishable from a
# crashed one.  The window is bounded; when it expires without readiness the state
# is an EXPLICIT STARTUP_FAILED, never a silent pass.  Hard ledger / strategy
# safety invariants are NEVER suppressed during the grace (see _invariant_flags).
STARTUP_GRACE_S = 240


def _session_started_utc(now: datetime) -> datetime | None:
    """Start time of the most recent prospective session (session.pids.json)."""
    try:
        from talonx_ops.prospective.paths import session_dir
        for d in (now.date(), (now - timedelta(days=1)).date()):
            p = session_dir(d) / "session.pids.json"
            if p.exists():
                info = json.loads(p.read_text())
                return datetime.fromisoformat(info["started_utc"])
    except Exception:  # noqa: BLE001
        pass
    return None


def startup_grace(s: dict, now: datetime, started_utc: datetime | None) -> dict[str, Any]:
    """NOT_IN_STARTUP | STARTING | STARTUP_FAILED, with a hard deadline."""
    hb = _age_s(s.get("heartbeat_utc"), now)
    fresh = hb is not None and hb < float(s.get("heartbeat_ttl_s", 180))
    version_ok = s.get("strategy_version") == V2_STRATEGY_VERSION
    data_ready = s.get("form4_records_seen") is not None and bool(s.get("tick"))
    comps = {"heartbeat_fresh": bool(fresh), "strategy_version_ok": bool(version_ok),
             "first_tick_data_ready": bool(data_ready)}
    if fresh and version_ok and data_ready:
        return {"state": "NOT_IN_STARTUP", "reason": "components + first data ready",
                "components": comps}
    if started_utc is None:
        # no session marker -> can't grant grace; fall through to normal health
        return {"state": "NOT_IN_STARTUP", "reason": "no session start marker",
                "components": comps}
    age = (now - started_utc).total_seconds()
    deadline = started_utc + timedelta(seconds=STARTUP_GRACE_S)
    if age <= STARTUP_GRACE_S:
        return {"state": "STARTING", "reason": "within bounded warmup grace",
                "started_utc": started_utc.isoformat(), "deadline_utc": deadline.isoformat(),
                "seconds_remaining": round(STARTUP_GRACE_S - age, 1), "components": comps}
    # STARTUP_FAILED is only meaningful in the window just after the deadline;
    # once the session-start marker is old (> 3x grace) it is simply stale and
    # normal DOWN/DEGRADED health stands.
    if age <= STARTUP_GRACE_S * 3:
        return {"state": "STARTUP_FAILED",
                "reason": f"warmup grace {STARTUP_GRACE_S}s exhausted without readiness",
                "started_utc": started_utc.isoformat(), "deadline_utc": deadline.isoformat(),
                "components": comps}
    return {"state": "NOT_IN_STARTUP", "reason": "session start marker is stale",
            "started_utc": started_utc.isoformat(), "components": comps}


def _service_health(s: dict, now: datetime,
                    started_utc: datetime | None = None) -> dict[str, Any]:
    hb = _age_s(s.get("heartbeat_utc"), now)
    ttl = float(s.get("heartbeat_ttl_s", 180))
    if not s:
        health = "DOWN"
    elif hb is None:
        health = "DOWN"
    elif hb < ttl:
        health = "HEALTHY"
    elif hb < ttl * 3:
        health = "DEGRADED"
    else:
        health = "DOWN"
    warmup = startup_grace(s, now, started_utc)
    # a bounded warmup masks DOWN/DEGRADED -> STARTING; an exhausted grace is an
    # explicit failure, not a silent DOWN.
    if warmup["state"] == "STARTING" and health in ("DOWN", "DEGRADED"):
        health = "STARTING"
    elif warmup["state"] == "STARTUP_FAILED":
        health = "STARTUP_FAILED"
    return {"health": health, "heartbeat_age_s": None if hb is None else round(hb, 1),
            "heartbeat_ttl_s": ttl, "heartbeat_kind": s.get("heartbeat_kind"),
            "tick": s.get("tick"), "last_tick_utc": s.get("last_tick_utc"),
            "strategy_version": s.get("strategy_version"),
            "active_profile": s.get("active_profile"),
            "startup": warmup}


def _supervisor_status() -> dict[str, Any]:
    try:
        from talonx_ops.supervisor import _status_snapshot
        return _status_snapshot()
    except Exception as exc:  # noqa: BLE001
        return {"error": f"{type(exc).__name__}: {exc}"}


def _market() -> dict[str, Any]:
    try:
        from dataclasses import asdict, is_dataclass
        from talonx_ops.market_health import market_health_view
        v = market_health_view()
        d = asdict(v) if is_dataclass(v) else vars(v)
        return {"state": d.get("state"), "producer_live": d.get("producer_live"),
                "symbols_priced": d.get("symbols_priced"),
                "newest_tick_age_seconds": d.get("newest_tick_age_seconds"),
                "coverage_ratio": d.get("coverage_ratio"),
                "session_phase": d.get("session_phase")}
    except Exception as exc:  # noqa: BLE001
        return {"error": f"{type(exc).__name__}: {exc}"}


def _intel() -> dict[str, Any]:
    try:
        import pathlib as _p
        led = _p.Path.home() / ".talonx" / "ingestion_ledger.db"
        con = sqlite3.connect(f"file:{led}?mode=ro", uri=True)
        proc = con.execute("SELECT MAX(at_utc) FROM intel_processing_log").fetchone()[0]
        newest_ev = con.execute("SELECT MAX(accepted_at_utc) FROM insider_transactions").fetchone()[0]
        today = datetime.now(timezone.utc).date().isoformat()
        events_today = con.execute(
            "SELECT COUNT(*) FROM intel_event_processing WHERE discovered_at_utc >= ?", (today,)).fetchone()[0]
        con.close()
        now = datetime.now(timezone.utc)
        return {"processing_log_age_s": _age_s(proc, now), "newest_insider_event_utc": newest_ev,
                "intel_events_discovered_today": int(events_today)}
    except Exception as exc:  # noqa: BLE001
        return {"error": f"{type(exc).__name__}: {exc}"}


def _experimental_external_sends_today() -> dict[str, Any]:
    out: dict[str, Any] = {"override_active": None, "sent_today": 0, "held": 0}
    try:
        from talonx_signals.external_boundary import experimental_external_override_active
        out["override_active"] = bool(experimental_external_override_active())
    except Exception:  # noqa: BLE001
        pass
    try:
        import pathlib as _p
        db = _p.Path.home() / ".talonx" / "experimental" / "exp_alerts.db"
        if db.exists():
            con = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
            today = datetime.now(timezone.utc).date().isoformat()
            try:
                out["sent_today"] = con.execute(
                    "SELECT COUNT(*) FROM directional_alerts WHERE sent=1 AND created_at >= ?",
                    (today,)).fetchone()[0]
            except sqlite3.Error:
                pass
            try:
                out["held"] = con.execute(
                    "SELECT COUNT(*) FROM dispatch_log WHERE event='DRY_RUN_HELD' AND at >= ?",
                    (today,)).fetchone()[0]
            except sqlite3.Error:
                pass
            con.close()
    except Exception:  # noqa: BLE001
        pass
    return out


def _official_dispatch_today() -> dict[str, Any]:
    try:
        import pathlib as _p
        db = _p.Path.home() / ".talonx" / "dispatch_audit.db"
        con = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
        today = datetime.now(timezone.utc).date().isoformat()
        alerts = con.execute("SELECT COUNT(*) FROM alerts WHERE received_at >= ?", (today,)).fetchone()[0]
        fails = con.execute(
            "SELECT COUNT(*) FROM alerts WHERE received_at >= ? AND telegram_error IS NOT NULL",
            (today,)).fetchone()[0]
        con.close()
        return {"alerts_today": int(alerts), "telegram_failures_today": int(fails)}
    except Exception as exc:  # noqa: BLE001
        return {"error": f"{type(exc).__name__}: {exc}"}


def eod_state(now: datetime | None = None) -> dict[str, Any]:
    """Market-phase-aware EOD state (Task 114 A5.4): NOT_DUE_YET before the
    close, PENDING in the grace window, STALE only after the deadline is
    actually missed."""
    now = now or datetime.now(timezone.utc)
    try:
        import exchange_calendars as xc
        cal = xc.get_calendar("XNYS")
        d = now.date()
        if not cal.is_session(d):
            return {"state": "NOT_DUE_YET", "reason": "not an XNYS session today"}
        close = cal.session_close(d).to_pydatetime()
        deadline = close + timedelta(minutes=90)
        if now < close:
            return {"state": "NOT_DUE_YET", "reason": f"XNYS close {close.isoformat()} not reached",
                    "close_utc": close.isoformat()}
        if now < deadline:
            return {"state": "PENDING", "reason": "within the post-close EOD grace window",
                    "close_utc": close.isoformat(), "deadline_utc": deadline.isoformat()}
        return {"state": "STALE", "reason": "EOD reconciliation deadline missed",
                "close_utc": close.isoformat(), "deadline_utc": deadline.isoformat()}
    except Exception as exc:  # noqa: BLE001
        return {"state": "UNKNOWN", "reason": f"{type(exc).__name__}: {exc}"}


def campaign_day(now: datetime | None = None) -> int:
    now = now or datetime.now(timezone.utc)
    try:
        import exchange_calendars as xc
        cal = xc.get_calendar("XNYS")
        start = date.fromisoformat(CAMPAIGN_START_DATE)
        d = now.date()
        if d < start:
            return 0
        return len(cal.sessions_in_range(start.isoformat(), d.isoformat()))
    except Exception:  # noqa: BLE001
        return 0


# Task 138: qualified outcomes for scope evidence -- Task 137's own
# `_live_companion_uses_broad_discovery` compared a bare count with NO
# check that the status snapshot was actually fresh, or that it belonged
# to the process currently running (a stale file left by a since-dead or
# since-replaced companion would be read exactly the same way). Every
# outcome below is a distinct, explicit, reported qualification -- a
# stale/unowned/malformed snapshot is NEVER silently treated as "verified
# live scope", and a genuine narrow (watchlist-only) result is never
# reported as if it were successful broad coverage.
SCOPE_FRESH_VALID = "FRESH_VALID"
SCOPE_STALE = "STALE"
SCOPE_MISSING_MALFORMED = "MISSING_MALFORMED"
SCOPE_WRONG_PROCESS = "WRONG_PROCESS"
SCOPE_MANIFEST_UNREADABLE = "MANIFEST_UNREADABLE"
SCOPE_MISMATCH = "SCOPE_MISMATCH"


def _session_pids_info(now: datetime) -> dict[str, Any]:
    """The most recent prospective session's full session.pids.json
    (today, then yesterday) -- run identity/argv evidence, same file
    `_session_started_utc` already reads a single field from."""
    try:
        from talonx_ops.prospective.paths import session_dir

        for d in (now.date(), (now - timedelta(days=1)).date()):
            p = session_dir(d) / "session.pids.json"
            if p.exists():
                return json.loads(p.read_text())
    except Exception:  # noqa: BLE001
        pass
    return {}


def evaluate_scope_evidence(status: dict[str, Any], now: datetime) -> dict[str, Any]:
    """Task 138: qualify the live V2 companion's reported execution scope
    before treating it as evidence for anything -- reuses EXISTING runtime
    metadata (the same `heartbeat_utc`/`heartbeat_ttl_s` freshness fields
    `_service_health` already reads; `session.pids.json`'s own recorded
    PID + argv; `psutil`-backed liveness via `talonx_ops.prospective.
    proc._alive`), never a new, independent liveness mechanism.

    Returns a dict with at least ``qualification`` (one of the
    ``SCOPE_*`` constants above) and ``broad_discovery_active`` (bool --
    only ever True for ``FRESH_VALID``) plus a human ``reason`` and the
    raw counts involved, so a caller can report UNKNOWN/DEGRADED with a
    reason rather than silently falling back to a narrow scope and
    calling it successful broad coverage.
    """
    reported = status.get("execution_scope_count")
    if not status or not isinstance(reported, int):
        return {"qualification": SCOPE_MISSING_MALFORMED, "broad_discovery_active": False,
                "reason": "no status file, or execution_scope_count missing/non-integer",
                "reported_scope_count": reported}

    hb_age = _age_s(status.get("heartbeat_utc"), now)
    ttl = float(status.get("heartbeat_ttl_s", 180))
    if hb_age is None:
        return {"qualification": SCOPE_MISSING_MALFORMED, "broad_discovery_active": False,
                "reason": "status has no parseable heartbeat_utc",
                "reported_scope_count": reported}
    if hb_age > ttl:
        return {"qualification": SCOPE_STALE, "broad_discovery_active": False,
                "reason": f"heartbeat {hb_age:.0f}s old > ttl {ttl:.0f}s -- "
                          "snapshot not treated as live evidence",
                "reported_scope_count": reported, "heartbeat_age_s": round(hb_age, 1)}

    # process/run identity, where existing metadata supports it: the
    # recorded companion PID must still be the one actually running.
    pids = _session_pids_info(now)
    companion_pid = pids.get("v2_companion_pid")
    if companion_pid is not None:
        try:
            from talonx_ops.prospective.proc import _alive
        except Exception:  # noqa: BLE001
            _alive = None
        if _alive is not None and not _alive(companion_pid):
            return {"qualification": SCOPE_WRONG_PROCESS, "broad_discovery_active": False,
                    "reason": f"session.pids.json names companion PID {companion_pid}, "
                              "which is not currently alive -- snapshot may belong to a "
                              "dead/replaced process",
                    "reported_scope_count": reported}
    argv = pids.get("v2_argv") or []
    argv_says_broad = "--enable-broad-discovery" in argv

    from talonx_ops.prospective.funnel import _BROAD_DISCOVERY_MANIFEST, _resolved_execution_scope

    try:
        watchlist_only = _resolved_execution_scope(include_broad_discovery=False)
    except Exception as exc:  # noqa: BLE001
        return {"qualification": SCOPE_MISSING_MALFORMED, "broad_discovery_active": False,
                "reason": f"could not resolve the watchlist-only scope: {exc!r}",
                "reported_scope_count": reported}
    watchlist_only_count = len(watchlist_only) if watchlist_only is not None else 0

    # _resolved_execution_scope() deliberately never raises on a manifest
    # problem (it must not crash the observational funnel) -- checked
    # explicitly and separately here instead, so a missing/unreadable
    # manifest is its own distinct, reported qualification rather than
    # silently degrading to "narrow scope confirmed".
    try:
        _BROAD_DISCOVERY_MANIFEST.read_text()
    except Exception as exc:  # noqa: BLE001
        return {"qualification": SCOPE_MANIFEST_UNREADABLE, "broad_discovery_active": False,
                "reason": f"discovery manifest unreadable at {_BROAD_DISCOVERY_MANIFEST}: {exc!r}",
                "reported_scope_count": reported, "watchlist_only_count": watchlist_only_count}
    reconstructed = _resolved_execution_scope(include_broad_discovery=True)
    reconstructed_count = len(reconstructed) if reconstructed is not None else 0

    active = argv_says_broad or reported > watchlist_only_count
    if not active:
        return {"qualification": SCOPE_FRESH_VALID, "broad_discovery_active": False,
                "reason": "fresh, owned snapshot; narrow (watchlist-only) scope confirmed "
                          "-- reported as narrow, not as successful broad coverage",
                "reported_scope_count": reported, "watchlist_only_count": watchlist_only_count,
                "reconstructed_scope_count": watchlist_only_count}

    if reported != reconstructed_count:
        return {"qualification": SCOPE_MISMATCH, "broad_discovery_active": False,
                "reason": f"reported scope ({reported}) differs from the reconstructed "
                          f"watchlist-union-manifest scope ({reconstructed_count}) -- "
                          "not treated as confirmed until reconciled",
                "reported_scope_count": reported, "watchlist_only_count": watchlist_only_count,
                "reconstructed_scope_count": reconstructed_count}

    return {"qualification": SCOPE_FRESH_VALID, "broad_discovery_active": True,
            "reason": "fresh, owned snapshot; argv confirms --enable-broad-discovery; "
                      "reported scope matches the reconstructed watchlist-union-manifest scope",
            "reported_scope_count": reported, "watchlist_only_count": watchlist_only_count,
            "reconstructed_scope_count": reconstructed_count}


def capture(now: datetime | None = None) -> dict[str, Any]:
    now = now or datetime.now(timezone.utc)
    s = _v2_status()
    v1fp, v2fp = _v1_fp(), _v2_fp()
    ledger = check_ledger_continuity(V2_DB_PATH)
    scope_evidence = evaluate_scope_evidence(s, now)
    funnel = build_funnel(db_path=V2_DB_PATH, as_of=now.date(),
                          include_broad_discovery=scope_evidence["broad_discovery_active"])
    funnel.setdefault("scope", {})["evidence"] = scope_evidence
    poller = logical_poller_report()
    market = _market()
    intel = _intel()
    exp = _experimental_external_sends_today()
    official = _official_dispatch_today()
    svc = _service_health(s, now, _session_started_utc(now))
    eods = eod_state(now)

    # data state (A4)
    if funnel.get("available"):
        data_state = "CURRENT"
    elif "form4_error" in funnel:
        data_state = "UNAVAILABLE"
    else:
        data_state = "UNKNOWN"

    # business activity (A4)
    term = funnel.get("terminal", {})
    if term.get("open_positions", 0) > 0:
        activity = "POSITION_OPEN"
    elif term.get("buys", 0) > 0:
        activity = "ACTIVITY"
    elif funnel.get("interpretation") == "NO_MARKET_OPPORTUNITY":
        activity = "NO_OPPORTUNITIES"
    else:
        activity = "NO_OPPORTUNITIES"

    ck: dict[str, Any] = {
        "checkpoint_version": 1,
        "time": now_pair(),
        "campaign": {"start_date": CAMPAIGN_START_DATE, "campaign_day": campaign_day(now),
                     "day1_outcome": "NO_NATURAL_V2_SIGNAL"},
        "release": {
            "head_sha": _git("rev-parse", "HEAD"),
            "head_short": _git("rev-parse", "--short", "HEAD"),
            "tree_clean": _git("status", "--porcelain") == "",
            "v1_fingerprint": v1fp, "v1_fingerprint_ok": v1fp == V1_FINGERPRINT_EXPECTED,
            "v2_fingerprint": v2fp, "v2_fingerprint_ok": v2fp == V2_FINGERPRINT_EXPECTED,
        },
        "service_health": svc,
        "data_state": data_state,
        "business_activity": activity,
        "v2": {
            "strategy_version": s.get("strategy_version"),
            "strategy_version_ok": s.get("strategy_version") == V2_STRATEGY_VERSION,
            "source": s.get("form4_source", "insider" if s.get("form4_records_seen") else "unknown"),
            "live_lookback_days": s.get("live_lookback_days"),
            "form4_records_seen": s.get("form4_records_seen"),
            "ripe_episodes_this_tick": s.get("ripe_episodes_this_tick"),
            "stale_entry_skipped_this_tick": s.get("stale_entry_skipped_this_tick"),
            "entries_this_tick": s.get("entries_this_tick"),
            "exits_this_tick": s.get("exits_this_tick"),
            "open_positions": s.get("open_positions"),
            "cash": s.get("cash"),
            "exit_unresolved": s.get("exit_unresolved", []),
            "eod_forced_flatten": s.get("eod_forced_flatten", False),
            "real_capital": s.get("real_capital", False),
            "shorts": s.get("shorts", False),
        },
        "ledger": ledger.to_dict(),
        "funnel": funnel,
        "market": market,
        "intelligence": intel,
        "experimental": exp,
        "official_dispatch": official,
        "telegram_poller": poller.to_dict(),
        "supervisor": _supervisor_status(),
        "eod": eods,
        "invariants": _invariant_flags(s, ledger, funnel, exp, poller, svc),
    }
    return ck


def _stale_episode_entered(db_path, stale_ids: set[str]) -> bool:
    if not stale_ids or not Path(db_path).exists():
        return False
    try:
        con = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
        qs = ",".join("?" * len(stale_ids))
        rows = con.execute(
            f"SELECT p.episode_id FROM positions p WHERE p.episode_id IN ({qs})",
            tuple(stale_ids)).fetchall()
        con.close()
        return len(rows) > 0
    except sqlite3.Error:
        return False


def _invariant_flags(s, ledger, funnel, exp, poller, svc) -> dict[str, Any]:
    """The hard CRITICAL/NO-GO checks (Task 114 B4).  Health-gated flags
    only fire when the V2 service is actually up."""
    from talonx_ops.prospective.paths import V2_DB_PATH
    live = svc["health"] in ("HEALTHY", "DEGRADED")
    starting = svc["health"] == "STARTING"          # bounded warmup -> not "dead"
    flags: dict[str, bool] = {}
    # always-meaningful ledger invariants (read straight from v2_lane.db)
    flags["negative_cash"] = bool(ledger.cash is not None and ledger.cash < 0)
    flags["ledger_equation_broken"] = any("equation broken" in p for p in ledger.problems)
    flags["duplicate_buy"] = any("duplicate BUY" in p for p in ledger.problems)
    flags["duplicate_position"] = any("duplicate position" in p for p in ledger.problems)
    stale_ids = set(funnel.get("clusters", {}).get("stale_episode_ids", []))
    flags["stale_episode_entered"] = _stale_episode_entered(V2_DB_PATH, stale_ids)
    flags["experimental_external_send"] = bool(exp.get("sent_today"))
    flags["experimental_override_active"] = bool(exp.get("override_active"))
    flags["multiple_telegram_pollers"] = not poller.healthy
    # service-gated invariants
    flags["v2_eod_forced_flatten"] = live and bool(s.get("eod_forced_flatten"))
    flags["v2_real_capital"] = live and bool(s.get("real_capital"))
    flags["v2_shorts"] = live and bool(s.get("shorts"))
    flags["v2_source_not_insider"] = live and (s.get("form4_source") not in (None, "insider")
                                               or s.get("form4_records_seen") == 0)
    flags["strategy_version_mismatch"] = live and s.get("strategy_version") != V2_STRATEGY_VERSION
    # a status file exists but the service is not fresh -- EXCEPT during the
    # bounded startup grace (Task 117 Phase 0 L1).  An exhausted grace is its
    # own explicit CRITICAL.
    flags["v2_process_dead"] = (live is False and not starting
                                and svc["health"] != "STARTUP_FAILED" and bool(s))
    flags["v2_startup_failed"] = svc["health"] == "STARTUP_FAILED"
    flags["any_critical"] = any(v for k, v in flags.items() if k != "any_critical")
    return flags
