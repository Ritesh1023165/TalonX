"""POST_DELIVERY_ALERT_MARKOUT_V1 revision 2 (INACTIVE package): synthetic alerts, synthetic transports, synthetic
bars/quotes only. No provider, no live store, no Telegram, no historical alert outcomes."""
from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import sqlite3
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace

import pytest

from talonx_paperperf import delivery_trace as T
from talonx_paperperf import post_delivery_acquisition as Q
from talonx_paperperf import post_delivery_markout as M

UTC = timezone.utc
REPO = Path(__file__).resolve().parents[1]
FIRST = "2026-10-12"                                       # Monday; EDT: regular 13:30-20:00Z


def t(h, m, s=0, d=12, mo=10):
    return datetime(2026, mo, d, h, m, s, tzinfo=UTC)


def z(dt):
    return dt.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def bar(start, o=100.0, c=100.0, v=100):
    return {"t": z(start), "o": o, "h": max(o, c), "l": min(o, c), "c": c, "v": v}


def quote(at, bid, ask):
    return {"t": at.astimezone(UTC).isoformat().replace("+00:00", "Z"), "bp": bid, "ap": ask}


# ============================================================================================ timing
def test_mid_minute_delivery_rounds_up_after_the_reaction_delay():
    g = M.targets(t(14, 10, 30))
    assert g["entry_utc"] == t(14, 16) and g["exit_utc"] == t(14, 46)
    assert g["entry_bar_start"] == t(14, 16) and g["exit_bar_start"] == t(14, 45)   # exit bar = [X-1m, X)


def test_exact_minute_boundary_is_kept():
    g = M.targets(t(14, 10, 0))
    assert g["entry_utc"] == t(14, 15) and g["exit_utc"] == t(14, 45)


def test_exit_may_equal_the_close_but_not_exceed_it_and_nothing_is_shifted():
    ok = M.targets(t(19, 25))                                  # E 19:30, X 20:00 == close
    assert ok["eligible"] and ok["exit_utc"] == t(20, 0)
    assert M.targets(t(19, 25, 1))["reason"] == "EXIT_AFTER_CLOSE"
    assert M.targets(t(19, 56))["reason"] == "ENTRY_AT_OR_AFTER_CLOSE"           # reaction delay crosses the close
    assert M.targets(t(13, 0))["reason"] == "DELIVERED_OUTSIDE_REGULAR_SESSION"


def test_half_day_and_dst_closes_come_from_the_exchange_calendar():
    assert M.targets(datetime(2026, 11, 27, 17, 25, tzinfo=UTC))["exit_utc"] == datetime(2026, 11, 27, 18, 0,
                                                                                         tzinfo=UTC)
    assert not M.targets(datetime(2026, 11, 27, 17, 26, tzinfo=UTC))["eligible"]
    est = M.targets(datetime(2026, 11, 2, 20, 25, tzinfo=UTC))                  # EST: close 21:00Z
    assert est["eligible"] and est["exit_utc"] == datetime(2026, 11, 2, 21, 0, tzinfo=UTC)


def test_deadline_is_second_subsequent_close_plus_60_minutes():
    from talonx_opportunity.phases import trading_window
    assert M.deadline(trading_window(date(2026, 10, 12))) == t(21, 0, d=14)
    assert M.deadline(trading_window(date(2026, 11, 25))) == datetime(2026, 11, 30, 22, 0, tzinfo=UTC)  # holiday, half day


# ============================================================================================ exact bars
def test_only_the_exact_target_bars_count():
    e = t(14, 16)
    assert M.target_bar([bar(e)], e)[1] == "OK"
    assert M.target_bar([bar(e - timedelta(minutes=1)), bar(e + timedelta(minutes=1))], e) == (None, "ABSENT")
    assert M.target_bar([bar(e, v=0)], e) == (None, "ZERO_VOLUME")
    assert M.target_bar([bar(e, o=float("nan"))], e) == (None, "INVALID_PRICE")
    assert M.target_bar([bar(e), bar(e)], e) == (None, "DUPLICATE_BARS")


