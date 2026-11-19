"""DTU_V2 live-universe floor (owner decision 2026-10-04): as-traded D-1 close >= $5 and ADV20 >= $20M (both inclusive),
20 completed XNYS sessions, prior-session cutoff, explicit data-quality reasons, one authoritative membership for
ingestion / discovery / Sentinel, management of existing work after removal, tracker segmentation, report
reconciliation, rollback. No network (injected fetchers)."""
from __future__ import annotations

import csv
import json
import sqlite3
from datetime import date, datetime, timedelta, timezone

import pytest

from talonx_opportunity import universe_tiers as U
from talonx_opportunity.phases import trading_window

UTC = timezone.utc
W = trading_window(date(2026, 10, 5))                    # Monday; reference session = Friday 2026-10-02
REF = W.reference_session.isoformat()
SESS = U.completed_sessions(REF, 20)
V2 = U.LiveFloorPolicy(core_size=2)


def bars(close, adv_usd, sessions=SESS, *, drop=(), extra=()):
    """One as-traded bar per session with close x volume == adv_usd (so ADV20 == adv_usd exactly)."""
    out = [{"t": f"{d}T04:00:00Z", "o": close, "h": close, "l": close, "c": close, "v": adv_usd / close}
           for d in sessions if d not in drop]
    return out + list(extra)


def universe():
    members = [{"symbol": s, "status": "ELIGIBLE", "cik": f"{i:010d}"} for i, s in
               enumerate(["BIG", "MID", "EDGE", "CHEAP", "THIN", "BOTH", "GAPPY", "STALE", "NEW"])]
    members.append({"symbol": "SPYETF", "status": "EXCLUDED", "reason": "ETF", "cik": None})
    live = {"BIG": bars(100.0, 5e8), "MID": bars(50.0, 1e8), "EDGE": bars(5.0, 20_000_000.0),
            "CHEAP": bars(4.99, 5e7), "THIN": bars(30.0, 19_999_999.0), "BOTH": bars(2.0, 1e6),
            "GAPPY": bars(40.0, 9e7, drop=(SESS[5],)), "STALE": bars(40.0, 9e7, drop=(REF,)), "NEW": []}
    # V1 reference data (split-adjusted table): identical values, so only the live floor differs from V1
    daily = {s: [dict(b) for b in v] or bars(40.0, 9e7) for s, v in live.items()}
    daily["GAPPY"] = bars(40.0, 9e7)
    daily["STALE"] = bars(40.0, 9e7)
    return members, daily, live


def rows_v2(**kw):
    members, daily, live = universe()
    return {r["symbol"]: r for r in U.classify_members(members, daily, REF, V2, live=live, sessions=SESS, **kw)}


# ------------------------------------------------------------------------------------------------ thresholds
def test_inclusive_boundaries_and_combined_exclusions():
    r = rows_v2()
    assert r["EDGE"]["state"] in (U.CORE, U.EVENT_ELIGIBLE) and r["EDGE"]["price"] == 5.0          # exactly $5 / $20M
    assert r["EDGE"]["adv20"] == 20_000_000.0
    assert (r["CHEAP"]["state"], r["CHEAP"]["reason"]) == (U.AUTO_EXCLUDED, U.L_PRICE)              # $4.99 only
    assert (r["THIN"]["state"], r["THIN"]["reason"]) == (U.AUTO_EXCLUDED, U.L_LIQ)                  # $19,999,999 only
    assert (r["BOTH"]["state"], r["BOTH"]["reason"]) == (U.AUTO_EXCLUDED, U.L_BOTH)
    assert r["SPYETF"]["state"] == U.STRUCTURAL                                                     # retained rule
    assert [s for s, x in r.items() if x["state"] == U.CORE] == ["BIG", "MID"]                     # Core kept (rank)
    assert {U.floor_category(x["state"], x["reason"]) for x in r.values()} <= set(U.CATEGORIES)


def test_policy_floors_are_owner_values_and_v1_fingerprint_is_unchanged():
    p = U.DTU_V2
    assert (p.live_min_close_usd, p.live_min_adv20_usd, p.live_sessions) == (5.0, 20_000_000.0, 20)
    assert U.DTU_V1.fingerprint() == "da27de22a3bb839a"                      # the live V1 fingerprint (rollback)
    assert U.policy_from_env({}) is U.DTU_V2 and U.policy_from_env({U.POLICY_ENV: "dtu_v1"}) is U.DTU_V1
    assert U.DTU_V2.fingerprint() != U.DTU_V1.fingerprint()
    with pytest.raises(SystemExit):
        U.policy_from_env({U.POLICY_ENV: "DTU_V3"})


