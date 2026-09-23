"""
PR #19 canary hardening: provider completeness / watermarks, duplicate bars, SIP-delay boundaries, restart/resume,
invalidation safety, SEC catalyst unknown + 429 back-off, alert-cap durability, enqueued-vs-sent delivery state,
stop.flag / session-directory identity, session calendar edges, status/report. No network.
"""
from __future__ import annotations

import json
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import pytest

from talonx_premarket import alerts as A
from talonx_premarket import scoring as S
from talonx_premarket.alpaca_data import AlpacaData, RateLimiter, complete_bars_as_of, data_as_of, iso, merge_bars, \
    sorted_bars
from talonx_premarket.catalysts import SecSubmissions
from talonx_premarket.config import PREMARKET_RESEARCH_V1, PremarketConfig
from talonx_premarket.engine import Engine, LiveSource, ReplaySource, provider_stale
from talonx_premarket.session import session_day
from talonx_premarket.store import ResearchStore
from talonx_premarket.universe import UniverseMember

from test_premarket_research_engine import _FakeData, _bar, _daily  # noqa: E402  (shared fakes)

UTC = timezone.utc
D = date(2026, 9, 23)
SD = session_day(D)
SYMS = ["AAA", "BBB", "CCC"]


def _uni(syms=SYMS):
    return [UniverseMember(s, f"{s} Inc", "NASDAQ", None, "ELIGIBLE", "") for s in syms]


def _pm_series(price, *, start=datetime(2026, 9, 23, 8, 0, tzinfo=UTC), minutes=320, v=40000):
    return [_bar(start + timedelta(minutes=i), price, v=v) for i in range(minutes)]


def _live_engine(tmp_path, pm, *, fail=None, db="r.db", route=None, cfg=PREMARKET_RESEARCH_V1, syms=SYMS):
    data = _FakeData({s: _daily(10.0) for s in syms}, pm, fail=fail)
    src = LiveSource(data, list(syms), SD, cfg)
    eng = Engine(universe=_uni(syms), source=src, store=ResearchStore(tmp_path / db), sd=SD, mode="live",
                 v2_scope=set(), sec=None, ledger_path=None, cfg=cfg, route=route or (lambda a: "RECORDED_NOT_DELIVERED"))
    return eng, data, src


def T(h, m=0, s=0):
    return datetime(2026, 9, 23, h, m, s, tzinfo=UTC)


# ================================================================ Phase 2: live watermark / partial batch failure
def test_PARTIAL_BATCH_FAILURE_DOES_NOT_ADVANCE_PAST_GAP(tmp_path):
    pm = {s: _pm_series(10.8) for s in SYMS}
    eng, data, src = _live_engine(tmp_path, pm, fail={"BBB"})
    bars, incomplete = src.premarket(data_as_of(T(9, 0)))
    assert incomplete == {"BBB"}
    assert src._wm["BBB"] == SD.premarket_start_utc          # failed symbol's watermark did NOT advance
    assert src._wm["AAA"] == data_as_of(T(9, 0))             # succeeded symbols advanced
    assert "BBB" not in bars or bars["BBB"] == []


def test_FAILED_BATCH_IS_RETRIED():
    calls = {"n": 0}

    def get(url, params, headers):
        calls["n"] += 1
        if calls["n"] == 1:
            raise RuntimeError("HTTP 503 transient")
        return {"bars": {"AAA": [{"t": "2026-09-23T08:00:00Z"}]}, "next_page_token": None}

    d = AlpacaData(key_id="k", secret="s", http_get=get, limiter=RateLimiter(1000))
    res = d.bars_ex(["AAA"], timeframe="1Min", start=T(8), end=T(9))
    assert res.complete and res.retried_batches == 1 and res.bars["AAA"] and calls["n"] == 2


def test_NO_CANDIDATE_FROM_INCOMPLETE_PROVIDER_WINDOW(tmp_path):
    pm = {s: _pm_series(11.0) for s in SYMS}                # +10% gap: would be a setup with complete data
    eng, data, src = _live_engine(tmp_path, pm, fail={"AAA", "BBB", "CCC"})
    r = eng.scan(T(12, 0))
    assert r.alerts == [] and r.funnel["PROVIDER_INCOMPLETE"] == 3
    assert r.funnel["provider"]["PROVIDER_COMPLETE"] is False and r.funnel["provider"]["DATA_GAPS"] == 3
    assert r.funnel.get("NO_PREMARKET_PRINTS", 0) == 0 and not r.funnel["hard_reject_reasons"]


