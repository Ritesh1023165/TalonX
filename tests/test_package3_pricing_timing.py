"""
Package 3 -- Authoritative Pricing, Refresh, Evidence Timestamps & Deadlines.

Targeted tests only (per the task's own instruction), covering:
  P3-B: missing/stale price semantics (never fabricate zero/NaN)
  P3-D: the exact Session-3 recovery deadline (official close, not an
        approximation), including weekend/holiday/early-close/live
        close-time-boundary cases
  P3-E: durable evidence receipt vs. processing time
  P3-A/P3-F: authoritative price propagated consistently into sizing/
        reservation/fill/cost-basis
  Concurrency: independent-connection proofs where a claim depends on
        real database serialization, not a single-connection unit test.

Uses real temporary SQLite files and, for concurrency claims, genuinely
independent V2Store/V2Service connections -- never a single-connection
stand-in for a concurrency proof.
"""
from __future__ import annotations

import threading
from datetime import date, datetime, timezone

import pytest

from talonx_v2 import calendar as v2cal
from talonx_v2 import paper, pipeline, service as service_module
from talonx_v2.cluster_engine import ClusterEpisode
from talonx_v2.config import V2Config
from talonx_v2.schemas import V2Action, V2Decision, V2Direction
from talonx_v2.service import V2Service
from talonx_v2.store import V2Store

ACT = date(2026, 8, 14)
BALANCE = 300_000.0
ALLOC = 10_000.0


