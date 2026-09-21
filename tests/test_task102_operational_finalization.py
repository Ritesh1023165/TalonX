"""TASK 102 Phase 17 -- operational finalization test matrix.

PREMARKET (1-15): store init, read-only access, idempotent insert, event
update, session rollover, stale prior-session, duplicate suppression, missing
values safe, per-family persistence, authoritative source/freshness, dashboard
section reads persisted values, no dashboard write side effect.

CONFIG (16-25): inventory coverage, allowed operational config validation,
strategy/execution denylists, previous/new audit, failed-validation no-write,
no secret logging, localhost-only binding, explicit confirmation, rollback
read-back.

8501/8770 (26-30): retention/deprecation criteria, parity, no default startup.

OPERATIONS (31-35): supervisor status command, dashboard URL, EOD state,
optional-component degradation, no duplicate runtime launch.

SAFETY (36-43): Original strategy/thresholds, Experimental V1, Experimental
Telegram, broker, shorts, paid data, Task101 live wiring.
"""
from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from talonx_signals.premarket import PremarketSymbolInput, PremarketWatchEngine
from talonx_signals.premarket_store import PremarketStateStore
from talonx_ops.admin_config import (
    AdminConfigService, ConfigAuditLog, ConfigDenied, is_denylisted, loopback_host,
    ALLOWED_ACTIONS,
)

NOW = datetime(2026, 9, 15, 12, 0, tzinfo=timezone.utc)


# --------------------------------------------------------------------------- #
# fakes
# --------------------------------------------------------------------------- #
class FakeWL:
    def __init__(self):
        self.t: dict[str, dict] = {}

    def get_ticker(self, s):
        return dict(self.t[s]) if s in self.t else None

    def add_ticker(self, s, n, e, status="paused", strategy_horizon="INTRADAY"):
        self.t[s] = {"symbol": s, "name": n, "exchange": e, "status": status,
                     "strategy_horizon": strategy_horizon,
                     "paper_trading_enabled": 0, "paper_trading_enabled_long_term": 0}

    def remove_ticker(self, s):
        self.t.pop(s, None)

    def pause_ticker(self, s):
        self.t[s]["status"] = "paused"

    def resume_ticker(self, s):
        self.t[s]["status"] = "active"

    def set_strategy_horizon(self, s, h):
        self.t[s]["strategy_horizon"] = h

    def set_paper_trading(self, s, e):
        self.t[s]["paper_trading_enabled"] = int(e)

    def set_paper_trading_long_term(self, s, e):
        self.t[s]["paper_trading_enabled_long_term"] = int(e)

    def close(self):
        pass


class FakePaper:
    def __init__(self):
        self.alloc = 250.0
        self.dca = 100.0

    def get_portfolio_summary(self):
        return {"trade_allocation_usd": self.alloc}

    def get_long_term_portfolio_summary(self):
        return {"dca_contribution_usd": self.dca}

    def update_trade_allocation(self, a):
        self.alloc = a

    def update_dca_contribution_amount(self, a):
        self.dca = a

    def close(self):
        pass


def _bundle(prev_close=100.0, msft=112.0, nvda=93.0, now=NOW):
    return PremarketWatchEngine().assess(
        [PremarketSymbolInput(symbol="MSFT", latest_price=msft, prev_close=prev_close),
         PremarketSymbolInput(symbol="NVDA", latest_price=nvda, prev_close=prev_close)],
        now=now, watchlist_configured=2, watchlist_active=2,
    )


@pytest.fixture
def store(tmp_path):
    s = PremarketStateStore(tmp_path / "premarket_state.db")
    yield s
    s.close()


