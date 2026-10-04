"""Dynamic Tradable Universe (DTU_V1): snapshot, Core, event tier, TTL, operator precedence, position/intent safety,
WATCH protection bound, fail-safe, determinism, upstream application in ingestion + discovery, restart persistence,
Sentinel read-only views. No network (injected fetchers)."""
from __future__ import annotations

import json
import sqlite3
from datetime import date, datetime, timedelta, timezone

import pytest

from talonx_opportunity import universe_tiers as U
from talonx_opportunity.phases import trading_window

UTC = timezone.utc
W = trading_window(date(2026, 9, 29))                    # reference session 2026-09-28
REF = W.reference_session.isoformat()


def daily_for(price, adv_usd, n=20):
    v = adv_usd / price
    days = [(date(2026, 9, 28) - timedelta(days=i)) for i in range(n * 2) if (date(2026, 9, 28) - timedelta(days=i)).weekday() < 5][:n]
    return [{"t": f"{d.isoformat()}T04:00:00Z", "o": price, "h": price, "l": price, "c": price, "v": v} for d in sorted(days)]


def universe(n_liquid=5):
    members, daily = [], {}
    for i in range(n_liquid):                               # L0 most liquid ... L{n-1}
        s = f"L{i}"
        members.append({"symbol": s, "status": "ELIGIBLE", "cik": f"{i:010d}"})
        daily[s] = daily_for(20.0, 1e8 / (i + 1))
    members += [{"symbol": "PENNY", "status": "ELIGIBLE", "cik": "0000000100"},
                {"symbol": "THIN", "status": "ELIGIBLE", "cik": "0000000101"},
                {"symbol": "WARR", "status": "EXCLUDED", "reason": "WARRANT", "cik": None}]
    daily["PENNY"] = daily_for(0.5, 5e6)
    daily["THIN"] = daily_for(10.0, 2e5)
    return members, daily


def policy(core=2):
    return U.DTUPolicy(core_size=core)


def test_snapshot_classification_is_causal_and_deterministic():
    members, daily = universe()
    daily["L0"] = daily["L0"] + [{"t": "2026-09-29T04:00:00Z", "o": 1, "h": 1, "l": 1, "c": 1, "v": 1e12}]  # future bar
    rows = {r["symbol"]: r for r in U.classify_members(members, daily, REF, policy(2))}
    assert (rows["L0"]["state"], rows["L0"]["core_rank"], rows["L0"]["prev_close"]) == (U.CORE, 1, 20.0)  # future ignored
    assert rows["L1"]["state"] == U.CORE and rows["L2"]["state"] == U.EVENT_ELIGIBLE and rows["L2"]["core_rank"] == 3
    assert (rows["PENNY"]["state"], rows["PENNY"]["reason"]) == (U.AUTO_EXCLUDED, "BELOW_V1_PRICE_FLOOR")
    assert (rows["THIN"]["state"], rows["THIN"]["reason"]) == (U.AUTO_EXCLUDED, "BELOW_V1_ADV20_FLOOR")
    assert rows["WARR"]["state"] == U.STRUCTURAL
    assert U.classify_members(members, daily, REF, policy(2)) == U.classify_members(members, daily, REF, policy(2))


def _snap():
    members, daily = universe()
    return {r["symbol"]: {**r, "snapshot_version": "v"} for r in U.classify_members(members, daily, REF, policy(2))}


def _res(**kw):
    base = dict(now="2026-09-29T15:00:00+00:00", promotions=[], operator_added=set(), operator_excluded=set(),
                v2_forced=set(), positions=set(), protections={})
    base.update(kw)
    return U.resolve(_snap(), **base)


def test_core_plus_promotion_and_ttl_expiry():
    act, st = _res()
    assert act == ["L0", "L1"] and st["L3"] == (U.EVENT_ELIGIBLE, "ADV20_RANK_4_OUTSIDE_CORE_2")
    p = [{"symbol": "L3", "reason": U.GAP, "started_utc": "2026-09-29T14:00:00+00:00",
          "expires_utc": "2026-09-30T00:00:00+00:00"}]
    act, st = _res(promotions=p)
    assert "L3" in act and st["L3"] == (U.EVENT_PROMOTED, U.GAP)
    act, _ = _res(promotions=p, now="2026-09-30T00:00:00+00:00")            # TTL expired -> back to EVENT_ELIGIBLE
    assert "L3" not in act
    act, _ = _res(promotions=p, now="2026-09-29T13:59:00+00:00")            # not yet started
    assert "L3" not in act


