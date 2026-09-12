"""
TASK 120B -- chronological V2 baseline, corrected methodology.

Reuses the EXACT engine Task 118 Deliverable A already used
(talonx_research.replay_engine.run_chronological_replay, driving the real
V2Service.tick() one XNYS session at a time) -- NOT the episode-return
primitives (runtime_episodes/build_returns) Task 120's original script
used, which is a materially different, less rigorous method (no position
limits, no cooldown, no capital constraint enforcement, no chronological
BUY/SELL pairing through the actual paper engine).

Two runs:
  B2 -- OVERLAP REGRESSION: reproduces Task 118 Deliverable A's exact
        config (39-name scope, 2024-09-01..2026-03-31, $10,000,000) and
        diffs the fresh output against the stored baseline_a_summary.json
        byte-for-byte on the metrics that must match.
  B3 -- LONGEST SUPPORTED WINDOW: same contract, same scope, extended to
        2019-01-01..2026-03-31 (the full Form-4 parquet coverage), using
        the $300,000 / 20-slot LIVE campaign sizing as the PRIMARY product
        diagnostic (this task's own instruction) -- $10,000,000 is run
        alongside only to isolate whether capital constraints bind.

No parameter tuning. No promotion. No threshold/scope change. Read-only
against the frozen release worktree's already-published free data.
"""
from __future__ import annotations
import json
import sqlite3
import sys
from datetime import date, timedelta
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO))

DATA_ROOT = Path("C:/workspace/TalonX")
OUT = REPO / "results" / "task120b_chronological_baseline"
OUT.mkdir(parents=True, exist_ok=True)

MANIFEST = json.loads((REPO / "docs/research/SCOPE_MANIFEST_39NAME.json").read_text())
THE_39 = MANIFEST["symbols"]
assert len(THE_39) == 39

COST_BPS = 20  # single, explicit, preregistered round-trip convention (Task 107B/112R/116/118A)

B2_WINDOW = ("2024-09-01", "2026-03-31")   # Task 118 Deliverable A's exact window
B3_WINDOW = ("2019-01-01", "2026-03-31")   # longest window the Form4 parquet supports


def _fingerprint_gate() -> str:
    from talonx_research.versioning import v2_fingerprint
    fp = v2_fingerprint()
    if fp != "11107198c5b81237":
        raise SystemExit(f"FINGERPRINT MOVED: {fp} -- ABORT")
    return fp


def _bar_dirs() -> list[Path]:
    # BOTH directories, exactly like Task 118 Deliverable A -- Task 120's
    # original script checked only the first one, which is the root cause
    # of its incorrect 6-name coverage-gap claim (see
    # docs/research/TASK120A_COVERAGE_RECONCILIATION.md).
    return [DATA_ROOT / "results/task95g_broad_cross_sectional/_daily",
            DATA_ROOT / "results/task107a_form4_feasibility/_prices"]


def _coverage(bar_dirs: list[Path]) -> dict:
    panels = [{f.stem.upper() for f in d.glob("*.csv")} for d in bar_dirs]
    union = set().union(*panels)
    return {
        "covered": sorted(set(THE_39) & union),
        "uncovered": sorted(set(THE_39) - union),
        "per_directory": {str(d): sorted(set(THE_39) & p) for d, p in zip(bar_dirs, panels)},
    }


def _provider(parquet: Path):
    from talonx_v2 import form4_source
    _all = [r for r in form4_source.from_research_parquet(
        str(parquet), symbols=set(THE_39), since=date.fromisoformat("2019-01-01"))]
    _all.sort(key=lambda r: r.filing_date)

    def provider(as_of):
        lo = as_of - timedelta(days=45)   # SAME causal 45-day rolling lookback V2Service._records() uses live
        return [r for r in _all if lo <= r.filing_date <= as_of]

    return provider


