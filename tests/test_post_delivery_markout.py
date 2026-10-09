"""POST_DELIVERY_ALERT_MARKOUT_V1 (inactive): synthetic fixtures only -- no provider, no live store, no Telegram."""
from __future__ import annotations

import hashlib
import sqlite3
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from talonx_paperperf import post_delivery_markout as M

UTC = timezone.utc
REPO = Path(__file__).resolve().parents[1]
A = datetime(2026, 10, 12, 0, 0, tzinfo=UTC)                     # activation boundary (Monday window start)


def t(h, m, s=0, d=12, mo=10):
    return datetime(2026, mo, d, h, m, s, tzinfo=UTC)


def bars(start, prices, vol=100):
    """prices: list of (o, c) per minute starting at ``start`` (bar t = interval start)."""
    return [{"t": (start + timedelta(minutes=i)).isoformat().replace("+00:00", "Z"), "o": o, "h": max(o, c),
             "l": min(o, c), "c": c, "v": vol} for i, (o, c) in enumerate(prices)]


def quotes(at, spread_bps, n=3, mid=100.0):
    half = mid * spread_bps / 2e4
    return [{"t": (at + timedelta(seconds=10 * i)).isoformat(), "bp": mid - half, "ap": mid + half} for i in range(n)]


# --------------------------------------------------------------------------------------------- timing (pure)
def test_delivery_mid_bar_enters_at_the_next_full_minute_after_the_reaction_delay():
    s = M.schedule(t(14, 10, 30))
    assert s["state"] == M.WAITING and s["entry_utc"] == t(14, 16) and s["exit_utc"] == t(14, 46)


def test_delivery_exactly_on_a_bar_boundary_does_not_round_up():
    s = M.schedule(t(14, 10, 0))
    assert s["entry_utc"] == t(14, 15) and s["exit_utc"] == t(14, 45)


def test_reaction_delay_or_exit_crossing_the_close_is_ineligible_never_extended():
    assert M.schedule(t(19, 56))["state"] == M.LATE                      # D + 5 min > 20:00 close
    assert M.schedule(t(19, 26))["state"] == M.LATE                      # T_x 20:01 > close
    ok = M.schedule(t(19, 20))
    assert ok["state"] == M.WAITING and ok["exit_utc"] == t(19, 55)
    assert M.schedule(t(13, 0))["state"] == M.OUT_SESSION                # premarket delivery


def test_half_day_close_is_respected():
    half = datetime(2026, 11, 27, 17, 30, tzinfo=UTC)                    # day after Thanksgiving: 18:00Z close
    assert M.schedule(half)["state"] == M.LATE
    ok = M.schedule(datetime(2026, 11, 27, 17, 20, tzinfo=UTC))
    assert ok["state"] == M.WAITING and ok["exit_utc"] == datetime(2026, 11, 27, 17, 55, tzinfo=UTC)


def test_pre_delivery_price_is_never_the_entry_and_market_time_not_arrival_order_decides():
    te, tx = t(14, 16), t(14, 46)
    pre = bars(t(14, 14), [(90, 90), (95, 95)])                          # 14:14, 14:15: before T_e
    post = bars(te, [(100, 101)] + [(101, 101)] * 29 + [(110, 110)])
    late_arrival = list(reversed(post)) + pre                            # arrival order is irrelevant
    m = M.measure(te, tx, late_arrival, quotes(te, 10))
    assert m["entry_bar_utc"].startswith("2026-10-12T14:16") and m["entry_px"] == 100.0
    assert m["exit_bar_utc"].startswith("2026-10-12T14:45") and m["exit_px"] == 101.0   # T_x bar (14:46) excluded
    assert m["gross_bps"] == pytest.approx(100.0)


def test_zero_volume_and_missing_entry_or_exit_are_states_not_zero_returns():
    te, tx = t(14, 16), t(14, 46)
    zero_first = bars(te, [(100, 100)], vol=0) + bars(te + timedelta(minutes=1), [(102, 102)] * 30)
    assert M.measure(te, tx, zero_first, None)["entry_px"] == 102.0      # first TRADED bar inside the 5-min window
    none_in_window = bars(te + timedelta(minutes=5), [(100, 100)] * 25)
    assert M.measure(te, tx, none_in_window, None)["state"] == M.MISSING_ENTRY
    no_exit = bars(te, [(100, 100)] * 10)                                # nothing in [14:41, 14:45]
    m = M.measure(te, tx, no_exit, None)
    assert m["state"] == M.MISSING_EXIT and "gross_bps" not in m


def test_cost_is_spread_plus_allowance_subtracted_exactly_once():
    te, tx = t(14, 16), t(14, 46)
    b = bars(te, [(100, 100)] + [(100, 100)] * 28 + [(101, 101)])
    m = M.measure(te, tx, b, quotes(te, 10))
    assert (m["gross_bps"], m["spread_bps"], m["cost_bps"]) == (pytest.approx(100.0), pytest.approx(10.0),
                                                                pytest.approx(15.0))
    assert m["net_bps"] == pytest.approx(85.0)
    nq = M.measure(te, tx, b, quotes(te - timedelta(minutes=2), 10))     # quotes outside the window: unusable
    assert nq["net_bps"] is None and nq["cost_state"] == M.COST_UNAVAILABLE and nq["gross_bps"] == pytest.approx(100.0)


