"""
Task 117 overnight P6 -- ONE complete isolated product-journey test.

timestamped filing -> InsiderStore -> V2Service -> cluster/eligibility ->
qualified decision -> official delivery (RecordingTransport at the boundary) ->
independently recorded paper outcome -> actual SPA read-model -> process restart
-> scheduled +10td exit -> SELL notification -> ledger reconciliation.

Plus: an interrupted-delivery/restart case and an open-position-source-failure
case.  Uses the REAL pricing / source / dispatch code -- clocks + data adapters
only, no rewritten strategy.  Fully isolated: temp InsiderStore, temp v2_lane.db,
temp dispatch_audit dir, RecordingTransport.  No production DB / Redis / send.
"""
from __future__ import annotations

import csv
import hashlib
import json
from datetime import date, datetime, time, timedelta, timezone
from pathlib import Path

import pytest

from talonx_ops.official_dispatch import OfficialExternalRouter
from talonx_v2 import calendar as vc
from talonx_v2.config import V2Config
from talonx_v2.delivery import RecordingTransport, deliver_outbox
from talonx_v2.service import V2Service, V2SourceError
from talonx_v2.store import V2Store

SYM = "JRNY"
ACT = date(2026, 8, 14)          # Fri: 2nd distinct insider's Form 4 disseminated
ENTRY = date(2026, 8, 17)        # Mon: eligible entry session (open)
EXIT = date(2026, 8, 31)        # +10 trading sessions


def _isolated_insider_store(tmp: Path):
    from talonx_ingest.intelligence.insider.store import InsiderStore
    from talonx_ingest.intelligence.insider.domain import InsiderTransaction, TransactionClass
    st = InsiderStore(path=tmp / "iso_ingestion_ledger.db")
    txns = []
    for i, (owner, tdate, acc, acc_ts) in enumerate([
        ("own-A", "2026-08-10", "0001234567-26-000111", "2026-08-13T18:05:00+00:00"),
        ("own-B", "2026-08-12", "0007654321-26-000222", "2026-08-14T15:20:00+00:00"),
    ]):
        tid = hashlib.sha256(f"{acc}|{owner}".encode()).hexdigest()[:32]
        st.upsert_transaction(InsiderTransaction(
            transaction_id=tid, accession=acc, issuer_cik="0000999888", symbol=SYM,
            accepted_at_utc=datetime.fromisoformat(acc_ts),
            filing_date=datetime.fromisoformat(acc_ts).date(),
            transaction_date=date.fromisoformat(tdate), owner_cik=owner,
            is_officer=True, transaction_code="P",
            classification=TransactionClass.OPEN_MARKET_PURCHASE, transaction_value=750_000.0))
    st._conn.commit()
    return st, ["0001234567-26-000111", "0007654321-26-000222"]


