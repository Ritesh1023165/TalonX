"""
Task 117 controlled-deployment-readiness -- ledger migration & recovery.

The additive tables `pending_entry_intents` / `v2_alert_outbox` (+ the
`deliver_by_utc` column) are created by V2Store._init on first open.  These
tests use a CONSISTENT ISOLATED COPY of the real production ledger and prove the
migration is safe, idempotent and recoverable, and that a historical episode in
the store does NOT produce a fresh actionable alert.

The production ledger is NEVER opened here -- only shutil.copy2 copies of it.
"""
from __future__ import annotations

import hashlib
import shutil
import sqlite3
from datetime import date
from pathlib import Path

import pytest

from talonx_v2.config import V2Config
from talonx_v2.form4_source import from_rows
from talonx_v2.service import V2Service
from talonx_v2.store import V2Store

PROD_LEDGER = Path(__file__).resolve().parents[1] / "v2_lane.db"
# The Task 117 controlled activation applied the additive migration to the live
# ledger (verified logical continuity). These isolated-copy tests now run against
# the ALREADY-MIGRATED ledger: the additive tables exist and re-opening a
# V2Store is a clean no-op. Pre-migration hash was c09c6a88188e65fd987b54f672a9759e.
_PRE_MIGRATION_MD5 = "c09c6a88188e65fd987b54f672a9759e"
_POST_MIGRATION_MD5 = "29e57dbcd1a567fbc4bb0e73efdba95f"
EXPECTED_MD5 = {_PRE_MIGRATION_MD5, _POST_MIGRATION_MD5}

pytestmark = pytest.mark.skipif(not PROD_LEDGER.exists(), reason="no production v2_lane.db")


def _md5(p: Path) -> str:
    return hashlib.md5(p.read_bytes()).hexdigest()


def _iso_copy(tmp_path) -> Path:
    dst = tmp_path / "v2_lane.db"
    shutil.copy2(PROD_LEDGER, dst)
    assert _md5(dst) in EXPECTED_MD5, "isolated copy must match a known production hash"
    return dst


def _already_migrated(db: Path) -> bool:
    return {"pending_entry_intents", "v2_alert_outbox"}.issubset(set(_logical(db)["tables"]))


def _logical(db: Path) -> dict:
    con = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
    con.row_factory = sqlite3.Row
    try:
        out = {
            "cash": con.execute("SELECT cash FROM portfolio WHERE id=1").fetchone()[0],
            "positions": con.execute("SELECT COUNT(*) FROM positions").fetchone()[0],
            "trades": con.execute("SELECT COUNT(*) FROM trades").fetchone()[0],
            "dispositions": sorted(
                (r[0], r[1]) for r in con.execute(
                    "SELECT episode_id, disposition FROM processed_episodes")),
            "tables": sorted(r[0] for r in con.execute(
                "SELECT name FROM sqlite_master WHERE type='table'")),
        }
    finally:
        con.close()
    return out


def test_migration_preserves_all_existing_state(tmp_path):
    db = _iso_copy(tmp_path)
    before = _logical(db)
    assert before["cash"] == 300000.0
    assert before["positions"] == 0 and before["trades"] == 0
    assert before["dispositions"] == [("07242bc857569f60", "SKIPPED_ENTRY_STALE")]
    if not _already_migrated(db):
        assert "pending_entry_intents" not in before["tables"]
        assert "v2_alert_outbox" not in before["tables"]

    # migrate (or, on the already-migrated ledger, a clean no-op): opening a
    # V2Store runs the additive CREATE TABLE IF NOT EXISTS + ALTER
    V2Store(str(db), starting_cash=300000.0)
    after = _logical(db)
    assert after["cash"] == 300000.0
    assert after["positions"] == 0 and after["trades"] == 0
    assert after["dispositions"] == before["dispositions"]         # ABCL stale preserved
    assert "pending_entry_intents" in after["tables"]
    assert "v2_alert_outbox" in after["tables"]
    # new tables are empty
    con = sqlite3.connect(str(db))
    assert con.execute("SELECT COUNT(*) FROM pending_entry_intents").fetchone()[0] == 0
    assert con.execute("SELECT COUNT(*) FROM v2_alert_outbox").fetchone()[0] == 0
    cols = {r[1] for r in con.execute("PRAGMA table_info(v2_alert_outbox)")}
    assert "deliver_by_utc" in cols
    con.close()