# ============================================================================================ quotes / cost
def test_quote_lookback_rules():
    tgt = t(14, 16)
    assert M.select_quote([quote(tgt, 99.9, 100.1)], tgt)[0]["bid"] == 99.9                  # at target
    assert M.select_quote([quote(tgt - timedelta(seconds=61), 99, 101)], tgt)[1] == "NO_VALID_QUOTE_WITHIN_60S"
    assert M.select_quote([quote(tgt + timedelta(seconds=1), 99, 101)], tgt)[0] is None      # after target never
    crossed = [quote(tgt, 100.2, 100.0), quote(tgt - timedelta(seconds=5), 99.8, 100.2)]
    assert M.select_quote(crossed, tgt)[0]["t"].startswith("2026-10-12T14:15:55")             # crossed skipped
    locked = M.select_quote([quote(tgt, 100.0, 100.0)], tgt)[0]
    assert locked["locked"] and M.half_spread(locked) == 0.0
    same = [quote(tgt, 99.95, 100.05), quote(tgt, 99.9, 100.1)]
    assert M.select_quote(same, tgt)[0]["bid"] == 99.9                                         # widest at equal time
    assert M.select_quote(list(reversed(same)), tgt)[0]["bid"] == 99.9                         # order-independent


def test_nanosecond_quote_times_after_the_target_are_rejected():
    tgt = t(14, 16)
    after = {"t": "2026-10-12T14:16:00.000000300Z", "bp": 99.0, "ap": 101.0}
    at = {"t": "2026-10-12T14:15:59.999999999Z", "bp": 99.5, "ap": 100.5}
    assert M.select_quote([after], tgt)[0] is None
    q = M.select_quote([after, at], tgt)[0]
    assert q["bid"] == 99.5 and q["t_ns"] < M.ts_ns("2026-10-12T14:16:00Z")


def test_half_spread_formula_and_5bps_subtracted_once():
    qe, qx = {"bid": 99.9, "ask": 100.1}, {"bid": 101.8, "ask": 102.2}
    r = M.compute({"o": 100.0}, {"c": 102.0}, qe, qx)
    sc = 0.2 / (2 * 100.0) + 0.4 / (2 * 102.0)
    assert r["gross"] == pytest.approx(0.02) and r["spread_cost"] == pytest.approx(sc)
    assert r["cost_adjusted"] == pytest.approx(0.02 - sc - 0.0005)
    assert M.compute({"o": 100.0}, {"c": 102.0}, None, qx)["cost_adjusted"] is None


# ============================================================================================ fixtures: sources
def sources(tmp_path, rows):
    ob = sqlite3.connect(tmp_path / "outbox.db")
    ob.execute("CREATE TABLE ops_notification_outbox (event_id TEXT PRIMARY KEY, destination TEXT, event_type TEXT, "
               "producer TEXT, dedup_key TEXT, payload_text TEXT, state TEXT, attempts INT, last_error TEXT, "
               "created_at_utc TEXT, updated_at_utc TEXT, sent_at_utc TEXT)")
    pc = sqlite3.connect(tmp_path / "promotion.db")
    pc.execute("CREATE TABLE promotions (promotion_id TEXT, symbol TEXT, window_id TEXT, state TEXT, reason_code TEXT, "
               "policy_fp TEXT, signal_event_id TEXT)")
    for r in rows:
        sent = r.get("sent")
        created = r.get("created") or (sent - timedelta(seconds=1) if sent else t(14, 0))
        ob.execute("INSERT INTO ops_notification_outbox VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
                   (r["id"], "TRADE_EVENT", r.get("etype", M.EVENT_TYPE), "talonx_opportunity.promotion", r["id"],
                    f"alert {r['id']}", r.get("state", "SENT"), r.get("attempts", 1), r.get("last_error"),
                    created.isoformat(), created.isoformat(), sent.isoformat() if sent else None))
        pc.execute("INSERT INTO promotions VALUES (?,?,?,?,?,?,?)",
                   (r["id"], r["sym"], (sent or created).date().isoformat(), "PROMOTED_SIGNAL", M.REVIEW_REASON,
                    r.get("pol", "PFP"), r["id"]))
    ob.commit()
    pc.commit()
    return tmp_path / "outbox.db", tmp_path / "promotion.db"


def activation(tmp_path, **over):
    d = {"approved": True, "approved_by": "owner", "approved_utc": "2026-10-10T12:00:00Z",
         "protocol_fingerprint": M.PDM_V1.fingerprint(), "first_session": FIRST,
         "delivery_trace_policy": "NOT_AVAILABLE_ACCEPTED", **over}
    p = tmp_path / "act.json"
    p.write_text(json.dumps(d), encoding="utf-8")
    return p


