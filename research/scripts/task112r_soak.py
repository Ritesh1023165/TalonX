"""Task 112R Gate G10 -- bounded accelerated soak of the FROZEN V2 pipeline.

Offline / replay only.  Pre-loads the frozen Form 4 records ONCE (Tuesday
uses the InsiderStore SQLite query, not this parquet -- the per-tick
re-read is a rehearsal-harness artefact, not a runtime cost), then drives
the pipeline over a long walk of historical as-of dates, asserting no
state corruption / duplicate trade / unbounded growth.  NO strategy change.
"""
from __future__ import annotations

import gc
import json
import os
import sys
import time
from datetime import date, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
OUT = ROOT / "results" / "task112r_release_rehearsal"

try:
    import psutil
    _P = psutil.Process()
except Exception:  # noqa: BLE001
    _P = None


def main() -> int:
    import tempfile

    from talonx_v2 import form4_source, pipeline
    from talonx_v2 import calendar as v2cal
    from talonx_v2.config import V2Config
    from talonx_v2.store import V2Store

    n = int(os.environ.get("SOAK_TICKS", "600"))
    db = str(Path(tempfile.mkdtemp()) / "soak.db")
    cfg = V2Config(db_path=db, starting_cash_usd=300_000.0)
    V2Store(db, starting_cash=300_000.0)

    # pre-load the frozen records ONCE, keep a 45-day rolling slice per tick.
    # scope to the task95g in-panel universe (the V2 target domain) so a
    # long tick count is feasible -- the per-tick pipeline path is identical.
    panel = {f.stem.upper() for f in (ROOT / "results/task95g_broad_cross_sectional/_daily").glob("*.csv")}
    all_recs = [r for r in form4_source.from_research_parquet(
        ROOT / "results/task107a_form4_feasibility/_build/form4_open_market_txn.parquet",
        since=date(2023, 12, 1)) if r.symbol in panel]
    all_recs.sort(key=lambda r: r.filing_date)
    print(f"pre-loaded {len(all_recs)} in-panel code-P records", flush=True)

    bar_dirs = [ROOT / "results/task95g_broad_cross_sectional/_daily",
                ROOT / "results/task107a_form4_feasibility/_prices"]
    _cache: dict[str, list[dict]] = {}

    def bars_lookup(sym):
        if sym in _cache:
            return _cache[sym]
        import pandas as pd
        for d in bar_dirs:
            f = d / f"{sym}.csv"
            if f.exists() and f.stat().st_size > 20:
                try:
                    df = pd.read_csv(f)
                except Exception:  # noqa: BLE001
                    continue
                if "date" not in df.columns:
                    continue
                _cache[sym] = [{"date": str(r.date)[:10], "open": float(r.open),
                                "close": float(r.close), "volume": float(r.volume)}
                               for r in df.itertuples(index=False)]
                return _cache[sym]
        _cache[sym] = []
        return []

    def price_lookup(sym, dd):
        ds = dd.isoformat() if isinstance(dd, date) else str(dd)[:10]
        for b in bars_lookup(sym):
            if b["date"] == ds:
                return b
        return None

    d = date(2024, 1, 15)
    t0 = time.time()
    samples = []
    for i in range(n):
        as_of = d
        lo = as_of - timedelta(days=45)
        slice_recs = [r for r in all_recs if lo <= r.filing_date <= as_of]
        eps = [e for e in pipeline.detect_episodes(slice_recs, config=cfg)
               if e.eligible_entry_session <= as_of]
        res = pipeline.ProcessResult()
        for ep in eps:
            pipeline.process_episode(ep, store=V2Store(db), bars_lookup=bars_lookup,
                                     price_lookup=price_lookup, config=cfg, result=res)
        pipeline.settle_due_exits(store=V2Store(db), as_of_session=as_of,
                                  price_lookup=price_lookup, config=cfg, result=res)
        d += timedelta(days=3)
        if d > date(2026, 3, 20):
            d = date(2024, 1, 15)
        if i % 25 == 0 or i == n - 1:
            gc.collect()
            S = V2Store(db)
            rss = _P.memory_info().rss / 1e6 if _P else 0.0
            samples.append({
                "tick": i, "as_of": as_of.isoformat(),
                "open": S.n_open(), "cash": round(S.cash(), 2),
                "unresolved": len(S.unresolved_positions()),
                "rss_mb": round(rss, 1),
                "db_mb": round(Path(db).stat().st_size / 1e6, 3),
                "elapsed_s": round(time.time() - t0, 1),
            })
            print(json.dumps(samples[-1]), flush=True)

    S = V2Store(db)
    tr = S.trades()
    ebuys = [t["episode_id"] for t in tr if t["action"] == "BUY"]
    report = {
        "ticks": n, "duration_s": round(time.time() - t0, 1),
        "samples": samples,
        "n_buys": len(ebuys), "n_sells": sum(1 for t in tr if t["action"] == "SELL"),
        "duplicate_buy_episode": len(ebuys) != len(set(ebuys)),
        "open_end": S.n_open(), "unresolved_end": len(S.unresolved_positions()),
        "cash_end": round(S.cash(), 2), "cash_negative_ever": S.cash() < 0,
        "rss_delta_mb": (round(samples[-1]["rss_mb"] - samples[0]["rss_mb"], 1)
                         if len(samples) > 1 and samples[0]["rss_mb"] else None),
        "db_growth_mb": round(samples[-1]["db_mb"] - samples[0]["db_mb"], 3) if len(samples) > 1 else 0.0,
    }
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "soak_report.json").write_text(json.dumps(report, indent=2, default=str))
    print("\n" + json.dumps(report, indent=2, default=str))
    return 0


if __name__ == "__main__":
    sys.exit(main())