def test_RECOVERY_FETCHES_MISSING_INTERVAL(tmp_path):
    pm = {s: _pm_series(10.8) for s in SYMS}
    eng, data, src = _live_engine(tmp_path, pm, fail={"BBB"})
    src.premarket(data_as_of(T(9, 0)))
    data.fail.clear()                                          # provider recovers
    bars, incomplete = src.premarket(data_as_of(T(9, 5)))
    assert incomplete == set()
    # BBB now has the WHOLE interval from 04:00 ET, not just the latest 5 minutes
    assert len(bars["BBB"]) == len(bars["AAA"]) and bars["BBB"][0]["t"] == "2026-09-23T08:00:00Z"
    starts = [c[1] for c in data.calls if c[0] == "1Min" and "BBB" in c[3]]
    assert starts[-1] == SD.premarket_start_utc


# ================================================================ Phase 3: daily partial download
def test_partial_daily_download_is_not_cached_as_authoritative(tmp_path):
    pm = {s: _pm_series(10.8) for s in SYMS}
    eng, data, src = _live_engine(tmp_path, pm, fail={"CCC"})
    daily, inc = src.daily()
    assert inc == {"CCC"} and "CCC" not in daily
    r = eng.scan(T(12, 0))
    assert r.funnel["hard_reject_reasons"].get("INSUFFICIENT_DAILY_HISTORY", 0) == 0   # not misclassified
    assert r.funnel["PROVIDER_INCOMPLETE"] == 1
    data.fail.clear()
    daily, inc = src.daily()
    assert inc == set() and len(daily["CCC"]) == 25
    assert [c for c in data.calls if c[0] == "1Day"][-1][3] == ("CCC",)                # only the missing symbol


# ================================================================ Phase 4: duplicate / overlapping bars
def test_live_incremental_windows_never_duplicate_the_boundary_bar(tmp_path):
    pm = {s: _pm_series(10.8) for s in SYMS}
    eng, data, src = _live_engine(tmp_path, pm)
    for m in range(0, 60, 5):
        bars, _ = src.premarket(data_as_of(T(9, m)))
    ts = [b["t"] for b in bars["AAA"]]
    assert len(ts) == len(set(ts))
    # every request ends one second before its as-of (Alpaca's end is inclusive)
    assert all(c[2].second == 59 for c in data.calls if c[0] == "1Min")


def test_live_and_replay_see_identical_premarket_volume(tmp_path):
    pm = {s: _pm_series(10.8) for s in SYMS}
    eng, data, live = _live_engine(tmp_path, pm)
    rep = ReplaySource(_FakeData({s: _daily(10.0) for s in SYMS}, pm), SYMS, SD, PREMARKET_RESEARCH_V1)
    for m in range(0, 60, 5):
        lb, _ = live.premarket(data_as_of(T(10, m)))
    rb, _ = rep.premarket(data_as_of(T(10, 55)))
    assert sum(b["v"] for b in lb["AAA"]) == sum(b["v"] for b in rb["AAA"])


def test_merge_bars_replaces_by_symbol_and_timestamp():
    store: dict = {}
    merge_bars(store, {"A": [{"t": "2026-09-23T08:00:00Z", "v": 1}, {"t": "2026-09-23T08:01:00Z", "v": 2}]})
    merge_bars(store, {"A": [{"t": "2026-09-23T08:01:00Z", "v": 5}]})           # retry / later complete copy
    assert [b["v"] for b in sorted_bars(store)["A"]] == [1, 5]


def test_a_failed_page_discards_the_whole_batch_attempt_so_retry_cannot_duplicate():
    calls = {"n": 0}

    def get(url, params, headers):
        calls["n"] += 1
        if params.get("page_token") is None:
            return {"bars": {"AAA": [{"t": "2026-09-23T08:00:00Z"}]}, "next_page_token": "p2"}
        if calls["n"] == 2:
            raise RuntimeError("HTTP 500 on page 2")
        return {"bars": {"AAA": [{"t": "2026-09-23T08:01:00Z"}]}, "next_page_token": None}

    d = AlpacaData(key_id="k", secret="s", http_get=get, limiter=RateLimiter(1000))
    res = d.bars_ex(["AAA"], timeframe="1Min", start=T(8), end=T(9))
    assert [b["t"][11:16] for b in res.bars["AAA"]] == ["08:00", "08:01"]      # page 1 not doubled