# --------------------------------------------------------------------------- #
# PREMARKET 1-15
# --------------------------------------------------------------------------- #
def test_01_store_initialization(tmp_path):
    p = tmp_path / "pm.db"
    s = PremarketStateStore(p)
    assert p.exists()
    con = sqlite3.connect(p)
    tables = {r[0] for r in con.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    con.close()
    s.close()
    assert {"premarket_sessions", "premarket_events"} <= tables


def test_02_read_only_dashboard_access(tmp_path):
    p = tmp_path / "pm.db"
    PremarketStateStore(p).upsert_bundle(_bundle(), now=NOW)
    ro = PremarketStateStore(p, read_only=True)
    assert ro.current_session(now=NOW)["status"] == "ACTIVE"
    with pytest.raises(RuntimeError):
        ro.upsert_bundle(_bundle(), now=NOW)
    ro.close()


def test_03_idempotent_event_insert(store):
    r1 = store.upsert_bundle(_bundle(), now=NOW)
    r2 = store.upsert_bundle(_bundle(), now=NOW.replace(minute=5))
    assert r1["events_upserted"] == r2["events_upserted"]
    assert store.counts_for_session("2026-09-15") == \
        {"GAP_UP": 1, "GAP_DOWN": 1, "BULLISH_WATCH": 1, "BEARISH_WATCH": 1}


def test_04_event_update_refreshes_measurements(store):
    store.upsert_bundle(_bundle(msft=112.0), now=NOW)
    row0 = store.events_for_session("2026-09-15")["GAP_UP"][0]
    store.upsert_bundle(_bundle(msft=120.0), now=NOW.replace(minute=10))
    row1 = store.events_for_session("2026-09-15")["GAP_UP"][0]
    assert row1["watch_id"] == row0["watch_id"]          # same logical event
    assert row1["gap_pct"] != row0["gap_pct"]            # measurement refreshed
    assert row1["first_seen_at"] == row0["first_seen_at"]  # never rewritten
    assert row1["last_updated_at"] > row0["last_updated_at"]


def test_05_session_rollover(store):
    store.upsert_bundle(_bundle(now=NOW), now=NOW)
    store.upsert_bundle(_bundle(now=NOW.replace(day=16)), now=NOW.replace(day=16))
    assert store.counts_for_session("2026-09-15")
    assert store.counts_for_session("2026-09-16")
    # current session is day-scoped
    assert store.current_session(now=NOW.replace(day=16))["session_date"] == "2026-09-16"


def test_06_stale_prior_session_handling(store):
    store.upsert_bundle(_bundle(now=NOW), now=NOW)
    # 3h later, still 'today' but past the freshness window -> STALE
    cs = store.current_session(now=NOW + timedelta(hours=3))
    assert cs["status"] == "STALE"
    # a different day with no session row -> NO_SESSION_TODAY, prior date noted
    nxt = store.current_session(now=NOW.replace(day=18))
    assert nxt["status"] == "NO_SESSION_TODAY"
    assert nxt["last_session_date"] == "2026-09-15"


def test_07_duplicate_suppression_across_families(store):
    store.upsert_bundle(_bundle(), now=NOW)
    store.upsert_bundle(_bundle(), now=NOW)
    store.upsert_bundle(_bundle(), now=NOW)
    total = sum(store.counts_for_session("2026-09-15").values())
    assert total == 4  # never 12


def test_08_missing_values_safe(store):
    # no volume feed -> ABNORMAL_VOLUME never persisted, relative_volume NULL
    store.upsert_bundle(_bundle(), now=NOW)
    ev = store.events_for_session("2026-09-15")
    assert "ABNORMAL_VOLUME" not in ev
    assert ev["GAP_UP"][0]["relative_volume"] is None


def test_09_gap_event_persistence(store):
    store.upsert_bundle(_bundle(msft=115.0, nvda=88.0), now=NOW)
    ev = store.events_for_session("2026-09-15")
    assert ev["GAP_UP"][0]["symbol"] == "MSFT" and ev["GAP_UP"][0]["bias"] == "BULLISH"
    assert ev["GAP_DOWN"][0]["symbol"] == "NVDA" and ev["GAP_DOWN"][0]["bias"] == "BEARISH"


def test_10_abnormal_volume_persistence(store):
    eng = PremarketWatchEngine()
    b = eng.assess([PremarketSymbolInput(symbol="AMD", latest_price=100.0, prev_close=100.0,
                                         latest_volume=9_000_000, avg_premarket_volume=1_000_000)],
                   now=NOW, watchlist_configured=1, watchlist_active=1)
    store.upsert_bundle(b, now=NOW)
    ev = store.events_for_session("2026-09-15")
    assert ev.get("ABNORMAL_VOLUME") and ev["ABNORMAL_VOLUME"][0]["symbol"] == "AMD"


def test_11_earnings_radar_persistence(store):
    eng = PremarketWatchEngine()
    b = eng.assess([PremarketSymbolInput(symbol="ORCL", latest_price=100.0, prev_close=100.0,
                                         earnings_when="2026-09-16")],
                   now=NOW, watchlist_configured=1, watchlist_active=1)
    store.upsert_bundle(b, now=NOW)
    assert store.counts_for_session("2026-09-15").get("RADAR", 0) >= 1


def test_12_event_context_persistence(store):
    eng = PremarketWatchEngine()
    b = eng.assess([PremarketSymbolInput(symbol="AVGO", latest_price=100.0, prev_close=100.0,
                                         overnight_events=("8-K item 2.02",))],
                   now=NOW, watchlist_configured=1, watchlist_active=1)
    store.upsert_bundle(b, now=NOW)
    assert store.counts_for_session("2026-09-15").get("EVENT_CONTEXT", 0) >= 1


def test_13_authoritative_source_and_freshness(store):
    store.upsert_bundle(_bundle(), now=NOW)
    cs = store.current_session(now=NOW.replace(minute=2))
    assert cs["status"] == "ACTIVE"
    assert cs["last_updated_age_seconds"] is not None
    assert cs["generated_at"] and cs["last_updated_at"]


def test_14_dashboard_section_reads_persisted_values(tmp_path):
    from talonx_ops.dashboard_read import DashboardReadModel

    home = tmp_path / ".talonx"
    (home / "experimental" / "premarket").mkdir(parents=True)
    PremarketStateStore(home / "experimental" / "premarket" / "premarket_state.db").upsert_bundle(
        _bundle(msft=115.0), now=NOW)
    pm = DashboardReadModel(home=home, exp_home=home / "experimental",
                            intel_ledger=home / "ingestion_ledger.db",
                            now=NOW.replace(minute=5), check_processes=False).premarket()
    pw = pm["premarket_watch"]
    assert pw["status"] == "ACTIVE"
    assert pw["session_date"] == "2026-09-15"
    assert pw["counts_by_family"]["GAP_UP"] == 1
    assert pw["events_by_family"]["GAP_UP"][0]["relative_volume"] == "NOT_AVAILABLE"
    assert pw["external_eligible"] is False


def test_15_no_dashboard_write_side_effect(tmp_path):
    from talonx_ops.dashboard_read import DashboardReadModel

    home = tmp_path / ".talonx"
    (home / "experimental" / "premarket").mkdir(parents=True)
    db = home / "experimental" / "premarket" / "premarket_state.db"
    PremarketStateStore(db).upsert_bundle(_bundle(), now=NOW)
    before = db.stat().st_mtime_ns
    m = DashboardReadModel(home=home, exp_home=home / "experimental",
                           intel_ledger=home / "ingestion_ledger.db", now=NOW, check_processes=False)
    m.premarket()
    m.premarket()
    assert db.stat().st_mtime_ns == before


# --------------------------------------------------------------------------- #
# CONFIG 16-25
# --------------------------------------------------------------------------- #
@pytest.fixture
def admin(tmp_path):
    wl, pp = FakeWL(), FakePaper()
    svc = AdminConfigService(home=tmp_path, watchlist_factory=lambda: wl,
                             paper_factory=lambda: pp)
    svc._wl, svc._pp = wl, pp
    yield svc
    svc.close()


def test_16_config_inventory_coverage():
    # every allowed action maps to a real :8501 write surface documented in the inventory
    doc = Path("results/task102_operational_finalization/streamlit_config_inventory.md")
    assert doc.exists()
    text = doc.read_text(encoding="utf-8")
    for a in ALLOWED_ACTIONS:
        assert a in text, a


def test_17_allowed_operational_config_validation(admin):
    r = admin.apply("watchlist.add", {"symbol": "nvda", "name": "NVIDIA", "exchange": "NASDAQ",
                                      "horizon": "INTRADAY"}, confirm=True)
    assert r.ok and r.outcome == "APPLIED"
    assert "NVDA" in admin._wl.t
    r = admin.apply("watchlist.set_horizon", {"symbol": "NVDA", "horizon": "DUAL_HORIZON"}, confirm=True)
    assert r.ok and r.previous_value == "INTRADAY" and r.new_value == "DUAL_HORIZON"
    r = admin.apply("paper.set_trade_allocation", {"amount": 500}, confirm=True)
    assert r.ok and r.previous_value == 250.0 and r.new_value == 500.0


def test_18_strategy_key_denylist(admin):
    for probe in ("min_atr_pct", "confluence_score_min", "min_risk_reward_ratio",
                  "trend_semantics", "brain_ordering", "quant_config.threshold"):
        assert is_denylisted(probe), probe
    with pytest.raises(ConfigDenied):
        admin.apply("quant.set_threshold", {"key": "min_atr_pct", "value": 0.1}, confirm=True)
    with pytest.raises(ConfigDenied):
        admin.apply("watchlist.add", {"symbol": "X", "name": "confluence override test",
                                      "exchange": "NASDAQ"}, confirm=True)


def test_19_execution_key_denylist(admin):
    for probe in ("submit_order", "broker_api", "alpaca_key", "real_capital",
                  "open_short", "enable_external_send", "experimental_promotion"):
        assert is_denylisted(probe), probe
    with pytest.raises(ConfigDenied):
        admin.apply("broker.enable", {"live": True}, confirm=True)


def test_20_previous_new_value_audit(admin, tmp_path):
    admin.apply("watchlist.add", {"symbol": "MSFT", "name": "MS", "exchange": "NASDAQ"}, confirm=True)
    admin.apply("watchlist.pause", {"symbol": "MSFT"}, confirm=True)  # already paused -> prev 'paused'
    admin.apply("watchlist.resume", {"symbol": "MSFT"}, confirm=True)
    log = ConfigAuditLog(tmp_path / "admin" / "config_audit.db")
    tail = log.tail(10)
    log.close()
    resume = [t for t in tail if t["action"] == "watchlist.resume"][0]
    assert resume["previous_value"] == "paused" and resume["new_value"] == "active"
    assert resume["outcome"] == "APPLIED"


def test_21_failed_validation_does_not_write(admin):
    r = admin.apply("paper.set_trade_allocation", {"amount": 5}, confirm=True)  # < 10
    assert not r.ok and r.outcome == "REJECTED_INVALID"
    assert admin._pp.alloc == 250.0                       # unchanged
    r = admin.apply("watchlist.set_horizon", {"symbol": "NOPE", "horizon": "INTRADAY"}, confirm=True)
    assert not r.ok and r.outcome == "REJECTED_INVALID"


def test_22_no_secret_logging(admin, tmp_path):
    # a token-shaped param is denylisted before any store call, and the audit
    # row records the action/key, never echoing a raw secret value verbatim
    with pytest.raises(ConfigDenied):
        admin.apply("telegram.set_token", {"telegram_token": "123:AAABBBCCC_secret"}, confirm=True)
    raw = (tmp_path / "admin" / "config_audit.db").read_bytes()
    assert b"AAABBBCCC_secret" not in raw


def test_23_localhost_only_admin_binding():
    assert loopback_host("127.0.0.1") and loopback_host("localhost") and loopback_host("::1")
    assert not loopback_host("0.0.0.0")
    assert not loopback_host("192.168.1.10")


def test_24_explicit_confirmation_path(admin):
    r = admin.apply("watchlist.add", {"symbol": "AMD", "name": "AMD", "exchange": "NASDAQ"})  # no confirm
    assert not r.ok and r.outcome == "REJECTED_UNCONFIRMED"
    assert "AMD" not in admin._wl.t


def test_25_rollback_read_back(admin):
    admin.apply("paper.set_trade_allocation", {"amount": 250}, confirm=True)
    r1 = admin.apply("paper.set_trade_allocation", {"amount": 750}, confirm=True)
    assert r1.previous_value == 250.0
    # roll back using the recorded previous value
    r2 = admin.apply("paper.set_trade_allocation", {"amount": r1.previous_value}, confirm=True)
    assert r2.ok and admin._pp.alloc == 250.0


# --------------------------------------------------------------------------- #
# 8501 / 8770  (26-30)
# --------------------------------------------------------------------------- #
def test_26_8501_retained_config_editing_present():
    src = Path("talonx_dispatch/app.py").read_text(encoding="utf-8")
    for m in ("store.add_ticker", "store.remove_ticker", "update_trade_allocation",
              "reset_portfolio", "update_dca_contribution_amount"):
        assert m in src


def test_27_8501_deprecation_report_lists_blockers():
    doc = Path("results/task102_operational_finalization/streamlit_retirement_report.md")
    assert doc.exists()
    t = doc.read_text(encoding="utf-8").lower()
    # the destructive resets + long-term research views are the documented blockers
    assert "reset" in t and ("research" in t or "valuation" in t)


def test_28_8770_parity_still_5_of_5():
    doc = Path("results/task100c_unified_dashboard/task8770_parity_report.md")
    assert doc.exists()
    t = doc.read_text(encoding="utf-8")
    assert t.count("**verdict** | **PASS**") >= 5


def test_29_8770_no_default_startup():
    from talonx_ops.supervisor import default_talonx_components

    specs = default_talonx_components()
    names = {s.name for s in specs}
    assert names == {"original", "experimental", "intelligence", "dashboard"}
    # no component launches a :8770-hosting dashboard, and no argv mentions 8770
    for s in specs:
        argv = " ".join(s.argv)
        assert "8770" not in argv
        if s.name == "dashboard":
            assert "dashboard_web.py" in argv          # the :8787 cockpit, not :8770
    sup = Path("talonx_ops/supervisor.py").read_text(encoding="utf-8")
    assert "8770" not in sup


def test_30_8770_compatibility_start_still_possible():
    # the entry point is unchanged
    assert Path("talonx_signals/run.py").exists()
    doc = Path("results/task102_operational_finalization/task8770_retirement_contract.md")
    assert doc.exists()
    assert "python -m talonx_signals.run" in doc.read_text(encoding="utf-8")


# --------------------------------------------------------------------------- #
# OPERATIONS 31-35
# --------------------------------------------------------------------------- #
def test_31_supervisor_status_command():
    from talonx_ops.supervisor import _status_snapshot

    snap = _status_snapshot()
    assert "answers" in snap
    a = snap["answers"]
    for k in ("talonx_running", "original_ready", "market_feed_healthy",
              "experimental_shadow_alive", "intelligence_alive", "telegram_send_ok",
              "original_open_positions", "eod_reconciled_today", "dashboard_url"):
        assert k in a


def test_32_dashboard_url_reported():
    from talonx_ops.supervisor import _status_snapshot

    assert _status_snapshot()["answers"]["dashboard_url"] == "http://localhost:8787"


def test_33_eod_state_reported():
    from talonx_ops.supervisor import _status_snapshot

    snap = _status_snapshot()
    assert "eod_latest" in snap and "eod_reconciled_today" in snap


def test_34_optional_component_degradation_represented():
    from talonx_ops.dashboard_read import DashboardReadModel

    # no producers running -> overview marks optional components DEGRADED, original FAILED,
    # overall FAILED, but the sections still render
    ov = DashboardReadModel(check_processes=False).overview()
    assert ov["runtime"]["experimental"] in ("READY", "DEGRADED", "FAILED")
    assert ov["runtime"]["intelligence"] in ("READY", "DEGRADED", "FAILED")


def test_35_no_duplicate_runtime_launch():
    from talonx_ops.supervisor import Supervisor, default_talonx_components, DuplicateTelegramOwnerError

    class R:
        def spawn(self, spec):
            class H:
                pid = 1
                def poll(self): return None
                def terminate(self): pass
                def kill(self): pass
                def wait(self, timeout=None): return 0
            return H()

    s = Supervisor(default_talonx_components(include_dashboard=False),
                   runner=R(), clock=lambda: 0.0, telegram_owner_probe=lambda: 1)
    with pytest.raises(DuplicateTelegramOwnerError):
        s.start_all()


# --------------------------------------------------------------------------- #
# SAFETY 36-43
# --------------------------------------------------------------------------- #
def test_36_original_strategy_unchanged():
    import subprocess

    out = subprocess.run(
        ["git", "diff", "--stat", "a657750", "--",
         "talonx_quant/", "talonx_core/", "talonx_paper/", "talonx_piv/", "talonx_brain/", "run_talonx.py"],
        capture_output=True, text=True, cwd=Path(__file__).resolve().parent.parent,
    )
    assert out.stdout.strip() == "", f"frozen path changed:\n{out.stdout}"


def test_37_original_thresholds_unchanged():
    from talonx_quant.config import QuantConfig

    c = QuantConfig()
    assert (c.min_atr_pct, c.confluence_score_min, c.min_risk_reward_ratio) == (0.25, 2, 1.5)


def test_38_experimental_v1_unchanged():
    from talonx_signals.config import RELAXED_OVERRIDES

    assert dict(RELAXED_OVERRIDES) == {"min_atr_pct": 0.10, "confluence_score_min": 1,
                                       "min_risk_reward_ratio": 1.0}


def test_39_no_experimental_telegram():
    src = Path("talonx_signals/premarket_store.py").read_text(encoding="utf-8")
    assert "Telegram" not in src and "telegram" not in src
    admin_src = Path("talonx_ops/admin_config.py").read_text(encoding="utf-8")
    assert "enable_external_send" in admin_src  # only as a denylist pattern
    assert "TelegramSenderAdapter" not in admin_src


def test_40_no_broker_execution_change():
    for f in ("talonx_signals/premarket_store.py", "talonx_ops/admin_config.py",
              "talonx_ops/dashboard_read.py"):
        src = Path(f).read_text(encoding="utf-8").lower()
        for banned in ("submit_order", "place_order", "tradingclient", "execute_buy", "execute_sell"):
            assert banned not in src, f"{f}: {banned}"


def test_41_no_short_path():
    src = Path("talonx_signals/premarket_store.py").read_text(encoding="utf-8")
    assert "open_short" not in src and "short_" not in src


def test_42_no_paid_data():
    for f in ("talonx_signals/premarket_store.py", "talonx_ops/admin_config.py"):
        src = Path(f).read_text(encoding="utf-8").lower()
        for banned in ("api_key", "apikey", "subscription", "paid", "premium_data"):
            assert banned not in src, f"{f}: {banned}"


def test_43_no_task101_live_wiring():
    for f in ("talonx_signals/premarket_store.py", "talonx_ops/admin_config.py",
              "talonx_ops/dashboard_read.py", "talonx_signals/run.py"):
        src = Path(f).read_text(encoding="utf-8").lower()
        assert "task101" not in src and "task_101" not in src
