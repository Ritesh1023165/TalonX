"""
Package 2 Acceptance Review -- targeted tests for A1, A4, A5.

Each section below traces a specific acceptance question end to end
(not merely the surface-level admission-gate check) and proves either
that the existing behavior was already safe, or verifies the narrow
correction made for this acceptance pass. Uses real temporary SQLite
files and, where concurrency/transaction semantics matter, genuinely
INDEPENDENT store connections/instances -- never a single-connection
unit test standing in for a concurrency proof.
"""
from __future__ import annotations

import sqlite3
import threading
from datetime import date, datetime, timezone

import pytest

from talonx_ops import account_blocks, eod_reconciliation as er
from talonx_paper.schemas import AlertAction
from talonx_paper.store import ORIGINAL_INTRADAY_ACCOUNT_ID, ORIGINAL_LONGTERM_ACCOUNT_ID, PaperTradingStore
from talonx_v2 import paper, pipeline
from talonx_v2.cluster_engine import ClusterEpisode
from talonx_v2.config import V2Config
from talonx_v2.schemas import V2Action, V2Decision, V2Direction
from talonx_v2.service import V2Service
from talonx_v2.store import V2_ACCOUNT_ID, V2Store

NOW = datetime(2026, 8, 10, 14, 37, 0, tzinfo=timezone.utc)

ACT = date(2026, 8, 14)
FUTURE_ENTRY = date(2027, 6, 3)  # within the generated XNYS calendar, far past real "now"
EARLY_DISSEMINATION = datetime(2026, 8, 14, 15, 20, tzinfo=timezone.utc)
BALANCE = 300_000.0
ALLOC = 10_000.0


def _bars(tmp, symbols):
    import csv
    from talonx_v2 import calendar as vc
    bd = tmp / "bars"
    bd.mkdir(exist_ok=True)
    sess = [s for s in vc._sessions() if date(2019, 1, 1) <= s <= date(2027, 12, 31)]
    for sym in symbols:
        with open(bd / f"{sym}.csv", "w", newline="") as f:
            w = csv.writer(f)
            w.writerow(["date", "open", "close", "volume"])
            for s in sess:
                w.writerow([s.isoformat(), 40.0, 40.5, 1_500_000])
    return bd


def _svc(tmp, db_path, *, name, symbols, starting_cash=BALANCE, alloc=ALLOC):
    cfg = V2Config(db_path=str(db_path), starting_cash_usd=starting_cash,
                   per_position_allocation_usd=alloc)
    return V2Service(config=cfg, bar_dirs=[_bars(tmp, symbols)], form4_kind="parquet",
                     status_path=str(tmp / f"{name}.json"))


def _ep(entry_session, episode_id, symbol):
    return ClusterEpisode(episode_id=episode_id, symbol=symbol, issuer_cik="x",
                          distinct_owner_ciks=("a", "b"), n_distinct_owners=2, n_filings=2,
                          first_filing_date=ACT, activation_filing_date=ACT, last_filing_date=ACT,
                          aggregate_purchase_value=0.0, any_officer=False, any_director=False,
                          any_ten_percent=False,
                          causal_event_ts=datetime(2026, 8, 14, 23, 59, 59, tzinfo=timezone.utc),
                          eligible_entry_session=entry_session)


def _fixed_buy_decision(e):
    liq = type("Liq", (), {"ok": True, "median_dollar_volume": 1e7, "last_close": 10.0})()
    dec = V2Decision(signal_id="s1", episode_id=e.episode_id, symbol=e.symbol,
                     direction=V2Direction.BULLISH, action=V2Action.BUY,
                     official_eligible=False, rationale="test (acceptance-review fixture)",
                     eligible_entry_session=e.eligible_entry_session)
    return liq, dec


def _wire(svc, symbol):
    svc._dissemination_lookup = {(symbol, ACT.isoformat()): EARLY_DISSEMINATION}
    svc._eval_causal_decision = _fixed_buy_decision


def _price_lookup(sym, sess):
    return {"open": 40.0, "close": 40.5}


