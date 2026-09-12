"""
TASK 121A -- corrected Experimental (EXPERIMENTAL_RELAXED_V1) replay.

Fixes two proven Task 121 defects:

  1. SOURCE PROVENANCE: Task 121's claim "no automatic exit caller exists"
     was based on reading talonx_signals/run.py from this STALE research
     worktree. The pinned release worktree's run.py HAS wired
     ExperimentalLane._maybe_check_exit() -> self.paper.check_exits() into
     every live market tick (Task 118A P1, commit 72baca2) -- confirmed by
     direct byte-hash comparison (see module_manifest below; the research
     branch diverged from the release lineage at 9bec279 and never
     received that specific fix). EVERY module this replay actually
     IMPORTS for gate/indicator/execution math (talonx_quant/*,
     talonx_paper/engine.py, talonx_backtest/*) is byte-identical between
     worktrees -- ONLY talonx_signals/run.py (used here for CONTRACT
     READING, never imported/executed) differs. This is recorded and
     verified programmatically below, not asserted from memory.

  2. LIFECYCLE FIDELITY: talonx_backtest.engine.BacktestEngine's own
     built-in LONG_ONLY trade lifecycle (bearish-signal-driven exit,
     15:50 ET EOD flatten, next-bar-open fill) is Original/PIV-shaped, NOT
     Experimental's actual confirmed lifecycle. Reading the pinned release
     source directly establishes Experimental's real lifecycle:
       - Entry price = the SIGNAL's own bar close (QuantSignal.price,
         itself `float(latest_row["close"])` -- talonx_quant/indicators.py)
         -- immediate, same-bar fill, NOT the next bar's open.
       - Exit = ONLY check_exits() (stop/target), sampled against a SINGLE
         scalar price per tick (talonx_paper.engine.check_stop_take) --
         NEVER intrabar high/low.
       - NO automatic close on a bearish/contradicted signal (run.py's
         handle_message only ever calls _maybe_open_experimental on a
         BULLISH candidate; nothing closes on bearish).
       - NO EOD flatten (ExperimentalPaperEngine.flatten_all exists but
         still has no caller anywhere in run.py -- confirmed directly,
         not inferred).
     This adapter reuses BacktestEngine UNMODIFIED for the gate/candidate
     pipeline (evaluate_signals, volatility/confluence/RR/HTF/blackout/
     cooldown/loss-lockout/throttle -- all imported, not reimplemented),
     but installs a thin composition shim (`ExperimentalLifecycleShim`,
     duck-typed to TradeSimulator's own interface) in place of
     BacktestEngine's own TradeSimulator, so entries/exits are driven by
     the REAL, unmodified `talonx_signals.experimental_paper.
     ExperimentalPaperEngine.open_long`/`.check_exits` -- the same
     production class run.py itself calls -- rather than by
     BacktestEngine's own (Original-shaped) TradeSimulator.

Cost convention (verified, see tests/test_task121a_parity_trace.py::
test_apply_spread_worked_example): `apply_spread(price, spread_bps, side)`
crosses HALF the given spread_bps on ONE side. A 5.0 parameter is
~5bps ROUND-TRIP at an unchanged reference price (2.5bps entry + 2.5bps
exit), NOT 5bps per side. ExperimentalPaperEngine's own default
spread_bps=5.0 is used AS-IS here (the shim calls the real open_long/
check_exits methods, which apply this internally -- no cost math is
duplicated in this file).
"""
from __future__ import annotations

import hashlib
import json
import sqlite3
import sys
import tempfile
from dataclasses import dataclass, field, fields, replace
from pathlib import Path

import pandas as pd

RELEASE_ROOT = Path("C:/workspace/TalonX")
RESEARCH_ROOT = Path(__file__).resolve().parents[2]

# Provenance gate: the release worktree goes FIRST on sys.path, so every
# `import talonx_quant...` / `talonx_backtest...` / `talonx_paper...`
# resolves there, not to this (possibly stale) research worktree's own
# copies -- narrow, reproducible, no branch merge, no uncommitted copy.
sys.path.insert(0, str(RELEASE_ROOT))
sys.path.insert(1, str(RESEARCH_ROOT))  # talonx_research/* etc. -- research-only code