# ================================================================ Phase 8: exactly one 15-minute delay
@pytest.mark.parametrize("decision,newest_bar_start", [
    (T(12, 0, 0), "11:44"),      # as-of 11:45 -> last complete bar is 11:44 (ends 11:45)
    (T(12, 0, 59), "11:44"),     # same minute
    (T(12, 1, 0), "11:45"),
    (T(11, 59, 59), "11:43"),    # T - 1s: as-of 11:44
])
def test_single_sip_delay_boundaries(decision, newest_bar_start):
    rows = [_bar(T(11, 30) + timedelta(minutes=i), 10) for i in range(40)]
    got = complete_bars_as_of(rows, data_as_of(decision))
    assert got[-1]["t"][11:16] == newest_bar_start
    assert decision - (datetime.fromisoformat(got[-1]["t"].replace("Z", "+00:00")) + timedelta(minutes=1)) \
        < timedelta(minutes=16)                                   # 15:00 .. 15:59 -- never 30 min


def test_live_requests_never_ask_for_data_newer_than_the_subscription_allows(tmp_path):
    eng, data, src = _live_engine(tmp_path, {s: _pm_series(10.8) for s in SYMS})
    eng.scan(T(12, 0, 30))
    assert all(c[2] <= T(12, 0, 30) - timedelta(minutes=15) for c in data.calls if c[0] == "1Min")


# ================================================================ Phase 9/10: provider stale + invalidation safety
def test_provider_failure_never_invalidates_an_existing_candidate(tmp_path):
    pm = {s: _pm_series(10.8) for s in SYMS}
    eng, data, src = _live_engine(tmp_path, pm)
    first = eng.scan(T(12, 0))
    assert {a["symbol"] for a in first.alerts} == set(SYMS)
    data.fail.update({"AAA"})
    src._wm["AAA"] = SD.premarket_start_utc                       # simulate a gap needing re-fetch
    r = eng.scan(T(12, 10))
    assert not [a for a in r.alerts if a["alert_type"] == A.INVALIDATED]
    assert eng._active_candidate("AAA")["state"] != A.INVALIDATED


def test_provider_stale_holds_every_symbol(tmp_path):
    old = {s: _pm_series(10.8, minutes=30) for s in SYMS}           # prints stop at 08:30Z
    eng, data, src = _live_engine(tmp_path, old)
    eng.scan(T(8, 45))                                               # creates candidates while fresh
    assert provider_stale(src.premarket(data_as_of(T(9, 30)))[0], data_as_of(T(9, 30)), SD)
    r = eng.scan(T(9, 30))
    assert r.funnel["provider"]["PROVIDER_STALE"] is True and r.alerts == []


def test_genuine_market_fade_on_complete_data_still_invalidates(tmp_path):
    pm = {s: _pm_series(10.8, minutes=200) + [_bar(T(11, 20) + timedelta(minutes=i), 10.0, v=40000)
                                             for i in range(120)] for s in SYMS}
    eng, data, src = _live_engine(tmp_path, pm)
    eng.scan(T(11, 0))
    r = eng.scan(T(13, 0))
    assert {a["alert_type"] for a in r.alerts} == {A.INVALIDATED}


def test_unknown_classification_is_a_hold_in_the_state_machine():
    prev = {"candidate_id": "c", "symbol": "X", "family": "GAP_UP", "state": S.BULLISH_SETUP,
            "last_alert_utc": T(9).isoformat(), "last_alert_score": 70, "last_alert_gap": 5.0}
    for cls in ("UNKNOWN:PROVIDER_INCOMPLETE", "UNKNOWN:PROVIDER_STALE"):
        assert A.decide(prev, A.Observation("X", cls, None, None, None, None), session_date="2026-09-23",
                        now=T(12), new_alerts_so_far=1) is None
        assert A.decide(None, A.Observation("X", cls, None, None, None, None), session_date="2026-09-23",
                        now=T(12), new_alerts_so_far=0) is None


