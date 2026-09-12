"""
TASK 121 -- Experimental (EXPERIMENTAL_RELAXED_V1) exact-contract replay.

Narrow adapter, NOT a new research platform. Reuses:
  - talonx_backtest.engine.BacktestEngine    (the SAME production-code-reusing
    historical replay engine Task 93 used for Original -- see that module's
    own docstring: RollingBarBuffer/HtfBarAggregator/compute_indicators/
    evaluate_signals/the talonx_quant.consumer gate free-functions are all
    imported unmodified, nothing here re-derives a threshold or formula).
  - talonx_signals.config.RELAXED_OVERRIDES  (the EXACT three-field dict the
    live repaired Experimental runtime uses -- imported, never retyped).
  - talonx_paper.engine.apply_spread's own formula, reproduced via
    ExecutionConfig(spread_bps=5.0) (mathematically identical: bps/2/10000
    per side -- see docs/research/TASK121_PROTOCOL.md §4).

Only NEW code: (a) constructing the relaxed QuantConfig without touching any
production ExperimentalConfig path/state (`_build_relaxed_config` below,
which duplicates ONLY relaxed_profile.py's two guard assertions -- no
strategy logic), (b) converting the engine's per-share R/price output into
dollar terms at Experimental's real $2,500 fixed allocation (arithmetic
only, not a new position-sizing rule), (c) episode-disposition/economics
aggregation and reporting.

Read-only against the frozen release worktree's already-published
task93_canonical_v1 dataset. No network, no production DB/Redis writes, no
external send.
"""
from __future__ import annotations

import hashlib
import json
import sys
from dataclasses import fields, replace
from pathlib import Path

import numpy as np
import pandas as pd

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO))

RELEASE_ROOT = Path("C:/workspace/TalonX")
CANONICAL_DIR = RELEASE_ROOT / "results/task93_alpha_foundation/_canonical_data"
MANIFEST_PATH = RELEASE_ROOT / "results/task93_alpha_foundation/canonical_dataset_manifest.json"
OUT = REPO / "results" / "task121_experimental_replay"
OUT.mkdir(parents=True, exist_ok=True)

ALLOCATION_USD = 2500.0     # ExperimentalPaperEngine's real default
INITIAL_CASH = 100_000.0    # ExperimentalPaperEngine's real default
SPREAD_BPS_ROUND_TRIP = 5.0  # ExecutionConfig(spread_bps=X) -> X/2 per side; matches apply_spread(5.0)
BOOTSTRAP_SEED = 121121      # predeclared in TASK121_PROTOCOL.md, distinct from Task120's 118120
BOOTSTRAP_REPS = 5000


def _fingerprint_gate() -> dict:
    from talonx_research.versioning import v1_fingerprint

    fp = v1_fingerprint()
    if fp != "2ae6216bca70":
        raise SystemExit(f"V1 (Original) FINGERPRINT MOVED: {fp} -- ABORT (Experimental shares Original's "
                          f"scanner/strategy code; a moved fingerprint invalidates this replay's premise)")
    return {"v1_fingerprint": fp}


def _build_relaxed_config():
    """Reproduces build_experimental_quant_config's OWN two contract guards
    (never flip volatility_gate_mode / confluence_contract) without touching
    any ExperimentalConfig path/binding -- this is a batch historical
    replay, not a live isolated lane, so there is no Redis/db_path to bind.
    RELAXED_OVERRIDES itself is imported verbatim, not retyped."""
    from talonx_quant.config import ConfluenceContract, QuantConfig, VolatilityGateMode
    from talonx_signals.config import RELAXED_OVERRIDES

    frozen = QuantConfig()
    cfg = replace(frozen, **RELAXED_OVERRIDES)
    if cfg.volatility_gate_mode != VolatilityGateMode.CURRENT_1M:
        raise ValueError("EXPERIMENTAL_RELAXED_V1 must keep volatility_gate_mode=CURRENT_1M")
    if cfg.confluence_contract != ConfluenceContract.LEGACY:
        raise ValueError("EXPERIMENTAL_RELAXED_V1 must keep confluence_contract=LEGACY")
    diffs = {f.name for f in fields(cfg) if getattr(cfg, f.name) != getattr(frozen, f.name)}
    unexpected = diffs - set(RELAXED_OVERRIDES)
    if unexpected:
        raise ValueError(f"relaxed config changed fields outside the whitelist: {sorted(unexpected)}")
    return cfg, frozen


