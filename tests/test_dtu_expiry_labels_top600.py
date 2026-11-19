"""2026-10-08 owner decisions: (A) the expired DTU shadow collector can never overrun its registered endpoint again;
(B) result labels match the underlying metrics (promotion / candidate markouts; V2 zero-friction paper accounting);
(C) DTU_V3_TOP600: at most 600 new-opportunity names by the existing live ADV20, no event tier, deferred activation at
a window boundary, protections managed but never admitted. No network, no study restart, no live store touched."""
from __future__ import annotations

import json
import sqlite3
import types
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import pytest

from talonx_opportunity import universe_tiers as U
from tests.test_live_universe_floor import REF, SESS, W, bars, universe

UTC = timezone.utc
REPO = Path(__file__).resolve().parents[1]


# ============================================================================================ A. DTU endpoint
def test_endpoint_matches_the_segment_registry_and_boundary_is_inclusive():
    from talonx_shadow import dtu
    assert dtu.COLLECTION_END_UTC == datetime(2026, 10, 8, 0, 15, tzinfo=UTC)
    assert not dtu.collection_expired(dtu.COLLECTION_END_UTC - timedelta(microseconds=1))
    assert dtu.collection_expired(dtu.COLLECTION_END_UTC)
    reg = REPO / "results" / "dtu_shadow" / "UNIVERSE_SEGMENTS.json"
    if reg.exists():                                              # live registry (gitignored) -- same instant
        assert json.loads(reg.read_text(encoding="utf-8"))["end_date"].startswith("2026-10-08T00:15Z")


def test_run_refuses_to_start_after_the_endpoint(monkeypatch, capsys):
    from talonx_shadow import dtu
    monkeypatch.setattr(dtu, "Collector", lambda: (_ for _ in ()).throw(AssertionError("must not construct")))
    monkeypatch.setattr(dtu, "collection_expired", lambda now: True)
    dtu.run_forever()
    assert "REFUSED_STUDY_ENDED" in capsys.readouterr().out


def test_loop_stops_before_starting_new_work_at_the_endpoint(monkeypatch, capsys):
    from talonx_shadow import dtu
    calls = {"sweep": 0}

    class FakeCollector:
        def __init__(self):
            self.c = sqlite3.connect(":memory:")
            self.c.execute("CREATE TABLE meta (k TEXT PRIMARY KEY, v TEXT)")

        def sweep(self, now):
            calls["sweep"] += 1
    seq = iter([False, True])                                     # start allowed, then the endpoint arrives
    monkeypatch.setattr(dtu, "Collector", FakeCollector)
    monkeypatch.setattr(dtu, "collection_expired", lambda now: next(seq))
    dtu.run_forever()
    assert calls["sweep"] == 0 and "STOPPED_AT_ENDPOINT" in capsys.readouterr().out


def test_sweep_does_no_work_after_the_endpoint_and_writes_nothing_if_reached_during_fetch(monkeypatch):
    from talonx_shadow import dtu
    fake = types.SimpleNamespace(ensure_window=lambda wid: (_ for _ in ()).throw(AssertionError("no work")))
    assert dtu.Collector.sweep(fake, dtu.COLLECTION_END_UTC) is None
    # endpoint reached while the snapshot fetch was in flight: nothing is written
    import talonx_opportunity.phases as PH
    from talonx_opportunity.phases import trading_window
    w = trading_window(date(2026, 10, 7))
    monkeypatch.setattr(PH, "phase_at", lambda now: ("REGULAR", w))
    con = sqlite3.connect(":memory:")
    con.execute("CREATE TABLE sweeps (id INTEGER PRIMARY KEY, window_id TEXT, at_utc TEXT, phase TEXT, sip_as_of TEXT,"
                " requests INT, duration_s REAL, symbols_checked INT)")
    clock = iter([False, True])
    monkeypatch.setattr(dtu, "collection_expired", lambda now: next(clock))
    fake = types.SimpleNamespace(ensure_window=lambda wid: True, eligible=["A"], _snapshots=lambda s: ({}, 1, []),
                                 c=con)
    assert dtu.Collector.sweep(fake, datetime(2026, 10, 7, 15, 0, tzinfo=UTC)) is None
    assert con.execute("SELECT COUNT(*) FROM sweeps").fetchone()[0] == 0