class FakeAcq:
    """Synthetic acquirer: market-time keyed data; ``down`` makes every call fail; ``late`` delays availability."""
    def __init__(self, bars=None, quotes=None, down=None, available_from=None, permit=True):
        self.bars, self.quotes, self.down, self.available_from, self.permit = bars or {}, quotes or {}, down, \
            available_from, permit
        self.calls = []
        self.now = None

    def permitted(self, now):
        self.now = now
        return self.permit

    def _gate(self):
        if self.down:
            return {"outcome": self.down, "detail": "synthetic"}
        if self.available_from and self.now < self.available_from:
            return {"outcome": Q.TRANSPORT, "detail": "provider not yet serving"}
        return None

    def bar(self, sym, start):
        self.calls.append(("bar", sym, start))
        return self._gate() or {"outcome": Q.RETRIEVED, "payload": self.bars.get((sym, start), []), "scope": {},
                                "provider": "fake"}

    def quote(self, sym, target):
        self.calls.append(("quote", sym, target))
        return self._gate() or {"outcome": Q.RETRIEVED, "payload": self.quotes.get((sym, target), []), "scope": {},
                                "provider": "fake"}


def good_data(sym, anchor, entry=100.0, exit_=101.0, spread=(0.1, 0.1)):
    g = M.targets(anchor)
    e, xb, x = g["entry_utc"], g["exit_bar_start"], g["exit_utc"]
    b = {(sym, e): [bar(e, o=entry, c=entry)], (sym, xb): [bar(xb, o=exit_, c=exit_)]}
    q = {(sym, e): [quote(e, entry - spread[0] / 2, entry + spread[0] / 2)],
         (sym, x): [quote(x, exit_ - spread[1] / 2, exit_ + spread[1] / 2)]}
    return b, q


def run(tmp_path, ob, pc, acq, now, **env):
    e = {M.ENABLE_ENV: "1", M.CONFIG_ENV: str(activation(tmp_path, **env))}
    return M.run(e, store_root=tmp_path / "pdm", acquirer=acq, now=now, outbox_path=ob, promotion_path=pc)


def obs(tmp_path):
    s = M.Store(tmp_path / "pdm")
    return {o["event_id"]: o for o in s.q("SELECT * FROM observations")}, s


# ============================================================================================ orchestration
def test_end_to_end_measurement_with_costs(tmp_path):
    ob, pc = sources(tmp_path, [dict(id="A1", sym="AAA", sent=t(14, 10, 30))])
    b, q = good_data("AAA", t(14, 10, 30))
    r = run(tmp_path, ob, pc, FakeAcq(b, q), t(21, 5))
    assert r["state"] == "ENABLED"
    o, s = obs(tmp_path)
    assert o["A1"]["state"] == M.MEASURED and o["A1"]["cost_state"] == M.COST_OK
    res = s.q("SELECT * FROM results")[0]
    assert res["gross"] == pytest.approx(0.01)
    assert res["cost_adjusted"] == pytest.approx(0.01 - (0.05 / 100 + 0.05 / 101) - 0.0005)
    assert len(s.q("SELECT * FROM inputs")) == 4 and all(r["sha256"] for r in s.q("SELECT sha256 FROM inputs"))


def test_not_acquired_before_close_plus_60_and_r5_window_respected(tmp_path):
    ob, pc = sources(tmp_path, [dict(id="A1", sym="AAA", sent=t(14, 10))])
    acq = FakeAcq(*good_data("AAA", t(14, 10)))
    assert run(tmp_path, ob, pc, acq, t(20, 30))["acquisition"]["skipped_not_matured"] == 1
    blocked = FakeAcq(*good_data("AAA", t(14, 10)), permit=False)
    assert run(tmp_path, ob, pc, blocked, t(21, 5))["acquisition"]["skipped_window"] == 1
    assert acq.calls == [] and blocked.calls == []
    assert Q.r5_permitted(t(20, 31)) and not Q.r5_permitted(datetime(2026, 11, 27, 19, 0, tzinfo=UTC))  # half day 14:00 ET