def test_migration_is_idempotent_across_restarts(tmp_path):
    db = _iso_copy(tmp_path)
    for _ in range(4):                                     # simulate repeated service (re)starts
        V2Store(str(db), starting_cash=300000.0)
    a = _logical(db)
    assert a["cash"] == 300000.0 and a["positions"] == 0 and a["trades"] == 0
    assert a["dispositions"] == [("07242bc857569f60", "SKIPPED_ENTRY_STALE")]


def test_alter_migration_on_a_preexisting_outbox_without_the_new_column(tmp_path):
    db = _iso_copy(tmp_path)
    # forge a legacy outbox table (no deliver_by_utc)
    con = sqlite3.connect(str(db))
    con.executescript("""
        DROP TABLE IF EXISTS v2_alert_outbox;
        CREATE TABLE v2_alert_outbox (
          event_id TEXT PRIMARY KEY, episode_id TEXT NOT NULL, intent_id TEXT,
          position_id INTEGER, kind TEXT NOT NULL, action TEXT NOT NULL, symbol TEXT NOT NULL,
          strategy_version TEXT NOT NULL, horizon_trading_days INTEGER, dedup_key TEXT NOT NULL,
          payload_text TEXT NOT NULL, provenance_json TEXT NOT NULL, state TEXT NOT NULL,
          attempts INTEGER NOT NULL DEFAULT 0, next_attempt_utc TEXT, last_error TEXT,
          transport_ref TEXT, created_at_utc TEXT NOT NULL, updated_at_utc TEXT NOT NULL,
          sent_at_utc TEXT);
        INSERT INTO v2_alert_outbox (event_id, episode_id, kind, action, symbol,
          strategy_version, dedup_key, payload_text, provenance_json, state, created_at_utc,
          updated_at_utc) VALUES ('legacy1','ep','ENTRY_FILL','BUY','AAA','v','k','x','{}',
          'SENT','2026-01-01T00:00:00Z','2026-01-01T00:00:00Z');
    """)
    con.commit(); con.close()
    V2Store(str(db), starting_cash=300000.0)               # must ALTER, not fail
    con = sqlite3.connect(str(db))
    cols = {r[1] for r in con.execute("PRAGMA table_info(v2_alert_outbox)")}
    assert "deliver_by_utc" in cols
    row = con.execute("SELECT state, deliver_by_utc FROM v2_alert_outbox WHERE event_id='legacy1'").fetchone()
    assert row[0] == "SENT" and row[1] is None             # legacy row preserved, new col NULL
    con.close()


