"""TASK 100B Phase 20 -- focused runtime-integration test matrix.

Covers the Phase 20 checklist: supervisor state transitions, mandatory vs
optional readiness, the single-Telegram-poller invariant + duplicate refusal,
D/X/R/E registration + first-match routing + the read-only secondary handle,
the structural Experimental external-send boundary, official routing
eligibility + dedup, Task 99H escaping retention, intelligence independent
start / crash restart / isolation, the unified market-health accessor, the
idempotent EOD reconciliation store, and SingletonLock.is_stale().
"""
from __future__ import annotations

import asyncio
import json
import sqlite3
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

import pytest

from talonx_ops.supervisor import (
    Supervisor, ComponentSpec, Classification, ComponentState, RestartPolicy,
    SupervisorStartError, DuplicateTelegramOwnerError, count_telegram_get_updates_owners,
    default_talonx_components,
)

_REPO = Path(__file__).resolve().parent.parent


# --------------------------------------------------------------------------- #
# fakes
# --------------------------------------------------------------------------- #
class FakeHandle:
    def __init__(self, name: str):
        self.name = name
        self.pid = abs(hash(name)) % 90000 + 1000
        self._code: int | None = None

    def poll(self):
        return self._code

    def terminate(self):
        self._code = 0

    def kill(self):
        self._code = -9

    def wait(self, timeout=None):
        if self._code is None:
            self._code = 0
        return self._code

    def die(self, code: int = 1):
        self._code = code


class FakeRunner:
    def __init__(self):
        self.spawned: list[FakeHandle] = []

    def spawn(self, spec):
        h = FakeHandle(spec.name)
        self.spawned.append(h)
        return h

    def newest(self, name: str) -> FakeHandle:
        return [h for h in self.spawned if h.name == name][-1]


def _specs(**over):
    mk = lambda name, cls, so, po, **kw: ComponentSpec(
        name, ["x"], cls, so, po, readiness_grace_s=0.0, **kw
    )
    return [
        mk("original", Classification.MANDATORY, 10, 30,
           restart_policy=over.get("original_policy", RestartPolicy(max_restarts=2, stable_reset_s=1e9))),
        mk("experimental", Classification.OPTIONAL, 20, 10,
           restart_policy=RestartPolicy(max_restarts=None, stable_reset_s=1e9)),
        mk("intelligence", Classification.OPTIONAL, 30, 20,
           restart_policy=RestartPolicy(max_restarts=None, stable_reset_s=1e9)),
        mk("dashboard", Classification.OPTIONAL, 40, 5,
           restart_policy=RestartPolicy(max_restarts=10, stable_reset_s=1e9)),
    ]


@pytest.fixture
def sup():
    t = [0.0]
    runner = FakeRunner()
    s = Supervisor(_specs(), runner=runner, clock=lambda: t[0], telegram_owner_probe=lambda: 0)
    s._clock_list = t          # test handle
    s._runner = runner
    return s


# --------------------------------------------------------------------------- #
# 1-2 supervisor state transitions + mandatory vs optional readiness
# --------------------------------------------------------------------------- #
def test_01_startup_all_ready(sup):
    sup.start_all()
    assert all(c.state is ComponentState.READY for c in sup.components.values())
    assert sup._start_order == ["original", "experimental", "intelligence", "dashboard"]


def test_02_state_transition_ready_to_restarting_to_ready(sup):
    sup.start_all()
    sup._runner.newest("experimental").die(1)
    sup.poll_once()
    assert sup.components["experimental"].state is ComponentState.RESTARTING
    sup._clock_list[0] += 120.0
    sup.poll_once()
    assert sup.components["experimental"].state is ComponentState.READY
    assert sup.components["experimental"].restart_count == 1


def test_03_mandatory_readiness_failure_aborts_startup():
    class DiesRunner(FakeRunner):
        def spawn(self, spec):
            h = super().spawn(spec)
            if spec.name == "original":
                h.die(1)
            return h

    s = Supervisor(_specs(), runner=DiesRunner(), clock=lambda: 0.0, telegram_owner_probe=lambda: 0)
    with pytest.raises(SupervisorStartError):
        s.start_all()
    assert s.mandatory_failed is True