def test_missing_and_zero_volume_target_bars_are_missing_not_zero(tmp_path):
    ob, pc = sources(tmp_path, [dict(id="M1", sym="AAA", sent=t(14, 10)), dict(id="M2", sym="BBB", sent=t(14, 10))])
    g = M.targets(t(14, 10))
    bars = {("AAA", g["entry_utc"] + timedelta(minutes=1)): [bar(g["entry_utc"] + timedelta(minutes=1))],   # neighbour
            ("AAA", g["exit_bar_start"]): [bar(g["exit_bar_start"])],
            ("BBB", g["entry_utc"]): [bar(g["entry_utc"])], ("BBB", g["exit_bar_start"]): [bar(g["exit_bar_start"], v=0)]}
    run(tmp_path, ob, pc, FakeAcq(bars), t(21, 5))
    o, s = obs(tmp_path)
    assert o["M1"]["state"] == M.MISSING_ENTRY and o["M2"]["state"] == M.MISSING_EXIT
    assert s.q("SELECT COUNT(*) n FROM results")[0]["n"] == 0                # never a zero return


def test_missing_quotes_keep_the_gross_and_mark_cost_unavailable(tmp_path):
    ob, pc = sources(tmp_path, [dict(id="Q1", sym="AAA", sent=t(14, 10))])
    b, _ = good_data("AAA", t(14, 10))
    run(tmp_path, ob, pc, FakeAcq(b, {}), t(21, 5))
    o, s = obs(tmp_path)
    assert o["Q1"]["state"] == M.MEASURED and o["Q1"]["cost_state"] == M.COST_NO_QUOTE
    r = s.q("SELECT gross, cost_adjusted, spread_cost FROM results")[0]
    assert r["gross"] is not None and r["cost_adjusted"] is None and r["spread_cost"] is None


def test_delayed_provider_does_not_move_market_time_targets(tmp_path):
    ob, pc = sources(tmp_path, [dict(id="D1", sym="AAA", sent=t(14, 10))])
    b, q = good_data("AAA", t(14, 10))
    acq = FakeAcq(b, q, available_from=t(23, 0))
    run(tmp_path, ob, pc, acq, t(21, 5))
    o, _ = obs(tmp_path)
    assert o["D1"]["state"] == M.SELECTED_WAITING
    run(tmp_path, ob, pc, acq, t(23, 30))
    o, _ = obs(tmp_path)
    assert o["D1"]["state"] == M.MEASURED and o["D1"]["entry_utc"] == t(14, 15).isoformat()
    assert {c[2] for c in acq.calls if c[0] == "bar"} == {t(14, 15), t(14, 44)}  # the same market-time targets


def test_partial_retrieval_retries_only_missing_parts_and_quote_failure_expires_with_gross(tmp_path):
    ob, pc = sources(tmp_path, [dict(id="P1", sym="AAA", sent=t(14, 10))])
    b, _ = good_data("AAA", t(14, 10))

    class QuoteDown(FakeAcq):
        def quote(self, sym, target):
            self.calls.append(("quote", sym, target))
            return {"outcome": Q.ENTITLE, "detail": "HTTP 403"}
    acq = QuoteDown(b)
    run(tmp_path, ob, pc, acq, t(21, 5))
    run(tmp_path, ob, pc, acq, t(22, 5))
    assert sum(1 for c in acq.calls if c[0] == "bar") == 2                   # bars fetched once, never again
    o, s = obs(tmp_path)
    assert o["P1"]["state"] == M.SELECTED_WAITING
    run(tmp_path, ob, pc, acq, t(21, 0, d=14))                              # deadline: gross kept, cost failed
    o, s = obs(tmp_path)
    assert o["P1"]["state"] == M.MEASURED and o["P1"]["cost_state"] == M.COST_ACQ_FAILED
    assert {r["error_class"] for r in s.q("SELECT error_class FROM acquisition_errors")} == {Q.ENTITLE}


@pytest.mark.parametrize("acq", [None, FakeAcq(down=Q.TRANSPORT), FakeAcq(down=Q.ENTITLE)])
def test_no_fetcher_outage_or_entitlement_failure_still_expire_at_the_deadline(tmp_path, acq):
    ob, pc = sources(tmp_path, [dict(id="X1", sym="AAA", sent=t(14, 10))])
    run(tmp_path, ob, pc, acq, t(21, 5))
    assert obs(tmp_path)[0]["X1"]["state"] == M.SELECTED_WAITING
    run(tmp_path, ob, pc, acq, t(21, 0, d=14))
    o, s = obs(tmp_path)
    assert o["X1"]["state"] == M.EXPIRED


