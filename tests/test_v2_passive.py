"""V2 passive record (owner decision 2026-11-20): INSIDER_BUY_CLUSTER_V2@1 is a passive, read-only descriptive record.

V2 must never send a Telegram/Signal message -- no BUY/SELL alert and no V2-produced OPERATIONS notification -- whatever
flags the companion is started with (the release start still passes ``--deliver --transport telegram``). The companion
keeps running and keeps draining the SHARED OPERATIONS outbox for other components. No real Telegram send anywhere."""
from __future__ import annotations

from datetime import date

from talonx_ops.notify import OPERATIONS
from talonx_ops.notify.outbox import NotifyStore
from talonx_v2 import passive
from talonx_v2.config import V2Config
from talonx_v2.delivery import RecordingTransport
from talonx_v2.service import V2Service
from talonx_v2.store import V2Store

BALANCE = 300_000.0
TODAY = date(2026, 9, 8)


class _Router:
    """Would route every family to the official Telegram path -- passive must still send nothing."""

    def decide(self, family, dedup_key, origin="PRODUCT_WATCHLIST"):
        from talonx_ops.official_dispatch import RoutingDecision
        return RoutingDecision(family=family, eligible=True, already_delivered=False,
                               path="official_telegram", reason="test")


def _store(tmp_path):
    return V2Store(str(tmp_path / "v2.db"), starting_cash=BALANCE, campaign_id="PASSIVE_TEST")


def _buy_alert(store, n=1):
    for i in range(n):
        store.enqueue_alert(event_id=f"ev{i}", episode_id=f"ep{i}", kind="ENTRY_FILL", action="BUY",
                            symbol="ABCL", strategy_version="INSIDER_BUY_CLUSTER_V2@1",
                            dedup_key=f"ep{i}:BUY:ENTRY_FILL", payload_text="⚡ BUY — ABCL (fixture)",
                            provenance={"fixture": True}, horizon_trading_days=10)


def _no_records(svc):
    """No Form 4 source needed here (the research parquet lives in gitignored results/): an empty record set."""
    svc._records = lambda as_of=None: []
    return svc


def _svc(tmp_path, *, transport, ops=None):
    cfg = V2Config(db_path=str(tmp_path / "v2.db"), starting_cash_usd=BALANCE, campaign_id="PASSIVE_TEST")
    return _no_records(V2Service(config=cfg, bar_dirs=[tmp_path / "bars"], router=_Router(), transport=transport,
                                 deliver=True, ops_notify_store=ops))


def _ops_client(monkeypatch):
    client = RecordingTransport()
    monkeypatch.setattr("talonx_ops.notify.worker.telegram_client_for", lambda dest: client)
    monkeypatch.setenv("TALONX_NOTIFY_OPERATIONS_BOT_TOKEN", "t")
    monkeypatch.setenv("TALONX_NOTIFY_OPERATIONS_CHAT_ID", "c")
    return client


def test_v2_is_passive_by_owner_decision():
    assert passive.V2_PASSIVE is True
    assert passive.SUPPRESS_REASON.startswith("SUPPRESSED_V2_PASSIVE")


def test_v2_cannot_send_a_trade_alert_even_with_deliver_and_a_telegram_router(tmp_path, monkeypatch):
    store = _store(tmp_path)
    _buy_alert(store, n=2)
    _ops_client(monkeypatch)
    trade = RecordingTransport()
    _svc(tmp_path, transport=trade, ops=NotifyStore(str(tmp_path / "notify.db"))).tick(as_of=TODAY)
    assert trade.sent == []                                        # nothing reached the transport
    rows = store.all_outbox()
    assert [r["state"] for r in rows] == ["EXPIRED", "EXPIRED"]    # terminal: can never be sent later
    assert all(r["last_error"].startswith("SUPPRESSED_V2_PASSIVE") for r in rows)
    assert all(r["sent_at_utc"] is None for r in rows)


def test_suppression_is_terminal_across_restart_and_later_ticks(tmp_path, monkeypatch):
    store = _store(tmp_path)
    _buy_alert(store)
    _ops_client(monkeypatch)
    trade = RecordingTransport()
    for _ in range(2):                                            # a fresh service = a companion restart
        _svc(tmp_path, transport=trade).tick(as_of=TODAY)
    assert trade.sent == [] and store.all_outbox()[0]["state"] == "EXPIRED"


