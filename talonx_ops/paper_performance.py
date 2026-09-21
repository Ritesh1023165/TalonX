"""talonx_ops.paper_performance -- Task 119.

A read-ONLY, per-lane paper-performance surface built strictly on top of the
existing Task 100A/B authoritative sources (``talonx_paper.store``'s shared
schema for Original/Experimental, ``v2_lane.db`` for V2). This module does
NOT duplicate ``AuthoritativeReadModel``/``DashboardReadModel`` -- it answers
the one question they deliberately leave shallow: "what did each lane's
paper portfolio actually earn/lose, what remains open, and does the ledger
reconcile?" (Task 118H, Option 3 / ``PRODUCT_REQUIREMENTS_AND_NEXT_DECISION.md``).

Design constraints (binding, from Task 119's own instructions):

* Every store is opened ``file:...?mode=ro`` -- this module physically
  cannot write to a production ledger.
* Original and Experimental paper portfolios share ONE schema
  (``talonx_paper.store``'s ``portfolio_state`` / ``positions`` /
  ``trade_history`` / ``latest_prices``) -- one internal helper serves both,
  parameterised only by db path + lane label, so there is exactly one
  accounting implementation to get right.
* Marks come from ``latest_prices`` in the SAME db as the lane being priced
  (each lane's own db carries its own ``latest_prices`` table, written by
  that lane's own price-feed consumer) -- reused verbatim, never
  recomputed, never silently substituted with another lane's mark.
* Equity is ALWAYS ``cash + marked open-position value`` (Task 119 Part 2).
  If any open position lacks a usable mark, equity for that lane is reported
  as ``PARTIAL`` (the known-good cash-only floor is still shown, clearly
  labelled), never silently computed with a fabricated zero mark.
* Reconciliation is an *arithmetic* check against the ledger's own numbers,
  not a copied summary string: ``expected_cash = initial_balance -
  sum(open cost_basis) + total_realized_pnl_usd``, compared to the ledger's
  actual ``current_cash``.
* No fee/commission/slippage is modelled anywhere in ``talonx_paper.engine``
  (grepped, confirmed absent) -- costs are reported as ``UNMODELED``, not as
  a fabricated zero baked silently into P&L.
* "Recovery-affected" is a derived annotation tied to explicit, dated
  evidence (docs/research/SESSION_2026-09-11_OUTCOMES.md, Task 118A fix
  c88f4d4) -- never inferred from the mere absence of a flag, never mutating
  the underlying ``trade_history`` row.
"""
from __future__ import annotations

import sqlite3
from datetime import date as _date
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

# --------------------------------------------------------------------------- #
# Recovery-affected evidence (Task 118A / Task 118H) -- explicit, sourced,
# non-mutating. These are the exact trade_history.id values of the four
# 2026-09-11 Experimental SELL rows that were the FIRST-EVER exits to
# complete through the Task 118A exit-lifecycle fix (deployed release commit
# c88f4d4); before that fix the Experimental exit path never recorded a
# completed SELL. A future session's exits get new, higher ids and are NOT
# flagged -- the exit mechanism is treated as proven from this point forward,
# per docs/research/SESSION_2026-09-11_OUTCOMES.md and
# docs/research/SESSION_2026-09-11_FINAL.md.
RECOVERY_AFFECTED_EXPERIMENTAL_TRADE_IDS: frozenset[int] = frozenset({6, 7, 8, 9})
RECOVERY_AFFECTED_EVIDENCE_NOTE = (
    "First-ever Experimental exits to complete through the Task118A "
    "exit-lifecycle fix (release commit c88f4d4, 2026-09-11); before that "
    "fix the Experimental exit path never recorded a completed SELL. Not "
    "pooled with a clean track record. See "
    "docs/research/SESSION_2026-09-11_OUTCOMES.md."
)

# --------------------------------------------------------------------------- #
# Administrative-adjustment isolation (Task 131 Remediation Directive 5).
# A one-time, backed-up, idempotent migration
# (scripts/migrations/task131_close_stranded_spcx.py) administratively
# closed a stranded SPCX position at its own entry price (zero fabricated
# P&L, no market outcome invented) -- this is NOT a trading decision or
# outcome and must never be counted as one. The existing trade_history
# schema already carries a distinguishing marker for it (`exit_reason`),
# so no new column/migration is introduced; this prefix convention lets
# any FUTURE administrative closure be tagged and excluded the same way.
# `portfolio_state.win_count`/`loss_count`/`total_realized_pnl_usd` were
# deliberately NOT incremented by that migration, so the PRIMARY
# get_portfolio_summary()-style win-rate is already unaffected -- this
# constant closes the SEPARATE, real gap found in THIS module: the
# per-trade `closed_trades`/`trade_counts` breakdown below scans
# trade_history directly and would otherwise display/count that row as
# if it were a real trade.
ADMINISTRATIVE_ADJUSTMENT_EXIT_REASON_PREFIX = "administrative_"

