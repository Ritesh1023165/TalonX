"""
TASK 130 -- Option A: one offline evaluation of INSIDER_BUY_CLUSTER_V2@1
over Discovery Universe v1 (626 names), under a $300k isolated capacity-
constrained paper campaign and a stricter prospective-only entry policy.

Reuses talonx_research.replay_engine.run_chronological_replay (the REAL
talonx_v2.service.V2Service, unmodified) exactly as Task 118D's own
run_populations_bc.py did -- same records_provider pattern, same window.
No production code is modified. The isolated research ledger is opened
read-only afterward to derive Track A (historical, all closed trades)
and Track B (timestamp-proven prospective: only trades with a
pre-existing pending_entry_intents row) with Track B's own separately
reconstructed chronological cash/equity series.
"""
from __future__ import annotations

import json
import sqlite3
import sys
from datetime import date, timedelta
from pathlib import Path

import numpy as np
import pandas as pd

RELEASE_ROOT = Path("C:/workspace/TalonX")
RESEARCH_ROOT = Path(__file__).resolve().parents[2]
# Matches Task 118D's own run_populations_bc.py convention exactly: import
# talonx_v2/talonx_research from the RESEARCH worktree's own copy (verified
# fingerprint-checked below), reserving RELEASE_ROOT only as the DATA_ROOT
# for bar directories / the Form 4 parquet, not for code imports.
sys.path.insert(0, str(RESEARCH_ROOT))

OUT = RESEARCH_ROOT / "results" / "task130_option_a_discovery"
OUT.mkdir(parents=True, exist_ok=True)

FORM4_PARQUET = RELEASE_ROOT / "results/task107a_form4_feasibility/_build/form4_open_market_txn.parquet"
DAILY_DIR_1 = RELEASE_ROOT / "results/task95g_broad_cross_sectional/_daily"
DAILY_DIR_2 = RELEASE_ROOT / "results/task107a_form4_feasibility/_prices"
SPY_PATH = DAILY_DIR_2 / "SPY.csv"

START, END = "2024-09-01", "2026-03-31"
STARTING_CASH = 300_000.0
COST_BPS = 20.0
PRIMARY_MATERIALITY_PCT = 0.50
BOOTSTRAP_SEED = 130130
BOOTSTRAP_REPS = 5000
EXPECTED_FINGERPRINT = "11107198c5b81237"


def _load_universe() -> list[str]:
    m = json.loads((RESEARCH_ROOT / "results/task118_profitability/reconciliation/population_manifest.json").read_text())
    return sorted(m["C_full_panel_A_union_B"])


def _run_replay(symbols: list[str]) -> "object":
    from talonx_research.versioning import v2_fingerprint
    from talonx_v2 import form4_source
    from talonx_research.replay_engine import run_chronological_replay

    fp = v2_fingerprint()
    if fp != EXPECTED_FINGERPRINT:
        raise SystemExit(f"FINGERPRINT MOVED: {fp} -- ABORT")

    all_recs = list(form4_source.from_research_parquet(str(FORM4_PARQUET), since=date(2019, 1, 1)))
    all_recs.sort(key=lambda r: r.filing_date)
    syms = set(symbols)
    recs_sorted = [r for r in all_recs if r.symbol in syms]

    def provider(as_of):
        lo = as_of - timedelta(days=45)
        return [r for r in recs_sorted if lo <= r.filing_date <= as_of]

    ledger = OUT / "replay_v2_lane_discovery_v1.db"
    bar_dirs = [DAILY_DIR_1, DAILY_DIR_2]
    return run_chronological_replay(
        start=START, end=END, ledger_path=ledger, bar_dirs=bar_dirs,
        records_provider=provider, starting_cash=STARTING_CASH), ledger


def _net_return(entry_px: float, exit_px: float) -> float:
    return (exit_px - entry_px) / entry_px - COST_BPS / 10_000.0