# ================================================================ Phase 5: restart / resume
def test_restart_same_session_reuses_state_without_duplicates(tmp_path):
    pm = {s: _pm_series(10.8) for s in SYMS}
    eng1, _, _ = _live_engine(tmp_path, pm)
    eng1.scan(T(9, 0))
    eng1.scan(T(9, 15))
    before = eng1.store.alerts_for("2026-09-23")
    eng1.track_outcomes(T(20, 30))                                 # nothing post-open in the fake -> PENDING rows
    # process dies; new process, same DB, fresh in-memory watermark
    eng2, data2, src2 = _live_engine(tmp_path, pm)
    r = eng2.scan(T(9, 20))
    assert r.alerts == []                                          # no duplicate NEW alerts
    assert eng2._new_alerts_so_far() == eng1._new_alerts_so_far() == 3
    assert eng2.store.alerts_for("2026-09-23") == before
    # watermark rebuilt from the pre-market start: full history, no duplicates, nothing beyond as-of
    bars, _ = src2.premarket(data_as_of(T(9, 20)))
    ts = [b["t"] for b in bars["AAA"]]
    assert ts[0] == "2026-09-23T08:00:00Z" and len(ts) == len(set(ts))
    assert ts[-1] < iso(data_as_of(T(9, 20)))


def test_restart_preserves_invalidated_closure_cap_and_material_update_timing(tmp_path):
    pm = {"AAA": _pm_series(10.8), "BBB": _pm_series(10.8, minutes=60) + [
        _bar(T(9, 0) + timedelta(minutes=i), 10.0, v=40000) for i in range(260)]}
    cfg = PremarketConfig(max_new_alerts_per_session=2)
    eng1, _, _ = _live_engine(tmp_path, pm, cfg=cfg, syms=["AAA", "BBB"])
    eng1.scan(T(8, 45))                                            # AAA, BBB new
    eng1.scan(T(10, 0))                                            # BBB faded -> INVALIDATED
    eng2, _, _ = _live_engine(tmp_path, pm, cfg=cfg, syms=["AAA", "BBB"])
    assert eng2._active_candidate("BBB") is None                   # invalidated identity stays closed
    assert eng2._new_alerts_so_far() == 2                          # cap usage is durable
    row = eng2._active_candidate("AAA")
    assert row["last_alert_utc"] == T(8, 45).isoformat()           # MATERIAL_UPDATE clock survives


def test_crash_between_persist_and_route_is_rerouted_once_on_restart(tmp_path):
    routed = []

    def crashing_route(alert):
        raise SystemExit("process killed mid-route")

    pm = {"AAA": _pm_series(10.8)}
    eng1, _, _ = _live_engine(tmp_path, pm, route=crashing_route, syms=["AAA"])
    with pytest.raises(SystemExit):
        eng1.scan(T(9, 0))
    a = eng1.store.alerts_for("2026-09-23")
    assert len(a) == 1 and a[0]["routed"] == "PENDING_ROUTE"      # durable before routing
    eng2, _, _ = _live_engine(tmp_path, pm, route=lambda al: routed.append(al["alert_id"]) or "ENQUEUED_RESEARCH",
                              syms=["AAA"])
    assert eng2.resume_pending_routes() == 1 and eng2.resume_pending_routes() == 0
    assert routed == [a[0]["alert_id"]]
    assert eng2.scan(T(9, 5)).alerts == []                         # candidate exists -> no second NEW


# ================================================================ Phase 12: cap semantics (candidate identities)
def test_cap_counts_first_alerted_candidate_identities_not_sends(tmp_path):
    pm = {s: _pm_series(10.8) for s in ["AAA", "BBB", "CCC"]}
    cfg = PremarketConfig(max_new_alerts_per_session=2)
    eng, _, _ = _live_engine(tmp_path, pm, cfg=cfg)                # delivery disabled (record-only)
    r = eng.scan(T(9, 0))
    routed = sorted(a["routed"] for a in r.alerts)
    assert routed.count("RECORDED_NOT_DELIVERED") == 2 and routed.count("SUPPRESSED:SESSION_NEW_ALERT_CAP") == 1
    assert eng._new_alerts_so_far() == 2                           # suppressed candidate does not consume the cap
    eng.scan(T(10, 0))                                             # material updates / re-scans never consume it
    assert eng._new_alerts_so_far() == 2