# --------------------------------------------------------------------------- #
# Cost treatment (Task 119A A2 correction) -- Task 119 originally labelled
# every lane's costs "UNMODELED," which was WRONG for Original/Experimental:
# talonx_paper/engine.py's apply_spread() DOES simulate a bid-ask spread
# (talonx_paper/config.py's simulated_spread_bps, default 5.0 bps / 0.05% per
# side -- a BUY pays half the spread more, a SELL receives half the spread
# less) and it is applied to EVERY fill (talonx_paper/consumer.py), baked
# directly into the stored entry_price/execution_price -- confirmed by
# reading the source, not asserted from memory. What is genuinely NOT
# modelled is an explicit flat commission (deliberately -- most modern
# retail brokers are commission-free, per that module's own docstring) and
# any market-impact/size-dependent slippage beyond the fixed bps spread.
# V2 (talonx_v2/paper.py) applies NO spread adjustment at all -- entry_price/
# exit_price are used exactly as passed in from the pricing adapter -- so
# V2's figures are the most "optimistic" of the three lanes (zero simulated
# friction of any kind), a materially different and more meaningful
# distinction than a blanket "UNMODELED" label for every lane alike.
_TALONX_PAPER_COST_BREAKDOWN = {
    "spread_slippage": ("MODELED -- talonx_paper.engine.apply_spread(), default "
                        "simulated_spread_bps=5.0 (0.05%) per side, applied to EVERY "
                        "fill and baked into the stored entry_price/execution_price "
                        "(not a separate line item; the exact bps in force at the time "
                        "of an individual historical trade is not itself recorded per-row)"),
    "explicit_commissions_fees": ("NOT modelled -- deliberate (assumes a commission-free "
                                  "retail broker, per talonx_paper/config.py's own docstring)"),
    "additional_modeled_costs": "none (no market-impact, financing, or borrow cost modelled)",
    "unmodeled_costs": ("commissions/fees; any market-impact/size-dependent slippage beyond "
                        "the fixed bid-ask spread"),
    "summary": ("Realized P&L is net of the simulated bid-ask spread (already reflected in "
               "the stored fill prices) but gross of commissions (assumed zero) and any "
               "size-dependent slippage -- NOT \"net of all costs.\""),
    "unrealized_caveat": ("cost_basis already reflects the entry-side spread; the current "
                          "mark is a raw quote with no exit-side spread applied -- an actual "
                          "exit right now would cross the spread again and realize slightly "
                          "less than this mark-to-market figure. Not commission-adjusted."),
    "modeled": True,
}
_V2_COST_BREAKDOWN = {
    "spread_slippage": "NOT modelled/calibrated; quoted fills",
    "explicit_commissions_fees": "Persisted entry_fee and exit_fee where recorded; default zero",
    "additional_modeled_costs": "none",
    "unmodeled_costs": "market impact and uncalibrated spread/slippage",
    "summary": "Realized P&L = exit net minus persisted entry total, including recorded fees. Costs remain uncalibrated.",
    "modeled": True,
}


def _ro(path: Path) -> sqlite3.Connection | None:
    if not Path(path).exists():
        return None
    try:
        con = sqlite3.connect(f"file:{path}?mode=ro", uri=True, timeout=1.0)
        con.row_factory = sqlite3.Row
        return con
    except sqlite3.Error:
        return None


def _q1(con: sqlite3.Connection, sql: str, args: tuple = ()) -> Any:
    try:
        row = con.execute(sql, args).fetchone()
        return row[0] if row is not None else None
    except sqlite3.Error:
        return None


def _qall(con: sqlite3.Connection, sql: str, args: tuple = ()) -> list[sqlite3.Row]:
    try:
        return list(con.execute(sql, args).fetchall())
    except sqlite3.Error:
        return []