def _bars_dir(tmp, symbol, rows):
    import csv
    bd = tmp / "bars"
    bd.mkdir(exist_ok=True)
    with open(bd / f"{symbol}.csv", "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["date", "open", "close", "volume"])
        for r in rows:
            w.writerow(r)
    return bd


def _full_calendar_rows(symbol, *, open_=40.0, close=40.5, volume=1_500_000,
                        start=date(2019, 1, 1), end=date(2027, 12, 31), omit=()):
    from talonx_v2 import calendar as vc
    omit = set(omit)
    return [[s.isoformat(), open_, close, volume] for s in vc._sessions()
            if start <= s <= end and s not in omit]


def _svc(tmp, db_path, *, name, symbols, rows_by_symbol=None, starting_cash=BALANCE,
        alloc=ALLOC, form4_kind="parquet"):
    rows_by_symbol = rows_by_symbol or {s: _full_calendar_rows(s) for s in symbols}
    bd = tmp / f"bars_{name}"
    bd.mkdir(exist_ok=True)
    import csv
    for sym, rows in rows_by_symbol.items():
        with open(bd / f"{sym}.csv", "w", newline="") as f:
            w = csv.writer(f)
            w.writerow(["date", "open", "close", "volume"])
            for r in rows:
                w.writerow(r)
    cfg = V2Config(db_path=str(db_path), starting_cash_usd=starting_cash,
                   per_position_allocation_usd=alloc)
    return V2Service(config=cfg, bar_dirs=[bd], form4_kind=form4_kind,
                     status_path=str(tmp / f"{name}.json"))


def _ep(entry_session, episode_id, symbol, activation_filing_date=ACT):
    return ClusterEpisode(episode_id=episode_id, symbol=symbol, issuer_cik="x",
                          distinct_owner_ciks=("a", "b"), n_distinct_owners=2, n_filings=2,
                          first_filing_date=ACT, activation_filing_date=activation_filing_date,
                          last_filing_date=ACT,
                          aggregate_purchase_value=0.0, any_officer=False, any_director=False,
                          any_ten_percent=False,
                          causal_event_ts=datetime(2026, 8, 14, 23, 59, 59, tzinfo=timezone.utc),
                          eligible_entry_session=entry_session)


def _fixed_buy_decision(e):
    liq = type("Liq", (), {"ok": True, "median_dollar_volume": 1e7, "last_close": 10.0})()
    dec = V2Decision(signal_id="s1", episode_id=e.episode_id, symbol=e.symbol,
                     direction=V2Direction.BULLISH, action=V2Action.BUY,
                     official_eligible=False, rationale="test (package3 fixture)",
                     eligible_entry_session=e.eligible_entry_session)
    return liq, dec


def _wire(svc, symbol, *, dissemination_ts=None, receipt_ts=None, filing_date=ACT):
    early = dissemination_ts or datetime(2026, 8, 14, 15, 20, tzinfo=timezone.utc)
    svc._dissemination_lookup = {(symbol, filing_date.isoformat()): early}
    if receipt_ts is not None:
        svc._receipt_lookup = {(symbol, filing_date.isoformat()): receipt_ts}
    svc._eval_causal_decision = _fixed_buy_decision


def _run_admission(svc, ep, *, ripe_through=None):
    rt = ripe_through or ep.eligible_entry_session
    svc._phase_post_close([ep], [ep], today=rt, ripe_through=rt,
                          is_stale=lambda e: False, live=True)


def _run_open(svc, ep, ripe_through, *, live=True):
    res = pipeline.ProcessResult()
    svc._phase_open([ep], ripe_through, res, price_lookup=svc._price,
                    today=ripe_through, live=live)
    return res


def _decision(episode_id="ep1", symbol="AAA"):
    return V2Decision(signal_id=f"sig-{episode_id}", episode_id=episode_id, symbol=symbol,
                      direction=V2Direction.BULLISH, action=V2Action.BUY,
                      official_eligible=False, rationale="test",
                      eligible_entry_session=date(2026, 9, 8))


class _FrozenDatetime(datetime):
    _frozen: datetime | None = None

    @classmethod
    def now(cls, tz=None):
        f = cls._frozen
        return f.astimezone(tz) if tz is not None else f


# ======================================================================= #
# P3-B -- missing / stale price semantics
# ======================================================================= #

def test_p3b_missing_open_value_never_becomes_a_usable_price(tmp_path):
    """A CSV row with a blank/non-numeric open must be treated as
    MISSING (excluded entirely), never silently parsed into NaN (which
    is truthy in Python and would previously pass every existing
    "missing price" check downstream, corrupting sizing/cost basis)."""
    svc = _svc(tmp_path, tmp_path / "v2.db", name="p3b1", symbols=[])
    bd = tmp_path / "bars_p3b1"
    import csv
    with open(bd / "BADP.csv", "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["date", "open", "close", "volume"])
        w.writerow(["2026-09-08", "", "40.5", "1500000"])   # blank open
        w.writerow(["2026-09-09", "40.0", "40.5", "1500000"])  # valid

    rows = svc._bars("BADP")
    dates = {r["date"] for r in rows}
    assert "2026-09-08" not in dates, "a blank-open row was not excluded"
    assert "2026-09-09" in dates, "a valid row was incorrectly dropped too"
    px = svc._price("BADP", date(2026, 9, 8))
    assert px is None, "a missing price must resolve to None, never a fabricated value"


def test_p3b_valid_price_is_used_normally(tmp_path):
    svc = _svc(tmp_path, tmp_path / "v2.db", name="p3b2", symbols=["GOOD"])
    px = svc._price("GOOD", date(2026, 9, 8))
    assert px is not None
    assert px["open"] == 40.0 and px["close"] == 40.5


def test_p3b_one_malformed_row_does_not_drop_the_whole_symbol(tmp_path):
    svc = _svc(tmp_path, tmp_path / "v2.db", name="p3b3", symbols=[])
    bd = tmp_path / "bars_p3b3"
    import csv
    with open(bd / "MIXD.csv", "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["date", "open", "close", "volume"])
        w.writerow(["2026-09-08", "40.0", "40.5", "1500000"])
        w.writerow(["2026-09-09", "not_a_number", "40.5", "1500000"])
        w.writerow(["2026-09-10", "0", "40.5", "1500000"])   # zero price -- also rejected
        w.writerow(["2026-09-11", "-5.0", "40.5", "1500000"])  # negative -- also rejected
        w.writerow(["2026-09-14", "41.0", "41.5", "1500000"])

    rows = svc._bars("MIXD")
    dates_ok = {r["date"] for r in rows}
    assert dates_ok == {"2026-09-08", "2026-09-14"}


def _liquid_prior_bars(entry_session, *, close=40.5, volume=1_500_000):
    """20+ sessions strictly before ``entry_session`` at a dollar volume
    comfortably clearing the frozen $5M/$5 liquidity gate, so a test can
    reach the price-lookup step rather than failing liquidity first."""
    sess = [s for s in v2cal._sessions() if s < entry_session][-30:]
    return [{"date": s.isoformat(), "close": close, "volume": volume} for s in sess]


def test_p3b_missing_price_does_not_fabricate_a_zero_cost_reservation(tmp_path):
    """End-to-end: an episode whose entry-session bar is missing must
    be skipped, not sized/entered with a zero or NaN cost basis."""
    store = V2Store(str(tmp_path / "v2.db"), starting_cash=BALANCE)
    cfg = V2Config(starting_cash_usd=BALANCE, per_position_allocation_usd=ALLOC)
    res = pipeline.ProcessResult()
    entry_session = date(2026, 9, 8)
    ep = _ep(entry_session, "ep-missing", "MISS")
    bars = _liquid_prior_bars(entry_session)
    pipeline.process_episode(ep, store=store, bars_lookup=lambda s: bars,
                             price_lookup=lambda s, sess: None, config=cfg, result=res)
    assert res.entries == []
    assert any(s.get("reason") == "NO_ENTRY_BAR" for s in res.skipped)
    assert store.cash() == BALANCE
    assert store.all_positions() == []


# ======================================================================= #
# P3-D -- Session-3 recovery deadline (official close, real calendar)
# ======================================================================= #

def test_p3d_session3_is_computed_via_the_real_calendar_ordinary_week(tmp_path):
    """Ordinary Mon/Tue/Wed sequence: target entry = Session 1 (a
    Monday); Session 3 lands on the Wednesday."""
    monday = date(2027, 6, 7)   # a Monday (frozen fixture date)
    assert monday.weekday() == 0
    svc = _svc(tmp_path, tmp_path / "v2.db", name="p3d1", symbols=["AAA"])
    deadline = svc._recovery_deadline_session(monday)
    assert deadline == date(2027, 6, 9)  # Wednesday
    assert deadline.weekday() == 2


def test_p3d_weekend_is_skipped_by_the_real_calendar(tmp_path):
    """Target entry on a Thursday: Session 1=Thu, 2=Fri, 3=Mon (the
    weekend is skipped entirely -- never approximated as +2 calendar
    days, which would incorrectly land on a Saturday)."""
    thursday = date(2026, 9, 10)
    assert thursday.weekday() == 3
    svc = _svc(tmp_path, tmp_path / "v2.db", name="p3d2", symbols=["AAA"])
    deadline = svc._recovery_deadline_session(thursday)
    assert deadline.weekday() not in (5, 6)
    assert deadline == date(2026, 9, 14)  # the following Monday


def test_p3d_market_holiday_is_skipped_by_the_real_calendar(tmp_path):
    """Target entry the session before Labor Day: the holiday itself
    (2026-09-07, a Monday) must never be counted as a recovery
    session -- the deadline must land on a genuine trading day."""
    friday = date(2026, 9, 4)
    assert not v2cal.is_session(date(2026, 9, 7)), "fixture assumption: Labor Day is a holiday"
    svc = _svc(tmp_path, tmp_path / "v2.db", name="p3d3", symbols=["AAA"])
    deadline = svc._recovery_deadline_session(friday)
    assert deadline != date(2026, 9, 7)
    assert v2cal.is_session(deadline)


def test_p3d_early_close_session_uses_the_actual_early_close_timestamp(tmp_path):
    """The day after Thanksgiving is a real XNYS early-close session
    (13:00 ET / 18:00 UTC, not the ordinary 16:00 ET / 21:00 UTC) --
    the deadline must use the REAL close, never a fixed hour offset."""
    svc = _svc(tmp_path, tmp_path / "v2.db", name="p3d4", symbols=["AAA"])
    close = v2cal.session_close_utc(date(2024, 11, 29))
    assert close == datetime(2024, 11, 29, 18, 0, tzinfo=timezone.utc)
    ordinary_close = v2cal.session_close_utc(date(2024, 11, 27))
    assert ordinary_close == datetime(2024, 11, 27, 21, 0, tzinfo=timezone.utc)


def test_p3d_live_tick_immediately_before_session3_close_still_qualifies(tmp_path, monkeypatch):
    """S6-24's agreed equality semantics: evidence/fill attempted AT OR
    BEFORE the official close still qualifies."""
    svc = _svc(tmp_path, tmp_path / "v2.db", name="p3d5", symbols=["AAA"])
    monday = date(2027, 6, 7)
    deadline_session = svc._recovery_deadline_session(monday)
    close = v2cal.session_close_utc(deadline_session)
    monkeypatch.setattr(service_module, "datetime", _FrozenDatetime)
    _FrozenDatetime._frozen = close  # exactly AT the close -- still qualifies (inclusive)
    assert svc._recovery_deadline_passed(monday, ripe_through=deadline_session, live=True) is False
    from datetime import timedelta
    _FrozenDatetime._frozen = close - timedelta(minutes=1)  # one minute before -- still qualifies
    assert svc._recovery_deadline_passed(monday, ripe_through=deadline_session, live=True) is False


def test_p3d_live_tick_immediately_after_session3_close_is_refused(tmp_path, monkeypatch):
    svc = _svc(tmp_path, tmp_path / "v2.db", name="p3d6", symbols=["AAA"])
    monday = date(2027, 6, 7)
    deadline_session = svc._recovery_deadline_session(monday)
    close = v2cal.session_close_utc(deadline_session)
    monkeypatch.setattr(service_module, "datetime", _FrozenDatetime)
    from datetime import timedelta
    _FrozenDatetime._frozen = close + timedelta(minutes=1)
    assert svc._recovery_deadline_passed(monday, ripe_through=deadline_session, live=True) is True


def test_p3d_replay_tick_date_only_boundary_matches_live_session_boundary(tmp_path):
    """Non-live (replay/backtest): no real wall clock exists, so the
    boundary is date-only -- Session 3's own date remains within the
    window; the session strictly after it is not."""
    svc = _svc(tmp_path, tmp_path / "v2.db", name="p3d7", symbols=["AAA"])
    monday = date(2027, 6, 7)
    deadline_session = svc._recovery_deadline_session(monday)
    assert svc._recovery_deadline_passed(monday, ripe_through=deadline_session, live=False) is False
    after = v2cal.next_session_strictly_after(deadline_session)
    assert svc._recovery_deadline_passed(monday, ripe_through=after, live=False) is True


def test_p3d_pending_intent_released_not_left_zombie_after_deadline(tmp_path, monkeypatch):
    """After the deadline: no new fill, the PENDING intent resolves to
    a terminal state (never left indefinitely PENDING), and no cash is
    invented."""
    monkeypatch.setenv("TALONX_V2_DURABLE_STORE_ENABLED", "true")
    db_path = tmp_path / "v2.db"
    svc = _svc(tmp_path, db_path, name="p3d8", symbols=["ZZZZ"])
    monday = date(2027, 6, 7)
    ep = _ep(monday, "p3d8-ep1", "ZZZZ")
    _wire(svc, "ZZZZ")
    svc._phase_post_close([ep], [ep], today=monday, ripe_through=monday,
                          is_stale=lambda e: False, live=True)
    assert svc.store.entry_intent("p3d8-ep1")["status"] == "PENDING"
    cash_before = svc.store.cash()

    deadline_session = svc._recovery_deadline_session(monday)
    after = v2cal.next_session_strictly_after(deadline_session)
    # date-only (replay-style) check here: this proves the deadline
    # itself is correctly enforced independent of real wall-clock time
    # (restart-safe) -- the dedicated live-clock boundary tests above
    # separately prove the real-close-time precision.
    res = _run_open(svc, ep, after, live=False)

    fresh = V2Store(str(db_path))
    intent = fresh.entry_intent("p3d8-ep1")
    assert intent["status"] != "PENDING", "the intent was left a zombie PENDING reservation"
    assert intent["status"] == "EXPIRED_STALE" or intent["status"] == "EXPIRED_RECOVERY_DEADLINE"
    assert fresh.position_for_episode("p3d8-ep1") is None
    assert fresh.cash() == cash_before


# ======================================================================= #
# P3-E -- durable evidence receipt vs. processing time
# ======================================================================= #

def test_p3e_late_receipt_is_refused_even_with_an_earlier_source_timestamp(tmp_path, monkeypatch):
    """source_event_time <= deadline AND receipt_time > deadline must
    NOT be treated as timely merely because the source timestamp was
    earlier."""
    monkeypatch.setenv("TALONX_V2_DURABLE_STORE_ENABLED", "true")
    svc = _svc(tmp_path, tmp_path / "v2.db", name="p3e1", symbols=["LATE"])
    monday = date(2027, 6, 7)
    ep = _ep(monday, "p3e1-ep1", "LATE")
    import exchange_calendars as xc
    rth_open = xc.get_calendar("XNYS").session_open(monday.isoformat()).to_pydatetime().astimezone(timezone.utc)
    from datetime import timedelta
    early_source_ts = rth_open - timedelta(hours=1)   # clearly before RTH open (source: timely)
    late_receipt_ts = rth_open + timedelta(hours=2)    # TalonX's own durable receipt: AFTER RTH open

    _wire(svc, "LATE", dissemination_ts=early_source_ts, receipt_ts=late_receipt_ts)
    ok, detail = svc._verify_temporal_boundary(ep, None, live=True)
    assert ok is False
    assert "receipt" in detail.lower() or "ingested" in detail.lower()


def test_p3e_timely_receipt_and_timely_processing_admits_normally(tmp_path):
    svc = _svc(tmp_path, tmp_path / "v2.db", name="p3e2", symbols=["OK1"])
    monday = date(2027, 6, 7)
    ep = _ep(monday, "p3e2-ep1", "OK1")
    import exchange_calendars as xc
    from datetime import timedelta
    rth_open = xc.get_calendar("XNYS").session_open(monday.isoformat()).to_pydatetime().astimezone(timezone.utc)
    ts = rth_open - timedelta(hours=1)
    _wire(svc, "OK1", dissemination_ts=ts, receipt_ts=ts)
    ok, detail = svc._verify_temporal_boundary(ep, None, live=True)
    assert ok is True, detail


def test_p3e_timely_receipt_but_delayed_processing_still_admits(tmp_path, monkeypatch):
    """Evidence durably received before the deadline, and admitted on
    time, may still be PROCESSED (the actual fill attempt) later -- a
    later tick, after a delay -- without becoming ineligible purely due
    to the processing delay, as long as it is still within the
    recovery window."""
    monkeypatch.setenv("TALONX_V2_DURABLE_STORE_ENABLED", "true")
    db_path = tmp_path / "v2.db"
    svc = _svc(tmp_path, db_path, name="p3e3", symbols=["DELAY"])
    monday = date(2027, 6, 7)
    ep = _ep(monday, "p3e3-ep1", "DELAY")
    _wire(svc, "DELAY")

    # timely receipt -> timely admission (the reservation is created on schedule).
    svc._phase_post_close([ep], [ep], today=monday, ripe_through=monday,
                          is_stale=lambda e: False, live=True)
    assert svc.store.entry_intent("p3e3-ep1")["status"] == "PENDING"

    # PROCESSING (the actual fill attempt) is delayed to a LATER tick
    # (Session 2, not Session 1) -- still within the recovery window --
    # and must still succeed, never penalized merely for the delay.
    later_session = v2cal.add_sessions(monday, 1)
    res = _run_open(svc, ep, later_session, live=True)
    assert len(res.entries) == 1
    assert svc.store.entry_intent("p3e3-ep1")["status"] == "FILLED"


def test_p3e_restart_preserves_the_pending_intent_before_processing(tmp_path, monkeypatch):
    """Restart after timely receipt but before processing: a fresh
    V2Store/V2Service against the SAME file must still see the durable
    PENDING intent and correctly continue to honor the recovery window."""
    monkeypatch.setenv("TALONX_V2_DURABLE_STORE_ENABLED", "true")
    db_path = tmp_path / "v2.db"
    svc = _svc(tmp_path, db_path, name="p3e4a", symbols=["RST"])
    monday = date(2027, 6, 7)
    ep = _ep(monday, "p3e4-ep1", "RST")
    _wire(svc, "RST")
    svc._phase_post_close([ep], [ep], today=monday, ripe_through=monday,
                          is_stale=lambda e: False, live=True)
    assert svc.store.entry_intent("p3e4-ep1")["status"] == "PENDING"

    # simulate a full process restart: a brand-new V2Service/V2Store instance
    svc2 = _svc(tmp_path, db_path, name="p3e4b", symbols=["RST"])
    assert svc2.store.entry_intent("p3e4-ep1")["status"] == "PENDING"
    deadline = svc2._recovery_deadline_session(monday)
    assert svc2._recovery_deadline_passed(monday, ripe_through=deadline, live=False) is False


def test_p3e_duplicate_processing_does_not_create_duplicate_signal_or_position(tmp_path, monkeypatch):
    """Duplicate receipt/reprocessing of the SAME episode across
    multiple ticks must remain idempotent (one position, one BUY)."""
    monkeypatch.setenv("TALONX_V2_DURABLE_STORE_ENABLED", "true")
    db_path = tmp_path / "v2.db"
    svc = _svc(tmp_path, db_path, name="p3e5", symbols=["DUP1"])
    monday = date(2027, 6, 7)
    ep = _ep(monday, "p3e5-ep1", "DUP1")
    _wire(svc, "DUP1")
    svc._phase_post_close([ep], [ep], today=monday, ripe_through=monday,
                          is_stale=lambda e: False, live=True)

    r1 = _run_open(svc, ep, monday, live=True)
    r2 = _run_open(svc, ep, monday, live=True)  # duplicate/reprocessed same tick logic
    assert len(r1.entries) == 1
    assert len(r2.entries) == 0  # idempotency check (ALREADY_PROCESSED) must refuse the repeat

    fresh = V2Store(str(db_path))
    assert len(fresh.all_positions()) == 1
    assert len([t for t in fresh.trades() if t["action"] == "BUY"]) == 1


# ======================================================================= #
# P3-A / P3-F -- authoritative price propagated consistently
# ======================================================================= #

def test_p3a_same_entry_price_flows_into_sizing_reservation_fill_and_cost_basis(tmp_path):
    """The entry price used for share sizing, the paper fill, and the
    persisted cost basis must be the SAME single value -- never
    silently disagree."""
    store = V2Store(str(tmp_path / "v2.db"), starting_cash=BALANCE)
    cfg = V2Config(starting_cash_usd=BALANCE, per_position_allocation_usd=ALLOC)
    entry_session = date(2026, 9, 8)
    ep = _ep(entry_session, "p3a-ep1", "CONS")
    res = pipeline.ProcessResult()
    ENTRY_PRICE = 37.25
    bars = _liquid_prior_bars(entry_session)
    pipeline.process_episode(
        ep, store=store, bars_lookup=lambda s: bars,
        price_lookup=lambda s, sess: {"open": ENTRY_PRICE, "close": ENTRY_PRICE + 1},
        config=cfg, result=res)
    assert len(res.entries) == 1
    pos = store.all_positions()[0]
    assert pos["entry_price"] == ENTRY_PRICE
    expected_shares = ALLOC / ENTRY_PRICE
    assert pos["shares"] == pytest.approx(expected_shares)
    assert pos["position_cost"] == pytest.approx(ALLOC)
    trade = store.trades()[0]
    assert trade["execution_price"] == ENTRY_PRICE
    assert trade["shares"] == pytest.approx(expected_shares)
    # the res.entries record (what an alert/notification would carry)
    # must also agree -- never a second, divergent price.
    assert res.entries[0]["entry_price"] == ENTRY_PRICE
    assert res.entries[0]["shares"] == pytest.approx(expected_shares)


# ======================================================================= #
# Concurrency -- independent-connection proofs
# ======================================================================= #

def test_concurrency_independent_writers_cannot_double_fill_the_same_intent(tmp_path, monkeypatch):
    """A refresh race must never create multiple positions for the
    same episode -- proven with two genuinely independent V2Store
    connections racing for the SAME episode's fill, not a single-
    connection simulation."""
    monkeypatch.setenv("TALONX_V2_DURABLE_STORE_ENABLED", "true")
    db_path = tmp_path / "v2.db"
    svc_a = _svc(tmp_path, db_path, name="conc-a", symbols=["RACE"])
    svc_b = _svc(tmp_path, db_path, name="conc-b", symbols=["RACE"])
    monday = date(2027, 6, 7)
    ep = _ep(monday, "conc-ep1", "RACE")
    _wire(svc_a, "RACE")
    _wire(svc_b, "RACE")
    svc_a._phase_post_close([ep], [ep], today=monday, ripe_through=monday,
                            is_stale=lambda e: False, live=True)

    a_holds_lock = threading.Event()
    release_a = threading.Event()
    real_enqueue = svc_a.store.enqueue_alert

    def _paused_enqueue(*a, **k):
        a_holds_lock.set()
        assert release_a.wait(timeout=10), "test harness stalled"
        return real_enqueue(*a, **k)
    monkeypatch.setattr(svc_a.store, "enqueue_alert", _paused_enqueue)

    b_result: dict = {}

    def _run_a():
        _run_open(svc_a, ep, monday, live=True)

    def _run_b():
        r = _run_open(svc_b, ep, monday, live=True)
        b_result["entries"] = len(r.entries)

    t_a = threading.Thread(target=_run_a)
    t_a.start()
    assert a_holds_lock.wait(timeout=5), "writer A never reached its held-lock checkpoint"
    t_b = threading.Thread(target=_run_b)
    t_b.start()
    t_b.join(timeout=0.5)
    assert t_b.is_alive(), "writer B did not block on the real SQLite write lock"
    release_a.set()
    t_a.join(timeout=10)
    t_b.join(timeout=10)
    assert not t_a.is_alive() and not t_b.is_alive()

    fresh = V2Store(str(db_path))
    positions = fresh.all_positions()
    assert len(positions) == 1, "a refresh race created more than one position for the same episode"
    assert len([t for t in fresh.trades() if t["action"] == "BUY"]) == 1