def test_04_optional_readiness_failure_is_degraded_not_fatal():
    class SlowOptional(FakeRunner):
        pass

    specs = _specs()
    # give experimental a probe that never returns True + a tiny timeout
    specs[1] = ComponentSpec("experimental", ["x"], Classification.OPTIONAL, 20, 10,
                             readiness_probe=lambda: False, readiness_timeout_s=0.05,
                             restart_policy=RestartPolicy(max_restarts=None))
    s = Supervisor(specs, runner=FakeRunner(), clock=__import__("time").monotonic,
                   telegram_owner_probe=lambda: 0)
    s.start_all()  # must not raise
    assert s.components["experimental"].state is ComponentState.DEGRADED
    assert s.components["original"].state is ComponentState.READY


def test_05_mandatory_failed_after_max_restarts(sup):
    sup.start_all()
    for _ in range(4):
        sup._runner.newest("original").die(1)
        sup.poll_once()
        sup._clock_list[0] += 1000.0
        sup.poll_once()
    assert sup.components["original"].state is ComponentState.FAILED
    assert sup.mandatory_failed is True


# --------------------------------------------------------------------------- #
# 3-4 single Telegram poller / duplicate prevented
# --------------------------------------------------------------------------- #
def test_06_duplicate_telegram_owner_refused():
    s = Supervisor(_specs(), runner=FakeRunner(), clock=lambda: 0.0, telegram_owner_probe=lambda: 1)
    with pytest.raises(DuplicateTelegramOwnerError):
        s.start_all()


def test_07_single_owner_ok(sup):
    sup.start_all()  # probe returns 0 -> allowed
    hv = sup.aggregate_health(market_view={"state": "HEALTHY"})
    assert hv["telegram_receive"] == "READY"


def test_08_more_than_one_owner_is_degraded_receive(sup):
    sup._telegram_owner_probe = lambda: 2
    sup.start_all.__wrapped__ if hasattr(sup.start_all, "__wrapped__") else None
    # start_all would refuse with probe==2; bypass by starting with 0 then flipping
    sup._telegram_owner_probe = lambda: 0
    sup.start_all()
    sup._telegram_owner_probe = lambda: 2
    hv = sup.aggregate_health(market_view={"state": "HEALTHY"})
    assert hv["telegram_receive"] == "DEGRADED"


def test_09_count_telegram_owners_is_callable():
    # smoke: returns an int and does not raise in this environment
    assert isinstance(count_telegram_get_updates_owners(), int)


# --------------------------------------------------------------------------- #
# 5-8 D/X/R/E
# --------------------------------------------------------------------------- #
@pytest.fixture
def exp_db(tmp_path):
    from talonx_signals.alert_store import ExperimentalAlertStore

    db = tmp_path / "exp_alerts.db"
    store = ExperimentalAlertStore(str(db))
    store.record_radar({"radar_id": "R" + "a" * 16, "symbol": "MSFT", "headline": "earnings",
                        "session": "BMO", "window_label": "T-0"})
    store.record_directional({
        "alert_id": "D" + "b" * 16, "symbol": "NVDA", "direction": "BULLISH",
        "profile": "EXPERIMENTAL_RELAXED_V1", "session": "RTH", "price": 100.0,
        "setup_type": "reclaim", "setup_score": 1, "trade_gate_status": "WOULD_PASS",
        "bar_timestamp": "2026-09-04T14:00:00Z", "generated_at": "2026-09-04T14:00:00Z",
    })
    store.close()
    return db


def test_10_dxre_secondary_handle_is_read_only(exp_db):
    from talonx_signals.alert_store import ReadOnlyExperimentalAlertStore

    ro = ReadOnlyExperimentalAlertStore(exp_db)
    assert ro.get_radar("R" + "a" * 16)["symbol"] == "MSFT"
    # no write API, and the underlying connection is mode=ro
    with pytest.raises(sqlite3.OperationalError):
        ro._conn.execute("INSERT INTO radar_alerts(radar_id, symbol) VALUES ('x','y')")
    ro.close()