def _decision(episode_id="ep1", symbol="AAA"):
    return V2Decision(signal_id=f"sig-{episode_id}", episode_id=episode_id, symbol=symbol,
                      direction=V2Direction.BULLISH, action=V2Action.BUY,
                      official_eligible=False, rationale="test",
                      eligible_entry_session=date(2026, 9, 8))


# ======================================================================= #
# A1 -- blocked account vs already-admitted PENDING intents
# ======================================================================= #

def test_a1_pending_intent_created_before_block_does_not_silently_fill_while_blocked(tmp_path, monkeypatch):
    """Full lifecycle: candidate -> reservation (PENDING intent) -> block
    activated -> attempted FILL. The fill must be refused (not silently
    admitted), the intent must remain a legitimate, unresolved PENDING
    reservation (not corrupted, not force-expired), and cash/positions
    must be completely unaffected by the refused attempt."""
    monkeypatch.setenv("TALONX_V2_DURABLE_STORE_ENABLED", "true")
    db_path = tmp_path / "v2.db"
    svc = _svc(tmp_path, db_path, name="a1", symbols=["AAAA"])
    ep = _ep(FUTURE_ENTRY, "a1-ep1", "AAAA")
    _wire(svc, "AAAA")

    # 1) admission -> reservation: a genuine PENDING intent, created
    # while the account is healthy.
    svc._phase_post_close([ep], [ep], today=FUTURE_ENTRY, ripe_through=FUTURE_ENTRY,
                          is_stale=lambda e: False, live=True)
    intent = svc.store.entry_intent("a1-ep1")
    assert intent is not None and intent["status"] == "PENDING"
    cash_before = svc.store.cash()

    # 2) the account is now seriously blocked (a ledger-integrity
    # incident, unrelated to this specific episode).
    svc.store.record_account_block(reason_type=account_blocks.REASON_LEDGER_MISMATCH,
                                   reference="unrelated-incident", detail="")

    # 3) attempted FILL: the same still-PENDING intent reaches _phase_open.
    from talonx_v2 import pipeline as pl
    res = pl.ProcessResult()
    svc._phase_open([ep], FUTURE_ENTRY, res, price_lookup=_price_lookup,
                    today=FUTURE_ENTRY, live=True)

    fresh = V2Store(str(db_path))
    assert fresh.position_for_episode("a1-ep1") is None, (
        "a PENDING intent silently filled while the account was blocked")
    still_pending = fresh.entry_intent("a1-ep1")
    assert still_pending is not None and still_pending["status"] == "PENDING", (
        "a refused fill attempt must leave the reservation intact, not "
        "silently cancel/expire it"
    )
    assert fresh.cash() == cash_before, "cash must be unaffected by a refused fill attempt"
    assert fresh.n_open() == 0
    assert fresh.trades() == []


def test_a1_new_reservation_refused_while_account_is_blocked(tmp_path, monkeypatch):
    """The narrow correction: a serious account block must also stop a
    NEW reservation (PENDING intent) from being committed -- not merely
    stop the eventual fill. Before this fix, _capacity_rejection_reason()
    only checked cash/slot capacity, never the account block, so a brand
    new episode discovered while the account was blocked could still
    receive a fresh PENDING intent + an ACTIONABLE alert promising a
    future BUY that could never actually fill."""
    monkeypatch.setenv("TALONX_V2_DURABLE_STORE_ENABLED", "true")
    db_path = tmp_path / "v2.db"
    svc = _svc(tmp_path, db_path, name="a1b", symbols=["BBBB"])
    ep = _ep(FUTURE_ENTRY, "a1b-ep1", "BBBB")
    _wire(svc, "BBBB")

    svc.store.record_account_block(reason_type=account_blocks.REASON_CASH_DEFICIT,
                                   reference="unrelated-incident", detail="")

    svc._phase_post_close([ep], [ep], today=FUTURE_ENTRY, ripe_through=FUTURE_ENTRY,
                          is_stale=lambda e: False, live=True)

    fresh = V2Store(str(db_path))
    assert fresh.entry_intent("a1b-ep1") is None, (
        "a NEW reservation was created for a blocked account")
    assert fresh.episode_disposition("a1b-ep1") == "SKIPPED_ACCOUNT_BLOCKED"
    assert fresh.all_outbox() == [], "no ENTRY_INTENT alert should be enqueued for a blocked account"
    assert svc._account_blocked_intent_rejected == 1


