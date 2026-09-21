"""
Task 117 overnight -- product-journey closure: pre-open intent, official delivery,
exit during source failure, and one full isolated end-to-end journey.

All isolated: temp v2_lane.db, injected RecordingTransport at the final network
boundary, a stub router (or the real OfficialExternalRouter with an isolated
home).  No production DB / Redis / external message.
"""
from __future__ import annotations

import csv
import json
from datetime import date
from pathlib import Path

import pytest

from talonx_v2 import calendar as vc
from talonx_v2.config import V2Config
from talonx_v2.delivery import RecordingTransport, deliver_outbox
from talonx_v2.form4_source import from_rows
from talonx_v2.service import V2Service
from talonx_v2.store import V2Store

ACT_FRI = date(2026, 8, 14)
ENTRY_MON = date(2026, 8, 17)
EXIT_10TD = date(2026, 8, 31)


class _StubRouter:
    """Compatible with OfficialExternalRouter.decide(family, dedup_key)."""

    def __init__(self, *, delivered: set[str] | None = None, eligible: bool = True):
        self._delivered = delivered or set()
        self._eligible = eligible

    def decide(self, family, dedup_key=""):
        class _RD:
            pass
        rd = _RD()
        rd.family = family
        rd.eligible = self._eligible and family == "insider_buy_cluster_v2"
        rd.already_delivered = dedup_key in self._delivered
        rd.reason = ("eligible" if rd.eligible else "not eligible")
        return rd


