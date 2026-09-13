"""
TASK 128 -- reconciles the ACTUAL chronological portfolio for Task 127's
Benchmark 1 (eligible-universe equal-weight, NO selection) contract,
which was never built in Task 127 (only Strategy A's chronological
portfolio was; Benchmark B1's reported +13.70% was an arithmetic mean
of 68 individual 6-month cohort returns, not a portfolio return -- see
docs/research/TASK127_LONG_TERM_ECONOMIC_DECISION.md's Task 128
correction).

Reuses task127_52wk_high_evaluation.py's existing, already-generic
functions UNCHANGED (load_all, build_cohorts, Cohort, _price_on_or_none,
_month_end_dates) -- the SAME frozen Benchmark 1 contract (monthly
formation, ALL eligible names equal-weighted, 6-month overlapping
holds), never turned into a buy-and-hold or a monthly-rebalanced
single portfolio. The only NEW code is a daily-marking variant of the
existing monthly-marking `run_chronological_portfolio` (extended per
Task 128's explicit request for daily marked-equity drawdown/recovery,
not a new engine) and a SPY comparison portfolio using the SAME
starting capital/dates, also marked daily.

A completely SEPARATE $100,000 research-only capital pool -- NOT the
production V2 $300k paper campaign, NOT connected to any live ledger.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd

RESEARCH_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(RESEARCH_ROOT / "research" / "scripts"))

import task127_52wk_high_evaluation as t127  # noqa: E402

OUT = RESEARCH_ROOT / "results" / "task128_baseline_reconciliation"
OUT.mkdir(parents=True, exist_ok=True)


def run_chronological_portfolio_daily(cohorts: list, data: dict, all_dates: pd.DatetimeIndex,
                                      *, cost_bps: float, starting_capital: float) -> dict:
    """Same accounting rules as task127's run_chronological_portfolio
    (no reused capital across cohorts, no negative cash/leverage, costs
    applied exactly once per round trip half-at-entry/half-at-exit,
    causal entry/exit reference fills already computed by build_cohorts)
    -- extended to mark EVERY trading day, not only month-ends, so a
    genuine daily drawdown/recovery-duration series can be computed."""
    realized = [c for c in cohorts if c.status == "REALIZED"]
    slot_capital = starting_capital / t127.HOLD_MONTHS

    # Precomputed, forward-filled close-price lookup per symbol -- O(1)
    # per (symbol, date) instead of re-filtering the whole DataFrame on
    # every call (the naive per-date boolean mask was the bottleneck on
    # ~1,900 trading days x up to 38 concurrently-marked symbols).
    close_lookup: dict[str, pd.Series] = {}
    for sym, df in data.items():
        s = df.set_index("date")["close"].reindex(all_dates).ffill()
        close_lookup[sym] = s

    cash = starting_capital
    open_positions: list[dict] = []
    equity_curve = []
    realized_log = []
    by_entry_date: dict = {}
    for c in realized:
        by_entry_date.setdefault(c.entry_date, []).append(c)
    by_exit_date: dict = {}
    for c in realized:
        by_exit_date.setdefault(c.exit_date, []).append(c)

    contribution_by_issuer: dict = {}

    for d in all_dates:
        for c in by_exit_date.get(d, []):
            pos = next((p for p in open_positions if p["cohort"] is c), None)
            if pos is None:
                continue
            proceeds = 0.0
            per_symbol_pl = {}
            for sym, n in pos["shares"].items():
                px = c.exit_prices[sym]
                proceeds += n * px
                per_symbol_pl[sym] = n * px - n * c.entry_prices[sym]
            cost = proceeds * (cost_bps / 10_000.0) / 2.0
            assert cash >= 0, "cash must never go negative before this credit"
            cash += proceeds - cost
            for sym, pl in per_symbol_pl.items():
                contribution_by_issuer[sym] = contribution_by_issuer.get(sym, 0.0) + pl
            realized_log.append({"cohort_formation": str(c.formation_date.date()),
                                "entry": str(c.entry_date.date()), "exit": str(c.exit_date.date()),
                                "symbols": c.symbols, "notional": pos["entry_notional"],
                                "proceeds_net": round(proceeds - cost, 2)})
            open_positions.remove(pos)
        for c in by_entry_date.get(d, []):
            if not c.symbols:
                continue
            notional_per_symbol = slot_capital / len(c.symbols)
            entry_cost = slot_capital * (cost_bps / 10_000.0) / 2.0
            required = slot_capital + entry_cost
            if required > cash + 1e-6:
                # no implicit leverage: skip this entry, record as unresolved
                realized_log.append({"cohort_formation": str(c.formation_date.date()),
                                    "entry": str(c.entry_date.date()), "status": "SKIPPED_INSUFFICIENT_CASH"})
                continue
            shares = {sym: notional_per_symbol / c.entry_prices[sym] for sym in c.symbols}
            cash -= required
            assert cash >= -1e-6, "cash must never go negative (no implicit leverage)"
            open_positions.append({"cohort": c, "shares": shares, "entry_notional": slot_capital})

        marked = 0.0
        unresolved = []
        for pos in open_positions:
            for sym, n in pos["shares"].items():
                px = close_lookup[sym].get(d)
                if pd.notna(px):
                    marked += n * float(px)
                else:
                    unresolved.append(sym)
        equity = cash + marked
        equity_curve.append({"date": str(d.date()), "cash": round(cash, 2),
                            "marked_positions": round(marked, 2), "equity": round(equity, 2),
                            "n_open_cohorts": len(open_positions),
                            "n_unresolved_stale_marks": len(unresolved)})

    eq = pd.Series([e["equity"] for e in equity_curve],
                   index=pd.to_datetime([e["date"] for e in equity_curve]))
    running_max = eq.cummax()
    # guard against a degenerate all-zero equity path (e.g. starting_capital=0,
    # every entry skipped) -- running_max is 0 throughout, division is undefined;
    # treat as a flat/no drawdown series rather than raising on all-NaN.
    if (running_max == 0).all():
        drawdown = pd.Series(0.0, index=eq.index)
    else:
        drawdown = (eq - running_max) / running_max.replace(0, pd.NA)
        drawdown = drawdown.fillna(0.0)
    trough_idx = drawdown.idxmin()
    max_drawdown_pct = float(drawdown.min() * 100)
    peak_idx = eq[:trough_idx].idxmax()
    recovery_idx = None
    peak_val = eq[peak_idx]
    after_trough = eq[trough_idx:]
    recovered = after_trough[after_trough >= peak_val]
    if len(recovered):
        recovery_idx = recovered.index[0]
    recovery_days = (recovery_idx - peak_idx).days if recovery_idx is not None else None

    start_capital = starting_capital
    end_equity = equity_curve[-1]["equity"] if equity_curve else None
    first_date, last_date = all_dates.min(), all_dates.max()
    elapsed_years = (last_date - first_date).days / 365.25
    total_return_pct = (round(100 * (end_equity / start_capital - 1.0), 4)
                        if end_equity is not None and start_capital > 0 else None)
    annualized_pct = (round(100 * ((end_equity / start_capital) ** (1 / elapsed_years) - 1.0), 4)
                      if end_equity and start_capital > 0 else None)

    n_util_days = sum(1 for e in equity_curve if e["n_open_cohorts"] > 0)
    turnover_events = len([r for r in realized_log if "proceeds_net" in r])

    return {
        "starting_capital": start_capital, "cost_bps": cost_bps,
        "n_realized_round_trips": turnover_events,
        "n_skipped_insufficient_cash": len([r for r in realized_log if r.get("status") == "SKIPPED_INSUFFICIENT_CASH"]),
        "ending_cash": round(cash, 2), "ending_marked_positions": round(sum(
            n * t127._price_on_or_none(data[sym], last_date, "close") or 0
            for pos in open_positions for sym, n in pos["shares"].items()), 2) if open_positions else 0.0,
        "ending_equity": end_equity, "n_open_positions_at_end": len(open_positions),
        "open_position_symbols_at_end": sorted({s for p in open_positions for s in p["shares"]}),
        "total_return_pct": total_return_pct, "annualized_return_pct": annualized_pct,
        "elapsed_years": round(elapsed_years, 2),
        "max_drawdown_pct": round(max_drawdown_pct, 4),
        "drawdown_peak_date": str(peak_idx.date()) if peak_idx is not None else None,
        "drawdown_trough_date": str(trough_idx.date()) if trough_idx is not None else None,
        "drawdown_recovery_date": str(recovery_idx.date()) if recovery_idx is not None else None,
        "drawdown_recovery_days": recovery_days,
        "recovery_status": ("RECOVERED" if recovery_days is not None else "NOT_RECOVERED_WITHIN_WINDOW"),
        "capital_utilization_pct_of_days_with_any_open_position": round(100 * n_util_days / len(equity_curve), 2),
        "contribution_by_issuer_net_pl": {k: round(v, 2) for k, v in
                                         sorted(contribution_by_issuer.items(), key=lambda kv: -kv[1])},
        "equity_curve": equity_curve, "realized_trades": realized_log,
    }


def run_spy_chronological(spy: pd.DataFrame, all_dates: pd.DatetimeIndex, *,
                          starting_capital: float) -> dict:
    """SAME starting capital, SAME dates, marked DAILY, fully invested
    from day 1 (the standard buy-and-hold convention) -- disclosed as a
    DIFFERENT capital-deployment timing than the baseline's ramp-up."""
    first_d = all_dates.min()
    start_px = t127._price_on_or_none(spy, first_d, "close")
    shares = starting_capital / start_px
    curve = []
    for d in all_dates:
        px = t127._price_on_or_none(spy, d, "close")
        if px is None:
            prior = spy[spy["date"] <= d]
            px = float(prior.iloc[-1]["close"]) if len(prior) else start_px
        curve.append({"date": str(d.date()), "equity": round(shares * px, 2)})
    eq = pd.Series([c["equity"] for c in curve], index=pd.to_datetime([c["date"] for c in curve]))
    running_max = eq.cummax()
    dd = (eq - running_max) / running_max
    trough_idx = dd.idxmin()
    peak_idx = eq[:trough_idx].idxmax()
    after = eq[trough_idx:]
    recovered = after[after >= eq[peak_idx]]
    recovery_idx = recovered.index[0] if len(recovered) else None
    end_equity = curve[-1]["equity"]
    elapsed_years = (all_dates.max() - first_d).days / 365.25
    return {
        "starting_capital": starting_capital, "ending_equity": end_equity,
        "total_return_pct": round(100 * (end_equity / starting_capital - 1.0), 4),
        "annualized_return_pct": round(100 * ((end_equity / starting_capital) ** (1 / elapsed_years) - 1.0), 4),
        "elapsed_years": round(elapsed_years, 2),
        "max_drawdown_pct": round(float(dd.min() * 100), 4),
        "drawdown_peak_date": str(peak_idx.date()), "drawdown_trough_date": str(trough_idx.date()),
        "drawdown_recovery_date": str(recovery_idx.date()) if recovery_idx is not None else None,
        "drawdown_recovery_days": (recovery_idx - peak_idx).days if recovery_idx is not None else None,
        "capital_deployment": "FULLY_INVESTED_FROM_DAY_1 -- different timing than the baseline's ramp-up",
        "equity_curve": curve,
    }