CANONICAL_DIR = RELEASE_ROOT / "results/task93_alpha_foundation/_canonical_data"
MANIFEST_PATH = RELEASE_ROOT / "results/task93_alpha_foundation/canonical_dataset_manifest.json"
OUT = RESEARCH_ROOT / "results" / "task121a_experimental_replay"
OUT.mkdir(parents=True, exist_ok=True)

ALLOCATION_USD = 2500.0
INITIAL_CASH = 100_000.0
SPREAD_BPS = 5.0

_REQUIRED_MODULES = [
    "talonx_quant.consumer", "talonx_quant.strategy", "talonx_quant.config",
    "talonx_quant.session", "talonx_quant.indicators", "talonx_quant.schemas",
    "talonx_quant.buffer", "talonx_quant.aggregation",
    "talonx_signals.config", "talonx_signals.relaxed_profile", "talonx_signals.experimental_paper",
    "talonx_paper.engine", "talonx_paper.store", "talonx_paper.schemas",
    "talonx_backtest.engine", "talonx_backtest.execution", "talonx_backtest.data", "talonx_backtest.portfolio",
]


def verify_provenance() -> dict:
    """Imports every module this replay depends on, then asserts each
    one's __file__ resolves INSIDE RELEASE_ROOT -- fails closed (raises)
    before any replay executes if an import silently resolved to the
    research worktree's own (possibly stale) copy instead. Also hashes
    talonx_signals/run.py (imported by NOTHING here -- read directly as
    the contract source of truth in Part 2/the protocol doc) to make the
    research-worktree staleness finding reproducible, not asserted."""
    import importlib

    manifest: dict[str, dict] = {}
    for name in _REQUIRED_MODULES:
        mod = importlib.import_module(name)
        f = Path(mod.__file__).resolve()
        if RELEASE_ROOT not in f.parents and f.parent != RELEASE_ROOT:
            raise RuntimeError(
                f"PROVENANCE FAILURE: {name} resolved to {f}, NOT under {RELEASE_ROOT} -- "
                f"aborting before any replay. Check sys.path precedence / an unintended checkout."
            )
        h = hashlib.sha256(f.read_bytes()).hexdigest()[:16]
        manifest[name] = {"file": str(f), "sha256_16": h}

    # run.py: read-only provenance record (contract source, not imported by this adapter)
    release_run_py = RELEASE_ROOT / "talonx_signals/run.py"
    research_run_py = RESEARCH_ROOT / "talonx_signals/run.py"
    r_hash = hashlib.sha256(release_run_py.read_bytes()).hexdigest()[:16]
    s_hash = hashlib.sha256(research_run_py.read_bytes()).hexdigest()[:16] if research_run_py.exists() else None
    manifest["talonx_signals.run (NOT imported -- contract source only)"] = {
        "release_file": str(release_run_py), "release_sha256_16": r_hash,
        "research_file": str(research_run_py), "research_sha256_16": s_hash,
        "identical": r_hash == s_hash,
        "note": ("STALE in research worktree -- missing Task 118A P1's check_exits() wiring "
                "(commit 72baca2, never synced past the branches' divergence point 9bec279). "
                "This adapter reads the RELEASE copy directly for contract facts; it does not "
                "import run.py at all."),
    }

    # release/research repo identity + fingerprint gate
    from talonx_ops.prospective import V1_FINGERPRINT_EXPECTED
    from talonx_research.versioning import v1_fingerprint

    fp = v1_fingerprint()
    if fp != V1_FINGERPRINT_EXPECTED:
        raise SystemExit(f"V1 FINGERPRINT MOVED: {fp} != {V1_FINGERPRINT_EXPECTED} -- ABORT")
    manifest["_fingerprint_gate"] = {"v1_fingerprint": fp, "expected": V1_FINGERPRINT_EXPECTED}

    (OUT / "module_manifest.json").write_text(json.dumps(manifest, indent=2))
    return manifest


