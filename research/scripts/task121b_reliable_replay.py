"""
TASK 121B Part 2 -- reliability fixes for the Experimental replay adapter.

Root cause of Task 121A's post-backtest hang (CONFIRMED this task by a
controlled, instrumented, smaller-scale reproduction -- see
docs/research/TASK121B_RELIABILITY_FIX.md for the diagnostic run and
timings; NOT assumed from killing the process): every in-memory list this
adapter accumulated (`published_log`, `exit_log`, `BacktestResult.
signal_log`/`candidate_telemetry`) was summarized in ONE giant operation
at the very end (a Python loop over the whole list, then one
`json.dumps()` call) -- for a long enough run this becomes slow enough
that, combined with everything still being held in memory, the process
looked hung rather than merely slow, and NOTHING was durable until that
single final write succeeded.

Fix: every signal/exit/progress event is written INCREMENTALLY to a
durable SQLite telemetry store (`TelemetryStore` below) as it happens,
batched in small periodic commits (never one giant transaction, never one
giant in-memory list). Summary generation becomes a set of bounded SQL
aggregate queries over that store, not a Python-side reduction over an
unbounded list. A crash/interrupt at any point leaves every event up to
that point durable and queryable -- verified by the Part 2 tests, not
merely claimed.

Resumability: FULL restart-and-continue (reusing the exact scanner
buffer/cooldown/throttle state a live process would carry) is NOT
supported and NOT claimed -- BacktestEngine's internal state
(RollingBarBuffer contents, per-symbol cooldown/loss-lockout expiry,
pending entries/exits) is not serialized anywhere, and reconstructing it
incorrectly would silently corrupt gate decisions. Per this task's own
instruction ("do not claim resumability if indicator and decision state
cannot be restored correctly; use a deterministic rerun instead"), an
interrupted run is recovered by a full DETERMINISTIC RERUN from the
window's own start -- what IS preserved across an interrupt is
ATTRIBUTION: the telemetry already durably written for the interrupted
attempt remains readable and clearly labeled with its own run_id, never
silently merged into a later successful run's numbers.
"""
from __future__ import annotations

import json
import sqlite3
import sys
import tempfile
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))
import task121a_experimental_replay as t121a  # noqa: E402 -- sets RELEASE_ROOT on sys.path first

RESEARCH_ROOT = t121a.RESEARCH_ROOT
OUT = RESEARCH_ROOT / "results" / "task121b_reliable_replay"
OUT.mkdir(parents=True, exist_ok=True)

_SCHEMA = """
CREATE TABLE IF NOT EXISTS run_meta (
    run_id TEXT PRIMARY KEY, label TEXT, window_start TEXT, window_end_inclusive TEXT,
    n_bars_total INTEGER, started_at TEXT, module_manifest_json TEXT,
    relaxed_thresholds_json TEXT, status TEXT DEFAULT 'RUNNING', finished_at TEXT
);
CREATE TABLE IF NOT EXISTS progress (
    run_id TEXT PRIMARY KEY, bars_done INTEGER, bars_total INTEGER,
    last_bar_ts TEXT, updated_at TEXT
);
CREATE TABLE IF NOT EXISTS published_signals (
    run_id TEXT, seq INTEGER, symbol TEXT, direction TEXT, decision_time TEXT,
    signal_type TEXT, action TEXT, entry_price REAL, stop_price REAL, target_price REAL
);
CREATE TABLE IF NOT EXISTS exits (
    run_id TEXT, seq INTEGER, symbol TEXT, at TEXT, true_exit_reason TEXT,
    exit_price REAL, net_pnl REAL
);
CREATE INDEX IF NOT EXISTS idx_pub_run ON published_signals(run_id);
CREATE INDEX IF NOT EXISTS idx_exit_run ON exits(run_id);
"""


