"""
Task 114 -- autonomous prospective operator (114B) + unified V2 dashboard (114A).

Covers: heartbeat decoupled from strategy tick; ledger-continuity guard
(healthy + fail-closed); logical Telegram owner (shim false-positive);
V2 near-miss funnel; checkpoint capture; event classification
(INFO/WARNING/CRITICAL); session loop; evening close (NOT_DUE_YET +
reconcile + no-flatten); preflight; dashboard health/data/activity
separation + EOD NOT_DUE_YET vs STALE + funnel + Active-V2 on overview;
restart idempotency; no strategy semantics / fingerprint change.
"""
from __future__ import annotations

import json
import sqlite3
import threading
import time
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import pytest

from talonx_v2.config import V2Config
from talonx_v2.service import HEARTBEAT_TTL_S, V2Service
from talonx_v2.store import V2Store

BALANCE = 300_000.0


# ======================================================================
# B5 -- heartbeat decoupled from strategy tick cadence
# ======================================================================

def test_b5_heartbeat_independent_of_tick_seconds(tmp_path):
    cfg = V2Config(db_path=str(tmp_path / "v2.db"), starting_cash_usd=BALANCE)
    svc = V2Service(config=cfg, bar_dirs=[tmp_path], form4_kind="parquet",
                    status_path=str(tmp_path / "s.json"))
    svc._records = lambda *, as_of: []  # noqa: SLF001
    # tick cadence far larger than the heartbeat TTL -- must NOT go stale
    t = threading.Thread(target=lambda: svc.run(once=False, tick_seconds=3600, heartbeat_seconds=1),
                         daemon=True)
    t.start()
    time.sleep(3.5)
    svc._stop = True  # noqa: SLF001
    t.join(timeout=5)
    s = json.loads((tmp_path / "s.json").read_text())
    age = (datetime.now(timezone.utc) - datetime.fromisoformat(s["heartbeat_utc"])).total_seconds()
    assert age < HEARTBEAT_TTL_S, "heartbeat went stale despite the decoupled cadence"
    assert s["heartbeat_kind"] == "LIGHTWEIGHT"
    assert s["tick"] == 1, "strategy tick advanced -- cadence not decoupled"


def test_b5_status_file_written_atomically(tmp_path):
    cfg = V2Config(db_path=str(tmp_path / "v2.db"), starting_cash_usd=BALANCE)
    svc = V2Service(config=cfg, bar_dirs=[tmp_path], form4_kind="parquet",
                    status_path=str(tmp_path / "s.json"))
    svc._records = lambda *, as_of: []  # noqa: SLF001
    svc.tick(as_of=date(2026, 9, 9))
    assert not (tmp_path / "s.json.tmp").exists()
    assert json.loads((tmp_path / "s.json").read_text())["form4_source"] == "parquet"


# ======================================================================
# B2 -- ledger continuity guard (fail closed)
# ======================================================================

def _seed_ledger(path, cash=BALANCE, with_stale=True):
    V2Store(str(path), starting_cash=cash)
    if with_stale:
        s = V2Store(str(path))
        s.record_disposition(episode_id="07242bc857569f60", symbol="ABCL",
                             disposition="SKIPPED_ENTRY_STALE", issuer_cik="0001703057",
                             eligible_entry_session="2026-08-17")


def test_b2_ledger_continuity_healthy(tmp_path):
    from talonx_ops.prospective.ledger_guard import check_ledger_continuity
    db = tmp_path / "v2_lane.db"
    _seed_ledger(db)
    r = check_ledger_continuity(db)
    assert r.ok, r.problems
    assert r.cash == BALANCE and r.n_open == 0 and r.n_buys == 0


def test_b2_ledger_missing_fails_closed(tmp_path):
    from talonx_ops.prospective.ledger_guard import check_ledger_continuity
    r = check_ledger_continuity(tmp_path / "nope.db")
    assert not r.ok
    assert any("DOES NOT EXIST" in p for p in r.problems)