# ================================================================ Phase 13: delivery state (enqueued != sent)
def test_enqueued_is_not_delivered_until_the_outbox_reports_sent(tmp_path, monkeypatch):
    from talonx_ops.notify.outbox import NotifyStore
    from talonx_premarket.__main__ import _router
    monkeypatch.delenv("TALONX_NOTIFY_RESEARCH_ENABLED", raising=False)
    route, drain, sync, info = _router(True, tmp_path / "research_notify.db")
    eng, _, _ = _live_engine(tmp_path, {"AAA": _pm_series(10.8)}, route=route, syms=["AAA"])
    eng.scan(T(9, 0))
    a = eng.store.alerts_for("2026-09-23")[0]
    assert a["routed"] == "ENQUEUED_RESEARCH_DESTINATION_DISABLED"
    assert sync(eng.store, "2026-09-23") == {"PENDING": 1}
    assert eng.store.candidates_for("2026-09-23")[0]["delivered"] == 0
    assert drain()["skipped_disabled"] == 1                        # disabled destination: nothing sent
    NotifyStore(str(tmp_path / "research_notify.db")).update_outbox(a["alert_id"], state="SENT", attempts=1,
                                                                     transport_ref="t", sent=True)
    assert sync(eng.store, "2026-09-23") == {"SENT": 1}
    assert eng.store.candidates_for("2026-09-23")[0]["delivered"] == 1
    route(a)                                                       # restart re-route: idempotent, no second row
    import sqlite3
    n = sqlite3.connect(tmp_path / "research_notify.db").execute(
        "SELECT COUNT(*) FROM ops_notification_outbox").fetchone()[0]
    assert n == 1


def test_record_only_mode_never_touches_an_outbox(tmp_path):
    from talonx_premarket.__main__ import _router
    route, drain, sync, info = _router(False, tmp_path / "never.db")
    eng, _, _ = _live_engine(tmp_path, {"AAA": _pm_series(10.8)}, route=route, syms=["AAA"])
    eng.scan(T(9, 0))
    assert drain() is None and sync(eng.store, "2026-09-23") == {"RECORDED_NOT_DELIVERED": 1}
    assert not (tmp_path / "never.db").exists()


def test_undeliverable_research_alert_expires_instead_of_arriving_late(tmp_path, monkeypatch):
    from talonx_ops.notify import RESEARCH
    from talonx_ops.notify.outbox import NotifyStore
    from talonx_ops.notify.worker import drain as wdrain
    monkeypatch.setenv("TALONX_NOTIFY_RESEARCH_ENABLED", "1")
    monkeypatch.setenv("TALONX_NOTIFY_RESEARCH_BOT_TOKEN", "research-token")
    monkeypatch.setenv("TALONX_NOTIFY_RESEARCH_CHAT_ID", "research-chat")
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "primary-token")
    monkeypatch.setenv("TELEGRAM_CHAT_ID", "primary-chat")
    monkeypatch.setenv("TALONX_NOTIFY_TRADE_EVENT_BOT_TOKEN", "primary-token")
    monkeypatch.setenv("TALONX_NOTIFY_TRADE_EVENT_CHAT_ID", "primary-chat")
    from talonx_premarket.__main__ import _router
    route, _, sync, info = _router(True, tmp_path / "n.db")
    assert info["research_destination_enabled"] is True
    eng, _, _ = _live_engine(tmp_path, {"AAA": _pm_series(10.8)}, route=route, syms=["AAA"])
    eng.scan(T(9, 0))
    st = NotifyStore(str(tmp_path / "n.db"))
    out = wdrain(st, destination=RESEARCH, now=T(9, 45), client=object())   # 45 min later: past deliver_by
    assert out["expired"] == 1 and sync(eng.store, "2026-09-23") == {"EXPIRED": 1}


# ================================================================ Phase 11: SEC unknown + 429 back-off
def test_sec_failure_is_catalyst_unknown_not_none_and_429_backs_off():
    t = [0.0]
    calls = {"n": 0}

    def get(url, headers):
        calls["n"] += 1
        raise RuntimeError("HTTP Error 429: Too Many Requests")

    sec = SecSubmissions(user_agent="ua", http_get=get, clock=lambda: t[0])
    assert sec.get("1") == (None, None) and calls["n"] == 1
    assert sec.get("2") == (None, None) and calls["n"] == 1 and sec.throttled == 1    # backing off
    t[0] = 61.0
    sec.get("3")
    assert calls["n"] == 2


