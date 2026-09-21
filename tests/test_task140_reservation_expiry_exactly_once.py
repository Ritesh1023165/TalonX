"""
tests/test_task140_reservation_expiry_exactly_once.py
========================================================
Task 140 item 7: persistent reservation expiry/release, exactly once,
across a real store close/reopen (simulating a process restart) -- using
the REAL V2Service/V2Store path, an isolated on-disk database, and a
controlled clock. No live position is constructed anywhere in this file.

Real mechanism (verified by direct code inspection first,
talonx_v2/service.py::_capacity_rejection_reason -- Task 131 Remediation
Directive 4): a PENDING entry intent reserves capacity by being COUNTED
(cash = per_position_allocation_usd * count of PENDING intents, one
slot per PENDING intent) -- it does NOT debit store.cash() at all. Cash
is only ever touched at an actual FILL. So "release" means the intent's
own status leaving 'PENDING' (EXPIRED_STALE is a terminal status,
excluded from pending_entry_intents()) -- there is no cash credit to
prove on release, because there was never a cash debit to prove on
reservation. This test proves the CORRECT invariant for the real
mechanism: cash is unchanged throughout, and available reserved
capacity is restored exactly once when (and only when) the intent
transitions out of PENDING.
"""
from __future__ import annotations

from datetime import date

from talonx_v2 import calendar as v2cal
from talonx_v2 import form4_source
from talonx_v2.cluster_engine import detect_episodes
from talonx_v2.config import V2Config
from talonx_v2.store import V2Store

BALANCE = 300_000.0


def _cfg(tmp_path, **kw):
    kw.setdefault("per_position_allocation_usd", 10_000.0)
    kw.setdefault("starting_cash_usd", BALANCE)
    kw.setdefault("db_path", str(tmp_path / "v2.db"))
    return V2Config(**kw)


def _bars(a="2026-06-01", b="2026-10-15", close=100.0, vol=500_000):
    sess = [s for s in v2cal._sessions()
            if date.fromisoformat(a) <= s <= date.fromisoformat(b)]
    return [{"date": s.isoformat(), "open": close, "close": close, "volume": vol}
            for s in sess]


def _cluster_rows(sym, d1, d2):
    return [
        dict(symbol=sym, issuer_cik=sym + "c", owner_cik=sym + "1", filing_date=d1,
             accession=sym + "a1", transaction_value=500_000, is_officer=True,
             transaction_code="P"),
        dict(symbol=sym, issuer_cik=sym + "c", owner_cik=sym + "2", filing_date=d2,
             accession=sym + "a2", transaction_value=700_000, is_director=True,
             transaction_code="P"),
    ]


def _svc(cfg, tmp_path, rows, bars):
    from talonx_v2.service import V2Service

    svc = V2Service(config=cfg, bar_dirs=[tmp_path], form4_kind="parquet",
                    status_path=str(tmp_path / "status.json"))
    recs = form4_source.from_rows(rows)
    svc._records = lambda *, as_of: recs           # noqa: SLF001
    svc._bars = lambda sym: bars                   # noqa: SLF001
    # deliberately NO price for the entry session -- so if the episode
    # ever became ripe, it could not fill; this test never lets it
    # become ripe before it goes stale, so this is belt-and-suspenders,
    # not the actual mechanism under test (see the module docstring).
    svc._price = lambda sym, session: None          # noqa: SLF001
    return svc