# ============================================================================================ B. labels
def test_markout_timing_reports_unknown_instead_of_inventing():
    from talonx_ops.opportunity_read import markout_timing
    t = markout_timing("2026-10-07T19:24:00+00:00", "2026-10-07T19:43:48+00:00")
    assert t == {"reference_data_utc": "2026-10-07T19:24:00+00:00", "alert_delivered_utc": "2026-10-07T19:43:48+00:00",
                 "delay_min": 19.8}
    assert markout_timing("2026-10-07T19:24:00+00:00", None)["delay_min"] == "UNKNOWN"
    u = markout_timing(None, "garbage")
    assert u == {"reference_data_utc": "UNKNOWN", "alert_delivered_utc": "UNKNOWN", "delay_min": "UNKNOWN"}


def test_promotion_markout_view_labels_the_metric_and_adds_no_returns(tmp_path):
    from talonx_opportunity import promotion as P
    from talonx_ops.opportunity_read import MARKOUT_EXPLANATION, MARKOUT_LABEL, promotion_markout_view
    pc = sqlite3.connect(tmp_path / "promotion.db")
    pc.executescript(P.SCHEMA)
    cols = [r[1] for r in pc.execute("PRAGMA table_info(promotions)")]
    for pid, sig in (("P1", "P1"), ("P2", None)):
        row = {c: None for c in cols}
        row.update(promotion_id=pid, symbol=pid, data_as_of_utc="2026-10-07T19:24:00+00:00",
                   decision_utc="2026-10-07T19:40:00+00:00", signal_event_id=sig, state="PROMOTED_SIGNAL")
        pc.execute(f"INSERT INTO promotions ({','.join(cols)}) VALUES ({','.join('?' * len(cols))})", list(row.values()))
        ocols = [r[1] for r in pc.execute("PRAGMA table_info(paper_outcomes)")]
        o = {c: None for c in ocols}
        o.update(promotion_id=pid, ref_time_utc="2026-10-07T19:24:00+00:00", ret_30m_pct=5.0)
        pc.execute(f"INSERT INTO paper_outcomes ({','.join(ocols)}) VALUES ({','.join('?' * len(ocols))})",
                   list(o.values()))
    pc.commit()
    ob = sqlite3.connect(tmp_path / "promotion_signal_notifications.db")
    ob.execute("CREATE TABLE ops_notification_outbox (event_id TEXT, state TEXT, sent_at_utc TEXT)")
    ob.execute("INSERT INTO ops_notification_outbox VALUES ('P1','SENT','2026-10-07T19:43:48+00:00')")
    ob.commit()
    v = promotion_markout_view(tmp_path)
    assert v["label"] == MARKOUT_LABEL == "Gross markout from data timestamp"
    assert v["explanation"] == MARKOUT_EXPLANATION == ("Not an executable return from Telegram alert delivery; the "
                                                       "reference price can predate the alert.")
    rec = {r["symbol"]: r for r in v["recent"]}
    assert rec["P1"]["delay_min"] == 19.8 and rec["P2"]["alert_delivered_utc"] == "UNKNOWN"
    assert v["delay_summary"] == {"with_delivery_time": 1, "without_delivery_time": 1, "median_delay_min": 19.8}
    dumped = json.dumps(v)
    assert "ret_" not in dumped and "5.0" not in dumped and "pct" not in dumped   # no return value is exposed here


def test_session_report_labels_its_outcome_statistics(tmp_path):
    from talonx_opportunity.reporting import build_report, render_md
    from tests.test_continuous_opportunity_engine import _seed_window_candidates
    _seed_window_candidates(tmp_path, ["2026-09-24T14:00:00+00:00"])
    rep = build_report(tmp_path, "2026-09-24")
    assert rep["outcome_metric"]["label"] == "Gross markout from data timestamp"
    md = render_md(rep)
    assert "gross markout from data timestamp: +30m" in md and "Not an executable return from Telegram" in md


