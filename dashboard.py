"""
dashboard.py
----------------
Live, read-only terminal dashboard for the whole TalonX pipeline.
Subscribes to every Redis channel each module publishes to and renders a
live-updating table of message counts, throughput, and per-ticker
breakdowns -- one glance at how much data has moved through Modules 1-4
and where the activity actually is.

Channels watched:
    talonx:filings:events   (Module 1 -- NewFilingIngestedEvent)
    talonx:market:stream    (Module 1 -- MarketTickEvent)
    talonx:signals:quant    (Module 2 -- QuantSignal)
    talonx:reports:brain    (Module 3 -- ResearchReport)
    talonx:alerts:dispatch  (Module 4 -- ActionableAlert)

Purely an observer -- never publishes anything, and subscribing doesn't
affect delivery to the pipeline's real consumers (Redis Pub/Sub fans out
to every subscriber independently). In-memory only: counts reset if you
restart it. This is a live view, not a historical record -- see
talonx_ingest.storage.ledger / talonx_core.store for this project's
actual durable stores, deliberately not duplicated here since this tool
is meant to answer "what's happening right now," not "what happened
last week."

Usage:
    python dashboard.py
    python dashboard.py --top-n 8       # more/fewer tickers shown per channel
    python dashboard.py --refresh 0.5   # faster/slower redraw interval
"""
from __future__ import annotations

import argparse
import asyncio
import json
import os
import time
from collections import Counter, deque
from dataclasses import dataclass, field
from pathlib import Path

from dotenv import load_dotenv

# Same resolution approach as talonx_ingest/talonx_quant's own config.py --
# load the shared .env by path, not by searching the current directory.
_shared_env = Path(__file__).resolve().parent / "talonx_ingest" / ".env"
if _shared_env.is_file():
    load_dotenv(_shared_env, override=False)

from rich.console import Group
from rich.live import Live
from rich.panel import Panel
from rich.table import Table
from rich.text import Text

REDIS_URL = os.environ.get("TALONX_REDIS_URL", "redis://localhost:6379/0")


@dataclass
class ChannelWatch:
    key: str
    channel: str
    label: str
    ticker_field: str  # which JSON field holds the ticker/symbol for this schema


CHANNELS: list[ChannelWatch] = [
    ChannelWatch(
        "filings",
        os.environ.get("TALONX_REDIS_FILINGS_CHANNEL", "talonx:filings:events"),
        "M1 - Filings ingested", "ticker",
    ),
    ChannelWatch(
        "market",
        os.environ.get("TALONX_REDIS_MARKET_CHANNEL", "talonx:market:stream"),
        "M1 - Market ticks", "symbol",
    ),
    ChannelWatch(
        "signals",
        os.environ.get("TALONX_REDIS_SIGNALS_CHANNEL", "talonx:signals:quant"),
        "M2 - Quant signals", "ticker",
    ),
    ChannelWatch(
        "reports",
        os.environ.get("TALONX_REDIS_REPORTS_CHANNEL", "talonx:reports:brain"),
        "M3 - Research reports", "ticker",
    ),
    ChannelWatch(
        "alerts",
        os.environ.get("TALONX_REDIS_ALERTS_CHANNEL", "talonx:alerts:dispatch"),
        "M4 - Actionable alerts", "ticker",
    ),
]


@dataclass
class ChannelStats:
    total: int = 0
    unparseable: int = 0
    tickers: Counter = field(default_factory=Counter)
    # Rolling per-interval deltas -- unused by the terminal dashboard
    # (only dashboard_web.py calls snapshot_interval(), for its sparkline
    # charts), kept here so both tools share one ChannelStats definition.
    history: "deque[int]" = field(default_factory=lambda: deque(maxlen=60))
    _last_snapshot_total: int = 0

    def rate_per_min(self, elapsed_seconds: float) -> float:
        elapsed_min = max(elapsed_seconds / 60.0, 1e-9)
        return self.total / elapsed_min

    def snapshot_interval(self) -> int:
        """Records messages received since the last call into `history`. Returns the delta."""
        delta = self.total - self._last_snapshot_total
        self._last_snapshot_total = self.total
        self.history.append(delta)
        return delta


