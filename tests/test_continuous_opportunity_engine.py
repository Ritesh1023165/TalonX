"""Continuous Opportunity Engine (REQ S14-01..S14-06) -- offline tests, no network, no real Telegram."""
from __future__ import annotations

import ast
import hashlib
import json
import os
import random
import subprocess
import sys
import time
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import pytest

from talonx_opportunity import capabilities as C
from talonx_opportunity.aggregates import SymbolAggregate, features_from_aggregate
from talonx_opportunity.config import CONTINUOUS_RESEARCH_V1, NotificationPolicy
from talonx_opportunity.discovery import Discovery
from talonx_opportunity.evaluators import HorizonEvaluator
from talonx_opportunity.ingestion import Ingestion
from talonx_opportunity.notifier import Notifier
from talonx_opportunity.outcome_tracker import OutcomeTracker
from talonx_opportunity.phases import AFTER_HOURS, OVERNIGHT, PREMARKET, REGULAR, phase_at
from talonx_opportunity.reporting import build_report
from talonx_opportunity.runtime import RuntimeStore, run_component
from talonx_opportunity.store import OpportunityStore
from talonx_premarket import features as F
from talonx_premarket.alpaca_data import FetchResult, parse_ts

UTC = timezone.utc
REPO = Path(__file__).resolve().parents[1]
D = date(2026, 9, 24)               # a real XNYS session (reference 2026-09-23)


def U(h, m=0, d=24):
    return datetime(2026, 9, d, h, m, tzinfo=UTC)


def _iso(t):
    return t.strftime("%Y-%m-%dT%H:%M:%SZ")


def _daily(close=10.0, n=25):
    out, day = [], date(2026, 8, 18)
    while len(out) < n:
        if day.weekday() < 5:
            out.append({"t": f"{day.isoformat()}T04:00:00Z", "o": close, "h": close * 1.02, "l": close * 0.98,
                        "c": close, "v": 1_000_000, "vw": close, "n": 1000})
        day += timedelta(days=1)
    out[-1]["t"] = "2026-09-23T04:00:00Z"
    return out


def _minutes(start, end, price, v, step=1):
    t, out = start, []
    while t < end:
        out.append({"t": _iso(t), "o": price, "h": price * 1.001, "l": price * 0.999, "c": price, "v": v,
                    "vw": price, "n": 10})
        t += timedelta(minutes=step)
    return out


class FakeData:
    """Alpaca stand-in: honours start/end (inclusive) and can fail chosen symbols."""

    def __init__(self, minute: dict[str, list[dict]], daily: dict[str, list[dict]], fail: set[str] | None = None):
        self.minute, self.daily_bars, self.fail = minute, daily, set(fail or ())
        self.requests, self.errors = 0, []
        self.failed_batches_total = self.retried_batches_total = 0
        self.last_success_utc = None

    def bars_ex(self, symbols, *, timeframe, start, end, attempts=2):
        self.requests += 1
        res = FetchResult(batches=1)
        src = self.daily_bars if timeframe == "1Day" else self.minute
        for s in symbols:
            if s in self.fail:
                res.failed.add(s)
                continue
            rows = [b for b in src.get(s, []) if start <= parse_ts(b["t"]) <= end]
            if rows:
                res.bars[s] = rows
        if res.failed:
            res.failed_batches = 1
        return res

    def assets(self):
        return []


class Clock:
    def __init__(self, t):
        self.t = t

    def __call__(self):
        return self.t


def _world():
    minute = {
        "SPY": _minutes(U(8), U(23, 59), 500.0, 1000),
        # AAA: strong pre-market gap, keeps trading through regular + after-hours
        "AAA": _minutes(U(8), U(23, 59), 11.0, 5000),
        # BBB: flat pre-market, then a regular-session move from 14:00Z, no after-hours prints
        "BBB": _minutes(U(8), U(13, 30), 10.02, 100) + _minutes(U(13, 30), U(14), 10.05, 1000)
        + _minutes(U(14), U(20), 10.9, 20000),
        "CCC": _minutes(U(8), U(20), 10.01, 500),
    }
    daily = {s: _daily() for s in ("SPY", "AAA", "BBB", "CCC")}
    members = [{"symbol": s, "name": s, "exchange": "NASDAQ", "cik": None, "status": "ELIGIBLE", "reason": ""}
               for s in ("AAA", "BBB", "CCC")]
    return minute, daily, members


@pytest.fixture
def eng(tmp_path):
    minute, daily, members = _world()
    clock = Clock(U(9))
    data = FakeData(minute, daily)
    ing = Ingestion(data=data, root=tmp_path, clock=clock, universe_loader=lambda: (members, "test"))
    disc = Discovery(root=tmp_path, clock=clock)
    return {"root": tmp_path, "clock": clock, "data": data, "ing": ing, "disc": disc}


def _step(e, t):
    e["clock"].t = t
    e["ing"].tick()
    e["disc"].tick()


def _events(root):
    s = OpportunityStore(root, readonly=True)
    try:
        return s.events_after(0, 10_000)
    finally:
        s.close()


def _cands(root):
    s = OpportunityStore(root, readonly=True)
    try:
        return s.candidates()
    finally:
        s.close()


# --------------------------------------------------------------------------------------------- aggregate == V1
def test_aggregate_features_are_bit_identical_to_v1_compute():
    rnd = random.Random(7)
    for _ in range(50):
        n = rnd.randint(1, 120)
        start = U(8)
        bars = []
        for i in range(n):
            p = 10 * (1 + rnd.uniform(-0.1, 0.1))
            bars.append({"t": _iso(start + timedelta(minutes=i * rnd.randint(1, 3))), "o": p, "h": p * 1.01,
                         "l": p * 0.99, "c": p, "v": rnd.randint(0, 50_000), "vw": p * rnd.uniform(0.99, 1.01),
                         "n": rnd.randint(0, 40)})
        bars = sorted({b["t"]: b for b in bars}.values(), key=lambda b: b["t"])
        agg = SymbolAggregate("X", "w")
        agg.add(bars)
        as_of = parse_ts(bars[-1]["t"]) + timedelta(minutes=rnd.randint(1, 60))
        f1, r1 = F.compute("X", _daily(), bars, prev_session=date(2026, 9, 23), data_as_of=as_of)
        f2, r2 = features_from_aggregate("X", _daily(), agg, prev_session=date(2026, 9, 23), data_as_of=as_of)
        assert r1 == r2 and f1 == f2


# --------------------------------------------------------------------------------------------- phases / continuity
def test_1_premarket_to_regular_discovery_continues(eng):
    _step(eng, U(9))
    assert phase_at(U(9))[0] == PREMARKET
    new_pm = [e for e in _events(eng["root"]) if e["event_type"] == "NEW"]
    assert [e["symbol"] for e in new_pm] == ["AAA"] and new_pm[0]["phase"] == PREMARKET
    _step(eng, U(14, 30))
    assert phase_at(U(14, 30))[0] == REGULAR
    new = {e["symbol"]: e for e in _events(eng["root"]) if e["event_type"] == "NEW"}
    assert "BBB" in new and new["BBB"]["phase"] == REGULAR          # discovered AFTER the regular open
    s = OpportunityStore(eng["root"], readonly=True)
    assert s.last_scan()["phase"] == REGULAR and s.last_scan()["state"] == "SCANNED"