def test_sec_refresh_failure_keeps_the_previous_copy():
    t = [0.0]
    ok = {"v": True}

    def get(url, headers):
        if ok["v"]:
            return {"filings": {"recent": {}}}
        raise TimeoutError("timed out")

    sec = SecSubmissions(user_agent="ua", http_get=get, clock=lambda: t[0], ttl_s=600)
    first, obs = sec.get("1")
    ok["v"] = False
    t[0] = 700.0
    again, obs2 = sec.get("1")
    assert again is first and obs2 == obs


def test_engine_labels_catalyst_unknown(tmp_path):
    class DeadSec:
        def get(self, cik):
            return None, None

    pm = {"AAA": _pm_series(10.8)}
    data = _FakeData({"AAA": _daily(10.0)}, pm)
    eng = Engine(universe=[UniverseMember("AAA", "A", "NASDAQ", "0000000001", "ELIGIBLE", "")],
                 source=LiveSource(data, ["AAA"], SD, PREMARKET_RESEARCH_V1), store=ResearchStore(tmp_path / "c.db"),
                 sd=SD, mode="live", v2_scope=set(), sec=DeadSec(), ledger_path=None, route=lambda a: "R")
    r = eng.scan(T(9, 0))
    assert r.funnel["provider"]["CATALYST_UNKNOWN"] == 1
    assert "catalyst lookup incomplete: SEC lookup failed" in r.alerts[0]["catalyst"]


def test_insider_ledger_unreadable_is_unknown(tmp_path):
    from talonx_premarket.catalysts import insider_open_market_owners
    assert insider_open_market_owners(str(tmp_path / "absent.db"), "AAA", scan_day=D, decision_utc=T(12)) is None


# ================================================================ Phase 6/7/17: stop.flag, session dirs, calendar
def test_session_directories_are_keyed_by_the_new_york_session_date():
    from zoneinfo import ZoneInfo

    from talonx_premarket.__main__ import OUT_ROOT, session_dir_for
    assert session_dir_for(date(2026, 9, 24)) == OUT_ROOT / "2026-09-24"
    # 00:30Z on 09-24 is still 09-23 in New York; 07:30Z on 09-24 is the 09-24 session
    ny = ZoneInfo("America/New_York")
    assert datetime(2026, 9, 24, 0, 30, tzinfo=UTC).astimezone(ny).date() == date(2026, 9, 23)
    assert datetime(2026, 9, 24, 7, 30, tzinfo=UTC).astimezone(ny).date() == date(2026, 9, 24)
    sd = session_day(date(2026, 9, 24))
    assert (sd.premarket_start_utc, sd.open_utc, sd.close_utc) == (
        datetime(2026, 9, 24, 8, 0, tzinfo=UTC), datetime(2026, 9, 24, 13, 30, tzinfo=UTC),
        datetime(2026, 9, 24, 20, 0, tzinfo=UTC))


class _Clock:
    def __init__(self, t):
        self.t = t

    def __call__(self):
        return self.t

    def sleep(self, s):
        self.t = self.t + timedelta(seconds=s)


def _run(tmp_path, eng, data, start, out=None):
    from talonx_premarket.__main__ import run_session
    out = out or (tmp_path / "2026-09-23")
    out.mkdir(parents=True, exist_ok=True)
    clk = _Clock(start)
    scans = []
    orig = eng.scan
    eng.scan = lambda now: scans.append(now) or orig(now)
    state = run_session(eng=eng, sd=SD, cfg=PREMARKET_RESEARCH_V1, data=data, base={}, out=out,
                        drain=lambda: None, sync=lambda st, s: {}, clock=clk, sleep=clk.sleep)
    return state, scans, out


def test_stale_previous_session_stop_flag_is_harmless(tmp_path):
    (tmp_path / "2026-09-22").mkdir()
    (tmp_path / "2026-09-22" / "stop.flag").write_text("old")
    eng, data, _ = _live_engine(tmp_path, {s: _pm_series(10.8) for s in SYMS})
    state, scans, _ = _run(tmp_path, eng, data, T(13, 0))
    assert state == "DONE" and scans