# ------------------------------------------------------------------------------------------------ time / calendar
def test_prior_session_cutoff_weekend_holiday_and_partial_session():
    assert SESS[-1] == "2026-10-02" and len(SESS) == 20 and "2026-10-03" not in SESS            # weekend skipped
    # Thanksgiving 2025 (holiday 11-27) and the 11-28 early close: holiday absent, early close is a completed session
    tg = U.completed_sessions("2025-12-01", 20)
    assert "2025-11-27" not in tg and "2025-11-28" in tg and tg[-1] == "2025-12-01"
    # bars of session D (in progress / partial), of a weekend date and after D-1 are ignored -> no lookahead
    later = [{"t": "2026-10-05T04:00:00Z", "c": 1.0, "v": 1.0}, {"t": "2026-10-03T04:00:00Z", "c": 1.0, "v": 1.0}]
    close, adv, n, why = U.live_eligibility(bars(10.0, 3e7, extra=later), SESS, V2)
    assert (close, adv, n, why) == (10.0, 3e7, 20, "")


def test_live_fetch_window_ends_before_the_session_and_retries_failures(tmp_path):
    calls = []

    def fetch(symbols, start, end):
        calls.append((list(symbols), start, end))
        failed = {"B"} if len(calls) == 1 else set()
        return {s: bars(10.0, 3e7) for s in symbols if s not in failed}, failed, 1, "fake raw"
    con = sqlite3.connect(tmp_path / "market.db")
    d = U.DTU(con, policy=V2, live_fetch=fetch, clock=lambda: datetime(2026, 10, 5, 0, 5, tzinfo=UTC))
    now = datetime(2026, 10, 5, 0, 5, tzinfo=UTC)
    r1 = d.ensure_live_daily(W, ["A", "B"], now)
    assert r1["complete"] is False and calls[0][1] == datetime(2026, 9, 4, tzinfo=UTC)       # first of 20 sessions
    assert calls[0][2] < datetime(2026, 10, 5, tzinfo=UTC)                                    # never a bar of D
    r2 = d.ensure_live_daily(W, ["A", "B"], now)
    assert r2["complete"] is True and calls[1][0] == ["B"]                                    # only the failed batch
    assert d.ensure_live_daily(W, ["A", "B"], now) == {"complete": True, "fetched": 0} and len(calls) == 2
    live, failed, sessions = d.live_inputs(W.window_id)
    assert set(live) == {"A", "B"} and failed == set() and sessions == SESS


# ------------------------------------------------------------------------------------------------ 20 sessions / data
def test_twenty_session_mean_and_data_quality_reasons():
    mixed = [{"t": f"{d}T04:00:00Z", "c": 10.0, "v": (1e6 if i < 10 else 3e6)} for i, d in enumerate(SESS)]
    older = [{"t": "2026-09-03T04:00:00Z", "c": 10.0, "v": 1e9}]                         # 21st session: excluded
    assert U.live_eligibility(older + mixed, SESS, V2)[1:3] == (2e7, 20)                 # mean of 1e7 x10, 3e7 x10
    r = rows_v2()
    assert r["GAPPY"]["reason"] == f"{U.D_INSUFF}_19_OF_20" and r["GAPPY"]["state"] == U.AUTO_EXCLUDED
    assert r["STALE"]["reason"] == U.D_STALE and r["STALE"]["state"] == U.AUTO_EXCLUDED
    assert r["NEW"]["reason"] == U.D_NONE
    assert U.live_eligibility([{"t": f"{REF}T04:00:00Z", "c": 0, "v": 5}], SESS, V2)[3].startswith(U.D_INVALID)
    assert U.live_eligibility([{"t": f"{REF}T04:00:00Z", "c": "x", "v": 5}], SESS, V2)[3].startswith(U.D_INVALID)
    r = rows_v2(live_failed={"BIG"})
    assert (r["BIG"]["state"], r["BIG"]["reason"]) == (U.AUTO_EXCLUDED, U.D_FETCH)        # never silently included
    with pytest.raises(ValueError):                                                       # no inputs -> no snapshot
        members, daily, _ = universe()
        U.classify_members(members, daily, REF, V2)


# ------------------------------------------------------------------------------------------------ one membership
def _built(tmp_path, positions=(), readers=None):
    members, daily, live = universe()
    con = sqlite3.connect(tmp_path / "market.db")
    rd = {"open_candidates": lambda w: [], "signals_today": lambda w: [], "positions": lambda w: set(positions)}
    rd.update(readers or {})
    d = U.DTU(con, policy=V2, clock=lambda: datetime(2026, 10, 5, 14, 0, tzinfo=UTC), readers=rd,
              live_fetch=lambda s, a, b: ({x: live.get(x, []) for x in s}, set(), 1, "fake raw"),
              snapshot_fetch=lambda s: ({}, 1, []), edgar_fetch=lambda: [])
    base = [m["symbol"] for m in members if m["status"] == "ELIGIBLE"]
    d.ensure_live_daily(W, base, datetime(2026, 10, 5, 0, 5, tzinfo=UTC))
    return d, con, members, daily, base