def test_2_regular_to_after_hours_discovery_continues(eng):
    for t in (U(9), U(14, 30), U(20, 30)):
        _step(eng, t)
    s = OpportunityStore(eng["root"], readonly=True)
    last = s.last_scan()
    assert phase_at(U(20, 30))[0] == AFTER_HOURS and last["phase"] == AFTER_HOURS and last["state"] == "SCANNED"
    assert last["funnel"]["DATA_READY"] >= 1


def test_3_phase_transition_does_not_duplicate_identity(eng):
    for t in (U(9), U(9, 30), U(13, 45), U(14, 30), U(16), U(20, 30)):
        _step(eng, t)
    aaa = [c for c in _cands(eng["root"]) if c["symbol"] == "AAA"]
    assert len(aaa) == 1 and aaa[0]["first_seen_phase"] == PREMARKET
    assert aaa[0]["last_phase"] in (REGULAR, AFTER_HOURS)
    assert sum(1 for e in _events(eng["root"]) if e["symbol"] == "AAA" and e["event_type"] == "NEW") == 1


def test_after_hours_stale_holds_but_premarket_rules_unchanged(eng):
    for t in (U(9), U(14, 30), U(21, 30)):             # BBB has no after-hours prints: 75 min stale at 21:15 as-of
        _step(eng, t)
    bbb = [c for c in _cands(eng["root"]) if c["symbol"] == "BBB"]
    assert bbb and bbb[0]["state"] != "INVALIDATED"
    last = OpportunityStore(eng["root"], readonly=True).last_scan()
    assert last["funnel"]["HELD_STALE_NON_INVALIDATING_PHASE"] >= 1
    assert "REGULAR" in CONTINUOUS_RESEARCH_V1.stale_invalidates_phases
    assert CONTINUOUS_RESEARCH_V1.base.max_premarket_staleness_min == 45       # frozen gate untouched


# --------------------------------------------------------------------------------------------- capability
def test_4_unsupported_overnight_fails_closed(eng):
    eng["clock"].t = U(3)                              # 23:00 ET -> OVERNIGHT of the 09-24 window
    assert phase_at(U(3))[0] == OVERNIGHT
    before = eng["data"].requests
    assert eng["ing"].tick() == 300.0
    minute_calls = eng["data"].requests - before
    eng["disc"].tick()
    last = OpportunityStore(eng["root"], readonly=True).last_scan()
    assert last["phase"] == OVERNIGHT and last["state"] == "DATA_UNAVAILABLE"
    assert last["capability"]["availability"] == C.NOT_SUPPORTED and not last["capability"]["usable_for_discovery"]
    assert _cands(eng["root"]) == []
    assert minute_calls <= 1                            # at most the daily-history fetch, never overnight bars
    assert C.OVERNIGHT_ALTERNATIVES["boats"].availability == C.DISABLED
    assert not C.OVERNIGHT_ALTERNATIVES["boats"].usable_for_discovery


def test_5_unsupported_overnight_does_not_stop_other_components(eng):
    _step(eng, U(9))
    eng["clock"].t = U(3, 0, 25)                        # next window's overnight
    eng["ing"].tick()
    eng["disc"].tick()
    n = Notifier(root=eng["root"])
    assert n.tick() > 0 and n.cursor() >= 1
    for h in ("INTRADAY", "SAME_DAY", "SHORT_TERM", "LONG_TERM"):
        ev = HorizonEvaluator(h, root=eng["root"])
        ev.tick()
        assert ev.cursor() >= 1


def test_failed_probe_degrades_only_that_phase(eng):
    probe = {"ok": False, "at_utc": "x", "detail": "HTTP 403"}
    assert C.effective_capability(REGULAR, probe).availability == C.UNAVAILABLE
    assert C.effective_capability(PREMARKET, None).usable_for_discovery


def test_incomplete_provider_batch_holds_symbol(tmp_path):
    minute, daily, members = _world()
    clock = Clock(U(9))
    data = FakeData(minute, daily, fail={"AAA"})
    ing = Ingestion(data=data, root=tmp_path, clock=clock, universe_loader=lambda: (members, "t"))
    ing.tick()
    Discovery(root=tmp_path, clock=clock).tick()
    assert not [c for c in _cands(tmp_path) if c["symbol"] == "AAA"]      # unknown data never creates a candidate
    last = OpportunityStore(tmp_path, readonly=True).last_scan()
    assert last["funnel"]["PROVIDER_INCOMPLETE"] == 1


# --------------------------------------------------------------------------------------------- uncapped + policy
def _seed_events(root, specs):
    """specs: list of (symbol, classification, event_type, score, at)."""
    s = OpportunityStore(root)
    for i, (sym, cls, typ, score, at) in enumerate(specs):
        cid = f"2026-09-24:{sym}:GAP_UP"
        if s.candidate(cid) is None:
            s.upsert_candidate({"candidate_id": cid, "window_id": "2026-09-24", "symbol": sym, "family": "GAP_UP",
                                "state": cls, "classification": cls, "first_seen_utc": at, "first_seen_phase": "REGULAR",
                                "in_v2_scope": 0})
        s.add_event({"event_id": f"{cid}:{typ}:{at}:{i}", "candidate_id": cid, "window_id": "2026-09-24",
                     "symbol": sym, "at_utc": at, "phase": "REGULAR", "event_type": typ, "classification": cls,
                     "score": score, "features_json": "{}", "score_json": "{}", "provenance_json": "{}"})
    s.commit()
    s.close()


def test_6_persistence_continues_after_budget_exhausted(tmp_path):
    specs = [(f"W{i:02d}", "WATCH", "NEW", 45.0, "2026-09-24T09:00:00+00:00") for i in range(40)]
    _seed_events(tmp_path, specs)
    n = Notifier(root=tmp_path, policy=NotificationPolicy(total_new_per_window=3, setup_reserved=1))
    n.tick()
    assert len(_cands(tmp_path)) == 40                      # every candidate persisted
    dec = dict(n.con.execute("SELECT decision, COUNT(*) FROM decisions GROUP BY 1").fetchall())
    assert dec["SELECTED"] == 2 and dec["BUDGET_EXHAUSTED_WATCH"] == 38


def test_7_later_setup_routes_despite_watch_quota(tmp_path):
    early = [(f"W{i}", "WATCH", "NEW", 50.0, "2026-09-24T08:30:00+00:00") for i in range(10)]
    late = [("SETUP", "BULLISH", "NEW", 70.0, "2026-09-24T15:00:00+00:00")]
    _seed_events(tmp_path, early + late)
    n = Notifier(root=tmp_path, policy=NotificationPolicy(total_new_per_window=5, setup_reserved=2))
    n.tick()
    rows = {r["symbol"]: r["decision"] for r in n.con.execute("SELECT symbol, decision FROM decisions")}
    assert rows["SETUP"] == "SELECTED"
    assert sum(1 for s, d in rows.items() if s.startswith("W") and d == "SELECTED") == 3


def test_priority_within_one_evaluation_puts_setups_first(tmp_path):
    at = "2026-09-24T09:00:00+00:00"
    _seed_events(tmp_path, [("W1", "WATCH", "NEW", 90.0, at), ("B1", "BULLISH", "NEW", 61.0, at)])
    n = Notifier(root=tmp_path, policy=NotificationPolicy(total_new_per_window=1, setup_reserved=0))
    n.tick()
    rows = {r["symbol"]: r["decision"] for r in n.con.execute("SELECT symbol, decision FROM decisions")}
    assert rows == {"B1": "SELECTED", "W1": "BUDGET_EXHAUSTED_TOTAL"}