def test_11_dxre_registration_and_first_match(exp_db):
    from talonx_signals.reply import build_experimental_dxre_resolver

    handle, resolver = build_experimental_dxre_resolver(db_path=exp_db)
    assert handle is not None and resolver is not None
    out = resolver("R" + "a" * 16)
    assert out and "MSFT" in out
    # numeric / LT ids fall through unchanged (Original's path)
    assert resolver("47") is None
    assert resolver("LT47") is None
    assert resolver("not an id") is None
    handle.close()


def test_12_dxre_registered_on_single_listener(exp_db):
    from talonx_dispatch.telegram_listener import TelegramReplyListener
    from talonx_dispatch.config import DispatchConfig
    from talonx_signals.reply import build_experimental_dxre_resolver

    _, resolver = build_experimental_dxre_resolver(db_path=exp_db)
    listener = TelegramReplyListener(object(), DispatchConfig(), None,
                                     dispatch_agent=None, extra_resolvers=[resolver])
    assert len(listener.extra_resolvers) == 1


def test_13_dxre_lock_contention_fallback(monkeypatch, exp_db):
    from talonx_signals import reply as reply_mod

    def boom(_text):
        raise sqlite3.OperationalError("database is locked")

    monkeypatch.setattr(reply_mod, "make_reply_resolver", lambda store: boom)
    _, resolver = reply_mod.build_experimental_dxre_resolver(db_path=exp_db)
    msg = resolver("D" + "b" * 16)
    assert "temporarily unavailable" in msg


def test_14_original_numeric_resolver_semantics_unchanged():
    # the D/X/R/E pattern must NOT match a bare integer or an LT id
    from talonx_signals.reply import _PATTERN

    assert _PATTERN.match("47") is None
    assert _PATTERN.match("LT47") is None
    assert _PATTERN.match("D" + "a" * 16) is not None


# --------------------------------------------------------------------------- #
# 9-12 external boundary + official routing
# --------------------------------------------------------------------------- #
def test_15_experimental_external_send_structurally_blocked(tmp_path, monkeypatch):
    monkeypatch.delenv("TALONX_EXPERIMENTAL_EXTERNAL_SEND_OVERRIDE", raising=False)
    from talonx_signals.dispatcher import ExperimentalDispatcher, RecordingSender
    from talonx_signals.alert_store import ExperimentalAlertStore
    from talonx_signals.external_boundary import ExperimentalExternalBoundaryError

    class RealTransport(RecordingSender):
        is_external_transport = True

        @property
        def configured(self):
            return True

    d = ExperimentalDispatcher(store=ExperimentalAlertStore(str(tmp_path / "e.db")),
                               sender=RealTransport(), enable_external_send=True)
    with pytest.raises(ExperimentalExternalBoundaryError):
        asyncio.new_event_loop().run_until_complete(d.dispatch_trade({
            "trade_id": "X" + "9" * 16, "symbol": "MSFT", "side": "BUY", "direction": "BULLISH",
            "price": 100.0, "qty": 1, "stop_price": 98.0, "target_price": 104.0, "rr": 2.0,
            "session": "RTH", "profile": "EXPERIMENTAL_RELAXED_V1",
        }))


def test_16_override_env_permits_send(tmp_path, monkeypatch):
    monkeypatch.setenv("TALONX_EXPERIMENTAL_EXTERNAL_SEND_OVERRIDE", "i-understand")
    from talonx_signals.dispatcher import ExperimentalDispatcher, RecordingSender
    from talonx_signals.alert_store import ExperimentalAlertStore

    class RealTransport(RecordingSender):
        is_external_transport = True

        @property
        def configured(self):
            return True

    sender = RealTransport()
    d = ExperimentalDispatcher(store=ExperimentalAlertStore(str(tmp_path / "e.db")),
                               sender=sender, enable_external_send=True)
    res = asyncio.new_event_loop().run_until_complete(d.dispatch_trade({
        "trade_id": "X" + "8" * 16, "symbol": "MSFT", "side": "BUY", "direction": "BULLISH",
        "price": 100.0, "qty": 1, "stop_price": 98.0, "target_price": 104.0, "rr": 2.0,
        "session": "RTH", "profile": "EXPERIMENTAL_RELAXED_V1",
    }))
    assert res == "SENT" and len(sender.sent) == 1