def test_operator_precedence_and_position_safety():
    act, st = _res(operator_excluded={"L0"})
    assert "L0" not in act and st["L0"] == (U.OPERATOR_EXCLUDED, "OPERATOR_EXCLUDED")
    act, st = _res(operator_added={"L4", "NEWX"})
    assert {"L4", "NEWX"} <= set(act) and st["NEWX"][1] == "OPERATOR_ADDED_OUTSIDE_BASE"
    act, st = _res(operator_added={"PENNY"})                                 # operator add bypasses ranking/floors
    assert "PENNY" in act
    act, st = _res(operator_excluded={"L3"}, positions={"L3"})              # position/intent beats exclusion
    assert "L3" in act and st["L3"][1] == U.P_POSITION
    act, _ = _res(v2_forced={"L4"})
    assert "L4" in act


def test_watch_protection_is_bounded_to_its_creation_window():
    class Clock:
        t = datetime(2026, 9, 29, 15, 0, tzinfo=UTC)
    con = sqlite3.connect(":memory:")
    cands = [("L3", "WATCH", "x", "2026-09-29"), ("L4", "WATCH", "x", "2026-09-28"),
             ("L2", "BULLISH_SETUP", "x", "2026-09-25")]
    d = U.DTU(con, clock=lambda: Clock.t, readers={"open_candidates": lambda w: cands,
                                                   "signals_today": lambda w: ["L5"], "positions": lambda w: set()})
    prot, pos = d.protections(W)
    assert prot == {"L3": U.P_WATCH, "L2": U.P_SETUP, "L5": U.P_SIGNAL}      # L4: WATCH from an earlier window -> none
    Clock.t = datetime(2026, 9, 30, 0, 0, tzinfo=UTC)                        # the creation window has ended
    prot, _ = d.protections(W)
    assert "L3" not in prot and prot["L2"] == U.P_SETUP                      # setups stay until resolved


def _dtu(con, trades=None, entries=None, positions=frozenset(), clock=None):
    return U.DTU(con, policy=policy(2), clock=clock or (lambda: datetime(2026, 9, 29, 15, 0, tzinfo=UTC)),
                 snapshot_fetch=lambda syms: ({s: (trades or {}).get(s) for s in syms}, 1, []),
                 edgar_fetch=lambda: entries or [],
                 readers={"open_candidates": lambda w: [], "signals_today": lambda w: [],
                          "positions": lambda w: set(positions)})


def test_active_symbols_sweep_promotes_on_gap_and_8k_and_persists_across_restart(tmp_path):
    members, daily = universe()
    con = sqlite3.connect(tmp_path / "market.db")
    trades = {"L3": {"p": 21.0, "t": "2026-09-29T14:40:00Z"},                # +5 % -> GAP
              "L4": {"p": 20.2, "t": "2026-09-29T14:40:00Z"}}               # +1 % -> nothing
    entries = [{"accession": "0001-26-1", "cik": f"{2:010d}", "form": "8-K", "updated_utc": "2026-09-29T14:30:00+00:00"}]
    d = _dtu(con, trades, entries)
    base = [m["symbol"] for m in members if m["status"] == "ELIGIBLE"]
    fetch, info = d.active_symbols(W, base, members=members, daily=daily,
                                   sip_as_of=datetime(2026, 9, 29, 14, 45, tzinfo=UTC), operator_added=set(),
                                   operator_excluded=set(), v2_forced=set())
    assert info["fallback"] is None and fetch == ["L0", "L1", "L2", "L3"]      # base order kept; L2 via 8-K, L3 via gap
    assert "PENNY" not in fetch and "THIN" not in fetch
    reasons = dict(con.execute("SELECT symbol, reason FROM dtu_promotions").fetchall())
    assert reasons == {"L3": U.GAP, "L2": U.SEC_8K}
    exp = dict(con.execute("SELECT symbol, expires_utc FROM dtu_promotions").fetchall())
    assert exp["L3"] == W.after_hours_end_utc.isoformat() and exp["L2"] > exp["L3"]   # 8-K TTL spans 3 sessions
    # restart: a new DTU on the same store restores durable promotions without re-promoting
    d2 = _dtu(con)
    fetch2, _ = d2.active_symbols(W, base, members=members, daily=daily,
                                  sip_as_of=datetime(2026, 9, 29, 14, 46, tzinfo=UTC), operator_added=set(),
                                  operator_excluded=set(), v2_forced=set())
    assert fetch2 == fetch and con.execute("SELECT COUNT(*) FROM dtu_promotions").fetchone()[0] == 2
    assert U.latest_active(con, W.window_id)["symbols"] == set(fetch)