def test_updates_and_invalidations_only_for_surfaced(tmp_path):
    at, later = "2026-09-24T09:00:00+00:00", "2026-09-24T10:00:00+00:00"
    _seed_events(tmp_path, [("A", "WATCH", "NEW", 50.0, at), ("B", "WATCH", "NEW", 49.0, at),
                            ("A", "WATCH", "MATERIAL_UPDATE", 70.0, later), ("B", "WATCH", "MATERIAL_UPDATE", 70.0, later),
                            ("B", "INVALIDATED", "INVALIDATED", None, later)])
    n = Notifier(root=tmp_path, policy=NotificationPolicy(total_new_per_window=1, setup_reserved=0))
    n.tick()
    rows = [(r["symbol"], r["event_type"], r["decision"]) for r in
            n.con.execute("SELECT symbol, event_type, decision FROM decisions ORDER BY seq")]
    assert ("A", "MATERIAL_UPDATE", "SELECTED") in rows
    assert ("B", "MATERIAL_UPDATE", "NOT_SURFACED_PARENT") in rows
    assert ("B", "INVALIDATED", "NOT_SURFACED_PARENT") in rows


# --------------------------------------------------------------------------------------------- restart boundaries
def _hash_rows(root):
    s = OpportunityStore(root, readonly=True)
    rows = [tuple(dict(r).items()) for r in s.con.execute("SELECT * FROM candidates ORDER BY candidate_id")]
    evs = s.con.execute("SELECT COUNT(*) FROM candidate_events").fetchone()[0]
    s.close()
    return hashlib.sha256(repr(rows).encode()).hexdigest(), evs


def test_8_notification_restart_preserves_candidate_state(eng):
    _step(eng, U(9))
    _step(eng, U(14, 30))
    before = _hash_rows(eng["root"])
    n1 = Notifier(root=eng["root"])
    n1.tick()
    c1 = n1.cursor()
    n1.con.close()
    n2 = Notifier(root=eng["root"])                     # "restart"
    n2.tick()
    assert _hash_rows(eng["root"]) == before
    assert n2.cursor() == c1
    assert n2.con.execute("SELECT COUNT(*) FROM decisions").fetchone()[0] == len(_events(eng["root"]))


def test_9_discovery_restart_preserves_outbox(eng):
    _step(eng, U(9))
    n = Notifier(root=eng["root"], deliver=True, drain=lambda store: {"sent": 0})
    n.tick()
    rows_before = len(n.outbox.all_outbox())
    assert rows_before >= 1
    eng["disc"].store.close()
    eng["disc"] = Discovery(root=eng["root"], clock=eng["clock"])     # restart discovery
    _step(eng, U(9, 5))
    assert len(n.outbox.all_outbox()) == rows_before
    assert {r["state"] for r in n.outbox.all_outbox()} == {"PENDING"}


def test_10_outbox_survives_worker_restart_and_sends_once(eng):
    _step(eng, U(9))
    n1 = Notifier(root=eng["root"], deliver=True, drain=lambda store: {"sent": 0})   # Lab disabled / worker down
    n1.tick()
    ids = [r["event_id"] for r in n1.outbox.all_outbox()]
    n1.con.close()
    sent = []

    def drain(store):
        for r in store.outbox_due(now_iso=datetime.now(UTC).isoformat(), destination="RESEARCH"):
            store.update_outbox(r["event_id"], state="SENT", attempts=1)
            sent.append(r["event_id"])
        return {"sent": len(sent)}
    n2 = Notifier(root=eng["root"], deliver=True, drain=drain)
    n2.tick()
    n2.tick()
    assert sorted(sent) == sorted(ids)
    assert {r["state"] for r in n2.outbox.all_outbox()} == {"SENT"}
    assert set(n2.sync()) == {"SENT"}


def test_11_deployment_boundary_persists(tmp_path):
    run_component("evaluator:LONG_TERM", tick=lambda: 0.0, root=tmp_path, max_ticks=1, config_fps={"a": "1"})
    run_component("evaluator:LONG_TERM", tick=lambda: 0.0, root=tmp_path, max_ticks=1, config_fps={"a": "1"})
    run_component("evaluator:LONG_TERM", tick=lambda: 0.0, root=tmp_path, max_ticks=1, config_fps={"a": "2"})
    rt = RuntimeStore(tmp_path, readonly=True)
    deps = rt.deployments()
    assert [d["decided_by"] for d in deps] == ["FIRST_START", "RULE:UNCHANGED_RESTART",
                                                 "RULE:CONFIG_FINGERPRINT_CHANGED"]
    assert deps[1]["classification"] == "OPERATIONS_ONLY" and deps[1]["restart_only"] == 1
    assert deps[2]["classification"] == "STRATEGY_MATERIAL" and deps[2]["affects_detection"] == 1
    for k in ("deployment_id", "at_utc", "component", "old_version", "new_version", "commit_sha", "reason",
              "classification", "affects_detection", "affects_classification", "affects_execution",
              "affects_notification", "affects_candidate_counts", "affects_pnl", "affects_profitability_analysis"):
        assert k in deps[2]


def test_declaration_cannot_downgrade_config_change(tmp_path):
    run_component("discovery", tick=lambda: 0.0, root=tmp_path, max_ticks=1, config_fps={"c": "A"})
    RuntimeStore(tmp_path).declare_change("discovery", "OPERATIONS_ONLY", "just a refactor")
    run_component("discovery", tick=lambda: 0.0, root=tmp_path, max_ticks=1, config_fps={"c": "B"})
    assert RuntimeStore(tmp_path, readonly=True).deployments()[-1]["classification"] == "STRATEGY_MATERIAL"


def _seed_window_candidates(root, times):
    s = OpportunityStore(root)
    for i, t in enumerate(times):
        s.upsert_candidate({"candidate_id": f"2026-09-24:S{i}:GAP_UP", "window_id": "2026-09-24", "symbol": f"S{i}",
                            "family": "GAP_UP", "state": "WATCH", "classification": "WATCH", "first_seen_utc": t,
                            "first_seen_phase": "REGULAR"})
    s.commit()
    s.close()


def _dep(rt, at, component, cls, restart_only=0, decided="DECLARED"):
    from talonx_opportunity.runtime import impact_for
    imp = impact_for(cls, component)
    rt.con.execute("INSERT INTO deployment_events VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                   (f"d-{at}-{component}", at, component, "v1", "v1" if restart_only else "v2", "sha", "{}", "{}",
                    "test", cls, restart_only, int(imp["detection"]), int(imp["classification"]),
                    int(imp["execution"]), int(imp["notification"]), int(imp["candidate_counts"]), int(imp["pnl"]),
                    int(imp["profitability_analysis"]), json.dumps(imp), 1, decided))
    rt.con.commit()


def test_12_reporting_splits_on_strategy_material_boundary(tmp_path):
    _seed_window_candidates(tmp_path, ["2026-09-24T14:00:00+00:00", "2026-09-24T17:00:00+00:00"])
    rt = RuntimeStore(tmp_path)
    _dep(rt, "2026-09-24T15:08:00+00:00", "discovery", "STRATEGY_MATERIAL")
    rep = build_report(tmp_path, "2026-09-24")
    assert len(rep["segments"]) == 2 and not rep["aggregatable"]["candidates"]
    assert [s["candidates_first_seen"] for s in rep["segments"]] == [1, 1]
    assert rep["comparability_warnings"] and rep["material_changes"]