def test_b2_negative_cash_fails_closed(tmp_path):
    from talonx_ops.prospective.ledger_guard import check_ledger_continuity
    db = tmp_path / "v2_lane.db"
    _seed_ledger(db)
    con = sqlite3.connect(str(db))
    con.execute("UPDATE portfolio SET cash=-1 WHERE id=1")
    con.commit()
    con.close()
    r = check_ledger_continuity(db)
    assert not r.ok
    assert any("NEGATIVE CASH" in p for p in r.problems)


def test_b2_broken_equation_fails_closed(tmp_path):
    from talonx_ops.prospective.ledger_guard import check_ledger_continuity
    db = tmp_path / "v2_lane.db"
    _seed_ledger(db)
    con = sqlite3.connect(str(db))
    con.execute("INSERT INTO trades (episode_id,symbol,action,execution_price,shares,position_cost,"
                "portfolio_cash_after,executed_at) VALUES ('x','X','BUY',10,1,10,1,'2026-09-09')")
    con.commit()
    con.close()
    r = check_ledger_continuity(db)
    assert not r.ok
    assert any("equation broken" in p for p in r.problems)


def test_b2_guard_never_writes(tmp_path):
    from talonx_ops.prospective.ledger_guard import check_ledger_continuity
    db = tmp_path / "v2_lane.db"
    _seed_ledger(db)
    before = db.stat().st_mtime_ns
    time.sleep(0.01)
    check_ledger_continuity(db)
    assert db.stat().st_mtime_ns == before, "ledger guard modified the ledger"


# ======================================================================
# B6 -- Telegram logical owner (shim false-positive tolerated, real dup flagged)
# ======================================================================

def test_b6_shim_child_pair_is_one_logical_owner(monkeypatch):
    from talonx_ops.prospective import telegram_owner as to
    monkeypatch.setattr(to, "_network_pids", lambda: ([], "psutil-unavailable"))
    monkeypatch.setattr("talonx_ops.supervisor.count_telegram_get_updates_owners", lambda: 2)
    r = to.logical_poller_report()
    assert r.logical_owners == 1 and r.healthy, r.to_dict()


def test_b6_two_independent_network_pollers_is_degraded(monkeypatch):
    from talonx_ops.prospective import telegram_owner as to
    monkeypatch.setattr(to, "_network_pids", lambda: ([111, 222], "ok"))
    r = to.logical_poller_report()
    assert r.logical_owners == 2 and not r.healthy


def test_b6_single_network_poller_healthy(monkeypatch):
    from talonx_ops.prospective import telegram_owner as to
    monkeypatch.setattr(to, "_network_pids", lambda: ([3160], "ok"))
    r = to.logical_poller_report()
    assert r.logical_owners == 1 and r.healthy


# ======================================================================
# A3 -- V2 near-miss funnel
# ======================================================================

def test_a3_funnel_stale_abcl_is_accounted(tmp_path):
    from talonx_ops.prospective.funnel import build_funnel
    db = tmp_path / "v2_lane.db"
    _seed_ledger(db)
    fn = build_funnel(db_path=db, as_of=date(2026, 9, 9))
    assert "terminal" in fn
    disp = fn["terminal"]["processed_episode_dispositions"]
    assert disp.get("SKIPPED_ENTRY_STALE", 0) >= 1
    assert fn["terminal"]["buys"] == 0 and fn["terminal"]["sells"] == 0
    assert fn["interpretation"] in {"NO_MARKET_OPPORTUNITY", "STRATEGY_SELECTIVE",
                                    "DATA_UNAVAILABLE", "REVIEW_POSSIBLE_SUPPRESSION", "ACTIVITY"}


# ======================================================================
# B3 -- checkpoint capture
# ======================================================================

def test_b3_checkpoint_has_required_fields():
    from talonx_ops.prospective.checkpoint import capture
    ck = capture()
    for key in ("time", "campaign", "release", "service_health", "data_state",
                "business_activity", "v2", "ledger", "funnel", "market", "intelligence",
                "experimental", "official_dispatch", "telegram_poller", "supervisor",
                "eod", "invariants"):
        assert key in ck, f"checkpoint missing {key}"
    assert set(ck["time"]) == {"utc", "europe_london"}
    assert ck["service_health"]["health"] in {"HEALTHY", "DEGRADED", "DOWN", "UNKNOWN"}
    assert ck["eod"]["state"] in {"NOT_DUE_YET", "PENDING", "STALE", "RECONCILED_PASS",
                                  "PARTIAL", "FAILED", "UNKNOWN"}


