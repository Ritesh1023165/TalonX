"""
scripts/ticker_funnel_report.py
------------------------------------
Read-only, per-ticker diagnostic report tracing one ticker through the
full TalonX pipeline (ingest -> quant -> brain -> core -> dispatch ->
paper), built entirely from the same persisted SQLite stores and Redis
keys the live app already writes.

Safe to run against a LIVE, running instance: every SQLite connection is
opened read-only (`mode=ro`), so it never triggers a store's own
`_migrate()` (which only runs on a normal read/write connect) and can
never block or corrupt a concurrent writer -- WAL mode is designed for
exactly this multi-reader pattern (same reasoning talonx_dispatch/app.py
already relies on to read the audit trail live). Redis access is
read-only too (GET/SCAN/EXISTS only).

Usage:
    python scripts/ticker_funnel_report.py NVDA
    python scripts/ticker_funnel_report.py NVDA --date 2026-08-14
    python scripts/ticker_funnel_report.py NVDA --history-days 5
"""
from __future__ import annotations

import argparse
import json
import sqlite3
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from talonx_core.config import CoreConfig
from talonx_dispatch.config import DispatchConfig
from talonx_paper.config import PaperConfig
from talonx_quant.config import QuantConfig

try:
    import redis
except ImportError:  # pragma: no cover - optional at report time
    redis = None