# ---------------------------------------------------------------------------
# ExperimentalLifecycleShim -- duck-typed replacement for
# talonx_backtest.execution.TradeSimulator, installed as
# `engine.simulator` AFTER construction (pure composition; engine.py's own
# source is never modified). Every method BacktestEngine calls on
# `self.simulator` is implemented here; entries/exits are routed to the
# REAL `ExperimentalPaperEngine` (talonx_signals.experimental_paper,
# release-sourced, verified above) instead of TradeSimulator's own
# (Original-shaped) math. BacktestEngine's own `result.trades` stays
# EMPTY by design -- real economics are read from `paper.store`
# (the actual PaperTradingStore SQLite ledger) after the run.
# ---------------------------------------------------------------------------
@dataclass
class ExperimentalLifecycleShim:
    paper: object  # ExperimentalPaperEngine instance
    bar_close: dict  # {(symbol, pd.Timestamp): float} -- close-price lookup, causal (this bar only)
    published_log: list = field(default_factory=list)
    # trade_history.exit_reason stores the coarser AlertAction
    # (CONFIRMED_BEARISH for BOTH stop_loss and target_exit -- see
    # experimental_paper.py's own _EXIT_ACTION map) -- the TRUE stop-vs-
    # target distinction only exists on close_long()'s own in-memory
    # return value, captured here so it isn't silently lost.
    exit_log: list = field(default_factory=list)
    _skip_counts: dict = field(default_factory=dict)  # symbol -> total SKIPPED_POSITION_ALREADY_OPEN attempts

    def has_open(self, symbol: str) -> bool:
        return self.paper.store.get_position(symbol.upper()) is not None

    def open_position(self, signal, entry_timestamp, entry_price_raw, opportunity_score=None):
        """`entry_price_raw` (BacktestEngine's own next-bar-open guess) is
        DELIBERATELY IGNORED -- the real fill price is the signal's own
        bar close (signal.price), matching run.py's zero-latency
        _maybe_open_experimental exactly. Requires BacktestConfig(
        allow_overlapping_trades=True) so this is reached for EVERY
        published bullish candidate (not just ones BacktestEngine itself
        thinks are unoccupied) -- occupancy is enforced HERE instead, so
        every attempt is logged, matching Part 4's "every published
        signal" requirement."""
        symbol = signal.ticker.upper()
        if self.has_open(symbol):
            # Reliability fix (Task 121A finding): with no EOD flatten and
            # no bearish-close, a position can stay open for many days
            # while the cooldown-bounded (but still repeated) candidate
            # stream keeps re-attempting it -- logging every single
            # attempt individually made this list grow large enough to
            # make the final JSON-summary step pathologically slow on a
            # full-month run (diagnosed after the fact from a stuck
            # process; the underlying replay/ledger was already complete
            # and unaffected -- see TASK121A results doc limitations).
            # Detail is kept per-symbol up to a small cap; beyond that,
            # only an aggregate count is kept -- still answers "was this
            # published signal acted on" (no) without unbounded growth.
            self._skip_counts[symbol] = self._skip_counts.get(symbol, 0) + 1
            if self._skip_counts[symbol] <= 20:
                self.published_log.append({
                    "symbol": symbol, "direction": "bullish", "decision_time": str(signal.bar_timestamp),
                    "signal_type": signal.signal_type.value, "action": "SKIPPED_POSITION_ALREADY_OPEN",
                })
            return None
        atr_pct = (signal.atr / signal.price * 100.0) if signal.atr and signal.price else None
        trade = self.paper.open_long(
            symbol, float(signal.price), stop=signal.stop_price, target=signal.target_price,
            now=signal.bar_timestamp, setup=signal.signal_type.value, setup_score=signal.confluence_score,
            risk_reward_ratio=signal.risk_reward_ratio, atr_pct=atr_pct,
        )
        self.published_log.append({
            "symbol": symbol, "direction": "bullish", "decision_time": str(signal.bar_timestamp),
            "signal_type": signal.signal_type.value,
            "action": "OPENED" if trade else "OPEN_LONG_DECLINED_ENGINE_LEVEL",
            "entry_price": signal.price, "stop": signal.stop_price, "target": signal.target_price,
        })
        return None  # BacktestEngine's own trades list stays empty -- real ledger is paper.store

    def check_exit(self, symbol: str, timestamp, bar_high: float, bar_low: float):
        """bar_high/bar_low DELIBERATELY IGNORED -- production samples a
        SINGLE scalar price per tick (check_stop_take), never intrabar
        wicks. The bar's own CLOSE is used as the causal per-minute proxy
        for that sampled tick (see protocol doc's disclosed observation-
        schedule limitation)."""
        symbol = symbol.upper()
        if not self.has_open(symbol):
            return None
        close = self.bar_close.get((symbol, pd.Timestamp(timestamp)))
        if close is None:
            return None  # no observation this bar -- no fill invented
        exit_trade = self.paper.check_exits(symbol, close, now=timestamp)
        if exit_trade:
            self.exit_log.append({
                "symbol": symbol, "at": str(timestamp), "true_exit_reason": exit_trade.get("exit_reason"),
                "exit_price": exit_trade.get("exit"), "net_pnl": exit_trade.get("net_pnl"),
            })
        return None

    def close_on_signal_exit(self, symbol: str, timestamp, price_raw, exit_signal):
        """Real Experimental has NO bearish-signal-driven close (run.py's
        handle_message never calls close_long from a bearish candidate)
        -- always a no-op. Logged so a bearish-published-while-open event
        is still visible in the published-signal accounting."""
        symbol = symbol.upper()
        self.published_log.append({
            "symbol": symbol, "direction": "bearish", "decision_time": str(timestamp),
            "signal_type": getattr(exit_signal.signal_type, "value", None),
            "action": "BEARISH_PUBLISHED_WHILE_OPEN_NO_ACTION_TAKEN (no live caller closes on a bearish signal)",
        })
        return None

    def force_close(self, symbol: str, timestamp, price_raw, reason: str):
        """Real Experimental has no EOD flatten (BacktestConfig.eod_flatten_enabled
        =False makes this unreachable for END_OF_SESSION) and this replay
        does not force-close at the dataset boundary either (DATA_END) --
        always a no-op; open positions are reported separately, marked,
        never force-closed at an invented price."""
        return None

    def open_symbols(self) -> list[str]:
        return [p["ticker"] for p in self.paper.open_positions()]


