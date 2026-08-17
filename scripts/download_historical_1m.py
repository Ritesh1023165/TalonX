"""
scripts/download_historical_1m.py
--------------------------------------
Downloads historical 1-minute OHLCV bars for one or more symbols into
the CSV layout `talonx_backtest.data.load_ohlcv_directory` expects
(`<output-dir>/<SYMBOL>.csv`, columns timestamp,symbol,open,high,low,
close,volume) -- so its output can be fed straight into
`python -m talonx_backtest --data <output-dir> --symbols ...`.

Not part of any live TalonX process (ingest/quant/dispatch/paper) --
this is an offline, one-shot utility for sourcing REAL historical data
to backtest against, matching docs/backtesting.md's "Where to get
historical 1-minute OHLCV data" section.

Providers (first available is used, in this order, unless --provider
forces one):
  1. Polygon.io REST  (POLYGON_API_KEY)      -- via polygon-api-client,
     lazily imported; needs `pip install -r scripts/requirements.txt`.
  2. Alpaca Markets   (APCA_API_KEY_ID + APCA_API_SECRET_KEY) -- plain
     REST via `requests`, lazily imported.
  3. yfinance fallback (no key needed) -- `yf.download(...)`, chunked
     into 7-day sliding windows (see _chunk_date_range) since Yahoo caps
     1-minute-granularity requests at ~8 days per call; chunks are
     stitched back together (dedup + re-sort) into one continuous
     series. Yahoo also only serves roughly the trailing 30 days of
     1-minute history overall; a wider --start-date/--end-date range
     will simply come back short, logged loudly, not silently.

Rate limits: every provider call is retried with the SAME jittered
exponential backoff talonx_ingest.common.backoff already provides
(reused, not reimplemented) -- a persistent failure after
--max-retries logs a warning and moves on to the next symbol rather
than aborting the whole batch (per-symbol failure isolation, matching
talonx_quant/preseed.py's "fails soft" convention).

After writing each symbol's CSV, runs it through
talonx_backtest.data.check_data_quality and prints the report -- so a
"did this download actually produce something talonx_backtest can use"
answer is part of running this script, not a separate manual step.

Usage:
    python scripts/download_historical_1m.py --symbols AAPL,MSFT,NVDA --start-date 2024-01-01 --end-date 2024-06-30
    python scripts/download_historical_1m.py --symbols tickers.txt --start-date 2025-01-01 --end-date 2025-12-31 --output-dir data/historical_1m
    python scripts/download_historical_1m.py --symbols AAPL --provider yfinance --start-date 2026-08-01 --end-date 2026-08-10
"""
from __future__ import annotations

import argparse
import json
import logging
import os
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pandas as pd  # noqa: E402

from talonx_ingest.common.backoff import jittered_backoff_seconds  # noqa: E402
from talonx_backtest.data import check_data_quality, from_dataframe  # noqa: E402

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")
logger = logging.getLogger("scripts.download_historical_1m")

_BAR_COLUMNS = ("timestamp", "open", "high", "low", "close", "volume")


class DownloadError(Exception):
    """Raised when a provider call fails after exhausting all retries
    for one symbol -- caught by the per-symbol loop in main(), never
    lets one bad ticker abort the whole batch."""


# 2026-08-17 real-data smoke test follow-up: the downloader used to
# collapse "provider call failed" and "provider returned zero bars" into
# the same None/"failed" bucket, and never compared what was ACTUALLY
# returned against what was REQUESTED -- see download_symbol/main below.
# FULL/PARTIAL/EMPTY/FAILED makes those four outcomes explicit and
# distinct everywhere a caller might look (console output, exit code,
# download_summary.json).
_STATUSES = ("FULL", "PARTIAL", "EMPTY", "FAILED")


@dataclass
class DownloadResult:
    """One symbol's outcome. `df` is the raw fetched bars (None unless
    status is FULL or PARTIAL) -- excluded from repr/eq since comparing
    DataFrames via `==` is ambiguous and no caller needs to compare two
    DownloadResults for equality."""

    symbol: str
    status: str  # one of _STATUSES
    requested_start: str
    requested_end: str
    actual_start: str | None
    actual_end: str | None
    bars: int
    error: str | None = None
    df: pd.DataFrame | None = field(default=None, repr=False, compare=False)