def test_a1_blocked_pending_intent_can_still_legitimately_expire(tmp_path, monkeypatch):
    """Legitimate expiry/cancellation of an EXISTING PENDING intent must
    remain possible while the account is blocked -- this must not be
    "solved" by indiscriminately freezing every state transition."""
    monkeypatch.setenv("TALONX_V2_DURABLE_STORE_ENABLED", "true")
    db_path = tmp_path / "v2.db"
    svc = _svc(tmp_path, db_path, name="a1c", symbols=["CCCC"])
    ep = _ep(FUTURE_ENTRY, "a1c-ep1", "CCCC")
    _wire(svc, "CCCC")
    svc._phase_post_close([ep], [ep], today=FUTURE_ENTRY, ripe_through=FUTURE_ENTRY,
                          is_stale=lambda e: False, live=True)
    assert svc.store.entry_intent("a1c-ep1")["status"] == "PENDING"

    svc.store.record_account_block(reason_type=account_blocks.REASON_LEDGER_MISMATCH,
                                   reference="unrelated-incident", detail="")

    # the staleness sweep in _phase_post_close is unconditional -- an
    # episode now judged stale must still transition its intent to
    # EXPIRED_STALE even though the account remains blocked.
    svc._phase_post_close([ep], [ep], today=FUTURE_ENTRY, ripe_through=FUTURE_ENTRY,
                          is_stale=lambda e: True, live=True)

    fresh = V2Store(str(db_path))
    assert fresh.entry_intent("a1c-ep1")["status"] == "EXPIRED_STALE"


def test_a1_existing_open_position_exit_continues_while_blocked(tmp_path, monkeypatch):
    """Existing open-position exits and recovery obligations must remain
    possible even while new admissions are blocked."""
    db_path = tmp_path / "v2.db"
    store = V2Store(str(db_path), starting_cash=BALANCE)
    cfg = V2Config(starting_cash_usd=BALANCE, per_position_allocation_usd=ALLOC)
    outcome = paper.enter_position(store, _decision("a1d-ep1", "DDDD"), entry_price=40.0,
                                   entry_session=date(2026, 9, 8), config=cfg)
    assert outcome.entered, outcome.reason

    store.record_account_block(reason_type=account_blocks.REASON_CASH_DEFICIT,
                               reference="unrelated-incident", detail="")

    from talonx_v2 import pipeline as pl
    res = pl.ProcessResult()
    pl.settle_due_exits(store=store, as_of_session=date(2026, 9, 25),
                        price_lookup=lambda sym, sess: {"open": 45.0, "close": 45.5},
                        config=cfg, result=res)

    fresh = V2Store(str(db_path))
    assert fresh.all_positions()[0]["status"] == "CLOSED", (
        "an existing open position could not be exited while the account was blocked")
    assert len(res.exits) == 1