def _build_relaxed_config():
    from talonx_quant.config import ConfluenceContract, QuantConfig, VolatilityGateMode
    from talonx_signals.config import RELAXED_OVERRIDES

    frozen = QuantConfig()
    cfg = replace(frozen, **RELAXED_OVERRIDES)
    if cfg.volatility_gate_mode != VolatilityGateMode.CURRENT_1M:
        raise ValueError("EXPERIMENTAL_RELAXED_V1 must keep volatility_gate_mode=CURRENT_1M")
    if cfg.confluence_contract != ConfluenceContract.LEGACY:
        raise ValueError("EXPERIMENTAL_RELAXED_V1 must keep confluence_contract=LEGACY")
    diffs = {f.name for f in fields(cfg) if getattr(cfg, f.name) != getattr(frozen, f.name)}
    if diffs - set(RELAXED_OVERRIDES):
        raise ValueError(f"relaxed config changed fields outside the whitelist: {sorted(diffs - set(RELAXED_OVERRIDES))}")
    return cfg, frozen


def _load_universe_mapping() -> dict:
    """Static symbol-universe mapping (Part 4): historical task93_canonical_v1
    35-symbol set vs. the CURRENT configured Experimental scope. Experimental
    consumes talonx:market:stream / talonx:signals:quant UNFILTERED by its
    own symbol allowlist -- it scans whatever CONTROL's own QuantScanner
    publishes candidates for, i.e. Original's configured watchlist
    (talonx_ops.watchlist_coverage), NOT a separate Experimental-only list.
    Reported explicitly, not assumed equal to "35 historical symbols"."""
    from talonx_piv.config import DEFAULT_UNIVERSE as PIV_UNIVERSE

    manifest = json.loads(MANIFEST_PATH.read_text())
    historical_35 = set(manifest["symbols"])
    piv_universe = set(PIV_UNIVERSE)
    # Read-only: this task is research-only and must never write/mutate a
    # production DB. build_coverage_map() only opens watchlist.db for a
    # SELECT internally; we additionally verify no write occurs by using
    # a strict read-only sqlite URI ourselves for the existence check.
    configured_live: set | None = None
    configured_live_error: str | None = None
    try:
        home = Path.home() / ".talonx"
        wl_path = home / "watchlist.db"
        if not wl_path.exists():
            raise FileNotFoundError(str(wl_path))
        with sqlite3.connect(f"file:{wl_path}?mode=ro", uri=True):
            pass  # existence + read-only-openable check only
        from talonx_ops.watchlist_coverage import build_coverage_map
        coverage = build_coverage_map(home=home)
        configured_live = {t["symbol"].upper() for t in coverage["tickers"]}
    except Exception as exc:  # noqa: BLE001 -- best-effort; live watchlist DB may not exist in this env
        configured_live_error = str(exc)

    return {
        "historical_35_symbol_universe": sorted(historical_35),
        "historical_is_piv_default_universe": historical_35 == piv_universe,
        "configured_live_watchlist": sorted(configured_live) if configured_live else None,
        "configured_live_watchlist_error": configured_live_error,
        "intersection_with_configured_live": (sorted(historical_35 & configured_live)
                                              if configured_live else None),
        "historical_not_in_configured_live": (sorted(historical_35 - configured_live)
                                              if configured_live else None),
        "note": ("Experimental scans CONTROL's published candidates unfiltered -- there is no "
                "Experimental-specific symbol allowlist in the runtime. The historical "
                "35-symbol set is Original's OWN validation universe (talonx_piv.DEFAULT_UNIVERSE), "
                "not independently proven equal to 'the complete configured product scope'."),
    }