def test_fail_safe_full_universe_on_corrupt_snapshot_or_unreadable_positions(tmp_path):
    members, daily = universe()
    con = sqlite3.connect(tmp_path / "market.db")
    base = [m["symbol"] for m in members if m["status"] == "ELIGIBLE"]
    d = _dtu(con, positions={"__V2_UNREADABLE__"})
    fetch, info = d.active_symbols(W, base, members=members, daily=daily, sip_as_of=datetime(2026, 9, 29, 14, 45,
                                                                                              tzinfo=UTC),
                                   operator_added=set(), operator_excluded=set(), v2_forced=set())
    assert fetch == base and "V2_POSITIONS_UNREADABLE" in info["fallback"]
    con2 = sqlite3.connect(tmp_path / "m2.db")
    d2 = _dtu(con2)
    d2.ensure_snapshot(W, members[:1], daily)                                 # snapshot built from a truncated universe
    fetch, info = d2.active_symbols(W, base, members=members, daily=daily, sip_as_of=datetime(2026, 9, 29, 14, 45,
                                                                                               tzinfo=UTC),
                                    operator_added=set(), operator_excluded=set(), v2_forced=set())
    assert fetch == base and info["fallback"].startswith("RuntimeError: SNAPSHOT_CORRUPT")
    row = U.latest_active(con2, W.window_id)
    assert row["fallback"] and row["symbols"] == set(base)                    # visible, never a silent partial set


def test_gap_uses_v1_prev_close_and_stale_gate():
    pm = W.premarket_start_utc
    asof = datetime(2026, 9, 29, 15, 0, tzinfo=UTC)
    assert round(U.gap_pct({"p": 10.3, "t": "2026-09-29T14:59:00Z"}, 10.0, pm, asof), 6) == 3.0
    assert U.gap_pct({"p": 10.3, "t": "2026-09-29T14:00:00Z"}, 10.0, pm, asof) is None      # older than 45 min
    assert U.gap_pct({"p": 10.3, "t": "2026-09-28T19:00:00Z"}, 10.0, pm, asof) is None      # previous window


def test_mode_off_is_identity_and_keeps_fingerprints():
    assert U.mode({}) == U.OFF and U.mode({U.MODE_ENV: "active"}) == U.ACTIVE
    with pytest.raises(SystemExit):
        U.mode({U.MODE_ENV: "canary"})
    src = open("talonx_opportunity/ingestion.py", encoding="utf-8").read()
    assert 'fps = {} if ing.dtu_mode == U.OFF else {"DTU": ing.dtu_policy.fingerprint()}' in src
    d = open("talonx_opportunity/discovery.py", encoding="utf-8").read()
    assert 'if disc.dtu_mode == U.ACTIVE:' in d and 'fps["DTU"] = disc.dtu_policy.fingerprint()' in d
    assert U.policy_from_env({U.POLICY_ENV: "DTU_V1"}).fingerprint() == "da27de22a3bb839a"   # rollback = live V1 fp


def test_ingestion_applies_the_active_set_before_fetch_batches(tmp_path, monkeypatch):
    from talonx_opportunity import ingestion as I
    members, daily = universe()
    calls = []

    class Data:
        _headers = {}
        requests = 0
        errors = []

        def bars_ex(self, syms, **kw):
            calls.append(list(syms))
            from talonx_premarket.alpaca_data import FetchResult
            return FetchResult()

        def assets(self):
            return []
    now = datetime(2026, 9, 29, 15, 0, tzinfo=UTC)
    ing = I.Ingestion(data=Data(), root=tmp_path, clock=lambda: now, universe_loader=lambda: (members, "t"),
                      dtu_mode=U.ACTIVE, dtu=_dtu(None or sqlite3.connect(":memory:")))
    ing._dtu = U.DTU(ing.con, policy=policy(2), clock=lambda: now, snapshot_fetch=lambda s: ({}, 1, []),
                     edgar_fetch=lambda: [], readers={"open_candidates": lambda w: [], "signals_today": lambda w: [],
                                                      "positions": lambda w: set()})
    with ing.con:
        for s, bars in daily.items():
            ing.con.execute("INSERT OR REPLACE INTO daily VALUES (?,?,?)", ("2026-09-29", s, json.dumps(bars)))
        ing.con.execute("INSERT OR REPLACE INTO daily_state VALUES (?,?,?)", ("2026-09-29", now.isoformat(), "[]"))
    monkeypatch.setattr(I.C, "effective_capability", lambda phase, probe: type("Cap", (), {
        "usable_for_discovery": True, "availability": "AVAILABLE", "evidence": ""})())
    monkeypatch.setattr(ing, "probe", lambda phase, now: {"ok": True})
    import talonx_premarket.__main__ as M
    monkeypatch.setattr(M, "_v2_scope", lambda x: set())
    ing.tick()
    fetched = sorted({s for c in calls for s in c})
    assert fetched == ["L0", "L1"]                                            # Core only: nothing else was requested
    assert json.loads(ing.con.execute("SELECT symbols_json FROM dtu_active").fetchone()[0]) == ["L0", "L1"]