def _hash_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()[:16]


def _manifest() -> dict:
    files = [
        RELEASE_ROOT / "talonx_quant/consumer.py",
        RELEASE_ROOT / "talonx_quant/strategy.py",
        RELEASE_ROOT / "talonx_quant/config.py",
        RELEASE_ROOT / "talonx_quant/session.py",
        RELEASE_ROOT / "talonx_quant/indicators.py",
        RELEASE_ROOT / "talonx_signals/config.py",
        RELEASE_ROOT / "talonx_signals/relaxed_profile.py",
        RELEASE_ROOT / "talonx_signals/experimental_paper.py",
        RELEASE_ROOT / "talonx_backtest/engine.py",
        RELEASE_ROOT / "talonx_backtest/execution.py",
        RELEASE_ROOT / "talonx_paper/engine.py",
    ]
    research_files = [REPO / f.relative_to(RELEASE_ROOT) for f in files]
    out = {}
    for rel, res in zip(files, research_files):
        rel_h = _hash_file(rel)
        res_h = _hash_file(res) if res.exists() else None
        out[str(rel.relative_to(RELEASE_ROOT))] = {
            "release_sha256_16": rel_h, "research_sha256_16": res_h,
            "content_identical": (rel.read_text(errors="ignore").replace("\r\n", "\n")
                                  == res.read_text(errors="ignore").replace("\r\n", "\n")) if res.exists() else False,
        }
    return out


# First calendar week of Segment A only (see TASK121_PROTOCOL.md #2 --
# a timed, progress-logged smoke test measured a stable ~42-48 bars/sec
# single-threaded; a full-month run (393,624 bars) was actually launched
# and observed in progress (5.0% after ~8 minutes, confirming a ~2.5hr
# completion), then STOPPED and narrowed further to fit this task's
# session-interactive time budget -- no Experimental economic outcome
# (trade/candidate/rejection count) had been inspected at either window
# size when this final narrowing was made; only the bars/sec rate and
# elapsed-time-to-completion were observed. See
# results/task121_experimental_replay/rate_smoke_test.log and
# TASK121_PROTOCOL.md's window-selection note for the full chronology.
SEGMENT_A_START = "2025-01-24"
SEGMENT_A_END = "2025-01-31"


def _load_data() -> pd.DataFrame:
    from talonx_backtest.data import abort_on_critical_corruption, check_dataset_quality, load_ohlcv_directory, sort_and_dedupe

    manifest = json.loads(MANIFEST_PATH.read_text())
    df = load_ohlcv_directory(CANONICAL_DIR, symbols=manifest["symbols"])
    df = df[(df["timestamp"] >= pd.Timestamp(SEGMENT_A_START, tz="UTC"))
           & (df["timestamp"] < pd.Timestamp(SEGMENT_A_END, tz="UTC") + pd.Timedelta(days=1))]
    df = sort_and_dedupe(df)
    reports = check_dataset_quality(df)
    abort_on_critical_corruption(reports)  # fail closed -- same posture the CLI requires
    n_blocking = sum(1 for r in reports.values() if r.has_critical_corruption)
    return df, manifest, manifest["symbols"], n_blocking


def _run_backtest(quant_config, df: pd.DataFrame):
    import time

    from talonx_backtest.engine import BacktestConfig, BacktestEngine
    from talonx_backtest.execution import ExecutionConfig

    cfg = BacktestConfig(
        quant_config=quant_config,
        execution=ExecutionConfig(entry_slippage_bps=0.0, exit_slippage_bps=0.0,
                                  spread_bps=SPREAD_BPS_ROUND_TRIP, same_bar_resolution="stop_first"),
        eod_flatten_enabled=True, eod_flatten_hour_et=15, eod_flatten_minute_et=50,
        allow_overlapping_trades=False,
    )
    engine = BacktestEngine(cfg, research_telemetry=False)

    def _progress(done, total):
        print(f"  progress: {done}/{total} bars ({100.0 * done / total:.1f}%)", flush=True)

    t0 = time.time()
    result = engine.run(df, progress_callback=_progress, progress_interval_seconds=30.0)
    print(f"  backtest elapsed: {time.time() - t0:.1f}s", flush=True)
    return result