def test_13_operations_only_restart_does_not_split(tmp_path):
    _seed_window_candidates(tmp_path, ["2026-09-24T14:00:00+00:00", "2026-09-24T17:00:00+00:00"])
    rt = RuntimeStore(tmp_path)
    _dep(rt, "2026-09-24T13:42:00+00:00", "notifier", "OPERATIONS_ONLY", restart_only=1,
         decided="RULE:UNCHANGED_RESTART")
    rep = build_report(tmp_path, "2026-09-24")
    assert len(rep["segments"]) == 1 and rep["aggregatable"]["candidates"] and rep["aggregatable"]["outcomes"]
    assert rep["operations_only_restarts"][0]["comparability"] == "INTACT"
    assert not rep["comparability_warnings"]


def test_notifier_code_fix_splits_alerts_but_not_candidates(tmp_path):
    _seed_window_candidates(tmp_path, ["2026-09-24T14:00:00+00:00"])
    _dep(RuntimeStore(tmp_path), "2026-09-24T13:42:00+00:00", "notifier", "ROUTING_FIX")
    rep = build_report(tmp_path, "2026-09-24")
    assert rep["aggregatable"]["candidates"] and not rep["aggregatable"]["alerts"]


# --------------------------------------------------------------------------------------------- frozen / isolation
def test_14_v2_frozen_identity_unchanged():
    from talonx_v2 import provider_contract as pc
    from talonx_v2 import release_gate as rg
    assert rg._strategy_fingerprint() == "e2acf6454789217e"
    assert pc.RELEASE_CONTRACT.fingerprint() == "ac5e51aa3599d6c9"
    assert rg.RELEASE_PROFILE.campaign_id == "V2-PAPER-RC1"
    assert CONTINUOUS_RESEARCH_V1.base.fingerprint() == "62ba413daf85e674"


def _lane_sources():
    return [p for p in (REPO / "talonx_opportunity").glob("*.py")]


def test_15_research_cannot_emit_v2_trade_event():
    for p in _lane_sources():
        if p.name == "promotion.py":
            continue            # the ONE sanctioned Signal producer; held to its own stricter guard (test_15b)
        text = p.read_text(encoding="utf-8")
        tree = ast.parse(text)
        names = {n.id for n in ast.walk(tree) if isinstance(n, ast.Name)} | \
                {n.attr for n in ast.walk(tree) if isinstance(n, ast.Attribute)}
        assert not names & {"TRADE_EVENT", "OPERATIONS", "submit_order", "execute_buy", "execute_sell"}, p
        for forbidden in ("import talonx_v2", "from talonx_v2", "/v2/orders", "paper_trading.db"):
            assert forbidden not in text, (p, forbidden)
    src = (REPO / "talonx_opportunity" / "notifier.py").read_text(encoding="utf-8")
    assert "destination=RESEARCH" in src and "TRADE_EVENT" not in src



def test_15b_promotion_is_the_only_signal_producer_and_only_paper_opportunities():
    """2026-09-25 OPPORTUNITY_PROMOTION_V1: the promotion lane may reach the TRADE_EVENT (TalonX Signal) destination,
    but only as event_type PAPER_OPPORTUNITY, only in PAPER_SIGNAL mode (default SHADOW), never V2 / orders."""
    p = REPO / "talonx_opportunity" / "promotion.py"
    text = p.read_text(encoding="utf-8")
    for forbidden in ("import talonx_v2", "from talonx_v2", "/v2/orders", "paper_trading.db", "submit_order",
                      "execute_buy", "execute_sell", "OPERATIONS", 'event_type="TRADE_EVENT"'):
        assert forbidden not in text, forbidden
    assert text.count("destination=TRADE_EVENT") == 2 and 'event_type="PAPER_OPPORTUNITY"' in text   # enqueue + drain
    assert "if self.mode == PAPER_SIGNAL and self.outbox is not None:" in text                         # enqueue gate
    assert "if self.mode != PAPER_SIGNAL or self.outbox is None:\n            return None" in text      # drain gate
    assert 'str((env if env is not None else os.environ).get(MODE_ENV, SHADOW))' in text      # default SHADOW
    # every OTHER lane source is still held to test_15's AST guard (no TRADE_EVENT / OPERATIONS name in code)

def test_16_lab_signal_sentinel_isolation(tmp_path, monkeypatch):
    from talonx_ops.notify import RESEARCH, resolve_destination_config
    monkeypatch.delenv("TALONX_NOTIFY_RESEARCH_ENABLED", raising=False)
    assert not resolve_destination_config(RESEARCH).enabled
    monkeypatch.setenv("TALONX_NOTIFY_RESEARCH_ENABLED", "1")
    monkeypatch.setenv("TALONX_NOTIFY_RESEARCH_BOT_TOKEN", "same-token")
    monkeypatch.setenv("TALONX_NOTIFY_RESEARCH_CHAT_ID", "1")
    monkeypatch.setenv("TALONX_NOTIFY_TRADE_EVENT_BOT_TOKEN", "same-token")
    assert not resolve_destination_config(RESEARCH).enabled          # Lab may never alias Signal
    from talonx_opportunity.db import PROTECTED_DB_NAMES, connect
    from talonx_opportunity.notifier import outbox_path
    assert outbox_path(tmp_path).name not in PROTECTED_DB_NAMES
    with pytest.raises(PermissionError):
        connect(tmp_path / "v2_release_rc1_notifications.db")
    _seed_events(tmp_path, [("A", "WATCH", "NEW", 50.0, "2026-09-24T09:00:00+00:00")])
    n = Notifier(root=tmp_path, deliver=True, drain=lambda s: None)
    n.tick()
    assert {r["destination"] for r in n.outbox.all_outbox()} == {"RESEARCH"}


def test_19_dashboard_reflects_component_degradation_independently(tmp_path):
    from talonx_ops.opportunity_read import read_opportunity_status
    now = datetime.now(UTC)
    rt = RuntimeStore(tmp_path)
    for n in ("ingestion", "discovery", "evaluator:INTRADAY", "evaluator:SAME_DAY", "evaluator:SHORT_TERM",
              "evaluator:LONG_TERM", "notifier", "outcomes", "reporting"):
        rt.set_component(n, pid=os.getpid(), state="RUNNING", heartbeat_utc=now.isoformat())
    rt.set_component("notifier", state="DEGRADED")
    rt.set_component("evaluator:INTRADAY", heartbeat_utc=(now - timedelta(hours=1)).isoformat())
    s = read_opportunity_status(tmp_path)
    health = {c["component"]: c["health"] for c in s["components"]}
    # alive pid + 1 h old heartbeat = STALE_HEARTBEAT (possibly hung), not DOWN (2026-09-25 status semantics)
    assert health["notifier"] == "DEGRADED" and health["evaluator:INTRADAY"] == "STALE_HEARTBEAT"
    assert health["discovery"] == "UP" and health["ingestion"] == "UP"
    assert s["system"]["overall"] == "DEGRADED"
    assert s["horizons"]["INTRADAY"]["health"] == "STALE_HEARTBEAT" and s["horizons"]["SAME_DAY"]["health"] == "UP"