# --------------------------------------------------------------------------------------------- fixtures: sources
def sources(tmp_path, rows):
    """rows: dict(event_id, symbol, sent, created=None, attempts=1, last_error=None, state='SENT', etype, pol)."""
    ob = sqlite3.connect(tmp_path / "outbox.db")
    ob.execute("CREATE TABLE ops_notification_outbox (event_id TEXT PRIMARY KEY, destination TEXT, event_type TEXT, "
               "producer TEXT, state TEXT, attempts INT, last_error TEXT, created_at_utc TEXT, sent_at_utc TEXT)")
    pc = sqlite3.connect(tmp_path / "promotion.db")
    pc.execute("CREATE TABLE promotions (promotion_id TEXT, symbol TEXT, window_id TEXT, state TEXT, reason_code TEXT, "
               "policy_fp TEXT, data_as_of_utc TEXT, decision_utc TEXT, signal_event_id TEXT)")
    for r in rows:
        sent = r["sent"]
        ob.execute("INSERT INTO ops_notification_outbox VALUES (?,?,?,?,?,?,?,?,?)",
                   (r["event_id"], "TRADE_EVENT", r.get("etype", M.EVENT_TYPE), "talonx_opportunity.promotion",
                    r.get("state", "SENT"), r.get("attempts", 1), r.get("last_error"),
                    (r.get("created") or sent - timedelta(seconds=1)).isoformat(), sent.isoformat()))
        pc.execute("INSERT INTO promotions VALUES (?,?,?,?,?,?,?,?,?)",
                   (r["event_id"], r["symbol"], sent.date().isoformat(), "PROMOTED_SIGNAL", M.REVIEW_REASON,
                    r.get("pol", "POLFP"), (sent - timedelta(minutes=19)).isoformat(), sent.isoformat(), r["event_id"]))
    ob.commit()
    pc.commit()
    return tmp_path / "outbox.db", tmp_path / "promotion.db"


def md5(p):
    return hashlib.md5(Path(p).read_bytes()).hexdigest()


def reg(tmp_path, rows, store=None):
    ob, pc = sources(tmp_path, rows) if rows is not None else (tmp_path / "outbox.db", tmp_path / "promotion.db")
    store = store or M.Store(tmp_path / "pdm")
    return store, M.register(store, activation_utc=A, outbox_path=ob, promotion_path=pc, now=t(21, 0)), ob, pc


# --------------------------------------------------------------------------------------------- registration
def test_only_prospective_review_alerts_after_activation_are_observations(tmp_path):
    store, r, ob, pc = reg(tmp_path, [
        dict(event_id="OLD", symbol="AAA", sent=A - timedelta(hours=60)),                     # before activation
        dict(event_id="LEGACY", symbol="BBB", sent=t(14, 0), etype="PAPER_OPPORTUNITY"),      # legacy type
        dict(event_id="NEW", symbol="CCC", sent=t(14, 0)),
        dict(event_id="EDGE", symbol="DDD", sent=t(14, 1), created=A - timedelta(seconds=1)),  # enqueued before A
    ])
    assert [o["event_id"] for o in store.rows()] == ["NEW"]
    o = store.rows()[0]
    assert o["delivered_utc"] == t(14, 0).isoformat() and o["entry_utc"] == t(14, 5).isoformat()
    assert o["segment"].startswith("POST_DELIVERY_ALERT_MARKOUT_V1|") and o["source_sha256"]


def test_ambiguous_acknowledgement_is_excluded_and_counted(tmp_path):
    store, *_ = reg(tmp_path, [dict(event_id="R2", symbol="AAA", sent=t(14, 0), attempts=2),
                               dict(event_id="ERR", symbol="BBB", sent=t(14, 0), last_error="telegram: timed out")])
    assert {o["event_id"]: o["state"] for o in store.rows()} == {"R2": M.AMBIGUOUS, "ERR": M.AMBIGUOUS}


def test_repeat_alerts_same_symbol_same_window_keep_the_first(tmp_path):
    store, *_ = reg(tmp_path, [dict(event_id="A1", symbol="AAA", sent=t(14, 0)),
                               dict(event_id="A2", symbol="AAA", sent=t(15, 0)),
                               dict(event_id="A3", symbol="AAA", sent=t(14, 0, d=13))])
    st = {o["event_id"]: o["state"] for o in store.rows()}
    assert st == {"A1": M.WAITING, "A2": M.REPEAT, "A3": M.WAITING}