def test_restart_after_the_deadline_reconciles_first_and_never_reopens(tmp_path):
    ob, pc = sources(tmp_path, [dict(id="R1", sym="AAA", sent=t(14, 10))])
    run(tmp_path, ob, pc, None, t(21, 5))                                    # registered, then the worker is down
    late = FakeAcq(*good_data("AAA", t(14, 10)))
    r = run(tmp_path, ob, pc, late, t(9, 0, d=20))                           # restart a week later
    assert r["expired_before"] == 1 and late.calls == []                    # expiry BEFORE any request
    run(tmp_path, ob, pc, late, t(10, 0, d=21))
    assert obs(tmp_path)[0]["R1"]["state"] == M.EXPIRED and late.calls == []  # data now available: not reopened


def test_first_alert_selection_is_fixed_before_any_price_data(tmp_path):
    ob, pc = sources(tmp_path, [dict(id="F2", sym="AAA", sent=t(14, 30)), dict(id="F1", sym="AAA", sent=t(14, 10)),
                                dict(id="G1", sym="AAA", sent=t(14, 10, d=13))])
    acq = FakeAcq(*good_data("AAA", t(14, 30)))                             # only the LATER alert has data
    run(tmp_path, ob, pc, acq, t(21, 5))
    o, _ = obs(tmp_path)
    assert o["F1"]["state"] == M.MISSING_ENTRY and o["F2"]["state"] == M.REPEAT   # no substitution
    assert o["G1"]["state"] == M.SELECTED_WAITING                                 # next session: own observation


def test_equal_anchor_tie_break_is_the_stable_id(tmp_path):
    ob, pc = sources(tmp_path, [dict(id="B-2", sym="AAA", sent=t(14, 10)), dict(id="B-1", sym="AAA", sent=t(14, 10))])
    run(tmp_path, ob, pc, None, t(15, 0))
    o, _ = obs(tmp_path)
    assert o["B-1"]["state"] == M.SELECTED_WAITING and o["B-2"]["state"] == M.REPEAT


def test_ambiguous_deliveries_are_never_definitely_delivered(tmp_path):
    ob, pc = sources(tmp_path, [dict(id="W2", sym="AAA", sent=t(14, 10), attempts=2),
                                dict(id="ER", sym="BBB", sent=t(14, 10), last_error="timed out"),
                                dict(id="AM", sym="CCC", state="AMBIGUOUS", created=t(14, 9)),
                                dict(id="AA", sym="AAA", sent=t(14, 20)),
                                dict(id="FL", sym="DDD", state="FAILED", created=t(14, 9))])
    run(tmp_path, ob, pc, None, t(15, 0))
    o, s = obs(tmp_path)
    assert (o["W2"]["state"], o["ER"]["state"], o["AM"]["state"]) == (M.AMBIGUOUS,) * 3
    assert o["AA"]["state"] == M.REPEAT                                      # earlier ambiguous send wins selection
    assert "FL" not in o                                                     # never delivered: not a delivery


def test_trace_required_policy_and_clock_checks():
    row = {"state": "SENT", "attempts": 1, "last_error": None, "sent_at_utc": t(14, 10, 2).isoformat()}
    good = {"send_start_utc": t(14, 10, 0).isoformat(), "response_utc": t(14, 10, 1).isoformat(),
            "server_date_utc": t(14, 10, 1).isoformat(), "hidden_retries": 0}
    assert M.classify_delivery(row, None, "REQUIRED")[0] == M.AMBIGUOUS
    assert M.classify_delivery(row, good, "REQUIRED")[0] == "DELIVERED_CLEAN"
    assert M.classify_delivery(row, {**good, "hidden_retries": 1}, "REQUIRED")[0] == M.AMBIGUOUS   # retry after timeout
    assert M.classify_delivery(row, {**good, "server_date_utc": t(14, 9, 50).isoformat()}, "REQUIRED")[0] == M.CLOCK
    assert M.classify_delivery({**row, "sent_at_utc": t(14, 9, 0).isoformat()}, good, "REQUIRED")[0] == M.CLOCK