def test_20_no_real_money_execution_path():
    from talonx_v2 import release_gate as rg
    assert rg.RELEASE_PROFILE.execution_mode == "PAPER"
    for p in _lane_sources():
        text = p.read_text(encoding="utf-8").lower()
        for forbidden in ("api.alpaca.markets/v2/orders", "paper-api.alpaca.markets/v2/orders",
                          "allow_real_capital=true", "live_trading"):
            assert forbidden not in text, (p, forbidden)
    for h in ("INTRADAY", "SAME_DAY", "SHORT_TERM", "LONG_TERM"):
        from talonx_opportunity.evaluators import AUTHORIZED_STRATEGIES
        assert AUTHORIZED_STRATEGIES[h] == ()


def test_evaluators_never_emit_buy_sell_and_are_independent(eng):
    for t in (U(9), U(14, 30), U(20, 30)):
        _step(eng, t)
    evs = {h: HorizonEvaluator(h, root=eng["root"]) for h in ("INTRADAY", "SAME_DAY", "SHORT_TERM", "LONG_TERM")}
    evs["SAME_DAY"].tick()                               # only one evaluator runs
    assert evs["INTRADAY"].cursor() == 0 and evs["SAME_DAY"].cursor() > 0
    for e in evs.values():
        e.tick()
        assert e.con.execute("SELECT COUNT(*) FROM records WHERE action_state IN ('BUY','SELL')").fetchone()[0] == 0
    assert evs["LONG_TERM"].con.execute("SELECT COUNT(*) FROM records").fetchone()[0] == 0
    assert evs["LONG_TERM"].last["state"] == "IDLE_NOT_IMPLEMENTED"


def test_outcomes_measure_every_candidate_not_only_surfaced(eng):
    for t in (U(9), U(14, 30)):
        _step(eng, t)
    eng["clock"].t = U(20, 20)
    ot = OutcomeTracker(root=eng["root"], data=eng["data"], clock=eng["clock"])
    ot.tick()
    rows = {r["symbol"]: dict(r) for r in ot.con.execute("SELECT * FROM outcomes")}
    assert rows["AAA"]["model"] == "PREMARKET_RESEARCH_V1.measure"
    assert rows["BBB"]["model"] == "SINCE_FIRST_SEEN_V1" and rows["BBB"]["status"] != "OUTCOME_PENDING"


def test_premarket_classification_identical_to_v1_engine(tmp_path):
    """Same bars, same as-of: continuous discovery classifies exactly like the frozen V1 engine in PREMARKET."""
    from talonx_premarket import scoring as S
    minute, daily, _ = _world()
    as_of = U(8, 45)
    for sym in ("AAA", "BBB", "CCC"):
        bars = [b for b in minute[sym] if parse_ts(b["t"]) + timedelta(minutes=1) <= as_of]
        agg = SymbolAggregate(sym, "w")
        agg.add(bars)
        f1, _ = F.compute(sym, daily[sym], bars, prev_session=date(2026, 9, 23), data_as_of=as_of)
        f2, _ = features_from_aggregate(sym, daily[sym], agg, prev_session=date(2026, 9, 23), data_as_of=as_of)
        s1, s2 = S.score(f1, "NONE"), S.score(f2, "NONE")
        assert S.classify(f1, s1) == S.classify(f2, s2) and s1 == s2


def test_independent_processes_restart_one_component_only(tmp_path):
    """Real OS processes: restarting one component leaves the other's PID untouched."""
    from talonx_opportunity import supervise as SV
    env = dict(os.environ, TALONX_OPP_ROOT=str(tmp_path))
    SV.up(tmp_path, ("evaluator:LONG_TERM", "reporting"), env=env)
    deadline = time.time() + 60
    while time.time() < deadline and not (SV.is_running(tmp_path, "evaluator:LONG_TERM")
                                          and SV.is_running(tmp_path, "reporting")):
        time.sleep(0.5)
    rep_pid = SV._lock_pid(tmp_path, "reporting")
    old = SV._lock_pid(tmp_path, "evaluator:LONG_TERM")
    try:
        assert rep_pid and old
        SV.restart(tmp_path, "evaluator:LONG_TERM", env=env)
        deadline = time.time() + 60
        while time.time() < deadline and SV._lock_pid(tmp_path, "evaluator:LONG_TERM") in (None, old):
            time.sleep(0.5)
        assert SV._lock_pid(tmp_path, "evaluator:LONG_TERM") not in (None, old)
        assert SV._lock_pid(tmp_path, "reporting") == rep_pid          # untouched
        # the lock (PID) is written BEFORE record_start (version hash + git commit lookup); under load the restart's
        # deployment row can lag the PID -- wait for it instead of reading the first-start row (2026-09-25 flake)
        deadline = time.time() + 60
        lt = []
        while time.time() < deadline:
            deps = RuntimeStore(tmp_path, readonly=True).deployments()
            lt = [d for d in deps if d["component"] == "evaluator:LONG_TERM"]
            if len(lt) >= 2:
                break
            time.sleep(0.5)
        assert len(lt) == 2
        assert lt[-1]["classification"] == "OPERATIONS_ONLY" and lt[-1]["restart_only"] == 1
    finally:
        for n in ("evaluator:LONG_TERM", "reporting"):
            SV.stop(tmp_path, n, 30)


# --------------------------------------------------------------------------------------------- V2 release preflight
def test_continuous_allowlist_is_closed_and_strategy_free():
    from talonx_ops.prospective import preflight as pf
    fp_mod = __import__("research.scripts.task112_v2_release_fingerprint", fromlist=["_STRATEGY_FILES"])
    fp_files = {str(p.relative_to(Path(fp_mod.__file__).resolve().parents[2])).replace("\\", "/")
                for p in fp_mod._STRATEGY_FILES}
    files = set(pf.FREEZE_CONTINUOUS_ENGINE_FILES)
    assert not fp_files & files
    assert not [f for f in files if f.startswith("talonx_v2/") or f.startswith("talonx_quant/")]
    assert not [f for f in files if any(x in f for x in ("pricing", "provider_contract", "store.py", "paper",
                                                           "cluster_engine", "form4_source", "insider/", "ledger"))]
    assert "talonx_opportunity/discovery.py".startswith(pf.FREEZE_RESEARCH_LANE_PREFIXES)
    assert not "talonx_v2/service.py".startswith(pf.FREEZE_RESEARCH_LANE_PREFIXES)