def _closed_trades_from_positions(closed_positions: list[dict]) -> list[dict]:
    """Built from the `positions` table's own `entry_session`/`exit_session`
    columns (the SIMULATED trading-session dates) -- NOT from `trades.executed_at`,
    which is a REAL WALL-CLOCK timestamp (when this script happened to run),
    discovered and corrected during this task's own evaluation run (see
    TASK130_OPTION_A_ECONOMIC_DECISION.md's implementation-difference note)."""
    closed = []
    for p in closed_positions:
        gross = (p["exit_price"] - p["entry_price"]) / p["entry_price"]
        net = _net_return(p["entry_price"], p["exit_price"])
        closed.append({
            "episode_id": p["episode_id"], "symbol": p["symbol"],
            "entry_session": p["entry_session"], "exit_session": p["exit_session"],
            "entry_price": p["entry_price"], "exit_price": p["exit_price"],
            "gross_return": gross, "net_return": net,
            "net_pnl_usd": 10_000.0 * net,
        })
    return closed


def _issuer_block_bootstrap(returns_by_issuer: dict[str, list[float]], *, seed: int) -> dict:
    issuers = list(returns_by_issuer.keys())
    if len(issuers) < 2:
        return {"n_issuer_blocks": len(issuers), "ci_pct": None, "method": "insufficient_issuers"}
    rng = np.random.default_rng(seed)
    means = []
    for _ in range(BOOTSTRAP_REPS):
        idx = rng.integers(0, len(issuers), size=len(issuers))
        sampled = [r for i in idx for r in returns_by_issuer[issuers[i]]]
        if sampled:
            means.append(float(np.mean(sampled)))
    if not means:
        return {"n_issuer_blocks": len(issuers), "ci_pct": None, "method": "no_valid_resamples"}
    ci = [float(np.percentile(means, 2.5)), float(np.percentile(means, 97.5))]
    return {"n_issuer_blocks": len(issuers), "ci_pct": [round(100 * c, 4) for c in ci],
           "method": f"issuer-block bootstrap, {BOOTSTRAP_REPS} reps, seed {seed}, 95% percentile CI"}


def _date_block_bootstrap(returns_by_month: dict[str, list[float]], *, seed: int) -> dict:
    months = list(returns_by_month.keys())
    if len(months) < 2:
        return {"n_date_blocks": len(months), "ci_pct": None, "method": "insufficient_blocks"}
    rng = np.random.default_rng(seed)
    means = []
    for _ in range(BOOTSTRAP_REPS):
        idx = rng.integers(0, len(months), size=len(months))
        sampled = [r for i in idx for r in returns_by_month[months[i]]]
        if sampled:
            means.append(float(np.mean(sampled)))
    if not means:
        return {"n_date_blocks": len(months), "ci_pct": None, "method": "no_valid_resamples"}
    ci = [float(np.percentile(means, 2.5)), float(np.percentile(means, 97.5))]
    return {"n_date_blocks": len(months), "ci_pct": [round(100 * c, 4) for c in ci],
           "method": f"date-block (monthly) bootstrap, {BOOTSTRAP_REPS} reps, seed {seed}, 95% percentile CI"}


