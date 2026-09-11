"""Task 118 Part 2B -- trade-level reconciliation of the exact 39-name V2
baseline (docs/research/TASK118_BASELINE_A_RESULTS.md). Reads the already-
committed replay artifacts (never re-runs the replay; measurement-only,
no re-simulation, no parameter change) and produces sanitized CSVs:
  reconciliation/episodes.csv   -- all 17 episode dispositions
  reconciliation/trades.csv     -- all 10 closed round trips, BUY+SELL legs
"""
from __future__ import annotations
import csv
import json
import sqlite3
from pathlib import Path

OUT = Path(__file__).resolve().parent
REC = OUT / "reconciliation"
REC.mkdir(exist_ok=True)

con = sqlite3.connect(f"file:{OUT / 'replay_v2_lane.db'}?mode=ro", uri=True)
con.row_factory = sqlite3.Row
cur = con.cursor()

# ---- episodes ----
cur.execute("""SELECT episode_id, symbol, issuer_cik, eligible_entry_session,
               disposition, detail FROM processed_episodes
               ORDER BY eligible_entry_session, episode_id""")
episodes = [dict(r) for r in cur.fetchall()]
with open(REC / "episodes.csv", "w", newline="") as f:
    w = csv.DictWriter(f, fieldnames=["episode_id", "symbol", "issuer_cik",
                                       "eligible_entry_session", "disposition", "detail"])
    w.writeheader()
    w.writerows(episodes)

# ---- trades (BUY/SELL legs, joined into closed round trips) ----
rd = json.loads((OUT / "baseline_a_replay_result.json").read_text())
trades = rd["trades"]
by_ep: dict[str, dict] = {}
for t in trades:
    by_ep.setdefault(t["episode_id"], {})[t["action"]] = t

ep_by_id = {e["episode_id"]: e for e in episodes}
COST_BPS = 20
rows = []
for eid, legs in by_ep.items():
    b, s = legs.get("BUY"), legs.get("SELL")
    if b is None or s is None:
        continue
    ep = ep_by_id.get(eid, {})
    gross_ret = (s["execution_price"] - b["execution_price"]) / b["execution_price"]
    net_ret = gross_ret - COST_BPS / 10_000.0
    net_pnl_usd = b["position_cost"] * net_ret
    rows.append({
        "episode_id": eid, "symbol": b["symbol"], "issuer_cik": ep.get("issuer_cik"),
        "eligible_entry_session": ep.get("eligible_entry_session"),
        "entry_date": b["executed_at"], "exit_date": s["executed_at"],
        "trading_days_held": s.get("trading_days_held"),
        "entry_price": b["execution_price"], "exit_price": s["execution_price"],
        "shares": b["shares"], "position_cost_usd": b["position_cost"],
        "gross_return_pct": round(gross_ret * 100, 4),
        "cost_bps_round_trip": COST_BPS,
        "net_return_pct": round(net_ret * 100, 4),
        "net_pnl_usd": round(net_pnl_usd, 2),
        "win": net_ret > 0,
        "pricing_source_provenance": "local bar CSV (task95g_broad_cross_sectional/_daily or "
                                      "task107a_form4_feasibility/_prices) -- frozen historical, "
                                      "NOT live composite-yf",
    })
rows.sort(key=lambda r: r["entry_date"])
with open(REC / "trades.csv", "w", newline="") as f:
    w = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
    w.writeheader()
    w.writerows(rows)

# ---- summary check ----
n = len(rows)
net_mean = sum(r["net_return_pct"] for r in rows) / n
wins = sum(1 for r in rows if r["win"])
total_net_pnl = sum(r["net_pnl_usd"] for r in rows)
print(f"episodes: {len(episodes)}  closed trades: {n}  wins: {wins}  "
      f"net_mean_pct: {net_mean:.3f}  total_net_pnl_usd: {total_net_pnl:.2f}")

# concentration: MSTR share of total ABSOLUTE net pnl
by_sym_abs = {}
for r in rows:
    by_sym_abs[r["symbol"]] = by_sym_abs.get(r["symbol"], 0.0) + abs(r["net_pnl_usd"])
tot_abs = sum(by_sym_abs.values())
print("issuer abs-P&L share:", {k: round(v/tot_abs*100, 1) for k, v in by_sym_abs.items()})

# ---- cost-convention reconciliation: ledger (GROSS, no cost deducted by
# V2Service itself) vs the 20bps-net figure this report publishes ----
portfolio = rd.get("portfolio")
ledger_gross_pnl = portfolio["ending_cash"] - portfolio["starting_cash"]
reported_net_pnl = sum(r["net_pnl_usd"] for r in rows)
cost_total = sum(r["position_cost_usd"] for r in rows) * (COST_BPS / 10_000.0)
print(f"ledger gross P&L (V2Service ledger, cost NOT deducted): {ledger_gross_pnl:.2f}")
print(f"reported net P&L (20bps applied once, post-hoc):        {reported_net_pnl:.2f}")
print(f"total 20bps round-trip cost ({n} trades x $10,000 notional): {cost_total:.2f}")
print(f"reconciles (gross - cost == net, within 1 cent): "
      f"{abs((ledger_gross_pnl - cost_total) - reported_net_pnl) < 0.01}")

# ---- REAL portfolio equity-curve drawdown (using portfolio_cash_after,
# the actual $10,000,000-book chronological cash trace) vs the published
# -42.7% CUMULATIVE TRADE-RETURN running-sum figure -- these are NOT the
# same quantity; see docs/research/TASK118_BASELINE_RECONCILIATION.md ----
cash_trace = sorted(
    [(t["executed_at"], t["portfolio_cash_after"]) for t in trades],
    key=lambda x: x[0])
peak_cash = portfolio["starting_cash"]
max_dd_usd = 0.0
max_dd_pct = 0.0
for _, cash in cash_trace:
    peak_cash = max(peak_cash, cash)
    dd_usd = cash - peak_cash
    dd_pct = dd_usd / peak_cash
    if dd_usd < max_dd_usd:
        max_dd_usd = dd_usd
        max_dd_pct = dd_pct
print(f"REAL portfolio equity drawdown (on $10,000,000 book): "
      f"{max_dd_usd:.2f} USD = {max_dd_pct*100:.4f}% of peak book value")
print(f"(published 'max_drawdown_equal_weight_running_return' -42.7% is a "
      f"cumulative-trade-RETURN running-sum in return-percentage-points, "
      f"NOT this portfolio-equity drawdown -- see report)")

# ---- max concurrent notional exposure (for the $300k-campaign-capacity
# diagnostic: would a $300k cash constraint ever have been binding at the
# frozen equal-notional $10,000/position sizing?) ----
events = []
for r in rows:
    events.append((r["entry_date"], 1, r["position_cost_usd"]))
    events.append((r["exit_date"], -1, r["position_cost_usd"]))
events.sort(key=lambda x: (x[0], x[1]))  # exits (-1) before entries (+1) on ties
open_notional = 0.0
max_open_notional = 0.0
for _, sign, notional in events:
    open_notional += sign * notional
    max_open_notional = max(max_open_notional, open_notional)
print(f"max concurrent notional exposure across the 10 trades: ${max_open_notional:,.2f} "
      f"(vs $300,000 live campaign cash / $10,000,000 research cash)")
