"""
Broad-universe pre-market research engine (talonx_premarket): universe, data contract, features,
hard gates vs score, alert state machine / dedup, RESEARCH isolation, post-open outcomes, causal
replay (no lookahead), and the frozen-V2 boundary. No network: every provider is a fake.
"""
from __future__ import annotations

import ast
import json
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import pytest

from talonx_premarket import alerts as A
from talonx_premarket import features as F
from talonx_premarket import scoring as S
from talonx_premarket.alpaca_data import AlpacaData, RateLimiter, complete_bars_as_of, data_as_of, iso
from talonx_premarket.catalysts import Filing, evaluate, parse_submissions
from talonx_premarket.config import PREMARKET_RESEARCH_V1, PremarketConfig
from talonx_premarket.engine import Engine, ReplaySource, v2_scope_from_log
from talonx_premarket.outcomes import CONFIRMED, FAILED_CONFIRMATION, INVALIDATED, OUTCOME_PENDING, measure
from talonx_premarket.session import (CORE, EARLY, NEAR_OPEN, REGULAR, CLOSED, phase_at, scan_schedule,
                                      session_day)
from talonx_premarket.store import ResearchStore
from talonx_premarket.universe import build_universe, classify, summarize

REPO = Path(__file__).resolve().parents[1]
UTC = timezone.utc
D = date(2026, 9, 23)             # Wednesday, EDT
PREV = date(2026, 9, 22)


def _bar(t: datetime, c: float, v: float = 1000, o=None, h=None, l=None, n=10) -> dict:  # noqa: E741
    return {"t": iso(t), "o": o if o is not None else c, "h": h if h is not None else c, "l": l if l is not None else c,
            "c": c, "v": v, "vw": c, "n": n}


def _daily(prev_close=10.0, n=25, vol=1_000_000, last_day=PREV) -> list[dict]:
    rows, d = [], last_day
    days = []
    while len(days) < n:
        if d.weekday() < 5:
            days.append(d)
        d -= timedelta(days=1)
    for i, dd in enumerate(sorted(days)):
        c = prev_close * (1 - 0.001 * (n - 1 - i))
        rows.append({"t": f"{dd.isoformat()}T04:00:00Z", "o": c, "h": c * 1.01, "l": c * 0.99, "c": c, "v": vol,
                     "vw": c, "n": 100})
    rows[-1]["c"] = prev_close
    return rows


# ------------------------------------------------------------------------------------------ universe
def _asset(sym, name="Acme Corp Common Stock", exch="NASDAQ", **kw):
    return {"symbol": sym, "name": name, "exchange": exch, "class": "us_equity", "status": "active", "tradable": True, **kw}


