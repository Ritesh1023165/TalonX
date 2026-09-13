"""Task 119 -- attributable per-lane paper-performance surface
(talonx_ops.paper_performance / DashboardReadModel.paper_performance).

Focused coverage per the task's own Part 6 checklist: lane/source
separation, session-vs-campaign counts, equity including open-position
value, cost handling without double deduction, missing/stale marks,
post-close vs regular-close valuation, recovery provenance,
exact/partial/unavailable reconciliation, and no production writes or
network sends anywhere in the read path.

All fixtures are isolated sqlite files under ``tmp_path`` -- this suite
never opens ``~/.talonx`` or any repo-root production db.
"""
from __future__ import annotations

import sqlite3
from datetime import datetime, timezone
from pathlib import Path

import pytest

from talonx_ops.paper_performance import (
    RECOVERY_AFFECTED_EVIDENCE_NOTE,
    build_paper_performance,
    classify_valuation_timestamp,
)

NOW = datetime(2026, 9, 11, 20, 15, 0, tzinfo=timezone.utc)


def _mk_paper_db(path: Path, *, initial_balance, current_cash, total_realized_pnl_usd=0.0,
                 win_count=0, loss_count=0, positions=(), trade_history=(), latest_prices=()):
    for sfx in ("", "-wal", "-shm"):
        p = Path(str(path) + sfx)
        if p.exists():
            p.unlink()
    con = sqlite3.connect(path)
    con.executescript("""
      CREATE TABLE portfolio_state (id INTEGER PRIMARY KEY CHECK (id=1),
        initial_balance REAL NOT NULL, current_cash REAL NOT NULL,
        trade_allocation_usd REAL NOT NULL DEFAULT 0,
        total_realized_pnl_usd REAL NOT NULL DEFAULT 0,
        win_count INTEGER NOT NULL DEFAULT 0, loss_count INTEGER NOT NULL DEFAULT 0);
      CREATE TABLE positions (ticker TEXT PRIMARY KEY, shares REAL NOT NULL,
        entry_price REAL NOT NULL, entry_timestamp TEXT NOT NULL,
        cost_basis REAL NOT NULL, stop_price REAL, target_price REAL);
      CREATE TABLE trade_history (id INTEGER PRIMARY KEY AUTOINCREMENT,
        ticker TEXT NOT NULL, order_type TEXT NOT NULL, execution_price REAL NOT NULL,
        shares REAL NOT NULL, position_cost REAL NOT NULL, entry_price REAL,
        realized_pnl_usd REAL, realized_pnl_pct REAL, exit_reason TEXT,
        holding_duration_seconds REAL, portfolio_cash_after REAL NOT NULL, timestamp TEXT NOT NULL);
      CREATE TABLE latest_prices (ticker TEXT PRIMARY KEY, price REAL NOT NULL, updated_at TEXT NOT NULL);
    """)
    con.execute("INSERT INTO portfolio_state VALUES (1,?,?,0,?,?,?)",
               (initial_balance, current_cash, total_realized_pnl_usd, win_count, loss_count))
    for p in positions:
        con.execute("INSERT INTO positions VALUES (?,?,?,?,?,?,?)", p)
    for t in trade_history:
        con.execute("INSERT INTO trade_history (ticker,order_type,execution_price,shares,"
                    "position_cost,entry_price,realized_pnl_usd,realized_pnl_pct,exit_reason,"
                    "holding_duration_seconds,portfolio_cash_after,timestamp) "
                    "VALUES (?,?,?,?,?,?,?,?,?,?,?,?)", t)
    for lp in latest_prices:
        con.execute("INSERT INTO latest_prices VALUES (?,?,?)", lp)
    con.commit()
    con.close()