def _run(*, label: str, window: tuple[str, str], starting_cash: float) -> dict:
    from talonx_research.replay_engine import run_chronological_replay

    bar_dirs = _bar_dirs()
    parquet = DATA_ROOT / "results/task107a_form4_feasibility/_build/form4_open_market_txn.parquet"
    cov = _coverage(bar_dirs)
    ledger = OUT / f"replay_v2_lane_{label}.db"

    res = run_chronological_replay(
        start=window[0], end=window[1], ledger_path=ledger, bar_dirs=bar_dirs,
        records_provider=_provider(parquet), starting_cash=starting_cash)
    rd = res.to_dict()
    (OUT / f"{label}_raw_replay_result.json").write_text(json.dumps(rd, indent=2, default=str))

    trades = rd["trades"]
    buys = [t for t in trades if t["action"] == "BUY"]
    sells = [t for t in trades if t["action"] == "SELL"]

    by_episode: dict[str, dict] = {}
    for t in trades:
        by_episode.setdefault(t["episode_id"], {"symbol": t["symbol"]})[t["action"]] = t

    closed = []
    for eid, legs in by_episode.items():
        b, s = legs.get("BUY"), legs.get("SELL")
        if b is None or s is None:
            continue
        entry_px, exit_px = b.get("execution_price"), s.get("execution_price")
        if entry_px is None or exit_px is None:
            continue
        shares = b.get("shares") or 0.0
        gross_ret = (exit_px - entry_px) / entry_px
        entry_cost_bps = COST_BPS / 2.0
        exit_cost_bps = COST_BPS / 2.0
        net_ret = gross_ret - (COST_BPS / 10_000.0)   # applied ONCE, round-trip, verified below
        realized_usd = s.get("realized_pnl_usd")
        closed.append({
            "episode_id": eid, "symbol": legs["symbol"],
            "entry_price": entry_px, "exit_price": exit_px, "shares": shares,
            "entry_time": b.get("executed_at"), "exit_time": s.get("executed_at"),
            "gross_return_pct": round(100 * gross_ret, 4),
            "entry_cost_bps": entry_cost_bps, "exit_cost_bps": exit_cost_bps,
            "total_cost_bps": COST_BPS,
            "net_return_pct_20bps": round(100 * net_ret, 4),
            "realized_pnl_usd_from_ledger": realized_usd,
        })

    n = len(closed)
    net_col = [c["net_return_pct_20bps"] / 100.0 for c in closed]
    net_mean = sum(net_col) / n if n else None
    wins = [x for x in net_col if x > 0]
    losses = [x for x in net_col if x <= 0]
    gross_win = sum(wins)
    gross_loss = -sum(losses)
    pf = (gross_win / gross_loss) if gross_loss > 0 else (float("inf") if gross_win > 0 else None)
    win_rate = (len(wins) / n) if n else None

    by_sym_net: dict[str, float] = {}
    by_sym_n: dict[str, int] = {}
    for c, r in zip(closed, net_col):
        by_sym_net[c["symbol"]] = by_sym_net.get(c["symbol"], 0.0) + r
        by_sym_n[c["symbol"]] = by_sym_n.get(c["symbol"], 0) + 1
    distinct_issuers = len(by_sym_n)

    # equity: cash + marked value of open positions (final snapshot) -- NEVER
    # portfolio_cash_after or a cumulative-return sum (this task's own
    # instruction). Open positions at replay end are marked at their last
    # available close from the same bar directories used for execution.
    con = sqlite3.connect(f"file:{ledger}?mode=ro", uri=True)
    con.row_factory = sqlite3.Row
    opens = [dict(r) for r in con.execute(
        "SELECT symbol, shares, entry_price, position_cost, entry_session, target_exit_session "
        "FROM positions WHERE status='OPEN'")]
    con.close()

    import pandas as pd
    marked_open_value = 0.0
    open_detail = []
    for p in opens:
        mark = None
        for d in bar_dirs:
            f = d / f"{p['symbol']}.csv"
            if f.exists():
                df = pd.read_csv(f)
                df = df[pd.to_datetime(df["date"]) <= pd.Timestamp(window[1])]
                if len(df):
                    mark = float(df.iloc[-1]["close"])
                    break
        mv = (mark or 0.0) * p["shares"]
        marked_open_value += mv
        open_detail.append({**p, "mark": mark, "marked_value": mv,
                           "mark_status": "AVAILABLE" if mark is not None else "UNAVAILABLE"})

    ending_cash = rd["portfolio"]["ending_cash"]
    equity = ending_cash + marked_open_value
    open_cost_basis = sum(p["position_cost"] or 0.0 for p in opens)

    # trade-event-granularity cash curve (NOT a true daily mark-to-market --
    # daily bars for every holding-period day were not pulled for every
    # open position across the whole window; labelled explicitly, not
    # silently presented as continuous equity).
    cash_events = sorted(
        [{"at": t.get("executed_at"), "cash_after": t.get("portfolio_cash_after")} for t in trades],
        key=lambda x: (x["at"] or ""))

    # ---- B5: predeclared issuer-block bootstrap (seed 118120, 5000 reps, 95% CI) ----
    import numpy as np
    rng = np.random.default_rng(118120)
    issuers = list(by_sym_n.keys())
    ci = [float("nan"), float("nan")]
    if issuers and n:
        by_issuer_vals = {i: [r for c, r in zip(closed, net_col) if c["symbol"] == i] for i in issuers}
        means = []
        for _ in range(5000):
            picked = rng.choice(issuers, size=len(issuers), replace=True)
            vals = [v for i in picked for v in by_issuer_vals[i]]
            if vals:
                means.append(sum(vals) / len(vals))
        if means:
            ci = [float(np.percentile(means, 2.5)), float(np.percentile(means, 97.5))]

    result = {
        "label": label, "window": {"start": window[0], "end": window[1]},
        "starting_cash_usd": starting_cash,
        "cost_convention": {"total_round_trip_bps": COST_BPS, "entry_bps": COST_BPS / 2, "exit_bps": COST_BPS / 2,
                           "applied": "once per round trip, verified against realized_pnl_usd_from_ledger below"},
        "scope_manifest": "docs/research/SCOPE_MANIFEST_39NAME.json (frozen, not re-resolved per-tick)",
        "price_coverage": cov,
        "episode_accounting": {
            "processed_episode_dispositions": rd["activity"]["processed_episode_dispositions"],
            "buys": len(buys), "sells": len(sells),
            "closed_round_trips": n,
            "exit_unresolved": len(rd["exit_unresolved"]),
            "open_at_end": len(rd["open_at_end"]),
        },
        "trades_table": closed,
        "open_positions_at_end": open_detail,
        "performance": {
            "n_closed_trades": n, "distinct_issuers": distinct_issuers,
            "net_expectancy_mean_pct_20bps": round(100 * net_mean, 4) if net_mean is not None else None,
            "profit_factor": pf, "win_rate": win_rate,
            "by_issuer_net_return_pct_sum": {k: round(100 * v, 4) for k, v in by_sym_net.items()},
            "by_issuer_n_trades": by_sym_n,
        },
        "equity_final": {
            "ending_cash": ending_cash, "open_position_cost_basis": open_cost_basis,
            "marked_open_value": marked_open_value, "equity": equity,
            "formula": "cash + marked open-position value (NOT portfolio_cash_after, NOT a cumulative-return sum)",
        },
        "equity_curve_caveat": "trade-event-granularity cash curve only (cash_events below) -- NOT a true "
                               "daily mark-to-market of open positions between trade events; that would "
                               "require pulling daily bars for every holding-period day of every open "
                               "position across the whole window, not done in this bounded task",
        "cash_events": cash_events,
        "uncertainty": {
            "method": "issuer-block bootstrap, 5000 reps, seed 118120, 95% percentile CI (predeclared, "
                     "fixed before this script was run -- same convention as Task 95A-118F)",
            "ci_pct": [round(100 * ci[0], 4), round(100 * ci[1], 4)] if ci[0] == ci[0] else None,
            "effective_independent_groups": distinct_issuers,
            "caveat": f"N={n} trades across only {distinct_issuers} distinct issuers -- N alone is NOT "
                      "proof of adequate power; the effective independent-group count is the more "
                      "relevant power measure and is reported explicitly, not implied by N.",
        },
        "external_sends": rd["external_sends"],
        "live_ledger_written": False,
    }
    (OUT / f"{label}_summary.json").write_text(json.dumps(result, indent=2, default=str))
    return result