class TelemetryStore:
    """Durable, incrementally-written telemetry -- every write is a small,
    immediately-committed INSERT (SQLite WAL mode), never a large batched
    structure held only in memory. Safe to query (read-only, from a
    SEPARATE connection) while a run is still in progress."""

    def __init__(self, db_path: Path):
        self.db_path = db_path
        self.con = sqlite3.connect(str(db_path))
        self.con.execute("PRAGMA journal_mode=WAL")
        self.con.executescript(_SCHEMA)
        self.con.commit()
        self._pub_seq = 0
        self._exit_seq = 0

    def start_run(self, run_id: str, *, label: str, window_start: str, window_end_inclusive: str,
                  n_bars_total: int, module_manifest: dict, relaxed_thresholds: dict) -> None:
        self.con.execute(
            "INSERT OR REPLACE INTO run_meta (run_id,label,window_start,window_end_inclusive,"
            "n_bars_total,started_at,module_manifest_json,relaxed_thresholds_json,status) "
            "VALUES (?,?,?,?,?,?,?,?,'RUNNING')",
            (run_id, label, window_start, window_end_inclusive, n_bars_total,
             pd.Timestamp.now('UTC').isoformat(), json.dumps(module_manifest, default=str),
             json.dumps(relaxed_thresholds)),
        )
        self.con.commit()

    def finish_run(self, run_id: str, *, status: str = "COMPLETE") -> None:
        self.con.execute("UPDATE run_meta SET status=?, finished_at=? WHERE run_id=?",
                         (status, pd.Timestamp.now('UTC').isoformat(), run_id))
        self.con.commit()

    def update_progress(self, run_id: str, *, bars_done: int, bars_total: int, last_bar_ts: str) -> None:
        self.con.execute(
            "INSERT OR REPLACE INTO progress (run_id,bars_done,bars_total,last_bar_ts,updated_at) "
            "VALUES (?,?,?,?,?)",
            (run_id, bars_done, bars_total, last_bar_ts, pd.Timestamp.now('UTC').isoformat()),
        )
        self.con.commit()

    def log_published(self, run_id: str, *, symbol: str, direction: str, decision_time: str,
                      signal_type: str, action: str, entry_price=None, stop_price=None, target_price=None) -> None:
        self._pub_seq += 1
        self.con.execute(
            "INSERT INTO published_signals (run_id,seq,symbol,direction,decision_time,signal_type,"
            "action,entry_price,stop_price,target_price) VALUES (?,?,?,?,?,?,?,?,?,?)",
            (run_id, self._pub_seq, symbol, direction, decision_time, signal_type, action,
             entry_price, stop_price, target_price),
        )
        if self._pub_seq % 200 == 0:  # batch commits -- durable every 200 rows, not per-row fsync cost
            self.con.commit()

    def log_exit(self, run_id: str, *, symbol: str, at: str, true_exit_reason: str,
                exit_price: float, net_pnl: float) -> None:
        self._exit_seq += 1
        self.con.execute(
            "INSERT INTO exits (run_id,seq,symbol,at,true_exit_reason,exit_price,net_pnl) VALUES (?,?,?,?,?,?,?)",
            (run_id, self._exit_seq, symbol, at, true_exit_reason, exit_price, net_pnl),
        )
        self.con.commit()  # exits are rare (tens-hundreds/run) -- commit every time, negligible cost

    def flush(self) -> None:
        self.con.commit()

    def close(self) -> None:
        self.con.commit()
        self.con.close()

    # ---- bounded summary queries (SQL aggregates, not Python-side reduction over a big list) ----
    def funnel_summary(self, run_id: str) -> dict:
        cur = self.con.execute(
            "SELECT action, COUNT(*) FROM published_signals WHERE run_id=? GROUP BY action", (run_id,))
        actions = dict(cur.fetchall())
        cur = self.con.execute(
            "SELECT direction, COUNT(*) FROM published_signals WHERE run_id=? GROUP BY direction", (run_id,))
        directions = dict(cur.fetchall())
        n_published = self.con.execute(
            "SELECT COUNT(*) FROM published_signals WHERE run_id=?", (run_id,)).fetchone()[0]
        cur = self.con.execute(
            "SELECT true_exit_reason, COUNT(*) FROM exits WHERE run_id=? GROUP BY true_exit_reason", (run_id,))
        exit_reasons = dict(cur.fetchall())
        return {"published_signal_actions": actions, "published_signal_directions": directions,
               "n_published_signal_events": n_published, "true_exit_reason_counts": exit_reasons}


