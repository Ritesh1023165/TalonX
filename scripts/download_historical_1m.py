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
  3. yfinance fallback (no key needed) -- same
     `yf.Ticker(...).history(...)` call talonx_quant/preseed.py already
     uses, but Yahoo only serves roughly the trailing 30 days of
     1-minute history; a wider --start-date/--end-date range will
     simply come back short, logged loudly, not silently.

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
import logging
import os
import sys
import time
from datetime import datetime, timezone
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

    def _call():
        history = yf.Ticker(symbol.upper()).history(
            start=start_date, end=end_date, interval="1m", prepost=True,
        )
        if history is None or history.empty:
            return []
        bars = []
        for ts, row in history.iterrows():
            timestamp = ts.to_pydatetime() if hasattr(ts, "to_pydatetime") else ts
            if timestamp.tzinfo is None:
                timestamp = timestamp.replace(tzinfo=timezone.utc)
            bars.append({
                "timestamp": pd.Timestamp(timestamp).tz_convert("UTC"),
                "open": float(row["Open"]), "high": float(row["High"]),
                "low": float(row["Low"]), "close": float(row["Close"]), "volume": float(row["Volume"]),
            })
        return bars

    return _retry(_call, max_retries=max_retries, base_seconds=2.0, max_seconds=30.0, description=f"yfinance fetch for {symbol}")


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


def download_symbol(symbol: str, start_date: str, end_date: str, provider: str, max_retries: int) -> pd.DataFrame | None:
    fetch = _PROVIDERS[provider]
    try:
        bars = fetch(symbol, start_date, end_date, max_retries=max_retries)
    except DownloadError as exc:
        logger.warning("Giving up on %s via %s: %s", symbol, provider, exc)
        return None

    if not bars:
        logger.warning("%s: 0 bars returned by %s for %s -> %s", symbol, provider, start_date, end_date)
        return None

    df = pd.DataFrame(bars)[list(_BAR_COLUMNS)].sort_values("timestamp").reset_index(drop=True)
    logger.info("%s: downloaded %d bar(s) via %s (%s -> %s)", symbol, len(df), provider, df["timestamp"].iloc[0], df["timestamp"].iloc[-1])
    return df


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
    failed_symbols: list[str] = []
    for symbol in symbols:
        df = download_symbol(symbol, args.start_date, args.end_date, provider, args.max_retries)
        if df is None:
            failed_symbols.append(symbol)
            continue

        normalized = from_dataframe(df, symbol=symbol)
        out_path = out_dir / f"{symbol}.csv"
        normalized.to_csv(out_path, index=False)
        total_bars += len(normalized)

        report = check_data_quality(normalized, symbol=symbol)
        print(report.summary())
        print()

    print("=" * 70)
    print(f"Done: {len(symbols) - len(failed_symbols)}/{len(symbols)} symbol(s) written, {total_bars:,} total bar(s), output -> {out_dir}")
    if failed_symbols:
        print(f"Failed/empty: {', '.join(failed_symbols)}")
    return 1 if failed_symbols and len(failed_symbols) == len(symbols) else 0


if __name__ == "__main__":
    raise SystemExit(main())