def test_this_branch_still_passes_the_v2_frozen_release_check():
    """Every tracked change + untracked file since the frozen SHA must be inside the declared allowlists, so the
    V2 release preflight (`repo_head_matches_release`) stays READY on this branch."""
    from talonx_ops.prospective import preflight as pf
    run = lambda *a: subprocess.run(["git", *a], cwd=REPO, capture_output=True, text=True).stdout.split()  # noqa: E731
    if subprocess.run(["git", "merge-base", "--is-ancestor", "a56ec8c", "HEAD"], cwd=REPO).returncode != 0:
        pytest.skip("frozen release SHA not in history")
    src_suffix = (".py", ".ps1", ".sh", ".toml", ".cfg", ".ini", ".yml", ".yaml", ".md", ".txt", ".example")
    untracked_src = {f for f in run("ls-files", "--others", "--exclude-standard") if f.endswith(src_suffix)}
    changed = set(run("diff", "--name-only", "a56ec8c")) | untracked_src      # runtime *.db-shm/status json excluded
    allowed = lambda f: (f.startswith(pf.FREEZE_ALLOWED_PREFIXES) or f in pf.FREEZE_ALLOWED_FILES  # noqa: E731
                         or f in pf.FREEZE_OPS_HARDENING_FILES or f in pf.FREEZE_RELEASE_FIDELITY_FIX_FILES
                         or f in pf.FREEZE_SESSION03_HARDENING_FILES or f in pf.FREEZE_CONTINUOUS_ENGINE_FILES
                         or f in pf.FREEZE_SIGNAL_ROUTING_FIX_FILES or f in pf.FREEZE_OPERATOR_CONTROL_FILES
                         or f.startswith(pf.FREEZE_RESEARCH_LANE_PREFIXES))
    assert sorted(f for f in changed if not allowed(f)) == []


def test_frozen_release_does_not_import_the_opportunity_lane():
    for pkg in ("talonx_v2", "talonx_ops", "talonx_dispatch", "talonx_ingest"):
        for p in (REPO / pkg).rglob("*.py"):
            text = p.read_text(encoding="utf-8", errors="replace")
            assert "import talonx_opportunity" not in text and "from talonx_opportunity" not in text, p


# --------------------------------------------------------------------------------------------- 2026-09-25 live fixes
def test_supervisor_does_not_respawn_a_component_inside_its_startup_grace(tmp_path, monkeypatch):
    """Live finding 1: supervise() judged just-spawned components dead before they wrote their lock."""
    from talonx_opportunity import supervise as SV
    spawned = []
    monkeypatch.setattr(SV.subprocess, "Popen", lambda *a, **k: type("P", (), {"pid": 1})())
    SV.spawn(tmp_path, "reporting")                                    # as `up` does
    monkeypatch.setattr(SV, "spawn", lambda root, n, env=None: spawned.append(n) or 2)
    monkeypatch.setattr(SV, "is_running", lambda root, n: False)       # lock not written yet
    ticks = iter([False, True])
    monkeypatch.setattr(SV.time, "sleep", lambda s: None)
    SV.supervise(tmp_path, ("reporting",), should_stop=lambda: next(ticks))
    assert spawned == []                                               # no spurious second copy
    deps = RuntimeStore(tmp_path, readonly=True).deployments()
    assert deps[-1]["component"] == "supervisor" and deps[-1]["classification"] == "OPERATIONS_ONLY"


def test_supervisor_still_restarts_a_dead_component_after_grace(tmp_path, monkeypatch):
    from talonx_opportunity import supervise as SV
    spawned = []
    SV._SPAWNED_AT.pop("reporting", None)
    monkeypatch.setattr(SV, "spawn", lambda root, n, env=None: spawned.append(n) or 2)
    monkeypatch.setattr(SV, "is_running", lambda root, n: False)
    ticks = iter([False, True])
    monkeypatch.setattr(SV.time, "sleep", lambda s: None)
    SV.supervise(tmp_path, ("reporting",), should_stop=lambda: next(ticks))
    assert spawned == ["reporting"]


def test_up_deliver_status_resolves_like_the_notifier(tmp_path, monkeypatch, capsys):
    """Live finding 3: `up --deliver` must load .env before resolving RESEARCH (no false negative)."""
    import talonx_opportunity.__main__ as CLI
    from talonx_opportunity import supervise as SV
    monkeypatch.setattr(SV, "up", lambda root, names, env=None: {})
    called = []
    import talonx_premarket.__main__ as PM
    monkeypatch.setattr(PM, "_env", lambda *a, **k: called.append(1))
    monkeypatch.setenv("TALONX_OPP_ROOT", str(tmp_path))
    CLI.main(["up", "--deliver"])
    assert called and "LAB DELIVERY:" in capsys.readouterr().out


def test_live_budget_override_adds_setup_only_capacity_without_replay(tmp_path):
    from talonx_opportunity.config import LAB_NOTIFY_POLICY_V1
    from talonx_opportunity.notifier import NOTIFY_POLICY_OVERRIDES, selected_policy
    ov = selected_policy({"TALONX_OPP_NOTIFY_POLICY": "LAB_NOTIFY_POLICY_V1_LIVE_OVERRIDE_20260925"})
    assert (ov.total_new_per_window, ov.total_new_per_window - ov.setup_reserved) == (40, 15)
    assert ov.fingerprint() != LAB_NOTIFY_POLICY_V1.fingerprint() and selected_policy({}) is LAB_NOTIFY_POLICY_V1
    with pytest.raises(SystemExit):
        selected_policy({"TALONX_OPP_NOTIFY_POLICY": "ANYTHING_ELSE"})
    assert set(NOTIFY_POLICY_OVERRIDES) == {"LAB_NOTIFY_POLICY_V1_LIVE_OVERRIDE_20260925",
                                            "LAB_NOTIFY_POLICY_V1_PHASE_RESERVED_20260925",
                                            "LAB_NOTIFY_POLICY_V1_REGULAR_EXT_20260925"}
    # exhaust V1 (25 = 15 WATCH + 10 setups) and hold some of each
    pre = ([(f"W{i:02d}", "WATCH", "NEW", 50.0, "2026-09-24T08:30:00+00:00") for i in range(20)]
           + [(f"B{i:02d}", "BULLISH", "NEW", 70.0, "2026-09-24T08:40:00+00:00") for i in range(12)])
    _seed_events(tmp_path, pre)
    n1 = Notifier(root=tmp_path)
    n1.tick()
    before = n1.con.execute("SELECT event_id, decision, policy_version FROM decisions ORDER BY event_id").fetchall()
    assert n1._used("2026-09-24") == (25, 15)
    held = [r for r in before if r[1].startswith("BUDGET")]
    assert len(held) == 7
    # restart under the override: nothing already decided is re-evaluated (no backlog replay)
    n2 = Notifier(root=tmp_path, policy=ov)
    n2.tick()
    assert n2.con.execute("SELECT event_id, decision, policy_version FROM decisions ORDER BY event_id").fetchall() == before
    # later events: WATCH stays capped, only setups use the 15 extra slots
    post = ([(f"X{i:02d}", "WATCH", "NEW", 60.0, "2026-09-24T14:00:00+00:00") for i in range(3)]
            + [(f"S{i:02d}", "BEARISH", "NEW", 70.0, "2026-09-24T14:10:00+00:00") for i in range(16)])
    _seed_events(tmp_path, post)
    n2.tick()
    rows = {r["symbol"]: r["decision"] for r in n2.con.execute(
        "SELECT symbol, decision FROM decisions WHERE decided_utc IS NOT NULL AND symbol GLOB '[XS]*'")}
    assert all(rows[f"X{i:02d}"] == "BUDGET_EXHAUSTED_WATCH" for i in range(3))
    assert sum(d == "SELECTED" for s, d in rows.items() if s.startswith("S")) == 15
    assert sum(d == "BUDGET_EXHAUSTED_TOTAL" for s, d in rows.items() if s.startswith("S")) == 1
    assert n2._used("2026-09-24") == (40, 15)