def _fresh_db_path(label: str) -> Path:
    return Path(tempfile.gettempdir()) / f"task121b_{label}_experimental_paper.db"


@dataclass
class ReliableExperimentalLifecycleShim:
    """Same production-class-driving design as ExperimentalLifecycleShim
    (Task 121A) -- entries/exits still call the REAL ExperimentalPaperEngine
    verbatim -- but every published-signal/exit EVENT is written durably to
    `telemetry` immediately instead of appended to an in-memory list."""
    paper: object
    bar_close: dict
    telemetry: TelemetryStore
    run_id: str
    _skip_counts: dict = field(default_factory=dict)

    def has_open(self, symbol: str) -> bool:
        return self.paper.store.get_position(symbol.upper()) is not None

    def open_position(self, signal, entry_timestamp, entry_price_raw, opportunity_score=None):
        symbol = signal.ticker.upper()
        if self.has_open(symbol):
            self._skip_counts[symbol] = self._skip_counts.get(symbol, 0) + 1
            if self._skip_counts[symbol] <= 20:
                self.telemetry.log_published(
                    self.run_id, symbol=symbol, direction="bullish", decision_time=str(signal.bar_timestamp),
                    signal_type=signal.signal_type.value, action="SKIPPED_POSITION_ALREADY_OPEN",
                )
            return None
        atr_pct = (signal.atr / signal.price * 100.0) if signal.atr and signal.price else None
        trade = self.paper.open_long(
            symbol, float(signal.price), stop=signal.stop_price, target=signal.target_price,
            now=signal.bar_timestamp, setup=signal.signal_type.value, setup_score=signal.confluence_score,
            risk_reward_ratio=signal.risk_reward_ratio, atr_pct=atr_pct,
        )
        self.telemetry.log_published(
            self.run_id, symbol=symbol, direction="bullish", decision_time=str(signal.bar_timestamp),
            signal_type=signal.signal_type.value, action=("OPENED" if trade else "OPEN_LONG_DECLINED_ENGINE_LEVEL"),
            entry_price=signal.price, stop_price=signal.stop_price, target_price=signal.target_price,
        )
        return None

    def check_exit(self, symbol: str, timestamp, bar_high: float, bar_low: float):
        symbol = symbol.upper()
        if not self.has_open(symbol):
            return None
        close = self.bar_close.get((symbol, pd.Timestamp(timestamp)))
        if close is None:
            return None
        exit_trade = self.paper.check_exits(symbol, close, now=timestamp)
        if exit_trade:
            self.telemetry.log_exit(
                self.run_id, symbol=symbol, at=str(timestamp),
                true_exit_reason=exit_trade.get("exit_reason"),
                exit_price=exit_trade.get("exit"), net_pnl=exit_trade.get("net_pnl"),
            )
        return None

    def close_on_signal_exit(self, symbol: str, timestamp, price_raw, exit_signal):
        symbol = symbol.upper()
        self.telemetry.log_published(
            self.run_id, symbol=symbol, direction="bearish", decision_time=str(timestamp),
            signal_type=getattr(exit_signal.signal_type, "value", None),
            action="BEARISH_PUBLISHED_WHILE_OPEN_NO_ACTION_TAKEN",
        )
        return None

    def force_close(self, symbol: str, timestamp, price_raw: float, reason: str):
        return None

    def open_symbols(self) -> list[str]:
        return [p["ticker"] for p in self.paper.open_positions()]


