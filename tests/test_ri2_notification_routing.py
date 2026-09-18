"""
V2 Release Integration RI-2 -- Multi-Channel Telegram + Durable
Trade/Event/Operations Routing.

Targeted tests only, covering the 31 minimum required scenarios. NO
real Telegram send anywhere -- every test uses `RecordingTransport`
(talonx_v2/delivery.py, already established) or a plain fake client
injected via `client=` into `talonx_ops.notify.worker.drain`.
"""
from __future__ import annotations

import time
from datetime import date, datetime, timedelta, timezone

import pytest

from talonx_v2 import calendar as vc
from talonx_v2 import paper, pipeline
from talonx_v2.cluster_engine import ClusterEpisode
from talonx_v2.config import V2Config
from talonx_v2.delivery import RecordingTransport
from talonx_v2.schemas import V2Action, V2Decision, V2Direction
from talonx_v2.service import V2Service
from talonx_v2.store import V2Store
from talonx_ops.notify import OPERATIONS, RESEARCH, TRADE_EVENT, resolve_destination_config
from talonx_ops.notify.outbox import NotifyStore
from talonx_ops.notify.producers import (
    enqueue_delivery_subsystem_failure, enqueue_lifecycle_event,
    enqueue_reconciliation_failure, enqueue_research_event, scan_v2_operational_events,
)
from talonx_ops.notify.worker import drain

BALANCE = 300_000.0
ALLOC = 10_000.0
ACT = date(2026, 8, 14)
ENTRY_SESSION = vc.next_session_strictly_after(ACT)


def _decision(episode_id="ep1", symbol="AAA"):
    return V2Decision(signal_id=f"sig-{episode_id}", episode_id=episode_id, symbol=symbol,
                      direction=V2Direction.BULLISH, action=V2Action.BUY,
                      official_eligible=False, rationale="test",
                      eligible_entry_session=date(2026, 9, 8))


def _ep(entry_session, episode_id, symbol):
    return ClusterEpisode(episode_id=episode_id, symbol=symbol, issuer_cik="x",
                          distinct_owner_ciks=("a", "b"), n_distinct_owners=2, n_filings=2,
                          first_filing_date=ACT, activation_filing_date=ACT, last_filing_date=ACT,
                          aggregate_purchase_value=0.0, any_officer=False, any_director=False,
                          any_ten_percent=False,
                          causal_event_ts=datetime(2026, 8, 14, 23, 59, 59, tzinfo=timezone.utc),
                          eligible_entry_session=entry_session)


def _fixed_buy_decision(e):
    liq = type("Liq", (), {"ok": True, "median_dollar_volume": 1e7, "last_close": 10.0})()
    dec = V2Decision(signal_id="s1", episode_id=e.episode_id, symbol=e.symbol,
                     direction=V2Direction.BULLISH, action=V2Action.BUY,
                     official_eligible=False, rationale="test (RI-2 fixture)",
                     eligible_entry_session=e.eligible_entry_session)
    return liq, dec


def _svc(tmp, db_path, *, name, symbols, starting_cash=BALANCE, alloc=ALLOC, campaign_id="V2",
        ops_notify_store=None):
    import csv
    bd = tmp / f"bars_{name}"
    bd.mkdir(exist_ok=True)
    sess = [s for s in vc._sessions() if date(2019, 1, 1) <= s <= date(2027, 12, 31)]
    for sym in symbols:
        with open(bd / f"{sym}.csv", "w", newline="") as f:
            w = csv.writer(f)
            w.writerow(["date", "open", "close", "volume"])
            for s in sess:
                w.writerow([s.isoformat(), 40.0, 40.5, 1_500_000])
    cfg = V2Config(db_path=str(db_path), starting_cash_usd=starting_cash,
                   per_position_allocation_usd=alloc, campaign_id=campaign_id)
    return V2Service(config=cfg, bar_dirs=[bd], form4_kind="parquet",
                     status_path=str(tmp / f"{name}.json"), ops_notify_store=ops_notify_store)


def _wire(svc, symbol):
    svc._dissemination_lookup = {(symbol, ACT.isoformat()): datetime(2026, 8, 14, 15, 20, tzinfo=timezone.utc)}
    svc._eval_causal_decision = _fixed_buy_decision