def _seed_phase_events(root, specs):
    """specs: (symbol, classification, phase, at)."""
    s = OpportunityStore(root)
    for i, (sym, cls, ph, at) in enumerate(specs):
        cid = f"2026-09-24:{sym}:GAP_UP"
        s.upsert_candidate({"candidate_id": cid, "window_id": "2026-09-24", "symbol": sym, "family": "GAP_UP",
                            "state": cls, "classification": cls, "first_seen_utc": at, "first_seen_phase": ph,
                            "in_v2_scope": 0})
        s.add_event({"event_id": f"{cid}:NEW:{at}:{i}", "candidate_id": cid, "window_id": "2026-09-24", "symbol": sym,
                     "at_utc": at, "phase": ph, "event_type": "NEW", "classification": cls, "score": 70.0,
                     "features_json": "{}", "score_json": "{}", "provenance_json": "{}"})
    s.commit()
    s.close()


def test_phase_reserved_override_keeps_later_phase_capacity_without_replay(tmp_path):
    from talonx_opportunity.notifier import selected_policy
    pr = selected_policy({"TALONX_OPP_NOTIFY_POLICY": "LAB_NOTIFY_POLICY_V1_PHASE_RESERVED_20260925"})
    ov = selected_policy({"TALONX_OPP_NOTIFY_POLICY": "LAB_NOTIFY_POLICY_V1_LIVE_OVERRIDE_20260925"})
    assert pr.fingerprint() != ov.fingerprint()
    base = ([(f"W{i:02d}", "WATCH", "PREMARKET", "2026-09-24T09:00:00+00:00") for i in range(15)]
            + [(f"B{i:02d}", "BULLISH", "PREMARKET", "2026-09-24T09:10:00+00:00") for i in range(10)])
    _seed_phase_events(tmp_path, base + [("P00", "BULLISH", "PREMARKET", "2026-09-24T12:36:00+00:00")])
    n = Notifier(root=tmp_path, policy=ov)
    n.tick()
    assert n._used("2026-09-24") == (26, 15)                    # one extra PREMARKET slot used before the change
    before = n.con.execute("SELECT * FROM decisions ORDER BY event_id").fetchall()
    n2 = Notifier(root=tmp_path, policy=pr)
    n2.tick()
    assert n2.con.execute("SELECT * FROM decisions ORDER BY event_id").fetchall() == before    # no re-decision
    later = ([(f"P{i:02d}", "BEARISH", "PREMARKET", "2026-09-24T13:00:00+00:00") for i in range(1, 8)]
             + [("WX", "WATCH", "PREMARKET", "2026-09-24T13:01:00+00:00")]
             + [(f"R{i:02d}", "BULLISH", "REGULAR", "2026-09-24T14:00:00+00:00") for i in range(9)]
             + [(f"A{i:02d}", "BEARISH", "AFTER_HOURS", "2026-09-24T20:30:00+00:00") for i in range(5)])
    _seed_phase_events(tmp_path, later)
    n2.tick()
    d = {r["symbol"]: r["decision"] for r in n2.con.execute("SELECT symbol, decision FROM decisions")}
    pm = [d[f"P{i:02d}"] for i in range(1, 8)]
    assert pm.count("SELECTED") == 4 and pm.count("BUDGET_RESERVED_LATER_PHASE") == 3   # PREMARKET extra capped at 5
    assert d["WX"] == "BUDGET_EXHAUSTED_WATCH"
    rg = [d[f"R{i:02d}"] for i in range(9)]
    assert rg.count("SELECTED") == 7 and rg.count("BUDGET_RESERVED_LATER_PHASE") == 2  # REGULAR leaves 3
    ah = [d[f"A{i:02d}"] for i in range(5)]
    assert ah.count("SELECTED") == 3 and ah.count("BUDGET_EXHAUSTED_TOTAL") == 2
    assert n2._used("2026-09-24") == (40, 15)


def test_phase_reserve_rolls_unused_capacity_forward(tmp_path):
    from talonx_opportunity.notifier import selected_policy
    pr = selected_policy({"TALONX_OPP_NOTIFY_POLICY": "LAB_NOTIFY_POLICY_V1_PHASE_RESERVED_20260925"})
    base = ([(f"W{i:02d}", "WATCH", "PREMARKET", "2026-09-24T09:00:00+00:00") for i in range(15)]
            + [(f"B{i:02d}", "BULLISH", "PREMARKET", "2026-09-24T09:10:00+00:00") for i in range(10)]
            + [(f"R{i:02d}", "BULLISH", "REGULAR", "2026-09-24T14:00:00+00:00") for i in range(14)])
    _seed_phase_events(tmp_path, base)
    n = Notifier(root=tmp_path, policy=pr)
    n.tick()
    rg = [r["decision"] for r in n.con.execute("SELECT decision FROM decisions WHERE symbol GLOB 'R*'")]
    assert rg.count("SELECTED") == 12              # unused PREMARKET reserve rolled into REGULAR; 3 kept for AH


# ------------------------------------------------ outcome phase basis = causal data time (2026-09-25 F3 fix)
def _cand(first_seen, as_of):
    return {"first_seen_utc": first_seen.isoformat(), "first_data_as_of_utc": as_of.isoformat() if as_of else None}


def test_outcome_basis_uses_causal_data_phase_not_wall_clock():
    from talonx_opportunity.outcome_tracker import NOT_APPLICABLE_KIND, PRE_OPEN, SINCE_FIRST_SEEN, outcome_basis
    from talonx_opportunity.phases import phase_at, trading_window
    w = trading_window(U(9).date())
    # A: processed 13:35Z (wall REGULAR) from 13:20Z data -> PREMARKET data -> pre-open model
    assert phase_at(U(13, 35))[0] == "REGULAR"
    assert outcome_basis(_cand(U(13, 35), U(13, 20)), w) == (PRE_OPEN, U(13, 20), "PREMARKET")
    # B: processed 20:05Z (wall AFTER_HOURS) from 19:50Z data -> REGULAR data -> still measurable same day
    assert phase_at(U(20, 5))[0] == "AFTER_HOURS"
    assert outcome_basis(_cand(U(20, 5), U(19, 50)), w) == (SINCE_FIRST_SEEN, U(19, 50), "REGULAR")
    # C: true AFTER_HOURS data -> not applicable same day
    assert outcome_basis(_cand(U(20, 20), U(20, 5)), w) == (NOT_APPLICABLE_KIND, U(20, 5), "AFTER_HOURS")
    # data horizon exactly at the close: the last RTH bar was used, no regular minute remains -> not applicable
    assert outcome_basis(_cand(U(20, 15), U(20)), w)[0] == NOT_APPLICABLE_KIND
    # data horizon exactly at the open: only pre-open bars were used -> pre-open model
    assert outcome_basis(_cand(U(13, 45), U(13, 30)), w)[:2] == (PRE_OPEN, U(13, 30))
    # fallback: no causal data time recorded -> the wall-clock first sighting (previous behaviour)
    assert outcome_basis(_cand(U(20, 5), None), w)[0] == NOT_APPLICABLE_KIND
    assert outcome_basis(_cand(U(12), None), w)[0] == PRE_OPEN
    # ordinary cases unchanged
    assert outcome_basis(_cand(U(9), U(8, 45)), w)[0] == PRE_OPEN
    assert outcome_basis(_cand(U(15), U(14, 45)), w) == (SINCE_FIRST_SEEN, U(14, 45), "REGULAR")