def test_same_session_stop_flag_stops_the_loop_and_is_preserved(tmp_path):
    eng, data, _ = _live_engine(tmp_path, {s: _pm_series(10.8) for s in SYMS})
    out = tmp_path / "2026-09-23"
    out.mkdir()
    (out / "stop.flag").write_text("operator")
    state, scans, _ = _run(tmp_path, eng, data, T(9, 0), out=out)
    assert state == "STOPPED_BY_FLAG" and scans == [] and (out / "stop.flag").exists()
    assert json.loads((out / "status.json").read_text())["state"] == "STOPPED_BY_FLAG"


def test_cmd_run_refuses_to_restart_over_a_same_session_stop_flag(tmp_path, monkeypatch, capsys):
    import talonx_premarket.__main__ as M
    monkeypatch.setattr(M, "OUT_ROOT", tmp_path)

    class FakeDT(datetime):
        @classmethod
        def now(cls, tz=None):
            return datetime(2026, 9, 24, 8, 5, tzinfo=UTC)

    monkeypatch.setattr(M, "datetime", FakeDT)
    (tmp_path / "2026-09-24").mkdir()
    (tmp_path / "2026-09-24" / "stop.flag").write_text("x")
    assert M.cmd_run(type("A", (), {"universe": "x", "deliver": False, "notify_db": "n.db", "v2_scope_log": None})()) == 3
    assert "rename it" in capsys.readouterr().out and (tmp_path / "2026-09-24" / "stop.flag").exists()


@pytest.mark.parametrize("start,expect_scans", [
    (T(7, 30), 41),          # before pre-market: full schedule
    (T(11, 2), 29),          # mid pre-market: only future scans (11:05 .. 13:25)
    (T(13, 26), 0),          # just before open: last scan (13:25) already past
    (T(14, 0), 0),           # after open: tracking only
])
def test_start_time_edges_never_scan_after_open(tmp_path, start, expect_scans):
    eng, data, _ = _live_engine(tmp_path, {s: _pm_series(10.8) for s in SYMS})
    state, scans, _ = _run(tmp_path, eng, data, start)
    assert state == "DONE" and len(scans) == expect_scans and all(s < SD.open_utc for s in scans)


def test_slow_scans_that_overrun_the_open_are_skipped(tmp_path):
    from talonx_premarket.__main__ import run_session
    eng, data, _ = _live_engine(tmp_path, {s: _pm_series(10.8) for s in SYMS})
    clk = _Clock(T(13, 20))
    scans = []

    def slow_scan(now):
        scans.append(now)
        clk.t = clk.t + timedelta(minutes=12)                         # a scan that takes 12 minutes
        return Engine.scan(eng, now)

    eng.scan = slow_scan
    out = tmp_path / "s"
    out.mkdir()
    run_session(eng=eng, sd=SD, cfg=PREMARKET_RESEARCH_V1, data=data, base={}, out=out, drain=lambda: None,
                sync=lambda st, s: {}, clock=clk, sleep=clk.sleep)
    assert all(s < SD.open_utc for s in scans) and len(scans) == 1


def test_early_close_day_tracks_until_the_actual_exchange_close():
    sd = session_day(date(2026, 11, 27))                                # day after Thanksgiving: 13:00 ET close
    assert sd.close_utc == datetime(2026, 11, 27, 18, 0, tzinfo=UTC)
    assert sd.open_utc == datetime(2026, 11, 27, 14, 30, tzinfo=UTC)    # EST


def test_dst_transition_sessions():
    assert session_day(date(2026, 3, 9)).open_utc.hour == 13           # first EDT session after spring-forward
    assert session_day(date(2026, 3, 6)).open_utc.hour == 14           # EST
    assert session_day(date(2026, 11, 2)).open_utc.hour == 14          # first EST session after fall-back
    assert session_day(date(2026, 10, 30)).open_utc.hour == 13


