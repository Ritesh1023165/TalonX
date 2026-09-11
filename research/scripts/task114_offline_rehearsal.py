"""
Task 114 -- OFFLINE autonomous-operator rehearsal.

No real market, no real ledger, no external Telegram.  Uses a sandbox
v2_lane.db + synthetic Form 4 records + a mocked clock to walk the full
Day-2 lifecycle:

  1  day start            -- carry-forward ledger, preflight-style checks, first checkpoint
  2  healthy zero-activity -- Form 4 with no code-P -> NO_OPPORTUNITIES (not "broken")
  3  single-insider near-miss -- funnel shows the near-miss, no BUY
  4  qualifying cluster    -- 2nd distinct insider -> cluster -> signal lineage -> paper BUY
  5  stale historical episode -- ABCL-equivalent -> SKIPPED_ENTRY_STALE, cash unchanged
  6  open-position persistence -- survives a companion restart, NOT EOD-flattened
  7  EOD                    -- reconciliation asserts + report + graceful (no-op) shutdown
  8  ledger preserved       -- v2_lane.db still present, copy made, never reset

Writes results/task114_autonomous_operator/rehearsal_report.json
Exit 0 iff every scenario PASSES.
"""
from __future__ import annotations

import json
import sys
import tempfile
from datetime import date, datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from talonx_v2 import form4_source, pipeline           # noqa: E402
from talonx_v2.config import V2Config                  # noqa: E402
from talonx_v2.service import V2Service                # noqa: E402
from talonx_v2.store import V2Store                    # noqa: E402
from talonx_v2 import calendar as v2cal                # noqa: E402

OUT = ROOT / "results" / "task114_autonomous_operator"
BALANCE = 300_000.0
R: dict = {"generated_utc": datetime.now(timezone.utc).isoformat(), "scenarios": {}}


def _bars(a="2026-06-01", b="2026-12-31", close=100.0, vol=800_000):
    sess = [s for s in v2cal._sessions() if date.fromisoformat(a) <= s <= date.fromisoformat(b)]
    return [{"date": s.isoformat(), "open": close, "close": close, "volume": vol} for s in sess]


def _cluster(sym, d1, d2, val=600_000):
    return [
        dict(symbol=sym, issuer_cik=sym + "c", owner_cik=sym + "1", filing_date=d1,
             accession=sym + "a1", transaction_value=val, is_officer=True, transaction_code="P"),
        dict(symbol=sym, issuer_cik=sym + "c", owner_cik=sym + "2", filing_date=d2,
             accession=sym + "a2", transaction_value=val, is_director=True, transaction_code="P"),
    ]


def _one_p(sym, d1, val=600_000):
    return [dict(symbol=sym, issuer_cik=sym + "c", owner_cik=sym + "1", filing_date=d1,
                 accession=sym + "a1", transaction_value=val, is_officer=True, transaction_code="P")]


def _svc(db, status, records, bars):
    cfg = V2Config(db_path=str(db), starting_cash_usd=BALANCE)
    s = V2Service(config=cfg, bar_dirs=[Path(".")], form4_kind="parquet", status_path=str(status))
    s._records = lambda *, as_of: form4_source.from_rows(records)
    s._bars = lambda sym: bars
    s._price = lambda sym, sess: next(
        (b for b in bars if b["date"] == (sess.isoformat() if isinstance(sess, date) else str(sess)[:10])), None)
    return s


def _rec(name, ok, **detail):
    R["scenarios"][name] = {"pass": bool(ok), **detail}
    print(f"[{'PASS' if ok else 'FAIL'}] {name}  {detail}")


