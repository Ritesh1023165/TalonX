"""POST_DELIVERY_ALERT_MARKOUT_V1: max_observations is an operational per-run PROCESSING budget, never a sample-size
cap (2026-10-09 correction). Synthetic alerts and a mock transport only -- nothing is fetched or sent."""
from __future__ import annotations

import hashlib
import json
import sqlite3
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from talonx_paperperf import post_delivery_acquisition as Q
from talonx_paperperf import post_delivery_collector as C
from talonx_paperperf import post_delivery_markout as M
from tests.test_post_delivery_markout import FakeAcq, activation, good_data, sources, t

UTC = timezone.utc
REPO = Path(__file__).resolve().parents[1]
LOCKED = REPO / "docs" / "research" / "protocols" / "POST_DELIVERY_ALERT_MARKOUT_V1_APPROVED_CONFIG.json"
DEADLINE_S1 = datetime(2026, 10, 14, 21, 0, tzinfo=UTC)       # session 2026-10-12: close of 10-14 (20:00Z) + 60 min


def many(n, start=t(14, 0), step_s=40, prefix="S"):
    """n eligible first deliveries on distinct symbols in session 2026-10-12 (anchors 14:00Z onwards)."""
    return [dict(id=f"E{i:04d}", sym=f"{prefix}{i:04d}", sent=start + timedelta(seconds=i * step_s)) for i in range(n)]


def acq_for(rows):
    bars, quotes = {}, {}
    for r in rows:
        b, q = good_data(r["sym"], r["sent"])
        bars.update(b)
        quotes.update(q)
    return FakeAcq(bars, quotes)


def go(tmp_path, ob, pc, acq, now, limit=M.DEFAULT_MAX_OBSERVATIONS):
    env = {M.ENABLE_ENV: "1", M.CONFIG_ENV: str(activation(tmp_path))}
    return M.run(env, store_root=tmp_path / "pdm", acquirer=acq, now=now, outbox_path=ob, promotion_path=pc,
                 max_observations=limit)


def states(tmp_path):
    s = M.Store(tmp_path / "pdm")
    return dict(s.con.execute("SELECT state, COUNT(*) FROM observations GROUP BY state").fetchall())


def count(tmp_path, sql, args=()):
    return M.Store(tmp_path / "pdm").con.execute(sql, args).fetchone()[0]


# ============================================================================================ batching, not truncation
def test_more_than_200_eligible_observations_complete_across_invocations_without_truncation(tmp_path):
    rows = many(250)
    ob, pc = sources(tmp_path, rows)
    acq = acq_for(rows)
    r1 = go(tmp_path, ob, pc, acq, t(23, 15))                                    # default budget 200
    assert r1["observations_created"] == 250 and r1["acquisition"]["processed"] == 200
    assert r1["acquisition"]["deferred"] == 50 and states(tmp_path) == {M.MEASURED: 200, M.SELECTED_WAITING: 50}
    r2 = go(tmp_path, ob, pc, acq, t(23, 15, d=13))
    assert r2["observations_created"] == 0 and r2["acquisition"]["processed"] == 50
    assert states(tmp_path) == {M.MEASURED: 250}                                 # every eligible delivery represented
    assert count(tmp_path, "SELECT COUNT(DISTINCT event_id) FROM observations") == 250


def test_small_budget_spreads_work_over_runs_before_the_deadline(tmp_path):
    rows = many(25)
    ob, pc = sources(tmp_path, rows)
    acq = acq_for(rows)
    seen = []
    for now in (t(23, 15), t(23, 15, d=13), t(3, 0, d=14)):                     # all before 10-14 21:00Z
        seen.append(go(tmp_path, ob, pc, acq, now, limit=10)["acquisition"]["processed"])
    assert seen == [10, 10, 5] and states(tmp_path) == {M.MEASURED: 25}


def test_completed_observations_do_not_consume_later_processing_slots(tmp_path):
    rows = many(10)
    ob, pc = sources(tmp_path, rows)
    acq = acq_for(rows)
    go(tmp_path, ob, pc, acq, t(23, 15), limit=5)
    first_calls = len(acq.calls)
    r = go(tmp_path, ob, pc, acq, t(23, 15, d=13), limit=5)
    assert r["acquisition"]["due"] == 5 and r["acquisition"]["processed"] == 5      # only the 5 still waiting
    run1, run2 = {c[1] for c in acq.calls[:first_calls]}, {c[1] for c in acq.calls[first_calls:]}
    assert not run1 & run2 and run1 | run2 == {r["sym"] for r in rows}