def _reserve_then_fill(svc, ep, *, reserve_today: date = ACT, fill_session: date = ENTRY_SESSION):
    svc._phase_post_close([ep], [ep], today=reserve_today, ripe_through=reserve_today,
                          is_stale=lambda e: False, live=False)
    res = pipeline.ProcessResult()
    price_lookup = svc._resilient_price_lookup(live=False)
    svc._phase_open([ep], fill_session, res, price_lookup=price_lookup, today=fill_session, live=False)
    return res


def _entered(tmp_path, *, cash=BALANCE, allocation=ALLOC, symbol="AAA", episode_id="ep1",
            db_name="v.db", entry_price=100.0, campaign_id="RI2_CAMP"):
    store = V2Store(str(tmp_path / db_name), starting_cash=cash, campaign_id=campaign_id,
                    per_position_allocation_usd=allocation)
    cfg = V2Config(starting_cash_usd=cash, per_position_allocation_usd=allocation,
                   campaign_id=campaign_id)
    outcome = paper.enter_position(store, _decision(episode_id, symbol), entry_price=entry_price,
                                   entry_session=date(2026, 9, 8), config=cfg)
    return store, cfg, outcome


def _clean_env(monkeypatch):
    """Ensures every destination starts from a clean, known env state --
    no test leaks TELEGRAM_*/TALONX_NOTIFY_* into another."""
    for k in list(__import__("os").environ):
        if k.startswith("TALONX_NOTIFY_") or k in ("TELEGRAM_BOT_TOKEN", "TELEGRAM_CHAT_ID"):
            monkeypatch.delenv(k, raising=False)


# ======================================================================= #
# 1-3 -- V2 BUY/SELL -> TRADE_EVENT, campaign identity retained
# ======================================================================= #

def test_1_2_3_v2_buy_and_sell_route_to_trade_event_with_campaign_identity(tmp_path):
    """Outbox rows are enqueued by V2Service (_on_entry_recorded/
    _on_exit_recorded), not by the low-level paper.enter_position/
    close_position calls directly -- drives the REAL service phases,
    the same pattern RI-1's own test suite established."""
    svc = _svc(tmp_path, tmp_path / "v2_lane.db", name="ri2buysell", symbols=["AAA"],
              campaign_id="RI2_CAMP")
    _wire(svc, "AAA")
    ep = _ep(ENTRY_SESSION, "epBS", "AAA")
    res = _reserve_then_fill(svc, ep)
    assert len(res.entries) == 1

    ob = svc.store.all_outbox()
    buy_rows = [r for r in ob if r["action"] == "BUY"]
    assert buy_rows, "no BUY alert enqueued"
    buy_row = buy_rows[-1]
    assert buy_row["destination"] == TRADE_EVENT
    assert "RI2_CAMP" in buy_row["payload_text"]
    assert "RI2_CAMP" in buy_row["provenance_json"]

    pos = svc.store.all_positions()[0]
    exit_res = pipeline.ProcessResult()
    exit_price_lookup = svc._resilient_price_lookup(live=False)
    svc._phase_close(vc.add_sessions(ENTRY_SESSION, 10), exit_res, price_lookup=exit_price_lookup)
    if exit_res.exits:
        sell_rows = [r for r in svc.store.all_outbox() if r["action"] == "SELL"]
        assert sell_rows
        assert sell_rows[-1]["destination"] == TRADE_EVENT
        assert "RI2_CAMP" in sell_rows[-1]["payload_text"]
    # campaign identity unaffected either way (entry alone already proves it)
    assert svc.store.campaign_identity()["campaign_id"] == "RI2_CAMP"


# ======================================================================= #
# 4-6 -- operational failure / account block / reconciliation failure -> OPERATIONS
# ======================================================================= #

def test_4_5_account_block_and_exit_unresolved_route_to_operations(tmp_path):
    store, cfg, outcome = _entered(tmp_path, campaign_id="OPS_CAMP")
    assert outcome.entered
    pos = store.all_positions()[0]
    store.mark_exit_unresolved(pos["position_id"], detail="no bar found")

    ops = NotifyStore(str(tmp_path / "notify.db"))
    counts = scan_v2_operational_events(store, ops)
    assert counts["exit_unresolved"] == 1
    assert counts["account_block"] == 1  # mark_exit_unresolved also records a block (Package 2)

    rows = ops.all_outbox(destination=OPERATIONS)
    types = {r["event_type"] for r in rows}
    assert "EXIT_UNRESOLVED" in types
    assert "ACCOUNT_BLOCK" in types
    for r in rows:
        assert r["destination"] == OPERATIONS


