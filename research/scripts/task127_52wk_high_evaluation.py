"""
TASK 127 -- one frozen evaluation of a source-grounded, long-only
52-week-high candidate for TalonX's long-term paper-alert lane.

Reuses existing daily-bar datasets only (no new acquisition). Implements
exactly the contract frozen in docs/research/TASK127_FROZEN_LONG_TERM_PROTOCOL.md
BEFORE this script was run against any real return: tercile selection
by close/252-day-rolling-high, monthly formation with Jegadeesh-Titman-
style overlapping 6-month holds, causal next-month-open entry,
chronological $100k capital accounting with monthly marked equity, two
benchmarks (eligible-universe equal-weight, SPY buy-and-hold), and a
non-overlapping 6-month block bootstrap for uncertainty.
"""
from __future__ import annotations

import json
import sys
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np
import pandas as pd

RELEASE_ROOT = Path("C:/workspace/TalonX")
sys.path.insert(0, str(RELEASE_ROOT))
RESEARCH_ROOT = Path(__file__).resolve().parents[2]

OUT = RESEARCH_ROOT / "results" / "task127_52wk_high_evaluation"
OUT.mkdir(parents=True, exist_ok=True)

D1 = RELEASE_ROOT / "results/task95g_broad_cross_sectional/_daily"
D2 = RELEASE_ROOT / "results/task107a_form4_feasibility/_prices"

# ---------------------------------------------------------------------
# Frozen parameters (TASK127_FROZEN_LONG_TERM_PROTOCOL.md) -- fixed
# BEFORE any return was inspected.
# ---------------------------------------------------------------------
ROLLING_WINDOW_DAYS = 252
MIN_PRICE = 5.0
MIN_ELIGIBLE_POPULATION = 15
SELECTION_FRACTION = 0.30
HOLD_MONTHS = 6
TOTAL_BUDGET = 100_000.0
COST_BPS_ROUND_TRIP = 5.0
ADVERSE_COST_BPS_ROUND_TRIP = 15.0
MATERIALITY_BAND_BPS = 10.0
BOOTSTRAP_REPS = 5000
BOOTSTRAP_SEED = 127127

UNIVERSE_38 = [
    "AAPL", "ABCL", "ABT", "ACHR", "ADC", "ADP", "AFL", "AGNC", "AMAT", "AMD", "AVGO", "BAC",
    "BLK", "C", "CSCO", "CVX", "DELL", "GOOGL", "IBM", "INTC", "JNJ", "JPM", "KO", "MA", "MCD",
    "MSFT", "MSTR", "NUE", "NVDA", "ORCL", "PG", "PYPL", "STX", "TSLA", "UNH", "V", "VRT", "WMT",
]


def _load_symbol(sym: str) -> pd.DataFrame:
    p1, p2 = D1 / f"{sym}.csv", D2 / f"{sym}.csv"
    src = p1 if p1.exists() else p2
    df = pd.read_csv(src, usecols=["date", "open", "close"], parse_dates=["date"])
    df = df.sort_values("date").drop_duplicates("date", keep="last").reset_index(drop=True)
    df["nearness"] = df["close"] / df["close"].rolling(ROLLING_WINDOW_DAYS, min_periods=ROLLING_WINDOW_DAYS).max()
    df["history_days"] = np.arange(1, len(df) + 1)
    return df


def load_all() -> dict[str, pd.DataFrame]:
    return {s: _load_symbol(s) for s in UNIVERSE_38}


def _month_end_dates(all_dates: pd.DatetimeIndex) -> list[pd.Timestamp]:
    s = pd.Series(all_dates, index=all_dates)
    return sorted(s.groupby(s.dt.to_period("M")).max().tolist())


def _first_trading_day_on_or_after(all_dates: pd.DatetimeIndex, target_period: pd.Period) -> pd.Timestamp | None:
    cand = [d for d in all_dates if pd.Period(d, freq="M") == target_period]
    return min(cand) if cand else None


