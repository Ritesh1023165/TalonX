"""Deterministic generator for examples/data/sample_multi_trade_1m.csv.

TEST_FIXTURE_ONLY -- NOT ALPHA EVIDENCE.

Task 81-R2 §5. The previous fixture's TSTW/TSTL/TSTE "trades" were built
around the long/short bug (BEARISH-while-flat shorts) removed in Task
24/25A and produced ZERO trades under the corrected long-only strategy.

This regenerates the fixture WITHOUT touching the strategy: it reuses the
exact, known-good bar sequence of examples/data/sample_AAPL_trade_1m.csv
(a Task 73S fixture proven to produce one genuine long entry --
macd_bullish_cross, confluence_score 2, risk_reward_ratio ~3.5, entry
96.1226, stop 95.1352, target 99.5775) through its entry bar, then appends
a DIFFERENT post-entry price path per symbol so each of the three symbols
takes exactly one long trade with a distinct exit reason:

  TSTW -> TARGET          (keeps the AAPL recovery tail -> target hit)
  TSTL -> STOP            (declines through the stop -> clean -1R)
  TSTE -> END_OF_SESSION  (drifts up, holds between stop and target until
                           the 15:50 ET EOD flatten -> a small positive R)

Pre-entry bars are byte-identical across the three symbols (only the
`symbol` column changes), so the strategy computes an identical entry /
stop / target for each -- only the exit differs. Nothing is hand-edited in
any result ledger: this script writes only OHLCV input bars, and the
backtest engine derives every trade.

Usage:  python scripts/gen_sample_multi_trade_1m.py [--verify]
"""
from __future__ import annotations

import argparse
import csv
import subprocess
import sys
import tempfile
from datetime import datetime, timedelta
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
SRC = REPO / "examples" / "data" / "sample_AAPL_trade_1m.csv"
OUT = REPO / "examples" / "data" / "sample_multi_trade_1m.csv"

# From `python -m talonx_backtest --data sample_AAPL_trade_1m.csv --symbol AAPL`:
ENTRY_TS = "2026-01-06 10:48:00"     # entry bar (executes at its open)
ENTRY_PRICE = 96.1226
STOP_PRICE = 95.135234796188        # engine ATR_FALLBACK stop -> gross_R == -1 exactly at this level
TARGET_PRICE = 99.57749999999999
SESSION_END_TS = "2026-01-06 15:55:00"   # a few bars past the 15:50 ET EOD flatten


def _load_src() -> list[dict]:
    with SRC.open(newline="", encoding="utf-8") as fh:
        return [dict(r) for r in csv.DictReader(fh)]


def _bar(ts: str, o: float, h: float, l: float, c: float, v: float) -> dict:
    return {"timestamp": ts, "open": f"{o:.4f}", "high": f"{h:.4f}",
            "low": f"{l:.4f}", "close": f"{c:.4f}", "volume": f"{v:.1f}"}


def _minutes(start_ts: str, count: int, step: int = 1):
    t = datetime.strptime(start_ts, "%Y-%m-%d %H:%M:%S")
    for _ in range(count):
        yield t.strftime("%Y-%m-%d %H:%M:%S")
        t += timedelta(minutes=step)