def test_duplicate_processing_is_idempotent(tmp_path):
    ob, pc = sources(tmp_path, [dict(id="I1", sym="AAA", sent=t(14, 10))])
    acq = FakeAcq(*good_data("AAA", t(14, 10)))
    for k in range(3):
        run(tmp_path, ob, pc, acq, t(21, 5 + k))
    o, s = obs(tmp_path)
    assert len(o) == 1 and len(s.q("SELECT * FROM results")) == 1 and len(acq.calls) == 4


def test_policy_change_is_a_separate_segment_without_resetting_the_clock(tmp_path):
    ob, pc = sources(tmp_path, [dict(id="S1", sym="AAA", sent=t(14, 10), pol="FP1"),
                                dict(id="S2", sym="BBB", sent=t(14, 10, d=13), pol="FP2")])
    run(tmp_path, ob, pc, None, t(15, 0, d=13))
    o, _ = obs(tmp_path)
    assert o["S1"]["segment"] != o["S2"]["segment"]
    act = M.load_activation(activation(tmp_path))
    assert act["sessions"][0] == FIRST and len(act["sessions"]) == 20      # fixed from the first session


def test_population_excludes_pre_activation_legacy_and_out_of_period_alerts(tmp_path):
    ob, pc = sources(tmp_path, [dict(id="OLD", sym="AAA", sent=t(14, 10, d=9)),
                                dict(id="LEG", sym="BBB", sent=t(14, 10), etype="PAPER_OPPORTUNITY"),
                                dict(id="AFTER", sym="CCC", sent=datetime(2026, 11, 12, 15, 0, tzinfo=UTC)),
                                dict(id="IN", sym="DDD", sent=t(14, 10))])
    run(tmp_path, ob, pc, None, datetime(2026, 11, 13, 1, 0, tzinfo=UTC))
    assert set(obs(tmp_path)[0]) == {"IN"}


# ============================================================================================ activation / isolation
@pytest.mark.parametrize("over,why", [({"approved": False}, "NOT_APPROVED"),
                                      ({"protocol_fingerprint": "x"}, "PROTOCOL_FINGERPRINT_MISMATCH"),
                                      ({"first_session": "2026-10-11"}, "FIRST_SESSION_NOT_A_TRADING_SESSION"),
                                      ({"approved_utc": "2026-10-12T10:00:00Z"}, "ACTIVATION_NOT_BEFORE_A_FULL_SESSION"),
                                      ({"delivery_trace_policy": None}, "DELIVERY_TRACE_POLICY_MISSING")])
def test_unapproved_configs_are_refused(tmp_path, over, why):
    r = M.run({M.ENABLE_ENV: "1", M.CONFIG_ENV: str(activation(tmp_path, **over))}, store_root=tmp_path / "pdm")
    assert r["state"] == "NOT_APPROVED" and r["reason"].startswith(why) and not (tmp_path / "pdm").exists()


def test_disabled_by_default_creates_nothing(tmp_path):
    assert M.run({}, store_root=tmp_path / "pdm") == {"state": "DISABLED"}
    assert M.run({M.ENABLE_ENV: "1"}, store_root=tmp_path / "pdm") == {"state": "NOT_APPROVED",
                                                                      "reason": "NO_ACTIVATION_CONFIG"}
    assert not (tmp_path / "pdm").exists()


def test_production_source_stores_are_never_written(tmp_path):
    ob, pc = sources(tmp_path, [dict(id="N1", sym="AAA", sent=t(14, 10))])
    before = [hashlib.md5(Path(p).read_bytes()).hexdigest() for p in (ob, pc)]
    run(tmp_path, ob, pc, FakeAcq(*good_data("AAA", t(14, 10))), t(21, 5))
    assert [hashlib.md5(Path(p).read_bytes()).hexdigest() for p in (ob, pc)] == before