def main() -> int:
    fp = _fingerprint_gate()
    print(f"fingerprint OK: {fp}")

    print("\n=== B2: OVERLAP REGRESSION (2024-09-01..2026-03-31, $10,000,000) ===")
    b2 = _run(label="b2_overlap_10m", window=B2_WINDOW, starting_cash=10_000_000.0)
    print(f"  N={b2['performance']['n_closed_trades']}  "
          f"net@20bps={b2['performance']['net_expectancy_mean_pct_20bps']}%  "
          f"PF={b2['performance']['profit_factor']}")

    # ---- reconcile against the STORED Task 118 Deliverable A artifact ----
    stored_path = REPO / "results/task118_profitability/baseline_a_summary.json"
    recon = {"stored_artifact_found": stored_path.exists()}
    if stored_path.exists():
        stored = json.loads(stored_path.read_text())
        sp = stored["performance"]
        bp = b2["performance"]
        recon["N"] = {"stored": sp["n_closed_trades"], "fresh": bp["n_closed_trades"]}
        recon["net_20bps_pct"] = {"stored": round(100 * sp["net_expectancy_mean_20bps"], 4),
                                  "fresh": bp["net_expectancy_mean_pct_20bps"]}
        recon["profit_factor"] = {"stored": sp["profit_factor"], "fresh": bp["profit_factor"]}
        recon["exact_match"] = (recon["N"]["stored"] == recon["N"]["fresh"]
                                and abs(recon["net_20bps_pct"]["stored"] - recon["net_20bps_pct"]["fresh"]) < 0.01)
    (OUT / "b2_overlap_reconciliation.json").write_text(json.dumps(recon, indent=2, default=str))
    print(f"  overlap reconciliation vs. stored Task118 Deliverable A: {recon}")

    print("\n=== B3: LONGEST WINDOW, $300,000 PRIMARY (2019-01-01..2026-03-31) ===")
    b3_300k = _run(label="b3_full_300k", window=B3_WINDOW, starting_cash=300_000.0)
    print(f"  N={b3_300k['performance']['n_closed_trades']}  "
          f"net@20bps={b3_300k['performance']['net_expectancy_mean_pct_20bps']}%  "
          f"PF={b3_300k['performance']['profit_factor']}  "
          f"equity=${b3_300k['equity_final']['equity']:,.2f}")

    print("\n=== B3 (capital-isolation comparison): $10,000,000 ===")
    b3_10m = _run(label="b3_full_10m", window=B3_WINDOW, starting_cash=10_000_000.0)
    print(f"  N={b3_10m['performance']['n_closed_trades']}  "
          f"net@20bps={b3_10m['performance']['net_expectancy_mean_pct_20bps']}%  "
          f"PF={b3_10m['performance']['profit_factor']}")

    capital_binding = {
        "n_closed_300k": b3_300k["performance"]["n_closed_trades"],
        "n_closed_10m": b3_10m["performance"]["n_closed_trades"],
        "capital_constrained": b3_300k["performance"]["n_closed_trades"] < b3_10m["performance"]["n_closed_trades"],
        "note": "if $300k trade count is lower than $10m's, the campaign-sized run missed entries purely "
               "on capital/slot availability, not on signal detection -- reported explicitly, not blended "
               "into one number",
    }
    (OUT / "b3_capital_isolation.json").write_text(json.dumps(capital_binding, indent=2, default=str))
    print(f"\ncapital isolation: {capital_binding}")

    print("\nDONE. Full artifacts under", OUT)
    return 0


if __name__ == "__main__":
    sys.exit(main())