def test_already_sent_rows_are_never_touched(tmp_path, monkeypatch):
    store = _store(tmp_path)
    _buy_alert(store)
    store.update_outbox("ev0", state="SENT", attempts=1, transport_ref="telegram:sent:x", sent=True)
    _ops_client(monkeypatch)
    _svc(tmp_path, transport=RecordingTransport()).tick(as_of=TODAY)
    row = store.all_outbox()[0]
    assert row["state"] == "SENT" and row["transport_ref"] == "telegram:sent:x" and row["last_error"] is None


def test_v2_produces_no_operations_notification(tmp_path, monkeypatch):
    store = _store(tmp_path)
    pos = store.insert_open_position(episode_id="epW", symbol="AAA", issuer_cik="x", entry_session=TODAY,
                                     target_exit_session=date(2026, 9, 22), entry_price=100.0, shares=10,
                                     position_cost=1000.0)
    store.mark_exit_unresolved(pos, detail="test")                 # would produce EXIT_UNRESOLVED when active
    ops = NotifyStore(str(tmp_path / "notify.db"))
    client = _ops_client(monkeypatch)
    svc = _svc(tmp_path, transport=RecordingTransport(), ops=ops)
    svc._resolver = type("R", (), {"last": {"AAA": object()}, "disagreements": [],      # an unresolved price: would
                                   "adapter": type("A", (), {"name": "stub"})()})()     # trigger v2 DEGRADED_HEALTH
    svc.tick(as_of=TODAY)
    v2_rows = [r for r in ops.all_outbox(destination=OPERATIONS) if r["producer"] != "intelligence"]
    assert v2_rows == [] and client.sent == []


def test_control_same_setup_with_passive_off_would_have_notified(tmp_path, monkeypatch):
    """Negative control: proves the passive tests above are not vacuous."""
    monkeypatch.setattr("talonx_v2.service.V2_PASSIVE", False)
    store = _store(tmp_path)
    _buy_alert(store)
    pos = store.insert_open_position(episode_id="epW", symbol="AAA", issuer_cik="x", entry_session=TODAY,
                                     target_exit_session=date(2026, 9, 22), entry_price=100.0, shares=10,
                                     position_cost=1000.0)
    store.mark_exit_unresolved(pos, detail="test")
    ops = NotifyStore(str(tmp_path / "notify.db"))
    _ops_client(monkeypatch)
    trade = RecordingTransport()
    svc = _svc(tmp_path, transport=trade, ops=ops)
    svc._resolver = type("R", (), {"last": {"AAA": object()}, "disagreements": [],
                                   "adapter": type("A", (), {"name": "stub"})()})()
    svc.tick(as_of=TODAY)
    produced = {r["event_type"] for r in ops.all_outbox(destination=OPERATIONS) if r["producer"] != "intelligence"}
    assert {"EXIT_UNRESOLVED", "DEGRADED_HEALTH"} <= produced
    assert len(trade.sent) == 1                                    # the BUY alert would have been sent


def test_shared_operations_drain_still_delivers_other_components(tmp_path, monkeypatch):
    from talonx_ops.notify.producers import enqueue_degraded_health
    ops = NotifyStore(str(tmp_path / "notify.db"))
    enqueue_degraded_health(ops, component="intelligence", condition="POLL_ERRORS")
    client = _ops_client(monkeypatch)
    _store(tmp_path)
    _svc(tmp_path, transport=RecordingTransport(), ops=ops).tick(as_of=TODAY)
    sent = [r for r in ops.all_outbox(destination=OPERATIONS) if r["state"] == "SENT"]
    assert [r["producer"] for r in sent] == ["intelligence"] and len(client.sent) == 1


def test_status_reports_passive_and_no_delivery(tmp_path, monkeypatch):
    import json
    _store(tmp_path)
    _ops_client(monkeypatch)
    cfg = V2Config(db_path=str(tmp_path / "v2.db"), starting_cash_usd=BALANCE, campaign_id="PASSIVE_TEST")
    svc = _no_records(V2Service(config=cfg, bar_dirs=[tmp_path / "bars"], router=_Router(),
                                transport=RecordingTransport(), deliver=True,
                                status_path=str(tmp_path / "status.json")))
    svc.tick(as_of=TODAY)
    st = json.loads((tmp_path / "status.json").read_text(encoding="utf-8"))
    assert st["v2_passive"] is True and st["delivery_enabled"] is False


def test_strategy_fingerprint_unchanged():
    """Passive lives outside V2Config, so the frozen strategy fingerprint the release gate checks is unchanged."""
    from research.scripts.task112_v2_release_fingerprint import v2_release_fingerprint
    from talonx_v2.release_gate import ReleaseProfile
    assert v2_release_fingerprint()["fingerprint"] == ReleaseProfile().strategy_fingerprint == "e2acf6454789217e"