def test_v2_label_matches_its_zero_friction_accounting():
    from talonx_ops import dashboard_read as DR
    from talonx_v2 import sizing
    s = sizing.size_whole_shares_fee_inclusive(price=10.0, allocation_usd=10_000.0, available_cash=1e5)
    assert s.entry_fee == 0                                               # the code fact the label states
    svc = (REPO / "talonx_v2" / "service.py").read_text(encoding="utf-8")
    assert "fee_fn" not in svc                                            # the service never passes a fee model
    assert DR.V2_ACCOUNTING_BASIS["label"] == "Before fees, spread and slippage"
    perf = {"costs": {"summary": "x", "modeled": True},
            "closed_trades": [{"costs": DR._V2_OLD_COST_SUMMARY, "realized_pnl_usd": 12.5}],
            "open_positions": {"detail": [{"unrealized_status": DR._V2_OLD_COST_SUMMARY, "unrealized_pnl_usd": 3.0}]}}
    out = DR._relabel_v2_costs(perf)
    assert out["costs"]["modeled"] is False and out["costs"]["summary"].startswith("Before fees, spread and slippage")
    assert out["closed_trades"][0]["realized_pnl_usd"] == 12.5             # numbers untouched
    assert out["open_positions"]["detail"][0]["unrealized_pnl_usd"] == 3.0
    assert out["closed_trades"][0]["costs"] == "Before fees, spread and slippage"


# ============================================================================================ C. DTU_V3_TOP600
def _members(n, *, tie=False):
    members = [{"symbol": f"S{i:04d}", "status": "ELIGIBLE", "cik": None} for i in range(n)]
    live = {m["symbol"]: bars(50.0, 30e6 + (0 if tie else (n - i) * 1e5)) for i, m in enumerate(members)}
    return members, {s: list(v) for s, v in live.items()}, live


@pytest.mark.parametrize("n,admitted", [(599, 599), (600, 600), (601, 600)])
def test_at_most_600_admitted_with_no_event_tier(n, admitted):
    m, daily, live = _members(n)
    rows = U.classify_members(m, daily, REF, U.DTU_V3_TOP600, live=live, sessions=SESS)
    core = [r for r in rows if r["state"] == U.CORE]
    assert len(core) == admitted and not [r for r in rows if r["state"] == U.EVENT_ELIGIBLE]
    out = [r for r in rows if r["reason"].startswith(U.CAP_RANK)]
    assert len(out) == n - admitted
    if out:
        assert out[0]["state"] == U.AUTO_EXCLUDED and out[0]["reason"] == f"CAP_RANK_EXCLUDED_RANK_601_OF_{n}_CAP_600"
        assert U.floor_category(out[0]["state"], out[0]["reason"]) == U.CAP_RANK


def test_ranking_is_by_live_adv20_with_symbol_tie_break_and_deterministic():
    m, daily, live = _members(5, tie=True)
    pol = U.CappedLiveFloorPolicy(core_size=3, admission_cap=3)
    a = U.classify_members(m, daily, REF, pol, live=live, sessions=SESS)
    b = U.classify_members(list(reversed(m)), daily, REF, pol, live=live, sessions=SESS)
    pick = lambda rows: [r["symbol"] for r in sorted(rows, key=lambda r: r["symbol"]) if r["state"] == U.CORE]  # noqa
    assert pick(a) == pick(b) == ["S0000", "S0001", "S0002"]


def test_floors_and_data_quality_are_unchanged_under_the_cap():
    members, daily, live = universe()
    pol = U.CappedLiveFloorPolicy(core_size=2, admission_cap=2)
    v2 = {r["symbol"]: r for r in U.classify_members(members, daily, REF, U.LiveFloorPolicy(core_size=2), live=live,
                                                       sessions=SESS)}
    v3 = {r["symbol"]: r for r in U.classify_members(members, daily, REF, pol, live=live, sessions=SESS)}
    for s, r in v2.items():
        if r["state"] not in (U.CORE, U.EVENT_ELIGIBLE):
            assert (v3[s]["state"], v3[s]["reason"]) == (r["state"], r["reason"])       # floor / DQ reasons identical
    assert v3["EDGE"]["reason"].startswith(U.CAP_RANK) and v2["EDGE"]["state"] == U.EVENT_ELIGIBLE
    assert U.DTU_V1.fingerprint() == "da27de22a3bb839a" and U.DTU_V2.fingerprint() == "65f3285f8181c552"
    assert U.DTU_V3_TOP600.core_size == U.DTU_V3_TOP600.admission_cap == 600 and not U.DTU_V3_TOP600.event_tier
    assert U.DTU_V3_TOP600.fingerprint() not in (U.DTU_V1.fingerprint(), U.DTU_V2.fingerprint())