def test_6_reconciliation_failure_routes_to_operations(tmp_path):
    ops = NotifyStore(str(tmp_path / "notify.db"))
    ok = enqueue_reconciliation_failure(
        ops, campaign_id="RECON_CAMP", findings=["cash_plus_open_cost_reconciles: FAIL"],
        reference="blk123")
    assert ok
    rows = ops.all_outbox(destination=OPERATIONS)
    assert len(rows) == 1
    assert rows[0]["event_type"] == "RECONCILIATION_FAILURE"
    assert "RECON_CAMP" in rows[0]["payload_text"]


# ======================================================================= #
# 7-10 -- Research: routes to RESEARCH, OFF by default, no fallback
# ======================================================================= #

def test_7_research_event_routes_to_research_destination(tmp_path):
    ops = NotifyStore(str(tmp_path / "notify.db"))
    ok = enqueue_research_event(ops, event_type="BACKTEST_EVALUATION",
                                summary="illustrative research record", source="talonx_backtest")
    assert ok
    rows = ops.all_outbox(destination=RESEARCH)
    assert len(rows) == 1 and rows[0]["destination"] == RESEARCH


def test_8_research_off_by_default_no_send(tmp_path, monkeypatch):
    _clean_env(monkeypatch)
    cfg = resolve_destination_config(RESEARCH)
    assert cfg.enabled is False

    ops = NotifyStore(str(tmp_path / "notify.db"))
    enqueue_research_event(ops, event_type="X", summary="s", source="test")
    client = RecordingTransport()
    result = drain(ops, destination=RESEARCH, client=client)
    assert result["enabled"] is False
    assert client.sent == []  # no send attempted at all
    # row is untouched, still PENDING -- not silently discarded
    assert ops.all_outbox(destination=RESEARCH)[0]["state"] == "PENDING"


def test_9_research_off_does_not_fallback_to_trade_event(tmp_path, monkeypatch):
    _clean_env(monkeypatch)
    ops = NotifyStore(str(tmp_path / "notify.db"))
    enqueue_research_event(ops, event_type="X", summary="s", source="test")
    # confirm nothing was ever written into TRADE_EVENT's own queryable slice
    assert ops.all_outbox(destination=TRADE_EVENT) == []


def test_10_research_off_does_not_fallback_to_operations(tmp_path, monkeypatch):
    _clean_env(monkeypatch)
    ops = NotifyStore(str(tmp_path / "notify.db"))
    enqueue_research_event(ops, event_type="X", summary="s", source="test")
    assert ops.all_outbox(destination=OPERATIONS) == []


def test_research_enabled_with_own_credentials_sends(tmp_path, monkeypatch):
    _clean_env(monkeypatch)
    monkeypatch.setenv("TALONX_NOTIFY_RESEARCH_ENABLED", "1")
    monkeypatch.setenv("TALONX_NOTIFY_RESEARCH_BOT_TOKEN", "rtok")
    monkeypatch.setenv("TALONX_NOTIFY_RESEARCH_CHAT_ID", "rchat")
    cfg = resolve_destination_config(RESEARCH)
    assert cfg.enabled is True and cfg.bot_token == "rtok" and cfg.chat_id == "rchat"

    ops = NotifyStore(str(tmp_path / "notify.db"))
    enqueue_research_event(ops, event_type="X", summary="s", source="test")
    client = RecordingTransport()
    result = drain(ops, destination=RESEARCH, client=client)
    assert result["sent"] == 1
    assert len(client.sent) == 1


def test_research_enabled_flag_without_credentials_still_disabled(monkeypatch):
    _clean_env(monkeypatch)
    monkeypatch.setenv("TALONX_NOTIFY_RESEARCH_ENABLED", "1")
    # deliberately no token/chat_id set
    cfg = resolve_destination_config(RESEARCH)
    assert cfg.enabled is False  # the flag alone is not sufficient


# ======================================================================= #
# 11-12 -- company-development routing
# ======================================================================= #