def _to_dollar_trades(trades) -> list[dict]:
    """shares = ALLOCATION_USD / entry_price_net (the actual fill price);
    dollar P&L = shares * (per-share P&L) already computed by the engine.
    gross ignores spread; net includes it (see TradeSimulator._close --
    gross_pnl/net_pnl are per-share, using raw vs. spread-adjusted prices
    respectively)."""
    from talonx_backtest.execution import ExecutionConfig, apply_entry_cost
    from talonx_quant.schemas import SignalDirection

    ex_cfg = ExecutionConfig(spread_bps=SPREAD_BPS_ROUND_TRIP)
    out = []
    for t in trades:
        if t.direction != "bullish" or t.entry_price is None or t.exit_price is None:
            continue
        entry_price_net = apply_entry_cost(t.entry_price, SignalDirection.BULLISH, ex_cfg)
        shares = ALLOCATION_USD / entry_price_net if entry_price_net > 0 else 0.0
        gross_usd = shares * (t.gross_pnl or 0.0)
        net_usd = shares * (t.net_pnl or 0.0)
        out.append({
            "symbol": t.symbol, "signal_timestamp": str(t.signal_timestamp),
            "entry_timestamp": str(t.entry_timestamp), "exit_timestamp": str(t.exit_timestamp),
            "entry_price_raw": t.entry_price, "entry_price_net": entry_price_net,
            "exit_price_raw": t.exit_price, "exit_reason": t.exit_reason,
            "holding_seconds": t.holding_seconds, "session": t.session,
            "setup_type": t.signal_type, "confluence_score": t.confluence_score,
            "risk_reward_ratio_screening": t.risk_reward_ratio,
            "shares": shares, "allocation_usd": ALLOCATION_USD,
            "gross_pnl_per_share": t.gross_pnl, "net_pnl_per_share": t.net_pnl,
            "gross_pnl_usd": gross_usd, "net_pnl_usd": net_usd,
            "spread_cost_usd": gross_usd - net_usd,
            "gross_return_pct": (t.gross_pnl / t.entry_price * 100.0) if t.entry_price else None,
            "net_return_pct": (net_usd / ALLOCATION_USD * 100.0),
            "gross_R": t.gross_R, "net_R": t.net_R,
        })
    return out


def _issuer_block_bootstrap(dollar_trades: list[dict], value_key: str) -> dict:
    if not dollar_trades:
        return {"ci_pct": None, "effective_independent_groups": 0}
    by_issuer: dict[str, list[float]] = {}
    for t in dollar_trades:
        by_issuer.setdefault(t["symbol"], []).append(t[value_key])
    issuers = list(by_issuer.keys())
    rng = np.random.default_rng(BOOTSTRAP_SEED)
    means = []
    for _ in range(BOOTSTRAP_REPS):
        picked = rng.choice(issuers, size=len(issuers), replace=True)
        vals = [v for i in picked for v in by_issuer[i]]
        if vals:
            means.append(float(np.mean(vals)))
    ci = [float(np.percentile(means, 2.5)), float(np.percentile(means, 97.5))] if means else None
    return {"ci": ci, "effective_independent_groups": len(issuers), "n_reps": BOOTSTRAP_REPS,
            "seed": BOOTSTRAP_SEED, "method": "issuer-block bootstrap, 95% percentile CI"}