def test_no_future_or_incomplete_session_input_changes_the_rank():
    m, daily, live = _members(3)
    pol = U.CappedLiveFloorPolicy(core_size=1, admission_cap=1)
    live2 = {k: list(v) for k, v in live.items()}
    live2["S0002"] = live2["S0002"] + [{"t": f"{W.session.isoformat()}T04:00:00Z", "o": 50, "h": 50, "l": 50,
                                        "c": 50, "v": 1e12}]                      # today's (incomplete) bar
    a = U.classify_members(m, daily, REF, pol, live=live, sessions=SESS)
    b = U.classify_members(m, daily, REF, pol, live=live2, sessions=SESS)
    assert [(r["symbol"], r["state"], r["adv20"]) for r in a] == [(r["symbol"], r["state"], r["adv20"]) for r in b]


def _built(tmp_path, policy, positions=(), readers=None):
    members, daily, live = universe()
    con = sqlite3.connect(tmp_path / "market.db")
    rd = {"open_candidates": lambda w: [], "signals_today": lambda w: [], "positions": lambda w: set(positions)}
    rd.update(readers or {})
    d = U.DTU(con, policy=policy, clock=lambda: datetime(2026, 10, 5, 14, 0, tzinfo=UTC), readers=rd,
              live_fetch=lambda s, a, b: ({x: live.get(x, []) for x in s}, set(), 1, "fake raw"),
              snapshot_fetch=lambda s: ({}, 1, []), edgar_fetch=lambda: [])
    base = [m["symbol"] for m in members if m["status"] == "ELIGIBLE"]
    d.ensure_live_daily(W, base, datetime(2026, 10, 5, 0, 5, tzinfo=UTC))
    return d, con, members, daily, base


def test_protected_names_stay_fetched_but_are_never_admitted_and_no_event_promotion(tmp_path):
    pol = U.CappedLiveFloorPolicy(core_size=2, admission_cap=2)
    d, con, members, daily, base = _built(tmp_path, pol, positions={"EDGE"}, readers={
        "open_candidates": lambda w: [("CHEAP", "BULLISH_SETUP", "x", "2026-10-02")]})
    fetch, last = d.active_symbols(W, base, members=members, daily=daily,
                                   sip_as_of=datetime(2026, 10, 5, 13, 45, tzinfo=UTC), operator_added=set(),
                                   operator_excluded=set(), v2_forced={"BOTH"})
    assert {"EDGE", "CHEAP", "BOTH"} <= set(fetch)                 # capped-out position / setup / V2 scope: managed
    con.commit()
    assert U.read_admission(tmp_path, W.window_id, pol) == {"BIG", "MID"}       # ...never admissible
    snap = d.snapshot(W.window_id)
    assert snap["EDGE"]["reason"].startswith(U.CAP_RANK)
    assert [s for s, r in snap.items() if r["state"] == U.EVENT_ELIGIBLE] == []    # empty event-tier sweep pool
    assert all(r[0] == 0 for r in con.execute("SELECT symbols FROM dtu_sweeps"))
    _, st = U.resolve(snap, now="2026-10-05T14:00:00+00:00", promotions=[
        {"symbol": "EDGE", "reason": U.GAP, "started_utc": "2026-10-05T13:00:00+00:00", "expires_utc": None}],
        operator_added=set(), operator_excluded=set(), v2_forced=set(), positions=set(), protections={})
    assert st["EDGE"][0] == U.AUTO_EXCLUDED                        # a gap promotion cannot admit a capped-out name


def test_snapshot_persists_and_reloads_with_policy_identity_and_reconciled_report(tmp_path):
    pol = U.CappedLiveFloorPolicy(core_size=2, admission_cap=2)
    d, con, members, daily, base = _built(tmp_path, pol)
    d.ensure_snapshot(W, members, daily)
    con.commit()
    v = con.execute("SELECT snapshot_version, policy_fp, core_size FROM dtu_snapshots").fetchone()
    assert v[0].endswith("#" + pol.fingerprint()) and v[1] == pol.fingerprint() and v[2] == 2
    reload = U.DTU(sqlite3.connect(tmp_path / "market.db"), policy=pol).snapshot(W.window_id)
    assert reload == d.snapshot(W.window_id)
    rep = d.report(W, members, daily, v2_scope=set(), previous_policy=U.LiveFloorPolicy(core_size=2))
    assert rep["reconciled"] and rep["counts"]["categories"][U.CAP_RANK] == 1 and rep["meta"]["admission_cap"] == 2
    assert rep["counts"]["event_eligible"] == 0