def test_b3_eod_state_not_due_before_close(monkeypatch):
    from talonx_ops.prospective.checkpoint import eod_state
    # 2026-09-09 is an XNYS session; 10:00 UTC is well before the 20:00 close
    es = eod_state(datetime(2026, 9, 9, 10, 0, tzinfo=timezone.utc))
    assert es["state"] == "NOT_DUE_YET"


def test_b3_eod_state_pending_then_stale(monkeypatch):
    from talonx_ops.prospective.checkpoint import eod_state
    assert eod_state(datetime(2026, 9, 9, 20, 30, tzinfo=timezone.utc))["state"] == "PENDING"
    assert eod_state(datetime(2026, 9, 9, 23, 0, tzinfo=timezone.utc))["state"] == "STALE"


# ======================================================================
# B4 -- event classification
# ======================================================================

def _ck(**over):
    base = {"invariants": {}, "funnel": {"form4": {}, "clusters": {}, "terminal": {}},
            "service_health": {"health": "HEALTHY"}, "market": {"state": "HEALTHY"},
            "intelligence": {}, "official_dispatch": {}, "supervisor": {"producers": {}}}
    base.update(over)
    return base


def test_b4_critical_on_stale_episode_entered():
    from talonx_ops.prospective.events import classify
    curr = _ck(invariants={"stale_episode_entered": True, "any_critical": True})
    evs = classify(None, curr)
    assert any(e["level"] == "CRITICAL" and e["kind"] == "stale_episode_entered" for e in evs)


def test_b4_critical_on_experimental_external_send():
    from talonx_ops.prospective.events import classify
    curr = _ck(invariants={"experimental_external_send": True, "any_critical": True})
    evs = classify(None, curr)
    assert any(e["level"] == "CRITICAL" and e["kind"] == "experimental_external_send" for e in evs)


def test_b4_info_on_cluster_formed():
    from talonx_ops.prospective.events import classify
    prev = _ck(funnel={"form4": {}, "clusters": {"clusters_ge2_distinct_insiders": 0,
                                                 "cluster_symbols": []}, "terminal": {}})
    curr = _ck(funnel={"form4": {}, "clusters": {"clusters_ge2_distinct_insiders": 1,
                                                 "cluster_symbols": ["FOO"]}, "terminal": {}})
    evs = classify(prev, curr)
    assert any(e["level"] == "INFO" and e["kind"] == "cluster_formed" for e in evs)


def test_b4_warning_on_market_degraded():
    from talonx_ops.prospective.events import classify
    curr = _ck(market={"state": "STALE"})
    evs = classify(_ck(), curr)
    assert any(e["level"] == "WARNING" and e["kind"] == "market_degraded" for e in evs)


def test_b4_healthy_zero_activity_emits_nothing():
    from talonx_ops.prospective.events import classify
    evs = classify(_ck(), _ck())
    assert evs == []


# ======================================================================
# B3/B4 -- session loop writes checkpoints + events, honours stop.flag
# ======================================================================

def test_b3_session_loop_writes_and_stops(tmp_path):
    from talonx_ops.prospective.session_loop import run_loop
    run_loop(tmp_path, checkpoint_every_s=1, until_close=False, max_iterations=2)
    cps = sorted((tmp_path / "checkpoints").glob("checkpoint_*.json"))
    assert len(cps) >= 3  # 2 iterations + 1 final
    assert (tmp_path / "checkpoints" / "latest.json").exists()


def test_b3_session_loop_stop_flag(tmp_path):
    from talonx_ops.prospective.session_loop import run_loop
    (tmp_path / "stop.flag").write_text("x")
    rc = run_loop(tmp_path, checkpoint_every_s=1, until_close=False)
    assert rc == 0
    # only the final checkpoint
    assert len(list((tmp_path / "checkpoints").glob("checkpoint_*.json"))) == 1