def test_duplicate_processing_and_restart_are_idempotent(tmp_path):
    rows = [dict(event_id="X", symbol="AAA", sent=t(14, 0))]
    store, r1, ob, pc = reg(tmp_path, rows)
    assert r1["registered"] == 1
    store2 = M.Store(tmp_path / "pdm")                                   # restart: a new process / connection
    assert M.register(store2, activation_utc=A, outbox_path=ob, promotion_path=pc, now=t(21, 1))["registered"] == 0
    calls = []

    def fetch(sym, a, b):
        calls.append(sym)
        return bars(a, [(100, 100)] * 30), quotes(a, 8), "fixture"
    M.process(store2, fetch=fetch, now=t(21, 5))
    M.process(M.Store(tmp_path / "pdm"), fetch=fetch, now=t(21, 6))      # restart again: nothing re-measured
    assert calls == ["AAA"]
    assert store2.con.execute("SELECT COUNT(*) FROM results").fetchone()[0] == 1
    assert store2.rows()[0]["state"] == M.MATURE


def test_policy_change_starts_a_separate_segment_never_pooled(tmp_path):
    store, *_ = reg(tmp_path, [dict(event_id="P1", symbol="AAA", sent=t(14, 0), pol="FP_A"),
                               dict(event_id="P2", symbol="BBB", sent=t(14, 0), pol="FP_B")])
    M.process(store, fetch=lambda s, a, b: (bars(a, [(100, 100)] * 30), quotes(a, 8), "fx"), now=t(21, 5))
    rep = M.report(store)
    assert len(rep) == 2 and all(v["measured"] == 1 for v in rep.values())
    assert all("not portfolio performance" in v["note"] for v in rep.values())


# --------------------------------------------------------------------------------------------- data waiting
def test_waits_until_maturity_then_bounded_timeout(tmp_path):
    store, *_ = reg(tmp_path, [dict(event_id="W", symbol="AAA", sent=t(14, 0))])
    assert M.process(store, fetch=lambda *a: None, now=t(20, 30))["waiting"] == 1        # before close + 60 min
    assert M.process(store, fetch=lambda *a: None, now=t(21, 30))["waiting"] == 1        # matured, no data yet
    out = M.process(store, fetch=lambda *a: None, now=t(21, 0, d=14) + timedelta(hours=1))   # after 2 sessions
    assert out["timeout"] == 1 and store.rows()[0]["state"] == M.MISSING_TIMEOUT


def test_without_an_acquisition_function_nothing_times_out(tmp_path):
    store, *_ = reg(tmp_path, [dict(event_id="W", symbol="AAA", sent=t(14, 0))])
    out = M.process(store, fetch=None, now=t(21, 0, d=20))
    assert out["acquisition_not_configured"] == 1 and store.rows()[0]["state"] == M.WAITING


def test_measured_missing_stays_in_the_denominator(tmp_path):
    store, *_ = reg(tmp_path, [dict(event_id="OK", symbol="AAA", sent=t(14, 0)),
                               dict(event_id="NO", symbol="BBB", sent=t(14, 0))])
    M.process(store, fetch=lambda s, a, b: (bars(a, [(100, 100)] * 30) if s == "AAA" else [], quotes(a, 8), "fx"),
              now=t(21, 5))
    v = list(M.report(store).values())[0]
    assert v["eligible"] == 2 and v["measured"] == 1 and v["coverage"] == 0.5
    assert v["states"][M.MISSING_ENTRY] == 1


# --------------------------------------------------------------------------------------------- inactive / isolation
def test_disabled_by_default_and_activation_boundary_required(tmp_path):
    root = tmp_path / "never"
    assert M.run({}, store_root=root) == {"state": "DISABLED"}
    assert M.run({M.ENABLE_ENV: "1"}, store_root=root) == {"state": "NO_VALID_ACTIVATION_BOUNDARY"}
    assert M.run({M.ENABLE_ENV: "1", M.ACTIVATION_ENV: "2026-10-12T00:00:00"}, store_root=root)["state"] == \
        "NO_VALID_ACTIVATION_BOUNDARY"                                   # naive timestamp refused
    assert not root.exists()                                             # nothing created while inactive
    with pytest.raises(ValueError):
        M.register(M.Store(tmp_path / "s"), activation_utc=None, outbox_path=tmp_path / "x", promotion_path=tmp_path / "y")


def test_source_stores_are_never_written(tmp_path):
    rows = [dict(event_id="S", symbol="AAA", sent=t(14, 0))]
    ob, pc = sources(tmp_path, rows)
    before = (md5(ob), md5(pc))
    store = M.Store(tmp_path / "pdm")
    M.register(store, activation_utc=A, outbox_path=ob, promotion_path=pc, now=t(21, 0))
    M.process(store, fetch=lambda s, a, b: (bars(a, [(100, 100)] * 30), quotes(a, 8), "fx"), now=t(21, 5))
    assert (md5(ob), md5(pc)) == before


def test_module_is_not_registered_or_imported_by_any_runtime():
    from talonx_opportunity import runtime, supervise
    assert not any("post_delivery" in c for c in supervise.COMPONENTS)
    assert "post_delivery" not in str(runtime.COMPONENT_SOURCES)
    for pkg in ("talonx_opportunity", "talonx_ops", "talonx_v2", "talonx_dispatch", "talonx_ingest", "scripts"):
        for p in (REPO / pkg).rglob("*.py"):
            assert "post_delivery_markout" not in p.read_text(encoding="utf-8", errors="ignore"), p