def _mk_v2_db(path: Path, *, cash, positions=(), trades=()):
    for sfx in ("", "-wal", "-shm"):
        p = Path(str(path) + sfx)
        if p.exists():
            p.unlink()
    con = sqlite3.connect(path)
    con.executescript("""
      CREATE TABLE portfolio (id INTEGER PRIMARY KEY CHECK (id=1), cash REAL NOT NULL);
      CREATE TABLE positions (position_id INTEGER PRIMARY KEY AUTOINCREMENT, episode_id TEXT UNIQUE,
        symbol TEXT, issuer_cik TEXT, strategy_profile TEXT, strategy_version TEXT, status TEXT,
        entry_session TEXT, target_exit_session TEXT, entry_price REAL, shares REAL,
        position_cost REAL, exit_session TEXT, exit_price REAL, realized_pnl_usd REAL,
        realized_pnl_pct REAL, trading_days_held INTEGER, source_meta TEXT, opened_at TEXT, closed_at TEXT);
      CREATE TABLE trades (trade_id INTEGER PRIMARY KEY AUTOINCREMENT, episode_id TEXT, symbol TEXT,
        action TEXT, execution_price REAL, shares REAL, position_cost REAL, entry_price REAL,
        realized_pnl_usd REAL, realized_pnl_pct REAL, trading_days_held INTEGER,
        portfolio_cash_after REAL, executed_at TEXT);
    """)
    con.execute("INSERT INTO portfolio VALUES (1,?)", (cash,))
    for p in positions:
        con.execute("INSERT INTO positions (episode_id,symbol,status,entry_session,"
                    "target_exit_session,entry_price,shares,position_cost,exit_session,exit_price,"
                    "realized_pnl_usd,realized_pnl_pct,trading_days_held,opened_at,closed_at) "
                    "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)", p)
    for t in trades:
        con.execute("INSERT INTO trades (episode_id,symbol,action,execution_price,shares,"
                    "position_cost,realized_pnl_usd,portfolio_cash_after,executed_at) "
                    "VALUES (?,?,?,?,?,?,?,?,?)", t)
    con.commit()
    con.close()


def _empty_home(tmp_path: Path, name: str) -> Path:
    d = tmp_path / name
    d.mkdir(parents=True, exist_ok=True)
    return d


# --------------------------------------------------------------------------- #
# 1. Lane / source separation
# --------------------------------------------------------------------------- #
def test_lane_separation_no_cash_summed(tmp_path):
    home = _empty_home(tmp_path, "home")
    exp = _empty_home(tmp_path, "exp")
    _mk_paper_db(home / "paper_trading.db", initial_balance=10_000, current_cash=10_000)
    _mk_paper_db(exp / "experimental_paper.db", initial_balance=100_000, current_cash=100_000)
    _mk_v2_db(tmp_path / "v2_lane.db", cash=300_000)

    out = build_paper_performance(home=home, exp_home=exp, v2_db=tmp_path / "v2_lane.db",
                                   now=NOW, check_processes=False)
    assert out["lanes"]["original"]["cash"] == 10_000
    assert out["lanes"]["experimental"]["cash"] == 100_000
    assert out["lanes"]["v2"]["cash"] == 300_000
    assert "NEVER summed" in out["cross_lane_note"]
    # Intelligence has no invented paper ledger.
    assert out["lanes"]["intelligence"]["attributable_paper_ledger"] is False