def _classify_status(df: pd.DataFrame, requested_start: str, requested_end: str) -> str:
    """FULL vs PARTIAL, purely by comparing the ACTUAL returned calendar-
    date range against the REQUESTED one -- deliberately no weekend/
    holiday interpretation (this repo has no trading-calendar source of
    truth to consult -- see talonx_backtest/data.py's `_is_weekend`
    docstring for why one wasn't invented there either, and the same
    reasoning applies here). PARTIAL is a neutral description of
    "returned less date-range than requested," not an accusation that
    the shortfall represents missing market data -- a request whose end
    date hasn't traded yet, or that happens to span a weekend, can
    legitimately come back PARTIAL under this definition. The caller is
    expected to read requested/actual side by side, not treat PARTIAL
    alone as an error (see main()'s exit-code handling, which does NOT
    fail the run on PARTIAL by itself).

    2026-08-17 timezone/date-boundary audit fix: the actual/requested
    comparison is done on America/New_York calendar dates, not raw UTC
    ones -- `requested_start`/`requested_end` are bare "YYYY-MM-DD"
    strings with no time-of-day component at all, so they already mean
    "this ET trading day" by construction (the whole point of this
    downloader's date args); comparing them against a UTC .date() of the
    ACTUAL bars was the bug. Confirmed reproducible: extended-hours
    (prepost=True) 1-minute data genuinely trades as late as ~19:59 ET,
    which during EST (UTC-5, roughly Nov-Mar) is 00:59 UTC the NEXT
    calendar day -- comparing that against a UTC `requested_end_date`
    made a request for [D, D+1] where D+1 is ENTIRELY missing read as
    FULL (D's own last after-hours bar's UTC date coincidentally matched
    D+1). Converting both bar timestamps to America/New_York before
    taking .date() removes that spillover -- the requested date strings
    need no conversion, since they never carried a UTC assumption to
    begin with. This does NOT touch `df` itself, its stored timestamps,
    or DownloadResult.actual_start/actual_end (both still raw UTC
    strings, set independently in download_symbol) -- only the internal
    date basis this one classification decision uses."""
    actual_start_date = df["timestamp"].iloc[0].tz_convert("America/New_York").date()
    actual_end_date = df["timestamp"].iloc[-1].tz_convert("America/New_York").date()
    requested_start_date = pd.Timestamp(requested_start).date()
    requested_end_date = pd.Timestamp(requested_end).date()
    if actual_start_date <= requested_start_date and actual_end_date >= requested_end_date:
        return "FULL"
    return "PARTIAL"


def _retry(fn, *, max_retries: int, base_seconds: float, max_seconds: float, description: str):
    """Calls `fn()` (a zero-arg callable), retrying with jittered
    exponential backoff (talonx_ingest.common.backoff, the SAME helper
    polygon_ws.py/yfinance_poll.py already use) on any exception. Raises
    DownloadError if every attempt fails."""
    last_exc: Exception | None = None
    for attempt in range(1, max_retries + 1):
        try:
            return fn()
        except Exception as exc:  # noqa: BLE001 -- any provider/network failure is retried uniformly
            last_exc = exc
            if attempt == max_retries:
                break
            wait = jittered_backoff_seconds(attempt, base_seconds, max_seconds)
            logger.warning("%s failed (attempt %d/%d): %s -- retrying in %.1fs", description, attempt, max_retries, exc, wait)
            time.sleep(wait)
    raise DownloadError(f"{description} failed after {max_retries} attempts: {last_exc}") from last_exc


# ------------------------------------------------------------------
# Providers -- each returns a list of bar dicts (timestamp/open/high/
# low/close/volume), timestamp tz-aware UTC, oldest first. Empty list
# (not an exception) means "no data for this range", a legitimate
# outcome (e.g. a symbol with no trading that day); a genuine failure
# raises and is handled by _retry/the per-symbol loop.
# ------------------------------------------------------------------