def _ro_connect(path: str) -> sqlite3.Connection | None:
    p = Path(path)
    if not p.is_file():
        return None
    conn = sqlite3.connect(f"file:{p.as_posix()}?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row
    return conn


def _section(title: str) -> None:
    print()
    print(f"-- {title} " + "-" * max(0, 60 - len(title)))


def _print_rows(rows: list[dict], empty_msg: str) -> None:
    if not rows:
        print(f"  {empty_msg}")
        return
    for row in rows:
        print(" ", {k: v for k, v in row.items()})


def report_ingest(client, date_str: str) -> None:
    _section("1. INGEST")
    if client is None:
        print("  Redis not reachable -- cannot read telemetry.")
        return
    bars = client.get(f"metrics:{date_str}:ingest:bars_read")
    filings = client.get(f"metrics:{date_str}:ingest:filings_parsed")
    print(f"  System-wide bars read today: {bars or 0}")
    print(f"  System-wide filings parsed today: {filings or 0}")
    print("  (bars_read is a GLOBAL counter, not per-ticker -- talonx_ingest doesn't")
    print("   currently break this down by symbol.)")


def report_quant(conn: sqlite3.Connection | None, ticker: str, date_str: str, history_days: int) -> list[dict]:
    _section("2. QUANT (talonx_quant) -- candidate signals & suppression")
    if conn is None:
        print("  quant.db not found.")
        return []
    rows = [
        dict(r) for r in conn.execute(
            "SELECT date, reason, count, last_seen_at FROM suppression_counts "
            "WHERE ticker = ? AND date >= ? ORDER BY date DESC, last_seen_at DESC",
            (ticker, (datetime.fromisoformat(date_str) - timedelta(days=history_days)).strftime("%Y-%m-%d")),
        ).fetchall()
    ]
    today_rows = [r for r in rows if r["date"] == date_str]
    _print_rows(today_rows, f"No suppressed candidates recorded for {ticker} on {date_str}.")
    if len(rows) > len(today_rows):
        print(f"  ({len(rows) - len(today_rows)} more suppression row(s) in the prior {history_days} day(s) -- history below)")
        _print_rows([r for r in rows if r["date"] != date_str], "")
    return rows


def report_buffer_warmup(conn: sqlite3.Connection | None, ticker: str, quant_config: QuantConfig) -> None:
    """Bar-buffer checkpoint depth (talonx_quant.store's bar_buffer table)
    -- how far each RollingBarBuffer has warmed up for this ticker, and
    how close it is to the threshold that actually unlocks something:
    min_bars_required (120, regular signal evaluation) for the 1-min
    buffer, htf_sma_period (200, the 15-min-200-SMA trend gate) for the
    HTF one. Reads the same checkpoint QuantScanner._checkpoint_all_buffers
    writes every buffer_checkpoint_interval_seconds (default 60s) plus on
    a graceful stop() -- so this can lag the true in-memory buffer by up
    to that interval on a live process, but is otherwise an accurate,
    persisted view (this is exactly what survives a restart)."""
    _section("2b. BUFFER WARM-UP (bar_buffer checkpoint)")
    if conn is None:
        print("  quant.db not found.")
        return

    for buffer_type, threshold, label in (
        ("1m", quant_config.min_bars_required, "regular signal evaluation"),
        ("15m", quant_config.htf_sma_period, "15m-200-SMA trend gate"),
    ):
        row = conn.execute(
            "SELECT COUNT(*) AS n, MIN(ts) AS oldest, MAX(ts) AS newest FROM bar_buffer "
            "WHERE symbol = ? AND buffer_type = ?",
            (ticker, buffer_type),
        ).fetchone()
        count = row["n"] or 0
        if count == 0:
            print(f"  {buffer_type:>3} buffer: 0/{threshold} bars checkpointed -- nothing persisted yet for {label}.")
            continue
        pct = min(100.0, count / threshold * 100.0)
        status = "READY" if count >= threshold else f"warming up ({pct:.0f}%)"
        print(f"  {buffer_type:>3} buffer: {count}/{threshold} bars -- {status} -- unlocks {label}")
        print(f"       oldest checkpointed bar: {row['oldest']}")
        print(f"       newest checkpointed bar: {row['newest']}")


def report_core(conn: sqlite3.Connection | None, ticker: str, date_str: str, history_days: int) -> dict | None:
    _section("3. CORE (talonx_core) -- correlation & decision")
    if conn is None:
        print("  core_state.db not found.")
        return None

    state = conn.execute(
        "SELECT ticker, signal_at, report_at, last_alert_at, last_alert_action, last_alert_price "
        "FROM ticker_state WHERE ticker = ?",
        (ticker,),
    ).fetchone()
    if state is None:
        print(f"  No correlator state at all for {ticker} -- talonx_core has never seen a QuantSignal or ResearchReport for it.")
    else:
        state = dict(state)
        print(f"  Last QuantSignal received (signal_at):   {state['signal_at'] or '—'}")
        print(f"  Last ResearchReport received (report_at): {state['report_at'] or '—'}")
        print(f"  Last dispatched alert (last_alert_at):    {state['last_alert_at'] or '—'}")
        print(f"  Last alert action:                        {state['last_alert_action'] or '—'}")

    since = (datetime.fromisoformat(date_str) - timedelta(days=history_days)).strftime("%Y-%m-%d")
    supp_rows = [
        dict(r) for r in conn.execute(
            "SELECT date, reason, horizon, count, last_seen_at FROM suppression_counts "
            "WHERE ticker = ? AND date >= ? ORDER BY date DESC, last_seen_at DESC",
            (ticker, since),
        ).fetchall()
    ]
    print(f"\n  Decision-matrix suppressions (last {history_days}d):")
    _print_rows(supp_rows, "None -- either no signal/report pairs ever reached the decision matrix, or every pair produced a real alert.")
    return state


def report_dispatch(conn: sqlite3.Connection | None, ticker: str, limit: int = 10) -> list[dict]:
    _section("4. DISPATCH (talonx_dispatch) -- audit trail & Telegram push")
    if conn is None:
        print("  dispatch_audit.db not found.")
        return []
    rows = [
        dict(r) for r in conn.execute(
            "SELECT id, action, severity, research_confidence, telegram_sent, telegram_error, "
            "suppress_reason, correlated_at FROM alerts WHERE ticker = ? ORDER BY id DESC LIMIT ?",
            (ticker, limit),
        ).fetchall()
    ]
    _print_rows(rows, f"No rows for {ticker} in the audit trail (either never correlated into an alert, or the table was reset since).")
    return rows


def report_paper(conn: sqlite3.Connection | None, ticker: str, limit: int = 5) -> None:
    _section("5. PAPER TRADING (talonx_paper)")
    if conn is None:
        print("  paper_trading.db not found.")
        return
    position = conn.execute("SELECT * FROM positions WHERE ticker = ?", (ticker,)).fetchone()
    print(f"  Open position: {dict(position) if position else 'none'}")
    trades = [
        dict(r) for r in conn.execute(
            "SELECT id, order_type, execution_price, shares, realized_pnl_usd, timestamp "
            "FROM trade_history WHERE ticker = ? ORDER BY id DESC LIMIT ?",
            (ticker, limit),
        ).fetchall()
    ]
    print(f"  Recent trades:")
    _print_rows(trades, "  none")
    ignored = [
        dict(r) for r in conn.execute(
            "SELECT reason, triggering_action, price, timestamp FROM ignored_decisions "
            "WHERE ticker = ? ORDER BY id DESC LIMIT ?",
            (ticker, limit),
        ).fetchall()
    ]
    print(f"  Recent ignored decisions:")
    _print_rows(ignored, "  none")


def report_locks(client, ticker: str) -> None:
    _section("6. LIVE LOCKS (Redis)")
    if client is None:
        print("  Redis not reachable.")
        return
    cooldown_ttl = client.ttl(f"cooldown:{ticker}")
    lockout_ttl = client.ttl(f"loss_lockout:{ticker}")
    print(f"  cooldown:{ticker}      -> {'active, ' + str(cooldown_ttl) + 's left' if cooldown_ttl and cooldown_ttl > 0 else 'not set'}")
    print(f"  loss_lockout:{ticker} -> {'active, ' + str(lockout_ttl) + 's left' if lockout_ttl and lockout_ttl > 0 else 'not set'}")


def verdict(quant_rows: list[dict], core_state: dict | None, dispatch_rows: list[dict]) -> None:
    _section("VERDICT")
    if not quant_rows and core_state is None:
        print("  No pipeline activity found for this ticker in the available data at all --")
        print("  check the ticker symbol, or confirm it's actually on the tracked watchlist.")
        return

    if core_state is None or not core_state.get("signal_at"):
        print("  Stalled at QUANT: every candidate for this ticker is being suppressed before")
        print("  a single one is ever published to talonx:signals:quant -- see section 2 for reasons.")
        print("  talonx_brain/talonx_core/talonx_dispatch have nothing to do as a direct result.")
        return

    if not core_state.get("report_at"):
        print("  Reached CORE with a signal, but talonx_brain has never produced a research")
        print("  report for this ticker (or it hasn't arrived yet) -- correlation can't complete.")
        return

    if dispatch_rows:
        latest = dispatch_rows[0]
        if latest["telegram_sent"]:
            print(f"  Reached all the way through: alert #{latest['id']} was pushed to Telegram.")
        else:
            print(f"  Reached DISPATCH: alert #{latest['id']} was recorded but NOT pushed --")
            print(f"  suppress_reason = {latest['suppress_reason']!r}.")
        return

    if core_state.get("last_alert_action"):
        print(f"  CORE actually PUBLISHED a real alert: {core_state['last_alert_action']!r} at")
        print(f"  {core_state['last_alert_at']} -- that's proof it reached talonx:alerts:dispatch.")
        print("  Dispatch's audit trail has no matching row for it, which means either:")
        print("    (a) that alert predates a dispatch_audit.db reset/schema migration, or")
        print("    (b) talonx_dispatch's consumer wasn't running/connected at that moment.")
        print("  This is NOT a quant/core suppression -- the pipeline worked; dispatch's own")
        print("  record of it is just gone or was never received.")
        return

    print("  Signal + report both reached CORE, but core never produced a real alert action")
    print("  (see section 3's decision-matrix suppressions above -- most likely NO_STATE_CHANGE")
    print("  / STALE / a cooldown), so nothing was ever published for dispatch to receive.")


def main() -> None:
    # Windows consoles often default stdout to cp1252, which can't encode
    # some field values (e.g. an em dash in a free-text error message) --
    # reconfigure defensively rather than letting an ordinary print() crash
    # a purely diagnostic, read-only tool.
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except AttributeError:
        pass

    parser = argparse.ArgumentParser(description="Per-ticker TalonX pipeline funnel report (read-only)")
    parser.add_argument("ticker")
    parser.add_argument("--date", default=datetime.now(timezone.utc).strftime("%Y-%m-%d"))
    parser.add_argument("--history-days", type=int, default=3)
    args = parser.parse_args()
    ticker = args.ticker.strip().upper()

    quant_config, core_config, dispatch_config, paper_config = QuantConfig(), CoreConfig(), DispatchConfig(), PaperConfig()

    client = None
    if redis is not None:
        try:
            client = redis.Redis.from_url(quant_config.redis_url, decode_responses=True, socket_connect_timeout=3)
            client.ping()
        except Exception:
            client = None

    print(f"TalonX Pipeline Funnel Report -- {ticker} -- {args.date} (generated {datetime.now(timezone.utc).isoformat()})")

    report_ingest(client, args.date)

    quant_conn = _ro_connect(quant_config.db_path)
    quant_rows = report_quant(quant_conn, ticker, args.date, args.history_days)
    report_buffer_warmup(quant_conn, ticker, quant_config)
    if quant_conn:
        quant_conn.close()

    core_conn = _ro_connect(core_config.state_db_path)
    core_state = report_core(core_conn, ticker, args.date, args.history_days)
    if core_conn:
        core_conn.close()

    dispatch_conn = _ro_connect(dispatch_config.audit_db_path)
    dispatch_rows = report_dispatch(dispatch_conn, ticker)
    if dispatch_conn:
        dispatch_conn.close()

    paper_conn = _ro_connect(paper_config.db_path)
    report_paper(paper_conn, ticker)
    if paper_conn:
        paper_conn.close()

    report_locks(client, ticker)

    verdict(quant_rows, core_state, dispatch_rows)
    print()


if __name__ == "__main__":
    main()