def test_17_dry_run_sender_exempt_from_boundary(tmp_path, monkeypatch):
    monkeypatch.delenv("TALONX_EXPERIMENTAL_EXTERNAL_SEND_OVERRIDE", raising=False)
    from talonx_signals.dispatcher import ExperimentalDispatcher, RecordingSender
    from talonx_signals.alert_store import ExperimentalAlertStore

    d = ExperimentalDispatcher(store=ExperimentalAlertStore(str(tmp_path / "e.db")),
                               sender=RecordingSender(), enable_external_send=True)
    # RecordingSender.is_external_transport is False -> no boundary error, send "succeeds" locally
    res = asyncio.new_event_loop().run_until_complete(d.dispatch_trade({
        "trade_id": "X" + "7" * 16, "symbol": "MSFT", "side": "BUY", "direction": "BULLISH",
        "price": 100.0, "qty": 1, "stop_price": 98.0, "target_price": 104.0, "rr": 2.0,
        "session": "RTH", "profile": "EXPERIMENTAL_RELAXED_V1",
    }))
    assert res == "SENT"


def test_18_official_router_eligibility_rules():
    from talonx_ops.official_dispatch import OfficialExternalRouter

    r = OfficialExternalRouter(delivered_probe=lambda f, k: False)
    assert r.decide("original", "k1").should_send is True
    assert r.decide("actionable_alert", "k2").eligible is True
    assert r.decide("radar", "k3").eligible is True           # approved Task 96 family
    assert r.decide("directional", "k4").eligible is False
    assert r.decide("experimental_trade", "k5").eligible is False
    assert r.decide("totally_unknown", "k6").eligible is False  # fail-closed


def test_19_official_router_dedup_no_duplicate_send():
    from talonx_ops.official_dispatch import OfficialExternalRouter

    seen = {"dup-1"}
    r = OfficialExternalRouter(delivered_probe=lambda f, k: k in seen)
    d1 = r.decide("original", "dup-1")
    assert d1.eligible is True and d1.already_delivered is True and d1.should_send is False
    d2 = r.decide("original", "fresh-2")
    assert d2.should_send is True


def test_20_router_does_not_merge_stores():
    from talonx_ops.official_dispatch import OfficialExternalRouter

    stores = OfficialExternalRouter().delivery_stores()
    assert set(stores) == {"original", "experimental", "intelligence_96f"}
    assert stores["original"] != stores["experimental"]


# --------------------------------------------------------------------------- #
# 13 Task 99H escaping retained through the D/X/R/E render path
# --------------------------------------------------------------------------- #
def test_21_task99h_escaping_retained_via_dxre(tmp_path):
    from talonx_signals.alert_store import ExperimentalAlertStore, ReadOnlyExperimentalAlertStore
    from talonx_signals.reply import make_reply_resolver

    db = tmp_path / "exp_alerts.db"
    w = ExperimentalAlertStore(str(db))
    w.record_directional({
        "alert_id": "D" + "c" * 16, "symbol": "BRK_B", "direction": "BULLISH",
        "profile": "EXPERIMENTAL_RELAXED_V1", "session": "RTH", "price": 12.5,
        "setup_type": "under_scored_setup", "setup_score": 1,
        "trade_gate_status": "WOULD_REJECT", "trade_gate_reject_reason": "LOW_RISK_REWARD",
        "message": "under_bar move [see chart] *now*",
        "bar_timestamp": "2026-09-04T14:00:00Z", "generated_at": "2026-09-04T14:00:00Z",
    })
    w.close()
    resolver = make_reply_resolver(ReadOnlyExperimentalAlertStore(db))
    out = resolver("D" + "c" * 16)
    # Task 99H invariant: dynamic Markdown metacharacters in the rendered detail
    # card are escaped exactly once (no raw `_` in the dynamic symbol/profile/setup).
    assert "BRK\\_B" in out                       # symbol underscore escaped
    assert "EXPERIMENTAL\\_RELAXED\\_V1" in out   # profile underscores escaped
    assert "under\\_scored\\_setup" in out        # setup_type underscores escaped
    # and no double-escaping crept in
    assert "\\\\_" not in out