def test_discovery_evaluates_only_the_active_set_and_falls_back_safely(tmp_path, monkeypatch):
    from talonx_opportunity import discovery as D
    seen = []
    monkeypatch.setattr(D, "features_from_aggregate", lambda sym, *a, **k: (seen.append(sym), (None, "NO_PREMARKET_PRINTS"))[1])
    members = [{"symbol": s, "status": "ELIGIBLE", "cik": None} for s in ("A", "B", "C")]
    now = datetime(2026, 9, 29, 15, 0, tzinfo=UTC)

    def state(dtu):
        return {"state": {"as_of_utc": (now - timedelta(minutes=16)).isoformat(), "incomplete_json": "[]",
                          "cycle_utc": now.isoformat()}, "members": members, "daily": {}, "aggs": {},
                "probes": {"REGULAR": {"ok": True}}, "dtu": dtu}
    monkeypatch.setenv(U.MODE_ENV, "ACTIVE")
    monkeypatch.setenv(U.POLICY_ENV, "DTU_V1")                                 # V1 semantics (no live-floor gate)
    d = D.Discovery(root=tmp_path, clock=lambda: now, state_reader=lambda wid: state(
        {"symbols": {"A", "C"}, "fallback": None, "cycle_utc": "t", "counts": {}}))
    monkeypatch.setattr(D.C, "effective_capability", lambda phase, probe: type("Cap", (), {
        "usable_for_discovery": True, "as_dict": lambda self: {}, "provider": "p", "feed": "f",
        "delay_minutes": 15, "adjustment": "split"})())
    d.tick()
    assert sorted(seen) == ["A", "C"]                                          # B never reached features / SEC
    seen.clear()
    d2 = D.Discovery(root=tmp_path / "x", clock=lambda: now, state_reader=lambda wid: state(None))
    d2.tick()
    assert sorted(seen) == ["A", "B", "C"]                                     # no active set -> full, recorded
    f = json.loads(sqlite3.connect(tmp_path / "x" / "opportunity.db").execute(
        "SELECT funnel_json FROM scans ORDER BY decision_utc DESC").fetchone()[0])
    assert f["DTU"] == {"mode": "ACTIVE", "applied": False, "fallback": "NO_ACTIVE_SET"}


def test_sentinel_universe_views_are_read_only(tmp_path):
    from talonx_ops.operator_control import universe_view as UV
    members, daily = universe()
    con = sqlite3.connect(tmp_path / "market.db")
    d = _dtu(con)
    base = [m["symbol"] for m in members if m["status"] == "ELIGIBLE"]
    d.active_symbols(W, base, members=members, daily=daily, sip_as_of=datetime(2026, 9, 29, 14, 45, tzinfo=UTC),
                     operator_added=set(), operator_excluded=set(), v2_forced=set())
    con.close()
    v = UV.UniverseView(tmp_path)
    txt = UV.summary_text(v, "H")
    assert "Core: 2" in txt and "Effective active: 2" in txt and "Auto-excluded: 2" in txt
    assert "Snapshot state: EVENT_ELIGIBLE" in UV.status_text(v, "L3", "H")
    csvb = v.excluded_csv().decode()
    assert csvb.splitlines()[0].startswith("symbol,state,reason,price,adv20,core_rank,promotion_eligible")
    assert "L0," not in csvb                                                   # Core not listed as excluded
    src = open("talonx_ops/operator_control/universe_view.py", encoding="utf-8").read()
    assert "mode=ro" in src and "INSERT" not in src and "UPDATE" not in src