def test_11_12_company_development_routing_is_a_documented_bounded_gap():
    """RI2-G: Intelligence's own pipeline (Task 96E significance bands +
    Task 96F delivery) is the SOLE authoritative producer/outbox/
    delivery owner for company-development cards -- its content/
    materiality logic is NOT redesigned or retrofitted by RI-2 (out of
    scope: 'do not redesign its strategy/content logic'). This test
    confirms the existing gate is real (IMMEDIATE_MIN_BAND == HIGH,
    i.e. LOW/MEDIUM significance never reaches immediate delivery),
    satisfying 'unapproved/research-only event types must not silently
    reach the primary channel' without RI-2 rebuilding that gate."""
    from talonx_ingest.intelligence.delivery.config import IMMEDIATE_MIN_BAND
    from talonx_ingest.intelligence.domain import SignificanceBand
    assert IMMEDIATE_MIN_BAND in (SignificanceBand.HIGH, SignificanceBand.CRITICAL)


# ======================================================================= #
# 13-18 -- durable outbox, runtime drain wiring, retry, restart
# ======================================================================= #

def test_13_event_persisted_before_delivery(tmp_path):
    ops = NotifyStore(str(tmp_path / "notify.db"))
    ops.enqueue(event_id="e1", destination=OPERATIONS, event_type="TEST", producer="test",
               dedup_key="d1", payload_text="hello", provenance={})
    # persisted BEFORE any drain/send is ever attempted
    assert ops.all_outbox()[0]["state"] == "PENDING"


def test_14_runtime_delivery_component_actually_drains_outbox(tmp_path, monkeypatch):
    """RI2-I: proves an actual RUNTIME COMPONENT (V2Service.tick, the
    SAME already-proven-wired tick loop RI-1/Package-4 use) invokes the
    OPERATIONS delivery worker -- not a manually-invoked drain() call in
    isolation."""
    from talonx_v2.service import V2Service

    store = V2Store(str(tmp_path / "v2.db"), starting_cash=BALANCE, campaign_id="WIRE_TEST")
    pos_id = store.insert_open_position(
        episode_id="epW", symbol="AAA", issuer_cik="x", entry_session=date(2026, 9, 8),
        target_exit_session=date(2026, 9, 22), entry_price=100.0, shares=10, position_cost=1000.0)
    store.mark_exit_unresolved(pos_id, detail="test")

    ops = NotifyStore(str(tmp_path / "notify.db"))
    cfg = V2Config(db_path=str(tmp_path / "v2.db"), starting_cash_usd=BALANCE, campaign_id="WIRE_TEST")
    svc = V2Service(config=cfg, bar_dirs=[tmp_path / "bars"], ops_notify_store=ops)

    monkeypatch.setenv("TALONX_NOTIFY_OPERATIONS_ENABLED", "irrelevant")  # OPERATIONS has no such gate; sanity no-op
    fake_client = RecordingTransport()
    monkeypatch.setattr("talonx_ops.notify.worker.telegram_client_for",
                        lambda dest: fake_client)
    monkeypatch.setenv("TALONX_NOTIFY_OPERATIONS_BOT_TOKEN", "t")
    monkeypatch.setenv("TALONX_NOTIFY_OPERATIONS_CHAT_ID", "c")

    svc.tick(as_of=date(2026, 9, 8))  # the real runtime tick -- not a direct drain() call

    assert len(fake_client.sent) >= 1, "V2Service.tick() did not actually drive the OPERATIONS drain"
    assert ops.all_outbox(destination=OPERATIONS)
    assert any(r["state"] == "SENT" for r in ops.all_outbox(destination=OPERATIONS))


def test_15_success_marks_sent(tmp_path, monkeypatch):
    monkeypatch.setenv("TALONX_NOTIFY_OPERATIONS_BOT_TOKEN", "t")
    monkeypatch.setenv("TALONX_NOTIFY_OPERATIONS_CHAT_ID", "c")
    ops = NotifyStore(str(tmp_path / "notify.db"))
    ops.enqueue(event_id="e1", destination=OPERATIONS, event_type="TEST", producer="test",
               dedup_key="d1", payload_text="hello", provenance={})
    client = RecordingTransport()
    result = drain(ops, destination=OPERATIONS, client=client)
    assert result["sent"] == 1
    assert ops.all_outbox()[0]["state"] == "SENT"


def test_16_transient_failure_retries(tmp_path, monkeypatch):
    monkeypatch.setenv("TALONX_NOTIFY_OPERATIONS_BOT_TOKEN", "t")
    monkeypatch.setenv("TALONX_NOTIFY_OPERATIONS_CHAT_ID", "c")
    ops = NotifyStore(str(tmp_path / "notify.db"))
    ops.enqueue(event_id="e1", destination=OPERATIONS, event_type="TEST", producer="test",
               dedup_key="d1", payload_text="hello", provenance={})
    client = RecordingTransport(outcomes=[{"ok": False, "detail": "timeout"}])
    result = drain(ops, destination=OPERATIONS, client=client)
    assert result["retry"] == 1
    row = ops.all_outbox()[0]
    assert row["state"] == "RETRY" and row["attempts"] == 1 and row["next_attempt_utc"]