# ======================================================================
# B7 -- evening close
# ======================================================================

def test_b7_close_not_due_yet_before_market_close(tmp_path, monkeypatch):
    from talonx_ops.prospective import close as closemod
    monkeypatch.setattr(closemod, "eod_state",
                        lambda now=None: {"state": "NOT_DUE_YET", "reason": "before close"})
    res = closemod.run_close(tmp_path, do_shutdown=False)
    assert res.verdict == "NOT_DUE_YET"


def test_b7_close_reconciles_zero_activity_ledger(tmp_path, monkeypatch):
    from talonx_ops.prospective import close as closemod
    from talonx_ops.prospective import paths as pmod
    db = tmp_path / "v2_lane.db"
    _seed_ledger(db)
    (tmp_path / "v2_service_status.json").write_text(json.dumps({
        "strategy_version": "INSIDER_BUY_CLUSTER_V2@1", "heartbeat_utc":
        datetime.now(timezone.utc).isoformat(), "heartbeat_ttl_s": 180,
        "eod_forced_flatten": False, "real_capital": False, "shorts": False,
        "form4_source": "insider", "form4_records_seen": 24, "cash": BALANCE}))
    monkeypatch.setattr(pmod, "V2_DB_PATH", db)
    monkeypatch.setattr(pmod, "V2_STATUS_PATH", tmp_path / "v2_service_status.json")
    monkeypatch.setattr(closemod, "V2_DB_PATH", db)
    monkeypatch.setattr(closemod, "V2_STATUS_PATH", tmp_path / "v2_service_status.json")
    monkeypatch.setattr(closemod, "eod_state", lambda now=None: {"state": "PENDING", "reason": "grace"})
    res = closemod.run_close(tmp_path, do_shutdown=False)
    a = res.asserts
    assert a["buys_eq_sells_plus_open_plus_unresolved"] == "PASS"
    assert a["no_negative_cash"] == "PASS"
    assert a["no_stale_episode_entered"] == "PASS"
    assert a["no_illegal_eod_flatten"] == "PASS"
    assert a["experimental_external_sends_zero"] in ("PASS", "FAIL")  # env-dependent
    assert res.verdict in ("PASS", "PASS_WITH_FINDINGS")
    assert (tmp_path / "v2_lane.db.eod-copy").exists()   # preserved, not moved
    assert db.exists()                                    # NEVER deleted


# ======================================================================
# B1 -- preflight (read-only, library form)
# ======================================================================

def test_b1_preflight_runs_and_reports_overall():
    from talonx_ops.prospective.preflight import run_preflight
    pre = run_preflight(require_stack_up=False)
    assert pre.overall in {"READY", "READY_WITH_FINDINGS", "NOT_READY"}
    names = {r.check for r in pre.rows}
    for want in ("v1_fingerprint", "v2_fingerprint", "v2_strategy_version", "redis_reachable",
                 "v2_ledger_continuity", "active_profile_is_v2", "real_capital_off",
                 "experimental_external_override_absent", "telegram_logical_owner",
                 "heartbeat_decoupled_from_tick"):
        assert want in names, f"preflight missing check {want}"


def test_b1_preflight_fingerprints_are_expected():
    from talonx_ops.prospective.preflight import run_preflight
    pre = run_preflight()
    by = {r.check: r for r in pre.rows}
    assert by["v1_fingerprint"].status == "READY", by["v1_fingerprint"].detail
    assert by["v2_fingerprint"].status == "READY", by["v2_fingerprint"].detail


# ======================================================================
# A1/A2/A4/A5 -- dashboard
# ======================================================================

@pytest.fixture()
def _dash(monkeypatch, tmp_path):
    db = tmp_path / "v2_lane.db"
    _seed_ledger(db)
    monkeypatch.setenv("TALONX_V2_DB_PATH", str(db))
    monkeypatch.setenv("TALONX_V2_STATUS_PATH", str(tmp_path / "v2_service_status.json"))
    from talonx_ops.dashboard_read import DashboardReadModel
    return DashboardReadModel()