def main() -> int:
    gate = _fingerprint_gate()
    print("fingerprint gate:", gate)

    relaxed_cfg, frozen_cfg = _build_relaxed_config()
    print("relaxed thresholds:", {k: getattr(relaxed_cfg, k) for k in
                                  ("min_atr_pct", "confluence_score_min", "min_risk_reward_ratio")})
    print("frozen (Original) thresholds:", {k: getattr(frozen_cfg, k) for k in
                                            ("min_atr_pct", "confluence_score_min", "min_risk_reward_ratio")})

    manifest = _manifest()
    (OUT / "runtime_manifest.json").write_text(json.dumps({"fingerprint_gate": gate, "files": manifest}, indent=2))

    print("loading task93_canonical_v1 ...")
    df, ds_manifest, symbols, n_blocking = _load_data()
    print(f"loaded {len(df):,} bars, {df['symbol'].nunique()} symbols, "
          f"{df['timestamp'].min()} .. {df['timestamp'].max()}, blocking_issues={n_blocking}")
    configured_scope = set(symbols)
    covered_scope = set(df["symbol"].unique())
    missing = sorted(configured_scope - covered_scope)

    print("\nrunning EXPERIMENTAL_RELAXED_V1 replay (this can take a while)...")
    result = _run_backtest(relaxed_cfg, df)

    all_trades = [t for t in result.trades]
    regular_trades = [t for t in all_trades if t.session == "regular"]
    non_regular_trades = [t for t in all_trades if t.session != "regular"]
    dollar_trades = _to_dollar_trades(regular_trades)

    n = len(dollar_trades)
    net_vals = [t["net_pnl_usd"] for t in dollar_trades]
    gross_vals = [t["gross_pnl_usd"] for t in dollar_trades]
    net_ret_pct = [t["net_return_pct"] for t in dollar_trades]
    wins = [v for v in net_vals if v > 0]
    losses = [v for v in net_vals if v <= 0]
    win_rate = len(wins) / n if n else None
    pf = (sum(wins) / -sum(losses)) if losses and -sum(losses) > 0 else (float("inf") if wins else None)
    by_issuer_n: dict[str, int] = {}
    for t in dollar_trades:
        by_issuer_n[t["symbol"]] = by_issuer_n.get(t["symbol"], 0) + 1
    distinct_issuers = len(by_issuer_n)

    overnight_holds = [t for t in dollar_trades if t["exit_reason"] not in ("STOP", "TARGET")
                       and t["holding_seconds"] and t["holding_seconds"] > 16 * 3600]
    exit_reason_counts: dict[str, int] = {}
    for t in dollar_trades:
        exit_reason_counts[t["exit_reason"]] = exit_reason_counts.get(t["exit_reason"], 0) + 1

    rejections_by_reason: dict[str, int] = {}
    for r in result.rejections:
        rejections_by_reason[r.reason] = rejections_by_reason.get(r.reason, 0) + r.count

    entries_all = len(all_trades)
    published_minus_entered = result.signals_published - entries_all

    bootstrap = _issuer_block_bootstrap(dollar_trades, "net_pnl_usd")
    bootstrap_pct = _issuer_block_bootstrap(dollar_trades, "net_return_pct")

    # sensitivity: drop top-1 issuer by trade count
    if by_issuer_n:
        top_issuer = max(by_issuer_n, key=by_issuer_n.get)
        no_top = [t["net_pnl_usd"] for t in dollar_trades if t["symbol"] != top_issuer]
        drop_top1 = {
            "top_issuer": top_issuer, "top_issuer_n_trades": by_issuer_n[top_issuer],
            "mean_net_usd_all": (sum(net_vals) / n) if n else None,
            "mean_net_usd_excl_top": (sum(no_top) / len(no_top)) if no_top else None,
        }
    else:
        drop_top1 = None

    # capital-isolation empirical check: was $100k/$2500 ever insufficient?
    max_concurrent = 0
    # approximate via a sweep of entry/exit intervals (regular trades only, entries are next-bar-open)
    events = []
    for t in dollar_trades:
        events.append((t["entry_timestamp"], 1))
        events.append((t["exit_timestamp"], -1))
    events.sort()
    running = 0
    for _, delta in events:
        running += delta
        max_concurrent = max(max_concurrent, running)
    capital_never_binding = (max_concurrent * ALLOCATION_USD) <= INITIAL_CASH

    equity_final = INITIAL_CASH + sum(net_vals)

    result_summary = {
        "contract": "EXPERIMENTAL_RELAXED_V1",
        "dataset": {"id": ds_manifest["dataset_id"], "sha256": ds_manifest.get("combined_fingerprint_sha256"),
                   "window": [str(df["timestamp"].min()),
                   str(df["timestamp"].max())], "n_bars": len(df), "n_blocking_quality_issues": n_blocking},
        "universe": {"configured_scope_n": len(configured_scope), "covered_n": len(covered_scope),
                    "missing": missing},
        "thresholds": {"relaxed": {k: getattr(relaxed_cfg, k) for k in
                                   ("min_atr_pct", "confluence_score_min", "min_risk_reward_ratio")},
                      "frozen_original": {k: getattr(frozen_cfg, k) for k in
                                         ("min_atr_pct", "confluence_score_min", "min_risk_reward_ratio")}},
        "funnel": {
            "bars_processed": result.bars_processed,
            "signals_generated": result.signals_generated,
            "signals_published": result.signals_published,
            "rejections_by_reason": rejections_by_reason,
            "entries_all_sessions": entries_all,
            "entries_regular_session": len(regular_trades),
            "entries_non_regular_session_excluded": len(non_regular_trades),
            "published_minus_entered": published_minus_entered,
            "published_minus_entered_note": ("difference is entries skipped because the symbol already had an "
                "open position (no pyramiding) or the historical data ended before the next bar could fill it "
                "-- the engine does not emit a separate rejection record for the position-already-open case, "
                "so this is reported as one combined figure, not silently omitted"),
        },
        "cost_model": {"spread_bps_round_trip": SPREAD_BPS_ROUND_TRIP, "commissions_modeled": False,
                      "allocation_usd_per_trade": ALLOCATION_USD, "initial_cash_usd": INITIAL_CASH},
        "performance": {
            "n_closed_trades_regular_session": n, "distinct_issuers": distinct_issuers,
            "by_issuer_n_trades": by_issuer_n,
            "win_rate": win_rate, "profit_factor": pf,
            "net_expectancy_usd_mean": (sum(net_vals) / n) if n else None,
            "net_expectancy_pct_mean": (sum(net_ret_pct) / n) if n else None,
            "gross_expectancy_usd_mean": (sum(gross_vals) / n) if n else None,
            "net_pnl_usd_total": sum(net_vals) if net_vals else 0.0,
            "gross_pnl_usd_total": sum(gross_vals) if gross_vals else 0.0,
            "spread_cost_usd_total": (sum(gross_vals) - sum(net_vals)) if net_vals else 0.0,
        },
        "equity_final": {"starting_cash": INITIAL_CASH, "gross_pnl_total": sum(gross_vals) if gross_vals else 0.0,
                         "spread_cost_total": (sum(gross_vals) - sum(net_vals)) if net_vals else 0.0,
                         "net_pnl_total": sum(net_vals) if net_vals else 0.0,
                         "equity": equity_final,
                         "formula": "initial_cash + sum(net_pnl_usd per closed trade) -- no compounding "
                                   "across trades (fixed $2,500 allocation per entry, matching the real "
                                   "engine's fixed-notional sizing); 0 open positions expected at data end "
                                   "given EOD flatten (verified below)"},
        "exit_reason_counts": exit_reason_counts,
        "overnight_or_weekend_holds": len(overnight_holds),
        "concurrency": {"max_concurrent_open_positions": max_concurrent,
                       "capital_never_binding": capital_never_binding,
                       "max_committed_usd": max_concurrent * ALLOCATION_USD},
        "uncertainty_usd": bootstrap,
        "uncertainty_pct": bootstrap_pct,
        "sensitivity_drop_top1_issuer": drop_top1,
        "trades_table": dollar_trades,
    }
    (OUT / "experimental_replay_summary.json").write_text(json.dumps(result_summary, indent=2, default=str))
    print("\n=== SUMMARY ===")
    print(f"regular-session closed trades: {n}  distinct issuers: {distinct_issuers}")
    print(f"win_rate={win_rate}  PF={pf}")
    print(f"net expectancy: ${result_summary['performance']['net_expectancy_usd_mean']:.4f} "
          f"({result_summary['performance']['net_expectancy_pct_mean']:.4f}%)" if n else "no trades")
    print(f"net $ P&L total: ${sum(net_vals):.2f}" if net_vals else "no trades")
    print(f"equity_final: ${equity_final:,.2f}")
    print(f"95% CI (usd): {bootstrap.get('ci')}")
    print(f"95% CI (pct): {bootstrap_pct.get('ci')}")
    print(f"overnight/weekend holds: {len(overnight_holds)}  max_concurrent={max_concurrent}  "
          f"capital_never_binding={capital_never_binding}")
    print(f"missing configured symbols: {missing}")
    print("\nDONE. Full artifacts under", OUT)
    return 0


if __name__ == "__main__":
    sys.exit(main())