def test_a1_independent_connections_block_visible_to_second_writer(tmp_path, monkeypatch):
    """Genuinely independent connections: a block committed via ONE
    V2Store connection must be immediately honored by admission attempts
    made through a SECOND, independent V2Store/V2Service instance
    against the same file -- not merely within a single process/connection."""
    monkeypatch.setenv("TALONX_V2_DURABLE_STORE_ENABLED", "true")
    db_path = tmp_path / "v2.db"
    svc_writer = _svc(tmp_path, db_path, name="a1e-w", symbols=["EEEE"])
    ep = _ep(FUTURE_ENTRY, "a1e-ep1", "EEEE")
    _wire(svc_writer, "EEEE")
    svc_writer._phase_post_close([ep], [ep], today=FUTURE_ENTRY, ripe_through=FUTURE_ENTRY,
                                 is_stale=lambda e: False, live=True)

    # a SEPARATE connection/instance records the block.
    blocker_store = V2Store(str(db_path))
    blocker_store.record_account_block(reason_type=account_blocks.REASON_LEDGER_MISMATCH,
                                       reference="seen-by-other-writer", detail="")

    # a THIRD, independent V2Service/V2Store instance attempts the fill.
    svc_reader = _svc(tmp_path, db_path, name="a1e-r", symbols=["EEEE"])
    _wire(svc_reader, "EEEE")
    from talonx_v2 import pipeline as pl
    res = pl.ProcessResult()
    svc_reader._phase_open([ep], FUTURE_ENTRY, res, price_lookup=_price_lookup,
                           today=FUTURE_ENTRY, live=True)

    fresh = V2Store(str(db_path))
    assert fresh.position_for_episode("a1e-ep1") is None
    assert fresh.entry_intent("a1e-ep1")["status"] == "PENDING"


# ======================================================================= #
# A2 -- Original CASH_DEFICIT: debit caps + detector
# ======================================================================= #

def test_a2_execute_buy_refuses_a_cost_exceeding_available_cash(tmp_path):
    """The store itself -- not merely the caller's own sizing -- must
    never debit past available cash. Before this fix, execute_buy()
    trusted the caller-supplied `cost` unconditionally."""
    with PaperTradingStore(tmp_path / "paper.db", 1000.0, 2500.0) as store:
        execution = store.execute_buy("NVDA", shares=100.0, price=100.0, cost=10_000.0, timestamp=NOW)
        assert execution is None
        assert store.get_portfolio_summary()["current_cash"] == 1000.0
        assert store.get_position("NVDA") is None
        rows = store._conn.execute("SELECT reason FROM ignored_decisions").fetchall()
        assert any("INSUFFICIENT_CASH_AT_EXECUTION" in r[0] for r in rows)


def test_a2_execute_long_term_buy_refuses_a_cost_exceeding_available_cash(tmp_path):
    with PaperTradingStore(tmp_path / "paper.db", 10000.0, 2500.0,
                           default_long_term_initial_balance=1000.0) as store:
        execution = store.execute_long_term_buy("AAPL", 100.0, 100.0, 10_000.0, NOW)
        assert execution is None
        assert store.get_long_term_portfolio_summary()["current_cash"] == 1000.0
        assert store.get_long_term_position("AAPL") is None


def test_a2_execute_dca_contribution_now_checks_the_account_block(tmp_path):
    """A gap this acceptance review found: execute_dca_contribution had
    NO account-block check at all -- a DCA contribution commits new
    economic exposure into an existing position, the same category the
    block already covers for a fresh BUY."""
    with PaperTradingStore(tmp_path / "paper.db", 10000.0, 2500.0,
                           default_long_term_initial_balance=20000.0) as store:
        opened = store.execute_long_term_buy("AAPL", 10.0, 100.0, 1000.0, NOW)
        assert opened is not None
        store.record_account_block(account_id=ORIGINAL_LONGTERM_ACCOUNT_ID,
                                   reason_type=account_blocks.REASON_CASH_DEFICIT,
                                   reference="x", detail="")

        contrib = store.execute_dca_contribution("AAPL", 500.0, 100.0, NOW)
        assert contrib is None
        assert store.get_long_term_portfolio_summary()["current_cash"] == 19000.0


def test_a2_execute_dca_contribution_refuses_a_contribution_exceeding_cash(tmp_path):
    with PaperTradingStore(tmp_path / "paper.db", 10000.0, 2500.0,
                           default_long_term_initial_balance=1000.0) as store:
        opened = store.execute_long_term_buy("AAPL", 5.0, 100.0, 500.0, NOW)
        assert opened is not None
        cash_after_open = store.get_long_term_portfolio_summary()["current_cash"]

        contrib = store.execute_dca_contribution("AAPL", 10_000.0, 100.0, NOW)
        assert contrib is None
        assert store.get_long_term_portfolio_summary()["current_cash"] == cash_after_open