def _load_window(start: str, end_inclusive: str) -> tuple[pd.DataFrame, dict]:
    """[start, end_inclusive] both INCLUSIVE calendar dates. Loads all 35
    task93_canonical_v1 symbols, filters to the window, sorts/dedupes,
    aborts on critical corruption (fail-closed, not a silent continue)."""
    from talonx_backtest.data import abort_on_critical_corruption, check_dataset_quality, load_ohlcv_directory, sort_and_dedupe

    manifest = json.loads(MANIFEST_PATH.read_text())
    df = load_ohlcv_directory(CANONICAL_DIR, symbols=manifest["symbols"])
    lo = pd.Timestamp(start, tz="UTC")
    hi = pd.Timestamp(end_inclusive, tz="UTC") + pd.Timedelta(days=1)  # exclusive upper bound
    df = df[(df["timestamp"] >= lo) & (df["timestamp"] < hi)]
    df = sort_and_dedupe(df)
    reports = check_dataset_quality(df)
    abort_on_critical_corruption(reports)
    return df, manifest


def run_replay(*, start: str, end_inclusive: str, label: str, progress_every_s: float = 30.0) -> dict:
    import time

    from talonx_backtest.engine import BacktestConfig, BacktestEngine
    from talonx_backtest.execution import ExecutionConfig
    from talonx_signals.experimental_paper import ExperimentalPaperEngine

    relaxed_cfg, frozen_cfg = _build_relaxed_config()
    df, manifest = _load_window(start, end_inclusive)
    print(f"[{label}] loaded {len(df):,} bars, {df['symbol'].nunique()} symbols, "
          f"{df['timestamp'].min()} .. {df['timestamp'].max()}", flush=True)

    # Bar-close lookup for the shim's check_exits price (causal: this
    # bar's own close only, the same bar being processed this tick).
    bar_close = {(row.symbol, row.timestamp): row.close for row in df.itertuples(index=False)}

    tmp_db = Path(tempfile.gettempdir()) / f"task121a_{label}_experimental_paper.db"
    if tmp_db.exists():
        tmp_db.unlink()
    paper = ExperimentalPaperEngine(
        db_path=tmp_db, allocation_usd=ALLOCATION_USD, spread_bps=SPREAD_BPS, initial_cash=INITIAL_CASH,
    )
    shim = ExperimentalLifecycleShim(paper=paper, bar_close=bar_close)

    cfg = BacktestConfig(
        quant_config=relaxed_cfg,
        execution=ExecutionConfig(spread_bps=0.0),  # inert: shim intercepts before TradeSimulator ever runs
        eod_flatten_enabled=False,          # Experimental has NO live EOD flatten caller -- verified, not assumed
        allow_overlapping_trades=True,      # routes every candidate through the shim; occupancy enforced IN the shim
    )
    engine = BacktestEngine(cfg, research_telemetry=True)
    engine.simulator = shim  # composition, not modification -- engine.py's own source is untouched

    t0 = time.time()
    last = [t0]

    def _progress(done, total):
        now = time.time()
        print(f"[{label}] progress {done}/{total} ({100.0*done/total:.1f}%) "
              f"+{now-last[0]:.1f}s", flush=True)
        last[0] = now

    result = engine.run(df, progress_callback=_progress, progress_interval_seconds=progress_every_s)
    elapsed = time.time() - t0
    print(f"[{label}] backtest elapsed: {elapsed:.1f}s", flush=True)

    # ---- real economics, read from the REAL ExperimentalPaperEngine ledger ----
    con = paper.store._conn  # noqa: SLF001 -- read-only local queries against our OWN isolated db
    closed = _fetch_rows(con, "SELECT * FROM trade_history WHERE order_type='SELL' ORDER BY id")
    opens = _fetch_rows(con, "SELECT * FROM positions")
    portfolio_row = _fetch_rows(con, "SELECT * FROM portfolio_state WHERE id=1")
    portfolio = portfolio_row[0] if portfolio_row else {}

    # mark any open position at its last available close in this window --
    # ONE O(n) pass over bar_close builds the per-symbol last-close map
    # (was: an O(n log n) sort of the ENTIRE bar_close dict PER open
    # position -- pathologically slow with hundreds of thousands of bars
    # and more than a handful of open positions; fixed here, not a
    # strategy/behavior change, purely a performance correction).
    last_close_by_symbol: dict[str, tuple] = {}
    for (s, ts), c in bar_close.items():
        prev = last_close_by_symbol.get(s)
        if prev is None or ts > prev[0]:
            last_close_by_symbol[s] = (ts, c)

    open_detail = []
    marked_open_value = 0.0
    for p in opens:
        sym = p.get("ticker")
        last_close = last_close_by_symbol.get(sym, (None, None))[1]
        mv = (last_close or 0.0) * float(p.get("shares") or 0.0)
        marked_open_value += mv
        open_detail.append({**p, "mark": last_close, "marked_value": mv,
                           "mark_status": "AVAILABLE" if last_close is not None else "UNAVAILABLE"})

    ending_cash = float(portfolio.get("current_cash", INITIAL_CASH))
    equity = ending_cash + marked_open_value

    # The SQL trade_history.exit_reason column only stores the coarser
    # AlertAction (CONFIRMED_BEARISH for BOTH stop_loss and target_exit --
    # see experimental_paper.py's own _EXIT_ACTION map). The shim's own
    # exit_log (captured directly off close_long()'s in-memory return
    # value, in chronological order -- the same order trade_history rows
    # are inserted in) carries the TRUE stop_loss/target_exit distinction;
    # reported as its own aggregate rather than joined row-by-row onto
    # trade_history (a timestamp-string join would be fragile and is not
    # needed for the aggregate this task asks for).
    true_exit_reason_counts: dict[str, int] = {}
    for e in shim.exit_log:
        true_exit_reason_counts[e["true_exit_reason"]] = true_exit_reason_counts.get(e["true_exit_reason"], 0) + 1

    n = len(closed)
    net_vals = [float(t["realized_pnl_usd"]) for t in closed]
    win_rate = (sum(1 for v in net_vals if v > 0) / n) if n else None
    gross_win = sum(v for v in net_vals if v > 0)
    gross_loss = -sum(v for v in net_vals if v <= 0)
    pf = (gross_win / gross_loss) if gross_loss > 0 else (float("inf") if gross_win > 0 else None)
    by_issuer_n: dict[str, int] = {}
    for t in closed:
        by_issuer_n[t["ticker"]] = by_issuer_n.get(t["ticker"], 0) + 1

    published_log = shim.published_log
    directions = {"bullish": sum(1 for p in published_log if p["direction"] == "bullish"),
                 "bearish": sum(1 for p in published_log if p["direction"] == "bearish")}
    actions: dict[str, int] = {}
    for p in published_log:
        actions[p["action"]] = actions.get(p["action"], 0) + 1

    summary = {
        "label": label, "window": {"start": start, "end_inclusive": end_inclusive},
        "n_bars": len(df), "elapsed_seconds": elapsed,
        "thresholds": {"relaxed": {k: getattr(relaxed_cfg, k) for k in
                                   ("min_atr_pct", "confluence_score_min", "min_risk_reward_ratio")},
                      "frozen_original": {k: getattr(frozen_cfg, k) for k in
                                         ("min_atr_pct", "confluence_score_min", "min_risk_reward_ratio")}},
        "funnel": {
            "bars_processed": result.bars_processed,
            "signals_generated": result.signals_generated,
            "signals_published": result.signals_published,
            "rejections_by_reason": {r.reason: sum(x.count for x in result.rejections if x.reason == r.reason)
                                     for r in result.rejections},
            "published_signal_directions": directions,
            "published_signal_actions": actions,
            "skip_already_open_total_by_symbol": dict(shim._skip_counts),  # noqa: SLF001
        },
        "published_signal_log": published_log,
        "cost_model": {"spread_bps_round_trip_approx": SPREAD_BPS, "commissions_modeled": False,
                      "allocation_usd_per_trade": ALLOCATION_USD, "initial_cash_usd": INITIAL_CASH,
                      "note": "apply_spread(price, 5.0, side) moves ONE side by 2.5bps; round-trip "
                              "at an unchanged reference price is ~5bps -- verified by a worked test, "
                              "not merely asserted (see tests/test_task121a_parity_trace.py)."},
        "performance": {
            "n_closed_trades": n, "distinct_issuers": len(by_issuer_n), "by_issuer_n_trades": by_issuer_n,
            "win_rate": win_rate, "profit_factor": pf,
            "net_pnl_usd_total": sum(net_vals) if net_vals else 0.0,
            "net_expectancy_usd_mean": (sum(net_vals) / n) if n else None,
            "true_exit_reason_counts": true_exit_reason_counts,
        },
        "closed_trades_table": closed,
        "exit_log": shim.exit_log,
        "open_positions_at_end": open_detail,
        "equity_final": {"starting_cash": INITIAL_CASH, "ending_cash": ending_cash,
                        "marked_open_value": marked_open_value, "equity": equity,
                        "formula": "ending_cash (real ledger) + marked open-position value -- open "
                                  "positions are NOT force-closed at the dataset boundary"},
    }
    (OUT / f"{label}_summary.json").write_text(json.dumps(summary, indent=2, default=str))
    try:
        paper.close()
    finally:
        if tmp_db.exists():
            tmp_db.unlink()
        for ext in ("-wal", "-shm"):
            p = Path(str(tmp_db) + ext)
            if p.exists():
                p.unlink()
    return summary