def test_not_yet_matured_observations_do_not_occupy_the_budget(tmp_path):
    rows = many(3)
    ob, pc = sources(tmp_path, rows)
    r = go(tmp_path, ob, pc, acq_for(rows), t(20, 30), limit=1)                 # before close + 60: nothing due
    assert r["acquisition"]["due"] == 0 and r["acquisition"]["skipped_not_matured"] == 3
    assert r["acquisition"]["processed"] == 0 and states(tmp_path) == {M.SELECTED_WAITING: 3}


def test_processing_order_is_deadline_then_attempts_then_a_ticker_neutral_hash(tmp_path):
    rows = many(40)
    ob, pc = sources(tmp_path, rows)
    acq = acq_for(rows)
    go(tmp_path, ob, pc, acq, t(23, 15), limit=10)
    done = {c[1] for c in acq.calls}
    alphabetical = {r["sym"] for r in rows[:10]}
    assert done != alphabetical                                                 # not the first 10 tickers/anchors
    keys = sorted(M.Store(tmp_path / "pdm").q("SELECT * FROM observations WHERE state=?", (M.MEASURED,)) +
                  M.Store(tmp_path / "pdm").q("SELECT * FROM observations WHERE state=?", (M.SELECTED_WAITING,)),
                  key=lambda o: hashlib.sha256(o["obs_id"].encode()).hexdigest())
    assert done == {o["symbol"] for o in keys[:10]}


# ============================================================================================ selection independence
def test_first_alert_selection_is_independent_of_the_processing_budget(tmp_path):
    rows = many(30) + [dict(id="R1", sym="S0003", sent=t(16, 0)), dict(id="R2", sym="S0029", sent=t(16, 30))]
    picks = []
    for lim in (1, 7, 1000):
        d = tmp_path / str(lim)
        d.mkdir()
        ob, pc = sources(d, rows)
        go(d, ob, pc, acq_for(rows), t(23, 15), limit=lim)
        s = M.Store(d / "pdm")
        picks.append([tuple(r) for r in s.con.execute("SELECT event_id, state FROM observations ORDER BY event_id")])
    norm = [{e: (st if st == M.REPEAT else "SELECTED") for e, st in p} for p in picks]
    assert norm[0] == norm[1] == norm[2]
    assert norm[0]["R1"] == M.REPEAT and norm[0]["R2"] == M.REPEAT and norm[0]["E0003"] == "SELECTED"


def test_repeat_arriving_after_a_batch_boundary_stays_a_repeat_and_first_is_kept(tmp_path):
    rows = many(6) + [dict(id="LATE", sym="S0005", sent=t(17, 0), state="PENDING")]
    ob, pc = sources(tmp_path, rows)
    acq = acq_for(rows)
    go(tmp_path, ob, pc, acq, t(23, 15), limit=2)                               # 4 deferred; LATE not yet delivered
    c = sqlite3.connect(ob)
    c.execute("UPDATE ops_notification_outbox SET state='SENT', sent_at_utc=? WHERE event_id='LATE'",
              (t(17, 0).isoformat(),))
    c.commit()
    c.close()
    go(tmp_path, ob, pc, acq, t(23, 15, d=13), limit=2)
    s = M.Store(tmp_path / "pdm")
    st = dict(s.con.execute("SELECT event_id, state FROM observations").fetchall())
    assert st["LATE"] == M.REPEAT and st["E0005"] in (M.SELECTED_WAITING, M.MEASURED)
    assert s.con.execute("SELECT COUNT(*) FROM observations WHERE symbol='S0005' AND state NOT IN (?)",
                         (M.REPEAT,)).fetchone()[0] == 1


def test_source_rows_are_rescanned_so_none_is_skipped_and_none_duplicated(tmp_path):
    rows = many(4)
    rows[1]["state"] = "RETRY"
    ob, pc = sources(tmp_path, rows)
    go(tmp_path, ob, pc, None, t(23, 15))
    assert count(tmp_path, "SELECT COUNT(*) FROM deliveries") == 3
    c = sqlite3.connect(ob)
    c.execute("UPDATE ops_notification_outbox SET state='SENT' WHERE event_id='E0001'")
    c.commit()
    c.close()
    go(tmp_path, ob, pc, None, t(23, 15, d=13))
    go(tmp_path, ob, pc, None, t(23, 20, d=13))
    assert count(tmp_path, "SELECT COUNT(*) FROM deliveries") == 4
    assert count(tmp_path, "SELECT COUNT(*) FROM observations") == 4
    act = M.load_activation(activation(tmp_path))
    rec = M.source_reconciliation(M.Store(tmp_path / "pdm"), act, ob, pc)
    assert rec["reconciled"] and rec["unregistered_deliveries"] == 0