@dataclass
class Cohort:
    formation_date: pd.Timestamp
    entry_date: pd.Timestamp | None
    exit_date: pd.Timestamp | None
    symbols: list[str]
    entry_prices: dict = field(default_factory=dict)
    exit_prices: dict = field(default_factory=dict)
    excluded_symbols: dict = field(default_factory=dict)  # symbol -> reason
    status: str = "PENDING"  # PENDING / REALIZED / SKIPPED_NO_ELIGIBLE / SKIPPED_NO_ENTRY_DATA


def _select_cohort_symbols(data: dict[str, pd.DataFrame], formation_date: pd.Timestamp,
                           *, select_top_tercile: bool) -> tuple[list[str], dict]:
    """Returns (selected_symbols, exclusion_reasons_for_ineligible_symbols)."""
    eligible = []
    excluded = {}
    for sym, df in data.items():
        row = df[df["date"] == formation_date]
        if len(row) == 0:
            excluded[sym] = "no_bar_on_formation_date"
            continue
        r = row.iloc[0]
        if r["history_days"] < ROLLING_WINDOW_DAYS:
            excluded[sym] = "insufficient_trailing_history"
            continue
        if r["close"] < MIN_PRICE:
            excluded[sym] = "below_min_price_filter"
            continue
        if pd.isna(r["nearness"]):
            excluded[sym] = "nearness_undefined"
            continue
        eligible.append((sym, float(r["nearness"])))
    if len(eligible) < MIN_ELIGIBLE_POPULATION:
        return [], {"_pool_status": f"insufficient_eligible_population({len(eligible)})", **excluded}
    if select_top_tercile:
        eligible.sort(key=lambda x: x[1], reverse=True)
        n_select = max(1, round(len(eligible) * SELECTION_FRACTION))
        selected = [s for s, _ in eligible[:n_select]]
    else:
        selected = [s for s, _ in eligible]  # Benchmark 1: ALL eligible, no selection
    return selected, excluded


def _price_on_or_none(df: pd.DataFrame, date: pd.Timestamp, col: str) -> float | None:
    row = df[df["date"] == date]
    return float(row.iloc[0][col]) if len(row) else None


def build_cohorts(data: dict[str, pd.DataFrame], all_dates: pd.DatetimeIndex,
                  *, select_top_tercile: bool) -> list[Cohort]:
    formation_dates = _month_end_dates(all_dates)
    cohorts = []
    for fd in formation_dates:
        entry_period = pd.Period(fd, freq="M") + 1
        exit_period = entry_period + HOLD_MONTHS
        entry_date = _first_trading_day_on_or_after(all_dates, entry_period)
        exit_date = _first_trading_day_on_or_after(all_dates, exit_period)

        selected, excluded = _select_cohort_symbols(data, fd, select_top_tercile=select_top_tercile)
        c = Cohort(formation_date=fd, entry_date=entry_date, exit_date=exit_date, symbols=selected,
                  excluded_symbols=excluded)
        if not selected:
            c.status = "SKIPPED_NO_ELIGIBLE"
            cohorts.append(c)
            continue
        if entry_date is None:
            c.status = "SKIPPED_NO_ENTRY_DATA"
            cohorts.append(c)
            continue
        if exit_date is None:
            c.status = "PENDING"  # forward window not yet complete in the available data
            cohorts.append(c)
            continue

        entry_prices, exit_prices, kept = {}, {}, []
        for sym in selected:
            ep = _price_on_or_none(data[sym], entry_date, "open")
            xp = _price_on_or_none(data[sym], exit_date, "open")
            if ep is None:
                c.excluded_symbols[sym] = "missing_entry_bar"
                continue
            if xp is None:
                c.excluded_symbols[sym] = "missing_exit_bar"
                continue
            entry_prices[sym] = ep
            exit_prices[sym] = xp
            kept.append(sym)
        c.symbols = kept
        c.entry_prices = entry_prices
        c.exit_prices = exit_prices
        c.status = "REALIZED" if kept else "SKIPPED_NO_ELIGIBLE"
        cohorts.append(c)
    return cohorts


def cohort_gross_net_return(c: Cohort, cost_bps: float) -> tuple[float, float] | None:
    if c.status != "REALIZED" or not c.symbols:
        return None
    per_symbol_gross = [(c.exit_prices[s] / c.entry_prices[s] - 1.0) for s in c.symbols]
    gross = float(np.mean(per_symbol_gross))
    net = gross - cost_bps / 10_000.0
    return gross, net