def fetch_polygon(symbol: str, start_date: str, end_date: str, *, max_retries: int) -> list[dict]:
    from polygon import RESTClient  # lazy import -- optional dependency, see scripts/requirements.txt

    api_key = os.environ["POLYGON_API_KEY"]

    def _call():
        client = RESTClient(api_key)
        bars = []
        # list_aggs is a generator that auto-paginates via Polygon's own
        # next_url cursor internally -- no manual pagination needed.
        for agg in client.list_aggs(symbol, 1, "minute", start_date, end_date, limit=50000, adjusted=True):
            ts = pd.Timestamp(agg.timestamp, unit="ms", tz="UTC")
            bars.append({
                "timestamp": ts, "open": agg.open, "high": agg.high,
                "low": agg.low, "close": agg.close, "volume": agg.volume,
            })
        return bars

    return _retry(_call, max_retries=max_retries, base_seconds=2.0, max_seconds=60.0, description=f"Polygon fetch for {symbol}")


def fetch_alpaca(symbol: str, start_date: str, end_date: str, *, max_retries: int) -> list[dict]:
    import requests  # lazy import -- optional dependency, see scripts/requirements.txt

    key_id = os.environ["APCA_API_KEY_ID"]
    secret_key = os.environ["APCA_API_SECRET_KEY"]
    headers = {"APCA-API-KEY-ID": key_id, "APCA-API-SECRET-KEY": secret_key}
    base_url = "https://data.alpaca.markets/v2/stocks/{symbol}/bars".format(symbol=symbol)

    bars: list[dict] = []
    page_token: str | None = None
    while True:
        params = {
            "timeframe": "1Min", "start": f"{start_date}T00:00:00Z", "end": f"{end_date}T23:59:59Z",
            "limit": 10000, "adjustment": "raw",
        }
        if page_token:
            params["page_token"] = page_token

        def _call(params=params):
            resp = requests.get(base_url, headers=headers, params=params, timeout=30)
            if resp.status_code == 429:
                raise DownloadError(f"Alpaca rate-limited (HTTP 429) for {symbol}")
            resp.raise_for_status()
            return resp.json()

        payload = _retry(_call, max_retries=max_retries, base_seconds=2.0, max_seconds=60.0, description=f"Alpaca fetch for {symbol}")

        for bar in payload.get("bars") or []:
            bars.append({
                "timestamp": pd.Timestamp(bar["t"], tz="UTC"), "open": bar["o"], "high": bar["h"],
                "low": bar["l"], "close": bar["c"], "volume": bar["v"],
            })

        page_token = payload.get("next_page_token")
        if not page_token:
            break
    return bars


_YFINANCE_CHUNK_DAYS = 7
_YFINANCE_CHUNK_SLEEP_SECONDS = 0.5


def _chunk_date_range(start_date: str, end_date: str, chunk_days: int = _YFINANCE_CHUNK_DAYS) -> list[tuple[str, str]]:
    """Splits [start_date, end_date] into consecutive `chunk_days`-day
    sliding windows, e.g. 2026-07-20 -> 2026-07-27 -> 2026-08-03 ->
    2026-08-10 -> 2026-08-16 (the last chunk is whatever is left, not
    padded out to a full window). Yahoo caps 1-minute-granularity
    requests at ~8 days ("Only 8 days worth of 1m granularity data are
    allowed to be fetched per request") -- a single request for
    anything wider fails outright, so a multi-day/week/month range has
    to be downloaded in slices and stitched back together."""
    start = pd.Timestamp(start_date)
    end = pd.Timestamp(end_date)
    if end <= start:
        return [(start.strftime("%Y-%m-%d"), end.strftime("%Y-%m-%d"))]

    chunks: list[tuple[str, str]] = []
    cursor = start
    step = pd.Timedelta(days=chunk_days)
    while cursor < end:
        chunk_end = min(cursor + step, end)
        chunks.append((cursor.strftime("%Y-%m-%d"), chunk_end.strftime("%Y-%m-%d")))
        cursor = chunk_end
    return chunks