def test_a2_cash_deficit_detector_blocks_original_intraday_only(tmp_path):
    """A2's core claim: once every debit path is capped, a negative
    current_cash has no benign explanation -- it is a reliable
    CASH_DEFICIT invariant. Simulates the only way it could still occur
    (external corruption bypassing the store's own guards) via a direct
    raw write, then proves the detector attributes it to the correct
    account only."""
    home = tmp_path
    db_path = home / "paper_trading.db"
    with PaperTradingStore(db_path, 10000.0, 2500.0):
        pass
    with sqlite3.connect(str(db_path)) as raw:
        raw.execute("UPDATE portfolio_state SET current_cash = -500.0 WHERE id = 1")
        raw.commit()

    recorded = er._record_original_cash_deficit_blocks(home)
    assert recorded

    with PaperTradingStore(db_path, 10000.0, 2500.0) as fresh:
        assert fresh.blocked_reason(ORIGINAL_INTRADAY_ACCOUNT_ID) is not None
        assert fresh.blocked_reason(ORIGINAL_LONGTERM_ACCOUNT_ID) is None


def test_a2_cash_deficit_detector_blocks_original_longterm_only(tmp_path):
    home = tmp_path
    db_path = home / "paper_trading.db"
    with PaperTradingStore(db_path, 10000.0, 2500.0):
        pass
    with sqlite3.connect(str(db_path)) as raw:
        raw.execute("UPDATE long_term_portfolio_state SET current_cash = -250.0 WHERE id = 1")
        raw.commit()

    recorded = er._record_original_cash_deficit_blocks(home)
    assert recorded

    with PaperTradingStore(db_path, 10000.0, 2500.0) as fresh:
        assert fresh.blocked_reason(ORIGINAL_LONGTERM_ACCOUNT_ID) is not None
        assert fresh.blocked_reason(ORIGINAL_INTRADAY_ACCOUNT_ID) is None


def test_a2_cash_deficit_detector_is_a_no_op_when_cash_is_healthy(tmp_path):
    home = tmp_path
    db_path = home / "paper_trading.db"
    with PaperTradingStore(db_path, 10000.0, 2500.0):
        pass
    assert er._record_original_cash_deficit_blocks(home) == []


# ======================================================================= #
# A4 -- clearance/verification serialization race
# ======================================================================= #

def test_a4_concurrent_writer_cannot_land_between_verification_and_clearance_write(tmp_path, monkeypatch):
    """The exact race A4 describes: T1 verifies healthy, T2 concurrently
    mutates the account, T1 clears based on now-stale verification. This
    proves it is PREVENTED -- not with a single-connection unit test,
    but with a genuinely independent V2Store connection attempting a
    real competing write while clearance's own write lock is held.
    verify_clearance_eligible is stubbed to return "healthy" but PAUSE
    (still holding the lock, inside clear_block's own transaction)
    until the competing writer has had a real chance to race in."""
    import talonx_ops.prospective.clearance as clearance_mod

    db_path = tmp_path / "v2.db"
    store = V2Store(str(db_path), starting_cash=BALANCE)
    bid = store.record_account_block(reason_type=account_blocks.REASON_LEDGER_MISMATCH,
                                     reference="race-ref", detail="initial detection")

    verification_started = threading.Event()
    proceed_with_write = threading.Event()

    def _slow_verify(db_path_, account_kind, blk):
        verification_started.set()
        assert proceed_with_write.wait(timeout=10), "test harness stalled"
        return True, "forced-allow-for-test"

    monkeypatch.setattr(clearance_mod, "verify_clearance_eligible", _slow_verify)

    clearance_result: dict = {}

    def _run_clearance():
        clearance_result["result"] = clearance_mod.clear_block(
            str(db_path), "V2", block_id=bid, operator_id="ops1",
            reason="attempting", evidence_ref="ev")

    def _run_competing_writer():
        assert verification_started.wait(timeout=10)
        # a SEPARATE, independent V2Store connection -- not the same
        # instance clearance is using -- attempts to re-record the
        # SAME issue while clearance's write lock is held.
        writer_store = V2Store(str(db_path))
        writer_store.record_account_block(
            reason_type=account_blocks.REASON_LEDGER_MISMATCH,
            reference="race-ref", detail="re-detected mid-clearance")

    t_clear = threading.Thread(target=_run_clearance)
    t_write = threading.Thread(target=_run_competing_writer)

    t_clear.start()
    assert verification_started.wait(timeout=10)
    t_write.start()
    # bounded liveness check (not a hopeful sleep): the competing
    # writer's own BEGIN IMMEDIATE must still be blocked on the real
    # SQLite write lock clearance is holding.
    t_write.join(timeout=0.5)
    assert t_write.is_alive(), "competing writer did not block on the real SQLite write lock"

    proceed_with_write.set()
    t_clear.join(timeout=10)
    t_write.join(timeout=10)
    assert not t_clear.is_alive() and not t_write.is_alive()

    assert clearance_result["result"]["allow"] is True
    assert clearance_result["result"]["outcome"] == "CLEARED"

    fresh = V2Store(str(db_path))
    # the competing writer's re-detection landed AFTER clearance
    # committed (it was genuinely blocked, then proceeded) -- so the
    # block is correctly ACTIVE again: the underlying issue really did
    # recur, this is NOT a race that let a stale verification win.
    assert fresh.blocked_reason() is not None
    history = fresh.block_clearance_history(bid)
    assert len(history) == 1 and history[0]["outcome"] == "CLEARED"