# --------------------------------------------------------------------------- #
# 2. Session vs campaign counts
# --------------------------------------------------------------------------- #
def test_session_vs_campaign_counts(tmp_path):
    home = _empty_home(tmp_path, "home")
    exp = _empty_home(tmp_path, "exp")
    _mk_paper_db(home / "paper_trading.db", initial_balance=10_000, current_cash=10_000)
    _mk_paper_db(
        exp / "experimental_paper.db", initial_balance=100_000, current_cash=97_175.53378397295,
        total_realized_pnl_usd=-324.4662160270568,
        positions=[("SPCX", 16.865960067130683, 148.22755360794068,
                    "2026-09-10T19:29:45.777729+00:00", 2500.0, 144.6133321126302, 152.06332906087238)],
        trade_history=[
            ("VRT", "BUY", 274.55852115631103, 9.105526899952618, 2500.0, None, None, None, None,
             None, 97500.0, "2026-09-09T15:03:34.471751+00:00"),
            ("BLSH", "BUY", 35.238807042121884, 70.9445128778532, 2500.0, None, None, None, None,
             None, 95000.0, "2026-09-09T15:03:34.494263+00:00"),
            ("AMD", "BUY", 505.4163310470581, 4.946417134604285, 2500.0, None, None, None, None,
             None, 92500.0, "2026-09-10T16:51:26.497025+00:00"),
            ("STX", "BUY", 870.9526690979004, 2.8704200454307176, 2500.0, None, None, None, None,
             None, 90000.0, "2026-09-10T18:45:38.413386+00:00"),
            ("SPCX", "BUY", 148.22755360794068, 16.865960067130683, 2500.0, None, None, None, None,
             None, 87500.0, "2026-09-10T19:29:45.777729+00:00"),
            ("VRT", "SELL", 251.0872125, 9.105526899952618, 2500.0, 274.55852115631103,
             -213.71863234713055, -8.548745293885235, "confirmed_bearish", 161416.528249,
             89786.28136765287, "2026-09-11T07:53:51-04:00"),
            ("AMD", "SELL", 503.75403, 4.946417134604285, 2500.0, 505.4163310470581,
             -8.222434382038955, -0.32889737528155755, "confirmed_bearish", 70769.502975,
             92278.05893327083, "2026-09-11T08:30:56-04:00"),
            ("STX", "SELL", 862.10941875, 2.8704200454307176, 2500.0, 870.9526690979004,
             -25.38384306537546, -1.0153537226150167, "confirmed_bearish", 63912.586614,
             94752.67509020546, "2026-09-11T08:30:51-04:00"),
            ("BLSH", "SELL", 34.15145999999999, 70.9445128778532, 2500.0, 35.238807042121884,
             -77.14130623251185, -3.0856522493004834, "confirmed_bearish", 165352.505737,
             97175.53378397295, "2026-09-11T08:59:27-04:00"),
        ],
    )
    _mk_v2_db(tmp_path / "v2_lane.db", cash=300_000)

    out = build_paper_performance(home=home, exp_home=exp, v2_db=tmp_path / "v2_lane.db",
                                   now=NOW, check_processes=False)
    tc = out["lanes"]["experimental"]["trade_counts"]
    # Five entries span Sept 9/10 -- NOT today. Four exits ARE today.
    assert tc["entries_today"] == 0
    assert tc["exits_today"] == 4
    assert tc["entries_campaign_to_date"] == 5
    assert tc["exits_campaign_to_date"] == 4
    assert out["lanes"]["experimental"]["realized_pnl"]["campaign_to_date"] == pytest.approx(-324.4662160270568)


# --------------------------------------------------------------------------- #
# 3. Equity includes open-position value (when a mark is available)
# --------------------------------------------------------------------------- #
def test_equity_includes_marked_open_value(tmp_path):
    home = _empty_home(tmp_path, "home")
    exp = _empty_home(tmp_path, "exp")
    _mk_paper_db(home / "paper_trading.db", initial_balance=10_000, current_cash=10_000,
                latest_prices=[("SPCX", 151.21, "2026-09-11T20:09:20+00:00")])
    _mk_paper_db(
        exp / "experimental_paper.db", initial_balance=100_000, current_cash=97_500.0,
        positions=[("SPCX", 16.865960067130683, 148.22755360794068,
                    "2026-09-10T19:29:45.777729+00:00", 2500.0, 144.6133321126302, 152.06332906087238)],
    )
    _mk_v2_db(tmp_path / "v2_lane.db", cash=300_000)

    out = build_paper_performance(home=home, exp_home=exp, v2_db=tmp_path / "v2_lane.db",
                                   now=NOW, check_processes=False)
    e = out["lanes"]["experimental"]
    assert e["equity"]["status"] == "COMPLETE"
    expected_equity = 97_500.0 + 16.865960067130683 * 151.21
    assert e["equity"]["value"] == pytest.approx(expected_equity, abs=1e-2)
    assert e["equity"]["formula"] == "cash + marked open-position value"
    assert e["open_positions"]["detail"][0]["mark"] == pytest.approx(151.21)
    assert e["open_positions"]["detail"][0]["mark_source"].startswith("paper_trading.db")


