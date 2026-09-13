"""
TASK 125 Part 3 -- resumable, durable acquisition of 1-min SIP bars for
the 15 symbols frozen in docs/research/TASK125_FROZEN_EXTENSION_PROTOCOL.md
(12 original Track-B symbols + BABA/SHOP/SPCX), 2022-12-01 -> 2025-08-14.

Reuses the exact request pattern already established by
research/scripts/task63r_probe_alpaca_feeds.py and
research/scripts/task124_alpaca_feed_probe.py (release worktree) --
no new provider integration.

Durable progress: one partition = (symbol, calendar-year-chunk). Each
partition is fetched once, written to its own raw CSV under
results/task125_intraday_extension/_raw/<symbol>/<start>_<end>.csv,
and recorded (done) in a progress.json manifest keyed by partition id
-- a re-run skips any partition already marked done and only fetches
what remains, rather than restarting the whole acquisition. Bounded
concurrency: strictly sequential (matches every prior provider-facing
script in this program), rate-limited backoff on 429/5xx (same
1.5+attempt / 3+3*attempt convention as task107a_prices.py).

Usage:
    python research/scripts/task125_acquire_intraday.py --pilot
        # fetches ONLY the first partition, to measure throughput
    python research/scripts/task125_acquire_intraday.py
        # fetches all remaining partitions (resumable)
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
import time
from pathlib import Path

import pandas as pd
import requests
from dotenv import load_dotenv

RELEASE_ROOT = Path("C:/workspace/TalonX")
RESEARCH_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(RELEASE_ROOT))

OUT = RESEARCH_ROOT / "results" / "task125_intraday_extension"
RAW = OUT / "_raw"
RAW.mkdir(parents=True, exist_ok=True)
PROGRESS_PATH = OUT / "acquisition_progress.json"

SYMBOLS_ORIGINAL_12 = ["AAPL", "AMAT", "AMD", "AVGO", "CSCO", "GOOGL", "INTC", "MSFT", "NVDA", "PYPL", "STX", "TSLA"]
SYMBOLS_ADDED = ["BABA", "SHOP", "SPCX"]
ALL_SYMBOLS = SYMBOLS_ORIGINAL_12 + SYMBOLS_ADDED

ACQUISITION_START = "2022-12-01"
ACQUISITION_END = "2025-08-14"

# Date partitions (calendar-year chunks, clipped to the acquisition
# range) -- each is independently resumable.
_YEAR_CHUNKS = [
    ("2022-12-01", "2022-12-31"),
    ("2023-01-01", "2023-12-31"),
    ("2024-01-01", "2024-12-31"),
    ("2025-01-01", "2025-08-14"),
]


def _partitions() -> list[tuple[str, str, str]]:
    return [(sym, lo, hi) for sym in ALL_SYMBOLS for lo, hi in _YEAR_CHUNKS]


def _partition_id(sym: str, lo: str, hi: str) -> str:
    return f"{sym}__{lo}_{hi}"


def _load_progress() -> dict:
    if PROGRESS_PATH.exists():
        return json.loads(PROGRESS_PATH.read_text())
    return {"partitions": {}}


def _save_progress(progress: dict) -> None:
    PROGRESS_PATH.write_text(json.dumps(progress, indent=2, default=str))


def _fetch_symbol_range(sym: str, start: str, end: str, *, session: requests.Session) -> list[dict]:
    """Paginated fetch of ALL 1-min SIP bars for [start, end] inclusive.
    Retries with jittered backoff on 429/transient errors -- the same
    convention as research/scripts/task107a_prices.py."""
    headers = {
        "APCA-API-KEY-ID": os.environ["APCA_API_KEY_ID"],
        "APCA-API-SECRET-KEY": os.environ["APCA_API_SECRET_KEY"],
    }
    bars: list[dict] = []
    token = None
    for _ in range(200):  # hard page cap -- a partition is at most 1 year, never needs this many
        params = {
            "timeframe": "1Min", "start": f"{start}T00:00:00Z", "end": f"{end}T23:59:59Z",
            "limit": 10000, "adjustment": "raw", "feed": "sip",
        }
        if token:
            params["page_token"] = token
        for attempt in range(6):
            try:
                resp = session.get(f"https://data.alpaca.markets/v2/stocks/{sym}/bars",
                                  headers=headers, params=params, timeout=60)
            except requests.RequestException:
                time.sleep(1.5 + attempt)
                continue
            if resp.status_code == 429:
                time.sleep(3 + 3 * attempt)
                continue
            if resp.status_code >= 500:
                time.sleep(1.5 + attempt)
                continue
            break
        else:
            raise RuntimeError(f"{sym} {start}->{end}: exhausted retries")
        resp.raise_for_status()
        body = resp.json()
        bars.extend(body.get("bars") or [])
        token = body.get("next_page_token")
        if not token:
            break
    return bars


def _process_partition(sym: str, lo: str, hi: str, *, session: requests.Session) -> dict:
    pid = _partition_id(sym, lo, hi)
    t0 = time.time()
    bars = _fetch_symbol_range(sym, lo, hi, session=session)
    elapsed = time.time() - t0

    sym_dir = RAW / sym
    sym_dir.mkdir(parents=True, exist_ok=True)
    out_path = sym_dir / f"{lo}_{hi}.csv"

    if not bars:
        out_path.write_text("timestamp,open,high,low,close,volume\n")  # EMPTY, distinct from a failure
        record = {"partition_id": pid, "symbol": sym, "start": lo, "end": hi,
                  "status": "EMPTY_RESPONSE", "n_rows": 0, "file": str(out_path),
                  "file_sha256": None, "feed": "sip", "adjustment": "raw",
                  "retrieved_at_utc": pd.Timestamp.now(tz="UTC").isoformat(),
                  "elapsed_seconds": round(elapsed, 2)}
        return record

    df = pd.DataFrame(bars)
    df["timestamp"] = pd.to_datetime(df["t"], utc=True)
    df = df.rename(columns={"o": "open", "h": "high", "l": "low", "c": "close", "v": "volume"})
    df = df[["timestamp", "open", "high", "low", "close", "volume"]]
    # deterministic dedup + sort -- Alpaca pagination boundaries can
    # occasionally repeat the boundary bar across pages
    df = df.drop_duplicates(subset="timestamp").sort_values("timestamp").reset_index(drop=True)
    df.to_csv(out_path, index=False)

    file_hash = hashlib.sha256(out_path.read_bytes()).hexdigest()
    record = {"partition_id": pid, "symbol": sym, "start": lo, "end": hi,
              "status": "DATA_PRESENT", "n_rows": len(df), "file": str(out_path),
              "file_sha256": file_hash, "feed": "sip", "adjustment": "raw",
              "first_ts": str(df["timestamp"].iloc[0]), "last_ts": str(df["timestamp"].iloc[-1]),
              "retrieved_at_utc": pd.Timestamp.now(tz="UTC").isoformat(),
              "elapsed_seconds": round(elapsed, 2)}
    return record


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--pilot", action="store_true", help="Fetch only the first not-yet-done partition, then stop (throughput measurement).")
    parser.add_argument("--limit", type=int, default=None, help="Stop after fetching this many NEW partitions this run (still resumable).")
    args = parser.parse_args()

    load_dotenv(RELEASE_ROOT / ".env", override=False)
    if "APCA_API_KEY_ID" not in os.environ or "APCA_API_SECRET_KEY" not in os.environ:
        print(json.dumps({"error": "APCA credentials not present in environment -- aborting, no acquisition run"}))
        return 1

    progress = _load_progress()
    all_partitions = _partitions()
    todo = [(s, lo, hi) for (s, lo, hi) in all_partitions
           if progress["partitions"].get(_partition_id(s, lo, hi), {}).get("status") not in
           ("DATA_PRESENT", "EMPTY_RESPONSE")]

    print(f"total partitions: {len(all_partitions)}  already done: "
         f"{len(all_partitions) - len(todo)}  remaining: {len(todo)}")

    if args.pilot:
        todo = todo[:1]
    elif args.limit:
        todo = todo[:args.limit]

    session = requests.Session()
    n_done_this_run = 0
    t_run0 = time.time()
    for sym, lo, hi in todo:
        pid = _partition_id(sym, lo, hi)
        try:
            record = _process_partition(sym, lo, hi, session=session)
        except Exception as exc:  # noqa: BLE001 -- preserve failure, checkpoint, move on
            record = {"partition_id": pid, "symbol": sym, "start": lo, "end": hi,
                      "status": "PROVIDER_FAILURE", "error": str(exc),
                      "retrieved_at_utc": pd.Timestamp.now(tz="UTC").isoformat()}
            print(f"  FAILED {pid}: {exc}")
            progress["partitions"][pid] = record
            _save_progress(progress)  # checkpoint even on failure
            continue
        progress["partitions"][pid] = record
        _save_progress(progress)  # durable checkpoint after EVERY partition
        n_done_this_run += 1
        print(f"  [{n_done_this_run}/{len(todo)}] {pid}: {record['status']} "
             f"n_rows={record.get('n_rows', 0)} ({record.get('elapsed_seconds', 0):.2f}s)")

    total_elapsed = time.time() - t_run0
    done_now = sum(1 for r in progress["partitions"].values() if r.get("status") in ("DATA_PRESENT", "EMPTY_RESPONSE"))
    failed_now = sum(1 for r in progress["partitions"].values() if r.get("status") == "PROVIDER_FAILURE")
    print(f"\nthis run: {n_done_this_run} partitions in {total_elapsed:.1f}s "
         f"({total_elapsed / max(1, n_done_this_run):.2f}s/partition avg)")
    print(f"overall: {done_now}/{len(all_partitions)} done, {failed_now} failed")
    if n_done_this_run:
        remaining = len(all_partitions) - done_now
        est_seconds = remaining * (total_elapsed / n_done_this_run)
        print(f"remaining {remaining} partitions -> estimated {est_seconds:.0f}s "
             f"({est_seconds/60:.1f} min) at this measured rate")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