def test_universe_is_deterministic_auditable_and_broader_than_39():
    import string
    letters = string.ascii_uppercase
    assets = [_asset("Q" + letters[i // 26] + letters[i % 26]) for i in range(60)]
    assets += [_asset("SPYX", "SPDR Something ETF", "ARCA"), _asset("WRNTW", "Acme Warrants"),
               _asset("OTCX", exch="OTC"), _asset("BAD-1"), _asset("NOCIK"), _asset("BRK.B", "Berkshire Class B", "NYSE"),
               _asset("ADRX", "Foo American Depositary Shares", "NYSE"), _asset("PRFX", "Foo Series A Preferred")]
    sec = {str(i): {"ticker": a["symbol"].replace(".", "-"), "cik_str": 1000 + i}
           for i, a in enumerate(assets) if a["symbol"] != "NOCIK"}
    m1 = build_universe(assets, sec)
    m2 = build_universe(list(reversed(assets)), sec)
    assert [x.__dict__ for x in m1] == [x.__dict__ for x in m2]          # order-independent
    s = summarize(m1)
    assert s["eligible"] > 39 and s["total"] == len(assets)
    by = {m.symbol: (m.status, m.reason) for m in m1}
    assert by["SPYX"] == ("EXCLUDED", "FUND_ETF_ETN") and by["WRNTW"] == ("EXCLUDED", "WARRANT")
    assert by["OTCX"] == ("EXCLUDED", "NOT_LISTED_EXCHANGE") and by["BAD-1"][1] == "MALFORMED_OR_NON_COMMON_SYMBOL"
    assert by["NOCIK"] == ("EXCLUDED", "NOT_SEC_REGISTRANT_TICKER") and by["PRFX"][1] == "PREFERRED"
    assert by["BRK.B"] == ("ELIGIBLE", "") and by["ADRX"] == ("ELIGIBLE", "")     # class shares + ADRs kept


def test_every_v2_scope_symbol_can_be_eligible():
    scope = v2_scope_from_log(REPO / "docs/research/evidence/v2_prospective_session_03/extracts/v2_companion_scope_line.txt") \
        if (REPO / "docs/research/evidence/v2_prospective_session_03/extracts/v2_companion_scope_line.txt").exists() else \
        {"AAPL", "ADC", "AFL", "MSFT"}
    assets = [_asset(s, f"{s} Inc") for s in scope]
    sec = {str(i): {"ticker": s, "cik_str": i} for i, s in enumerate(scope)}
    assert all(m.status == "ELIGIBLE" for m in build_universe(assets, sec))


# ------------------------------------------------------------------------------- session / calendar
def test_session_phases_follow_the_exchange_calendar_not_a_uk_clock():
    sd = session_day(D)
    assert sd.open_utc == datetime(2026, 9, 23, 13, 30, tzinfo=UTC)          # EDT
    assert sd.premarket_start_utc == datetime(2026, 9, 23, 8, 0, tzinfo=UTC)
    assert phase_at(datetime(2026, 9, 23, 7, 59, tzinfo=UTC)) == CLOSED
    assert phase_at(datetime(2026, 9, 23, 8, 30, tzinfo=UTC)) == EARLY
    assert phase_at(datetime(2026, 9, 23, 11, 30, tzinfo=UTC)) == CORE
    assert phase_at(datetime(2026, 9, 23, 13, 10, tzinfo=UTC)) == NEAR_OPEN
    assert phase_at(datetime(2026, 9, 23, 13, 30, tzinfo=UTC)) == REGULAR
    est = session_day(date(2026, 12, 2))                                     # EST: open 14:30Z
    assert est.open_utc.hour == 14 and est.premarket_start_utc.hour == 9
    assert phase_at(datetime(2026, 9, 26, 12, 0, tzinfo=UTC)) == CLOSED        # Saturday
    with pytest.raises(ValueError):
        session_day(date(2026, 11, 26))                                       # Thanksgiving


def test_scan_schedule_starts_one_sip_delay_after_premarket_and_ends_before_open():
    s = scan_schedule(D)
    assert s[0] == datetime(2026, 9, 23, 8, 15, tzinfo=UTC)
    assert s[-1] < session_day(D).open_utc and all(b > a for a, b in zip(s, s[1:]))
    early = [t for t in s if phase_at(t) == EARLY]
    assert all((b - a).total_seconds() == 900 for a, b in zip(early, early[1:]))


# ------------------------------------------------------------------------------------ data contract
def test_data_as_of_honours_the_15_minute_sip_delay_and_bars_must_be_complete():
    now = datetime(2026, 9, 23, 12, 0, 30, tzinfo=UTC)
    assert data_as_of(now) == datetime(2026, 9, 23, 11, 45, tzinfo=UTC)
    rows = [_bar(datetime(2026, 9, 23, 11, 43, tzinfo=UTC), 1), _bar(datetime(2026, 9, 23, 11, 44, tzinfo=UTC), 2),
            _bar(datetime(2026, 9, 23, 11, 45, tzinfo=UTC), 3)]
    assert [r["c"] for r in complete_bars_as_of(rows, data_as_of(now))] == [1, 2]   # 11:44 bar ends 11:45


def test_bars_client_batches_paginates_and_reports_errors():
    calls = []

    def get(url, params, headers):
        calls.append(params)
        assert params["feed"] == "sip" and params["adjustment"] == "split"
        if params.get("page_token") is None and params["symbols"].startswith("A"):
            return {"bars": {"A0": [{"t": "x"}]}, "next_page_token": "p2"}
        if params["symbols"].startswith("B"):
            raise RuntimeError("HTTP 500")
        return {"bars": {"A1": [{"t": "y"}]}, "next_page_token": None}

    cfg = PremarketConfig(bars_symbols_per_request=2)
    d = AlpacaData(key_id="k", secret="s", cfg=cfg, http_get=get, limiter=RateLimiter(1000))
    out = d.bars(["A0", "A1", "B0"], timeframe="1Min", start=datetime(2026, 9, 23, 8, tzinfo=UTC),
                 end=datetime(2026, 9, 23, 9, tzinfo=UTC))
    assert out == {"A0": [{"t": "x"}], "A1": [{"t": "y"}]}
    assert len(calls) == 4                      # A-batch: 2 pages; B-batch: 1 attempt + 1 retry
    assert d.errors and "HTTP 500" in d.errors[0]
    res = d.bars_ex(["B0"], timeframe="1Min", start=datetime(2026, 9, 23, 8, tzinfo=UTC),
                    end=datetime(2026, 9, 23, 9, tzinfo=UTC))
    assert res.failed == {"B0"} and not res.complete and res.failed_batches == 1 and res.retried_batches == 1


def test_rate_limiter_waits_instead_of_exceeding_budget():
    t = [0.0]
    slept = []
    rl = RateLimiter(3, clock=lambda: t[0], sleep=lambda s: (slept.append(s), t.__setitem__(0, t[0] + s)))
    for _ in range(4):
        rl.acquire()
    assert slept and slept[0] == pytest.approx(60.05)


# ------------------------------------------------------------------------------------------ features
def _pm(prices, start=datetime(2026, 9, 23, 8, 0, tzinfo=UTC), v=5000):
    return [_bar(start + timedelta(minutes=i), p, v=v) for i, p in enumerate(prices)]


def test_features_compute_a_causal_gap_volume_and_range_position():
    as_of = datetime(2026, 9, 23, 8, 30, tzinfo=UTC)
    f, why = F.compute("XYZ", _daily(10.0), _pm([10.5] * 20 + [10.8]), prev_session=PREV, data_as_of=as_of)
    assert why == "" and f.gap_pct == pytest.approx(8.0) and f.pm_bars == 21 and f.pm_volume == 21 * 5000
    assert f.range_position == "ABOVE_PREV_HIGH" and f.activity_adv_fraction == pytest.approx(0.105)
    assert f.staleness_min == pytest.approx(9.0)                              # last bar 08:20 ends 08:21


@pytest.mark.parametrize("daily,pm,reason", [
    (_daily(n=3), _pm([10.5]), "INSUFFICIENT_DAILY_HISTORY"),
    (_daily(last_day=date(2026, 9, 21)), _pm([10.5]), "MISSING_PREVIOUS_SESSION_BAR"),
    (_daily(), [], "NO_PREMARKET_PRINTS"),
    (_daily(), [{**_bar(datetime(2026, 9, 23, 8, tzinfo=UTC), 1), "c": float("nan")}], "NO_PREMARKET_PRINTS"),
])
def test_features_report_missing_or_nan_data_as_not_ready(daily, pm, reason):
    assert F.compute("XYZ", daily, pm, prev_session=PREV, data_as_of=datetime(2026, 9, 23, 9, tzinfo=UTC)) == (None, reason)


def test_hard_gates_reject_only_genuine_invalidity():
    as_of = datetime(2026, 9, 23, 9, 30, tzinfo=UTC)
    f, _ = F.compute("XYZ", _daily(10.0), _pm([10.4] * 30), prev_session=PREV, data_as_of=as_of)
    assert S.hard_gate(f) == "STALE_PREMARKET_PRICE"                          # last print 60 min old
    f, _ = F.compute("XYZ", _daily(10.0), _pm([10.4] * 30, start=datetime(2026, 9, 23, 9, tzinfo=UTC)),
                     prev_session=PREV, data_as_of=as_of)
    assert S.hard_gate(f) == ""
    f2, _ = F.compute("P", _daily(0.5), _pm([0.6] * 30, start=datetime(2026, 9, 23, 9, tzinfo=UTC)),
                      prev_session=PREV, data_as_of=as_of)
    assert S.hard_gate(f2) == "PRICE_BELOW_MIN"
    thin, _ = F.compute("T", _daily(10.0, vol=1000), _pm([10.4] * 30, start=datetime(2026, 9, 23, 9, tzinfo=UTC)),
                        prev_session=PREV, data_as_of=as_of)
    assert S.hard_gate(thin) == "INSUFFICIENT_LIQUIDITY"
    # a low-quality but VALID symbol (tiny gap, little volume) is scored, never hard-rejected
    weak, _ = F.compute("W", _daily(10.0), _pm([10.01] * 3, start=datetime(2026, 9, 23, 9, 20, tzinfo=UTC), v=10),
                        prev_session=PREV, data_as_of=as_of)
    assert S.hard_gate(weak) == "" and S.classify(weak, S.score(weak, "NONE")) == S.SCORED_ONLY


# --------------------------------------------------------------------------------------------- score
def test_config_is_frozen_and_fingerprinted():
    c = PREMARKET_RESEARCH_V1
    assert c.weights.total() == 100.0 and c.version == "PREMARKET_RESEARCH_V1"
    assert c.fingerprint() == PremarketConfig().fingerprint()
    with pytest.raises(Exception):
        c.setup_min_score = 1  # type: ignore[misc]
    assert PremarketConfig(setup_min_score=61).fingerprint() != c.fingerprint()


def test_config_fingerprint_is_pinned_to_the_pre_replay_value():
    pinned = json.loads((REPO / "talonx_premarket" / "frozen_config.json").read_text(encoding="utf-8"))
    assert PREMARKET_RESEARCH_V1.fingerprint() == pinned["fingerprint"]
    assert PREMARKET_RESEARCH_V1.as_dict() == pinned["config"]


def test_score_is_deterministic_explainable_and_classifies_setups():
    as_of = datetime(2026, 9, 23, 12, 0, tzinfo=UTC)
    up, _ = F.compute("UP", _daily(10.0), _pm([10.6] * 60, start=datetime(2026, 9, 23, 10, 50, tzinfo=UTC), v=20000),
                      prev_session=PREV, data_as_of=as_of)
    s1, s2 = S.score(up, "STRONG"), S.score(up, "STRONG")
    assert s1 == s2 and s1.total == pytest.approx(sum((s1.gap, s1.activity, s1.liquidity, s1.catalyst, s1.structure,
                                                        s1.data_confidence)), abs=0.05)
    assert any("gap +6.00%" in w for w in s1.why)
    assert S.classify(up, s1) == S.BULLISH_SETUP
    dn, _ = F.compute("DN", _daily(10.0), _pm([9.4] * 60, start=datetime(2026, 9, 23, 10, 50, tzinfo=UTC), v=20000),
                      prev_session=PREV, data_as_of=as_of)
    assert S.classify(dn, S.score(dn, "STRONG")) == S.BEARISH_SETUP
    mild, _ = F.compute("MI", _daily(10.0), _pm([10.25] * 60, start=datetime(2026, 9, 23, 10, 50, tzinfo=UTC), v=3000),
                        prev_session=PREV, data_as_of=as_of)
    assert S.classify(mild, S.score(mild, "OTHER")) == S.WATCH


# --------------------------------------------------------------------------------------- catalysts
def test_catalyst_timing_is_causal_and_uses_resolved_sec_acceptance():
    observed = datetime(2026, 9, 23, 22, 0, tzinfo=UTC)
    subs = {"filings": {"recent": {
        "form": ["8-K", "4", "8-K", "10-Q"],
        "accessionNumber": ["a1", "a2", "a3", "a4"],
        "filingDate": ["2026-09-23", "2026-09-22", "2026-09-23", "2026-09-01"],
        "acceptanceDateTime": ["2026-09-23T11:00:00.000Z", "2026-09-22T20:00:00.000Z",
                               "2026-09-23T14:00:00.000Z", "2026-09-01T12:00:00.000Z"],
        "items": ["2.02,9.01", "", "7.01", ""]}}}
    fl = parse_submissions(subs, observed_at=observed)
    ev = evaluate(fl, prev_session=PREV, scan_day=D, decision_utc=datetime(2026, 9, 23, 12, 0, tzinfo=UTC), live=False)
    assert ev.strength == "STRONG" and any("earnings" in lb for lb in ev.labels)
    assert {f.accession for f in ev.filings} == {"a1", "a2"}           # a3 accepted after the decision; a4 too old
    early = evaluate(fl, prev_session=PREV, scan_day=D, decision_utc=datetime(2026, 9, 23, 10, 0, tzinfo=UTC), live=False)
    assert {f.accession for f in early.filings} == {"a2"} and early.strength == "OTHER"


def test_unresolvable_same_day_acceptance_is_excluded_in_replay_but_kept_live():
    f = Filing("8-K", "x", D, None, "AMBIGUOUS", "8.01")
    dec = datetime(2026, 9, 23, 12, tzinfo=UTC)
    assert evaluate([f], prev_session=PREV, scan_day=D, decision_utc=dec, live=False).excluded_unverified == 1
    assert evaluate([f], prev_session=PREV, scan_day=D, decision_utc=dec, live=True).strength == "STRONG"


# ------------------------------------------------------------------------------ alerts / dedup
def _obs(cls, gap, score=70.0, sym="XYZ"):
    return A.Observation(sym, cls, gap, score, 10 * (1 + gap / 100), 10.0)


def _row(d: A.AlertDecision, obs, t):
    return {"candidate_id": d.candidate_id, "symbol": obs.symbol, "family": A.family_of(obs.gap_pct),
            "state": d.new_state, "last_alert_utc": t.isoformat(), "last_alert_score": obs.score,
            "last_alert_gap": obs.gap_pct, "first_alert_utc": t.isoformat()}


def test_alert_state_machine_new_upgrade_update_invalidate_and_no_duplicates():
    t0 = datetime(2026, 9, 23, 11, 0, tzinfo=UTC)
    d = A.decide(None, _obs(S.WATCH, 3.0, 45), session_date="2026-09-23", now=t0, new_alerts_so_far=0)
    assert d.alert_type == S.WATCH and d.candidate_id == "2026-09-23:XYZ:GAP_UP"
    row = _row(d, _obs(S.WATCH, 3.0, 45), t0)
    # unchanged re-scan -> nothing
    assert A.decide(row, _obs(S.WATCH, 3.1, 46), session_date="2026-09-23", now=t0 + timedelta(minutes=5),
                    new_alerts_so_far=1) is None
    # WATCH -> BULLISH_SETUP
    up = A.decide(row, _obs(S.BULLISH_SETUP, 4.0, 65), session_date="2026-09-23", now=t0 + timedelta(minutes=10),
                  new_alerts_so_far=1)
    assert up.alert_type == S.BULLISH_SETUP
    row = _row(up, _obs(S.BULLISH_SETUP, 4.0, 65), t0 + timedelta(minutes=10))
    # material move but too soon -> nothing; later -> MATERIAL_UPDATE
    assert A.decide(row, _obs(S.BULLISH_SETUP, 8.0, 90), session_date="2026-09-23", now=t0 + timedelta(minutes=20),
                    new_alerts_so_far=1) is None
    mu = A.decide(row, _obs(S.BULLISH_SETUP, 8.0, 90), session_date="2026-09-23", now=t0 + timedelta(minutes=45),
                  new_alerts_so_far=1)
    assert mu.alert_type == A.MATERIAL_UPDATE and mu.new_state == S.BULLISH_SETUP
    # fade -> INVALIDATED; an invalidated identity never re-alerts
    inv = A.decide(row, _obs(S.SCORED_ONLY, 0.5, 20), session_date="2026-09-23", now=t0 + timedelta(minutes=50),
                   new_alerts_so_far=1)
    assert inv.alert_type == A.INVALIDATED
    assert A.decide({**row, "state": A.INVALIDATED}, _obs(S.BULLISH_SETUP, 6.0), session_date="2026-09-23",
                    now=t0 + timedelta(hours=1), new_alerts_so_far=1) is None
    # direction flip invalidates the GAP_UP identity
    flip = A.decide(row, _obs(S.WATCH, -3.0), session_date="2026-09-23", now=t0 + timedelta(minutes=55),
                    new_alerts_so_far=1)
    assert flip.alert_type == A.INVALIDATED and flip.reason == "gap flipped direction"


def test_new_alert_cap_suppresses_instead_of_spamming():
    d = A.decide(None, _obs(S.WATCH, 3.0), session_date="2026-09-23", now=datetime(2026, 9, 23, 11, tzinfo=UTC),
                 new_alerts_so_far=PREMARKET_RESEARCH_V1.max_new_alerts_per_session)
    assert d.suppressed == "SESSION_NEW_ALERT_CAP"


def test_rendered_alert_is_research_only_and_never_a_trade_event():
    txt = A.render(S.BULLISH_SETUP, symbol="XYZ", name="Xyz Inc",
                   feats={"gap_pct": 4.2, "last_price": 10.42, "prev_close": 10.0, "pm_volume": 100000, "pm_dollars": 1e6,
                          "activity_adv_fraction": 0.1, "prev_low": 9.8, "prev_high": 10.1,
                          "range_position": "ABOVE_PREV_HIGH"},
                   score={"total": 70, "gap": 30, "activity": 25, "liquidity": 5, "catalyst": 0, "structure": 10,
                          "data_confidence": 0}, catalyst="none found", phase="CORE_PREMARKET",
                   data_as_of_utc="2026-09-23T12:00:00+00:00", reason="new candidate", inside_v2_scope=False)
    assert txt.startswith("[PREMARKET RESEARCH] XYZ — BULLISH_SETUP")
    assert "Gap: +4.20%" in txt and A.RESEARCH_FOOTER in txt and "15-min delayed" in txt
    assert "TRADE_EVENT" not in txt.replace("Not a V2 trade event", "")


def test_research_router_uses_only_the_research_destination(tmp_path, monkeypatch):
    from talonx_ops.notify import RESEARCH, TRADE_EVENT
    from talonx_ops.notify.outbox import NotifyStore
    from talonx_premarket.__main__ import _router
    monkeypatch.delenv("TALONX_NOTIFY_RESEARCH_ENABLED", raising=False)
    route, drain, sync, info = _router(True, tmp_path / "research.db")
    assert info["research_destination_enabled"] is False
    alert = {"alert_id": "2026-09-23:XYZ:GAP_UP:WATCH:t", "decision_utc": "2026-09-23T12:00:00+00:00",
             "alert_type": "WATCH", "text": "x", "candidate_id": "c", "symbol": "XYZ"}
    assert route(alert) == "ENQUEUED_RESEARCH_DESTINATION_DISABLED"
    route(alert)                                                               # idempotent
    st = NotifyStore(str(tmp_path / "research.db"))
    rows = st.outbox_due(now_iso="2026-09-23T12:01:00+00:00", destination=RESEARCH)
    assert len(rows) == 1 and rows[0]["event_type"].startswith("PREMARKET_RESEARCH_")
    assert not st.outbox_due(now_iso="2026-09-23T12:01:00+00:00", destination=TRADE_EVENT)
    assert drain()["skipped_disabled"] == 1                                   # disabled -> nothing sent
    r2, _, _, _ = _router(False, tmp_path / "x.db")
    assert r2(alert) == "RECORDED_NOT_DELIVERED"
    for protected in ("v2_release_rc1_notifications.db", "notifications.db", "v2_release_rc1.db"):
        with pytest.raises(SystemExit):
            _router(True, tmp_path / protected)


def test_research_destination_refuses_to_alias_the_primary_chat(monkeypatch):
    from talonx_ops.notify import RESEARCH, resolve_destination_config
    monkeypatch.setenv("TALONX_NOTIFY_RESEARCH_ENABLED", "1")
    monkeypatch.setenv("TALONX_NOTIFY_RESEARCH_BOT_TOKEN", "research-token")
    monkeypatch.setenv("TALONX_NOTIFY_RESEARCH_CHAT_ID", "same-chat")
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "primary-token")
    monkeypatch.setenv("TELEGRAM_CHAT_ID", "same-chat")
    monkeypatch.setenv("TALONX_NOTIFY_TRADE_EVENT_BOT_TOKEN", "primary-token")
    monkeypatch.setenv("TALONX_NOTIFY_TRADE_EVENT_CHAT_ID", "same-chat")
    assert resolve_destination_config(RESEARCH).enabled is False
    monkeypatch.setenv("TALONX_NOTIFY_RESEARCH_CHAT_ID", "research-chat")
    assert resolve_destination_config(RESEARCH).enabled is True


# ------------------------------------------------------------------------------ post-open outcomes
def test_outcome_horizons_mfe_mae_and_confirmation_status():
    sd = session_day(D)
    o = sd.open_utc
    bars = [_bar(o + timedelta(minutes=i), 10.5 + 0.01 * i, h=10.5 + 0.01 * i + 0.05, l=10.5 + 0.01 * i - 0.05)
            for i in range(390)]
    m = measure(family="GAP_UP", ref_price=10.4, prev_close=10.0, rth_bars=bars, open_utc=o, close_utc=sd.close_utc)
    assert m["status"] == CONFIRMED and m["open_px"] == 10.5
    assert m["px_30m"] == pytest.approx(10.79) and m["px_1h"] == pytest.approx(11.09)
    assert m["close_px"] == pytest.approx(10.5 + 3.89) and m["mfe_pct"] > m["close_ret_pct"] > 0
    assert m["mae_pct"] == pytest.approx((10.45 / 10.4 - 1) * 100, abs=1e-3)
    assert measure(family="GAP_UP", ref_price=10.4, prev_close=10.0, rth_bars=bars[:10], open_utc=o,
                   close_utc=sd.close_utc)["status"] == OUTCOME_PENDING
    fill = [_bar(o + timedelta(minutes=i), 9.9) for i in range(40)]
    assert measure(family="GAP_UP", ref_price=10.4, prev_close=10.0, rth_bars=fill, open_utc=o,
                   close_utc=sd.close_utc)["status"] == INVALIDATED
    down = [_bar(o + timedelta(minutes=i), 10.3) for i in range(40)]
    assert measure(family="GAP_UP", ref_price=10.4, prev_close=10.0, rth_bars=down, open_utc=o,
                   close_utc=sd.close_utc)["status"] == FAILED_CONFIRMATION
    short = measure(family="GAP_DOWN", ref_price=9.5, prev_close=10.0, rth_bars=[_bar(o + timedelta(minutes=i), 9.0)
                    for i in range(40)], open_utc=o, close_utc=sd.close_utc)
    assert short["status"] == CONFIRMED and short["ret_30m_pct"] > 0          # direction-adjusted


# ------------------------------------------------------------------------ engine: causal / no lookahead
class _FakeData:
    """Provider fake with Alpaca's verified semantics: ``end`` INCLUSIVE; optional per-symbol failure injection."""

    def __init__(self, daily, pm, rth=None, fail=None):
        self._d, self._pm, self._rth = daily, pm, rth or {}
        self.fail = fail if fail is not None else set()      # symbols whose batch fails (mutable during a test)
        self.requests, self.errors, self.calls = 0, [], []
        self.failed_batches_total = self.retried_batches_total = 0
        self.last_success_utc = None

    def bars_ex(self, symbols, *, timeframe, start, end, attempts=2):
        from talonx_premarket.alpaca_data import FetchResult, parse_ts
        self.requests += 1
        self.calls.append((timeframe, start, end, tuple(symbols)))
        src = self._d if timeframe == "1Day" else (self._rth if (start.hour, start.minute) >= (13, 30) else self._pm)
        res = FetchResult(batches=1)
        bad = set(symbols) & self.fail
        if bad:
            res.failed = set(bad)
            res.failed_batches = 1
            self.failed_batches_total += 1
            self.errors.append(f"injected failure {sorted(bad)}")
        res.bars = {s: [b for b in src.get(s, []) if start <= parse_ts(b["t"]) <= end]
                    for s in symbols if s not in bad}
        return res

    def bars(self, symbols, *, timeframe, start, end):
        return self.bars_ex(symbols, timeframe=timeframe, start=start, end=end).bars


def _engine(tmp_path, pm, rth=None):
    from talonx_premarket.universe import UniverseMember
    uni = [UniverseMember(s, f"{s} Inc", "NASDAQ", None, "ELIGIBLE", "") for s in ("AAA", "BBB")]
    sd = session_day(D)
    data = _FakeData({s: _daily(10.0) for s in ("AAA", "BBB")}, pm, rth)
    src = ReplaySource(data, ["AAA", "BBB"], sd, PREMARKET_RESEARCH_V1)
    return Engine(universe=uni, source=src, store=ResearchStore(tmp_path / "r.db"), sd=sd, mode="replay",
                  v2_scope={"AAA"}, sec=None, ledger_path=None, route=lambda a: "NOT_ROUTED_REPLAY")


def test_replay_scan_cannot_see_future_bars(tmp_path):
    start = datetime(2026, 9, 23, 11, 0, tzinfo=UTC)
    quiet = [_bar(start + timedelta(minutes=i), 10.01, v=100) for i in range(60)]
    spike = [_bar(datetime(2026, 9, 23, 12, 30, tzinfo=UTC) + timedelta(minutes=i), 11.0, v=50000) for i in range(30)]
    eng = _engine(tmp_path, {"AAA": quiet + spike, "BBB": quiet})
    early = eng.scan(datetime(2026, 9, 23, 12, 30, tzinfo=UTC))                # as-of 12:15: spike invisible
    assert early.funnel.get("ALERT_WORTHY", 0) == 0 and not early.alerts
    late = eng.scan(datetime(2026, 9, 23, 13, 15, tzinfo=UTC))                 # as-of 13:00: spike visible
    assert [(a["symbol"], a["alert_type"]) for a in late.alerts] == [("AAA", S.BULLISH_SETUP)]
    assert late.funnel["UNIVERSE"] == 2 and late.funnel["DATA_READY"] == 2
    again = eng.scan(datetime(2026, 9, 23, 13, 20, tzinfo=UTC))
    assert again.alerts == []                                                  # dedup: unchanged -> no alert
    assert "in V2 39-name scope" in late.alerts[0]["text"]


def test_outcomes_are_computed_only_after_alerts_and_do_not_change_them(tmp_path):
    start = datetime(2026, 9, 23, 11, 0, tzinfo=UTC)
    pm = {"AAA": [_bar(start + timedelta(minutes=i), 10.8, v=40000) for i in range(120)], "BBB": []}
    o = session_day(D).open_utc
    rth = {"AAA": [_bar(o + timedelta(minutes=i), 10.9) for i in range(390)]}
    eng = _engine(tmp_path, pm, rth)
    r = eng.scan(datetime(2026, 9, 23, 13, 15, tzinfo=UTC))
    before = eng.store.alerts_for("2026-09-23")
    outs = eng.track_outcomes(datetime(2026, 9, 23, 21, 0, tzinfo=UTC))
    assert r.alerts and eng.store.alerts_for("2026-09-23") == before
    assert outs[0]["status"] == CONFIRMED and outs[0]["close_px"] == 10.9


# ------------------------------------------------------------------------------ frozen V2 boundary
def test_no_frozen_release_module_imports_the_research_lane():
    offenders = []
    for pkg in ("talonx_v2", "talonx_ops", "talonx_dispatch", "talonx_ingest", "talonx_quant", "talonx_brain",
                "talonx_core", "talonx_signals"):
        for p in (REPO / pkg).rglob("*.py"):
            tree = ast.parse(p.read_text(encoding="utf-8"))
            for n in ast.walk(tree):
                mods = [a.name for a in n.names] if isinstance(n, ast.Import) else (
                    [n.module or ""] if isinstance(n, ast.ImportFrom) else [])
                if any(m.startswith("talonx_premarket") for m in mods):
                    offenders.append(str(p))
    assert offenders == []


def test_research_lane_has_no_trading_or_v2_ledger_capability():
    import io
    import tokenize
    for p in (REPO / "talonx_premarket").glob("*.py"):
        text = p.read_text(encoding="utf-8")
        names = {t.string for t in tokenize.generate_tokens(io.StringIO(text).readline) if t.type == tokenize.NAME}
        assert not names & {"TRADE_EVENT", "submit_order", "PaperTradingStore", "execute_buy", "execute_sell"}, p
        for forbidden in ("/v2/orders", "talonx_v2.store", "talonx_v2.pipeline", "import talonx_v2", "from talonx_v2"):
            assert forbidden not in text, (p, forbidden)


def test_v2_fingerprints_scope_and_campaign_unchanged():
    from talonx_v2 import provider_contract as pc
    from talonx_v2 import release_gate as rg
    assert rg._strategy_fingerprint() == "e2acf6454789217e"
    assert pc.RELEASE_CONTRACT.fingerprint() == "ac5e51aa3599d6c9"
    assert rg.RELEASE_PROFILE.campaign_id == "V2-PAPER-RC1"


def test_preflight_accepts_the_research_lane_but_still_rejects_other_runtime_changes():
    from talonx_ops.prospective import preflight as pf
    assert "talonx_premarket/engine.py".startswith(pf.FREEZE_RESEARCH_LANE_PREFIXES)
    assert not "talonx_v2/cluster_engine.py".startswith(pf.FREEZE_RESEARCH_LANE_PREFIXES)
    assert "talonx_v2/cluster_engine.py" not in pf.FREEZE_SESSION03_HARDENING_FILES


def test_session_cap_keeps_the_highest_scoring_new_candidates(tmp_path):
    """Replay finding (before outcomes): the cap used to follow alphabetical order."""
    from talonx_premarket.universe import UniverseMember
    syms = ["AAA", "BBB", "ZZZ"]
    start = datetime(2026, 9, 23, 11, 0, tzinfo=UTC)
    pm = {"AAA": [_bar(start + timedelta(minutes=i), 10.25, v=500) for i in range(120)],
          "BBB": [_bar(start + timedelta(minutes=i), 10.3, v=800) for i in range(120)],
          "ZZZ": [_bar(start + timedelta(minutes=i), 11.0, v=60000) for i in range(120)]}
    sd = session_day(D)
    data = _FakeData({s: _daily(10.0) for s in syms}, pm)
    cfg = PremarketConfig(max_new_alerts_per_session=1)
    eng = Engine(universe=[UniverseMember(s, s, "NASDAQ", None, "ELIGIBLE", "") for s in syms],
                 source=ReplaySource(data, syms, sd, cfg), store=ResearchStore(tmp_path / "c.db"), sd=sd,
                 mode="replay", v2_scope=set(), sec=None, ledger_path=None, cfg=cfg, route=lambda a: "R")
    r = eng.scan(datetime(2026, 9, 23, 13, 15, tzinfo=UTC))
    routed = {a["symbol"]: a["routed"] for a in r.alerts}
    assert routed["ZZZ"] == "R" and all(v.startswith("SUPPRESSED") for k, v in routed.items() if k != "ZZZ")