# --------------------------------------------------------------------------- #
# 4. Cost handling -- no double deduction, no fabricated fee
# --------------------------------------------------------------------------- #
def test_costs_not_double_deducted(tmp_path):
    home = _empty_home(tmp_path, "home")
    exp = _empty_home(tmp_path, "exp")
    _mk_paper_db(home / "paper_trading.db", initial_balance=10_000, current_cash=10_000)
    _mk_paper_db(exp / "experimental_paper.db", initial_balance=100_000, current_cash=97_500.0)
    _mk_v2_db(tmp_path / "v2_lane.db", cash=300_000)
    out = build_paper_performance(home=home, exp_home=exp, v2_db=tmp_path / "v2_lane.db",
                                   now=NOW, check_processes=False)
    costs = out["lanes"]["experimental"]["costs"]
    # Spread/slippage IS modeled (apply_spread, baked into fill prices);
    # commissions/fees are NOT -- these must stay distinct, never a blanket
    # "everything is unmodeled" claim.
    assert costs["modeled"] is True
    assert "MODELED" in costs["spread_slippage"]
    assert "NOT modelled" in costs["explicit_commissions_fees"]
    assert "NOT" in costs["summary"] and "net of all costs" in costs["summary"]
    v2_costs = out["lanes"]["v2"]["costs"]
    assert v2_costs["modeled"] is False
    assert "NOT modelled" in v2_costs["spread_slippage"]
    # a closed trade's own cost annotation must say the same, never a second deduction
    _mk_paper_db(
        exp / "experimental_paper.db", initial_balance=100_000, current_cash=99_786.28136765287,
        total_realized_pnl_usd=-213.71863234713055,
        trade_history=[
            ("VRT", "BUY", 274.55852115631103, 9.105526899952618, 2500.0, None, None, None, None,
             None, 97500.0, "2026-09-09T15:03:34.471751+00:00"),
            ("VRT", "SELL", 251.0872125, 9.105526899952618, 2500.0, 274.55852115631103,
             -213.71863234713055, -8.548745293885235, "confirmed_bearish", 161416.528249,
             99786.28136765287, "2026-09-11T07:53:51-04:00"),
        ],
    )
    out2 = build_paper_performance(home=home, exp_home=exp, v2_db=tmp_path / "v2_lane.db",
                                    now=NOW, check_processes=False)
    ct = out2["lanes"]["experimental"]["closed_trades"][0]
    assert ct["realized_pnl_usd"] == pytest.approx(-213.71863234713055)
    assert "NOT" in ct["costs"] and "net of all costs" in ct["costs"]
    assert "spread" in ct["costs"].lower()


# --------------------------------------------------------------------------- #
# 5. Missing / stale marks -- never fabricated, never a silent 0
# --------------------------------------------------------------------------- #
def test_missing_mark_reports_unavailable_not_zero(tmp_path):
    home = _empty_home(tmp_path, "home")
    exp = _empty_home(tmp_path, "exp")
    _mk_paper_db(home / "paper_trading.db", initial_balance=10_000, current_cash=10_000)  # no latest_prices row
    _mk_paper_db(
        exp / "experimental_paper.db", initial_balance=100_000, current_cash=97_500.0,
        positions=[("ZZZZ", 10.0, 100.0, "2026-09-10T19:29:45+00:00", 1000.0, 90.0, 110.0)],
    )
    _mk_v2_db(tmp_path / "v2_lane.db", cash=300_000)
    out = build_paper_performance(home=home, exp_home=exp, v2_db=tmp_path / "v2_lane.db",
                                   now=NOW, check_processes=False)
    e = out["lanes"]["experimental"]
    assert e["equity"]["status"] == "PARTIAL"
    assert e["equity"]["value"] is None
    assert e["unrealized_pnl"]["status"].startswith("UNAVAILABLE")
    assert e["unrealized_pnl"]["total"] is None
    det = e["open_positions"]["detail"][0]
    assert det["mark"] is None
    assert det["unrealized_pnl_usd"] is None
    assert "UNAVAILABLE" in det["unrealized_status"]


