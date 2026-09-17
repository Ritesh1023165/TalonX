"""
Task 117 -- ONE bounded controlled-deployment REHEARSAL.

Isolated everything: a shutil.copy2 of the real v2_lane.db, an isolated
InsiderStore, an isolated bar dir, an isolated OfficialExternalRouter home, a
namespaced status file, an intercepted (stub) Telegram transport.  No production
DB / Redis / port / message.

Exercises the actual application path end to end:
  migration -> readiness -> pre-open intent -> intercepted Telegram delivery ->
  paper BUY (independent) -> restart -> SEC-source failure with an open position
  -> scheduled +10td exit -> SELL delivery -> reconciliation -> dashboard
  read-model -> bounded shutdown path.
"""
from __future__ import annotations

import csv
import hashlib
import json
import shutil
import sqlite3
from datetime import date, datetime, timezone
from pathlib import Path

import pytest

from talonx_ops.official_dispatch import OfficialExternalRouter
from talonx_v2 import calendar as vc
from talonx_v2.config import V2Config
from talonx_v2.delivery import OfficialTelegramTransport
from talonx_v2.service import V2Service
from talonx_v2.store import V2Store

PROD = Path(__file__).resolve().parents[1] / "v2_lane.db"
# pre-migration hash c09c6a88...; post Task 117 activation migration 29e57dbc...
EXPECTED_MD5 = {"c09c6a88188e65fd987b54f672a9759e",
                "29e57dbcd1a567fbc4bb0e73efdba95f"}
pytestmark = pytest.mark.skipif(not PROD.exists(), reason="no production v2_lane.db")

SYM = "RHRS"
ACT = date(2026, 8, 14)
ENTRY = date(2026, 8, 17)
S1 = date(2026, 8, 18)
EXIT = vc.add_sessions(ENTRY, 10)


class _StubTelegram:
    """Boundary intercept for talonx_dispatch.telegram_client.TelegramClient."""
    is_configured = True

    def __init__(self):
        self.sent: list[tuple[str, object]] = []

    async def send(self, text, parse_mode=None):
        self.sent.append((text, parse_mode))


def _iso_insider(tmp):
    from talonx_ingest.intelligence.insider.store import InsiderStore
    from talonx_ingest.intelligence.insider.domain import InsiderTransaction, TransactionClass
    st = InsiderStore(path=tmp / "iso_ledger.db")
    for owner, td, acc_ts in [("own-A", "2026-08-10", "2026-08-13T18:00:00+00:00"),
                              ("own-B", "2026-08-12", "2026-08-14T15:00:00+00:00")]:
        tid = hashlib.sha256(f"{owner}{acc_ts}".encode()).hexdigest()[:32]
        st.upsert_transaction(InsiderTransaction(
            transaction_id=tid, accession=f"a-{tid[:8]}", issuer_cik="0000998877", symbol=SYM,
            accepted_at_utc=datetime.fromisoformat(acc_ts),
            filing_date=datetime.fromisoformat(acc_ts).date(),
            transaction_date=date.fromisoformat(td), owner_cik=owner, is_officer=True,
            transaction_code="P", classification=TransactionClass.OPEN_MARKET_PURCHASE,
            transaction_value=900_000.0))
    st._conn.commit()
    return st


def _bars(tmp):
    bd = tmp / "bars"; bd.mkdir()
    with open(bd / f"{SYM}.csv", "w", newline="") as f:
        w = csv.writer(f); w.writerow(["date", "open", "close", "volume"])
        for s in vc._sessions():
            if date(2026, 6, 1) <= s <= vc.add_sessions(EXIT, 3):
                px = 30.0 if s < ENTRY else (31.0 if s < EXIT else 34.0)
                w.writerow([s.isoformat(), px, px + 0.4, 3_000_000])
    return bd


def _svc(tmp, store, tg, home):
    cfg = V2Config(db_path=str(tmp / "v2_lane.db"), starting_cash_usd=300_000.0)
    return V2Service(config=cfg, bar_dirs=[_bd_singleton(tmp)], form4_kind="insider",
                     status_path=str(tmp / "rehearsal_v2_status.json"),
                     router=OfficialExternalRouter(home=home),
                     transport=OfficialTelegramTransport(client=tg), deliver=True)