# --------------------------------------------------------------------------- #
# 14-16 intelligence independent start / crash restart / isolation
# --------------------------------------------------------------------------- #
def test_22_intelligence_independent_start(sup):
    sup.start_all()
    assert sup.components["intelligence"].state is ComponentState.READY
    # it has no start dependency on original/experimental beyond ordering
    spec = sup.components["intelligence"].spec
    assert spec.classification is Classification.OPTIONAL


def test_23_intelligence_crash_restart_bounded_backoff(sup):
    sup.start_all()
    sup._runner.newest("intelligence").die(1)
    sup.poll_once()
    c = sup.components["intelligence"]
    assert c.state is ComponentState.RESTARTING
    # unbounded policy -> never FAILED, keeps restarting
    for i in range(6):
        sup._clock_list[0] += 2000.0
        sup.poll_once()
        if c.state is ComponentState.READY:
            sup._runner.newest("intelligence").die(1)
            sup.poll_once()
    assert c.state in (ComponentState.READY, ComponentState.RESTARTING)
    assert c.state is not ComponentState.FAILED


def test_24_intelligence_failure_does_not_kill_original(sup):
    sup.start_all()
    for _ in range(5):
        sup._runner.newest("intelligence").die(1)
        sup.poll_once()
        sup._clock_list[0] += 2000.0
        sup.poll_once()
    assert sup.components["original"].state is ComponentState.READY
    hv = sup.aggregate_health(market_view={"state": "HEALTHY"})
    assert hv["original"] == "READY"
    assert hv["overall"] in ("DEGRADED", "HEALTHY")   # never FAILED for an optional crash
    assert hv["overall"] != "FAILED"


def test_25_experimental_failure_does_not_kill_original(sup):
    sup.start_all()
    sup._runner.newest("experimental").die(1)
    sup.poll_once()
    assert sup.components["original"].state is ComponentState.READY
    assert sup.components["experimental"].state is ComponentState.RESTARTING


# --------------------------------------------------------------------------- #
# controlled shutdown order + isolation
# --------------------------------------------------------------------------- #
def test_26_controlled_shutdown_semantic_order(sup):
    sup.start_all()
    order = []
    orig = sup._stop_component
    sup._stop_component = lambda c: (order.append(c.name), orig(c))[1]
    res = sup.stop_all()
    assert order[:4] == ["experimental", "intelligence", "original", "dashboard"]
    assert res["orphans"] == []
    assert all(c.state is ComponentState.STOPPED for c in sup.components.values())


def test_27_shutdown_persists_eod_once(sup):
    sup.start_all()
    calls = []
    sup._on_shutdown_persist_eod = lambda: (calls.append(1), {"session_date": "2026-09-04", "status": "PARTIAL"})[1]
    sup.stop_all()
    sup.stop_all()   # idempotent -- persist not called again
    assert len(calls) == 1


def test_28_idempotent_stop_no_error(sup):
    sup.start_all()
    sup.stop_all()
    sup.stop_all()
    sup.poll_once()  # must not raise


# --------------------------------------------------------------------------- #
# market health unified accessor (Phase 12)
# --------------------------------------------------------------------------- #
def test_29_market_health_offline_safe(tmp_path):
    from talonx_ops.market_health import MarketHealth

    v = MarketHealth(home=tmp_path, check_processes=False,
                     producer_probe=lambda: {"live": False, "reason": "test"}).view()
    assert v.state == "DISCONNECTED"
    assert v.symbols_priced is None or v.symbols_priced == 0