def main() -> int:
    data = t127.load_all()
    spy = pd.read_csv(t127.D2 / "SPY.csv", usecols=["date", "open", "close"], parse_dates=["date"])
    spy = spy.sort_values("date").drop_duplicates("date", keep="last").reset_index(drop=True)
    all_dates = pd.DatetimeIndex(sorted(set().union(*[set(df["date"]) for df in data.values()])))

    benchmark1_cohorts = t127.build_cohorts(data, all_dates, select_top_tercile=False)
    strategy_cohorts = t127.build_cohorts(data, all_dates, select_top_tercile=True)

    STARTING_CAPITAL = 100_000.0

    b1_base = run_chronological_portfolio_daily(benchmark1_cohorts, data, all_dates,
                                                cost_bps=t127.COST_BPS_ROUND_TRIP, starting_capital=STARTING_CAPITAL)
    b1_adv = run_chronological_portfolio_daily(benchmark1_cohorts, data, all_dates,
                                               cost_bps=t127.ADVERSE_COST_BPS_ROUND_TRIP, starting_capital=STARTING_CAPITAL)
    strategy_a_daily = run_chronological_portfolio_daily(strategy_cohorts, data, all_dates,
                                                          cost_bps=t127.COST_BPS_ROUND_TRIP, starting_capital=STARTING_CAPITAL)
    spy_chrono = run_spy_chronological(spy, all_dates, starting_capital=STARTING_CAPITAL)

    result = {
        "starting_capital_research_only": STARTING_CAPITAL,
        "note": "This $100,000 research pool is entirely separate from and unconnected to the "
               "production V2 $300k paper campaign or any live ledger.",
        "benchmark_B1_chronological_base_cost": {k: v for k, v in b1_base.items()
                                                 if k not in ("equity_curve", "realized_trades")},
        "benchmark_B1_chronological_adverse_cost": {k: v for k, v in b1_adv.items()
                                                    if k not in ("equity_curve", "realized_trades")},
        "strategy_A_chronological_daily_base_cost": {k: v for k, v in strategy_a_daily.items()
                                                      if k not in ("equity_curve", "realized_trades")},
        "spy_chronological_same_capital_same_dates": {k: v for k, v in spy_chrono.items() if k != "equity_curve"},
    }
    (OUT / "chronological_reconciliation.json").write_text(json.dumps(result, indent=2, default=str))
    (OUT / "benchmark_b1_equity_curve.json").write_text(json.dumps(b1_base["equity_curve"], indent=2, default=str))
    (OUT / "benchmark_b1_realized_trades.json").write_text(json.dumps(b1_base["realized_trades"], indent=2, default=str))

    print(json.dumps(result, indent=2, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
