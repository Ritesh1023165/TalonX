"""
send_test_signal.py
----------------------
Publishes synthetic MarketTickEvent BAR messages to talonx:market:stream
for a single test ticker, engineered to reliably trigger an
RSI_OVERSOLD_VOLUME_SURGE QuantSignal in talonx_quant -- without waiting
on real market conditions to happen to line up.

Recipe (verified against the actual RSI/volume-ratio math before writing
this script, not just assumed):
  - 70 bars with a steady 1.0-per-bar price decline. A pure decline drives
    RSI to 0 almost immediately (there are never any "gains" for the
    RSI formula to average), well under the default 30 threshold.
  - Normal volume (~1000) for the first 68 bars, then a 5x spike (5000)
    on the last 2 bars. Against a 20-bar rolling average, this produces
    a ~3.6x surge ratio, comfortably past the default 2.0x threshold.

Requires talonx_quant.run to be already running and subscribed, since
this only PUBLISHES -- it doesn't consume or compute anything itself.

Usage:
    python send_test_signal.py
    python send_test_signal.py --ticker MSFT --delay 0.05
"""
from __future__ import annotations

import argparse
import asyncio
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

from dotenv import load_dotenv

# Same resolution approach as talonx_ingest/talonx_quant's own config.py --
# load the shared .env by path, not by searching the current directory.
_shared_env = Path(__file__).resolve().parent / ".env"
if _shared_env.is_file():
    load_dotenv(_shared_env, override=False)

import os

REDIS_URL = os.environ.get("TALONX_REDIS_URL", "redis://localhost:6379/0")
MARKET_CHANNEL = os.environ.get("TALONX_REDIS_MARKET_CHANNEL", "talonx:market:stream")


def build_bars(ticker: str, count: int = 70) -> list[dict]:
    base_time = datetime.now(timezone.utc) - timedelta(minutes=count)
    bars = []
    for i in range(count):
        price = 150.0 - i  # steady decline -> drives RSI toward 0
        volume = 5000.0 if i >= count - 2 else 1000.0  # spike on the last 2 bars
        bars.append({
            "event_type": "bar",
            "symbol": ticker.upper(),
            "source": "polling",
            "timestamp": (base_time + timedelta(minutes=i)).isoformat(),
            "open": price + 0.5,
            "high": price + 1.0,
            "low": price - 0.5,
            "close": price,
            "volume": volume,
        })
    return bars


async def main(ticker: str, delay: float) -> None:
    try:
        import redis.asyncio as redis_asyncio
    except ImportError:
        print("The 'redis' package is required: pip install redis")
        return

    client = redis_asyncio.from_url(REDIS_URL)
    try:
        await client.ping()
    except Exception as exc:
        print(f"Could not connect to Redis at {REDIS_URL}: {exc}")
        print("Check that Redis is running and TALONX_REDIS_URL is correct.")
        return

    bars = build_bars(ticker)
    print(f"Publishing {len(bars)} synthetic bars for {ticker} to {MARKET_CHANNEL}")
    print(f"Price declines from {bars[0]['close']} to {bars[-1]['close']}, "
          f"volume spikes to {bars[-1]['volume']} on the last 2 bars")
    print("Make sure `python -m talonx_quant.run` is already running in another terminal.\n")

    for i, bar in enumerate(bars):
        await client.publish(MARKET_CHANNEL, json.dumps(bar))
        if (i + 1) % 10 == 0 or i == len(bars) - 1:
            print(f"  Published bar {i + 1}/{len(bars)} (close={bar['close']}, volume={bar['volume']})")
        await asyncio.sleep(delay)

    print(f"\nDone. Check the talonx_quant.run terminal for a "
          f"'Signal: {ticker.upper()} rsi_oversold_volume_surge' log line.")
    await client.aclose()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Publish synthetic bars to trigger a test QuantSignal")
    parser.add_argument("--ticker", default="TESTQ", help="Ticker symbol to use (default: TESTQ)")
    parser.add_argument("--delay", type=float, default=0.05, help="Seconds between bar publishes (default: 0.05)")
    args = parser.parse_args()
    asyncio.run(main(args.ticker, args.delay))