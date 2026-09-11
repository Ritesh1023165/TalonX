"""
Task 118 Part 2C -- $300,000 live-campaign-sizing DIAGNOSTIC re-run of the
exact 39-name V2 baseline (separately labelled from the primary $10,000,000
research-convention baseline in run_baseline_a.py; same window/scope/cost,
only starting_cash differs). Purpose: determine whether the live campaign's
$300,000 cash constraint (vs the $10,000,000 research sizing) would ever
have been binding at the frozen equal-notional $10,000/position sizing --
i.e. would the $300k campaign have skipped any entry for lack of available
cash that the $10M run took. Per-position sizing is unchanged (equal-notional
TALONX_V2_ALLOCATION_USD default, independent of starting_cash).

Same engine/data/window/manifest/cost convention as run_baseline_a.py -- see
that file's header for full provenance. No parameter tuning, no promotion.
"""
from __future__ import annotations
import json
import sys
from datetime import date, timedelta
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO))

DATA_ROOT = Path("C:/workspace/TalonX")   # frozen release worktree -- static historical artifacts only
OUT = Path(__file__).resolve().parent

THE_39 = sorted("""AAPL ABCL ABT ACHR ADC ADP AFL AGNC AMAT AMD AVGO BAC BLK C CSCO CVX DELL
GOOGL IBM INTC JNJ JPM KO MA MCD MSFT MSTR NUE NVDA ORCL PG PYPL SHOP STX
TSLA UNH V VRT WMT""".split())

START, END = "2024-09-01", "2026-03-31"     # Task 116 usable window (parquet ends 2026-03-31)
COST_BPS = 20                                # preregistered cost convention (Task 107B/112R/116)
STARTING_CASH = 300_000.0                    # DIAGNOSTIC: live campaign sizing (vs run_baseline_a.py's
                                              # $10,000,000 research-convention sizing). Per-position
                                              # sizing is the same fixed $10,000/position either way.


