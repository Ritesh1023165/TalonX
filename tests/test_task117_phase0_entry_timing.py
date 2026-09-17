"""
Task 117 Phase 0 -- Acceptance closure Phase 2: entry-time pricing & retry semantics.

Resolves "today's bar is PROVISIONAL" vs "entry deferred one tick": a PROVISIONAL
bar is *unavailable*, unavailability does NOT consume the episode, so it retries.

All bars here are SYNTHETIC constant-OHLCV fixtures. No test claims a historical
daily bar proves intraday availability.

Trace: results/task117_phase0_acceptance_closure_*/entry_timing/entry_disposition_trace.md
"""
from __future__ import annotations

from datetime import date

import pytest

from talonx_v2 import pipeline, pricing
from talonx_v2.cluster_engine import detect_episodes
from talonx_v2.config import V2Config
from talonx_v2.form4_source import from_rows
from talonx_v2.store import V2Store

# XNYS sessions used (from talonx_v2.calendar):
#   ... 2026-08-13, 2026-08-14(Fri), 2026-08-17(Mon), 2026-08-18 ... 2026-08-31(+10td)
ENTRY = date(2026, 8, 17)
ACTIVATION = date(2026, 8, 14)
EXIT_10TD = date(2026, 8, 31)


def _episode(symbol="AAA", activation=ACTIVATION):
    rows = [
        {"symbol": symbol, "issuer_cik": symbol + "_CIK", "owner_cik": "own1",
         "filing_date": activation.isoformat(), "accession": "a1",
         "transaction_value": 200000, "transaction_code": "P"},
        {"symbol": symbol, "issuer_cik": symbol + "_CIK", "owner_cik": "own2",
         "filing_date": activation.isoformat(), "accession": "a2",
         "transaction_value": 200000, "transaction_code": "P"},
    ]
    eps = detect_episodes(from_rows(rows), config=V2Config())
    assert len(eps) == 1 and eps[0].eligible_entry_session == ENTRY
    return eps[0]


class _FakeAdapter:
    """history()/session() over an in-memory {symbol: [rows]} map. A symbol
    in ``raise_for`` raises on session() until removed (transient fault)."""

    name = "fake:test"

    def __init__(self, bars: dict[str, list[dict]], raise_for: set[str] | None = None):
        self._bars = bars
        self.raise_for = raise_for or set()

    def history(self, symbol):
        return list(self._bars.get(symbol, []))

    def session(self, symbol, session):
        if symbol in self.raise_for:
            raise RuntimeError("transient provider fault")
        s = session.isoformat()
        return next((r for r in self._bars.get(symbol, []) if r["date"] == s), None)


def _hist_before_entry(symbol="AAA", close=100.0, vol=1_000_000):
    """>= 20 FINAL sessions strictly before ENTRY, all liquid."""
    from talonx_v2 import calendar as v2cal
    sess = [s for s in v2cal._sessions() if date(2026, 6, 1) <= s < ENTRY]
    return [{"date": s.isoformat(), "open": close, "close": close, "volume": vol} for s in sess]


def _resolver(adapter, today):
    r = pricing.PricingResolver(adapter=adapter)
    r.today = lambda: today
    return r


def _run(store, ep, resolver, cfg=None):
    cfg = cfg or V2Config()
    res = pipeline.ProcessResult()
    pipeline.process_episode(ep, store=store, bars_lookup=resolver.bars_lookup,
                             price_lookup=resolver.price_lookup, config=cfg, result=res)
    return res


# --------------------------------------------------------------------------- E1
def test_e1a_frozen_entry_at_eligible_session_open(tmp_path):
    sym = "AAA"
    bars = {sym: _hist_before_entry(sym) + [
        {"date": ENTRY.isoformat(), "open": 101.0, "close": 102.0, "volume": 900_000}]}
    store = V2Store(str(tmp_path / "v.db"), starting_cash=300_000.0)
    res = _run(store, _episode(sym), _resolver(_FakeAdapter(bars), today=date(2026, 8, 18)))
    assert len(res.entries) == 1
    e = res.entries[0]
    assert e["entry_session"] == ENTRY.isoformat()
    assert e["entry_price"] == 101.0                      # the eligible-entry-session OPEN
    assert e["target_exit_session"] == EXIT_10TD.isoformat()
    assert [t["action"] for t in store.trades()] == ["BUY"]