def _track_stats(closed: list[dict], label: str) -> dict:
    n = len(closed)
    if n == 0:
        return {"track": label, "n_closed_trades": 0}
    net = [c["net_return"] for c in closed]
    gross = [c["gross_return"] for c in closed]
    issuers = sorted({c["symbol"] for c in closed})
    by_issuer: dict[str, list[float]] = {}
    for c in closed:
        by_issuer.setdefault(c["symbol"], []).append(c["net_return"])
    by_month: dict[str, list[float]] = {}
    for c in closed:
        by_month.setdefault(str(pd.Timestamp(c["entry_session"]).to_period("M")), []).append(c["net_return"])

    gross_win = sum(r for r in net if r > 0)
    gross_loss = -sum(r for r in net if r <= 0)
    issuer_counts = {k: len(v) for k, v in by_issuer.items()}
    top_sorted = sorted(issuer_counts, key=lambda k: -issuer_counts[k])

    def _excl_top_n(n_top: int) -> dict:
        excl = set(top_sorted[:n_top])
        remaining = [c["net_return"] for c in closed if c["symbol"] not in excl]
        return {"n_remaining": len(remaining),
               "mean_net_pct": round(100 * float(np.mean(remaining)), 4) if remaining else None}

    half_year = {}
    for c in closed:
        ts = pd.Timestamp(c["entry_session"])
        half = f"{ts.year}H{1 if ts.month <= 6 else 2}"
        half_year.setdefault(half, []).append(c["net_return"])
    half_year_stats = {k: {"n": len(v), "mean_net_pct": round(100 * float(np.mean(v)), 4)}
                       for k, v in sorted(half_year.items())}

    top1_issuer = top_sorted[0] if top_sorted else None
    top1_pnl_share = (sum(c["net_pnl_usd"] for c in closed if c["symbol"] == top1_issuer) /
                      sum(c["net_pnl_usd"] for c in closed) if top1_issuer and
                      sum(c["net_pnl_usd"] for c in closed) != 0 else None)

    return {
        "track": label, "n_closed_trades": n, "n_distinct_issuers": len(issuers),
        "gross_mean_pct": round(100 * float(np.mean(gross)), 4),
        "net_mean_pct": round(100 * float(np.mean(net)), 4),
        "net_median_pct": round(100 * float(np.median(net)), 4),
        "win_rate": round(float(np.mean([r > 0 for r in net])), 4),
        "profit_factor": round(gross_win / gross_loss, 4) if gross_loss > 0 else None,
        "meets_primary_criterion_gt_0_50pct": (100 * float(np.mean(net))) > PRIMARY_MATERIALITY_PCT,
        "issuer_block_bootstrap": _issuer_block_bootstrap(by_issuer, seed=BOOTSTRAP_SEED),
        "date_block_bootstrap": _date_block_bootstrap(by_month, seed=BOOTSTRAP_SEED),
        "top1_issuer": top1_issuer, "top1_issuer_trade_count": issuer_counts.get(top1_issuer),
        "top1_issuer_share_of_trades": round(issuer_counts.get(top1_issuer, 0) / n, 4) if top1_issuer else None,
        "top1_issuer_share_of_net_pnl": round(top1_pnl_share, 4) if top1_pnl_share is not None else None,
        "sensitivity_excl_top1": _excl_top_n(1),
        "sensitivity_excl_top3": _excl_top_n(3),
        "sensitivity_excl_top5": _excl_top_n(5),
        "calendar_half_year_stability": half_year_stats,
    }


def _reconstruct_chronological_equity(closed: list[dict], *, starting_cash: float,
                                      allocation: float = 10_000.0) -> dict:
    """Independent, isolated reconstruction: only THESE closed trades'
    entries/exits move cash, chronologically, respecting the SAME
    $10k/position sizing and never going negative. Used for Track B so
    a cold-start trade (excluded from `closed`) genuinely never touches
    this series.

    Two distinct series are reported, with precise, non-conflated
    definitions:
      - `cash`: literal cash on hand (dips when capital is DEPLOYED into
        an open position, independent of any gain/loss -- deploying
        capital is not itself a drawdown).
      - `realized_equity` = cash + (each currently-open position marked
        AT ITS OWN ENTRY COST, never fluctuating until realized at
        exit). This is the metric `max_drawdown_pct` is computed from --
        it only falls when a trade is REALIZED at a loss, not merely
        because capital is committed. It explicitly does NOT include
        intra-holding unrealized mark-to-market fluctuation of open
        positions (this reconstruction has no daily bar marks wired in)
        -- stated as a limitation, not fabricated precision.
    """
    events = []
    for c in closed:
        events.append((pd.Timestamp(c["entry_session"]), "ENTRY", c))
        events.append((pd.Timestamp(c["exit_session"]), "EXIT", c))
    events.sort(key=lambda e: (e[0], 0 if e[1] == "EXIT" else 1))  # exits free cash before same-day entries

    cash = starting_cash
    open_notional = {}
    curve = []
    for ts, kind, c in events:
        if kind == "ENTRY":
            spend = min(allocation, cash)
            if spend <= 0:
                continue
            cash -= spend
            open_notional[c["episode_id"]] = spend
        else:
            notional = open_notional.pop(c["episode_id"], allocation)
            proceeds = notional * (1.0 + c["net_return"])
            cash += proceeds
        realized_equity = cash + sum(open_notional.values())  # open positions marked at cost, not fluctuating
        curve.append({"date": str(ts.date()), "event": kind, "symbol": c["symbol"],
                     "cash": round(cash, 2), "n_open": len(open_notional),
                     "realized_equity": round(realized_equity, 2)})
    eq = pd.Series([e["realized_equity"] for e in curve]) if curve else pd.Series([starting_cash])
    running_max = eq.cummax()
    dd = (eq - running_max) / running_max.replace(0, np.nan)
    min_cash = min((e["cash"] for e in curve), default=starting_cash)
    return {
        "starting_cash": starting_cash, "ending_cash": round(cash, 2),
        "ending_realized_equity": round(curve[-1]["realized_equity"], 2) if curve else starting_cash,
        "min_cash_observed": round(min_cash, 2),
        "total_return_pct": round(100 * (cash / starting_cash - 1.0), 4),
        "max_drawdown_pct_realized_equity_basis": round(float(dd.min() * 100), 4) if len(dd.dropna()) else 0.0,
        "drawdown_note": "computed on cash + open-positions-marked-at-entry-cost ('realized equity'); "
                        "does NOT include intra-holding unrealized mark-to-market fluctuation of open "
                        "positions (no daily bar marks wired into this reconstruction) -- a disclosed "
                        "limitation, not a claim of daily-marked precision.",
        "n_events": len(curve),
    }