def _bars(tmp: Path, sym="AAA", *, entry_bar=True, post=()):
    bd = tmp / "bars"
    bd.mkdir(exist_ok=True)
    sess = [s for s in vc._sessions() if date(2026, 6, 1) <= s < ENTRY_MON]
    with open(bd / f"{sym}.csv", "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["date", "open", "close", "volume"])
        for s in sess:
            w.writerow([s.isoformat(), 100, 100, 1_000_000])
        if entry_bar:
            w.writerow([ENTRY_MON.isoformat(), 101, 102, 900_000])
        for d, o, c, v in post:
            w.writerow([d, o, c, v])
    return bd


def _rows(sym="AAA", act=ACT_FRI):
    return [
        {"symbol": sym, "issuer_cik": sym + "_CIK", "owner_cik": "o1",
         "filing_date": act.isoformat(), "accession": "a1", "transaction_value": 200000,
         "transaction_code": "P"},
        {"symbol": sym, "issuer_cik": sym + "_CIK", "owner_cik": "o2",
         "filing_date": act.isoformat(), "accession": "a2", "transaction_value": 200000,
         "transaction_code": "P"},
    ]


def _svc(tmp, bd, *, router=None, transport=None, deliver=False, kind="parquet"):
    cfg = V2Config(db_path=str(tmp / "v.db"), starting_cash_usd=300_000.0)
    svc = V2Service(config=cfg, bar_dirs=[bd], form4_kind=kind,
                    status_path=str(tmp / "s.json"), router=router, transport=transport,
                    deliver=deliver)
    return svc


# --------------------------------------------------------------------------- P1
def test_p1_preopen_intent_created_before_entry_session(tmp_path):
    svc = _svc(tmp_path, _bars(tmp_path))
    svc._records = lambda *, as_of: from_rows(_rows())
    st = svc.tick(as_of=ACT_FRI)                       # entry Mon is in the future
    assert st["entry_intents_created_this_tick"] == 1
    intents = V2Store(str(tmp_path / "v.db"), starting_cash=300_000.0).all_entry_intents()
    assert len(intents) == 1
    i = intents[0]
    assert i["status"] == "PENDING"
    assert i["target_entry_session"] == ENTRY_MON.isoformat()
    # created on a tick whose as_of (Fri) is strictly BEFORE the entry session (Mon),
    # and no position exists yet -> the alert is actionable when emitted
    assert ACT_FRI.isoformat() < i["target_entry_session"]
    assert V2Store(str(tmp_path / "v.db"), 300_000.0).all_positions() == []
    ob = [r for r in V2Store(str(tmp_path / "v.db"), starting_cash=300_000.0).all_outbox()]
    assert [r["kind"] for r in ob] == ["ENTRY_INTENT"]
    assert "PLANNED BUY" in ob[0]["payload_text"] and "ACTIONABLE" in ob[0]["payload_text"]


def test_p1_fill_reconciles_to_intent_at_entry_session_open(tmp_path):
    svc = _svc(tmp_path, _bars(tmp_path))
    svc._records = lambda *, as_of: from_rows(_rows())
    svc.tick(as_of=ACT_FRI)
    st = svc.tick(as_of=ENTRY_MON)
    # Package 4 whole-share sizing: floor($10,000 / $101) = 99 shares = $9,999 (pre-Package-4 this expected a fractional $10,000)
    assert st["entries_this_tick"] == 1 and st["cash"] == 290_001.0
    s = V2Store(str(tmp_path / "v.db"), starting_cash=300_000.0)
    i = s.all_entry_intents()[0]
    assert i["status"] == "FILLED"
    assert i["fill_price"] == 101.0 and i["fill_entry_session"] == ENTRY_MON.isoformat()
    assert i["filled_position_id"] == s.all_positions()[0]["position_id"]
    kinds = [r["kind"] for r in s.all_outbox()]
    assert kinds == ["ENTRY_INTENT", "ENTRY_FILL"]
    fill = [r for r in s.all_outbox() if r["kind"] == "ENTRY_FILL"][0]
    assert "delayed notification of a previously-recorded paper intent" in fill["payload_text"]
    prov = json.loads(fill["provenance_json"])
    assert prov["intent_id"] == i["intent_id"] and prov["intent_created_at_utc"]


def test_p1_same_session_first_tick_defers_never_enters_cold(tmp_path, monkeypatch):
    # Task 131 Final Remediation Directive 4: this test specifically
    # exercises the GATED (ON) admission policy -- explicit, local
    # opt-in (V2Service's own runtime default is OFF).
    monkeypatch.setenv("TALONX_V2_DURABLE_STORE_ENABLED", "true")
    # Task 131 Directive 2: the first tick is ON the entry session itself --
    # no earlier tick ever existed to create a durable PENDING intent, so
    # the cold-start entry that Task 117 previously permitted (labelled
    # "cold-start backfill") is REFUSED this same tick: cash/capacity are
    # never touched without a reservation written to disk beforehand.
    # PHASE OPEN already ran (and refused) before PHASE POST-CLOSE gets a
    # chance to create a fresh intent for the NEXT tick -- so a durable
    # intent DOES appear by the end of this tick (never usable THIS tick,
    # by construction), and the entry actually resolves one tick later.
    svc = _svc(tmp_path, _bars(tmp_path))
    svc._records = lambda *, as_of: from_rows(_rows())
    st = svc.tick(as_of=ENTRY_MON)
    assert st["entries_this_tick"] == 0
    assert st["no_prior_intent_skipped_this_tick"] == 1
    s = V2Store(str(tmp_path / "v.db"), starting_cash=300_000.0)
    assert s.all_positions() == []
    assert s.cash() == 300_000.0
    intents = s.all_entry_intents()
    assert len(intents) == 1 and intents[0]["status"] == "PENDING"
    disp = [r[0] for r in __import__("sqlite3").connect(str(tmp_path / "v.db")).execute(
        "SELECT disposition FROM processed_episodes")]
    assert disp == []                       # not yet terminal -- the window is still open

    st2 = svc.tick(as_of=vc.add_sessions(ENTRY_MON, 1))
    assert st2["entries_this_tick"] == 1
    s = V2Store(str(tmp_path / "v.db"), starting_cash=300_000.0)
    assert s.n_open() == 1


def test_p1_late_first_tick_is_a_permanent_miss_not_a_stale_backfill(tmp_path, monkeypatch):
    # Task 131 Final Remediation Directive 4: this test specifically
    # exercises the GATED (ON) admission policy -- explicit, local
    # opt-in (V2Service's own runtime default is OFF).
    monkeypatch.setenv("TALONX_V2_DURABLE_STORE_ENABLED", "true")
    # the first tick arrives well AFTER the entry session -- the
    # intent-creation window (today <= eligible <= next_sess) has closed
    # too, so this is a genuine, permanent miss: no intent is ever
    # created, and NO later tick can resurrect it into a backfilled entry
    # at a since-stale price (Task 131 Directive 2).
    svc = _svc(tmp_path, _bars(tmp_path))
    svc._records = lambda *, as_of: from_rows(_rows())
    # 1 session late (well within max_entry_staleness_sessions=3, so this
    # exercises the "window closed, no intent ever existed" path
    # specifically -- not the separate, pre-existing staleness guard).
    late = vc.add_sessions(ENTRY_MON, 1)
    st = svc.tick(as_of=late)
    assert st["entries_this_tick"] == 0
    assert st["no_prior_intent_skipped_this_tick"] == 1
    s = V2Store(str(tmp_path / "v.db"), starting_cash=300_000.0)
    assert s.all_entry_intents() == []
    assert s.all_positions() == []
    assert s.cash() == 300_000.0
    disp = [r[0] for r in __import__("sqlite3").connect(str(tmp_path / "v.db")).execute(
        "SELECT disposition FROM processed_episodes")]
    assert disp == ["SKIPPED_NO_PRIOR_INTENT"]

    # a further later tick does not resurrect it
    st2 = svc.tick(as_of=vc.add_sessions(late, 1))
    assert st2["entries_this_tick"] == 0
    s = V2Store(str(tmp_path / "v.db"), starting_cash=300_000.0)
    assert s.all_positions() == [] and s.all_entry_intents() == []


def test_p1_a_timely_intent_still_fills_and_labels_delayed_notification(tmp_path):
    # the SAME episode, given a genuinely earlier tick to create its
    # durable PENDING intent first, fills normally -- confirming the new
    # gate only refuses the COLD-START case, not a legitimately admitted one.
    svc = _svc(tmp_path, _bars(tmp_path))
    svc._records = lambda *, as_of: from_rows(_rows())
    svc.tick(as_of=ACT_FRI)                     # creates the intent
    st = svc.tick(as_of=ENTRY_MON)               # resolves the entry
    assert st["entries_this_tick"] == 1
    s = V2Store(str(tmp_path / "v.db"), starting_cash=300_000.0)
    assert s.all_entry_intents()[0]["status"] == "FILLED"
    fill = [r for r in s.all_outbox() if r["kind"] == "ENTRY_FILL"][0]
    assert "delayed notification of a previously-recorded paper intent" in fill["payload_text"]


def test_p1_intent_expires_stale_without_a_fill(tmp_path):
    # entry bar missing -> never fills -> after staleness the intent EXPIRES
    svc = _svc(tmp_path, _bars(tmp_path, entry_bar=False))
    svc._records = lambda *, as_of: from_rows(_rows())
    svc.tick(as_of=ACT_FRI)                            # intent created
    assert V2Store(str(tmp_path / "v.db"), 300_000.0).all_entry_intents()[0]["status"] == "PENDING"
    svc.tick(as_of=date(2026, 8, 25))                  # ~6 sessions later -> stale
    s = V2Store(str(tmp_path / "v.db"), starting_cash=300_000.0)
    assert s.all_entry_intents()[0]["status"] == "EXPIRED_STALE"
    assert s.trades() == [] and s.cash() == 300_000.0
    assert any(r["kind"] == "ENTRY_STALE" for r in s.all_outbox())


def test_p1_restart_does_not_duplicate_intent_or_buy(tmp_path):
    bd = _bars(tmp_path)
    svc1 = _svc(tmp_path, bd)
    svc1._records = lambda *, as_of: from_rows(_rows())
    svc1.tick(as_of=ACT_FRI)
    del svc1
    svc2 = _svc(tmp_path, bd)                          # fresh instance, same db
    svc2._records = lambda *, as_of: from_rows(_rows())
    svc2.tick(as_of=ACT_FRI)                           # must NOT create a 2nd intent
    svc2.tick(as_of=ENTRY_MON)
    del svc2
    svc3 = _svc(tmp_path, bd)
    svc3._records = lambda *, as_of: from_rows(_rows())
    svc3.tick(as_of=ENTRY_MON)                         # must NOT create a 2nd BUY
    s = V2Store(str(tmp_path / "v.db"), starting_cash=300_000.0)
    assert len(s.all_entry_intents()) == 1
    assert [t["action"] for t in s.trades()] == ["BUY"]
    assert len({r["event_id"] for r in s.all_outbox()}) == len(s.all_outbox())  # no dup events


# --------------------------------------------------------------------------- P2
def test_p2_qualified_decision_reaches_recording_transport(tmp_path):
    rt = RecordingTransport()
    svc = _svc(tmp_path, _bars(tmp_path), router=_StubRouter(), transport=rt, deliver=True)
    svc._records = lambda *, as_of: from_rows(_rows())
    svc.tick(as_of=ACT_FRI)                            # ENTRY_INTENT enqueued + delivered
    svc.tick(as_of=ENTRY_MON)                          # ENTRY_FILL enqueued + delivered
    s = V2Store(str(tmp_path / "v.db"), starting_cash=300_000.0)
    ob = s.all_outbox()
    assert {r["state"] for r in ob} == {"SENT"}
    assert all(r["transport_ref"].startswith("rec-") for r in ob)
    assert all(r["sent_at_utc"] for r in ob)
    kinds_sent = [json.loads(x["meta"]["provenance"])["kind"] for x in rt.sent]
    assert "ENTRY_INTENT" in kinds_sent and "ENTRY_FILL" in kinds_sent


def test_p2_buy_and_sell_are_distinct_deliveries(tmp_path):
    rt = RecordingTransport()
    bd = _bars(tmp_path, post=[("2026-08-18", 102, 102, 9e5), ("2026-08-19", 102, 102, 9e5),
                               ("2026-08-20", 102, 102, 9e5), ("2026-08-21", 102, 102, 9e5),
                               ("2026-08-24", 102, 102, 9e5), ("2026-08-25", 102, 102, 9e5),
                               ("2026-08-26", 102, 102, 9e5), ("2026-08-27", 102, 102, 9e5),
                               ("2026-08-28", 102, 102, 9e5), ("2026-08-31", 102, 110, 9e5)])
    svc = _svc(tmp_path, bd, router=_StubRouter(), transport=rt, deliver=True)
    svc._records = lambda *, as_of: from_rows(_rows())
    svc.tick(as_of=ACT_FRI)
    svc.tick(as_of=ENTRY_MON)
    svc.tick(as_of=EXIT_10TD)                          # +10td -> SELL
    s = V2Store(str(tmp_path / "v.db"), starting_cash=300_000.0)
    ob = s.all_outbox()
    actions = {r["kind"]: r["action"] for r in ob}
    assert actions["ENTRY_FILL"] == "BUY" and actions["EXIT_FILL"] == "SELL"
    dedups = {r["dedup_key"] for r in ob}
    assert f"{list({r['episode_id'] for r in ob})[0]}:BUY:ENTRY_FILL" in dedups
    assert any(d.endswith(":SELL:EXIT_FILL") for d in dedups)
    assert [t["action"] for t in s.trades()] == ["BUY", "SELL"]


def test_p2_transient_failure_retries_then_succeeds(tmp_path):
    s = V2Store(str(tmp_path / "v.db"), starting_cash=300_000.0)
    s.enqueue_alert(event_id="e1", episode_id="ep", kind="ENTRY_INTENT", action="BUY",
                    symbol="AAA", strategy_version="INSIDER_BUY_CLUSTER_V2@1",
                    dedup_key="ep:BUY:ENTRY_INTENT", payload_text="x", provenance={})
    rt = RecordingTransport(outcomes=[{"raise": True, "detail": "net down"}])
    r1 = deliver_outbox(s, router=_StubRouter(), transport=rt)
    assert r1["retry"] == 1
    row = s.all_outbox()[0]
    assert row["state"] == "RETRY" and row["attempts"] == 1 and row["next_attempt_utc"]
    # second drain, force it due
    from datetime import datetime, timedelta, timezone
    r2 = deliver_outbox(s, router=_StubRouter(), transport=RecordingTransport(),
                        now=datetime.now(timezone.utc) + timedelta(seconds=400))
    assert r2["sent"] == 1
    assert s.all_outbox()[0]["state"] == "SENT"


def test_p2_dedup_across_ticks_and_router(tmp_path):
    s = V2Store(str(tmp_path / "v.db"), starting_cash=300_000.0)
    assert s.enqueue_alert(event_id="e1", episode_id="ep", kind="ENTRY_FILL", action="BUY",
                           symbol="AAA", strategy_version="v", dedup_key="ep:BUY:ENTRY_FILL",
                           payload_text="x", provenance={}) is True
    assert s.enqueue_alert(event_id="e1", episode_id="ep", kind="ENTRY_FILL", action="BUY",
                           symbol="AAA", strategy_version="v", dedup_key="ep:BUY:ENTRY_FILL",
                           payload_text="x", provenance={}) is False   # same event -> no dup row
    rt = RecordingTransport()
    deliver_outbox(s, router=_StubRouter(delivered={"ep:BUY:ENTRY_FILL"}), transport=rt)
    assert s.all_outbox()[0]["state"] == "SENT"
    assert s.all_outbox()[0]["transport_ref"] == "dedup:already_delivered"
    assert rt.sent == []                               # router said already delivered -> no send


def test_p2_experimental_family_never_escapes(tmp_path):
    from talonx_ops.official_dispatch import OfficialExternalRouter
    r = OfficialExternalRouter(home=tmp_path)
    assert r.decide("experimental", "x").eligible is False
    assert r.decide("insider_buy_cluster_v2", "x").eligible is True


def test_p2_ambiguous_transport_outcome_is_explicit(tmp_path):
    s = V2Store(str(tmp_path / "v.db"), starting_cash=300_000.0)
    s.enqueue_alert(event_id="e1", episode_id="ep", kind="ENTRY_INTENT", action="BUY",
                    symbol="AAA", strategy_version="v", dedup_key="k", payload_text="x",
                    provenance={})
    rt = RecordingTransport(outcomes=[{"ambiguous": True, "detail": "0 subscribers"}])
    r = deliver_outbox(s, router=_StubRouter(), transport=rt)
    assert r["ambiguous"] == 1
    assert s.all_outbox()[0]["state"] == "AMBIGUOUS"


# --------------------------------------------------------------------------- P3
def test_p3_open_position_settles_during_source_failure(tmp_path, monkeypatch):
    from talonx_v2.service import V2SourceError
    bd = _bars(tmp_path, post=[(d, 102, 102, 9e5) for d in
                               ("2026-08-18", "2026-08-19", "2026-08-20", "2026-08-21",
                                "2026-08-24", "2026-08-25", "2026-08-26", "2026-08-27",
                                "2026-08-28")] + [("2026-08-31", 102, 111, 9e5)])
    svc = _svc(tmp_path, bd, kind="insider")

    good = from_rows(_rows())

    class _S:
        mode = {"raise": False}

        def query_transactions(self, **_):
            if self.mode["raise"]:
                raise RuntimeError("ingestion_ledger.db locked")
            return []
    import talonx_ingest.intelligence.insider.store as _st
    holder = _S()
    monkeypatch.setattr(_st, "InsiderStore", lambda *a, **k: holder)
    # seed the position via the parquet path once
    svc._records = lambda *, as_of: good
    svc.tick(as_of=ACT_FRI)
    svc.tick(as_of=ENTRY_MON)
    assert V2Store(str(tmp_path / "v.db"), 300_000.0).n_open() == 1

    # now the live source FAILS -- but the +10td exit must still settle
    svc.form4_kind = "insider"
    svc._records = V2Service._records.__get__(svc)     # restore real _records
    holder.mode["raise"] = True
    st = svc.tick(as_of=EXIT_10TD)
    assert st["heartbeat_kind"] == "DEGRADED_SOURCE"
    assert st["data_state"] == "DATA_UNAVAILABLE"
    assert st["entries_this_tick"] == 0                # no new event-based entries
    s = V2Store(str(tmp_path / "v.db"), starting_cash=300_000.0)
    assert s.n_open() == 0                             # the exit STILL happened
    assert [t["action"] for t in s.trades()] == ["BUY", "SELL"]
    assert s.trades()[-1]["execution_price"] == 111.0  # the real +10td close


def test_p3_source_failure_missing_exit_price_holds_then_unresolved(tmp_path, monkeypatch):
    bd = _bars(tmp_path)                               # NO post-entry bars at all
    svc = _svc(tmp_path, bd, kind="insider")

    class _S:
        raise_it = {"v": False}

        def query_transactions(self, **_):
            if self.raise_it["v"]:
                raise RuntimeError("locked")
            return []
    import talonx_ingest.intelligence.insider.store as _st
    h = _S()
    monkeypatch.setattr(_st, "InsiderStore", lambda *a, **k: h)
    svc._records = lambda *, as_of: from_rows(_rows())
    svc.tick(as_of=ACT_FRI)
    svc.tick(as_of=ENTRY_MON)
    svc._records = V2Service._records.__get__(svc)
    h.raise_it["v"] = True
    # far past the +10td and all fall-forward, no bar ever -> EXIT_UNRESOLVED
    svc.tick(as_of=date(2026, 9, 14))
    s = V2Store(str(tmp_path / "v.db"), starting_cash=300_000.0)
    assert len(s.unresolved_positions()) == 1
    assert [t["action"] for t in s.trades()] == ["BUY"]   # no invented SELL price


def test_p3_no_duplicate_sell_on_restart_during_failure(tmp_path):
    bd = _bars(tmp_path, post=[(d, 102, 102, 9e5) for d in
                               ("2026-08-18", "2026-08-19", "2026-08-20", "2026-08-21",
                                "2026-08-24", "2026-08-25", "2026-08-26", "2026-08-27",
                                "2026-08-28")] + [("2026-08-31", 102, 109, 9e5)])
    svc = _svc(tmp_path, bd)
    svc._records = lambda *, as_of: from_rows(_rows())
    svc.tick(as_of=ACT_FRI)
    svc.tick(as_of=ENTRY_MON)
    svc.tick(as_of=EXIT_10TD)                          # SELL
    del svc
    svc2 = _svc(tmp_path, bd)
    svc2._records = lambda *, as_of: from_rows(_rows())
    svc2.tick(as_of=date(2026, 9, 1))                  # restart, re-settle
    s = V2Store(str(tmp_path / "v.db"), starting_cash=300_000.0)
    assert [t["action"] for t in s.trades()] == ["BUY", "SELL"]