def test_e1b_before_open_today_bar_is_provisional_not_consumed(tmp_path):
    sym = "AAA"
    bars = {sym: _hist_before_entry(sym) + [
        {"date": ENTRY.isoformat(), "open": 101.0, "close": 101.0, "volume": 10}]}
    store = V2Store(str(tmp_path / "v.db"), starting_cash=300_000.0)
    res = _run(store, _episode(sym), _resolver(_FakeAdapter(bars), today=ENTRY))  # today == entry
    assert res.entries == []
    assert store.episode_disposition(_episode(sym).episode_id) == "SKIPPED_NO_ENTRY_BAR"
    assert store.position_for_episode(_episode(sym).episode_id) is None
    # SKIPPED_NO_ENTRY_BAR is NOT in the terminal set
    assert "SKIPPED_NO_ENTRY_BAR" not in ("ENTERED", "SKIPPED_ENTRY_STALE")


# --------------------------------------------------------------------------- E2
def test_e2a_missing_entry_bar_is_non_terminal_skip(tmp_path):
    sym = "AAA"
    bars = {sym: _hist_before_entry(sym)}                 # no ENTRY bar at all
    store = V2Store(str(tmp_path / "v.db"), starting_cash=300_000.0)
    res = _run(store, _episode(sym), _resolver(_FakeAdapter(bars), today=date(2026, 8, 14)))
    assert res.entries == [] and res.skipped[-1]["reason"] == "NO_ENTRY_BAR"
    assert store.episode_disposition(_episode(sym).episode_id) == "SKIPPED_NO_ENTRY_BAR"


def test_e2b_next_tick_session_now_final_enters_once(tmp_path):
    sym = "AAA"
    db = str(tmp_path / "v.db")
    entry_bar = {"date": ENTRY.isoformat(), "open": 101.0, "close": 103.0, "volume": 900_000}
    bars = {sym: _hist_before_entry(sym) + [entry_bar]}
    ep = _episode(sym)

    # tick 1: today == entry session -> PROVISIONAL -> not consumed
    store = V2Store(db, starting_cash=300_000.0)
    _run(store, ep, _resolver(_FakeAdapter(bars), today=ENTRY))
    assert store.episode_disposition(ep.episode_id) == "SKIPPED_NO_ENTRY_BAR"

    # tick 2: one day later, the entry-session bar is now FINAL -> ENTER, single BUY
    store2 = V2Store(db, starting_cash=300_000.0)
    res = _run(store2, ep, _resolver(_FakeAdapter(bars), today=date(2026, 8, 18)))
    assert len(res.entries) == 1 and res.entries[0]["entry_price"] == 101.0
    assert store2.episode_disposition(ep.episode_id) == "ENTERED"
    assert [t["action"] for t in store2.trades()] == ["BUY"]
    assert store2.n_open() == 1


def test_e2c_day_rolled_still_enters_at_the_entry_sessions_open(tmp_path):
    # today = 2026-08-19 (2 sessions after entry, still within max_entry_staleness_sessions=3).
    # The fill is the ENTRY session's open, never a later session's.
    sym = "AAA"
    bars = {sym: _hist_before_entry(sym) + [
        {"date": ENTRY.isoformat(), "open": 101.0, "close": 103.0, "volume": 900_000},
        {"date": "2026-08-18", "open": 110.0, "close": 111.0, "volume": 900_000},
        {"date": "2026-08-19", "open": 120.0, "close": 121.0, "volume": 900_000}]}
    store = V2Store(str(tmp_path / "v.db"), starting_cash=300_000.0)
    res = _run(store, _episode(sym), _resolver(_FakeAdapter(bars), today=date(2026, 8, 19)))
    assert len(res.entries) == 1
    assert res.entries[0]["entry_price"] == 101.0         # NOT 110 or 120
    assert res.entries[0]["entry_session"] == ENTRY.isoformat()


# --------------------------------------------------------------------------- E3
def test_e3a_provisional_today_bar_excluded_from_liquidity_window(tmp_path):
    sym = "AAA"
    # a PROVISIONAL today-bar with 100x volume must NOT enter the 20-session median
    hist = _hist_before_entry(sym, close=100.0, vol=1_000_000)
    bars = {sym: hist + [
        {"date": ENTRY.isoformat(), "open": 101.0, "close": 101.0, "volume": 100_000_000}]}
    res_r = _resolver(_FakeAdapter(bars), today=ENTRY)
    liq_bars = res_r.bars_lookup(sym)
    assert all(b["date"] < ENTRY.isoformat() for b in liq_bars)      # no ENTRY-dated bar
    from talonx_v2.liquidity import evaluate_liquidity
    liq = evaluate_liquidity(liq_bars, entry_session=ENTRY, config=V2Config())
    assert liq.n_sessions_used == 20
    assert liq.median_dollar_volume == 100.0 * 1_000_000            # the clean 100M, not 10.1B