def test_endpoint_waits_for_final_session_maturity_and_refuses_early_reports(tmp_path):
    act = M.load_activation(activation(tmp_path))
    last = act["sessions"][-1]
    assert last == "2026-11-06" and act["endpoint_utc"] == datetime(2026, 11, 10, 22, 0, tzinfo=UTC)  # EST close+60
    ob, pc = sources(tmp_path, [dict(id="L1", sym="AAA", sent=datetime(2026, 11, 6, 15, 0, tzinfo=UTC))])
    run(tmp_path, ob, pc, None, datetime(2026, 11, 6, 22, 30, tzinfo=UTC))
    s = M.Store(tmp_path / "pdm")
    assert M.final_report(s, act, datetime(2026, 11, 7, tzinfo=UTC))["status"] == "NOT_AVAILABLE_BEFORE_ENDPOINT"
    acq = FakeAcq(*good_data("AAA", datetime(2026, 11, 6, 15, 0, tzinfo=UTC)))
    run(tmp_path, ob, pc, acq, datetime(2026, 11, 9, 23, 0, tzinfo=UTC))   # delayed completion inside the expiry
    rep = M.final_report(s, act, act["endpoint_utc"])
    seg = next(iter(rep.values()))
    assert seg["gross_measured"] == 1 and seg["cost_adjusted_measured"] == 1 and "NOT portfolio" in seg["note"]


def test_package_is_not_registered_or_imported_by_any_runtime():
    from talonx_opportunity import runtime, supervise
    assert not any("post_delivery" in c or "delivery_trace" in c for c in supervise.COMPONENTS)
    for pkg in ("talonx_opportunity", "talonx_ops", "talonx_v2", "talonx_dispatch", "talonx_ingest", "scripts"):
        for p in (REPO / pkg).rglob("*.py"):
            txt = p.read_text(encoding="utf-8", errors="ignore")
            assert "post_delivery_markout" not in txt and "delivery_trace" not in txt, p


# ============================================================================================ acquisition transport
def http_seq(*answers):
    seq = list(answers)
    calls = []

    def http(url, params, headers, timeout):
        calls.append((url, dict(params)))
        return seq.pop(0) if seq else (500, b"exhausted fixture")
    http.calls = calls
    return http


def acq(http, **kw):
    return Q.AlpacaAcquirer(headers={"h": "x"}, http=http, clock=lambda: t(21, 30), sleep=lambda s: None, **kw)


def test_bar_request_is_exact_and_raw_and_empty_success_is_confirmed_absence():
    h = http_seq((200, json.dumps({"bars": {}, "next_page_token": None}).encode()))
    r = acq(h).bar("AAA", t(14, 15))
    assert r["outcome"] == Q.RETRIEVED and r["payload"] == []
    p = h.calls[0][1]
    assert (p["start"], p["end"], p["adjustment"], p["feed"]) == ("2026-10-12T14:15:00Z", "2026-10-12T14:15:59Z",
                                                                   "raw", "sip")


def test_transient_errors_retry_boundedly_and_never_become_empty_success():
    h = http_seq((503, b""), (None, "URLError"), (429, b""))
    r = acq(h).bar("AAA", t(14, 15))
    assert r["outcome"] == Q.RATE and len(h.calls) == 3
    ok = http_seq((None, "timeout"), (200, json.dumps({"bars": {"AAA": [bar(t(14, 15))]}}).encode()))
    assert acq(ok).bar("AAA", t(14, 15))["outcome"] == Q.RETRIEVED


@pytest.mark.parametrize("ans,outcome", [((403, b"forbidden"), Q.ENTITLE),
                                         ((422, b"subscription does not permit querying recent SIP data"), Q.ENTITLE),
                                         ((400, b"bad"), Q.REJECTED), ((200, b"not json"), Q.MALFORMED),
                                         ((200, json.dumps({"x": 1}).encode()), Q.MALFORMED)])
def test_entitlement_rejection_and_malformed_responses_are_distinct(ans, outcome):
    assert acq(http_seq(ans)).bar("AAA", t(14, 15))["outcome"] == outcome


def test_quote_pagination_is_bounded_and_resolves_equal_timestamps():
    tgt = t(14, 15)
    page = lambda rows, tok: (200, json.dumps({"quotes": {"AAA": rows}, "next_page_token": tok}).encode())  # noqa
    same = [quote(tgt, 99.9, 100.1), quote(tgt, 99.95, 100.05)]
    older = [quote(tgt - timedelta(seconds=2), 99.8, 100.2)]
    r = acq(http_seq(page(same, "p2"), page(older, None))).quote("AAA", tgt)
    assert r["outcome"] == Q.RETRIEVED and len(r["payload"]) == 3
    assert M.select_quote(r["payload"], tgt)[0]["bid"] == 99.9
    crossed_forever = [page([quote(tgt, 101, 100)], f"p{i}") for i in range(10)]
    assert acq(http_seq(*crossed_forever), max_pages=3).quote("AAA", tgt)["outcome"] == Q.PAGES