def test_a4_v2_section_separates_health_data_activity(_dash):
    v2 = _dash.v2_active_strategy()
    assert v2["health"] in {"HEALTHY", "DEGRADED", "DOWN", "UNKNOWN"}
    assert v2["data_state"] in {"CURRENT", "STALE", "UNAVAILABLE", "UNKNOWN"}
    assert v2["activity"] in {"NO_OPPORTUNITIES", "ACTIVITY", "POSITION_OPEN", "COMPLETE", "SIGNAL"}
    # no v2 status file -> service DOWN, but the ledger + funnel still render
    assert v2["health"] == "DOWN"
    assert v2["ledger"]["cash"] == BALANCE
    assert "funnel" in v2


def test_a5_v2_section_eod_not_due_yet(_dash, monkeypatch):
    monkeypatch.setattr("talonx_ops.prospective.checkpoint.eod_state",
                        lambda now=None: {"state": "NOT_DUE_YET", "reason": "before close"})
    # also block the reconciliation-row override
    monkeypatch.setattr("talonx_ops.eod_reconciliation.EodReconciliationStore.latest",
                        lambda self: None)
    v2 = _dash.v2_active_strategy()
    assert v2["eod"]["state"] == "NOT_DUE_YET"


def test_a5_v2_section_no_eod_flatten_and_10td_hold(_dash):
    v2 = _dash.v2_active_strategy()
    assert v2["eod_forced_flatten"] is False
    assert v2["eod_auto_close"] == "OFF"
    assert v2["hold_trading_sessions"] == 10


def test_a2_overview_has_first_class_active_v2(_dash):
    ov = _dash.overview()
    assert "active_v2" in ov
    av = ov["active_v2"]
    assert av["strategy"] == "INSIDER_BUY_CLUSTER_V2@1"
    assert av["starting_campaign_cash"] == BALANCE
    assert av["hold_trading_sessions"] == 10
    assert av["eod_forced_flatten"] == "OFF"
    assert "needs_attention" in ov and isinstance(ov["needs_attention"], list)


def test_a2_overview_healthy_zero_is_not_an_attention_item(_dash, monkeypatch):
    # force a "healthy" runtime view -> zero activity must NOT create warnings
    from talonx_ops.dashboard_read import DashboardReadModel
    rt = {"original": "READY", "telegram_receive": "READY"}
    mk = {"state": "HEALTHY"}
    av = {"service_health": "HEALTHY", "source": "insider", "exit_unresolved": 0,
          "interpretation": "NO_MARKET_OPPORTUNITY"}
    al = {}
    out = DashboardReadModel._overview_needs_attention(rt, mk, av, al)
    assert out == []


# ======================================================================
# fingerprints / semantics UNCHANGED by Task 114
# ======================================================================

def test_task114_does_not_change_fingerprints():
    # Task 137: asserts against the live V1_FINGERPRINT_EXPECTED constant
    # (not a hardcoded literal duplicated here) -- that constant is the
    # single source of truth for what the CURRENT baseline is, and is
    # itself updated (with full per-file/commit evidence in its own
    # comment) only when a real, already-authorized change to one of the
    # 5 fingerprinted files is confirmed, distinct from a stale value
    # silently drifting out of sync with a second hardcoded copy here.
    from talonx_backtest.reproducibility import get_strategy_version
    from talonx_ops.prospective import V1_FINGERPRINT_EXPECTED, V2_FINGERPRINT_EXPECTED
    assert get_strategy_version() == V1_FINGERPRINT_EXPECTED
    import importlib
    fp = importlib.import_module("research.scripts.task112_v2_release_fingerprint").v2_release_fingerprint()
    # RI-1: was a hardcoded "11107198c5b81237" literal -- exactly the stale-
    # duplicate anti-pattern this test's own docstring warns about for V1,
    # now fixed the same way: assert against the live constant (updated,
    # with full justification, when config.py gained the campaign_id/
    # execution_mode account-identity fields -- see that constant's own
    # comment in talonx_ops/prospective/__init__.py).
    assert fp["fingerprint"] == V2_FINGERPRINT_EXPECTED
    assert fp["strategy_version"] == "INSIDER_BUY_CLUSTER_V2@1"