# ================================================================ Phase 15/19: status + evidence
def test_status_and_report_expose_the_operator_fields(tmp_path, monkeypatch):
    import talonx_premarket.__main__ as M
    monkeypatch.setattr(M, "OUT_ROOT", tmp_path)
    out = tmp_path / "2026-09-23"
    out.mkdir()
    eng = Engine(universe=_uni(), source=LiveSource(_FakeData({s: _daily(10.0) for s in SYMS},
                                                              {s: _pm_series(10.8) for s in SYMS}), SYMS, SD,
                                                    PREMARKET_RESEARCH_V1),
                 store=ResearchStore(out / "premarket_research.db"), sd=SD, mode="live", v2_scope=set(), sec=None,
                 ledger_path=None, route=lambda a: "RECORDED_NOT_DELIVERED")
    eng.store.start_run("2026-09-23", 1, T(7).isoformat(), "live", "fp", {})
    r = eng.scan(T(9, 0))
    from talonx_premarket.engine import write_status
    write_status(out / "status.json", {"pid": 1, "state": "SCANNED", "heartbeat_utc": T(9, 1).isoformat(),
                                       "config_fingerprint": PREMARKET_RESEARCH_V1.fingerprint(),
                                       "universe_total": 3, "universe_eligible": 3,
                                       "last_scan": {"funnel": r.funnel, "phase": r.phase,
                                                     "decision_utc": r.decision_utc,
                                                     "data_as_of_utc": r.data_as_of_utc}})
    st = M.build_status(out, now=T(9, 2))
    for k in ("SESSION", "PID", "STATE", "HEARTBEAT_AGE_S", "CONFIG_FP", "UNIVERSE", "ELIGIBLE", "CURRENT_PHASE",
              "LAST_SCAN", "NEXT_SCAN", "SCAN_DURATION_S", "DATA_AS_OF", "EFFECTIVE_SIP_DELAY", "PROVIDER_REQUESTS",
              "PROVIDER_ERRORS", "FAILED_BATCHES", "PROVIDER_COMPLETE", "DATA_READY", "HARD_REJECTED", "SCORED",
              "WATCH", "BULLISH_SETUP", "BEARISH_SETUP", "NEW_ALERTS_USED", "SUPPRESSED_BY_CAP", "DELIVERY_MODE",
              "OUTCOMES", "RUNS_THIS_SESSION"):
        assert k in st, k
    assert st["HEARTBEAT_AGE_S"] == 60.0 and st["NEW_ALERTS_USED"] == "3/25" and st["PROVIDER_COMPLETE"] is True
    assert M.cmd_report(type("A", (), {"date": "2026-09-23"})()) == 0
    md = (out / "evidence" / "CANARY_EVIDENCE.md").read_text(encoding="utf-8")
    assert "Scan timeline" in md and "Runs this session: 1" in md


def test_research_config_fingerprint_unchanged():
    assert PREMARKET_RESEARCH_V1.fingerprint() == "62ba413daf85e674"


# ================================================================ Phase 16: durable Intelligence poll history
def test_poll_history_is_append_only_bounded_and_secret_free(tmp_path):
    from talonx_ingest.intelligence.service import poll_history as ph
    summ = {"at_utc": "2026-09-24T08:00:00+00:00", "symbols_polled": 39, "symbols_failed": 0, "new_form4": 1,
            "new_events": 2, "freshness": "FRESH", "errors": ["ABC: token=SECRET-XYZ timed out"],
            "recovery": {"timed_out": 1, "failed": 0}, "delivery_ok": True, "health_causes": ["RECOVERY_PASS_TIMED_OUT"]}
    for i in range(1, 4):
        ph.record(tmp_path, cycle=i, summary=summ)
    rows = ph.read(tmp_path)
    assert [r["cycle"] for r in rows] == [1, 2, 3] and rows[0]["symbols_polled"] == 39 and rows[0]["error_count"] == 1
    assert "SECRET" not in (tmp_path / ph.FILE_NAME).read_text()          # counts only, never error text
    for i in range(4, 40):
        ph.record(tmp_path, cycle=i, summary=summ, max_bytes=2000)
    assert (tmp_path / (ph.FILE_NAME + ".1")).exists()
    assert (tmp_path / ph.FILE_NAME).stat().st_size < 4000                # bounded
    assert ph.read(tmp_path)[-1]["cycle"] == 39


def test_runner_records_poll_history_without_affecting_the_cycle():
    src = (Path(__file__).resolve().parents[1] / "talonx_ingest/intelligence/service/runner.py").read_text(encoding="utf-8")
    i = src.index("_record_poll(self.config.state_dir, cycle=cycles, summary=summary)")
    assert "try:" in src[i - 200:i] and "except Exception" in src[i:i + 200]
    for f in ("talonx_v2/service.py", "talonx_v2/form4_source.py", "talonx_v2/cluster_engine.py"):
        assert "poll_history" not in (Path(__file__).resolve().parents[1] / f).read_text(encoding="utf-8")