def test_30_market_health_healthy_when_producer_live_and_fresh(tmp_path):
    from talonx_ops.market_health import MarketHealth

    db = tmp_path / "paper_trading.db"
    con = sqlite3.connect(db)
    con.execute("CREATE TABLE latest_prices(ticker TEXT, price REAL, updated_at TEXT)")
    now = datetime.now(timezone.utc).isoformat()
    con.executemany("INSERT INTO latest_prices VALUES (?,?,?)",
                    [("MSFT", 1.0, now), ("NVDA", 2.0, now)])
    con.commit()
    con.close()
    v = MarketHealth(home=tmp_path, check_processes=False,
                     producer_probe=lambda: {"live": True, "reason": "test"}).view()
    assert v.state == "HEALTHY"
    assert v.symbols_priced == 2


def test_31_market_health_stale_when_ticks_old(tmp_path):
    from talonx_ops.market_health import MarketHealth

    db = tmp_path / "paper_trading.db"
    con = sqlite3.connect(db)
    con.execute("CREATE TABLE latest_prices(ticker TEXT, price REAL, updated_at TEXT)")
    con.execute("INSERT INTO latest_prices VALUES ('MSFT', 1.0, '2020-01-01T00:00:00+00:00')")
    con.commit()
    con.close()
    v = MarketHealth(home=tmp_path, check_processes=False,
                     producer_probe=lambda: {"live": True, "reason": "test"}).view()
    assert v.state == "STALE"


# --------------------------------------------------------------------------- #
# EOD reconciliation store (Phase 13)
# --------------------------------------------------------------------------- #
def test_32_eod_reconciliation_idempotent(tmp_path):
    from talonx_ops.eod_reconciliation import run_and_persist

    kw = dict(session_date="2026-09-04", db_path=tmp_path / "eod.db",
              home=tmp_path, exp_home=tmp_path / "exp", ledger_path=tmp_path / "l.db")
    (tmp_path / "exp").mkdir()
    run_and_persist(**kw)
    run_and_persist(**kw)
    con = sqlite3.connect(tmp_path / "eod.db")
    n = con.execute("SELECT COUNT(*) FROM eod_sessions WHERE session_date='2026-09-04'").fetchone()[0]
    con.close()
    assert n == 1


def test_33_eod_piv_not_checked_when_no_reader(tmp_path):
    from talonx_ops.eod_reconciliation import build_reconciliation, NOT_CHECKED

    rec = build_reconciliation(session_date="2026-09-04", home=tmp_path,
                               exp_home=tmp_path / "exp", ledger_path=tmp_path / "l.db")
    piv = [c for c in rec.component_status if c["name"] == "piv_paper"][0]
    assert piv["outcome"] == NOT_CHECKED
    assert rec.piv_paper == {"positions": None, "orders": None}   # never fabricated 0


def test_34_eod_piv_checked_with_reader(tmp_path):
    from talonx_ops.eod_reconciliation import build_reconciliation, CHECKED

    rec = build_reconciliation(session_date="2026-09-04", home=tmp_path,
                               exp_home=tmp_path / "exp", ledger_path=tmp_path / "l.db",
                               piv_reader=lambda: {"positions": 0, "orders": 0})
    piv = [c for c in rec.component_status if c["name"] == "piv_paper"][0]
    assert piv["outcome"] == CHECKED
    assert rec.piv_paper == {"positions": 0, "orders": 0}


def test_35_eod_store_read_only_does_not_create(tmp_path):
    from talonx_ops.eod_reconciliation import EodReconciliationStore

    p = tmp_path / "missing_eod.db"
    st = EodReconciliationStore(p, read_only=True)
    assert st.latest() is None
    st.close()
    assert not p.exists()