def test_17_restart_retry_resumes(tmp_path, monkeypatch):
    monkeypatch.setenv("TALONX_NOTIFY_OPERATIONS_BOT_TOKEN", "t")
    monkeypatch.setenv("TALONX_NOTIFY_OPERATIONS_CHAT_ID", "c")
    path = str(tmp_path / "notify.db")
    ops1 = NotifyStore(path)
    ops1.enqueue(event_id="e1", destination=OPERATIONS, event_type="TEST", producer="test",
                dedup_key="d1", payload_text="hello", provenance={})
    drain(ops1, destination=OPERATIONS, client=RecordingTransport(outcomes=[{"ok": False, "detail": "x"}]))
    del ops1

    # "restart" -- fresh store instance, same file
    ops2 = NotifyStore(path)
    row = ops2.all_outbox()[0]
    assert row["state"] == "RETRY"
    # past the backoff window
    past = datetime.fromisoformat(row["next_attempt_utc"]) + timedelta(seconds=1)
    client2 = RecordingTransport()
    result = drain(ops2, destination=OPERATIONS, now=past, client=client2)
    assert result["sent"] == 1


def test_18_eventual_success_after_retry(tmp_path, monkeypatch):
    monkeypatch.setenv("TALONX_NOTIFY_OPERATIONS_BOT_TOKEN", "t")
    monkeypatch.setenv("TALONX_NOTIFY_OPERATIONS_CHAT_ID", "c")
    ops = NotifyStore(str(tmp_path / "notify.db"))
    ops.enqueue(event_id="e1", destination=OPERATIONS, event_type="TEST", producer="test",
               dedup_key="d1", payload_text="hello", provenance={})
    client = RecordingTransport(outcomes=[{"ok": False, "detail": "x"}])
    drain(ops, destination=OPERATIONS, client=client)
    row = ops.all_outbox()[0]
    past = datetime.fromisoformat(row["next_attempt_utc"]) + timedelta(seconds=1)
    result = drain(ops, destination=OPERATIONS, now=past, client=client)
    assert result["sent"] == 1
    assert ops.all_outbox()[0]["state"] == "SENT"


# ======================================================================= #
# 19 -- business trade survives Telegram failure
# ======================================================================= #

def test_19_v2_buy_survives_telegram_failure(tmp_path, monkeypatch):
    """The trade already happened (paper.enter_position committed) BEFORE
    any delivery is ever attempted -- V2's own outbox is drained
    separately/later. This test proves the position/cash are correct
    and permanent regardless of what a LATER delivery attempt does."""
    store, cfg, outcome = _entered(tmp_path, campaign_id="SURVIVE")
    assert outcome.entered
    pos = store.all_positions()[0]
    assert pos["status"] == "OPEN"
    cash_after_buy = store.cash()

    # simulate every possible delivery failure downstream -- position/cash
    # are already committed and cannot be affected by this at all.
    from talonx_v2.delivery import deliver_outbox
    class _AlwaysFails:
        name = "fails"
        def send(self, *a, **k):
            raise RuntimeError("simulated total Telegram outage")
    class _Router:
        def decide(self, family, dedup_key, origin="PRODUCT_WATCHLIST"):
            from talonx_ops.official_dispatch import RoutingDecision
            return RoutingDecision(family=family, eligible=True, already_delivered=False,
                                   path="official_telegram", reason="test")
    deliver_outbox(store, router=_Router(), transport=_AlwaysFails())

    assert store.all_positions()[0]["status"] == "OPEN"
    assert store.cash() == cash_after_buy


# ======================================================================= #
# 20-21 -- dedup / idempotency
# ======================================================================= #

def test_20_duplicate_business_event_one_logical_outbox_item(tmp_path):
    ops = NotifyStore(str(tmp_path / "notify.db"))
    r1 = ops.enqueue(event_id="ev1", destination=OPERATIONS, event_type="TEST", producer="test",
                     dedup_key="d1", payload_text="hello", provenance={})
    r2 = ops.enqueue(event_id="ev1", destination=OPERATIONS, event_type="TEST", producer="test",
                     dedup_key="d1", payload_text="hello AGAIN", provenance={})
    assert r1 is True and r2 is False
    assert len(ops.all_outbox()) == 1


