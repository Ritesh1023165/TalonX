"""Task 118D Part 1/2 -- matched-runtime replay of Populations B (full
panel minus the 39-name scope) and C (full panel, A union B), run under
the EXACT SAME frozen contract/runtime as Population A
(run_baseline_a.py): same byte-synced service.py/form4_source.py/
store.py, same talonx_research.replay_engine, same 2024-09-01..2026-03-31
window, same 45-day rolling causal window, same 20bps cost convention,
same $10,000,000 research-convention starting cash, same fixed
$10,000/position sizing.

Population C is NOT simply Task 116's already-published 620-name figure
reused verbatim -- Task 116 ran under a pre-Task-117 vintage of
service.py/form4_source.py/store.py (missing execution_allowlist enforce-
ment and the F3 dissemination-slack fix), an unmatched runtime for this
comparison. Also, 6 of Population A's 39 names (ABCL, ACHR, ADC, AGNC,
MSTR, SHOP) are NOT members of Task 116's 620-name panel -- so re-using
that panel verbatim as "C" would violate C = A union B (C must be a
superset of A). C here is therefore explicitly constructed as
(Task 116's 620-name panel) union (the 39-name scope) = 626 names, and
B = C minus the 39 = 587 names -- both re-run fresh here, independently
(own capital pool, own concurrency/cooldown dynamics), not derived by
filtering a pre-existing trade ledger.

No parameter tuning. No promotion. Measurement only.
"""
from __future__ import annotations
import json
import sys
import time
from datetime import date, timedelta
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO))

DATA_ROOT = Path("C:/workspace/TalonX")
OUT = Path(__file__).resolve().parent

THE_39 = sorted("""AAPL ABCL ABT ACHR ADC ADP AFL AGNC AMAT AMD AVGO BAC BLK C CSCO CVX DELL
GOOGL IBM INTC JNJ JPM KO MA MCD MSFT MSTR NUE NVDA ORCL PG PYPL SHOP STX
TSLA UNH V VRT WMT""".split())

START, END = "2024-09-01", "2026-03-31"
COST_BPS = 20
STARTING_CASH = 10_000_000.0


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

    panel_620 = sorted(f.stem.upper() for f in bar_dirs[0].glob("*.csv"))
    C_names = sorted(set(panel_620) | set(THE_39))
    B_names = sorted(set(C_names) - set(THE_39))
    print(f"panel_620={len(panel_620)}  C(=panel_620 U THE_39)={len(C_names)}  "
          f"B(=C - THE_39)={len(B_names)}  overlap(panel_620,THE_39)="
          f"{len(set(panel_620) & set(THE_39))}")
    (OUT / "reconciliation" / "population_manifest.json").write_text(json.dumps({
        "A_the_39": THE_39,
        "panel_620_source": "task95g_broad_cross_sectional/_daily file listing (matches Task 116's reported 620-name panel size exactly)",
        "panel_620": panel_620,
        "C_full_panel_A_union_B": C_names,
        "B_remaining_panel_excl_A": B_names,
        "names_in_A_not_in_task116_620_panel": sorted(set(THE_39) - set(panel_620)),
    }, indent=2))

    panel1 = {f.stem.upper() for f in bar_dirs[0].glob("*.csv")}
    panel2 = {f.stem.upper() for f in bar_dirs[1].glob("*.csv")}

    _all_cache: dict | None = None

    def load_records(symbols):
        nonlocal _all_cache
        if _all_cache is None:
            _all_cache = list(form4_source.from_research_parquet(
                str(parquet), since=date.fromisoformat("2019-01-01")))
            _all_cache.sort(key=lambda r: r.filing_date)
        syms = set(symbols)
        return [r for r in _all_cache if r.symbol in syms]

    def run_population(tag: str, names: list[str]):
        t0 = time.monotonic()
        covered = sorted(set(names) & (panel1 | panel2))
        uncovered = sorted(set(names) - (panel1 | panel2))
        recs = load_records(names)
        recs_sorted = sorted(recs, key=lambda r: r.filing_date)

        def provider(as_of):
            lo = as_of - timedelta(days=45)
            return [r for r in recs_sorted if lo <= r.filing_date <= as_of]

        ledger = OUT / f"replay_v2_lane_{tag}.db"
        res = run_chronological_replay(
            start=START, end=END, ledger_path=ledger, bar_dirs=bar_dirs,
            records_provider=provider, starting_cash=STARTING_CASH)
        rd = res.to_dict()
        (OUT / f"baseline_{tag}_replay_result.json").write_text(json.dumps(rd, indent=2, default=str))

        trades = rd["trades"]
        by_ep: dict[str, dict] = {}
        for t in trades:
            by_ep.setdefault(t["episode_id"], {"symbol": t["symbol"]})[t["action"]] = t
        closed = []
        for eid, legs in by_ep.items():
            b, s = legs.get("BUY"), legs.get("SELL")
            if b is None or s is None:
                continue
            gross_ret = (s["execution_price"] - b["execution_price"]) / b["execution_price"]
            net_ret = gross_ret - COST_BPS / 10_000.0
            closed.append({"episode_id": eid, "symbol": legs["symbol"],
                           "entry": b["execution_price"], "exit": s["execution_price"],
                           "net_return_20bps": net_ret,
                           "net_pnl_usd": 10_000.0 * net_ret})
        n = len(closed)
        elapsed = time.monotonic() - t0
        summary = {
            "tag": tag, "n_symbols_requested": len(names),
            "n_symbols_price_covered": len(covered), "n_symbols_price_uncovered": len(uncovered),
            "uncovered_symbols": uncovered,
            "fingerprint": fp, "window": {"start": START, "end": END},
            "cost_convention_bps_round_trip": COST_BPS,
            "starting_cash_usd": STARTING_CASH,
            "episode_dispositions": rd["activity"]["processed_episode_dispositions"],
            "n_closed_trades": n,
            "n_distinct_issuers": len({c["symbol"] for c in closed}),
            "net_expectancy_mean_20bps": (sum(c["net_return_20bps"] for c in closed) / n) if n else None,
            "win_rate": (sum(1 for c in closed if c["net_return_20bps"] > 0) / n) if n else None,
            "total_net_pnl_usd": sum(c["net_pnl_usd"] for c in closed),
            "elapsed_seconds": round(elapsed, 1),
            "portfolio": rd.get("portfolio"),
        }
        gross_win = sum(c["net_return_20bps"] for c in closed if c["net_return_20bps"] > 0)
        gross_loss = -sum(c["net_return_20bps"] for c in closed if c["net_return_20bps"] <= 0)
        summary["profit_factor"] = (gross_win / gross_loss) if gross_loss > 0 else None
        (OUT / f"baseline_{tag}_summary.json").write_text(json.dumps(summary, indent=2, default=str))
        with open(OUT / "reconciliation" / f"trades_{tag}.csv", "w", newline="") as f:
            import csv
            w = csv.DictWriter(f, fieldnames=["episode_id", "symbol", "entry", "exit",
                                              "net_return_20bps", "net_pnl_usd"])
            w.writeheader()
            w.writerows(closed)
        print(f"[{tag}] symbols={len(names)} covered={len(covered)} uncovered={uncovered} "
              f"closed_trades={n} issuers={summary['n_distinct_issuers']} "
              f"net_mean={summary['net_expectancy_mean_20bps']} PF={summary['profit_factor']} "
              f"win_rate={summary['win_rate']} elapsed={elapsed:.1f}s")
        return summary

    run_population("B", B_names)
    run_population("C", C_names)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