def test_a4_original_clearance_also_serializes_verification_and_write(tmp_path, monkeypatch):
    """Same protection for Original (PaperTradingStore.lock()): while
    clear_block holds the store's lock across verification + write, a
    competing thread calling any OTHER locked method on the SAME store
    instance must block until clearance releases it. Disclosed
    limitation: this is an in-process guarantee only (a plain
    threading.Lock, not cross-process) -- matching every other write
    path in Original's own existing architecture, which has no
    stronger serialization anywhere either."""
    import talonx_ops.prospective.clearance as clearance_mod

    db_path = tmp_path / "paper.db"
    with PaperTradingStore(db_path, 10000.0, 2500.0) as store:
        bid = store.record_account_block(account_id=ORIGINAL_INTRADAY_ACCOUNT_ID,
                                         reason_type=account_blocks.REASON_LEDGER_MISMATCH,
                                         reference="x", detail="")

        verification_started = threading.Event()
        proceed_with_write = threading.Event()

        def _slow_verify(db_path_, account_kind, blk):
            verification_started.set()
            assert proceed_with_write.wait(timeout=10), "test harness stalled"
            return True, "forced-allow-for-test"

        monkeypatch.setattr(clearance_mod, "verify_clearance_eligible", _slow_verify)

        def _run_clearance():
            clearance_mod.clear_block(str(db_path), "ORIGINAL_INTRADAY", block_id=bid,
                                      operator_id="ops1", reason="attempting", evidence_ref="ev")

        def _run_competing_writer():
            assert verification_started.wait(timeout=10)
            # the SAME store instance -- Original's serialization is
            # per-instance (threading.Lock), not per-file like V2's.
            store.record_account_block(account_id=ORIGINAL_INTRADAY_ACCOUNT_ID,
                                       reason_type=account_blocks.REASON_CASH_DEFICIT,
                                       reference="y", detail="concurrent")

        t_clear = threading.Thread(target=_run_clearance)
        t_write = threading.Thread(target=_run_competing_writer)
        t_clear.start()
        assert verification_started.wait(timeout=10)
        t_write.start()
        t_write.join(timeout=0.3)
        assert t_write.is_alive(), "competing writer did not block on the store's own lock"

        proceed_with_write.set()
        t_clear.join(timeout=10)
        t_write.join(timeout=10)
        assert not t_clear.is_alive() and not t_write.is_alive()

        assert store.blocked_reason(ORIGINAL_INTRADAY_ACCOUNT_ID) is not None
        active = store.active_account_blocks(ORIGINAL_INTRADAY_ACCOUNT_ID)
        assert any(b["reason_type"] == account_blocks.REASON_CASH_DEFICIT for b in active), (
            "the competing writer's block must have landed (after clearance "
            "released the lock), proving it was delayed, not lost"
        )