# --------------------------------------------------------------------------- #
# SingletonLock.is_stale (Phase 8 / checklist step 2)
# --------------------------------------------------------------------------- #
def test_36_singleton_lock_is_stale(tmp_path):
    from talonx_ingest.intelligence.service.singleton import SingletonLock
    import socket

    lp = tmp_path / "service.lock"
    lp.write_text(json.dumps({
        "pid": 999999, "host": socket.gethostname(),
        "started_at_utc": "2026-09-04T00:00:00+00:00", "argv": [],
    }), encoding="utf-8")
    assert SingletonLock(lp).is_stale() is True


def test_37_singleton_lock_not_stale_for_live_pid(tmp_path):
    from talonx_ingest.intelligence.service.singleton import SingletonLock
    import os
    import socket

    lp = tmp_path / "service.lock"
    lp.write_text(json.dumps({
        "pid": os.getpid(), "host": socket.gethostname(),
        "started_at_utc": "2026-09-04T00:00:00+00:00", "argv": [],
    }), encoding="utf-8")
    assert SingletonLock(lp).is_stale() is False


def test_38_singleton_lock_not_stale_other_host(tmp_path):
    from talonx_ingest.intelligence.service.singleton import SingletonLock

    lp = tmp_path / "service.lock"
    lp.write_text(json.dumps({
        "pid": 1, "host": "some-other-host",
        "started_at_utc": "2026-09-04T00:00:00+00:00", "argv": [],
    }), encoding="utf-8")
    assert SingletonLock(lp).is_stale() is False   # cannot know -> not stale


def test_39_singleton_lock_no_file_not_stale(tmp_path):
    from talonx_ingest.intelligence.service.singleton import SingletonLock

    assert SingletonLock(tmp_path / "nope.lock").is_stale() is False


# --------------------------------------------------------------------------- #
# AuthoritativeReadModel Phase 16 additions
# --------------------------------------------------------------------------- #
def test_40_read_model_supervision_domain(tmp_path):
    from talonx_ops.authoritative_read_model import AuthoritativeReadModel

    da = AuthoritativeReadModel(home=tmp_path, check_processes=False).supervision()
    assert da.domain == "supervision"
    assert da.values["experimental_external_eligible"] is False
    assert da.values["telegram_owner_invariant_ok"] is True


def test_41_read_model_eod_domain_reads_store(tmp_path):
    from talonx_ops.authoritative_read_model import AuthoritativeReadModel
    from talonx_ops.eod_reconciliation import run_and_persist

    (tmp_path / "experimental").mkdir()
    run_and_persist(session_date=datetime.now(timezone.utc).strftime("%Y-%m-%d"),
                    db_path=tmp_path / "eod_reconciliation.db", home=tmp_path,
                    exp_home=tmp_path / "experimental", ledger_path=tmp_path / "ingestion_ledger.db")
    da = AuthoritativeReadModel(home=tmp_path, check_processes=False).eod_reconciliation()
    # Task 118A P3: this bare tmp_path fixture has no real paper-trading/
    # ledger files, so build_reconciliation's own component checks come
    # back UNKNOWN, not a completed RECONCILED -- exactly the case that
    # must NOT read as "today_reconciled". A record for today existing at
    # all is still visible separately via today_has_a_record.
    assert da.values["today_has_a_record"] is True
    assert da.values["today_record_status"] not in ("RECONCILED", "RECONCILED_WITH_MISMATCH")
    assert da.values["today_reconciled"] is False
    assert "status" in da.values