def fetch_yfinance(symbol: str, start_date: str, end_date: str, *, max_retries: int) -> list[dict]:
    import yfinance as yf  # lazy import, same as talonx_quant/preseed.py

    span_days = (pd.Timestamp(end_date) - pd.Timestamp(start_date)).days
    if span_days > 30:
        logger.warning(
            "yfinance only serves ~30 trailing days of 1-minute history -- the requested "
            "%d-day range for %s will very likely come back short. Use --provider polygon "
            "or --provider alpaca (with an API key) for a wider historical range.",
            span_days, symbol,
        )

    chunks = _chunk_date_range(start_date, end_date)
    frames: list[pd.DataFrame] = []
    for i, (chunk_start, chunk_end) in enumerate(chunks):
        def _call(chunk_start=chunk_start, chunk_end=chunk_end):
            return yf.download(
                symbol.upper(), start=chunk_start, end=chunk_end,
                interval="1m", prepost=True, progress=False,
            )

        chunk_df = _retry(
            _call, max_retries=max_retries, base_seconds=2.0, max_seconds=30.0,
            description=f"yfinance fetch for {symbol} ({chunk_start} -> {chunk_end})",
        )
        if chunk_df is not None and not chunk_df.empty:
            frames.append(chunk_df)

        if i < len(chunks) - 1:
            time.sleep(_YFINANCE_CHUNK_SLEEP_SECONDS)  # avoid rate limits between chunk requests

    if not frames:
        return []

    combined = pd.concat(frames)
    # yf.download can return MultiIndex columns (e.g. ('Open', 'AAPL'))
    # even for a single ticker in some yfinance versions -- flatten
    # defensively rather than assuming a plain single-level frame.
    if isinstance(combined.columns, pd.MultiIndex):
        combined.columns = combined.columns.get_level_values(0)

    combined = combined.reset_index()
    timestamp_col = "Datetime" if "Datetime" in combined.columns else combined.columns[0]
    combined = combined.rename(columns={timestamp_col: "timestamp"})
    combined["timestamp"] = pd.to_datetime(combined["timestamp"], utc=True)

    # Consecutive chunks share their boundary date, so the SAME bar can
    # come back in both the outgoing and incoming chunk -- drop exact
    # duplicate timestamps and restore strict chronological order
    # before this is treated as one continuous series.
    combined.drop_duplicates(subset=["timestamp"], inplace=True)
    combined.sort_values("timestamp", inplace=True)

    bars = []
    for _, row in combined.iterrows():
        bars.append({
            "timestamp": row["timestamp"], "open": float(row["Open"]), "high": float(row["High"]),
            "low": float(row["Low"]), "close": float(row["Close"]), "volume": float(row["Volume"]),
        })
    return bars


_PROVIDERS = {"polygon": fetch_polygon, "alpaca": fetch_alpaca, "yfinance": fetch_yfinance}


def select_provider(requested: str | None) -> str:
    """Explicit --provider wins outright. Otherwise: Polygon if
    POLYGON_API_KEY is set, else Alpaca if both APCA_* vars are set,
    else yfinance -- never silently picks a provider whose required
    credential isn't actually present."""
    if requested:
        return requested
    if os.environ.get("POLYGON_API_KEY"):
        return "polygon"
    if os.environ.get("APCA_API_KEY_ID") and os.environ.get("APCA_API_SECRET_KEY"):
        return "alpaca"
    logger.info("No POLYGON_API_KEY or APCA_API_KEY_ID/APCA_API_SECRET_KEY set -- falling back to yfinance.")
    return "yfinance"


# ------------------------------------------------------------------
# CLI
# ------------------------------------------------------------------

def _parse_symbols(value: str) -> list[str]:
    path = Path(value)
    if path.is_file():
        text = path.read_text(encoding="utf-8")
        return [line.strip().upper() for line in text.splitlines() if line.strip() and not line.strip().startswith("#")]
    return [s.strip().upper() for s in value.split(",") if s.strip()]


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="download_historical_1m",
        description="Download historical 1-minute OHLCV bars into talonx_backtest's expected CSV layout.",
    )
    parser.add_argument("--symbols", required=True, help="Comma-separated tickers, or a path to a text file (one ticker per line).")
    parser.add_argument("--start-date", required=True, help="YYYY-MM-DD (inclusive).")
    parser.add_argument("--end-date", required=True, help="YYYY-MM-DD (inclusive).")
    parser.add_argument("--output-dir", default="data/historical_1m", help="Target directory (default: data/historical_1m/).")
    parser.add_argument("--provider", choices=list(_PROVIDERS), default=None, help="Force a specific provider (default: auto-select by available API key).")
    parser.add_argument("--max-retries", type=int, default=5, help="Retry attempts per provider call before giving up on a symbol (default: 5).")
    return parser


