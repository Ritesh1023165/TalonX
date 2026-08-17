"""
dashboard.py
----------------
Live, read-only terminal dashboard for the whole TalonX pipeline.
Subscribes to every Redis channel each module publishes to and renders a
live-updating table of message counts, throughput, per-ticker, and
per-CATEGORY breakdowns -- one glance at how much data has moved through
Modules 1-6 and where the activity actually is.

Channels watched:
    talonx:filings:events       (Module 1 -- NewFilingIngestedEvent)
    talonx:market:stream        (Module 1 -- MarketTickEvent)
    talonx:signals:quant        (Module 2 -- QuantSignal)
    talonx:reports:brain        (Module 3 -- ResearchReport)
    talonx:alerts:dispatch      (Module 4 -- ActionableAlert)
    talonx:paper:trades         (Module 6 -- PaperTradeExecution)

    Phase 2 (LONG_TERM horizon) -- see README.md §3.9:
    talonx:fundamentals:events  (Module 1 -- NewFundamentalsIngestedEvent)
    talonx:signals:fundamental  (Module 2 -- FundamentalFactorSignal)
    talonx:reports:longterm     (Module 3 -- LongTermResearchReport)
    talonx:alerts:longterm      (Module 4 -- LongTermActionableAlert)
    talonx:paper:trades:longterm (Module 6 -- LongTermTradeExecution)

The category breakdowns (e.g. "how many of those ResearchReports were
actual LLM calls vs. cache hits") are derived entirely from fields
ALREADY present in each message's payload -- no other module needed any
change for this, since every category here was already being published,
just not broken out. This is also why some genuinely useful metrics
CAN'T show up here: a suppressed talonx_quant signal (cooldown/throttle),
a failed Telegram send, or an ignored paper trade never gets published to
begin with, so a pure Redis-message observer has nothing to count -- that
would need each module to explicitly publish its own internal counters
somewhere, which none of them do today.

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
from typing import Callable

from dotenv import load_dotenv

# Same resolution approach as talonx_ingest/talonx_quant's own config.py --
# load the shared .env by path, not by searching the current directory.
_shared_env = Path(__file__).resolve().parent / ".env"
if _shared_env.is_file():
    load_dotenv(_shared_env, override=False)

from rich.console import Group
from rich.live import Live
from rich.panel import Panel
from rich.table import Table
from rich.text import Text

REDIS_URL = os.environ.get("TALONX_REDIS_URL", "redis://localhost:6379/0")


def _categorize_report(payload: dict) -> str | None:
    """talonx:reports:brain -- breaks a ResearchReport down by how much
    LLM/Gemini spend it actually cost (Module 3's caching, README §3.3):
    a cache hit or stale fallback made NO retrieval+LLM call at all, a
    cold start made a retrieval call but bypassed the LLM, a degraded
    report means the LLM call FAILED, and "LLM call" is everything else
    -- a genuine, billed Gemini/Ollama request. This is the "count of LLM
    calls" the dashboard didn't show before."""
    if payload.get("from_cache"):
        return "stale fallback (no LLM)" if payload.get("is_stale") else "cache hit (no LLM)"
    if payload.get("is_degraded"):
        return "degraded (LLM failed)"
    if payload.get("verdict") == "insufficient_context":
        return "cold start (no LLM)"
    return "LLM call"


def _categorize_field(field_name: str) -> Callable[[dict], str | None]:
    """Generic categorizer: just read one field and title-case it (used
    for signal_type, action, order_type -- plain enum-valued fields that
    don't need report.py's derived-condition logic above)."""
    def _categorize(payload: dict) -> str | None:
        value = payload.get(field_name)
        return str(value).replace("_", " ") if value else None
    return _categorize


@dataclass
class ChannelWatch:
    key: str
    channel: str
    label: str
    ticker_field: str  # which JSON field holds the ticker/symbol for this schema
    # Optional category breakdown (e.g. LLM-call vs cache-hit, signal
    # type, alert action, BUY vs SELL) -- purely derived from the
    # message payload, see module docstring for why this is the only
    # kind of "metric" a Redis-pub/sub observer can show.
    categorize: Callable[[dict], str | None] | None = None
    category_label: str = "Breakdown"
    # Optional running sum of a numeric field (used for paper trading's
    # realized PnL -- a total, not a count).
    numeric_field: str | None = None
    numeric_label: str = ""


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
        categorize=_categorize_field("signal_type"), category_label="Signal types",
    ),
    ChannelWatch(
        "reports",
        os.environ.get("TALONX_REDIS_REPORTS_CHANNEL", "talonx:reports:brain"),
        "M3 - Research reports", "ticker",
        categorize=_categorize_report, category_label="LLM usage",
    ),
    ChannelWatch(
        "alerts",
        os.environ.get("TALONX_REDIS_ALERTS_CHANNEL", "talonx:alerts:dispatch"),
        "M4 - Actionable alerts", "ticker",
        categorize=_categorize_field("action"), category_label="Actions",
    ),
    ChannelWatch(
        "paper_trades",
        os.environ.get("TALONX_REDIS_PAPER_TRADES_CHANNEL", "talonx:paper:trades"),
        "M6 - Paper trades", "ticker",
        categorize=_categorize_field("order_type"), category_label="Order type",
        numeric_field="realized_pnl_usd", numeric_label="Realized PnL ($)",
    ),
    # --- Phase 2 (LONG_TERM horizon) -- see README.md §3.9. Same
    # ChannelWatch shape as the intraday channels above, just pointed at
    # the long-term wire schemas' equivalent fields; nothing else in this
    # file needed to change since _render/handle_message/dashboard_web.py
    # all iterate CHANNELS generically.
    ChannelWatch(
        "fundamentals_events",
        os.environ.get("TALONX_REDIS_FUNDAMENTALS_CHANNEL", "talonx:fundamentals:events"),
        "M1 - Financials ingested (LT)", "ticker",
    ),
    ChannelWatch(
        "fundamental_signals",
        os.environ.get("TALONX_REDIS_FUNDAMENTAL_SIGNALS_CHANNEL", "talonx:signals:fundamental"),
        "M2 - Fundamental signals (LT)", "ticker",
        categorize=_categorize_field("fiscal_year"), category_label="Fiscal year",
    ),
    ChannelWatch(
        "reports_longterm",
        os.environ.get("TALONX_REDIS_REPORTS_LONG_TERM_CHANNEL", "talonx:reports:longterm"),
        "M3 - Long-term reports (LT)", "ticker",
        categorize=_categorize_field("moat_rating"), category_label="Moat rating",
    ),
    ChannelWatch(
        "alerts_longterm",
        os.environ.get("TALONX_REDIS_ALERTS_LONG_TERM_CHANNEL", "talonx:alerts:longterm"),
        "M4 - Long-term alerts (LT)", "ticker",
        categorize=_categorize_field("action"), category_label="Actions",
    ),
    ChannelWatch(
        "paper_trades_longterm",
        os.environ.get("TALONX_REDIS_PAPER_TRADES_LONG_TERM_CHANNEL", "talonx:paper:trades:longterm"),
        "M6 - Long-term paper trades (LT)", "ticker",
        categorize=_categorize_field("order_type"), category_label="Order type",
        numeric_field="realized_pnl_usd", numeric_label="Realized PnL ($)",
    ),
]