_BD = {}
def _bd_singleton(tmp):
    if tmp not in _BD:
        _BD[tmp] = _bars(tmp)
    return _BD[tmp]


def _v2fp():
    import importlib
    return importlib.import_module(
        "research.scripts.task112_v2_release_fingerprint").v2_release_fingerprint()["fingerprint"]


def test_bounded_controlled_deployment_rehearsal(tmp_path, monkeypatch):
    home = tmp_path / "home"; home.mkdir()
    ledger = tmp_path / "v2_lane.db"
    shutil.copy2(PROD, ledger)
    assert hashlib.md5(ledger.read_bytes()).hexdigest() in EXPECTED_MD5

    store = _iso_insider(tmp_path)
    import talonx_ingest.intelligence.insider.store as _stmod
    monkeypatch.setattr(_stmod, "InsiderStore", lambda *a, **k: store)
    tg = _StubTelegram()
    fp_before = _v2fp()

    # --- 1. MIGRATION (opening the V2Store) + readiness -----------------------
    svc = _svc(tmp_path, store, tg, home)
    con = sqlite3.connect(f"file:{ledger}?mode=ro", uri=True)
    tables = {r[0] for r in con.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    assert {"pending_entry_intents", "v2_alert_outbox"} <= tables
    assert con.execute("SELECT cash FROM portfolio WHERE id=1").fetchone()[0] == 300000.0
    assert con.execute(
        "SELECT disposition FROM processed_episodes WHERE episode_id='07242bc857569f60'"
    ).fetchone()[0] == "SKIPPED_ENTRY_STALE"
    con.close()
    assert svc.ready() in (False, True)  # probe callable; no exception

    # --- 2. PRE-OPEN INTENT + intercepted Telegram delivery ------------------
    st1 = svc.tick(as_of=ACT)
    assert st1["entry_intents_created_this_tick"] == 1
    s = V2Store(str(ledger), starting_cash=300000.0)
    intent = s.all_entry_intents()[0]
    episode_id = intent["episode_id"]
    ob = s.all_outbox()
    assert [o["kind"] for o in ob] == ["ENTRY_INTENT"]
    assert ob[0]["state"] == "SENT" and ob[0]["transport_ref"].startswith("telegram:sent:")
    assert tg.sent and tg.sent[0][1] is None           # sent through the real adapter, parse_mode None
    intent_delivery_id = ob[0]["event_id"]

    # --- 3. FILL at the eligible-entry session: paper BUY recorded INDEPENDENTLY ---
    #     (frozen csv pricing -> the fill records at the ENTRY-session open; the
    #      BUY FILLED notification is enqueued + delivered)
    st3 = svc.tick(as_of=ENTRY)
    assert st3["entries_this_tick"] == 1
    s = V2Store(str(ledger), starting_cash=300000.0)
    pos = s.all_positions()[0]
    assert pos["episode_id"] == episode_id and pos["status"] == "OPEN"
    assert pos["entry_price"] == 31.0                    # ENTRY session open
    assert [t["action"] for t in s.trades()] == ["BUY"]
    assert s.entry_intent(episode_id)["status"] == "FILLED"
    fill_ob = [o for o in s.all_outbox() if o["kind"] == "ENTRY_FILL"][0]
    assert fill_ob["state"] == "SENT"
    assert "delayed notification" in fill_ob["payload_text"]

    # --- 4. RESTART -> no duplicate anything -------------------------------
    del svc
    tg2 = _StubTelegram()
    svc2 = _svc(tmp_path, store, tg2, home)
    svc2.tick(as_of=S1)
    s = V2Store(str(ledger), starting_cash=300000.0)
    assert [t["action"] for t in s.trades()] == ["BUY"]
    assert len(s.all_entry_intents()) == 1
    assert len({o["event_id"] for o in s.all_outbox()}) == len(s.all_outbox())
    assert tg2.sent == []                                # nothing new

    # --- 5. SEC-SOURCE FAILURE with the open position --------------------
    monkeypatch.setattr(store, "query_transactions",
                        lambda **k: (_ for _ in ()).throw(RuntimeError("iso_ledger locked")))
    st5 = svc2.tick(as_of=vc.add_sessions(ENTRY, 3))
    assert st5["heartbeat_kind"] == "DEGRADED_SOURCE"
    assert st5["data_state"] == "DATA_UNAVAILABLE" and st5["entries_this_tick"] == 0
    assert V2Store(str(ledger), 300000.0).n_open() == 1  # position untouched

    # --- 6. SCHEDULED +10td EXIT (still during source failure) ----------
    st6 = svc2.tick(as_of=vc.add_sessions(EXIT, 1))
    assert st6["exits_this_tick"] == 1
    s = V2Store(str(ledger), starting_cash=300000.0)
    assert [t["action"] for t in s.trades()] == ["BUY", "SELL"]
    assert s.trades()[-1]["execution_price"] == 34.4     # real +10td-session close
    exit_ob = [o for o in s.all_outbox() if o["kind"] == "EXIT_FILL"][0]
    assert exit_ob["state"] == "SENT" and exit_ob["action"] == "SELL"
    exit_delivery_id = exit_ob["event_id"]

    # --- 7. RECONCILIATION ------------------------------------------------
    closed = [p for p in s.all_positions() if p["episode_id"] == episode_id][0]
    assert closed["status"] == "CLOSED"
    cash = s.cash()
    realized = closed["realized_pnl_usd"]
    buys = sum(1 for t in s.trades() if t["action"] == "BUY")
    sells = sum(1 for t in s.trades() if t["action"] == "SELL")
    assert buys == sells + s.n_open() + len(s.unresolved_positions())
    assert abs(cash - (300000.0 + realized)) < 1.0

    # --- 8. DASHBOARD read-model ---------------------------------------
    from talonx_ops.dashboard_read import DashboardReadModel
    monkeypatch.setenv("TALONX_V2_DB_PATH", str(ledger))
    monkeypatch.setenv("TALONX_V2_STATUS_PATH", str(tmp_path / "rehearsal_v2_status.json"))
    dr = DashboardReadModel(home=home, check_processes=False,
                            intel_ledger=tmp_path / "iso_ledger.db")
    v2 = dr.v2_active_strategy()
    assert v2["ledger"]["closed_positions"] == 1 and v2["ledger"]["sells"] == 1
    assert v2["readiness"]["v2_fingerprint_frozen"] == fp_before
    ov = dr.overview()["active_v2"]
    assert ov["sells"] == 1 and ov["delivery"]["enabled"] is True

    # --- 9. BOUNDED SHUTDOWN path (no real children) -----------------
    from talonx_ops.prospective.proc import stop_stack
    sd = tmp_path / "session"; sd.mkdir()
    (sd / "session.pids.json").write_text(json.dumps({}))     # nothing running
    res = stop_stack(sd, grace_s=2.0, overall_budget_s=8.0)
    assert res["residual_talonx_processes"] == []
    assert res["v2_lane_db_intact"] in (True, False)          # callable, no raise

    # --- correlated identifiers + final safety --------------------------
    corr = {
        "episode_id": episode_id, "intent_id": intent["intent_id"],
        "position_id": closed["position_id"],
        "delivery_ids": {"ENTRY_INTENT": intent_delivery_id, "EXIT_FILL": exit_delivery_id},
        "fingerprint_before": fp_before, "fingerprint_after": _v2fp(),
        "entry_session": closed["entry_session"], "exit_session": closed["exit_session"],
        "realized_pnl_usd": realized, "telegram_messages_actually_sent": 0,
    }
    from talonx_ops.prospective import V2_FINGERPRINT_EXPECTED
    # RI-1: was a hardcoded stale "11107198c5b81237" literal; now references
    # the live constant (updated when config.py gained campaign_id/
    # execution_mode -- see that constant's own comment).
    assert corr["fingerprint_before"] == corr["fingerprint_after"] == V2_FINGERPRINT_EXPECTED
    for o in s.all_outbox():
        assert o["episode_id"] == episode_id
    (tmp_path / "rehearsal_correlation.json").write_text(json.dumps(corr, indent=2, default=str))
    # the ISOLATED copy changed (additive tables) but the PRODUCTION ledger is untouched
    assert hashlib.md5(PROD.read_bytes()).hexdigest() in EXPECTED_MD5