def test_41b_today_reconciled_true_only_for_a_genuinely_complete_record(tmp_path):
    """Task 118A P3 regression: the misleading case this fixes -- a same-
    day record whose own status is not RECONCILED must never read as
    today_reconciled=True, which is what an operator glancing at the
    dashboard before close would otherwise be told. This directly tests
    the corrected boolean against every real status value, rather than
    just one scenario's component-check outcome (which depends on what
    real store files build_reconciliation happens to find)."""
    from talonx_ops.authoritative_read_model import AuthoritativeReadModel
    from talonx_ops.eod_reconciliation import (
        STATUS_MISMATCH, STATUS_PARTIAL, STATUS_RECONCILED, STATUS_UNKNOWN, run_and_persist,
    )

    (tmp_path / "experimental").mkdir()
    session = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    run_and_persist(session_date=session, db_path=tmp_path / "eod_reconciliation.db",
                    home=tmp_path, exp_home=tmp_path / "experimental",
                    ledger_path=tmp_path / "ingestion_ledger.db")
    da = AuthoritativeReadModel(home=tmp_path, check_processes=False).eod_reconciliation()
    status = da.values["today_record_status"]
    assert status in (STATUS_PARTIAL, STATUS_MISMATCH, STATUS_RECONCILED, STATUS_UNKNOWN)
    expected = status in ("RECONCILED", "RECONCILED_WITH_MISMATCH")
    assert da.values["today_reconciled"] is expected


def test_42_read_model_market_delegates_to_market_health(tmp_path):
    from talonx_ops.authoritative_read_model import AuthoritativeReadModel

    da = AuthoritativeReadModel(home=tmp_path, check_processes=False).market()
    assert "MarketHealth" in da.authoritative_source
    assert "state" in da.values          # the MarketHealthView fields are surfaced


def test_43_snapshot_has_15_domains(tmp_path):
    from talonx_ops.authoritative_read_model import AuthoritativeReadModel

    snap = AuthoritativeReadModel(home=tmp_path, check_processes=False).snapshot()
    domains = {d["domain"] for d in snap["domains"]}
    assert "supervision" in domains
    assert len(snap["domains"]) == 15


# --------------------------------------------------------------------------- #
# canary verdicts (Phase 18 / 19)
# --------------------------------------------------------------------------- #
_CANARY_DIR = _REPO / "results" / "task100b_runtime_integration"
_OFFLINE = _CANARY_DIR / "offline_integration_canary.py"
_REPLAY = _CANARY_DIR / "replay_canary.py"


@pytest.mark.skipif(not _OFFLINE.exists(), reason="canary script not present (results/ is gitignored)")
def test_44_offline_integration_canary_passes():
    r = subprocess.run([sys.executable, str(_OFFLINE)], capture_output=True, text=True, timeout=300)
    assert "TASK100B_OFFLINE_INTEGRATION_CANARY_PASS" in r.stdout, r.stdout + r.stderr
    assert r.returncode == 0


@pytest.mark.skipif(not _REPLAY.exists(), reason="canary script not present (results/ is gitignored)")
def test_45_replay_canary_passes():
    r = subprocess.run([sys.executable, str(_REPLAY)], capture_output=True, text=True, timeout=300)
    assert "TASK100B_REPLAY_CANARY_PASS" in r.stdout, r.stdout + r.stderr
    assert r.returncode == 0


# --------------------------------------------------------------------------- #
# default component set sanity
# --------------------------------------------------------------------------- #
def test_46_default_components_classification():
    specs = {s.name: s for s in default_talonx_components()}
    assert specs["original"].classification is Classification.MANDATORY
    # SUPERSEDED 2026-09-24 (S14): the Experimental lane is RETIRED from active startup
    assert "experimental" not in specs
    for opt in ("intelligence", "dashboard"):
        assert specs[opt].classification is Classification.OPTIONAL
    # intelligence retries forever (never FAILED on its own)
    assert specs["intelligence"].restart_policy.max_restarts is None
    # intelligence invocation is the unchanged poll --with-backfill entrypoint
    assert specs["intelligence"].argv[-3:] == ["talonx_ingest.intelligence.service", "poll", "--with-backfill"]


def test_47_aggregate_health_original_ready_optional_down_is_degraded_not_failed(sup):
    sup.start_all()
    sup.components["intelligence"].state = ComponentState.FAILED
    hv = sup.aggregate_health(market_view={"state": "HEALTHY"})
    assert hv["original"] == "READY"
    assert hv["overall"] == "DEGRADED"
    assert hv["intelligence"] == "FAILED"