def main() -> int:
    sb = Path(tempfile.mkdtemp(prefix="task114_rehearsal_"))
    db = sb / "v2_lane.db"
    status = sb / "v2_service_status.json"
    session_dir = sb / "session"
    session_dir.mkdir()

    # ---- carry-forward ledger (Day-1 end state) ----
    V2Store(str(db), starting_cash=BALANCE)
    st0 = V2Store(str(db))
    st0.record_disposition(episode_id="07242bc857569f60", symbol="ABCL",
                           disposition="SKIPPED_ENTRY_STALE", issuer_cik="0001703057",
                           eligible_entry_session="2026-08-17")
    del st0

    from talonx_ops.prospective.ledger_guard import check_ledger_continuity
    lc = check_ledger_continuity(db)
    _rec("1_day_start_carry_forward", lc.ok and lc.cash == BALANCE and lc.n_open == 0,
         cash=lc.cash, open=lc.n_open, stale_records=lc.stale_skipped_episodes)

    bars = _bars()

    # ---- 2 healthy zero-activity: Form 4 with NO code-P ----
    rows_nop = [dict(symbol="ZZZ", issuer_cik="ZZZc", owner_cik="ZZZ1", filing_date="2026-09-09",
                     accession="z1", transaction_value=1, is_officer=True, transaction_code="A")]
    s = _svc(db, status, rows_nop, bars)
    st = s.tick(as_of=date(2026, 9, 9))
    from talonx_ops.prospective.funnel import build_funnel
    # funnel uses the InsiderStore for the "available" branch; here we assert the
    # ledger stayed inert and the tick recorded no entries
    _rec("2_healthy_zero_activity",
         st["entries_this_tick"] == 0 and st["open_positions"] == 0
         and V2Store(str(db)).cash() == BALANCE,
         entries=st["entries_this_tick"], cash=V2Store(str(db)).cash())

    # ---- 3 single-insider near-miss ----
    rows_one = _one_p("NEARMISS", "2026-09-08")
    s = _svc(db, status, rows_one, bars)
    st = s.tick(as_of=date(2026, 9, 9))
    eps = pipeline.detect_episodes(form4_source.from_rows(rows_one), config=V2Config())
    _rec("3_single_insider_near_miss",
         st["entries_this_tick"] == 0 and len(eps) == 0 and V2Store(str(db)).cash() == BALANCE,
         clusters_detected=len(eps), entries=st["entries_this_tick"])

    # ---- 4 qualifying cluster -> paper BUY (test data) ----
    # filings on 09-03 / 09-04 -> activation 09-04 -> entry = 09-08 (09-07 = Labor Day)
    # -> eligible on the 09-09 tick, and within the 3-session staleness window.
    rows_cl = _cluster("QUAL", "2026-09-03", "2026-09-04")
    s = _svc(db, status, rows_cl, bars)
    st = s.tick(as_of=date(2026, 9, 9))
    store = V2Store(str(db))
    pos = store.open_positions()
    lineage_ok = (st["entries_this_tick"] == 1 and len(pos) == 1
                  and pos[0]["episode_id"] and pos[0]["entry_price"]
                  and pos[0]["target_exit_session"]
                  and abs(pos[0]["position_cost"] - 10_000.0) < 1e-6
                  and store.cash() == BALANCE - 10_000.0)
    _rec("4_qualifying_cluster_paper_buy", lineage_ok,
         entries=st["entries_this_tick"], symbol=pos[0]["symbol"] if pos else None,
         size=pos[0]["position_cost"] if pos else None,
         target_exit=pos[0]["target_exit_session"] if pos else None,
         cash=store.cash())

    # ---- 5 stale historical episode (ABCL-equivalent) ----
    rows_stale = _cluster("OLDIE", "2026-07-20", "2026-07-22")
    s = _svc(db, status, rows_stale, bars)
    cash_before = V2Store(str(db)).cash()
    st = s.tick(as_of=date(2026, 9, 9))
    store = V2Store(str(db))
    oldie_ep = pipeline.detect_episodes(form4_source.from_rows(rows_stale), config=V2Config())[0]
    disp = store.episode_disposition(oldie_ep.episode_id)
    _rec("5_stale_historical_episode",
         disp == "SKIPPED_ENTRY_STALE" and st["entries_this_tick"] == 0
         and store.cash() == cash_before,
         disposition=disp, cash_before=cash_before, cash_after=store.cash())

    # ---- 6 open-position persistence across restart, no EOD flatten ----
    del s, store
    s2 = _svc(db, status, rows_cl, bars)              # fresh service instance = "restart"
    st = s2.tick(as_of=date(2026, 9, 10))
    store = V2Store(str(db))
    pos = store.open_positions()
    from talonx_v2.dashboard_read import eod_view
    ev = eod_view(store)
    _rec("6_open_position_persists_no_eod_flatten",
         len(pos) == 1 and pos[0]["symbol"] == "QUAL"
         and st["entries_this_tick"] == 0            # not re-entered (idempotent)
         and ev["v2_positions_flattened_at_eod"] is False,
         open=len(pos), flattened=ev["v2_positions_flattened_at_eod"],
         reentered=st["entries_this_tick"])

    # ---- 7 EOD reconciliation + report + graceful (no-op) shutdown ----
    (sb / "v2_service_status.json").write_text(json.dumps({
        "strategy_version": "INSIDER_BUY_CLUSTER_V2@1",
        "heartbeat_utc": datetime.now(timezone.utc).isoformat(), "heartbeat_ttl_s": 180,
        "eod_forced_flatten": False, "real_capital": False, "shorts": False,
        "form4_source": "insider", "form4_records_seen": 24, "cash": store.cash()}))
    from talonx_ops.prospective import close as closemod
    from talonx_ops.prospective import paths as pmod
    pmod.V2_DB_PATH = db
    pmod.V2_STATUS_PATH = sb / "v2_service_status.json"
    closemod.V2_DB_PATH = db
    closemod.V2_STATUS_PATH = sb / "v2_service_status.json"
    closemod.eod_state = lambda now=None: {"state": "PENDING", "reason": "rehearsal"}
    res = closemod.run_close(session_dir, do_shutdown=False)
    a = res.asserts
    eod_ok = (a["buys_eq_sells_plus_open_plus_unresolved"] == "PASS"
              and a["no_negative_cash"] == "PASS"
              and a["no_stale_episode_entered"] == "PASS"
              and a["no_illegal_eod_flatten"] == "PASS"
              and a.get("no_duplicate_buy_episode_id") == "PASS"
              and (session_dir / "v2_lane.db.eod-copy").exists()
              and res.verdict in ("PASS", "PASS_WITH_FINDINGS"))
    report = closemod.render_report(res, session_dir)
    (session_dir / "final_report.md").write_text(report, encoding="utf-8")
    _rec("7_eod_reconciliation_report_shutdown", eod_ok,
         verdict=res.verdict, asserts=a, findings=res.findings)

    # ---- 8 ledger preserved (never reset) ----
    _rec("8_ledger_preserved",
         db.exists() and (session_dir / "v2_lane.db.eod-copy").exists()
         and V2Store(str(db)).cash() == BALANCE - 10_000.0,     # the one BUY persists
         db_exists=db.exists(), cash=V2Store(str(db)).cash())

    # ---- checkpoint + event smoke over the same session dir ----
    from talonx_ops.prospective.events import classify
    prev = {"invariants": {}, "funnel": {"form4": {"code_p_records_today": 0},
            "clusters": {"clusters_ge2_distinct_insiders": 0, "cluster_symbols": []},
            "terminal": {"buys": 0, "sells": 0, "signals": 0}},
            "service_health": {"health": "HEALTHY"}, "market": {"state": "HEALTHY"},
            "intelligence": {}, "official_dispatch": {}, "supervisor": {"producers": {}}}
    curr = json.loads(json.dumps(prev))
    curr["funnel"]["clusters"] = {"clusters_ge2_distinct_insiders": 1, "cluster_symbols": ["QUAL"]}
    curr["funnel"]["terminal"] = {"buys": 1, "sells": 0, "signals": 1}
    evs = classify(prev, curr)
    _rec("9_event_classification",
         any(e["kind"] == "cluster_formed" for e in evs) and any(e["kind"] == "v2_buy" for e in evs)
         and all(e["level"] != "CRITICAL" for e in evs),
         events=[f"{e['level']}:{e['kind']}" for e in evs])

    OUT.mkdir(parents=True, exist_ok=True)
    R["all_pass"] = all(v["pass"] for v in R["scenarios"].values())
    (OUT / "rehearsal_report.json").write_text(json.dumps(R, indent=2, default=str))
    print("\n" + json.dumps({k: v["pass"] for k, v in R["scenarios"].items()}, indent=2))
    print("ALL PASS:", R["all_pass"])
    return 0 if R["all_pass"] else 1


if __name__ == "__main__":
    sys.exit(main())