def test_outcome_after_hours_wall_clock_with_regular_data_is_measured(eng):
    """Case B end-to-end: first discovered at 20:05Z from 19:50Z bars -> measured, not NOT_APPLICABLE_SAME_DAY."""
    _step(eng, U(20, 5))
    cands = {c["symbol"]: c for c in _cands(eng["root"])}
    assert "BBB" in cands and cands["BBB"]["first_seen_phase"] == "AFTER_HOURS"
    eng["clock"].t = U(20, 30)
    ot = OutcomeTracker(root=eng["root"], data=eng["data"], clock=eng["clock"])
    ot.tick()
    row = dict(ot.con.execute("SELECT * FROM outcomes WHERE symbol='BBB'").fetchone())
    assert row["model"] == "SINCE_FIRST_SEEN_V1" and row["status"] != "NOT_APPLICABLE_SAME_DAY"
    assert row["ref_time_utc"] == cands["BBB"]["first_data_as_of_utc"]


def test_regular_extension_keeps_held_cohort_watch_cap_and_after_hours_reserve(tmp_path):
    from talonx_opportunity.notifier import selected_policy
    pr = selected_policy({"TALONX_OPP_NOTIFY_POLICY": "LAB_NOTIFY_POLICY_V1_PHASE_RESERVED_20260925"})
    ext = selected_policy({"TALONX_OPP_NOTIFY_POLICY": "LAB_NOTIFY_POLICY_V1_REGULAR_EXT_20260925"})
    assert (ext.total_new_per_window, ext.total_new_per_window - ext.setup_reserved) == (75, 15)
    base = ([(f"W{i:02d}", "WATCH", "PREMARKET", "2026-09-24T09:00:00+00:00") for i in range(15)]
            + [(f"B{i:02d}", "BULLISH", "PREMARKET", "2026-09-24T09:10:00+00:00") for i in range(13)]
            + [(f"R{i:02d}", "BULLISH", "REGULAR", "2026-09-24T13:50:00+00:00") for i in range(9)]
            + [(f"H{i:02d}", "BEARISH", "REGULAR", "2026-09-24T13:55:00+00:00") for i in range(17)])
    _seed_phase_events(tmp_path, base)
    n = Notifier(root=tmp_path, policy=pr)
    n.tick()
    assert n._used("2026-09-24") == (37, 15)
    before = n.con.execute("SELECT * FROM decisions ORDER BY event_id").fetchall()
    held = [r["symbol"] for r in n.con.execute("SELECT symbol FROM decisions WHERE decision='BUDGET_RESERVED_LATER_PHASE'")]
    assert sorted(held) == [f"H{i:02d}" for i in range(17)]
    n2 = Notifier(root=tmp_path, policy=ext)
    n2.tick()
    assert n2.con.execute("SELECT * FROM decisions ORDER BY event_id").fetchall() == before     # held cohort frozen
    later = ([(f"N{i:02d}", "BULLISH", "REGULAR", "2026-09-24T14:10:00+00:00") for i in range(40)]
             + [("WX", "WATCH", "REGULAR", "2026-09-24T14:10:00+00:00")]
             + [(f"A{i:02d}", "BEARISH", "AFTER_HOURS", "2026-09-24T20:30:00+00:00") for i in range(4)])
    _seed_phase_events(tmp_path, later)
    n2.tick()
    d = {r["symbol"]: r["decision"] for r in n2.con.execute("SELECT symbol, decision FROM decisions")}
    nd = [d[f"N{i:02d}"] for i in range(40)]
    assert nd.count("SELECTED") == 35 and nd.count("BUDGET_RESERVED_LATER_PHASE") == 5    # 75-37-3 for REGULAR
    assert d["WX"] == "BUDGET_EXHAUSTED_WATCH"
    ah = [d[f"A{i:02d}"] for i in range(4)]
    assert ah.count("SELECTED") == 3 and ah.count("BUDGET_EXHAUSTED_TOTAL") == 1
    assert n2._used("2026-09-24") == (75, 15)


def test_outcome_rows_are_already_direction_adjusted_so_tools_must_not_flip_again():
    """Contract validation tooling relies on (2026-09-25: a live study script flipped GAP_DOWN a second time).
    A GAP_DOWN candidate whose price FALLS must produce POSITIVE ret/MFE in the stored row."""
    from talonx_opportunity.outcome_tracker import since_first_seen
    ref_t = U(14)
    bars = [{"t": (ref_t + timedelta(minutes=i)).strftime("%Y-%m-%dT%H:%M:%SZ"), "o": 10 - 0.02 * i, "h": 10 - 0.02 * i + 0.01,
             "l": 10 - 0.02 * i - 0.01, "c": 10 - 0.02 * i, "v": 1000} for i in range(0, 90)]
    down = since_first_seen(family="GAP_DOWN", ref_price=10.0, ref_time=ref_t, prev_close=11.0, bars=bars, close_utc=U(20))
    up = since_first_seen(family="GAP_UP", ref_price=10.0, ref_time=ref_t, prev_close=9.0, bars=bars, close_utc=U(20))
    assert down["ret_30m_pct"] > 0 and down["ret_1h_pct"] > 0 and down["mfe_pct"] > 0
    assert up["ret_30m_pct"] < 0 and abs(up["ret_30m_pct"] + down["ret_30m_pct"]) < 1e-9


# --------------------------------------------- status semantics: a long tick is BUSY, not DOWN (2026-09-25, reporting)
def _row(pid, age_s, name="discovery", state="RUNNING"):
    now = datetime(2026, 9, 25, 15, 18, tzinfo=timezone.utc)
    return {"name": name, "pid": pid, "state": state,
            "heartbeat_utc": (now - timedelta(seconds=age_s)).isoformat()}, now


def _lock(root, name, pid):
    (root / "locks").mkdir(parents=True, exist_ok=True)
    (root / "locks" / (name.replace(":", "_") + ".lock")).write_text(str(pid))


def test_live_pid_old_heartbeat_with_lock_is_busy_long_scan_not_down(tmp_path):
    from talonx_ops.opportunity_read import component_health
    me = os.getpid()
    _lock(tmp_path, "discovery", me)
    row, now = _row(me, 244)
    assert component_health(row, now, root=tmp_path) == "BUSY_LONG_SCAN"


def test_dead_pid_is_down(tmp_path):
    from talonx_ops.opportunity_read import component_health
    row, now = _row(999_999_991, 20)
    assert component_health(row, now, root=tmp_path) == "DOWN"


def test_alive_but_heartbeat_beyond_ceiling_is_stale_heartbeat(tmp_path):
    from talonx_ops.opportunity_read import component_health
    me = os.getpid()
    _lock(tmp_path, "discovery", me)
    row, now = _row(me, 1200)
    assert component_health(row, now, root=tmp_path) == "STALE_HEARTBEAT"


def test_old_heartbeat_with_a_foreign_lock_owner_is_stale_not_busy(tmp_path):
    from talonx_ops.opportunity_read import component_health
    me = os.getpid()
    _lock(tmp_path, "discovery", me + 1)
    row, now = _row(me, 244)
    assert component_health(row, now, root=tmp_path) == "STALE_HEARTBEAT"


def test_fresh_heartbeat_is_up(tmp_path):
    from talonx_ops.opportunity_read import component_health
    row, now = _row(os.getpid(), 12)
    assert component_health(row, now, root=tmp_path) == "UP"