def run_chronological_portfolio(cohorts: list[Cohort], data: dict[str, pd.DataFrame],
                                all_dates: pd.DatetimeIndex, *, cost_bps: float) -> dict:
    """Chronological capital accounting: cash + marked open positions ->
    equity, marked at each calendar month-end using that month's own
    close price for every symbol still held."""
    realized = [c for c in cohorts if c.status == "REALIZED"]
    month_ends = _month_end_dates(all_dates)
    slot_capital = TOTAL_BUDGET / HOLD_MONTHS

    cash = TOTAL_BUDGET
    open_positions: list[dict] = []  # {cohort, shares: {sym: n}, entry_notional}
    equity_curve = []
    realized_log = []
    by_entry_date = {}
    for c in realized:
        by_entry_date.setdefault(c.entry_date, []).append(c)
    by_exit_date = {}
    for c in realized:
        by_exit_date.setdefault(c.exit_date, []).append(c)

    for d in all_dates:
        # exits first (free capital before new entries the same day, if any)
        for c in by_exit_date.get(d, []):
            pos = next((p for p in open_positions if p["cohort"] is c), None)
            if pos is None:
                continue
            proceeds = 0.0
            for sym, n in pos["shares"].items():
                proceeds += n * c.exit_prices[sym]
            cost = proceeds * (cost_bps / 10_000.0) / 2.0  # half the round-trip cost charged at exit
            cash += proceeds - cost
            realized_log.append({"cohort_formation": str(c.formation_date.date()),
                                "entry": str(c.entry_date.date()), "exit": str(c.exit_date.date()),
                                "symbols": c.symbols, "notional": pos["entry_notional"],
                                "proceeds_net": proceeds - cost})
            open_positions.remove(pos)
        # entries
        for c in by_entry_date.get(d, []):
            if not c.symbols:
                continue
            notional_per_symbol = slot_capital / len(c.symbols)
            entry_cost = slot_capital * (cost_bps / 10_000.0) / 2.0
            shares = {sym: (notional_per_symbol) / c.entry_prices[sym] for sym in c.symbols}
            cash -= slot_capital + entry_cost
            open_positions.append({"cohort": c, "shares": shares, "entry_notional": slot_capital})
        # mark at month-end
        if d in month_ends:
            marked = 0.0
            for pos in open_positions:
                for sym, n in pos["shares"].items():
                    px = _price_on_or_none(data[sym], d, "close")
                    if px is not None:
                        marked += n * px
                    else:
                        # last known close on/before d, causal (never a future price)
                        df = data[sym]
                        prior = df[df["date"] <= d]
                        if len(prior):
                            marked += n * float(prior.iloc[-1]["close"])
            equity = cash + marked
            equity_curve.append({"date": str(d.date()), "cash": round(cash, 2),
                                "marked_positions": round(marked, 2), "equity": round(equity, 2),
                                "n_open_cohorts": len(open_positions)})

    eq = pd.Series([e["equity"] for e in equity_curve], index=[e["date"] for e in equity_curve])
    running_max = eq.cummax()
    drawdown = (eq - running_max) / running_max
    max_drawdown_pct = float(drawdown.min() * 100) if len(drawdown) else None

    return {
        "cost_bps": cost_bps, "ending_cash": round(cash, 2),
        "ending_marked_equity": round(equity_curve[-1]["equity"], 2) if equity_curve else None,
        "n_realized_cohorts": len(realized_log), "n_open_at_end": len(open_positions),
        "equity_curve": equity_curve, "max_drawdown_pct": max_drawdown_pct,
        "realized_trades": realized_log,
    }