def test_zero_open_positions_is_a_valid_zero(tmp_path):
    home = _empty_home(tmp_path, "home")
    exp = _empty_home(tmp_path, "exp")
    _mk_paper_db(home / "paper_trading.db", initial_balance=10_000, current_cash=10_000)
    _mk_paper_db(exp / "experimental_paper.db", initial_balance=100_000, current_cash=100_000)
    _mk_v2_db(tmp_path / "v2_lane.db", cash=300_000)
    out = build_paper_performance(home=home, exp_home=exp, v2_db=tmp_path / "v2_lane.db",
                                   now=NOW, check_processes=False)
    v2 = out["lanes"]["v2"]
    assert v2["open_positions"]["count"] == 0
    assert v2["unrealized_pnl"]["status"].startswith("N/A")
    assert v2["equity"]["status"] == "COMPLETE"
    assert v2["equity"]["value"] == 300_000.0


# --------------------------------------------------------------------------- #
# 6. Post-close vs regular-close valuation labelling
# --------------------------------------------------------------------------- #
def test_post_close_mark_labelled_distinctly():
    # SPCX's real mark: 2026-09-11T20:08:00Z, regular close that day is 20:00:00Z.
    cls = classify_valuation_timestamp("2026-09-11T20:08:00+00:00", now=NOW)
    assert cls["classification"] == "POST_CLOSE"
    assert cls["regular_close_utc"] == "2026-09-11T20:00:00+00:00"
    assert "NOT an official regular-session closing price" in cls["note"]


def test_regular_session_mark_labelled_distinctly():
    cls = classify_valuation_timestamp("2026-09-11T15:00:00+00:00", now=NOW)
    assert cls["classification"] == "REGULAR_SESSION"


def test_stale_historical_mark_labelled_distinctly():
    cls = classify_valuation_timestamp("2026-08-13T17:05:00+00:00", now=NOW)
    assert cls["classification"] == "STALE_HISTORICAL"
    assert cls["mark_age_seconds"] is not None and cls["mark_age_seconds"] > 0


def test_unavailable_mark_timestamp():
    cls = classify_valuation_timestamp(None, now=NOW)
    assert cls["classification"] == "UNAVAILABLE"


def test_non_session_day_distinct_from_unavailable():
    # 2026-09-12 is a Saturday.
    cls = classify_valuation_timestamp("2026-09-12T15:00:00+00:00", now=NOW)
    assert cls["classification"] == "NON_SESSION_DAY"
    assert cls["regular_open_utc"] is None and cls["regular_close_utc"] is None


def test_half_day_uses_real_open_not_close_minus_6h30m():
    """Task 119A regression: the post-Thanksgiving half day (2026-11-27)
    closes at 18:00 UTC and opens at 14:30 UTC (a 3.5h session) -- the old
    close-6h30m approximation would have placed the approximated open at
    11:30 UTC, 3 hours too early. A mark at 12:00 UTC (before the REAL
    open) must classify PRE_MARKET, not REGULAR_SESSION."""
    half_day_now = datetime(2026, 11, 27, 19, 0, tzinfo=timezone.utc)
    cls = classify_valuation_timestamp("2026-11-27T12:00:00+00:00", now=half_day_now)
    assert cls["classification"] == "PRE_MARKET"
    assert cls["regular_open_utc"] == "2026-11-27T14:30:00+00:00"
    assert cls["regular_close_utc"] == "2026-11-27T18:00:00+00:00"
    # a mark just after the real (early) close is POST_CLOSE, not REGULAR_SESSION
    cls2 = classify_valuation_timestamp("2026-11-27T18:30:00+00:00", now=half_day_now)
    assert cls2["classification"] == "POST_CLOSE"


