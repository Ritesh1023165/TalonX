"""
Task 131 Remediation Directive 2 -- non-blocking, cross-tick missing-price
retry (``PENDING_RETRY``). Proves, under real failure conditions:

  1. A missing entry price never blocks ``tick()`` (no ``time.sleep`` --
     each tick makes exactly one attempt and returns immediately).
  2. A durable PENDING intent survives repeated ticks within its OWN
     eligible-entry-session's RTH window without being prematurely
     expired as FAILED_NO_MARKET_DATA.
  3. A late-arriving bar update (still within the same session) lets the
     SAME intent reconcile normally -- exactly one fill, never a
     duplicate.
  4. Only once a LATER session's tick observes the price is STILL
     missing is the intent released as FAILED_NO_MARKET_DATA -- exactly
     once, never silently retried forever.
"""
from __future__ import annotations

import time
from datetime import date

from talonx_v2 import calendar as v2cal
from talonx_v2 import form4_source
from talonx_v2.config import V2Config
from talonx_v2.service import V2Service
from talonx_v2.store import V2Store

BALANCE = 300_000.0
ACT = date(2026, 9, 3)          # both filings same day -> activation 09-03
ELIGIBLE = date(2026, 9, 4)     # next session strictly after 09-03
NEXT_SESSION = date(2026, 9, 8) # next session strictly after 09-04 (weekend gap)


def _cfg(tmp_path):
    return V2Config(per_position_allocation_usd=10_000.0, starting_cash_usd=BALANCE,
                    db_path=str(tmp_path / "v2.db"))


def _bars(*, omit: date | None = None, a="2026-06-01", b="2026-10-15", close=100.0, vol=500_000):
    sess = [s for s in v2cal._sessions() if date.fromisoformat(a) <= s <= date.fromisoformat(b)]
    return [{"date": s.isoformat(), "open": close, "close": close, "volume": vol}
            for s in sess if s != omit]


def _rows(sym="GAPX"):
    return [
        dict(symbol=sym, issuer_cik=sym + "c", owner_cik=sym + "1", filing_date=ACT.isoformat(),
             accession=sym + "a1", transaction_value=500_000, is_officer=True, transaction_code="P"),
        dict(symbol=sym, issuer_cik=sym + "c", owner_cik=sym + "2", filing_date=ACT.isoformat(),
             accession=sym + "a2", transaction_value=700_000, is_director=True, transaction_code="P"),
    ]


def _svc(tmp_path, bars):
    svc = V2Service(config=_cfg(tmp_path), bar_dirs=[tmp_path], form4_kind="parquet",
                    status_path=str(tmp_path / "status.json"))
    recs = form4_source.from_rows(_rows())
    svc._records = lambda *, as_of: recs
    svc._bars = lambda sym: bars["rows"]
    svc._price = lambda sym, session: next(
        (b for b in bars["rows"] if b["date"] == (session.isoformat()
                                                   if isinstance(session, date) else str(session)[:10])), None)
    return svc


def test_missing_price_tick_completes_fast_no_blocking_sleep(tmp_path):
    bars = {"rows": _bars(omit=ELIGIBLE)}
    svc = _svc(tmp_path, bars)
    svc.tick(as_of=ACT)  # creates the durable PENDING intent

    t0 = time.monotonic()
    st = svc.tick(as_of=ELIGIBLE)   # price missing for ELIGIBLE
    elapsed = time.monotonic() - t0

    assert elapsed < 2.0, f"tick() blocked for {elapsed:.1f}s -- a sleep loop is still present"
    assert st["entries_this_tick"] == 0
    assert st["pending_retry_count_this_tick"] == 1
    assert st["pending_retry_episodes_this_tick"][0]["symbol"] == "GAPX"


def test_intent_survives_repeated_ticks_within_the_same_session(tmp_path):
    bars = {"rows": _bars(omit=ELIGIBLE)}
    svc = _svc(tmp_path, bars)
    svc.tick(as_of=ACT)

    for _ in range(5):  # simulate several intraday ticks, same RTH session
        st = svc.tick(as_of=ELIGIBLE)
        assert st["entries_this_tick"] == 0
        assert st["pending_retry_count_this_tick"] == 1

    store = V2Store(str(tmp_path / "v2.db"), starting_cash=BALANCE)
    intents = store.all_entry_intents()
    assert len(intents) == 1
    assert intents[0]["status"] == "PENDING"  # never touched, never escalated
    assert store.n_open() == 0
    assert store.cash() == BALANCE