def test_reservation_reserves_then_releases_exactly_once_across_restart(tmp_path):
    # Activation 2 sessions before "today" (2026-09-08) so
    # eligible_entry_session (entry_offset_sessions=1 after activation)
    # is 1 SESSION IN THE FUTURE relative to the first tick below --
    # the episode is NOT yet ripe, so the pre-open PENDING intent pass
    # creates a real reservation without ever attempting a fill.
    cfg = _cfg(tmp_path)
    rows = _cluster_rows("RSRV", "2026-09-03", "2026-09-04")
    bars = _bars()
    svc = _svc(cfg, tmp_path, rows, bars)
    ep = detect_episodes(form4_source.from_rows(rows), config=cfg)[0]

    tick1 = date(2026, 9, 4)
    assert ep.eligible_entry_session > tick1, "fixture must start with the intent not yet ripe"

    # ---- tick 1: reservation created --------------------------------
    st1 = svc.tick(as_of=tick1)
    store = V2Store(cfg.db_path)
    intent = store.entry_intent(ep.episode_id)
    assert intent is not None and intent["status"] == "PENDING"
    cash_after_reservation = store.cash()
    assert cash_after_reservation == BALANCE, "a PENDING intent must not debit cash at all"

    # ---- BEFORE expiry: the reservation genuinely constrains capacity ----
    reserved_cash = cfg.per_position_allocation_usd * len(store.pending_entry_intents())
    available = store.cash() - reserved_cash
    assert available < BALANCE, "the reservation must reduce computed available capacity"
    reject_reason = svc._capacity_rejection_reason()  # noqa: SLF001
    # only 1 intent reserving $10k out of $300k -- plenty of room left for
    # ANOTHER $10k intent, so this specific fixture doesn't reject a
    # second one; the reservation's REAL effect (a nonzero deduction) is
    # what's asserted above, not artificial exhaustion.
    assert reject_reason is None or "unreserved" in reject_reason

    # ---- close/reopen (simulates a process restart) ------------------
    store2 = V2Store(cfg.db_path)
    intent_after_restart = store2.entry_intent(ep.episode_id)
    assert intent_after_restart is not None and intent_after_restart["status"] == "PENDING"
    assert store2.cash() == BALANCE

    # ---- advance beyond the approved staleness boundary and tick ------
    # max_entry_staleness_sessions=3 (frozen minimum meaning); the
    # episode becomes RIPE once its own eligible_entry_session passes,
    # and STALE once more than max_entry_staleness_sessions have elapsed
    # since then without a fill (svc._price always returns None here).
    stale_tick = v2cal.add_sessions(ep.eligible_entry_session, cfg.max_entry_staleness_sessions + 2)
    st2 = svc.tick(as_of=stale_tick)
    assert st2["stale_entry_skipped_this_tick"] >= 1
    assert st2["entries_this_tick"] == 0

    store3 = V2Store(cfg.db_path)
    intent_expired = store3.entry_intent(ep.episode_id)
    assert intent_expired is not None
    assert intent_expired["status"] == "EXPIRED_STALE"     # terminal, released
    assert intent_expired["episode_id"] not in {i["episode_id"] for i in store3.pending_entry_intents()}
    assert store3.cash() == BALANCE                        # never touched, before or after
    assert store3.n_open() == 0                             # no phantom position
    assert store3.all_positions() == []
    assert store3.trades() == []                            # no phantom trade/fill

    # capacity is now genuinely restored -- 0 PENDING intents reserving anything
    reserved_after = cfg.per_position_allocation_usd * len(store3.pending_entry_intents())
    assert reserved_after == 0.0

    # ---- repeat the tick and close/reopen again -- exactly once, idempotent ----
    updated_at_1 = intent_expired["updated_at_utc"]
    st3 = svc.tick(as_of=v2cal.add_sessions(stale_tick, 1))
    store4 = V2Store(cfg.db_path)
    intent_again = store4.entry_intent(ep.episode_id)
    assert intent_again["status"] == "EXPIRED_STALE"        # still terminal, not re-processed
    assert intent_again["updated_at_utc"] == updated_at_1, \
        "the release must not re-fire (row churned) on a later tick"
    assert store4.cash() == BALANCE
    assert store4.n_open() == 0
    assert store4.all_positions() == []
    assert store4.trades() == []
    assert st3["entries_this_tick"] == 0


def test_reservation_release_does_not_invent_a_cash_credit(tmp_path):
    """Explicit, narrow assertion matching the directive's own warning:
    this implementation's reservations never touch store.cash() at all,
    at creation OR release -- prove that directly, rather than assuming
    a debit/credit pair the code does not use."""
    cfg = _cfg(tmp_path)
    rows = _cluster_rows("NOCR", "2026-09-03", "2026-09-04")
    bars = _bars()
    svc = _svc(cfg, tmp_path, rows, bars)
    ep = detect_episodes(form4_source.from_rows(rows), config=cfg)[0]
    tick1 = date(2026, 9, 4)

    cash_before_any_tick = V2Store(cfg.db_path).cash()
    svc.tick(as_of=tick1)                                    # reservation created
    cash_after_reservation = V2Store(cfg.db_path).cash()
    stale_tick = v2cal.add_sessions(ep.eligible_entry_session, cfg.max_entry_staleness_sessions + 2)
    svc.tick(as_of=stale_tick)                                # reservation released
    cash_after_release = V2Store(cfg.db_path).cash()

    assert cash_before_any_tick == cash_after_reservation == cash_after_release == BALANCE