def test_dst_winter_open_is_1430_utc():
    cls = classify_valuation_timestamp("2026-11-27T15:00:00+00:00",
                                       now=datetime(2026, 11, 27, 19, 0, tzinfo=timezone.utc))
    assert cls["classification"] == "REGULAR_SESSION"
    assert cls["regular_open_utc"] == "2026-11-27T14:30:00+00:00"


def test_calendar_mechanism_failure_reports_unknown_not_non_session_day(monkeypatch):
    import talonx_signals.market_sessions as ms

    def _boom(_d):
        raise RuntimeError("calendar backend unavailable")

    monkeypatch.setattr(ms, "session_open_utc", _boom)
    monkeypatch.setattr(ms, "session_close_utc", _boom)
    cls = classify_valuation_timestamp("2026-09-11T15:00:00+00:00", now=NOW)
    assert cls["classification"] == "UNKNOWN"
    assert "could not be established" in cls["note"]


# --------------------------------------------------------------------------- #
# 7. Recovery provenance -- tied to explicit evidence, never mutates the row
# --------------------------------------------------------------------------- #
def test_recovery_affected_flag_tied_to_known_ids(tmp_path):
    home = _empty_home(tmp_path, "home")
    exp = _empty_home(tmp_path, "exp")
    _mk_paper_db(home / "paper_trading.db", initial_balance=10_000, current_cash=10_000)
    _mk_paper_db(
        exp / "experimental_paper.db", initial_balance=100_000, current_cash=99_786.28136765287,
        total_realized_pnl_usd=-213.71863234713055,
        trade_history=[
            ("VRT", "BUY", 274.55852115631103, 9.105526899952618, 2500.0, None, None, None, None,
             None, 97500.0, "2026-09-09T15:03:34.471751+00:00"),
            ("VRT", "SELL", 251.0872125, 9.105526899952618, 2500.0, 274.55852115631103,
             -213.71863234713055, -8.548745293885235, "confirmed_bearish", 161416.528249,
             99786.28136765287, "2026-09-11T07:53:51-04:00"),
        ],
    )
    _mk_v2_db(tmp_path / "v2_lane.db", cash=300_000)
    out = build_paper_performance(home=home, exp_home=exp, v2_db=tmp_path / "v2_lane.db",
                                   now=NOW, check_processes=False)
    ct = out["lanes"]["experimental"]["closed_trades"][0]
    # trade_history.id for this single-row fixture is 2 (BUY=1, SELL=2) --
    # NOT in the real production {6,7,8,9} cutoff -- so it must NOT be flagged
    # (proves the flag is tied to the specific evidenced ids, not "any SELL").
    assert ct["trade_history_id"] == 2
    assert ct["recovery_affected"] is False
    assert ct["recovery_affected_reason"] is None
    assert ct["provenance"].startswith("CONFIRMED")