def test_e3b_no_lookahead_entry_session_bar_never_in_liquidity_set(tmp_path):
    sym = "AAA"
    bars = {sym: _hist_before_entry(sym) + [
        {"date": ENTRY.isoformat(), "open": 101.0, "close": 101.0, "volume": 900_000}]}
    res_r = _resolver(_FakeAdapter(bars), today=date(2026, 8, 18))  # ENTRY now FINAL
    liq_bars = res_r.bars_lookup(sym)
    from talonx_v2.liquidity import evaluate_liquidity
    liq = evaluate_liquidity(liq_bars, entry_session=ENTRY, config=V2Config())
    assert liq.n_sessions_used == 20                                # strictly-before only


# --------------------------------------------------------------------------- E4
def test_e4a_stale_episode_never_chased_at_a_historical_open(tmp_path):
    from talonx_v2.service import V2Service
    sym = "AAA"
    # eligible entry 2026-08-17; today 2026-09-09 -> ~16 sessions later -> STALE (>3)
    rows = [
        {"symbol": sym, "issuer_cik": sym + "_CIK", "owner_cik": "o1",
         "filing_date": ACTIVATION.isoformat(), "accession": "a1", "transaction_code": "P",
         "transaction_value": 200000},
        {"symbol": sym, "issuer_cik": sym + "_CIK", "owner_cik": "o2",
         "filing_date": ACTIVATION.isoformat(), "accession": "a2", "transaction_code": "P",
         "transaction_value": 200000},
    ]
    import talonx_v2.form4_source as f4s

    class _S:
        def query_transactions(self, **_):
            return []
    cfg = V2Config(db_path=str(tmp_path / "v.db"), starting_cash_usd=300_000.0)
    svc = V2Service(config=cfg, bar_dirs=[tmp_path], form4_kind="parquet",
                    status_path=str(tmp_path / "s.json"))
    # feed the records directly via the parquet-normalised path
    svc._records = lambda *, as_of: f4s.from_rows(rows)  # type: ignore
    st1 = svc.tick(as_of=date(2026, 9, 9))
    assert st1["stale_entry_skipped_this_tick"] == 1
    assert st1["entries_this_tick"] == 0
    st2 = svc.tick(as_of=date(2026, 9, 10))
    assert st2["entries_this_tick"] == 0
    store = V2Store(str(tmp_path / "v.db"), starting_cash=300_000.0)
    assert store.cash() == 300_000.0 and store.n_open() == 0
    import sqlite3
    con = sqlite3.connect(str(tmp_path / "v.db"))
    disps = [r[0] for r in con.execute("SELECT disposition FROM processed_episodes")]
    con.close()
    assert disps == ["SKIPPED_ENTRY_STALE"]              # exactly one, and stale -- never ENTERED


# --------------------------------------------------------------------------- E5
def test_e5a_transient_provider_error_retried_then_entered_single_buy(tmp_path):
    sym = "AAA"
    db = str(tmp_path / "v.db")
    entry_bar = {"date": ENTRY.isoformat(), "open": 101.0, "close": 103.0, "volume": 900_000}
    bars = {sym: _hist_before_entry(sym) + [entry_bar]}
    ep = _episode(sym)

    # tick 1: session() raises for this symbol -> PROVIDER_ERROR -> None -> non-terminal skip
    adapter = _FakeAdapter(bars, raise_for={sym})
    store = V2Store(db, starting_cash=300_000.0)
    r = _resolver(adapter, today=date(2026, 8, 18))
    res1 = _run(store, ep, r)
    assert res1.entries == []
    assert store.episode_disposition(ep.episode_id) == "SKIPPED_NO_ENTRY_BAR"
    assert r.last[f"{sym}|{ENTRY.isoformat()}"].reason == "PROVIDER_ERROR"

    # tick 2: provider recovers -> ENTER exactly once
    adapter.raise_for.clear()
    store2 = V2Store(db, starting_cash=300_000.0)
    res2 = _run(store2, ep, _resolver(adapter, today=date(2026, 8, 18)))
    assert len(res2.entries) == 1
    assert [t["action"] for t in store2.trades()] == ["BUY"]


def test_e5b_duplicate_filing_or_restart_no_second_buy(tmp_path):
    sym = "AAA"
    db = str(tmp_path / "v.db")
    bars = {sym: _hist_before_entry(sym) + [
        {"date": ENTRY.isoformat(), "open": 101.0, "close": 103.0, "volume": 900_000}]}
    ep = _episode(sym)
    store = V2Store(db, starting_cash=300_000.0)
    _run(store, ep, _resolver(_FakeAdapter(bars), today=date(2026, 8, 18)))
    store2 = V2Store(db, starting_cash=300_000.0)
    res = _run(store2, ep, _resolver(_FakeAdapter(bars), today=date(2026, 8, 18)))
    assert res.entries == []
    assert res.skipped[-1]["reason"] == "ALREADY_PROCESSED"
    assert [t["action"] for t in store2.trades()] == ["BUY"]     # still exactly one


