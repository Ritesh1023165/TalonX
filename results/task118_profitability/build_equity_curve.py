"""Task 118B Part 2 -- reconstruct REAL chronological equity
(cash + market value of open positions), replacing the cash-only
"drawdown" figure from Task118A's research corrections. Reads only the
already-committed, sanitized trades.csv (Task 118 baseline reconciliation)
plus the same frozen local daily-bar CSVs the baseline replay itself used
-- no new simulation, no parameter change, no live/production data touched.
"""
from __future__ import annotations
import csv
import json
from pathlib import Path
from datetime import date, timedelta

REPO = Path(__file__).resolve().parents[2]
DATA_ROOT = Path("C:/workspace/TalonX")
OUT = Path(__file__).resolve().parent
REC = OUT / "reconciliation"

BAR_DIRS = [DATA_ROOT / "results/task95g_broad_cross_sectional/_daily",
            DATA_ROOT / "results/task107a_form4_feasibility/_prices"]
COST_BPS = 20
HOLD_TD = 10  # frozen V2 contract: 10 trading-day hold


def load_daily_closes(symbol: str) -> dict[date, float]:
    closes: dict[date, float] = {}
    for d in BAR_DIRS:
        p = d / f"{symbol}.csv"
        if not p.exists():
            continue
        with open(p) as f:
            for row in csv.DictReader(f):
                try:
                    dt = date.fromisoformat(row["date"][:10])
                    closes[dt] = float(row["close"])
                except (KeyError, ValueError):
                    continue
    return closes


def trading_days_calendar(all_closes: dict[str, dict[date, float]]) -> list[date]:
    """Union of every date any covered symbol has a bar for, sorted --
    used as a proxy XNYS session calendar (no separate calendar dependency
    needed; every date here is, by construction, a date the underlying
    price data itself considers a trading day)."""
    days: set[date] = set()
    for d in all_closes.values():
        days |= set(d.keys())
    return sorted(days)


def nth_trading_day_after(cal: list[date], start: date, n: int) -> date | None:
    if start not in cal:
        # fall back: nearest trading day at or after start
        later = [d for d in cal if d >= start]
        if not later:
            return None
        start = later[0]
    idx = cal.index(start)
    tgt = idx + n
    return cal[tgt] if tgt < len(cal) else None


def main() -> int:
    trades = list(csv.DictReader(open(REC / "trades.csv")))
    symbols = sorted({t["symbol"] for t in trades})
    closes = {s: load_daily_closes(s) for s in symbols}
    cal = trading_days_calendar(closes)

    positions = []
    for t in trades:
        entry_d = date.fromisoformat(t["eligible_entry_session"])
        exit_d = nth_trading_day_after(cal, entry_d, HOLD_TD)
        if exit_d is None:
            exit_d = entry_d + timedelta(days=14)  # fallback, out-of-coverage tail
        positions.append({
            "symbol": t["symbol"], "episode_id": t["episode_id"],
            "entry_date": entry_d, "exit_date": exit_d,
            "entry_price": float(t["entry_price"]), "exit_price": float(t["exit_price"]),
            "shares": float(t["shares"]), "cost_usd": float(t["position_cost_usd"]),
        })
    positions.sort(key=lambda p: p["entry_date"])

    span_start = min(p["entry_date"] for p in positions)
    span_end = max(p["exit_date"] for p in positions)
    session_days = [d for d in cal if span_start <= d <= span_end]

    for BASE in (10_000_000.0, 300_000.0):
        cash = BASE
        rows = []
        peak = BASE
        max_dd_usd = 0.0
        max_dd_pct = 0.0
        peak_date = span_start
        trough_date = span_start
        missing_marks = []
        for d in session_days:
            # apply entry/exit cash events dated on this session
            for p in positions:
                if p["entry_date"] == d:
                    cash -= p["cost_usd"]
                if p["exit_date"] == d:
                    # SAME convention as reconcile.py: cost applied once to
                    # the round-trip RETURN, not to sell-side proceeds only
                    # -- keeps this equity build reconciling exactly to the
                    # already-published trade-level net P&L figures.
                    gross_ret = (p["exit_price"] - p["entry_price"]) / p["entry_price"]
                    net_ret = gross_ret - COST_BPS / 10_000.0
                    cash += p["cost_usd"] * (1 + net_ret)

            open_value = 0.0
            for p in positions:
                if p["entry_date"] <= d < p["exit_date"]:
                    if d == p["entry_date"]:
                        mark = p["entry_price"]
                    else:
                        mark = closes[p["symbol"]].get(d)
                        if mark is None:
                            missing_marks.append((p["symbol"], str(d)))
                            mark = p["entry_price"]  # last-known fallback, flagged above
                    open_value += p["shares"] * mark

            equity = cash + open_value
            peak_before = peak
            peak = max(peak, equity)
            dd_usd = equity - peak
            dd_pct = dd_usd / peak
            if dd_usd < max_dd_usd:
                max_dd_usd = dd_usd
                max_dd_pct = dd_pct
                trough_date = d
            if peak > peak_before:
                peak_date = d
            rows.append({"date": str(d), "cash": round(cash, 2), "open_value": round(open_value, 2),
                        "equity": round(equity, 2), "peak": round(peak, 2),
                        "drawdown_usd": round(equity - peak, 2),
                        "drawdown_pct": round((equity - peak) / peak * 100, 4)})

        tag = "10m" if BASE == 10_000_000.0 else "300k"
        with open(REC / f"equity_curve_{tag}.csv", "w", newline="") as f:
            w = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
            w.writeheader()
            w.writerows(rows)

        final_equity = rows[-1]["equity"]
        final_cash = rows[-1]["cash"]
        net_closed_trade_pnl = sum(
            p["cost_usd"] * (((p["exit_price"] - p["entry_price"]) / p["entry_price"]) - COST_BPS/10_000.0)
            for p in positions)
        print(f"--- base ${BASE:,.0f} ({tag}) ---")
        print(f"final cash: {final_cash:,.2f}  final equity: {final_equity:,.2f}  "
              f"starting: {BASE:,.2f}")
        print(f"reconciles to net closed-trade P&L: final_equity - starting = "
              f"{final_equity - BASE:,.2f} vs summed net_pnl = {net_closed_trade_pnl:,.2f} "
              f"(match={abs((final_equity-BASE) - net_closed_trade_pnl) < 0.01})")
        print(f"max equity drawdown: ${max_dd_usd:,.2f} = {max_dd_pct*100:.4f}%  "
              f"peak {peak_date} -> trough {trough_date}")
        print(f"missing marks (used entry-price fallback): {len(set(missing_marks))} "
              f"symbol-days: {sorted(set(missing_marks))[:10]}")
        print()

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