def test_one_authoritative_membership_for_ingestion_discovery_and_sentinel(tmp_path):
    d, con, members, daily, base = _built(tmp_path)
    fetch, last = d.active_symbols(W, base, members=members, daily=daily,
                                   sip_as_of=datetime(2026, 10, 5, 13, 45, tzinfo=UTC), operator_added=set(),
                                   operator_excluded=set(), v2_forced=set())
    assert last["fallback"] is None and fetch == ["BIG", "MID"]                           # Core only, no sub-floor
    snap = d.snapshot(W.window_id)
    qualifying = {s for s, r in snap.items() if r["state"] in (U.CORE, U.EVENT_ELIGIBLE)}
    assert qualifying == {"BIG", "MID", "EDGE"}
    con.commit()
    assert U.read_admission(tmp_path, W.window_id, V2) == qualifying                     # discovery's admission
    assert U.read_admission(tmp_path, W.window_id, U.DTU_V2) is None                     # other policy -> fail closed
    from talonx_ops.operator_control import universe_view as UV
    txt = UV.summary_text(UV.UniverseView(tmp_path), "H")                                 # Sentinel reads the same rows
    assert "Core: 2" in txt and "Event-eligible: 1" in txt and "Auto-excluded: 6" in txt


def test_snapshot_is_rebuilt_when_the_policy_changes_inside_a_window(tmp_path):
    d, con, members, daily, base = _built(tmp_path)
    d.ensure_snapshot(W, members, daily)
    assert d.snapshot(W.window_id)["CHEAP"]["state"] == U.AUTO_EXCLUDED
    v1 = U.DTU(con, policy=U.DTUPolicy(core_size=2), clock=d.clock)                        # rollback mid-window
    v1.ensure_snapshot(W, members, daily)
    assert v1.snapshot(W.window_id)["CHEAP"]["state"] == U.EVENT_ELIGIBLE
    assert con.execute("SELECT reason FROM dtu_transitions WHERE symbol='*'").fetchone()[0] == \
        "SNAPSHOT_REBUILT_POLICY_CHANGE"


# ------------------------------------------------------------------------------------------------ management
def test_removed_symbol_with_position_or_open_setup_stays_fetched(tmp_path):
    d, con, members, daily, base = _built(tmp_path, positions={"CHEAP"}, readers={
        "open_candidates": lambda w: [("THIN", "BULLISH_SETUP", "x", "2026-10-02")]})
    fetch, _ = d.active_symbols(W, base, members=members, daily=daily,
                                sip_as_of=datetime(2026, 10, 5, 13, 45, tzinfo=UTC), operator_added=set(),
                                operator_excluded=set(), v2_forced={"BOTH"})
    assert {"CHEAP", "THIN", "BOTH"} <= set(fetch)                                      # position / setup / V2 scope
    con.commit()
    adm = U.read_admission(tmp_path, W.window_id, V2)
    assert not ({"CHEAP", "THIN", "BOTH"} & adm)                                          # ...but never admissible
    _, states = U.resolve(d.snapshot(W.window_id), now="2026-10-05T14:00:00+00:00", promotions=[],
                          operator_added=set(), operator_excluded=set(), v2_forced=set(), positions={"CHEAP"},
                          protections={"THIN": U.P_SETUP})
    assert states["CHEAP"][1] == U.P_POSITION and states["THIN"] == (U.EVENT_PROMOTED, U.P_SETUP)
    # an earlier-window 8-K promotion does not re-admit a removed symbol
    _, st2 = U.resolve(d.snapshot(W.window_id), now="2026-10-05T14:00:00+00:00", promotions=[
        {"symbol": "CHEAP", "reason": U.SEC_8K, "started_utc": "2026-10-02T15:00:00+00:00",
         "expires_utc": "2026-10-07T00:00:00+00:00"}], operator_added=set(), operator_excluded=set(),
        v2_forced=set(), positions=set(), protections={})
    assert st2["CHEAP"] == (U.AUTO_EXCLUDED, U.L_PRICE)