# ============================================================================================ restarts / failures
class CrashAfter(FakeAcq):
    def __init__(self, n, *a, **k):
        super().__init__(*a, **k)
        self.n = n

    def bar(self, sym, start):
        if len(self.calls) >= self.n:
            raise RuntimeError("process killed")
        return super().bar(sym, start)


def test_restart_between_creation_and_acquisition_resumes_without_duplicates(tmp_path):
    rows = many(5)
    ob, pc = sources(tmp_path, rows)
    good = acq_for(rows)
    go(tmp_path, ob, pc, None, t(23, 15))                                       # created, not acquired
    assert states(tmp_path) == {M.SELECTED_WAITING: 5}
    crash = CrashAfter(6, good.bars, good.quotes)
    with pytest.raises(RuntimeError):
        go(tmp_path, ob, pc, crash, t(23, 20))                                  # dies mid-acquisition
    go(tmp_path, ob, pc, good, t(23, 15, d=13))
    assert states(tmp_path) == {M.MEASURED: 5}
    assert count(tmp_path, "SELECT COUNT(*) FROM observations") == 5
    assert count(tmp_path, "SELECT COUNT(*) FROM inputs") == 20                 # 4 parts each, never duplicated


class PartlyDown(FakeAcq):
    def __init__(self, bad, *a, **k):
        super().__init__(*a, **k)
        self.bad = bad

    def bar(self, sym, start):
        if sym in self.bad:
            self.calls.append(("bar", sym, start))
            return {"outcome": Q.TRANSPORT, "detail": "synthetic"}
        return super().bar(sym, start)

    def quote(self, sym, target):
        if sym in self.bad:
            self.calls.append(("quote", sym, target))
            return {"outcome": Q.TRANSPORT, "detail": "synthetic"}
        return super().quote(sym, target)


def test_failing_observations_do_not_starve_fresh_ones_and_are_never_silently_removed(tmp_path):
    rows = many(10)
    ob, pc = sources(tmp_path, rows)
    g = acq_for(rows)
    go(tmp_path, ob, pc, None, t(23, 0))                                        # select only
    order = [o["symbol"] for o in sorted(M.Store(tmp_path / "pdm").q("SELECT * FROM observations"),
                                         key=M.processing_key)]
    bad = set(order[:5])                                                        # the 5 processed FIRST always fail
    acq = PartlyDown(bad, g.bars, g.quotes)
    go(tmp_path, ob, pc, acq, t(23, 15), limit=5)                               # run 1: the 5 failing ones
    assert states(tmp_path) == {M.SELECTED_WAITING: 10}
    n = len(acq.calls)
    go(tmp_path, ob, pc, acq, t(23, 15, d=13), limit=5)                         # run 2: fresh ones go first
    assert {c[1] for c in acq.calls[n:]} == set(order[5:])
    assert states(tmp_path) == {M.MEASURED: 5, M.SELECTED_WAITING: 5}
    assert count(tmp_path, "SELECT COUNT(DISTINCT obs_id) FROM acquisition_errors") == 5
    go(tmp_path, ob, pc, acq, DEADLINE_S1)                                      # original deadline: no extension
    assert states(tmp_path) == {M.MEASURED: 5, M.EXPIRED: 5}
    assert count(tmp_path, "SELECT COUNT(*) FROM observations WHERE state=? AND reason LIKE 'deadline%'",
                 (M.EXPIRED,)) == 5


class BudgetAfter(FakeAcq):
    def __init__(self, n, *a, **k):
        super().__init__(*a, **k)
        self.n = n

    def _gate(self):
        if len(self.calls) > self.n:
            return {"outcome": Q.BUDGET, "detail": "per-run time budget exhausted"}
        return super()._gate()


def test_time_budget_exhaustion_defers_work_without_errors_or_false_attempts(tmp_path):
    rows = many(6)
    ob, pc = sources(tmp_path, rows)
    g = acq_for(rows)
    r = go(tmp_path, ob, pc, BudgetAfter(8, g.bars, g.quotes), t(23, 15))       # 8 requests = 2 observations
    a = r["acquisition"]
    assert a["budget_exhausted"] and a["processed"] == 2 and a["deferred"] == 4 and a["errors"] == 0
    assert count(tmp_path, "SELECT COUNT(*) FROM acquisition_errors") == 0
    assert count(tmp_path, "SELECT COUNT(*) FROM observations WHERE attempts>0") == 2
    go(tmp_path, ob, pc, g, t(23, 15, d=13))
    assert states(tmp_path) == {M.MEASURED: 6}