def test_late_arriving_bar_reconciles_within_the_same_session_one_fill(tmp_path):
    bars = {"rows": _bars(omit=ELIGIBLE)}
    svc = _svc(tmp_path, bars)
    svc.tick(as_of=ACT)
    st1 = svc.tick(as_of=ELIGIBLE)
    assert st1["entries_this_tick"] == 0

    # the market-data feed now has ELIGIBLE's bar -- still the SAME session
    bars["rows"] = _bars()
    st2 = svc.tick(as_of=ELIGIBLE)
    assert st2["entries_this_tick"] == 1
    assert st2["pending_retry_count_this_tick"] == 0

    store = V2Store(str(tmp_path / "v2.db"), starting_cash=BALANCE)
    assert store.n_open() == 1
    assert len(store.trades()) == 1  # exactly one fill, no duplicate
    assert store.entry_intent(next(iter(store.pending_entry_intents()), {"episode_id": None})
                              ["episode_id"] or store.all_entry_intents()[0]["episode_id"]
                              )["status"] == "FILLED"


def test_price_still_missing_next_session_releases_intent_exactly_once(tmp_path):
    # Task 131 Final Remediation Directive 3: the retry deadline is the
    # APPROVED session-based recovery window -- ONE SESSION SHORT of
    # max_entry_staleness_sessions (3, the same frozen operational
    # parameter the pre-existing staleness guard uses), not just the
    # single immediate next session. The one-session offset is
    # deliberate: using the SAME threshold as the staleness guard would
    # make this escalation unreachable, since staleness excludes a stale
    # episode from ever reaching this check again one phase earlier in
    # the very same tick -- see service.py's own comment at the
    # retry_deadline computation for the full reasoning.
    bars = {"rows": _bars(omit=ELIGIBLE)}
    svc = _svc(tmp_path, bars)
    svc.tick(as_of=ACT)
    svc.tick(as_of=ELIGIBLE)                       # PENDING_RETRY

    # still well within the approved recovery window -- NOT escalated yet.
    st_mid = svc.tick(as_of=NEXT_SESSION)           # eligible + 1 session
    assert st_mid["entries_this_tick"] == 0
    assert st_mid["pending_retry_count_this_tick"] == 1
    store_mid = V2Store(str(tmp_path / "v2.db"), starting_cash=BALANCE)
    assert store_mid.all_entry_intents()[0]["status"] == "PENDING"

    retry_deadline = v2cal.add_sessions(ELIGIBLE, 2)
    st_at_deadline = svc.tick(as_of=retry_deadline)  # still <= deadline -- one more retry
    assert st_at_deadline["entries_this_tick"] == 0
    assert st_at_deadline["pending_retry_count_this_tick"] == 1
    assert V2Store(str(tmp_path / "v2.db"), starting_cash=BALANCE
                  ).all_entry_intents()[0]["status"] == "PENDING"

    past_deadline = v2cal.add_sessions(retry_deadline, 1)
    st = svc.tick(as_of=past_deadline)               # the approved window has fully elapsed

    assert st["entries_this_tick"] == 0
    assert st["pending_retry_count_this_tick"] == 0  # no longer pending -- terminal now
    store = V2Store(str(tmp_path / "v2.db"), starting_cash=BALANCE)
    intents = store.all_entry_intents()
    assert len(intents) == 1
    # Package 3 P3-D (OPS-003 Finding B, item 1): the coarse, date-only
    # staleness gate is now unified with this exact Session-3 boundary
    # (previously one session wider, a documented defect) -- so at
    # `past_deadline` the episode is now excluded by that OUTER gate
    # before `_phase_open` ever runs its own reactive NO_ENTRY_BAR
    # release logic, and is instead released via `_phase_post_close`'s
    # pre-existing staleness sweep. Still terminal, still exactly-once,
    # still no economic mutation -- only the specific terminal label
    # changed, a direct and intended consequence of closing the
    # 4-session/3-session gap this test's own timeline exercises.
    assert intents[0]["status"] == "EXPIRED_STALE"
    assert store.n_open() == 0
    assert store.cash() == BALANCE

    disp = [r[0] for r in __import__("sqlite3").connect(str(tmp_path / "v2.db")).execute(
        "SELECT disposition FROM processed_episodes")]
    # `processed_episodes.disposition` was already written as
    # SKIPPED_NO_ENTRY_BAR by an EARLIER retry attempt inside the
    # window (pipeline.process_episode) -- the later staleness sweep's
    # own disposition write is guarded (episode_seen() already True)
    # and correctly does not overwrite it; only the intent's own
    # status (asserted above) records the final EXPIRED_STALE outcome.
    assert disp == ["SKIPPED_NO_ENTRY_BAR"]

    # a further later tick does not re-release it or re-attempt it
    st2 = svc.tick(as_of=v2cal.next_session_strictly_after(past_deadline))
    assert st2["entries_this_tick"] == 0
    store2 = V2Store(str(tmp_path / "v2.db"), starting_cash=BALANCE)
    assert store2.all_entry_intents()[0]["status"] == "EXPIRED_STALE"
    assert store2.n_open() == 0