def _feat(sym, now, gap=8.0):
    from talonx_premarket.features import Features
    return Features(symbol=sym, data_as_of_utc=now.isoformat(), prev_session=REF, prev_close=10.0,
                    prev_high=10.2, prev_low=9.8, atr20_pct=2.0, adv20_shares=5e6, adv20_dollars=5e7, trend5_pct=1.0,
                    last_price=10.0 * (1 + gap / 100), last_bar_utc=(now - timedelta(minutes=1)).isoformat(),
                    staleness_min=1.0, pm_high=11.0, pm_low=10.0, pm_volume=2e6, pm_dollars=2e7, pm_bars=200,
                    pm_trades=5000, gap_pct=gap, activity_adv_fraction=0.4, range_position="ABOVE_PREV_HIGH",
                    range_distance_pct=5.0)


def _discovery(tmp_path, monkeypatch, admissible, clock):
    from talonx_opportunity import discovery as D
    monkeypatch.setenv(U.MODE_ENV, "ACTIVE")
    monkeypatch.delenv(U.POLICY_ENV, raising=False)                                       # default = DTU_V2
    monkeypatch.setattr(D, "features_from_aggregate", lambda sym, *a, **k: (_feat(sym, clock["t"]), ""))
    monkeypatch.setattr(D.C, "effective_capability", lambda phase, probe: type("Cap", (), {
        "usable_for_discovery": True, "as_dict": lambda self: {}, "provider": "p", "feed": "f",
        "delay_minutes": 15, "adjustment": "split"})())
    members = [{"symbol": s, "status": "ELIGIBLE", "cik": None} for s in ("OK", "OUT", "HELD")]

    def state(wid):
        return {"state": {"as_of_utc": (clock["t"] - timedelta(minutes=16)).isoformat(), "incomplete_json": "[]",
                          "cycle_utc": clock["t"].isoformat()}, "members": members, "daily": {}, "aggs": {},
                "probes": {"REGULAR": {"ok": True}}, "dtu": {"symbols": {"OK", "OUT", "HELD"}, "fallback": None,
                                                             "cycle_utc": "t", "counts": {}}}
    return D.Discovery(root=tmp_path, clock=lambda: clock["t"], state_reader=state,
                       admission_reader=lambda wid: admissible)


def test_discovery_blocks_new_identities_outside_the_floor_but_keeps_managing_existing(tmp_path, monkeypatch):
    clock = {"t": datetime(2026, 10, 5, 14, 0, tzinfo=UTC)}
    d = _discovery(tmp_path, monkeypatch, {"OK", "HELD"}, clock)
    d.tick()
    st = d.store
    first = {c["symbol"] for c in st.active_candidates()}
    assert first == {"OK", "HELD"}                                                        # OUT never admitted
    f = json.loads(st.con.execute("SELECT funnel_json FROM scans ORDER BY decision_utc DESC").fetchone()[0])
    assert f["ADMISSION_BLOCKED_LIVE_FLOOR"] == 1 and f["DTU"]["policy"] == "DTU_V2_LIVE_FLOOR"
    # HELD leaves the universe (next window's snapshot) while its identity is open: still observed and managed
    d2 = _discovery(tmp_path, monkeypatch, {"OK"}, clock)
    clock["t"] += timedelta(minutes=5)
    d2.tick()
    held = [c for c in d2.store.active_candidates() if c["symbol"] == "HELD"][0]
    assert held["last_observed_utc"] == clock["t"].isoformat()                            # lifecycle continues
    assert "OUT" not in {c["symbol"] for c in d2.store.active_candidates()}


def test_discovery_fails_closed_without_a_snapshot_of_the_running_policy(tmp_path, monkeypatch):
    clock = {"t": datetime(2026, 10, 5, 14, 0, tzinfo=UTC)}
    d = _discovery(tmp_path, monkeypatch, None, clock)
    d.tick()
    assert d.store.active_candidates() == []
    f = json.loads(d.store.con.execute("SELECT funnel_json FROM scans").fetchone()[0])
    assert f["DTU"]["admission"] == "FAIL_CLOSED_NO_SNAPSHOT" and f["ADMISSION_BLOCKED_LIVE_FLOOR"] == 3


def test_outcome_tracking_does_not_depend_on_the_universe():
    src = open("talonx_opportunity/outcome_tracker.py", encoding="utf-8").read()
    assert "universe_tiers" not in src and "dtu" not in src.lower()                      # own bars per live candidate