def test_task114_v2config_frozen_unchanged():
    c = V2Config()
    c.validate_frozen()
    assert c.max_entry_staleness_sessions == 3
    assert c.per_position_allocation_usd == 10_000.0
    assert c.max_concurrent_positions == 20
    assert c.hold_trading_days == 10
    assert c.stop_loss_enabled is False


# ======================================================================
# Task 132 -- prospective start_stack() gains --enable-broad-discovery
# pass-through to the V2 companion (previously only reachable via a raw,
# unsupervised `python -m talonx_v2.run` invocation, never through the
# real, established launcher). Argv construction tested directly, with
# _spawn() monkeypatched (no real process ever launched) and V2_DB_PATH/
# V2_STATUS_PATH redirected to tmp_path (never the real repo-root ledger).
# ======================================================================

def _patched_proc(monkeypatch, tmp_path):
    from talonx_ops.prospective import proc
    v2_db = tmp_path / "v2_lane.db"
    v2_status = tmp_path / "v2_service_status.json"
    monkeypatch.setattr(proc, "V2_DB_PATH", v2_db)
    monkeypatch.setattr(proc, "V2_STATUS_PATH", v2_status)
    spawned: list[dict] = []
    _next_pid = iter(range(9001, 9999))

    def _fake_spawn(argv, *, log_path, env=None):
        spawned.append({"argv": argv, "log_path": log_path, "env": env})
        return next(_next_pid)
    monkeypatch.setattr(proc, "_spawn", _fake_spawn)
    return proc, spawned, v2_db


def test_start_stack_omits_enable_broad_discovery_by_default(tmp_path, monkeypatch):
    proc, spawned, v2_db = _patched_proc(monkeypatch, tmp_path)
    proc.start_stack(tmp_path / "session", env={}, with_dashboard=False,
                     with_checkpoint_daemon=False)
    v2_call = next(c for c in spawned if "talonx_v2.run" in c["argv"])
    assert "--enable-broad-discovery" not in v2_call["argv"]
    assert "--form4-source" in v2_call["argv"]
    assert v2_call["argv"][v2_call["argv"].index("--form4-source") + 1] == "insider"


def test_start_stack_passes_enable_broad_discovery_through_to_the_v2_companion(tmp_path, monkeypatch):
    proc, spawned, v2_db = _patched_proc(monkeypatch, tmp_path)
    proc.start_stack(tmp_path / "session", env={}, with_dashboard=False,
                     with_checkpoint_daemon=False, enable_broad_discovery=True)
    v2_call = next(c for c in spawned if "talonx_v2.run" in c["argv"])
    assert "--enable-broad-discovery" in v2_call["argv"]
    # never supervisor include_v2 -- still the ONE, separately-spawned companion
    sup_call = next(c for c in spawned if "talonx_ops.supervisor" in c["argv"])
    assert "--include-v2" not in sup_call["argv"]
    assert not any("talonx_v2" in a for a in sup_call["argv"] if a != sup_call["argv"][1])


# ======================================================================
# Task 140 -- found during a live /ping investigation: --enable-broad-
# discovery reached the V2 companion's own argv (tested above) but was
# NEVER wired to Intelligence's OWN broad-discovery mode
# (TALONX_INTEL_ENABLE_BROAD_DISCOVERY, the only control surface
# talonx_ingest/intelligence/service/broad_discovery.py reads -- no CLI
# flag exists on `poll` for it). The only way it was ever active in this
# deployment was an ad-hoc interactive shell export before the FIRST
# `prospective start` of a campaign, invisible to and not restored by any
# subsequent restart -- including this task's own host-reboot recovery,
# which is exactly how this was caught (a live /ping showed Intelligence
# collecting 39 symbols, watchlist-only, instead of the 569 a genuinely
# broad-collecting deployment resolves). Fixed by setting the env var
# supervisor's own spawn merges into every child it launches (Original/
# Experimental/Intelligence/Dashboard) whenever --enable-broad-discovery
# is requested -- one flag now consistently governs both V2's execution
# scope and Intelligence's actual collection scope.
# ======================================================================