def _render(stats: dict[str, ChannelStats], started_at: float, top_n: int) -> Group:
    elapsed = time.monotonic() - started_at

    table = Table(expand=True)
    table.add_column("Channel")
    table.add_column("Total", justify="right")
    table.add_column("Rate/min", justify="right")
    table.add_column(f"Top {top_n} tickers")

    grand_total = 0
    all_tickers: Counter = Counter()
    for watch in CHANNELS:
        s = stats[watch.key]
        grand_total += s.total
        all_tickers.update(s.tickers)

        top = s.tickers.most_common(top_n)
        top_str = ", ".join(f"{ticker}:{count}" for ticker, count in top) or "-"
        rate = s.rate_per_min(elapsed)
        table.add_row(
            f"{watch.label}\n[dim]{watch.channel}[/dim]",
            str(s.total),
            f"{rate:.1f}",
            top_str,
        )
        if s.unparseable:
            table.add_row("", f"[yellow]{s.unparseable} unparseable[/yellow]", "", "")

    hours, remainder = divmod(int(elapsed), 3600)
    minutes, seconds = divmod(remainder, 60)
    uptime = f"{hours:02d}:{minutes:02d}:{seconds:02d}"

    header = Text.from_markup(
        f"[bold]TalonX Pipeline Dashboard[/bold]  |  up {uptime}  |  "
        f"{grand_total} messages total  |  {len(all_tickers)} distinct ticker(s) seen  |  "
        f"[dim]Ctrl+C to stop[/dim]"
    )
    return Group(header, table)


async def main(top_n: int, refresh_seconds: float) -> None:
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

    by_channel = {watch.channel: watch for watch in CHANNELS}
    stats: dict[str, ChannelStats] = {watch.key: ChannelStats() for watch in CHANNELS}

    pubsub = client.pubsub()
    await pubsub.subscribe(*by_channel.keys())

    started_at = time.monotonic()
    last_render = 0.0

    try:
        with Live(_render(stats, started_at, top_n), refresh_per_second=4, screen=False) as live:
            while True:
                message = await pubsub.get_message(ignore_subscribe_messages=True, timeout=1.0)
                if message is not None:
                    handle_message(message, by_channel, stats)

                now = time.monotonic()
                if now - last_render >= refresh_seconds:
                    live.update(_render(stats, started_at, top_n))
                    last_render = now
    except (KeyboardInterrupt, asyncio.CancelledError):
        pass
    finally:
        await pubsub.unsubscribe(*by_channel.keys())
        await pubsub.aclose()
        await client.aclose()
        elapsed = time.monotonic() - started_at
        print(f"\nStopped after {elapsed:.0f}s. Final counts:")
        for watch in CHANNELS:
            s = stats[watch.key]
            print(f"  {watch.label:28s} {s.total:6d} messages  ({len(s.tickers)} ticker(s))")


def handle_message(
    message: dict, by_channel: dict[str, ChannelWatch], stats: dict[str, ChannelStats]
) -> None:
    """Public (not `_`-prefixed) since dashboard_web.py imports and reuses this,
    along with CHANNELS/ChannelWatch/ChannelStats/REDIS_URL, to avoid keeping
    two copies of the channel-to-ticker-field mapping in sync."""
    raw = message.get("data")
    if raw is None:
        return

    channel = message.get("channel")
    if isinstance(channel, bytes):
        channel = channel.decode()
    watch = by_channel.get(channel)
    if watch is None:
        return

    s = stats[watch.key]
    s.total += 1
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError:
        s.unparseable += 1
        return

    ticker = payload.get(watch.ticker_field)
    if ticker:
        s.tickers[str(ticker).upper()] += 1


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Live terminal dashboard for the TalonX pipeline")
    parser.add_argument(
        "--top-n", type=int, default=5,
        help="How many top tickers to show per channel (default: 5)",
    )
    parser.add_argument(
        "--refresh", type=float, default=1.0,
        help="Redraw interval in seconds (default: 1.0)",
    )
    args = parser.parse_args()
    try:
        asyncio.run(main(args.top_n, args.refresh))
    except KeyboardInterrupt:
        pass