# --------------------------------------------------------------------------- E6
def test_e6a_liquidity_uses_completed_sessions_strictly_before_entry(tmp_path):
    sym = "AAA"
    bars = {sym: _hist_before_entry(sym) + [
        {"date": ENTRY.isoformat(), "open": 101.0, "close": 101.0, "volume": 900_000}]}
    r = _resolver(_FakeAdapter(bars), today=date(2026, 8, 18))
    from talonx_v2.liquidity import evaluate_liquidity
    liq = evaluate_liquidity(r.bars_lookup(sym), entry_session=ENTRY, config=V2Config())
    assert liq.ok and liq.n_sessions_used == 20
    # the last close used is the session immediately before ENTRY (2026-08-14)
    assert liq.last_close == 100.0


# --------------------------------------------------------------------------- E7
def test_e7a_every_unavailability_reason_is_distinct(tmp_path):
    sym = "AAA"
    bars = {sym: [
        {"date": "2026-08-10", "open": 10.0, "close": 10.0, "volume": 1000},        # good FINAL
        {"date": ENTRY.isoformat(), "open": 5.0, "close": 5.0, "volume": 1000},      # today -> PROVISIONAL
        {"date": "2026-08-18", "open": float("nan"), "close": 5.0, "volume": 1000},  # nonfinite
        {"date": "2026-08-19", "open": 5.0, "close": 5.0, "volume": -3},             # bad volume
    ]}
    r = _resolver(_FakeAdapter(bars), today=ENTRY)
    assert r.resolve(sym, date(2026, 8, 24)).reason == "FUTURE_SESSION"      # > today
    assert r.resolve(sym, date(2026, 8, 11)).reason == "NO_BAR"             # no row
    assert r.resolve(sym, ENTRY).reason == "PROVISIONAL_ONLY"
    r2 = _resolver(_FakeAdapter(bars), today=date(2026, 8, 20))
    assert r2.resolve(sym, date(2026, 8, 18)).reason == \
        "REJECTED_NONFINITE_OR_NONPOSITIVE_PRICE"
    assert r2.resolve(sym, date(2026, 8, 19)).reason == "REJECTED_BAD_VOLUME"
    # wrong-session: adapter hands back a row dated other than asked
    bad = _FakeAdapter({sym: [{"date": "2026-08-10", "open": 5.0, "close": 5.0, "volume": 1}]})
    bad.session = lambda s, d: {"date": "2026-08-10", "open": 5.0, "close": 5.0, "volume": 1}
    assert _resolver(bad, today=date(2026, 8, 20)).resolve(sym, date(2026, 8, 11)).reason \
        .startswith("REJECTED_WRONG_SESSION_")
    assert _resolver(_FakeAdapter(bars, raise_for={sym}), today=date(2026, 8, 20)) \
        .resolve(sym, date(2026, 8, 18)).reason == "PROVIDER_ERROR"


# --------------------------------------------------------------------------- E8
def test_e8a_friday_activation_enters_monday(tmp_path):
    ep = _episode("AAA", activation=date(2026, 8, 14))    # Friday
    assert ep.eligible_entry_session == date(2026, 8, 17)  # Monday, not Sat/Sun


def test_e8c_exit_unresolved_when_target_and_all_fallforward_missing(tmp_path):
    sym = "AAA"
    db = str(tmp_path / "v.db")
    # enter normally
    bars = {sym: _hist_before_entry(sym) + [
        {"date": ENTRY.isoformat(), "open": 101.0, "close": 103.0, "volume": 900_000}]}
    ep = _episode(sym)
    store = V2Store(db, starting_cash=300_000.0)
    _run(store, ep, _resolver(_FakeAdapter(bars), today=date(2026, 8, 18)))
    assert store.n_open() == 1

    # settle far in the future with NO bar on the +10 session or any of the next 5
    from talonx_v2 import calendar as v2cal
    as_of = v2cal.add_sessions(EXIT_10TD, 8)               # well past target+5
    res = pipeline.ProcessResult()
    r = _resolver(_FakeAdapter(bars), today=as_of)          # bars has no post-entry sessions
    pipeline.settle_due_exits(store=store, as_of_session=as_of,
                              price_lookup=r.price_lookup, config=V2Config(), result=res)
    # Package 1 Settlement Integrity: EXIT_UNRESOLVED is no longer OPEN
    # (not retryable -- confirmed by open_positions() below), but it
    # still occupies its capacity slot until an operator auditably
    # resolves it -- n_open() now correctly counts OPEN + EXIT_UNRESOLVED.
    assert store.open_positions() == []
    assert store.n_open() == 1
    unresolved = store.unresolved_positions()
    assert len(unresolved) == 1 and unresolved[0]["symbol"] == sym
    assert any(s["reason"] == "EXIT_UNRESOLVED" for s in res.skipped)