def test_work_still_awaiting_processing_expires_at_its_original_deadline(tmp_path):
    rows = many(8)
    ob, pc = sources(tmp_path, rows)
    acq = acq_for(rows)
    go(tmp_path, ob, pc, acq, t(23, 15), limit=3)
    r = go(tmp_path, ob, pc, acq, DEADLINE_S1 + timedelta(hours=2), limit=3)    # missed the in-between run
    assert r["acquisition"]["due"] == 0                                         # nothing past its deadline is fetched
    assert states(tmp_path) == {M.MEASURED: 3, M.EXPIRED: 5}


# ============================================================================================ reporting gate
def test_final_report_refused_while_deferred_observations_or_sources_are_pending(tmp_path):
    rows = many(6) + [dict(id="PEND", sym="ZZZ", sent=t(15, 0), state="PENDING")]
    ob, pc = sources(tmp_path, rows)
    go(tmp_path, ob, pc, acq_for(rows), t(23, 15), limit=2)
    act = M.load_activation(activation(tmp_path))
    s = M.Store(tmp_path / "pdm")
    cc = M.completion_checks(s, act, act["endpoint_utc"], outbox_path=ob, promotion_path=pc)
    assert not cc["checks"]["all_selected_terminal"] and not cc["checks"]["sources_reconciled"]
    assert M.final_report(s, act, act["endpoint_utc"], outbox_path=ob, promotion_path=pc)["status"] == "INCOMPLETE"


# ============================================================================================ one authoritative value
def locked_cfg(tmp_path, value):
    d = json.loads(LOCKED.read_text(encoding="utf-8"))
    d = {**d, "first_session": "2026-10-12", "delivery_trace_policy": "NOT_AVAILABLE_ACCEPTED",
         "implementation_sha256": M.implementation_hashes(), "collector": {**d["collector"]}}
    if value is None:
        d["collector"].pop("max_observations_per_run")
    else:
        d["collector"]["max_observations_per_run"] = value
    p = tmp_path / "cfg.json"
    p.write_text(json.dumps(d), encoding="utf-8")
    return p


def test_collector_effective_limit_is_the_locked_value(tmp_path):
    rows = many(9)
    ob, pc = sources(tmp_path, rows)
    r = C.collect(config=locked_cfg(tmp_path, 4), enable=True, store=tmp_path / "pdm", budget_s=60, now=t(23, 15),
                  acquirer=acq_for(rows), outbox_path=ob, promotion_path=pc, trace_path=tmp_path / "tr.db",
                  lock_alive=lambda pid: False)
    assert r["max_observations"] == 4 and r["summary"]["acquisition"]["max_observations"] == 4
    assert r["summary"]["acquisition"]["processed"] == 4 and r["summary"]["acquisition"]["deferred"] == 5
    log = (tmp_path / "pdm_ops" / "runs.jsonl").read_text(encoding="utf-8").splitlines()
    assert json.loads(log[-1])["max_observations"] == 4


@pytest.mark.parametrize("locked,requested", [(200, 150), (0, None), (-3, None), ("200", None), (True, None),
                                              (None, None), (200, 0)])
def test_conflicting_missing_or_invalid_settings_refuse_the_run_without_requests(tmp_path, locked, requested):
    rows = many(2)
    ob, pc = sources(tmp_path, rows)
    acq = acq_for(rows)
    r = C.collect(config=locked_cfg(tmp_path, locked), enable=True, store=tmp_path / "pdm", budget_s=60,
                  max_observations=requested, now=t(23, 15), acquirer=acq, outbox_path=ob, promotion_path=pc,
                  trace_path=tmp_path / "tr.db", lock_alive=lambda pid: False)
    assert r["state"] == "CONFIG_REJECTED" and acq.calls == [] and not (tmp_path / "pdm").exists()


def test_matching_explicit_value_is_accepted(tmp_path):
    assert C.resolve_max_observations(locked_cfg(tmp_path, 200), 200) == 200
    assert C.resolve_max_observations(locked_cfg(tmp_path, 200), None) == 200


def test_invalid_values_are_rejected_by_the_engine_too():
    for bad in (0, -1, 1.5, "10", True, None):
        with pytest.raises(ValueError):
            M.validate_max_observations(bad)


def test_shipped_config_task_and_cli_agree_on_one_value():
    d = json.loads(LOCKED.read_text(encoding="utf-8"))
    assert d["collector"]["max_observations_per_run"] == 200 == M.DEFAULT_MAX_OBSERVATIONS
    assert C.resolve_max_observations(LOCKED, None) == 200
    xml = (REPO / "docs/research/protocols/pdm_v1_scheduler/PDM_V1_Collector.task.xml").read_text(encoding="utf-8")
    assert "--max-observations" not in xml                                      # the locked value applies