# ------------------------------------------------------------------------------------------------ ingestion
def test_ingestion_builds_snapshot_and_report_at_window_start_before_premarket(tmp_path, monkeypatch):
    from talonx_opportunity import ingestion as I
    from talonx_premarket.alpaca_data import FetchResult
    members, daily, live = universe()

    class Data:
        _headers, requests, errors = {}, 0, []

        def bars_ex(self, syms, timeframe, **kw):
            assert timeframe == "1Day"                                                 # OVERNIGHT: no 1-min fetch
            return FetchResult(bars={s: daily.get(s, []) for s in syms})
    now = datetime(2026, 10, 5, 0, 10, tzinfo=UTC)                                     # OVERNIGHT of window 10-05
    dtu = U.DTU(sqlite3.connect(":memory:"), policy=V2)
    ing = I.Ingestion(data=Data(), root=tmp_path, clock=lambda: now, universe_loader=lambda: (members, "t"),
                      dtu_mode=U.ACTIVE, dtu=dtu)
    ing._dtu = U.DTU(ing.con, root=tmp_path, policy=V2, clock=lambda: now,
                     live_fetch=lambda s, a, b: ({x: live.get(x, []) for x in s}, set(), 1, "fake raw"),
                     readers={"open_candidates": lambda w: [], "signals_today": lambda w: [],
                              "positions": lambda w: set()})
    monkeypatch.setattr(ing, "probe", lambda phase, now: {"ok": False})
    import talonx_premarket.__main__ as M
    monkeypatch.setattr(M, "_v2_scope", lambda x: {"BOTH"})
    ing.tick()
    assert ing.dtu_prep["reconciled"] is True and ing.dtu_prep["counts"]["qualifying"] == 3
    rep = json.loads((tmp_path / "universe_reports" / "2026-10-05" / "universe_2026-10-05.json").read_text())
    assert rep["meta"]["policy_version"] == "DTU_V2_LIVE_FLOOR" and rep["meta"]["sessions"] == SESS
    assert rep["protected"] == {"BOTH": "V2_EXECUTION_SCOPE"}


# ------------------------------------------------------------------------------------------------ report
def test_report_counts_reconcile_to_the_symbol_lists(tmp_path):
    members, daily, live = universe()
    snap = rows_v2()
    prev = {r["symbol"]: r for r in U.classify_members(members, daily, REF, U.DTUPolicy(core_size=2))}
    rep = U.window_report(snap, {"window_id": W.window_id, "reference_session": REF, "policy_version": "DTU_V2",
                                 "min_close_usd": 5.0, "min_adv20_usd": 2e7, "sessions_required": 20,
                                 "snapshot_version": "v"}, prev, {"CHEAP": U.P_POSITION})
    c = rep["counts"]
    assert rep["reconciled"] and c["qualifying"] == 3 and c["previous_pool"] == 9
    assert (c["retained"], c["added"], c["removed"]) == (3, 0, 6)
    assert c["removed_by_category"] == {"PRICE_ONLY": 1, "LIQUIDITY_ONLY": 1, "PRICE_AND_LIQUIDITY": 1,
                                        "DATA_QUALITY": 3, "RETAINED_V1_RULE": 0, "STRUCTURAL": 0}
    assert c["protected_not_qualifying"] == 1
    paths = U.write_report(rep, tmp_path / "r")
    rows = list(csv.DictReader(open(paths["csv"], encoding="utf-8")))
    assert len(rows) == c["universe_members"] == 10
    for k, n in c["categories"].items():
        assert sum(1 for x in rows if x["category"] == k) == n                             # file == counts
    txt = open(paths["summary"], encoding="utf-8").read()
    assert "Qualifying: 3" in txt and "removed 6" in txt and "not a profitability claim" in txt


# ------------------------------------------------------------------------------------------------ trackers
def test_vr_tracker_labels_each_window_with_its_universe_segment(tmp_path):
    from talonx_paperperf import vr_live as VL
    con = sqlite3.connect(tmp_path / "market.db")
    con.executescript(U.SCHEMA)
    con.execute("INSERT INTO dtu_snapshots VALUES ('2026-10-02','v','2026-10-01','t',1200,'{}',?)",
                (U.DTU_V1.fingerprint(),))
    con.execute("INSERT INTO dtu_snapshots VALUES ('2026-10-05','v','2026-10-02','t',1200,'{}',?)",
                (U.DTU_V2.fingerprint(),))
    con.commit()
    assert VL.universe_segment("2026-10-02", tmp_path) == "DTU_V1"
    assert VL.universe_segment("2026-10-05", tmp_path) == "DTU_V2"
    assert VL.universe_segment("2026-09-25", tmp_path) == "UNKNOWN_NO_DTU_SNAPSHOT"
    src = open("talonx_paperperf/vr_live.py", encoding="utf-8").read()
    assert '"oe_universe_segment": universe_segment(wid)' in src and "--until" in src     # end date untouched
    assert 'date(2026, 10, 16)' in src