@dataclass
class ChannelStats:
    total: int = 0
    unparseable: int = 0
    tickers: Counter = field(default_factory=Counter)
    categories: Counter = field(default_factory=Counter)  # watch.categorize(payload) breakdown
    numeric_total: float = 0.0  # running sum of watch.numeric_field, if set
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
    table.add_column("Breakdown")
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

        breakdown_str = "-"
        if watch.categorize is not None:
            cats = s.categories.most_common()
            breakdown_str = ", ".join(f"{cat}:{count}" for cat, count in cats) or "-"
        if watch.numeric_field is not None:
            sign = "+" if s.numeric_total >= 0 else ""
            pnl = f"{watch.numeric_label} {sign}{s.numeric_total:,.2f}"
            breakdown_str = pnl if breakdown_str == "-" else f"{breakdown_str}\n{pnl}"

        table.add_row(
            f"{watch.label}\n[dim]{watch.channel}[/dim]",
            str(s.total),
            f"{rate:.1f}",
            breakdown_str,
            top_str,
        )
        if s.unparseable:
            table.add_row("", f"[yellow]{s.unparseable} unparseable[/yellow]", "", "", "")

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

    if watch.categorize is not None:
        category = watch.categorize(payload)
        if category:
            s.categories[category] += 1

    if watch.numeric_field is not None:
        value = payload.get(watch.numeric_field)
        if isinstance(value, (int, float)):
            s.numeric_total += value


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