def _nonoverlapping_block_bootstrap(cohort_returns: list[tuple[pd.Timestamp, float]]) -> dict:
    """Resamples NON-OVERLAPPING 6-calendar-month macro-blocks (each
    block's value = mean net return of cohorts whose FORMATION falls in
    that block) -- acknowledges overlapping holdings/common market
    dates rather than treating each monthly cohort as independent."""
    if not cohort_returns:
        return {"n_blocks": 0}
    dates = [d for d, _ in cohort_returns]
    start = min(dates).to_period("M")
    blocks: dict[int, list[float]] = {}
    for d, r in cohort_returns:
        months_since_start = (d.to_period("M") - start).n
        block_idx = months_since_start // HOLD_MONTHS
        blocks.setdefault(block_idx, []).append(r)
    block_means = np.array([np.mean(v) for v in blocks.values()])
    n_blocks = len(block_means)
    rng = np.random.default_rng(BOOTSTRAP_SEED)
    means = []
    for _ in range(BOOTSTRAP_REPS):
        idx = rng.integers(0, n_blocks, size=n_blocks)
        means.append(block_means[idx].mean())
    ci = [float(np.percentile(means, 2.5)), float(np.percentile(means, 97.5))]
    return {"n_blocks": n_blocks, "block_means_pct": [round(100 * m, 4) for m in block_means],
           "mean_ci_pct": [round(100 * c, 4) for c in ci],
           "method": f"non-overlapping {HOLD_MONTHS}-month block bootstrap, {BOOTSTRAP_REPS} reps, "
                    f"seed {BOOTSTRAP_SEED}, 95% percentile CI"}


def run_spy_benchmark(spy: pd.DataFrame, all_dates: pd.DatetimeIndex) -> dict:
    month_ends = _month_end_dates(all_dates)
    first_d, last_d = all_dates.min(), all_dates.max()
    start_px = _price_on_or_none(spy, first_d, "close")
    curve = []
    for d in month_ends:
        px = _price_on_or_none(spy, d, "close")
        if px is not None and start_px:
            curve.append({"date": str(d.date()), "equity": round(TOTAL_BUDGET * px / start_px, 2)})
    eq = pd.Series([c["equity"] for c in curve])
    running_max = eq.cummax()
    dd = float(((eq - running_max) / running_max).min() * 100) if len(eq) else None
    end_px = _price_on_or_none(spy, last_d, "close")
    total_return_pct = round(100 * (end_px / start_px - 1.0), 4) if (start_px and end_px) else None
    return {"start_date": str(first_d.date()), "end_date": str(last_d.date()),
           "total_return_pct": total_return_pct, "max_drawdown_pct": dd, "equity_curve": curve}