def test_start_stack_does_not_set_intel_broad_discovery_env_by_default(tmp_path, monkeypatch):
    from talonx_ops.prospective import proc
    monkeypatch.setattr(proc, "_live_prior_stack", lambda: [])
    proc, spawned, v2_db = _patched_proc(monkeypatch, tmp_path)
    proc.start_stack(tmp_path / "session", env={}, with_dashboard=False,
                     with_checkpoint_daemon=False)
    sup_call = next(c for c in spawned if "talonx_ops.supervisor" in c["argv"])
    assert "TALONX_INTEL_ENABLE_BROAD_DISCOVERY" not in (sup_call["env"] or {})


def test_start_stack_enable_broad_discovery_also_sets_the_intelligence_env_var(tmp_path, monkeypatch):
    from talonx_ops.prospective import proc
    monkeypatch.setattr(proc, "_live_prior_stack", lambda: [])
    proc, spawned, v2_db = _patched_proc(monkeypatch, tmp_path)
    proc.start_stack(tmp_path / "session", env={}, with_dashboard=False,
                     with_checkpoint_daemon=False, enable_broad_discovery=True)
    sup_call = next(c for c in spawned if "talonx_ops.supervisor" in c["argv"])
    assert sup_call["env"]["TALONX_INTEL_ENABLE_BROAD_DISCOVERY"] == "1"
    # every child supervisor itself spawns inherits this same merged env
    # (proc._spawn's {**os.environ, **env} pattern -- verified once here at
    # the level THIS launcher actually controls, not re-testing supervisor's
    # own internal spawn mechanics, which belong to test_task78i_supervisor.py)


def test_start_stack_deliver_telegram_also_enables_intelligence_delivery(tmp_path, monkeypatch):
    """Sibling gap to the broad-discovery one above, found in the SAME live
    investigation: --deliver --transport telegram was wired only into the
    V2 companion's own argv, never into Intelligence's own delivery-
    enablement env vars (no CLI flag exists for it on `poll` by design --
    see test_task117_supervised_intelligence.py)."""
    from talonx_ops.prospective import proc
    monkeypatch.setattr(proc, "_live_prior_stack", lambda: [])
    proc, spawned, v2_db = _patched_proc(monkeypatch, tmp_path)
    proc.start_stack(tmp_path / "session", env={}, with_dashboard=False,
                     with_checkpoint_daemon=False, deliver=True, transport="telegram")
    sup_call = next(c for c in spawned if "talonx_ops.supervisor" in c["argv"])
    assert sup_call["env"]["TALONX_INTEL_DELIVER_CARDS"] == "1"
    assert sup_call["env"]["TALONX_INTEL_DRY_RUN_DELIVERY"] == "0"


def test_start_stack_dryrun_transport_does_not_enable_intelligence_delivery(tmp_path, monkeypatch):
    from talonx_ops.prospective import proc
    monkeypatch.setattr(proc, "_live_prior_stack", lambda: [])
    proc, spawned, v2_db = _patched_proc(monkeypatch, tmp_path)
    proc.start_stack(tmp_path / "session", env={}, with_dashboard=False,
                     with_checkpoint_daemon=False, deliver=True, transport="dryrun")
    sup_call = next(c for c in spawned if "talonx_ops.supervisor" in c["argv"])
    assert "TALONX_INTEL_DELIVER_CARDS" not in (sup_call["env"] or {})
    assert "TALONX_INTEL_DRY_RUN_DELIVERY" not in (sup_call["env"] or {})


def test_start_stack_deliver_telegram_never_overrides_an_explicit_shell_value(tmp_path, monkeypatch):
    from talonx_ops.prospective import proc
    monkeypatch.setattr(proc, "_live_prior_stack", lambda: [])
    proc, spawned, v2_db = _patched_proc(monkeypatch, tmp_path)
    monkeypatch.setenv("TALONX_INTEL_DELIVER_CARDS", "0")
    proc.start_stack(tmp_path / "session", env={}, with_dashboard=False,
                     with_checkpoint_daemon=False, deliver=True, transport="telegram")
    sup_call = next(c for c in spawned if "talonx_ops.supervisor" in c["argv"])
    assert "TALONX_INTEL_DELIVER_CARDS" not in (sup_call["env"] or {})