def main() -> int:
    universe = _load_universe()
    res, ledger = _run_replay(universe)
    rd = res.to_dict()

    con = sqlite3.connect(f"file:{ledger}?mode=ro", uri=True)
    con.row_factory = sqlite3.Row
    all_intents = {r["episode_id"]: dict(r) for r in con.execute("SELECT * FROM pending_entry_intents")}
    ep_disp = {r[0]: r[1] for r in con.execute(
        "SELECT disposition, COUNT(*) FROM processed_episodes GROUP BY disposition")}
    n_filings = con.execute("SELECT COUNT(*) FROM processed_episodes").fetchone()[0]
    closed_positions = [dict(r) for r in con.execute(
        "SELECT * FROM positions WHERE status='CLOSED' ORDER BY entry_session")]
    con.close()

    closed_all = _closed_trades_from_positions(closed_positions)
    closed_A = closed_all  # Track A = historical, unfiltered
    closed_B = [c for c in closed_all if c["episode_id"] in all_intents]
    n_cold_start = len(closed_A) - len(closed_B)

    track_A = _track_stats(closed_A, "A_historical_ideal_timing")
    track_B = _track_stats(closed_B, "B_timestamp_proven_prospective")
    equity_B = _reconstruct_chronological_equity(closed_B, starting_cash=STARTING_CASH)
    equity_A_native = rd["portfolio"]  # Track A's OWN native replay portfolio (includes cold-start cash impact)

    # SPY benchmark over the same window
    spy = pd.read_csv(SPY_PATH, parse_dates=["date"])
    spy = spy[(spy["date"] >= START) & (spy["date"] <= END)].sort_values("date")
    spy_ret = float(spy["close"].iloc[-1] / spy["close"].iloc[0] - 1.0) if len(spy) else None

    result = {
        "window": {"start": START, "end": END}, "universe_n": len(universe),
        "starting_cash": STARTING_CASH, "per_position_allocation": 10_000.0,
        "max_concurrent_positions": 20, "cost_bps_round_trip": COST_BPS,
        "fingerprint": res.fingerprint,
        "funnel": {
            "n_processed_episode_records": n_filings,
            "episode_dispositions": ep_disp,
            "n_entries_native_replay": rd["activity"]["n_buys"],
            "n_exits_native_replay": rd["activity"]["n_sells"],
            "n_closed_trades_track_A": len(closed_A),
            "n_closed_trades_track_B_timestamp_proven": len(closed_B),
            "n_cold_start_excluded_from_track_B": n_cold_start,
            "n_pending_entry_intents_total": len(all_intents),
            "n_open_at_end": len(rd["open_at_end"]),
            "n_exit_unresolved": len(rd["exit_unresolved"]),
        },
        "track_A_historical": track_A,
        "track_A_native_portfolio": equity_A_native,
        "track_B_prospective": track_B,
        "track_B_reconstructed_equity": equity_B,
        "track_C_operational_latency": "UNAVAILABLE_REQUIRES_LIVE_OBSERVATION",
        "spy_benchmark_total_return_pct": round(100 * spy_ret, 4) if spy_ret is not None else None,
    }
    (OUT / "task130_evaluation_results.json").write_text(json.dumps(result, indent=2, default=str))
    (OUT / "closed_trades_track_A.json").write_text(json.dumps(closed_A, indent=2, default=str))
    (OUT / "closed_trades_track_B.json").write_text(json.dumps(closed_B, indent=2, default=str))

    print(json.dumps({k: v for k, v in result.items() if k not in ()}, indent=2, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
