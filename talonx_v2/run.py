"""
talonx_v2.run -- V2 lane entry point (opt-in, additive)
=====================================================
Modes
-----
  --mode replay   deterministic offline replay from the Task 107A research
                  parquet + a local daily-bar directory (Alpaca SIP CSVs).
                  Produces v2_lane.db + a JSON summary.  No network beyond
                  the bar files already on disk.  DEFAULT.
  --mode recover  print restart-recovery summary for an existing v2_lane.db
                  (open positions, overdue exits) and exit.
  --mode live     the Tuesday companion loop -- detect causally-ripe
                  episodes, open/hold/close the frozen 10-td paper
                  positions, write a heartbeat + status file.  --once
                  runs a single tick (dry-run / supervisor readiness).
  --mode status   print the current v2_service_status.json and exit.

This is NOT started by the Original supervisor automatically.  It is the
V2 lane, run explicitly:  ``python -m talonx_v2.run --mode replay ...``.

Never sends Telegram, never touches a broker, never uses real capital.
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import date
from pathlib import Path

from talonx_v2 import form4_source, pipeline
from talonx_v2.config import V2Config
from talonx_v2.store import V2Store


def _bar_dir_lookup(bar_dirs: list[Path]):
    import pandas as pd

    cache: dict[str, list[dict]] = {}

    def _load(sym: str) -> list[dict]:
        if sym in cache:
            return cache[sym]
        for d in bar_dirs:
            f = d / f"{sym}.csv"
            if f.exists() and f.stat().st_size > 20:
                try:
                    df = pd.read_csv(f)
                except Exception:  # noqa: BLE001
                    continue
                if "date" not in df.columns:
                    continue
                rows = [{"date": str(r.date)[:10], "open": float(getattr(r, "open", "nan")),
                         "close": float(r.close), "volume": float(getattr(r, "volume", 0) or 0)}
                        for r in df.itertuples(index=False)]
                cache[sym] = rows
                return rows
        cache[sym] = []
        return []

    def bars_lookup(sym: str) -> list[dict]:
        return _load(sym)

    def price_lookup(sym: str, session: date) -> dict | None:
        s = session.isoformat() if isinstance(session, date) else str(session)[:10]
        for row in _load(sym):
            if row["date"] == s:
                return row
        return None

    return bars_lookup, price_lookup


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser("talonx_v2.run")
    ap.add_argument("--mode", choices=["replay", "recover", "live", "status"], default="replay")
    ap.add_argument("--once", action="store_true", help="live mode: run one tick and exit")
    ap.add_argument("--tick-seconds", type=int, default=300,
                    help="strategy evaluation cadence (seconds)")
    ap.add_argument("--heartbeat-seconds", type=int, default=30,
                    help="lightweight health-heartbeat cadence, decoupled from --tick-seconds")
    ap.add_argument("--form4-source", choices=["parquet", "insider"], default="parquet")
    ap.add_argument("--status-path", default="")
    ap.add_argument("--as-of", default="", help="live --once: pin the tick date (dry-run only)")
    ap.add_argument("--live-lookback-days", type=int, default=45)
    ap.add_argument("--form4-parquet",
                    default="results/task107a_form4_feasibility/_build/form4_open_market_txn.parquet")
    ap.add_argument("--bar-dir", action="append", default=[
        "results/task95g_broad_cross_sectional/_daily",
        "results/task107a_form4_feasibility/_prices",
    ])
    ap.add_argument("--symbols", default="", help="comma-separated filter (default: all)")
    ap.add_argument("--since", default="2019-06-03")
    ap.add_argument("--db", default="v2_lane.db")
    ap.add_argument("--out", default="results/task110_v2_integration/_replay_summary.json")
    args = ap.parse_args(argv)

    cfg = V2Config(db_path=args.db)
    cfg.validate_frozen()
    store = V2Store(args.db, starting_cash=cfg.starting_cash_usd)

    if args.mode == "recover":
        summary = pipeline.paper.recover(store, as_of_session=date.today())
        print(json.dumps(summary, indent=2))
        return 0

    if args.mode == "status":
        from talonx_v2.service import V2Service
        svc = V2Service(config=cfg, bar_dirs=[Path(p) for p in args.bar_dir],
                        status_path=args.status_path or None)
        try:
            print(Path(svc.status_path).read_text())
        except OSError:
            print(json.dumps({"error": "no status file yet", "path": str(svc.status_path)}))
        return 0

    if args.mode == "live":
        import logging
        logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
        from talonx_v2.service import V2Service
        svc = V2Service(
            config=cfg, bar_dirs=[Path(p) for p in args.bar_dir],
            form4_kind=args.form4_source, form4_parquet=args.form4_parquet,
            status_path=args.status_path or None,
            since=None, live_lookback_days=args.live_lookback_days,
        )
        if args.once and args.as_of:
            st = svc.tick(as_of=date.fromisoformat(args.as_of))
            print(json.dumps(st, indent=2, default=str))
            return 0
        return svc.run(once=args.once, tick_seconds=args.tick_seconds,
                       heartbeat_seconds=args.heartbeat_seconds)

    syms = {s.strip().upper() for s in args.symbols.split(",") if s.strip()} or None
    records = form4_source.from_research_parquet(
        args.form4_parquet, symbols=syms,
        since=date.fromisoformat(args.since) if args.since else None,
    )
    bars_lookup, price_lookup = _bar_dir_lookup([Path(p) for p in args.bar_dir])
    res = pipeline.run_replay(records, store=store, bars_lookup=bars_lookup,
                              price_lookup=price_lookup, config=cfg)

    out = {
        "mode": "replay", "records": len(records),
        "episodes_detected": res.episodes_detected,
        "signals_built": res.signals_built,
        "entries": len(res.entries), "exits": len(res.exits),
        "skipped": len(res.skipped),
        "realized_pnl_usd": round(sum(e["realized_pnl_usd"] for e in res.exits), 2),
        "sample_entries": res.entries[:5],
        "sample_exits": res.exits[:5],
        "skip_reasons": _tally(res.skipped),
    }
    Path(args.out).parent.mkdir(parents=True, exist_ok=True)
    Path(args.out).write_text(json.dumps(out, indent=2, default=str))
    print(json.dumps(out, indent=2, default=str)[:3000])
    return 0


def _tally(skips: list[dict]) -> dict:
    t: dict[str, int] = {}
    for s in skips:
        t[s["reason"]] = t.get(s["reason"], 0) + 1
    return dict(sorted(t.items(), key=lambda kv: -kv[1]))


if __name__ == "__main__":
    sys.exit(main())