def download_symbol(symbol: str, start_date: str, end_date: str, provider: str, max_retries: int) -> DownloadResult:
    fetch = _PROVIDERS[provider]
    try:
        bars = fetch(symbol, start_date, end_date, max_retries=max_retries)
    except DownloadError as exc:
        logger.warning("Giving up on %s via %s: %s", symbol, provider, exc)
        return DownloadResult(
            symbol=symbol, status="FAILED", requested_start=start_date, requested_end=end_date,
            actual_start=None, actual_end=None, bars=0, error=str(exc),
        )

    if not bars:
        reason = f"0 bars returned by {provider} for {start_date} -> {end_date}"
        logger.warning("%s: %s", symbol, reason)
        return DownloadResult(
            symbol=symbol, status="EMPTY", requested_start=start_date, requested_end=end_date,
            actual_start=None, actual_end=None, bars=0, error=reason,
        )

    df = pd.DataFrame(bars)[list(_BAR_COLUMNS)].sort_values("timestamp").reset_index(drop=True)
    status = _classify_status(df, start_date, end_date)
    actual_start, actual_end = df["timestamp"].iloc[0], df["timestamp"].iloc[-1]
    logger.info(
        "%s: downloaded %d bar(s) via %s (%s -> %s) -- %s",
        symbol, len(df), provider, actual_start, actual_end, status,
    )
    return DownloadResult(
        symbol=symbol, status=status, requested_start=start_date, requested_end=end_date,
        actual_start=str(actual_start), actual_end=str(actual_end), bars=len(df), df=df,
    )


def main(argv: list[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)
    symbols = _parse_symbols(args.symbols)
    if not symbols:
        logger.error("No symbols to download (empty --symbols).")
        return 1

    provider = select_provider(args.provider)
    logger.info("Provider: %s | Symbols: %s | Range: %s -> %s", provider, ", ".join(symbols), args.start_date, args.end_date)

    out_dir = Path(args.output_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    total_bars = 0
    results: list[DownloadResult] = []
    for symbol in symbols:
        result = download_symbol(symbol, args.start_date, args.end_date, provider, args.max_retries)
        results.append(result)
        if result.df is None:
            continue

        normalized = from_dataframe(result.df, symbol=symbol)
        out_path = out_dir / f"{symbol}.csv"
        normalized.to_csv(out_path, index=False)
        total_bars += len(normalized)

        report = check_data_quality(normalized, symbol=symbol)
        print(report.summary())
        print()

    print("=" * 70)
    print("DOWNLOAD RESULT")
    print("=" * 70)
    for r in results:
        print(r.symbol)
        print(f"  Status:    {r.status}")
        print(f"  Requested: {r.requested_start} -> {r.requested_end}")
        print(f"  Returned:  {r.actual_start or 'n/a'} -> {r.actual_end or 'n/a'}")
        print(f"  Bars:      {r.bars}")
        if r.error:
            print(f"  Error:     {r.error}")
        print()

    # PARTIAL still produced usable data -- it is NOT a fetch failure and
    # must never be silently folded into either "written" or "failed"
    # bucket. Only EMPTY/FAILED (no usable data at all) count as failures
    # for the written-count/exit-code purposes below.
    hard_failures = [r for r in results if r.status in ("EMPTY", "FAILED")]

    print("=" * 70)
    print(f"Done: {len(symbols) - len(hard_failures)}/{len(symbols)} symbol(s) written, {total_bars:,} total bar(s), output -> {out_dir}")
    if hard_failures:
        print(f"Failed/empty: {', '.join(r.symbol for r in hard_failures)}")

    summary = {
        "provider": provider,
        "requested_start": args.start_date,
        "requested_end": args.end_date,
        "symbols": {
            r.symbol: {
                "status": r.status,
                "actual_start": r.actual_start,
                "actual_end": r.actual_end,
                "bars": r.bars,
                "error": r.error,
            }
            for r in results
        },
    }
    summary_path = out_dir / "download_summary.json"
    summary_path.write_text(json.dumps(summary, indent=2), encoding="utf-8")
    print(f"Summary written -> {summary_path}")

    # 2026-08-16 infra audit (Part B, finding #1) + 2026-08-17
    # FULL/PARTIAL/EMPTY/FAILED follow-up: exit non-zero whenever ANY
    # requested symbol is EMPTY or FAILED. PARTIAL is deliberately EXCLUDED
    # from this -- it produced real, usable data and must not be treated
    # as a fetch failure (see _classify_status's docstring); it is still
    # fully visible in both the console output and download_summary.json
    # above, just not silently upgraded to FULL or downgraded to a failure.
    return 1 if hard_failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