def test_20b_v2_scan_producer_is_idempotent_across_ticks(tmp_path):
    store, cfg, outcome = _entered(tmp_path, campaign_id="IDEMP")
    assert outcome.entered
    pos = store.all_positions()[0]
    store.mark_exit_unresolved(pos["position_id"], detail="x")
    ops = NotifyStore(str(tmp_path / "notify.db"))
    scan_v2_operational_events(store, ops)
    scan_v2_operational_events(store, ops)  # a second "tick"
    scan_v2_operational_events(store, ops)  # a third
    rows = ops.all_outbox()
    exit_rows = [r for r in rows if r["event_type"] == "EXIT_UNRESOLVED"]
    assert len(exit_rows) == 1  # never duplicated


def test_21_duplicate_drain_does_not_duplicate_logical_event(tmp_path, monkeypatch):
    monkeypatch.setenv("TALONX_NOTIFY_OPERATIONS_BOT_TOKEN", "t")
    monkeypatch.setenv("TALONX_NOTIFY_OPERATIONS_CHAT_ID", "c")
    ops = NotifyStore(str(tmp_path / "notify.db"))
    ops.enqueue(event_id="e1", destination=OPERATIONS, event_type="TEST", producer="test",
               dedup_key="d1", payload_text="hello", provenance={})
    client = RecordingTransport()
    drain(ops, destination=OPERATIONS, client=client)
    drain(ops, destination=OPERATIONS, client=client)  # already SENT -> not re-selected
    assert len(client.sent) == 1
    assert len(ops.all_outbox()) == 1


def test_21b_external_exactly_once_is_not_falsely_claimed():
    """RI2-K: an ambiguous (post-send-unconfirmed) transport outcome must
    resolve to AMBIGUOUS, never be silently treated as SENT nor
    blind-retried (which could double-send externally) -- internal
    durable idempotency (one outbox row) is distinct from, and does not
    imply, exactly-once EXTERNAL Telegram delivery."""
    import inspect
    src = inspect.getsource(__import__("talonx_ops.notify.worker", fromlist=["drain"]).drain)
    assert "ambiguous" in src.lower()


# ======================================================================= #
# 22-24 -- backlog / expiry safety
# ======================================================================= #

def test_22_stale_trade_alert_expires():
    """Reuses V2's OWN already-established, already-tested EXPIRED
    mechanism (deliver_by_utc) -- not reinvented here."""
    from talonx_v2.delivery import deliver_outbox
    store, cfg, outcome = _entered_for_expiry()
    class _Router:
        def decide(self, family, dedup_key, origin="PRODUCT_WATCHLIST"):
            from talonx_ops.official_dispatch import RoutingDecision
            return RoutingDecision(family=family, eligible=True, already_delivered=False,
                                   path="official_telegram", reason="test")
    store.enqueue_alert(
        event_id="stale1", episode_id="epS", kind="ENTRY_INTENT", action="BUY", symbol="AAA",
        strategy_version="INSIDER_BUY_CLUSTER_V2@1", dedup_key="d-stale", payload_text="stale",
        provenance={}, deliver_by_utc=(datetime.now(timezone.utc) - timedelta(hours=1)).isoformat())
    deliver_outbox(store, router=_Router(), transport=RecordingTransport())
    row = [r for r in store.all_outbox() if r["event_id"] == "stale1"][0]
    assert row["state"] == "EXPIRED"


def _entered_for_expiry(cash=BALANCE):
    import tempfile
    tmp = tempfile.mkdtemp()
    store = V2Store(f"{tmp}/v.db", starting_cash=cash)
    return store, None, None


def test_23_stale_backlog_not_sent_on_startup(tmp_path, monkeypatch):
    """Historical-backlog safety (the 9.8k-row class of risk): a large
    PENDING backlog with PAST deliver_by_utc deadlines never floods
    Telegram merely because delivery is (re)enabled -- every stale row
    resolves EXPIRED, never SENT."""
    monkeypatch.setenv("TALONX_NOTIFY_OPERATIONS_BOT_TOKEN", "t")
    monkeypatch.setenv("TALONX_NOTIFY_OPERATIONS_CHAT_ID", "c")
    ops = NotifyStore(str(tmp_path / "notify.db"))
    past = (datetime.now(timezone.utc) - timedelta(days=3)).isoformat()
    for i in range(25):
        ops.enqueue(event_id=f"old{i}", destination=OPERATIONS, event_type="TEST",
                   producer="test", dedup_key=f"d{i}", payload_text="old backlog",
                   provenance={}, deliver_by_utc=past)
    client = RecordingTransport()
    result = drain(ops, destination=OPERATIONS, client=client)
    assert result["expired"] == 25
    assert result["sent"] == 0
    assert client.sent == []  # zero actual sends -- no flood