# --------------------------------------------------------------------------------------- schedule / activation
def _schedule(root, entries):
    f = U.schedule_path(root)
    f.parent.mkdir(parents=True, exist_ok=True)
    f.write_text(entries if isinstance(entries, str) else json.dumps({"schedule": entries}), encoding="utf-8")


def test_schedule_activates_only_from_its_window_and_never_rewrites_a_published_window(tmp_path):
    _schedule(tmp_path, [{"policy": "DTU_V3_TOP600", "effective_from_window": "2026-10-09"}])
    assert U.effective_policy("2026-10-08", tmp_path, env={}) is U.DTU_V2
    assert U.effective_policy("2026-10-09", tmp_path, env={}) is U.DTU_V3_TOP600
    # a window already published under DTU_V2 keeps it (no in-place rewrite), even if the schedule says otherwise
    assert U.effective_policy("2026-10-09", tmp_path, env={}, snapshot_fp=U.DTU_V2.fingerprint()) is U.DTU_V2
    # rollback: a FUTURE DTU_V2 entry; already-built windows keep their published policy
    _schedule(tmp_path, [{"policy": "DTU_V3_TOP600", "effective_from_window": "2026-10-09"},
                         {"policy": "DTU_V2", "effective_from_window": "2026-10-13"}])
    assert U.effective_policy("2026-10-12", tmp_path, env={}) is U.DTU_V3_TOP600
    assert U.effective_policy("2026-10-13", tmp_path, env={}) is U.DTU_V2
    assert U.effective_policy("2026-10-12", tmp_path, env={},
                              snapshot_fp=U.DTU_V3_TOP600.fingerprint()) is U.DTU_V3_TOP600


@pytest.mark.parametrize("bad", ["{not json", json.dumps({"schedule": [{"policy": "DTU_V9", "effective_from_window":
                                                                         "2026-10-09"}]}),
                                 json.dumps({"schedule": [{"policy": "DTU_V3_TOP600", "effective_from_window": "soon"}]})])
def test_malformed_schedule_keeps_the_base_policy_and_reports_it(tmp_path, bad):
    _schedule(tmp_path, bad)
    assert U.effective_policy("2026-10-09", tmp_path, env={}) is U.DTU_V2
    assert U.read_schedule(tmp_path)[1].startswith("MALFORMED_SCHEDULE_IGNORED")


def test_ingestion_and_discovery_resolve_the_same_window_policy(tmp_path, monkeypatch):
    from talonx_opportunity.discovery import Discovery
    from talonx_opportunity.ingestion import Ingestion
    from talonx_opportunity.phases import trading_window
    _schedule(tmp_path, [{"policy": "DTU_V3_TOP600", "effective_from_window": "2026-10-09"}])
    monkeypatch.delenv(U.POLICY_ENV, raising=False)
    con = sqlite3.connect(tmp_path / "market.db")
    con.executescript(U.SCHEMA)
    con.execute("INSERT INTO dtu_snapshots VALUES ('2026-10-08','v','2026-10-07','t',1200,'{}',?)",
                (U.DTU_V2.fingerprint(),))
    con.commit()
    ing = types.SimpleNamespace(root=tmp_path, con=con, dtu_base_policy=U.DTU_V2, dtu_policy=U.DTU_V2, _dtu=None)
    disc = Discovery(root=tmp_path, state_reader=lambda w: {}, admission_reader=lambda w: set())
    for wid, want in (("2026-10-08", U.DTU_V2), ("2026-10-09", U.DTU_V3_TOP600)):
        Ingestion._apply_window_policy(ing, trading_window(date.fromisoformat(wid)))
        assert ing.dtu_policy is want and disc._policy_for(wid) is want


def test_runtime_sources_cover_the_policy_module_so_the_deploy_is_versioned():
    from talonx_opportunity.runtime import COMPONENT_SOURCES
    for comp in ("ingestion", "discovery"):
        assert "talonx_opportunity/universe_tiers.py" in COMPONENT_SOURCES[comp]