# ======================================================================= #
# A5 -- settlement uses authoritative persisted position data
# ======================================================================= #

def _entered_v2(tmp_path, *, cash=BALANCE, symbol="AAA", episode_id="ep1", db_name="v.db"):
    store = V2Store(str(tmp_path / db_name), starting_cash=cash)
    cfg = V2Config(starting_cash_usd=cash, per_position_allocation_usd=10_000.0)
    outcome = paper.enter_position(store, _decision(episode_id, symbol), entry_price=100.0,
                                   entry_session=date(2026, 9, 8), config=cfg)
    assert outcome.entered, outcome.reason
    pos = store.all_positions()[0]
    return store, cfg, pos


def test_a5_close_position_ignores_a_stale_caller_supplied_shares_and_entry_price(tmp_path):
    """A caller passing a STALE/WRONG shares+entry_price (e.g. an
    overlapping caller's earlier read, or simple corruption of the
    in-memory dict) must not be able to make settlement disagree with
    what is actually persisted -- cash credited and P&L recorded must
    reflect the REAL position, not the caller's claim."""
    store, cfg, real_pos = _entered_v2(tmp_path)
    real_shares = real_pos["shares"]
    real_entry_price = real_pos["entry_price"]
    cash_before = store.cash()

    tampered = dict(real_pos)
    tampered["shares"] = real_shares * 100  # wildly wrong
    tampered["entry_price"] = 1.0           # wildly wrong -> would fabricate huge fake profit
    tampered["position_cost"] = 1.0

    out = paper.close_position(store, tampered, exit_price=105.0,
                               exit_session=date(2026, 9, 22), config=cfg)

    fresh = V2Store(str(tmp_path / "v.db"))
    expected_proceeds = real_shares * 105.0
    assert fresh.cash() == pytest.approx(cash_before + expected_proceeds), (
        "settlement used the caller-supplied (tampered) shares instead of "
        "the authoritative persisted quantity"
    )
    trade = fresh.trades()[-1]
    assert trade["shares"] == pytest.approx(real_shares)
    assert trade["entry_price"] == pytest.approx(real_entry_price)
    assert out.realized_pnl_usd == pytest.approx((105.0 - real_entry_price) * real_shares)


def test_a5_close_position_ignores_a_stale_caller_supplied_position_id_free_fields(tmp_path):
    """Even the episode_id/symbol used in the appended trade record and
    ExitOutcome must come from the authoritative row, not a caller's
    possibly-wrong dict -- only position_id is trusted as a lookup key."""
    store, cfg, real_pos = _entered_v2(tmp_path, symbol="AAA", episode_id="ep1")
    tampered = dict(real_pos)
    tampered["symbol"] = "WRONG"
    tampered["episode_id"] = "wrong-episode"

    out = paper.close_position(store, tampered, exit_price=105.0,
                               exit_session=date(2026, 9, 22), config=cfg)

    assert out.symbol == "AAA"
    assert out.episode_id == "ep1"
    fresh = V2Store(str(tmp_path / "v.db"))
    trade = fresh.trades()[-1]
    assert trade["symbol"] == "AAA"
    assert trade["episode_id"] == "ep1"


def test_a5_close_position_refuses_a_nonexistent_position_id_without_fabricating_an_exit(tmp_path):
    store, cfg, real_pos = _entered_v2(tmp_path)
    fake = dict(real_pos)
    fake["position_id"] = 99999  # does not exist

    out = paper.close_position(store, fake, exit_price=105.0,
                               exit_session=date(2026, 9, 22), config=cfg)
    assert out.settled is False
    fresh = V2Store(str(tmp_path / "v.db"))
    assert len(fresh.trades()) == 1  # only the original BUY -- no fabricated SELL
    assert fresh.all_positions()[0]["status"] == "OPEN"