def test_recovery_affected_flag_fires_on_evidenced_ids(tmp_path):
    from talonx_ops.paper_performance import _lane_paper_snapshot

    exp = _empty_home(tmp_path, "exp")
    db = exp / "experimental_paper.db"
    _mk_paper_db(
        db, initial_balance=100_000, current_cash=99_786.28136765287,
        total_realized_pnl_usd=-213.71863234713055,
        trade_history=[
            ("VRT", "BUY", 274.55852115631103, 9.105526899952618, 2500.0, None, None, None, None,
             None, 97500.0, "2026-09-09T15:03:34.471751+00:00"),
            ("VRT", "SELL", 251.0872125, 9.105526899952618, 2500.0, 274.55852115631103,
             -213.71863234713055, -8.548745293885235, "confirmed_bearish", 161416.528249,
             99786.28136765287, "2026-09-11T07:53:51-04:00"),
        ],
    )
    out = _lane_paper_snapshot(
        db, lane="EXPERIMENTAL", strategy_identity="EXPERIMENTAL_RELAXED_V1", attribution="x",
        now=NOW, session_date="2026-09-11", producer_live=False,
        recovery_affected_ids=frozenset({2}), recovery_affected_note=RECOVERY_AFFECTED_EVIDENCE_NOTE,
    )
    ct = out["closed_trades"][0]
    assert ct["recovery_affected"] is True
    assert ct["recovery_affected_reason"] == RECOVERY_AFFECTED_EVIDENCE_NOTE


# --------------------------------------------------------------------------- #
# 8. Reconciliation -- EXACT / MISMATCH / UNAVAILABLE
# --------------------------------------------------------------------------- #
def test_reconciliation_exact(tmp_path):
    home = _empty_home(tmp_path, "home")
    exp = _empty_home(tmp_path, "exp")
    _mk_paper_db(home / "paper_trading.db", initial_balance=10_000, current_cash=10_000)
    _mk_paper_db(exp / "experimental_paper.db", initial_balance=100_000, current_cash=97_175.53378397295,
                total_realized_pnl_usd=-324.4662160270568,
                positions=[("SPCX", 16.865960067130683, 148.22755360794068,
                           "2026-09-10T19:29:45+00:00", 2500.0, 144.61, 152.06)])
    _mk_v2_db(tmp_path / "v2_lane.db", cash=300_000)
    out = build_paper_performance(home=home, exp_home=exp, v2_db=tmp_path / "v2_lane.db",
                                   now=NOW, check_processes=False)
    rc = out["lanes"]["experimental"]["reconciliation"]
    assert rc["status"] == "EXACT"
    assert rc["diff"] == pytest.approx(0.0, abs=1e-4)


def test_reconciliation_mismatch_detected(tmp_path):
    home = _empty_home(tmp_path, "home")
    exp = _empty_home(tmp_path, "exp")
    _mk_paper_db(home / "paper_trading.db", initial_balance=10_000, current_cash=10_000)
    # current_cash deliberately wrong vs initial_balance - open_cost + realized
    _mk_paper_db(exp / "experimental_paper.db", initial_balance=100_000, current_cash=50_000.0,
                total_realized_pnl_usd=-324.47,
                positions=[("SPCX", 16.865960067130683, 148.22755360794068,
                           "2026-09-10T19:29:45+00:00", 2500.0, 144.61, 152.06)])
    _mk_v2_db(tmp_path / "v2_lane.db", cash=300_000)
    out = build_paper_performance(home=home, exp_home=exp, v2_db=tmp_path / "v2_lane.db",
                                   now=NOW, check_processes=False)
    rc = out["lanes"]["experimental"]["reconciliation"]
    assert rc["status"] == "MISMATCH"
    assert abs(rc["diff"]) > 1


def test_reconciliation_unavailable_when_source_missing(tmp_path):
    home = _empty_home(tmp_path, "home")
    exp = _empty_home(tmp_path, "exp")  # experimental_paper.db never created
    _mk_paper_db(home / "paper_trading.db", initial_balance=10_000, current_cash=10_000)
    _mk_v2_db(tmp_path / "v2_lane.db", cash=300_000)
    out = build_paper_performance(home=home, exp_home=exp, v2_db=tmp_path / "v2_lane.db",
                                   now=NOW, check_processes=False)
    e = out["lanes"]["experimental"]
    assert e["status"] == "UNKNOWN"
    assert e["equity"]["status"] == "UNAVAILABLE"
    assert "unavailable" in e["note"].lower()