def _has_table(con: sqlite3.Connection, name: str) -> bool:
    return _q1(con, "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (name,)) == 1


def _parse_ts(ts: str | None) -> datetime | None:
    if not ts:
        return None
    try:
        dt = datetime.fromisoformat(str(ts).replace("Z", "+00:00"))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(timezone.utc)
    except Exception:  # noqa: BLE001
        return None


def _age_seconds(ts: str | None, now: datetime) -> float | None:
    dt = _parse_ts(ts)
    if dt is None:
        return None
    return (now - dt).total_seconds()


def classify_valuation_timestamp(ts: str | None, *, now: datetime) -> dict[str, Any]:
    """Session classification for a price mark's timestamp.

    Task 119A correction: uses BOTH
    ``talonx_signals.market_sessions.session_open_utc`` AND
    ``session_close_utc`` -- the SAME exchange_calendars-backed instants
    already authoritative elsewhere in this repo (Task 99G forward-outcome
    resolution) -- for the session boundary, instead of Task 119's
    ``close - 6h30m`` approximation. That approximation is correct on a
    full session but WRONG on an early-close (half) day (e.g. the
    post-Thanksgiving half day is a 3.5h session, not 6.5h) -- fixed here
    by reading the real open, which is also correctly DST-aware.

    Distinguishes ``NON_SESSION_DAY`` (the calendar affirmatively says
    ``ts``'s date is not a trading day -- a weekend/holiday, independently
    confirmed via ``talonx_v2.calendar.is_session``, an established fact)
    from ``UNKNOWN`` (the calendar mechanism itself could not be consulted
    -- e.g. ``exchange_calendars`` unavailable/raised) -- per this task's
    own instruction: "If session classification cannot be established,
    show UNKNOWN," never silently folded into NON_SESSION_DAY.

    Naive (tz-less) timestamps: every timestamp actually written by this
    repo's paper-trading stores carries an explicit UTC offset (confirmed
    by reading the real ledger schema/values) -- a naive string is treated
    as UTC by ``_parse_ts`` purely as a defensive fallback, not because
    that is a verified source contract for any producer.
    """
    dt = _parse_ts(ts)
    if dt is None:
        return {"classification": "UNAVAILABLE", "mark_timestamp": None, "mark_age_seconds": None,
                "session_date": None, "regular_open_utc": None, "regular_close_utc": None}
    age = (now - dt).total_seconds()
    d = dt.date()
    try:
        from talonx_v2.calendar import is_session as _is_session
        affirmed_non_session = not _is_session(d)
    except Exception:  # noqa: BLE001
        affirmed_non_session = None  # the independent check itself failed -- can't affirm either way
    try:
        from talonx_signals.market_sessions import session_open_utc, session_close_utc
        open_ = session_open_utc(d)
        close = session_close_utc(d)
        calendar_failed = False
    except Exception:  # noqa: BLE001
        open_ = close = None
        calendar_failed = True

    if calendar_failed:
        classification = "UNKNOWN"
    elif close is None or open_ is None:
        # market_sessions agrees no session exists for this date.
        classification = "NON_SESSION_DAY" if affirmed_non_session is not False else "UNKNOWN"
    elif dt < open_:
        classification = "PRE_MARKET"
    elif dt <= close:
        classification = "REGULAR_SESSION"
    else:
        classification = "POST_CLOSE"

    is_today = d == now.astimezone(timezone.utc).date()
    if not is_today and classification in ("PRE_MARKET", "REGULAR_SESSION", "POST_CLOSE"):
        classification = "STALE_HISTORICAL"
    return {
        "classification": classification,
        "mark_timestamp": dt.isoformat(),
        "mark_age_seconds": round(age, 1),
        "session_date": d.isoformat(),
        "regular_open_utc": open_.isoformat() if open_ else None,
        "regular_close_utc": close.isoformat() if close else None,
        "note": ("post-close mark -- NOT an official regular-session closing price"
                 if classification == "POST_CLOSE" else
                 "historical mark from a prior calendar day" if classification == "STALE_HISTORICAL"
                 else "not a valid NYSE trading day" if classification == "NON_SESSION_DAY"
                 else "session classification could not be established" if classification == "UNKNOWN"
                 else None),
    }


def _load_marks(db_path: Path) -> dict[str, tuple[Any, Any]]:
    con = _ro(Path(db_path))
    if con is None:
        return {}
    try:
        if not _has_table(con, "latest_prices"):
            return {}
        return {r["ticker"]: (r["price"], r["updated_at"])
                for r in _qall(con, "SELECT ticker, price, updated_at FROM latest_prices")}
    finally:
        con.close()


def _unknown_lane_stub(lane: str, strategy_identity: str, attribution: str, note: str) -> dict[str, Any]:
    """A fully-shaped stub (every top-level key any caller might read is
    present, each explicitly UNAVAILABLE/UNKNOWN) for a lane whose source db
    could not be read at all -- never a partially-shaped dict that silently
    KeyErrors a downstream reader, and never a plausible-looking 0."""
    return {
        "lane": lane, "strategy_identity": strategy_identity, "attribution": attribution,
        "status": "UNKNOWN", "note": note,
        "period": {"as_of_date": None, "campaign_start": None, "campaign_start_basis": note},
        "starting_capital": {"amount": None, "accounting_period": None},
        "cash": None,
        "open_positions": {"count": None, "cost_basis_total": None, "marked_value_total": None,
                          "marked_value_status": "UNAVAILABLE", "detail": []},
        "closed_trades": [],
        "trade_counts": {"entries_today": None, "exits_today": None,
                        "entries_campaign_to_date": None, "exits_campaign_to_date": None},
        "realized_pnl": {"campaign_to_date": None, "source": note},
        "unrealized_pnl": {"total": None, "status": "UNAVAILABLE"},
        "costs": {"modeled": False, "note": "UNAVAILABLE -- source ledger unreadable"},
        "equity": {"value": None, "status": "UNAVAILABLE", "formula": "cash + marked open-position value",
                  "note": note},
        "reconciliation": {"status": "UNAVAILABLE", "expected_cash": None, "actual_cash": None,
                          "diff": None, "basis": note},
    }


def _lane_paper_snapshot(
    db_path: Path,
    *,
    lane: str,
    strategy_identity: str,
    attribution: str,
    now: datetime,
    session_date: str,
    producer_live: bool,
    recovery_affected_ids: frozenset[int] = frozenset(),
    recovery_affected_note: str = "",
    fallback_marks_db: Path | None = None,
) -> dict[str, Any]:
    con = _ro(db_path)
    if con is None:
        return _unknown_lane_stub(lane, strategy_identity, attribution,
                                  f"{Path(db_path).name} unavailable")
    try:
        if not _has_table(con, "portfolio_state"):
            return _unknown_lane_stub(lane, strategy_identity, attribution, "no portfolio_state table")
        ps = _qall(con, "SELECT initial_balance, current_cash, total_realized_pnl_usd, "
                        "win_count, loss_count FROM portfolio_state WHERE id=1")
        if not ps:
            return _unknown_lane_stub(lane, strategy_identity, attribution, "portfolio_state has no row")
        row = ps[0]
        initial_balance = row["initial_balance"]
        current_cash = row["current_cash"]
        total_realized = row["total_realized_pnl_usd"]

        opens = _qall(con, "SELECT ticker, shares, entry_price, entry_timestamp, cost_basis, "
                           "stop_price, target_price FROM positions ORDER BY entry_timestamp")
        open_cost_total = sum((r["cost_basis"] or 0.0) for r in opens)

        first_trade_at = _q1(con, "SELECT MIN(timestamp) FROM trade_history") if _has_table(con, "trade_history") else None

        own_marks = {r["ticker"]: (r["price"], r["updated_at"])
                    for r in _qall(con, "SELECT ticker, price, updated_at FROM latest_prices")} \
            if _has_table(con, "latest_prices") else {}
        fallback_marks: dict[str, tuple[Any, Any]] = (
            _load_marks(fallback_marks_db) if fallback_marks_db is not None else {})

        open_detail: list[dict[str, Any]] = []
        marked_value_total = 0.0
        marked_value_complete = True
        unrealized_total = 0.0
        for r in opens:
            sym = r["ticker"]
            mark_px, mark_ts = own_marks.get(sym, (None, None))
            mark_source_db = db_path
            if mark_px is None and sym in fallback_marks:
                mark_px, mark_ts = fallback_marks[sym]
                mark_source_db = fallback_marks_db
            cls = classify_valuation_timestamp(mark_ts, now=now)
            entry = {
                "symbol": sym, "lane": lane,
                "entry_time": r["entry_timestamp"], "quantity": r["shares"],
                "entry_price": r["entry_price"], "cost_basis": r["cost_basis"],
                "stop_price": r["stop_price"], "target_price": r["target_price"],
                "mark": mark_px, "mark_timestamp": cls["mark_timestamp"],
                "mark_source": (f"{Path(mark_source_db).name}.latest_prices"
                                + ("" if mark_source_db == db_path else
                                   " (shared quant price feed -- this lane's own db carries no "
                                   "latest_prices row for this symbol)")
                                if mark_px is not None else None),
                "mark_session_classification": cls["classification"],
                "mark_age_seconds": cls["mark_age_seconds"],
                "mark_note": cls.get("note"),
            }
            if mark_px is None:
                marked_value_complete = False
                entry["marked_value"] = None
                entry["unrealized_pnl_usd"] = None
                entry["unrealized_pnl_pct"] = None
                entry["unrealized_status"] = "UNAVAILABLE -- no usable mark for this symbol"
            else:
                mv = (r["shares"] or 0.0) * mark_px
                upnl = mv - (r["cost_basis"] or 0.0)
                marked_value_total += mv
                unrealized_total += upnl
                entry["marked_value"] = round(mv, 4)
                entry["unrealized_pnl_usd"] = round(upnl, 4)
                entry["unrealized_pnl_pct"] = (round((upnl / r["cost_basis"]) * 100, 4)
                                               if r["cost_basis"] else None)
                entry["unrealized_status"] = _TALONX_PAPER_COST_BREAKDOWN["unrealized_caveat"]
            entry["last_exit_evaluation"] = {
                "status": "NOT_TRACKED",
                "note": ("no dedicated exit-evaluation log exists; the mark timestamp above is "
                         "evidence a fresh price was available for a check, not confirmation one ran"),
            }
            entry["pending_exit_obligation"] = (
                f"open until stop ${r['stop_price']:.4f} or target ${r['target_price']:.4f} is "
                f"crossed, per existing paper exit policy" if r["stop_price"] and r["target_price"]
                else "open position, exit policy thresholds not recorded on this row")
            open_detail.append(entry)

        all_sell_rows = _qall(con, "SELECT id, ticker, order_type, execution_price, shares, position_cost, "
                                   "entry_price, realized_pnl_usd, realized_pnl_pct, exit_reason, "
                                   "holding_duration_seconds, portfolio_cash_after, timestamp "
                                   "FROM trade_history WHERE order_type='SELL' ORDER BY id") \
            if _has_table(con, "trade_history") else []
        # Task 131 Remediation Directive 5: an administrative closure (see
        # ADMINISTRATIVE_ADJUSTMENT_EXIT_REASON_PREFIX above) is not a
        # trading outcome -- excluded from closed/sells/realized_sum_check
        # below, but never silently dropped: reported separately, in full.
        closed = [r for r in all_sell_rows
                 if not str(r["exit_reason"] or "").startswith(ADMINISTRATIVE_ADJUSTMENT_EXIT_REASON_PREFIX)]
        administrative_adjustments = [
            {"symbol": r["ticker"], "trade_history_id": r["id"], "exit_reason": r["exit_reason"],
             "realized_pnl_usd": r["realized_pnl_usd"], "timestamp": r["timestamp"],
             "note": "administrative adjustment -- excluded from trading performance metrics "
                    "(win rate, profit factor, net expectancy, trade counts)"}
            for r in all_sell_rows
            if str(r["exit_reason"] or "").startswith(ADMINISTRATIVE_ADJUSTMENT_EXIT_REASON_PREFIX)
        ]
        closed_detail = []
        realized_sum_check = 0.0
        for r in closed:
            recovery = int(r["id"]) in recovery_affected_ids
            realized_sum_check += (r["realized_pnl_usd"] or 0.0)
            closed_detail.append({
                "symbol": r["ticker"], "lane": lane, "trade_history_id": r["id"],
                "entry_price": r["entry_price"], "exit_price": r["execution_price"],
                "quantity": r["shares"], "cost_basis": r["position_cost"],
                "realized_pnl_usd": r["realized_pnl_usd"], "realized_pnl_pct": r["realized_pnl_pct"],
                "exit_reason": r["exit_reason"],
                "exit_event_time": r["timestamp"],
                "processing_time": None,  # this ledger records one timestamp per trade row; no
                                          # separately materially-different processing time exists
                "holding_duration_seconds": r["holding_duration_seconds"],
                "recovery_affected": recovery,
                "recovery_affected_reason": recovery_affected_note if recovery else None,
                "provenance": "CONFIRMED -- talonx_paper.store.trade_history (authoritative ledger row)",
                "costs": _TALONX_PAPER_COST_BREAKDOWN["summary"],
            })

        buys = _qall(con, "SELECT ticker, timestamp FROM trade_history WHERE order_type='BUY'") \
            if _has_table(con, "trade_history") else []
        sells = closed
        entries_today = sum(1 for r in buys if (_parse_ts(r["timestamp"]) or now).date().isoformat() == session_date)
        exits_today = sum(1 for r in sells if (_parse_ts(r["timestamp"]) or now).date().isoformat() == session_date)

        expected_cash = None
        recon_status = "UNAVAILABLE"
        recon_diff = None
        if initial_balance is not None and total_realized is not None:
            expected_cash = initial_balance - open_cost_total + total_realized
            recon_diff = round((current_cash or 0.0) - expected_cash, 6)
            recon_status = "EXACT" if abs(recon_diff) < 1e-4 else "MISMATCH"
        realized_row_diff = round((total_realized or 0.0) - realized_sum_check, 6) if closed else 0.0

        equity_status = "COMPLETE" if marked_value_complete else ("PARTIAL" if opens else "COMPLETE")
        equity_value = (current_cash or 0.0) + marked_value_total if marked_value_complete or not opens else None

        status = "ACTIVE" if (opens or closed) else ("ZERO_ACTIVITY" if producer_live else "NO_ACTIVE_PRODUCER")

        return {
            "lane": lane, "strategy_identity": strategy_identity, "attribution": attribution,
            "status": status,
            "period": {
                "as_of_date": session_date,
                "campaign_start": first_trade_at,
                "campaign_start_basis": ("first recorded trade_history entry" if first_trade_at
                                         else "no trades recorded yet -- start date not fabricated"),
            },
            "starting_capital": {"amount": initial_balance,
                                 "accounting_period": "campaign inception (ledger initial_balance, "
                                                       "never re-derived from current cash)"},
            "cash": current_cash,
            "open_positions": {
                "count": len(opens), "cost_basis_total": round(open_cost_total, 4),
                "marked_value_total": round(marked_value_total, 4) if marked_value_complete else None,
                "marked_value_status": "COMPLETE" if marked_value_complete else "PARTIAL -- one or more open positions have no usable mark",
                "detail": open_detail,
            },
            "closed_trades": closed_detail,
            # Task 131 Remediation Directive 5: administrative closures
            # (e.g. the SPCX stranded-position cleanup) are NEVER counted
            # as trading outcomes above -- reported separately here,
            # never silently discarded.
            "administrative_adjustments": administrative_adjustments,
            "trade_counts": {
                "entries_today": entries_today, "exits_today": exits_today,
                "entries_campaign_to_date": len(buys), "exits_campaign_to_date": len(sells),
            },
            "realized_pnl": {
                "campaign_to_date": total_realized,
                "source": "portfolio_state.total_realized_pnl_usd",
                "row_sum_cross_check": round(realized_sum_check, 6) if closed else None,
                "row_sum_diff": realized_row_diff if closed else None,
            },
            "unrealized_pnl": {
                "total": (0.0 if not opens else
                          round(unrealized_total, 4) if marked_value_complete else None),
                "status": ("N/A -- zero open positions (a valid 0)" if not opens else
                           "COMPLETE" if marked_value_complete else
                           "UNAVAILABLE -- unavailable, not an empty profitable portfolio"),
            },
            "costs": dict(_TALONX_PAPER_COST_BREAKDOWN),
            "equity": {
                "value": round(equity_value, 4) if equity_value is not None else None,
                "status": equity_status,
                "formula": "cash + marked open-position value",
                "note": None if equity_status == "COMPLETE" else
                        "one or more open positions lack a usable mark -- equity is PARTIAL, not fabricated",
            },
            "reconciliation": {
                "status": recon_status,
                "expected_cash": round(expected_cash, 4) if expected_cash is not None else None,
                "actual_cash": current_cash,
                "diff": recon_diff,
                "basis": "expected_cash = initial_balance - open_position_cost_basis_total + "
                         "total_realized_pnl_usd",
            },
            "note": ("producer live -- flat book (0 open positions)" if (producer_live and not opens and not closed)
                     else ("producer not running" if not producer_live and not opens and not closed else "")),
        }
    finally:
        con.close()


def _v2_snapshot(v2_db: Path, *, now: datetime, session_date: str,
                 price_source_db: Path | None) -> dict[str, Any]:
    con = _ro(v2_db)
    if con is None:
        return _unknown_lane_stub("V2", "INSIDER_BUY_CLUSTER_V2@1",
                                  "V2 / multi-day insider-cluster paper campaign",
                                  "v2_lane.db unavailable")
    try:
        cash = _q1(con, "SELECT cash FROM portfolio WHERE id=1") if _has_table(con, "portfolio") else None
        opens = _qall(con, "SELECT position_id, symbol, episode_id, entry_session, target_exit_session, "
                           "entry_price, shares, position_cost, opened_at FROM positions WHERE status='OPEN'") \
            if _has_table(con, "positions") else []
        closed = _qall(con, "SELECT symbol, episode_id, entry_session, exit_session, entry_price, "
                            "exit_price, shares, position_cost, realized_pnl_usd, realized_pnl_pct, "
                            "trading_days_held, opened_at, closed_at FROM positions WHERE status='CLOSED'") \
            if _has_table(con, "positions") else []
        unresolved_rows = _qall(con, "SELECT symbol, episode_id, entry_session, entry_price, "
                                     "shares, position_cost, opened_at FROM positions "
                                     "WHERE status='EXIT_UNRESOLVED'") \
            if _has_table(con, "positions") else []
        unresolved = len(unresolved_rows)

        open_cost_total = sum((r["position_cost"] or 0.0) for r in opens)
        # Package 1 Settlement Integrity: an EXIT_UNRESOLVED position's
        # cost was debited at entry and never returned -- it must be
        # included wherever "money currently tied up in a position" is
        # computed, or the expected-cash/equity figures below silently
        # omit a real, outstanding obligation.
        unresolved_cost_total = sum((r["position_cost"] or 0.0) for r in unresolved_rows)
        realized_total = round(sum((r["realized_pnl_usd"] or 0.0) for r in closed), 4)

        marks: dict[str, tuple[Any, Any]] = {}
        if price_source_db and Path(price_source_db).exists():
            pcon = _ro(Path(price_source_db))
            if pcon is not None:
                try:
                    if _has_table(pcon, "latest_prices"):
                        marks = {r["ticker"]: (r["price"], r["updated_at"])
                                 for r in _qall(pcon, "SELECT ticker, price, updated_at FROM latest_prices")}
                finally:
                    pcon.close()

        open_detail = []
        marked_value_total = 0.0
        marked_value_complete = True
        unrealized_total = 0.0
        # PQ-2A: economic (post-corporate-action) quantity, read-only; positions
        # with no APPLIED action fall back to their entry shares unchanged.
        try:
            from talonx_v2.corporate_actions import effective_shares_map
            eff_map = effective_shares_map(con)
        except Exception:  # noqa: BLE001
            eff_map = {}
        for r in opens:
            sym = r["symbol"]
            mark_px, mark_ts = marks.get(sym, (None, None))
            cls = classify_valuation_timestamp(mark_ts, now=now)
            entry = {
                "symbol": sym, "lane": "V2", "episode_id": r["episode_id"],
                "entry_time": r["opened_at"], "entry_session": r["entry_session"],
                "planned_exit_session": r["target_exit_session"],
                "quantity": eff_map.get(r["position_id"], r["shares"]),
                "entry_quantity": r["shares"],
                "entry_price": r["entry_price"], "cost_basis": r["position_cost"],
                "mark": mark_px, "mark_timestamp": cls["mark_timestamp"],
                "mark_source": (f"{Path(price_source_db).name}.latest_prices (shared quant feed; "
                                "V2 has no per-lane latest_prices table of its own)" if mark_px is not None else None),
                "mark_session_classification": cls["classification"], "mark_age_seconds": cls["mark_age_seconds"],
                "mark_note": cls.get("note"),
                "pending_exit_obligation": f"held for up to 10 trading sessions; planned exit session "
                                          f"{r['target_exit_session']}, no EOD forced flatten",
                "last_exit_evaluation": {"status": "NOT_TRACKED",
                                         "note": "V2 evaluates exits on its own multi-day tick cadence; "
                                                 "no dedicated per-position exit-check log surfaced here"},
            }
            if mark_px is None:
                marked_value_complete = False
                entry["marked_value"] = None
                entry["unrealized_pnl_usd"] = None
                entry["unrealized_status"] = "UNAVAILABLE -- no usable mark for this symbol"
            else:
                mv = (eff_map.get(r["position_id"], r["shares"]) or 0.0) * mark_px
                upnl = mv - (r["position_cost"] or 0.0)
                marked_value_total += mv
                unrealized_total += upnl
                entry["marked_value"] = round(mv, 4)
                entry["unrealized_pnl_usd"] = round(upnl, 4)
                entry["unrealized_status"] = _V2_COST_BREAKDOWN["summary"]
            open_detail.append(entry)

        closed_detail = [{
            "symbol": r["symbol"], "lane": "V2", "episode_id": r["episode_id"],
            "entry_time": r["opened_at"], "exit_time": r["closed_at"],
            "entry_session": r["entry_session"], "exit_session": r["exit_session"],
            "quantity": r["shares"], "entry_price": r["entry_price"], "exit_price": r["exit_price"],
            "cost_basis": r["position_cost"], "realized_pnl_usd": r["realized_pnl_usd"],
            "realized_pnl_pct": r["realized_pnl_pct"], "trading_days_held": r["trading_days_held"],
            "exit_reason": "10-trading-day hold horizon (frozen V2 contract)",
            "recovery_affected": False, "recovery_affected_reason": None,
            "provenance": "CONFIRMED -- v2_lane.db.positions (authoritative campaign ledger row)",
            "costs": _V2_COST_BREAKDOWN["summary"],
        } for r in closed]

        buy_count = _q1(con, "SELECT COUNT(*) FROM trades WHERE action='BUY'") if _has_table(con, "trades") else 0
        sell_count = _q1(con, "SELECT COUNT(*) FROM trades WHERE action='SELL'") if _has_table(con, "trades") else 0
        buys_today = _q1(con, "SELECT COUNT(*) FROM trades WHERE action='BUY' AND substr(executed_at,1,10)=?",
                         (session_date,)) if _has_table(con, "trades") else 0
        sells_today = _q1(con, "SELECT COUNT(*) FROM trades WHERE action='SELL' AND substr(executed_at,1,10)=?",
                          (session_date,)) if _has_table(con, "trades") else 0

        campaign_rows = _qall(con, "SELECT * FROM campaign WHERE id=1") if _has_table(con, "campaign") else []
        campaign = dict(campaign_rows[0]) if campaign_rows else {}
        starting_campaign_cash = campaign.get("starting_cash_usd")
        expected_cash = (starting_campaign_cash - open_cost_total - unresolved_cost_total + realized_total
                         if starting_campaign_cash is not None else None)
        recon_diff = round((cash or 0.0) - expected_cash, 4) if cash is not None and expected_cash is not None else None
        recon_status = ("EXACT" if recon_diff is not None and abs(recon_diff) < 1e-2 else
                        "MISMATCH" if recon_diff is not None else "UNAVAILABLE")

        # Package 1 Settlement Integrity: an EXIT_UNRESOLVED position's
        # value is by definition unknown (that is why it is unresolved)
        # -- equity can never be COMPLETE while one exists, even if
        # `opens` (OPEN-only) happens to be empty. The old `if opens
        # else COMPLETE` fallback vacuously reported COMPLETE cash-only
        # equity whenever every open position was actually
        # EXIT_UNRESOLVED (zero OPEN rows to iterate, so the loop above
        # never ran and `marked_value_complete` stayed at its default
        # True) -- silently discarding the unresolved obligation.
        has_unresolved = bool(unresolved_rows)
        equity_status = "COMPLETE" if (marked_value_complete and not has_unresolved) else "PARTIAL"
        equity_value = ((cash or 0.0) + marked_value_total
                        if (marked_value_complete and not has_unresolved) and cash is not None
                        else None)

        status = "ACTIVE" if (opens or closed or unresolved_rows) else "ZERO_ACTIVITY"

        return {
            "lane": "V2", "strategy_identity": "INSIDER_BUY_CLUSTER_V2@1",
            "attribution": "V2 / multi-day insider-cluster paper campaign (Original-flow, not Experimental)",
            "status": status,
            "period": {"as_of_date": session_date, "campaign_start": campaign.get("created_at_utc"),
                      "campaign_start_basis": campaign.get("provenance", "UNKNOWN_LEGACY")},
            "starting_capital": {"amount": starting_campaign_cash,
                                 "accounting_period": "persisted campaign inception; unknown for legacy"},
            "cash": cash,
            "open_positions": {"count": len(opens), "cost_basis_total": round(open_cost_total, 4),
                              "marked_value_total": round(marked_value_total, 4) if marked_value_complete else None,
                              "marked_value_status": "COMPLETE" if marked_value_complete else
                                                    "PARTIAL -- one or more open positions have no usable mark",
                              "detail": open_detail},
            "closed_trades": closed_detail,
            "trade_counts": {"entries_today": buys_today or 0, "exits_today": sells_today or 0,
                            "entries_campaign_to_date": buy_count or 0, "exits_campaign_to_date": sell_count or 0},
            "realized_pnl": {"campaign_to_date": realized_total, "source": "v2_lane.db.positions (status=CLOSED)"},
            "unrealized_pnl": {"total": (0.0 if not opens else
                                        round(unrealized_total, 4) if marked_value_complete else None),
                              "status": ("N/A -- zero open positions (a valid 0)" if not opens else
                                        "COMPLETE" if marked_value_complete else
                                        "UNAVAILABLE -- unavailable, not an empty profitable portfolio")},
            "costs": dict(_V2_COST_BREAKDOWN),
            "equity": {"value": round(equity_value, 4) if equity_value is not None else None,
                      "status": equity_status, "formula": "cash + marked open-position value",
                      "note": None if equity_status == "COMPLETE" else
                              ("one or more EXIT_UNRESOLVED positions have unknown value -- "
                               "equity is PARTIAL" if has_unresolved else
                               "one or more open positions lack a usable mark -- equity is PARTIAL")},
            "reconciliation": {"status": recon_status,
                              "expected_cash": round(expected_cash, 4) if expected_cash is not None else None,
                              "actual_cash": cash, "diff": recon_diff,
                              "basis": "expected_cash = persisted starting_campaign_cash - "
                                       "open_position_cost_basis_total - "
                                       "exit_unresolved_cost_basis_total + "
                                       "realized_pnl_campaign_to_date"},
            "exit_unresolved": int(unresolved or 0),
            "exit_unresolved_cost_basis_total": round(unresolved_cost_total, 4),
            "note": "" if (opens or closed) else "producer/flat book -- 0 natural insider clusters entered to date",
        }
    finally:
        con.close()


def build_v2_paper_performance(
    v2_db: Path, *, home: Path | None = None, now: datetime | None = None,
) -> dict[str, Any]:
    """Public entrypoint for V2's richer accounting alone -- used by
    ``v2_active_strategy()`` (Task 119A A1) so V2's equity/reconciliation/
    cost breakdown is folded into its ONE existing destination (the Active
    V2 tab's campaign-ledger card) rather than duplicated on a second tab.
    ``home`` (Original's ``~/.talonx``, for the shared ``latest_prices``
    mark fallback) is optional -- without it, marks come only from
    ``v2_db``'s own tables (which has none), so unrealized P&L reads
    UNAVAILABLE rather than silently using a different, uncontrolled
    source.
    """
    now = now or datetime.now(timezone.utc)
    session_date = now.astimezone(timezone.utc).date().isoformat()
    price_source = (Path(home) / "paper_trading.db") if home is not None else None
    return _v2_snapshot(Path(v2_db), now=now, session_date=session_date, price_source_db=price_source)


def build_paper_performance(
    *,
    home: Path,
    exp_home: Path,
    v2_db: Path,
    now: datetime | None = None,
    check_processes: bool = True,
) -> dict[str, Any]:
    """The Task 119 per-lane paper-performance snapshot.

    ``home`` -- Original's ``~/.talonx`` (or a fixture copy of it).
    ``exp_home`` -- Experimental's ``~/.talonx/experimental`` (or a fixture
    copy).
    ``v2_db`` -- the V2 campaign ledger path.
    """
    now = now or datetime.now(timezone.utc)
    session_date = now.astimezone(timezone.utc).date().isoformat()

    try:
        from talonx_ops.authoritative_read_model import AuthoritativeReadModel
        arm = AuthoritativeReadModel(home=home, exp_home=exp_home, now=now,
                                     check_processes=check_processes)
        orig_live = arm.original_producer()["live"]
        exp_live = arm.experimental_producer()["live"]
    except Exception:  # noqa: BLE001
        orig_live = exp_live = False

    original = _lane_paper_snapshot(
        Path(home) / "paper_trading.db", lane="ORIGINAL", strategy_identity="ORIGINAL_INTRADAY_V1",
        attribution="ORIGINAL / local-only (no broker)", now=now, session_date=session_date,
        producer_live=orig_live,
    )
    experimental = _lane_paper_snapshot(
        Path(exp_home) / "experimental_paper.db", lane="EXPERIMENTAL",
        strategy_identity="EXPERIMENTAL_RELAXED_V1",
        attribution="EXPERIMENTAL / validation-only, simulated, no real capital", now=now,
        session_date=session_date, producer_live=exp_live,
        recovery_affected_ids=RECOVERY_AFFECTED_EXPERIMENTAL_TRADE_IDS,
        recovery_affected_note=RECOVERY_AFFECTED_EVIDENCE_NOTE,
        fallback_marks_db=Path(home) / "paper_trading.db",
    )
    v2 = _v2_snapshot(Path(v2_db), now=now, session_date=session_date,
                      price_source_db=Path(home) / "paper_trading.db")

    try:
        from talonx_signals.market_sessions import session_close_utc
        regular_close = session_close_utc(now.astimezone(timezone.utc).date())
    except Exception:  # noqa: BLE001
        regular_close = None

    return {
        "generated_utc": now.isoformat(),
        "session_date": session_date,
        "regular_session_close_utc": regular_close.isoformat() if regular_close else None,
        "cross_lane_note": ("Original / Experimental / V2 are INDEPENDENT ledgers with independent "
                            "cash pools. Their cash balances are NEVER summed into one investable "
                            "account -- each lane's equity is reported separately."),
        "lanes": {
            "original": original,
            "experimental": experimental,
            "v2": v2,
            "piv": {
                "lane": "PIV", "strategy_identity": "PIV_ALPACA_PAPER",
                "attribution": "PIV / Alpaca PAPER (independent; structurally cannot route real capital)",
                "status": "NOT_CHECKED",
                "attributable_paper_ledger": True,
                "note": "a read-only settings/position check would require a network call to Alpaca's "
                        "paper endpoint, which this read-only surface does not perform; an inactive "
                        "PIV is not a failure of local paper trading (separately labelled).",
                "equity": {"value": None, "status": "NOT_CHECKED"},
            },
            "intelligence": {
                "lane": "INTELLIGENCE", "attributable_paper_ledger": False,
                "note": "Intelligence (Task 96A-H) is informational activity -- filings/earnings/insider "
                        "significance cards delivered to Telegram. It has no attributable paper trading "
                        "ledger and none is invented here.",
            },
        },
    }