def test_r5_and_time_budget_are_enforced_before_any_request():
    h = http_seq()
    r = Q.AlpacaAcquirer(headers={}, http=h, clock=lambda: t(15, 0)).bar("AAA", t(14, 15))   # 11:00 ET weekday
    assert r["outcome"] == Q.R5 and h.calls == []
    clock = iter([0.0, 999.0, 999.0, 999.0])
    b = Q.AlpacaAcquirer(headers={}, http=http_seq(), clock=lambda: t(21, 30), monotonic=lambda: next(clock),
                         budget_s=10)
    assert b.bar("AAA", t(14, 15))["outcome"] == Q.BUDGET


# ============================================================================================ delivery trace
def test_traced_transport_records_ids_server_time_and_hidden_retries_without_changing_the_send(tmp_path):
    log = logging.getLogger(T.CLIENT_LOGGER)

    class Client:
        is_configured = True

        async def send(self, text, parse_mode=None, **kw):
            log.warning("Telegram network error (%s); retrying in %.1fs (attempt %d/%d)", "timeout", 0.1, 1, 3)
            return SimpleNamespace(message_id=42, date=t(14, 10, 1), chat=SimpleNamespace(id=-100123))
    store = T.TraceStore(tmp_path / "trace.db")
    clock = iter([t(14, 10, 0), t(14, 10, 1, )])
    tr = T.TracedTransport(Client(), store, clock=lambda: next(clock))
    msg = asyncio.run(tr.send("hello", parse_mode=None))
    assert msg.message_id == 42 and tr.is_configured
    row = store.con.execute("SELECT * FROM traces").fetchone()
    assert row[4] == "API_ACCEPTED" and row[6] == 42 and row[9] == 1            # network retry counted
    assert "-100123" not in json.dumps(row) and row[8] == hashlib.sha256(b"-100123").hexdigest()[:12]
    ob = sqlite3.connect(tmp_path / "ob.db")
    ob.execute("CREATE TABLE ops_notification_outbox (event_id TEXT, payload_text TEXT)")
    ob.execute("INSERT INTO ops_notification_outbox VALUES ('E1', 'hello')")
    ob.commit()
    look = T.make_trace_lookup(tmp_path / "ob.db", tmp_path / "trace.db")("E1")
    assert look["hidden_retries"] == 1 and look["message_id_present"]
    row_sent = {"state": "SENT", "attempts": 1, "last_error": None, "sent_at_utc": t(14, 10, 2).isoformat()}
    assert M.classify_delivery(row_sent, look, "REQUIRED")[0] == M.AMBIGUOUS     # success after a timeout


def test_traced_transport_records_failures_and_reraises(tmp_path):
    class Boom:
        is_configured = True

        async def send(self, text, parse_mode=None, **kw):
            raise RuntimeError("down")
    store = T.TraceStore(tmp_path / "trace.db")
    with pytest.raises(RuntimeError):
        asyncio.run(T.TracedTransport(Boom(), store).send("x"))
    assert store.con.execute("SELECT outcome, error_class FROM traces").fetchone() == ("SEND_FAILED", "RuntimeError")


def test_traced_transport_works_through_the_unchanged_worker_drain(tmp_path, monkeypatch):
    from talonx_ops.notify.outbox import NotifyStore
    from talonx_ops.notify.worker import drain
    monkeypatch.setenv("TALONX_NOTIFY_RESEARCH_ENABLED", "1")
    monkeypatch.setenv("TALONX_NOTIFY_RESEARCH_BOT_TOKEN", "tok")
    monkeypatch.setenv("TALONX_NOTIFY_RESEARCH_CHAT_ID", "1")

    class Client:
        is_configured = True

        async def send(self, text, parse_mode=None, **kw):
            return SimpleNamespace(message_id=7, date=datetime.now(UTC), chat=SimpleNamespace(id=1))
    store = NotifyStore(str(tmp_path / "o.db"))
    store.enqueue(event_id="E", destination="RESEARCH", event_type="X", producer="p", dedup_key="E",
                  payload_text="body", provenance={})
    out = drain(store, destination="RESEARCH", client=T.TracedTransport(Client(), T.TraceStore(tmp_path / "t.db")))
    assert out["sent"] == 1 and store.counts_by_state() == {"SENT": 1}