def test_historical_episode_in_store_makes_no_fresh_actionable_alert(tmp_path, monkeypatch):
    db = _iso_copy(tmp_path)
    bd = tmp_path / "bars"; bd.mkdir()
    # an OLD ABCL-style cluster: eligible entry ~2026-07 -> stale by 2026-09-10
    old_rows = from_rows([
        {"symbol": "ABCL", "issuer_cik": "0001703057", "owner_cik": "o1",
         "filing_date": "2026-07-06", "accession": "z1", "transaction_code": "P",
         "transaction_value": 500000},
        {"symbol": "ABCL", "issuer_cik": "0001703057", "owner_cik": "o2",
         "filing_date": "2026-07-07", "accession": "z2", "transaction_code": "P",
         "transaction_value": 500000},
    ])

    class _S:
        def query_transactions(self, **_):
            return []
    import talonx_ingest.intelligence.insider.store as _st
    monkeypatch.setattr(_st, "InsiderStore", lambda *a, **k: _S())

    class _RT:
        name = "rec"
        sent = []
        def send(self, payload_text, *, meta):
            self.sent.append(meta); return {"ok": True, "ref": "rec-1"}
    from talonx_ops.official_dispatch import OfficialExternalRouter
    rt = _RT()
    cfg = V2Config(db_path=str(db), starting_cash_usd=300000.0)
    svc = V2Service(config=cfg, bar_dirs=[bd], form4_kind="parquet",
                    status_path=str(tmp_path / "s.json"),
                    router=OfficialExternalRouter(home=tmp_path), transport=rt, deliver=True)
    svc._records = lambda *, as_of: old_rows

    st = svc.tick(as_of=date(2026, 9, 10))
    assert st["entries_this_tick"] == 0
    assert st["entry_intents_created_this_tick"] == 0          # stale -> NO pre-open intent
    s = V2Store(str(db), starting_cash=300000.0)
    kinds = [o["kind"] for o in s.all_outbox()]
    assert "ENTRY_INTENT" not in kinds                         # NO fresh actionable BUY alert
    assert all(o["action"] != "BUY" or o["kind"] == "ENTRY_STALE" for o in s.all_outbox())
    # ledger untouched
    assert _logical(db)["cash"] == 300000.0
    assert _logical(db)["trades"] == 0


def test_interrupted_tick_leaves_a_consistent_recoverable_ledger(tmp_path, monkeypatch):
    db = _iso_copy(tmp_path)
    bd = tmp_path / "bars"; bd.mkdir()
    from talonx_v2 import calendar as vc
    import csv
    with open(bd / "AAA.csv", "w", newline="") as f:
        w = csv.writer(f); w.writerow(["date", "open", "close", "volume"])
        for ssn in vc._sessions():
            if date(2026, 6, 1) <= ssn <= date(2026, 8, 20):
                w.writerow([ssn.isoformat(), 40, 40.5, 2_000_000])
    rows = from_rows([
        {"symbol": "AAA", "issuer_cik": "AAA_CIK", "owner_cik": "o1",
         "filing_date": "2026-08-14", "accession": "a1", "transaction_code": "P",
         "transaction_value": 300000},
        {"symbol": "AAA", "issuer_cik": "AAA_CIK", "owner_cik": "o2",
         "filing_date": "2026-08-14", "accession": "a2", "transaction_code": "P",
         "transaction_value": 300000},
    ])
    cfg = V2Config(db_path=str(db), starting_cash_usd=300000.0)
    svc = V2Service(config=cfg, bar_dirs=[bd], form4_kind="parquet",
                    status_path=str(tmp_path / "s.json"))
    svc._records = lambda *, as_of: rows

    # first tick opens the position normally
    svc.tick(as_of=date(2026, 8, 17))
    svc.tick(as_of=date(2026, 8, 18))
    s = V2Store(str(db), starting_cash=300000.0)
    assert s.n_open() == 1
    open_cost = s.all_positions()[0]["position_cost"]

    # now a tick that BLOWS UP mid-settle -- the per-episode/settle guards catch it
    monkeypatch.setattr("talonx_v2.pipeline.settle_due_exits",
                        lambda **k: (_ for _ in ()).throw(RuntimeError("boom")))
    svc.tick(as_of=date(2026, 8, 31))                      # exception is caught, tick returns

    # RESTART -> a fresh store recovers the still-open position; ledger equation holds
    s2 = V2Store(str(db), starting_cash=300000.0)
    assert s2.n_open() == 1
    cash = s2.cash()
    buys = sum(1 for t in s2.trades() if t["action"] == "BUY")
    sells = sum(1 for t in s2.trades() if t["action"] == "SELL")
    assert buys == sells + s2.n_open() + len(s2.unresolved_positions())
    assert abs((cash + open_cost) - (300000.0 + 0.0)) < 1.0