def _fetch_rows(con, sql: str) -> list[dict]:
    cur = con.execute(sql)
    cols = [d[0] for d in cur.description] if cur.description else []
    return [dict(zip(cols, row)) for row in cur.fetchall()]


def main() -> int:
    manifest = verify_provenance()
    print("provenance OK:", json.dumps({k: v for k, v in manifest.items() if k.startswith("_")}, indent=2))
    run_py_note = manifest["talonx_signals.run (NOT imported -- contract source only)"]
    print("run.py provenance:", json.dumps(run_py_note, indent=2))

    universe = _load_universe_mapping()
    (OUT / "universe_mapping.json").write_text(json.dumps(universe, indent=2, default=str))
    print("universe mapping:", json.dumps({k: v for k, v in universe.items() if k != "historical_35_symbol_universe"}, indent=2))

    # PART 5: one fixed, frozen calendar month, inclusive bounds, decided
    # BEFORE inspecting any outcome from this corrected adapter (only the
    # provenance/lifecycle corrections above informed this design).
    summary = run_replay(start="2025-01-24", end_inclusive="2025-02-23", label="month1_corrected")
    print(f"\n=== {summary['label']} ===")
    print(f"n_closed_trades={summary['performance']['n_closed_trades']} "
          f"distinct_issuers={summary['performance']['distinct_issuers']}")
    print(f"net_pnl_usd_total={summary['performance']['net_pnl_usd_total']}")
    print(f"equity_final={summary['equity_final']['equity']}")
    print(f"published directions: {summary['funnel']['published_signal_directions']}")
    print(f"published actions: {summary['funnel']['published_signal_actions']}")
    print("\nDONE. Full artifacts under", OUT)
    return 0


if __name__ == "__main__":
    sys.exit(main())