def test_forward_alpha_and_signal_policy_untouched():
    from talonx_opportunity.promotion import PROMOTION_V1
    from talonx_paperperf.hypotheses import SQF_V1
    assert PROMOTION_V1.fingerprint() == "4926c12e5eace04e" and SQF_V1.fingerprint() == "460ee466c5ae8d6f"


def _feat(sym, now, gap=8.0):
    from talonx_premarket.features import Features
    return Features(symbol=sym, data_as_of_utc=now.isoformat(), prev_session="2026-09-28", prev_close=10.0,
                    prev_high=10.2, prev_low=9.8, atr20_pct=2.0, adv20_shares=5e6, adv20_dollars=5e7, trend5_pct=1.0,
                    last_price=10.0 * (1 + gap / 100), last_bar_utc=(now - timedelta(minutes=1)).isoformat(),
                    staleness_min=1.0, pm_high=11.0, pm_low=10.0, pm_volume=2e6, pm_dollars=2e7, pm_bars=200,
                    pm_trades=5000, gap_pct=gap, activity_adv_fraction=0.4, range_position="ABOVE_PREV_HIGH",
                    range_distance_pct=5.0)


def _run_sequence(tmp_path, monkeypatch, active_by_scan):
    """Discovery over successive scans where X keeps gapping +8 %; X's DTU membership follows ``active_by_scan``."""
    from talonx_opportunity import discovery as D
    monkeypatch.setenv(U.MODE_ENV, "ACTIVE")
    monkeypatch.setenv(U.POLICY_ENV, "DTU_V1")                                 # V1 semantics (no live-floor gate)
    t0 = datetime(2026, 9, 29, 14, 0, tzinfo=UTC)
    clock = {"t": t0}
    monkeypatch.setattr(D, "features_from_aggregate", lambda sym, *a, **k: (_feat(sym, clock["t"]), ""))
    monkeypatch.setattr(D.C, "effective_capability", lambda phase, probe: type("Cap", (), {
        "usable_for_discovery": True, "as_dict": lambda self: {}, "provider": "p", "feed": "f",
        "delay_minutes": 15, "adjustment": "split"})())
    members = [{"symbol": "X", "status": "ELIGIBLE", "cik": None}, {"symbol": "C", "status": "ELIGIBLE", "cik": None}]
    act = {"i": 0}

    def state(wid):
        syms = {"C"} | ({"X"} if active_by_scan[act["i"]] else set())
        return {"state": {"as_of_utc": (clock["t"] - timedelta(minutes=16)).isoformat(), "incomplete_json": "[]",
                          "cycle_utc": clock["t"].isoformat()}, "members": members, "daily": {}, "aggs": {},
                "probes": {"REGULAR": {"ok": True}}, "dtu": {"symbols": syms, "fallback": None, "cycle_utc": "t",
                                                            "counts": {}}}
    d = D.Discovery(root=tmp_path, clock=lambda: clock["t"], state_reader=state)
    times = []
    for i in range(len(active_by_scan)):
        act["i"] = i
        clock["t"] = t0 + timedelta(minutes=5 * i)
        times.append(clock["t"].isoformat())
        d.tick()
    ev = [dict(zip(("event_type", "at_utc"), r)) for r in sqlite3.connect(tmp_path / "opportunity.db").execute(
        "SELECT event_type, at_utc FROM candidate_events WHERE symbol='X' ORDER BY seq")]
    return ev, times


def test_no_historical_replay_on_promotion(tmp_path, monkeypatch):
    ev, times = _run_sequence(tmp_path, monkeypatch, [False, False, False, True, True])
    assert [e["event_type"] for e in ev] == ["NEW"]                      # one identity, surfaced ONCE
    assert ev[0]["at_utc"] == times[3]                                   # at the promotion boundary, not backdated


def test_no_replay_of_the_inactive_interval_on_restore(tmp_path, monkeypatch):
    ev, times = _run_sequence(tmp_path, monkeypatch, [True, False, False, False, True])
    assert [e["event_type"] for e in ev] == ["NEW"] and ev[0]["at_utc"] == times[0]
    # restored at scan 4: the identity simply continues -- nothing is emitted for scans 1-3 and no catch-up burst
    assert all(e["at_utc"] in (times[0], times[4]) for e in ev)