def build() -> list[dict]:
    src = _load_src()
    entry_idx = next(i for i, r in enumerate(src) if r["timestamp"] == ENTRY_TS)
    pre = src[: entry_idx + 1]          # preroll + decline + recovery + entry bar (identical for all 3)

    rows: list[dict] = []

    # -- TSTW: keep the exact AAPL sequence -> TARGET --------------------
    for r in src:
        rows.append({"timestamp": r["timestamp"], "symbol": "TSTW", **{k: r[k] for k in ("open", "high", "low", "close", "volume")}})

    # -- TSTL: pre-entry identical, then decline through the stop -> STOP --
    for r in pre:
        rows.append({"timestamp": r["timestamp"], "symbol": "TSTL", **{k: r[k] for k in ("open", "high", "low", "close", "volume")}})
    tstl_tail = [
        # ts_offset from entry+1, close path stepping down; the 5th bar's LOW
        # pierces STOP_PRICE so the engine exits exactly at the stop (-1R).
        (96.1226, 95.90), (95.90, 95.62), (95.62, 95.36), (95.36, 95.18),
        (95.18, 95.05),   # low 94.95 <= STOP -> STOP exit at 95.1352
        (95.05, 95.02), (95.02, 95.00), (95.00, 95.00),
    ]
    for ts, (o, c) in zip(_minutes("2026-01-06 10:49:00", len(tstl_tail)), tstl_tail):
        lo = min(o, c) - 0.10
        hi = max(o, c) + 0.05
        rows.append({"timestamp": ts, "symbol": "TSTL", **_bar(ts, o, hi, lo, c, 1500.0)})

    # -- TSTE: pre-entry identical, drift up to ~98 and HOLD until the
    #    15:50 ET EOD flatten -> END_OF_SESSION at a small positive R -----
    for r in pre:
        rows.append({"timestamp": r["timestamp"], "symbol": "TSTE", **{k: r[k] for k in ("open", "high", "low", "close", "volume")}})
    drift = [96.55, 96.95, 97.30, 97.60, 97.85, 98.00]     # 10:49..10:54, up but < TARGET
    prev = 96.1226
    for ts, c in zip(_minutes("2026-01-06 10:49:00", len(drift)), drift):
        rows.append({"timestamp": ts, "symbol": "TSTE", **_bar(ts, prev, c + 0.10, prev - 0.05, c, 1500.0)})
        prev = c
    # hold flat at 98.00 (highs well below TARGET 99.5775, lows well above
    # STOP 95.1352) every minute through the EOD flatten and a little past.
    hold_start = "2026-01-06 10:55:00"
    n_hold = int((datetime.strptime(SESSION_END_TS, "%Y-%m-%d %H:%M:%S")
                  - datetime.strptime(hold_start, "%Y-%m-%d %H:%M:%S")).total_seconds() // 60) + 1
    for ts in _minutes(hold_start, n_hold):
        rows.append({"timestamp": ts, "symbol": "TSTE", **_bar(ts, 98.00, 98.05, 97.95, 98.00, 1000.0)})

    rows.sort(key=lambda r: (r["timestamp"], r["symbol"]))
    return rows


def write(rows: list[dict]) -> None:
    with OUT.open("w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=["timestamp", "symbol", "open", "high", "low", "close", "volume"])
        w.writeheader()
        w.writerows(rows)
    print(f"wrote {len(rows)} rows -> {OUT.relative_to(REPO)}")


def verify() -> int:
    out_dir = Path(tempfile.mkdtemp(prefix="gen_multi_verify_"))
    cmd = [sys.executable, "-m", "talonx_backtest", "--data", str(OUT),
           "--symbols", "TSTW,TSTL,TSTE", "--tz", "America/New_York", "--out", str(out_dir)]
    print("verify:", " ".join(cmd))
    r = subprocess.run(cmd, capture_output=True, text=True)
    print(r.stdout[-1500:])
    if r.returncode != 0:
        print(r.stderr, file=sys.stderr)
        return 1
    import json
    trades = json.loads((out_dir / "backtest_trades.json").read_text(encoding="utf-8"))
    by_sym = {t["symbol"]: t for t in trades}
    print(f"trades: {len(trades)}")
    for t in trades:
        print(f"  {t['symbol']:5s} entry={t['entry_price']:.4f} stop={t['stop_price']:.4f} "
              f"target={t['target_price']:.4f} exit={t['exit_price']:.4f} reason={t['exit_reason']} "
              f"gross_R={t['gross_R']:.4f} confluence={t['confluence_score']} rr={t['risk_reward_ratio']:.3f}")
    ok = (
        len(trades) == 3
        and by_sym.get("TSTW", {}).get("exit_reason") == "TARGET"
        and by_sym.get("TSTL", {}).get("exit_reason") == "STOP"
        and by_sym.get("TSTE", {}).get("exit_reason") == "END_OF_SESSION"
        and abs(by_sym["TSTL"]["gross_R"] - (-1.0)) < 1e-6
        and by_sym["TSTW"]["gross_R"] > 0
        and by_sym["TSTE"]["gross_R"] > 0
    )
    print("VERIFY:", "PASS" if ok else "FAIL")
    return 0 if ok else 1


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--verify", action="store_true")
    args = ap.parse_args()
    write(build())
    if args.verify:
        raise SystemExit(verify())