def _bars(tmp: Path):
    bd = tmp / "bars"
    bd.mkdir()
    sess = [s for s in vc._sessions() if date(2026, 6, 1) <= s <= EXIT]
    with open(bd / f"{SYM}.csv", "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["date", "open", "close", "volume"])
        for s in sess:
            px = 40.0 if s < ENTRY else (41.0 if s < EXIT else 44.0)
            w.writerow([s.isoformat(), px, px + 0.5, 1_500_000])
    return bd


def _svc(tmp, bd, store, *, transport, home, deliver=True):
    cfg = V2Config(db_path=str(tmp / "v2_lane.db"), starting_cash_usd=300_000.0)
    svc = V2Service(config=cfg, bar_dirs=[bd], form4_kind="insider",
                    status_path=str(tmp / "v2_service_status.json"),
                    router=OfficialExternalRouter(home=home), transport=transport,
                    deliver=deliver)
    import talonx_ingest.intelligence.insider.store as _st
    svc.__dict__["_iso_store"] = store
    return svc


def _v2fp() -> str:
    import importlib
    return importlib.import_module(
        "research.scripts.task112_v2_release_fingerprint").v2_release_fingerprint()["fingerprint"]


def test_p6_full_isolated_product_journey(tmp_path, monkeypatch):
    home = tmp_path / "home"
    home.mkdir()
    store, accessions = _isolated_insider_store(tmp_path)
    bd = _bars(tmp_path)
    import talonx_ingest.intelligence.insider.store as _stmod
    monkeypatch.setattr(_stmod, "InsiderStore", lambda *a, **k: store)

    rt = RecordingTransport()
    fp_before = _v2fp()
    svc = _svc(tmp_path, bd, store, transport=rt, home=home)

    # 1) intent tick -- day the cluster is public, entry session still in the future
    st1 = svc.tick(as_of=ACT)
    assert st1["entry_intents_created_this_tick"] == 1
    s = V2Store(str(tmp_path / "v2_lane.db"), starting_cash=300_000.0)
    intent = s.all_entry_intents()[0]
    episode_id = intent["episode_id"]
    assert intent["status"] == "PENDING"
    ob1 = s.all_outbox()
    assert [o["kind"] for o in ob1] == ["ENTRY_INTENT"]
    assert ob1[0]["state"] == "SENT" and ob1[0]["transport_ref"].startswith("rec-")
    delivery_id_intent = ob1[0]["event_id"]

    # 2) entry-session tick -- FINAL open observed, paper BUY recorded, fill delivered
    st2 = svc.tick(as_of=ENTRY)
    assert st2["entries_this_tick"] == 1
    s = V2Store(str(tmp_path / "v2_lane.db"), starting_cash=300_000.0)
    pos = s.all_positions()[0]
    assert pos["episode_id"] == episode_id and pos["status"] == "OPEN"
    assert pos["entry_session"] == ENTRY.isoformat() and pos["entry_price"] == 41.0  # ENTRY open
    intent = s.entry_intent(episode_id)
    assert intent["status"] == "FILLED" and intent["filled_position_id"] == pos["position_id"]
    fill_ob = [o for o in s.all_outbox() if o["kind"] == "ENTRY_FILL"][0]
    assert fill_ob["state"] == "SENT"
    prov = json.loads(fill_ob["provenance_json"])
    assert prov["intent_id"] == intent["intent_id"]
    # BUY paper trade recorded independently of the notification
    assert [t["action"] for t in s.trades()] == ["BUY"]

    # 3) actual SPA read-model shows the position + the delivery
    from talonx_ops.dashboard_read import DashboardReadModel
    monkeypatch.setenv("TALONX_V2_DB_PATH", str(tmp_path / "v2_lane.db"))
    monkeypatch.setenv("TALONX_V2_STATUS_PATH", str(tmp_path / "v2_service_status.json"))
    dr = DashboardReadModel(home=home, check_processes=False,
                            intel_ledger=tmp_path / "iso_ingestion_ledger.db")
    v2 = dr.v2_active_strategy()
    assert v2["ledger"]["n_open"] == 1
    assert v2["readiness"]["v2_fingerprint_frozen"] == fp_before
    assert v2["funnel"]["delivery"]["sent"] >= 2
    assert any(i["episode_id"] == episode_id
               for i in (v2["funnel"]["intents"]["pending"] + []))\
        or v2["funnel"]["intents"]["by_status"].get("FILLED", 0) >= 1

    # 4) PROCESS RESTART -- brand-new service instance, same durable stores
    del svc
    rt2 = RecordingTransport()
    svc2 = _svc(tmp_path, bd, store, transport=rt2, home=home)
    svc2.tick(as_of=date(2026, 8, 18))          # a normal tick after restart
    s = V2Store(str(tmp_path / "v2_lane.db"), starting_cash=300_000.0)
    assert [t["action"] for t in s.trades()] == ["BUY"]          # no duplicate BUY
    assert len(s.all_entry_intents()) == 1                        # no duplicate intent
    assert rt2.sent == []                                         # nothing new to deliver

    # 5) scheduled +10td exit -- SELL at the EXIT session close, delivered
    st3 = svc2.tick(as_of=EXIT)
    assert st3["exits_this_tick"] == 1
    s = V2Store(str(tmp_path / "v2_lane.db"), starting_cash=300_000.0)
    assert [t["action"] for t in s.trades()] == ["BUY", "SELL"]
    sell = s.trades()[-1]
    assert sell["execution_price"] == 44.5                        # EXIT session close
    exit_ob = [o for o in s.all_outbox() if o["kind"] == "EXIT_FILL"][0]
    assert exit_ob["state"] == "SENT" and exit_ob["action"] == "SELL"
    delivery_id_exit = exit_ob["event_id"]

    # 6) reconciliation -- ledger equations
    pos = [p for p in s.all_positions() if p["episode_id"] == episode_id][0]
    assert pos["status"] == "CLOSED"
    cash = s.cash()
    realized = pos["realized_pnl_usd"]
    buys = sum(1 for t in s.trades() if t["action"] == "BUY")
    sells = sum(1 for t in s.trades() if t["action"] == "SELL")
    n_open = s.n_open()
    n_unres = len(s.unresolved_positions())
    assert buys == sells + n_open + n_unres
    assert abs((cash + 0.0) - (300_000.0 + realized)) < 1.0      # flat -> cash == start + realized

    # 7) CORRELATED IDENTIFIERS
    corr = {
        "accessions": accessions,
        "episode_id": episode_id,
        "intent_id": intent["intent_id"],
        "position_id": pos["position_id"],
        "delivery_ids": {"ENTRY_INTENT": delivery_id_intent, "EXIT_FILL": delivery_id_exit},
        "strategy_fingerprint_before": fp_before,
        "strategy_fingerprint_after": _v2fp(),
        "entry_session": pos["entry_session"], "exit_session": pos["exit_session"],
        "realized_pnl_usd": realized,
        "spa_n_open_at_hold": 1,
        "external_messages_sent": 0,   # RecordingTransport is not a network
    }
    assert corr["strategy_fingerprint_before"] == corr["strategy_fingerprint_after"] == "11107198c5b81237"
    # every outbox row for this episode links back to it
    for o in s.all_outbox():
        assert o["episode_id"] == episode_id
        assert json.loads(o["provenance_json"])["episode_id"] == episode_id
    Path(tmp_path / "journey_correlation.json").write_text(json.dumps(corr, indent=2, default=str))


def test_p6_interrupted_delivery_survives_restart(tmp_path, monkeypatch):
    home = tmp_path / "home"; home.mkdir()
    store, _ = _isolated_insider_store(tmp_path)
    bd = _bars(tmp_path)
    import talonx_ingest.intelligence.insider.store as _stmod
    monkeypatch.setattr(_stmod, "InsiderStore", lambda *a, **k: store)

    # ENTRY_INTENT delivers on the ACT tick; force the transport to RAISE on the
    # ENTRY_FILL send (a notification -- no deadline) so RETRY-survives-restart is
    # the pure property under test.
    rt = RecordingTransport(outcomes=[{"ok": True, "ref": "rec-intent"},
                                      {"raise": True, "detail": "telegram 502"}])
    svc = _svc(tmp_path, bd, store, transport=rt, home=home)
    svc.tick(as_of=ACT)                                 # ENTRY_INTENT -> SENT
    svc.tick(as_of=ENTRY)                               # ENTRY_FILL send RAISES -> RETRY
    s = V2Store(str(tmp_path / "v2_lane.db"), starting_cash=300_000.0)
    fill = [o for o in s.all_outbox() if o["kind"] == "ENTRY_FILL"][0]
    assert fill["state"] == "RETRY" and fill["attempts"] == 1 and fill["next_attempt_utc"]
    assert [t["action"] for t in s.trades()] == ["BUY"]     # paper outcome independent of delivery

    # RESTART -> a fresh store + drain later; the pending fill notification is still there
    del svc
    s2 = V2Store(str(tmp_path / "v2_lane.db"), starting_cash=300_000.0)
    assert [o for o in s2.all_outbox() if o["kind"] == "ENTRY_FILL"][0]["state"] == "RETRY"
    summ = deliver_outbox(s2, router=OfficialExternalRouter(home=home),
                          transport=RecordingTransport(),
                          now=datetime.now(timezone.utc) + timedelta(seconds=600))
    assert summ["sent"] == 1
    assert [o for o in V2Store(str(tmp_path / "v2_lane.db"), 300_000.0).all_outbox()
            if o["kind"] == "ENTRY_FILL"][0]["state"] == "SENT"


def test_p6_open_position_source_failure_still_exits(tmp_path, monkeypatch):
    home = tmp_path / "home"; home.mkdir()
    store, _ = _isolated_insider_store(tmp_path)
    bd = _bars(tmp_path)
    import talonx_ingest.intelligence.insider.store as _stmod

    raising = {"v": False}
    real_query = store.query_transactions

    def _q(**kw):
        if raising["v"]:
            raise RuntimeError("iso ingestion_ledger.db locked")
        return real_query(**kw)
    store.query_transactions = _q
    monkeypatch.setattr(_stmod, "InsiderStore", lambda *a, **k: store)

    svc = _svc(tmp_path, bd, store, transport=RecordingTransport(), home=home)
    svc.tick(as_of=ACT)
    svc.tick(as_of=ENTRY)                               # position OPEN
    assert V2Store(str(tmp_path / "v2_lane.db"), 300_000.0).n_open() == 1

    raising["v"] = True                                 # SEC source now fails
    st = svc.tick(as_of=EXIT)
    assert st["heartbeat_kind"] == "DEGRADED_SOURCE"
    assert st["data_state"] == "DATA_UNAVAILABLE"
    assert st["entries_this_tick"] == 0
    s = V2Store(str(tmp_path / "v2_lane.db"), starting_cash=300_000.0)
    assert s.n_open() == 0                              # the +10td exit STILL happened
    assert [t["action"] for t in s.trades()] == ["BUY", "SELL"]
    assert s.trades()[-1]["execution_price"] == 44.5   # the real EXIT close, not invented
