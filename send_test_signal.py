"""
send_test_signal.py
----------------------
Publishes synthetic MarketTickEvent BAR messages to talonx:market:stream
for a single test ticker, engineered to reliably trigger an
RSI_OVERSOLD_VOLUME_SURGE QuantSignal in talonx_quant -- without waiting
on real market conditions to happen to line up.

Recipe (verified numerically against the actual pandas_ta RSI/MACD/SMA
math before writing this script -- see the three requirements below, all
three matter, not just the RSI one):

  1. RSI needs a real "was >= 30" state to cross away from. talonx_quant's
     RSI+volume check is edge-triggered (fires only on the crossing bar,
     see strategy.py) and min_bars_required=60 means nothing is evaluated
     before bar 60 at all. A price series that declines from bar 1 drives
     RSI to 0 almost immediately (there are never any "gains" for Wilder's
     RSI to average) -- by bar 60, BOTH the "previous" and "current" RSI
     are already 0, so there's no crossing left to observe and no signal
     ever fires (confirmed empirically: this was the original bug this
     three-phase recipe fixes).
  2. RSI needs to still be DECLINING at bar 60+, not already troughed.
     A flat or oscillating warm-up keeps RSI hovering near 50 but never
     lets it approach 30 -- the decline has to actually be in progress
     when the visible (bar 60+) window starts.
  3. No OTHER signal type (MACD cross, MA cross) may fire before the RSI
     crossing bar, or talonx_quant.consumer's per-ticker cooldown (also
     new -- see consumer.py) locks the ticker out and the RSI+volume
     signal never gets a chance to publish, even though it "would have"
     fired on paper.

  Three-phase price shape, verified against all three constraints above:
    - Phase 1 (bars 0-29): steady RISE, +0.5/bar. Builds real RSI gain
      history to draw down from, AND gives MACD/the MA cross their one
      reversal point here -- safely before bar 60, so it's invisible.
    - Phase 2 (bars 30-58): gentle DECLINE, -0.03/bar. Slow enough that
      MACD/MA stay settled in their post-reversal state (no second
      crossing), while RSI keeps eroding via Wilder's slow-moving average.
    - Phase 3 (bars 59-67): sharper DECLINE, -1.4/bar. Tips RSI under 30
      at bar 60 specifically (verified) -- 2 bars before the MA cross
      would otherwise land (bar 62), so the RSI+volume signal claims the
      per-ticker cooldown first and the MA signal is correctly suppressed
      as a duplicate, not a race.
  - Volume: normal (~1000) through bar 57, then a 5x spike (5000) for the
    last 10 bars -- wide enough to comfortably cover bar 60 (the verified
    crossing bar) even though it's earlier than the sequence's final bar.
    Against the 20-bar rolling average, this gives ~3.1x surge ratio at
    the crossing bar, past the default 2.0x threshold.

For a fully deterministic alternative that doesn't depend on any of this
(skips indicator computation entirely), see send_test_report_pair.py.

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


def build_bars(
    ticker: str,
    rise_bars: int = 30, rise_step: float = 0.5,
    settle_bars: int = 29, settle_step: float = 0.03,
    drop_bars: int = 9, drop_step: float = 1.4,
    volume_spike_bars: int = 10,
) -> list[dict]:
    """Three-phase price shape -- see the module docstring for why each
    phase exists and the exact bar this is verified to cross RSI under 30
    on (bar 60, against the defaults above)."""
    total = rise_bars + settle_bars + drop_bars
    base_time = datetime.now(timezone.utc) - timedelta(minutes=total)

    closes = []
    price = 150.0
    for _ in range(rise_bars):
        price += rise_step
        closes.append(price)
    for _ in range(settle_bars):
        price -= settle_step
        closes.append(price)
    for _ in range(drop_bars):
        price -= drop_step
        closes.append(price)

    bars = []
    for i, close in enumerate(closes):
        volume = 5000.0 if i >= total - volume_spike_bars else 1000.0
        bars.append({
            "event_type": "bar",
            "symbol": ticker.upper(),
            "source": "polling",
            "timestamp": (base_time + timedelta(minutes=i)).isoformat(),
            "open": close + 0.25,
            "high": close + 0.5,
            "low": close - 0.5,
            "close": close,
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
    print(f"Rise {bars[0]['close']:.2f} -> {bars[29]['close']:.2f}, gentle settle down to "
          f"{bars[58]['close']:.2f}, then a sharper drop to {bars[-1]['close']:.2f} -- crosses RSI "
          f"under 30 at bar 60 (verified). Volume spikes to 5000 for the last "
          f"{len(bars) - 58} bars, covering that crossing.")
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