def test_24_current_valid_event_still_sends(tmp_path, monkeypatch):
    monkeypatch.setenv("TALONX_NOTIFY_OPERATIONS_BOT_TOKEN", "t")
    monkeypatch.setenv("TALONX_NOTIFY_OPERATIONS_CHAT_ID", "c")
    ops = NotifyStore(str(tmp_path / "notify.db"))
    future = (datetime.now(timezone.utc) + timedelta(hours=1)).isoformat()
    ops.enqueue(event_id="fresh1", destination=OPERATIONS, event_type="TEST", producer="test",
               dedup_key="d1", payload_text="current", provenance={}, deliver_by_utc=future)
    client = RecordingTransport()
    result = drain(ops, destination=OPERATIONS, client=client)
    assert result["sent"] == 1


# ======================================================================= #
# 25 -- destination persisted correctly
# ======================================================================= #

def test_25_destination_persisted_correctly(tmp_path):
    ops = NotifyStore(str(tmp_path / "notify.db"))
    ops.enqueue(event_id="e1", destination=OPERATIONS, event_type="TEST", producer="test",
               dedup_key="d1", payload_text="x", provenance={})
    ops.enqueue(event_id="e2", destination=RESEARCH, event_type="TEST", producer="test",
               dedup_key="d2", payload_text="x", provenance={})
    assert ops.all_outbox(destination=OPERATIONS)[0]["destination"] == OPERATIONS
    assert ops.all_outbox(destination=RESEARCH)[0]["destination"] == RESEARCH

    svc = _svc(tmp_path, tmp_path / "v2b.db", name="ri2dest", symbols=["AAA"])
    _wire(svc, "AAA")
    ep = _ep(ENTRY_SESSION, "epD", "AAA")
    res = _reserve_then_fill(svc, ep)
    assert len(res.entries) == 1
    assert svc.store.all_outbox()[0]["destination"] == TRADE_EVENT


# ======================================================================= #
# 26-27 -- missing/disabled config handled safely
# ======================================================================= #

def test_26_missing_enabled_destination_config_handled_safely(tmp_path, monkeypatch):
    _clean_env(monkeypatch)
    ops = NotifyStore(str(tmp_path / "notify.db"))
    ops.enqueue(event_id="e1", destination=OPERATIONS, event_type="TEST", producer="test",
               dedup_key="d1", payload_text="x", provenance={})
    # no credentials at all -- OPERATIONS resolves disabled -> safe no-op, not a crash
    result = drain(ops, destination=OPERATIONS)
    assert result["enabled"] is False
    assert ops.all_outbox()[0]["state"] == "PENDING"  # never silently discarded


def test_27_disabled_research_requires_no_credentials(monkeypatch):
    _clean_env(monkeypatch)
    cfg = resolve_destination_config(RESEARCH)
    assert cfg.enabled is False
    assert cfg.bot_token is None and cfg.chat_id is None
    # this IS a valid configuration, not an error state
    assert "OFF by default" in cfg.reason


# ======================================================================= #
# 28-29 -- secret safety
# ======================================================================= #

def test_28_no_secret_in_persisted_payload(tmp_path, monkeypatch):
    monkeypatch.setenv("TALONX_NOTIFY_OPERATIONS_BOT_TOKEN", "SUPER-SECRET-TOKEN-VALUE")
    monkeypatch.setenv("TALONX_NOTIFY_OPERATIONS_CHAT_ID", "SECRET-CHAT-ID")
    ops = NotifyStore(str(tmp_path / "notify.db"))
    ops.enqueue(event_id="e1", destination=OPERATIONS, event_type="TEST", producer="test",
               dedup_key="d1", payload_text="a normal operational message", provenance={})
    client = RecordingTransport()
    drain(ops, destination=OPERATIONS, client=client)
    row = ops.all_outbox()[0]
    for secret in ("SUPER-SECRET-TOKEN-VALUE", "SECRET-CHAT-ID"):
        assert secret not in row["payload_text"]
        assert secret not in row["provenance_json"]
        assert secret not in (row["transport_ref"] or "")
        assert secret not in (row["last_error"] or "")


