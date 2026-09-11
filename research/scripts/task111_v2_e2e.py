"""
task111_v2_e2e.py -- Task 111 offline END-TO-END REPLAY QUALIFICATION harness
==========================================================================
Runs the whole-universe offline replay of the integrated V2 path
(Form4 -> cluster -> V2 Quant -> V2 Brain -> BUY -> local paper ->
multi-day persistence -> SELL -> official dispatch -> :8787/EOD) and
prints a qualification summary.  Deterministic; no network beyond the
daily-bar CSVs already on disk; no Telegram, no broker, no real capital.

  python research/scripts/task111_v2_e2e.py [--since 2019-06-03] [--cash 1000000]

Item (2) Redis round-trip, (3) fingerprint, (4) restart-under-load,
(5) dispatch dedup and (6) dashboard placement are covered by
tests/test_task111_v2_e2e.py -- run: pytest tests/test_task111_v2_e2e.py -q
"""
from __future__ import annotations

import argparse
import json
import sys
import tempfile
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / "results" / "task111_v2_e2e_replay"
OUT.mkdir(parents=True, exist_ok=True)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser("task111_v2_e2e")
    ap.add_argument("--since", default="2019-06-03")
    ap.add_argument("--cash", type=float, default=1_000_000.0)
    ap.add_argument("--form4-parquet",
                    default=str(ROOT / "results/task107a_form4_feasibility/_build/form4_open_market_txn.parquet"))
    ap.add_argument("--bar-dir", action="append", default=[
        str(ROOT / "results/task95g_broad_cross_sectional/_daily"),
        str(ROOT / "results/task107a_form4_feasibility/_prices"),
    ])
    args = ap.parse_args(argv)

    from talonx_v2 import form4_source, pipeline
    from talonx_v2.config import V2Config
    from talonx_v2.run import _bar_dir_lookup
    from talonx_v2.store import V2Store
    from talonx_backtest.reproducibility import get_strategy_version

    fp = get_strategy_version()
    print(f"Original strategy fingerprint (frozen): {fp}  "
          f"{'OK -- byte-identical' if fp == '2ae6216bca70' else 'CHANGED -- investigate!'}")

    db = str(Path(tempfile.mkdtemp()) / "task111_v2.db")
    cfg = V2Config(db_path=db)
    cfg.validate_frozen()
    store = V2Store(db, starting_cash=args.cash)

    records = form4_source.from_research_parquet(
        args.form4_parquet, since=date.fromisoformat(args.since))
    bars_lookup, price_lookup = _bar_dir_lookup([Path(p) for p in args.bar_dir])
    res = pipeline.run_replay(records, store=store, bars_lookup=bars_lookup,
                             price_lookup=price_lookup, config=cfg)

    pnl = round(sum(e["realized_pnl_usd"] for e in res.exits), 2)
    span_yrs = 2026 - int(args.since[:4]) + 1
    tally: dict[str, int] = {}
    for s in res.skipped:
        tally[s["reason"]] = tally.get(s["reason"], 0) + 1
    out = {
        "strategy_fingerprint": fp,
        "records": len(records),
        "episodes_detected": res.episodes_detected,
        "signals_built": res.signals_built,
        "entries": len(res.entries),
        "exits": len(res.exits),
        "open_at_end": store.n_open(),
        "realized_pnl_usd": pnl,
        "pnl_sign": "positive" if pnl > 0 else ("negative" if pnl < 0 else "flat"),
        "entries_per_year_approx": round(len(res.entries) / span_yrs, 1),
        "skip_reasons_top": dict(sorted(tally.items(), key=lambda kv: -kv[1])[:12]),
        "cash": args.cash,
    }
    (OUT / "_full_replay_summary.json").write_text(json.dumps(out, indent=2, default=str))
    print(json.dumps(out, indent=2, default=str))
    return 0


if __name__ == "__main__":
    sys.exit(main())