def test_start_stack_full_authorized_configuration_together(tmp_path, monkeypatch):
    """Task 140 (live /ping follow-up): one integrated scenario proving the
    launcher can deliver every authorized configuration dimension
    CONSISTENTLY in a single start_stack() call -- broad collection
    (Intelligence), expanded execution scope (V2), GATED admission (an
    operator-supplied env override -- NOT flipped by --enable-broad-
    discovery/--deliver, since PERMISSIVE remains this deployment's own
    documented, unchanged default; see docs/research/TASK131_
    RETROSPECTIVE.md and docs/research/evidence/task139/
    ping_discrepancy_investigation.md), Intelligence delivery enabled, and
    routine digest left OFF (never implied by --deliver -- a separate,
    still-default-off opt-in)."""
    from talonx_ops.prospective import proc
    monkeypatch.setattr(proc, "_live_prior_stack", lambda: [])
    proc, spawned, v2_db = _patched_proc(monkeypatch, tmp_path)

    proc.start_stack(
        tmp_path / "session", env={"TALONX_V2_DURABLE_STORE_ENABLED": "1"},
        with_dashboard=False, with_checkpoint_daemon=False,
        execution_scope="resolved-active-watchlist", deliver=True,
        transport="telegram", enable_broad_discovery=True,
    )
    sup_call = next(c for c in spawned if "talonx_ops.supervisor" in c["argv"])
    v2_call = next(c for c in spawned if "talonx_v2.run" in c["argv"])
    env = sup_call["env"] or {}

    # broad collection (Intelligence) + expanded execution (V2)
    assert env.get("TALONX_INTEL_ENABLE_BROAD_DISCOVERY") == "1"
    assert "--enable-broad-discovery" in v2_call["argv"]
    assert "--execution-scope" in v2_call["argv"]
    assert v2_call["argv"][v2_call["argv"].index("--execution-scope") + 1] == "resolved-active-watchlist"
    # GATED admission -- the operator-supplied override, carried through
    # UNCHANGED (never overwritten by any of the other flags above)
    assert env.get("TALONX_V2_DURABLE_STORE_ENABLED") == "1"
    # Intelligence delivery enabled
    assert env.get("TALONX_INTEL_DELIVER_CARDS") == "1"
    assert env.get("TALONX_INTEL_DRY_RUN_DELIVERY") == "0"
    # routine digest stays OFF -- never implied by --deliver
    assert "TALONX_INTEL_DELIVER_DIGEST_ENABLED" not in env
    # the SAME merged env reaches the V2 companion too (proc._spawn's
    # {**os.environ, **env} pattern; env is one shared dict object across
    # every spawn in _start_stack_locked)
    assert sup_call["env"] is v2_call["env"]


def test_start_stack_enable_broad_discovery_never_overrides_an_explicit_shell_value(tmp_path, monkeypatch):
    """A real, explicitly-set env var (shell export or an already-resolved
    `env` dict entry) always wins -- --enable-broad-discovery only ADDS
    the key when genuinely absent, mirroring the load_dotenv(override=
    False) precedent Task 132 already established for .env resolution."""
    from talonx_ops.prospective import proc
    monkeypatch.setattr(proc, "_live_prior_stack", lambda: [])
    proc, spawned, v2_db = _patched_proc(monkeypatch, tmp_path)
    monkeypatch.setenv("TALONX_INTEL_ENABLE_BROAD_DISCOVERY", "0")
    proc.start_stack(tmp_path / "session", env={}, with_dashboard=False,
                     with_checkpoint_daemon=False, enable_broad_discovery=True)
    sup_call = next(c for c in spawned if "talonx_ops.supervisor" in c["argv"])
    assert "TALONX_INTEL_ENABLE_BROAD_DISCOVERY" not in (sup_call["env"] or {})