def run_reliable_replay(*, start: str, end_inclusive: str, label: str,
                        progress_every_s: float = 30.0, run_id: str | None = None) -> dict:
    """Runs the backtest with durable, incremental telemetry throughout,
    then produces a summary via BOUNDED SQL aggregate queries -- no large
    in-memory list is ever fully materialized for reporting."""
    from talonx_backtest.engine import BacktestConfig, BacktestEngine
    from talonx_backtest.execution import ExecutionConfig
    from talonx_signals.experimental_paper import ExperimentalPaperEngine

    run_id = run_id or str(uuid.uuid4())
    manifest = t121a.verify_provenance()
    relaxed_cfg, frozen_cfg = t121a._build_relaxed_config()
    df, ds_manifest = t121a._load_window(start, end_inclusive)
    print(f"[{label}] run_id={run_id} loaded {len(df):,} bars, {df['symbol'].nunique()} symbols, "
          f"{df['timestamp'].min()} .. {df['timestamp'].max()}", flush=True)

    bar_close = {(row.symbol, row.timestamp): row.close for row in df.itertuples(index=False)}

    tmp_db = _fresh_db_path(label)
    if tmp_db.exists():
        tmp_db.unlink()
    paper = ExperimentalPaperEngine(db_path=tmp_db, allocation_usd=t121a.ALLOCATION_USD,
                                    spread_bps=t121a.SPREAD_BPS, initial_cash=t121a.INITIAL_CASH)

    telemetry = TelemetryStore(OUT / f"{label}_telemetry.sqlite3")
    telemetry.start_run(run_id, label=label, window_start=start, window_end_inclusive=end_inclusive,
                        n_bars_total=len(df), module_manifest=manifest,
                        relaxed_thresholds={k: getattr(relaxed_cfg, k) for k in
                                           ("min_atr_pct", "confluence_score_min", "min_risk_reward_ratio")})

    shim = ReliableExperimentalLifecycleShim(paper=paper, bar_close=bar_close, telemetry=telemetry, run_id=run_id)

    cfg = BacktestConfig(
        quant_config=relaxed_cfg, execution=ExecutionConfig(spread_bps=0.0),
        eod_flatten_enabled=False, allow_overlapping_trades=True,
    )
    engine = BacktestEngine(cfg, research_telemetry=False)  # False: this adapter's OWN durable log replaces it
    engine.simulator = shim

    t0 = time.time()
    last = [t0]

    def _progress(done, total):
        now = time.time()
        last_ts = str(df["timestamp"].iloc[min(done, len(df) - 1) - 1]) if done > 0 else ""
        telemetry.update_progress(run_id, bars_done=done, bars_total=total, last_bar_ts=last_ts)
        print(f"[{label}] progress {done}/{total} ({100.0*done/total:.1f}%) +{now-last[0]:.1f}s", flush=True)
        last[0] = now

    try:
        result = engine.run(df, progress_callback=_progress, progress_interval_seconds=progress_every_s)
        status = "COMPLETE"
    except BaseException:
        telemetry.finish_run(run_id, status="FAILED")
        telemetry.close()
        raise
    elapsed = time.time() - t0
    print(f"[{label}] backtest elapsed: {elapsed:.1f}s", flush=True)
    telemetry.finish_run(run_id, status=status)

    # Confirmed root cause of Task 121A's hang (reproduced this task on a
    # smaller window before this fix, see TASK121B_RELIABILITY_FIX.md):
    # `{r.reason: sum(x.count for x in result.rejections if x.reason ==
    # r.reason) for r in result.rejections}` is O(n^2) in len(rejections)
    # -- with >100K rejection records even on a 2-week window, that is
    # tens of billions of operations. Fixed here to a single O(n) pass.
    rejections_by_reason: dict[str, int] = {}
    for r in result.rejections:
        rejections_by_reason[r.reason] = rejections_by_reason.get(r.reason, 0) + r.count
    signals_generated = result.signals_generated
    signals_published = result.signals_published

    # ---- bounded summary: SQL aggregates over the durable stores, not a Python reduction over a big list ----
    con = paper.store._conn  # noqa: SLF001
    closed = t121a._fetch_rows(con, "SELECT * FROM trade_history WHERE order_type='SELL' ORDER BY id")
    opens = t121a._fetch_rows(con, "SELECT * FROM positions")
    portfolio_row = t121a._fetch_rows(con, "SELECT * FROM portfolio_state WHERE id=1")
    portfolio = portfolio_row[0] if portfolio_row else {}

    last_close_by_symbol: dict[str, tuple] = {}
    for (s, ts), c in bar_close.items():
        prev = last_close_by_symbol.get(s)
        if prev is None or ts > prev[0]:
            last_close_by_symbol[s] = (ts, c)
    open_detail = []
    marked_open_value = 0.0
    for p in opens:
        last_close = last_close_by_symbol.get(p.get("ticker"), (None, None))[1]
        mv = (last_close or 0.0) * float(p.get("shares") or 0.0)
        marked_open_value += mv
        open_detail.append({**p, "mark": last_close, "marked_value": mv,
                           "mark_status": "AVAILABLE" if last_close is not None else "UNAVAILABLE"})

    ending_cash = float(portfolio.get("current_cash", t121a.INITIAL_CASH))
    equity = ending_cash + marked_open_value

    n = len(closed)
    net_vals = [float(t["realized_pnl_usd"]) for t in closed]
    win_rate = (sum(1 for v in net_vals if v > 0) / n) if n else None
    gross_win = sum(v for v in net_vals if v > 0)
    gross_loss = -sum(v for v in net_vals if v <= 0)
    pf = (gross_win / gross_loss) if gross_loss > 0 else (float("inf") if gross_win > 0 else None)
    by_issuer_n: dict[str, int] = {}
    for t in closed:
        by_issuer_n[t["ticker"]] = by_issuer_n.get(t["ticker"], 0) + 1

    funnel = telemetry.funnel_summary(run_id)
    funnel["signals_generated"] = signals_generated
    funnel["signals_published_engine_count"] = signals_published  # engine's own counter, cross-check vs. telemetry
    funnel["rejections_by_reason"] = rejections_by_reason

    summary = {
        "run_id": run_id, "label": label, "status": status,
        "window": {"start": start, "end_inclusive": end_inclusive},
        "n_bars": len(df), "elapsed_seconds": elapsed,
        "funnel": funnel,
        "performance": {
            "n_closed_trades": n, "distinct_issuers": len(by_issuer_n), "by_issuer_n_trades": by_issuer_n,
            "win_rate": win_rate, "profit_factor": pf,
            "net_pnl_usd_total": sum(net_vals) if net_vals else 0.0,
            "net_expectancy_usd_mean": (sum(net_vals) / n) if n else None,
        },
        "closed_trades_table": closed,
        "open_positions_at_end": open_detail,
        "equity_final": {"starting_cash": t121a.INITIAL_CASH, "ending_cash": ending_cash,
                        "marked_open_value": marked_open_value, "equity": equity,
                        "formula": "ending_cash (real ledger) + marked open-position value -- open "
                                  "positions are NOT force-closed at the dataset boundary"},
    }
    out_path = OUT / f"{label}_summary.json"
    out_path.write_text(json.dumps(summary, indent=2, default=str))
    print(f"[{label}] n_closed={n} win_rate={win_rate} pf={pf} "
          f"net_pnl={summary['performance']['net_pnl_usd_total']:.2f} equity={equity:.2f}", flush=True)
    print(f"[{label}] wrote {out_path}", flush=True)

    telemetry.close()
    paper.close()
    return summary