def main() -> int:
    from talonx_research.versioning import v2_fingerprint
    from talonx_v2 import form4_source
    from talonx_research.replay_engine import run_chronological_replay

    fp = v2_fingerprint()
    if fp != "11107198c5b81237":
        print(f"FINGERPRINT MOVED: {fp} -- ABORT")
        return 1

    bar_dirs = [DATA_ROOT / "results/task95g_broad_cross_sectional/_daily",
                DATA_ROOT / "results/task107a_form4_feasibility/_prices"]
    parquet = DATA_ROOT / "results/task107a_form4_feasibility/_build/form4_open_market_txn.parquet"

    panel1 = {f.stem.upper() for f in bar_dirs[0].glob("*.csv")}
    panel2 = {f.stem.upper() for f in bar_dirs[1].glob("*.csv")}
    covered = sorted(set(THE_39) & (panel1 | panel2))
    uncovered = sorted(set(THE_39) - (panel1 | panel2))

    # Pre-load code-P records for the 39-name manifest ONLY, once (mirrors
    # talonx_research.validation's own caching pattern for a feasible 19-month
    # walk), then serve them per-tick under the SAME 45-day rolling window the
    # live/frozen V2Service._records() uses -- no additional causal relaxation.
    _all = [r for r in form4_source.from_research_parquet(
                str(parquet), symbols=set(THE_39), since=date.fromisoformat("2019-01-01"))]
    _all.sort(key=lambda r: r.filing_date)

    def provider(as_of):
        lo = as_of - timedelta(days=45)
        return [r for r in _all if lo <= r.filing_date <= as_of]

    ledger = OUT / "replay_v2_lane_300k.db"   # under results/ in the RESEARCH worktree -- never the live one
    res = run_chronological_replay(
        start=START, end=END, ledger_path=ledger, bar_dirs=bar_dirs,
        records_provider=provider, starting_cash=STARTING_CASH)

    rd = res.to_dict()
    (OUT / "baseline_a_300k_replay_result.json").write_text(json.dumps(rd, indent=2, default=str))

    trades = rd["trades"]
    buys = [t for t in trades if t["action"] == "BUY"]
    sells = [t for t in trades if t["action"] == "SELL"]

    # ---- close-out P&L per episode, cost-applied both legs (20 bps round trip) ----
    by_episode: dict[str, dict] = {}
    for t in trades:
        by_episode.setdefault(t["episode_id"], {"symbol": t["symbol"]})[t["action"]] = t

    closed = []
    for eid, legs in by_episode.items():
        b, s = legs.get("BUY"), legs.get("SELL")
        if b is None or s is None:
            continue
        entry_px = b.get("execution_price")
        exit_px = s.get("execution_price")
        if entry_px is None or exit_px is None:
            continue
        gross_ret = (exit_px - entry_px) / entry_px
        net_ret = gross_ret - (COST_BPS / 10_000.0)   # round-trip cost applied once, matches Task 116 convention
        closed.append({"episode_id": eid, "symbol": legs["symbol"],
                       "entry": entry_px, "exit": exit_px,
                       "gross_return": gross_ret, "net_return_20bps": net_ret})

    n = len(closed)
    net_mean = sum(c["net_return_20bps"] for c in closed) / n if n else None
    wins = [c for c in closed if c["net_return_20bps"] > 0]
    losses = [c for c in closed if c["net_return_20bps"] <= 0]
    gross_win = sum(c["net_return_20bps"] for c in wins)
    gross_loss = -sum(c["net_return_20bps"] for c in losses)
    pf = (gross_win / gross_loss) if gross_loss > 0 else (float("inf") if gross_win > 0 else None)
    win_rate = (len(wins) / n) if n else None

    # concentration: largest single issuer's share of total net P&L (equal-weight units)
    by_sym: dict[str, float] = {}
    for c in closed:
        by_sym[c["symbol"]] = by_sym.get(c["symbol"], 0.0) + c["net_return_20bps"]
    total_net = sum(by_sym.values())
    top_issuer_share = (max(by_sym.values()) / total_net) if (by_sym and total_net > 0) else None

    # simple running-return drawdown (equal-weight, chronological by entry)
    closed_sorted = sorted(closed, key=lambda c: c["episode_id"])
    running = 0.0
    peak = 0.0
    max_dd = 0.0
    for c in closed_sorted:
        running += c["net_return_20bps"]
        peak = max(peak, running)
        max_dd = min(max_dd, running - peak)

    summary = {
        "fingerprint": fp,
        "window": {"start": START, "end": END,
                  "reason": "SEC Form4 bulk parquet coverage ends 2026-03-31; requested-vs-usable per Task 116"},
        "manifest": {"names": THE_39, "resolved_utc": "2026-09-11 (docs/research/TASK118_INVENTORY.md)",
                    "covered_by_price_panel": covered, "uncovered_by_price_panel": uncovered},
        "cost_convention_bps_round_trip": COST_BPS,
        "starting_cash_research_convention_usd": STARTING_CASH,
        "note_starting_cash": "Task 116 research convention for statistical comparability; NOT the live "
                              "$300,000 / 20-slot campaign sizing -- see the note on that separately.",
        "episode_level": {"buys": len(buys), "sells": len(sells),
                          "closed_round_trips": n,
                          "exit_unresolved": len(res.exit_unresolved),
                          "open_at_end": len(res.open_at_end),
                          "processed_episode_dispositions": rd["activity"]["processed_episode_dispositions"]},
        "performance": {
            "n_closed_trades": n,
            "net_expectancy_mean_20bps": net_mean,
            "profit_factor": pf,
            "win_rate": win_rate,
            "max_drawdown_equal_weight_running_return": max_dd,
            "top_issuer_pnl_share": top_issuer_share,
            "by_issuer_net_return_sum": by_sym,
        },
        "external_sends": res.external_sends,
        "live_ledger_written": False,
    }
    (OUT / "baseline_a_300k_summary.json").write_text(json.dumps(summary, indent=2, default=str))
    print(json.dumps(summary, indent=2, default=str))
    return 0


if __name__ == "__main__":
    sys.exit(main())