# --------------------------------------------------------------------------- #
# 9. No production writes / no network sends
# --------------------------------------------------------------------------- #
def test_never_writes_to_source_dbs(tmp_path):
    home = _empty_home(tmp_path, "home")
    exp = _empty_home(tmp_path, "exp")
    _mk_paper_db(home / "paper_trading.db", initial_balance=10_000, current_cash=10_000)
    _mk_paper_db(exp / "experimental_paper.db", initial_balance=100_000, current_cash=100_000)
    _mk_v2_db(tmp_path / "v2_lane.db", cash=300_000)
    before = {
        p: p.stat().st_mtime for p in
        (home / "paper_trading.db", exp / "experimental_paper.db", tmp_path / "v2_lane.db")
    }
    build_paper_performance(home=home, exp_home=exp, v2_db=tmp_path / "v2_lane.db",
                            now=NOW, check_processes=False)
    after = {p: p.stat().st_mtime for p in before}
    assert before == after, "paper_performance() must never modify a source ledger file"


def test_no_network_import_side_effects(tmp_path, monkeypatch):
    """Every socket-capable import path (redis, requests, alpaca, etc.) must
    stay unused by this read-only module -- asserted by simply confirming a
    full build succeeds with sockets blocked."""
    import socket

    def _blocked(*a, **k):
        raise AssertionError("paper_performance() must never open a network socket")

    monkeypatch.setattr(socket, "socket", _blocked)
    home = _empty_home(tmp_path, "home")
    exp = _empty_home(tmp_path, "exp")
    _mk_paper_db(home / "paper_trading.db", initial_balance=10_000, current_cash=10_000)
    _mk_paper_db(exp / "experimental_paper.db", initial_balance=100_000, current_cash=100_000)
    _mk_v2_db(tmp_path / "v2_lane.db", cash=300_000)
    out = build_paper_performance(home=home, exp_home=exp, v2_db=tmp_path / "v2_lane.db",
                                   now=NOW, check_processes=False)
    assert out["lanes"]["original"]["status"] in {"ZERO_ACTIVITY", "NO_ACTIVE_PRODUCER"}


# --------------------------------------------------------------------------- #
# DashboardReadModel wiring
# --------------------------------------------------------------------------- #
def test_dashboard_read_model_exposes_paper_performance(tmp_path, monkeypatch):
    from talonx_ops.dashboard_read import DashboardReadModel

    home = _empty_home(tmp_path, "home")
    exp = _empty_home(tmp_path, "exp")
    _mk_paper_db(home / "paper_trading.db", initial_balance=10_000, current_cash=10_000)
    _mk_paper_db(exp / "experimental_paper.db", initial_balance=100_000, current_cash=100_000)
    v2db = tmp_path / "v2_lane.db"
    _mk_v2_db(v2db, cash=300_000)
    monkeypatch.setenv("TALONX_V2_DB_PATH", str(v2db))

    dr = DashboardReadModel(home=home, exp_home=exp, now=NOW, check_processes=False)
    out = dr.paper_performance()
    assert set(out["lanes"]) >= {"original", "experimental", "v2", "piv", "intelligence"}
    # Task 119A A1: no separate routed "paper_performance" section -- its
    # data is folded into paper_eod() (Original/Experimental/PIV) and
    # v2_active_strategy() (V2), the ONE destination for each lane.
    all_sec = dr.all_sections()
    assert "paper_performance" not in all_sec
    assert set(all_sec) == {"overview", "premarket", "original_quant", "v2_active_strategy",
                            "v2_broad_discovery", "validation", "intelligence", "paper_eod"}
    eod = dr.paper_eod()
    assert eod["original_local_paper"]["performance"]["lane"] == "ORIGINAL"
    assert eod["experimental_validation_paper"]["performance"]["lane"] == "EXPERIMENTAL"
    assert "v2_paper" not in eod  # V2 stays in its own existing destination, not duplicated here
    v2sec = dr.v2_active_strategy()
    assert v2sec["ledger"]["performance"]["lane"] == "V2"