def main() -> int:
    data = load_all()
    spy = pd.read_csv(D2 / "SPY.csv", usecols=["date", "open", "close"], parse_dates=["date"])
    spy = spy.sort_values("date").drop_duplicates("date", keep="last").reset_index(drop=True)

    all_dates = pd.DatetimeIndex(sorted(set().union(*[set(df["date"]) for df in data.values()])))

    strategy_cohorts = build_cohorts(data, all_dates, select_top_tercile=True)
    benchmark1_cohorts = build_cohorts(data, all_dates, select_top_tercile=False)

    def _summ(cohorts: list[Cohort], label: str) -> dict:
        realized = [c for c in cohorts if c.status == "REALIZED"]
        pending = [c for c in cohorts if c.status == "PENDING"]
        skipped_elig = [c for c in cohorts if c.status == "SKIPPED_NO_ELIGIBLE"]
        skipped_entry = [c for c in cohorts if c.status == "SKIPPED_NO_ENTRY_DATA"]
        rets = [cohort_gross_net_return(c, COST_BPS_ROUND_TRIP) for c in realized]
        rets = [r for r in rets if r is not None]
        gross = [g for g, n in rets]
        net = [n for g, n in rets]
        rets_adv = [cohort_gross_net_return(c, ADVERSE_COST_BPS_ROUND_TRIP) for c in realized]
        net_adv = [n for g, n in rets_adv if n is not None]
        issuers = sorted({s for c in realized for s in c.symbols})
        return {
            "label": label, "n_formation_months": len(cohorts),
            "n_realized_cohorts": len(realized), "n_pending_incomplete_forward_window": len(pending),
            "n_skipped_insufficient_eligible": len(skipped_elig), "n_skipped_no_entry_data": len(skipped_entry),
            "n_distinct_issuers_selected": len(issuers),
            "gross_mean_pct": round(100 * float(np.mean(gross)), 4) if gross else None,
            "net_mean_pct": round(100 * float(np.mean(net)), 4) if net else None,
            "net_median_pct": round(100 * float(np.median(net)), 4) if net else None,
            "net_win_rate": round(float(np.mean([r > 0 for r in net])), 4) if net else None,
            "net_worst_5pct_mean_pct": (round(100 * float(np.mean(sorted(net)[:max(1, len(net)//20)])), 4)
                                        if net else None),
            "net_mean_pct_adverse_cost_15bps": round(100 * float(np.mean(net_adv)), 4) if net_adv else None,
        }

    strategy_summary = _summ(strategy_cohorts, "A_tercile_selection")
    benchmark1_summary = _summ(benchmark1_cohorts, "B1_eligible_universe_equal_weight")

    # issuer concentration for strategy
    realized_a = [c for c in strategy_cohorts if c.status == "REALIZED"]
    by_issuer = {}
    for c in realized_a:
        for s in c.symbols:
            by_issuer[s] = by_issuer.get(s, 0) + 1
    strategy_summary["by_issuer_selection_counts"] = by_issuer

    # incremental estimand: per-formation-date paired (strategy - benchmark1) net return
    b1_by_date = {c.formation_date: cohort_gross_net_return(c, COST_BPS_ROUND_TRIP)
                 for c in benchmark1_cohorts if c.status == "REALIZED"}
    paired = []
    for c in realized_a:
        r_a = cohort_gross_net_return(c, COST_BPS_ROUND_TRIP)
        r_b = b1_by_date.get(c.formation_date)
        if r_a is not None and r_b is not None:
            paired.append((c.formation_date, r_a[1] - r_b[1]))
    incremental_mean_pct = round(100 * float(np.mean([r for _, r in paired])), 4) if paired else None
    incremental_bootstrap = _nonoverlapping_block_bootstrap(paired)

    # strategy's own uncertainty (absolute net return)
    strategy_returns_by_date = [(c.formation_date, cohort_gross_net_return(c, COST_BPS_ROUND_TRIP)[1])
                                for c in realized_a if cohort_gross_net_return(c, COST_BPS_ROUND_TRIP) is not None]
    strategy_bootstrap = _nonoverlapping_block_bootstrap(strategy_returns_by_date)

    portfolio_a = run_chronological_portfolio(strategy_cohorts, data, all_dates, cost_bps=COST_BPS_ROUND_TRIP)
    portfolio_a_adv = run_chronological_portfolio(strategy_cohorts, data, all_dates, cost_bps=ADVERSE_COST_BPS_ROUND_TRIP)
    spy_bench = run_spy_benchmark(spy, all_dates)

    result = {
        "universe": UNIVERSE_38, "n_universe": len(UNIVERSE_38),
        "data_window": {"first_date": str(all_dates.min().date()), "last_date": str(all_dates.max().date())},
        "strategy_A_tercile": strategy_summary,
        "benchmark_B1_eligible_universe": benchmark1_summary,
        "incremental_A_vs_B1": {"mean_pct": incremental_mean_pct, "uncertainty": incremental_bootstrap},
        "strategy_A_absolute_uncertainty": strategy_bootstrap,
        "portfolio_chronological_base_cost": {k: v for k, v in portfolio_a.items() if k != "realized_trades"},
        "portfolio_chronological_adverse_cost": {k: v for k, v in portfolio_a_adv.items() if k != "realized_trades"},
        "spy_benchmark": spy_bench,
    }
    (OUT / "task127_evaluation_results.json").write_text(json.dumps(result, indent=2, default=str))
    (OUT / "portfolio_a_realized_trades.json").write_text(json.dumps(portfolio_a["realized_trades"], indent=2, default=str))

    print(json.dumps({k: v for k, v in result.items() if k not in
                      ("portfolio_chronological_base_cost", "portfolio_chronological_adverse_cost", "spy_benchmark")},
                     indent=2, default=str))
    print("\nportfolio_chronological_base_cost:", json.dumps(
        {k: v for k, v in portfolio_a.items() if k not in ("equity_curve", "realized_trades")}, indent=2, default=str))
    print("\nspy_benchmark:", json.dumps({k: v for k, v in spy_bench.items() if k != "equity_curve"}, indent=2, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