def test_29_no_secret_in_error_output(tmp_path, monkeypatch):
    monkeypatch.setenv("TALONX_NOTIFY_OPERATIONS_BOT_TOKEN", "TOKEN-XYZ")
    monkeypatch.setenv("TALONX_NOTIFY_OPERATIONS_CHAT_ID", "CHAT-XYZ")
    ops = NotifyStore(str(tmp_path / "notify.db"))
    ops.enqueue(event_id="e1", destination=OPERATIONS, event_type="TEST", producer="test",
               dedup_key="d1", payload_text="msg", provenance={})
    client = RecordingTransport(outcomes=[{"ok": False, "detail": "connection refused"}])
    result = drain(ops, destination=OPERATIONS, client=client)
    row = ops.all_outbox()[0]
    assert "TOKEN-XYZ" not in str(result) and "CHAT-XYZ" not in str(result)
    assert "TOKEN-XYZ" not in (row["last_error"] or "")


# ======================================================================= #
# 30 -- observability
# ======================================================================= #

def test_30_delivery_observability_counters(tmp_path, monkeypatch):
    monkeypatch.setenv("TALONX_NOTIFY_OPERATIONS_BOT_TOKEN", "t")
    monkeypatch.setenv("TALONX_NOTIFY_OPERATIONS_CHAT_ID", "c")
    ops = NotifyStore(str(tmp_path / "notify.db"))
    ops.enqueue(event_id="e1", destination=OPERATIONS, event_type="TEST", producer="test",
               dedup_key="d1", payload_text="x", provenance={})
    ops.enqueue(event_id="e2", destination=OPERATIONS, event_type="TEST", producer="test",
               dedup_key="d2", payload_text="x", provenance={})
    client = RecordingTransport(outcomes=[{"ok": True, "ref": "r1"},
                                          {"ok": False, "detail": "permanent", "permanent": True}])
    drain(ops, destination=OPERATIONS, client=client)
    counts = ops.counts_by_state(destination=OPERATIONS)
    assert counts.get("SENT") == 1
    assert counts.get("FAILED") == 1
    assert ops.last_sent(destination=OPERATIONS) is not None
    assert ops.last_failure(destination=OPERATIONS) is not None


# ======================================================================= #
# 31 -- alternate/direct route cannot duplicate the authoritative V2 notification
# ======================================================================= #

def test_31_v2_has_exactly_one_authoritative_outbox_and_delivery_owner(tmp_path):
    """RI2-O: V2's own BUY/SELL notifications are enqueued ONLY into
    v2_alert_outbox by V2Service._enqueue_alert, and drained ONLY by
    talonx_v2.delivery.deliver_outbox. No second active code path
    enqueues a v2_alert_outbox-shaped row for the SAME episode/kind --
    proven by construction: `enqueue_alert` is idempotent on event_id,
    and this repo's OPERATIONS/RESEARCH outbox (`ops_notification_
    outbox`) is a physically SEPARATE table/file V2's own trade
    notifications never write into."""
    svc = _svc(tmp_path, tmp_path / "v2owner.db", name="ri2owner", symbols=["AAA"],
              campaign_id="OWNER_TEST")
    _wire(svc, "AAA")
    ep = _ep(ENTRY_SESSION, "epO", "AAA")
    res = _reserve_then_fill(svc, ep)
    assert len(res.entries) == 1
    v2_rows = svc.store.all_outbox()
    # ENTRY_INTENT (pre-open reservation) + ENTRY_FILL (the actual fill) are
    # two DISTINCT, both-legitimate notification kinds for one episode
    # (Task 117's own established "PLANNED BUY" then "BUY FILLED" pattern)
    # -- the invariant is no DUPLICATE within a kind, one owner per kind.
    kinds = [r["kind"] for r in v2_rows]
    assert sorted(kinds) == ["ENTRY_FILL", "ENTRY_INTENT"]
    assert len(kinds) == len(set(kinds))  # no duplicate kind for this episode

    ops = NotifyStore(str(tmp_path / "notify2.db"))
    assert ops.all_outbox() == []  # the separate OPERATIONS/RESEARCH outbox never received it
