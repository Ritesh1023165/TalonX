"""
talonx_quant.buffer
-----------------------
In-memory rolling OHLCV buffer, one per ticker, bounded to
`max_bars_per_symbol` bars (oldest bars drop off as new ones arrive).

Only BAR-type MarketTickEvents feed the buffer. TRADE and QUOTE events
carry price/spread info but not the OHLCV shape pandas_ta needs, so
they're not part of this buffer (a consumer could track them separately
for sub-bar signals, but that's out of scope for the indicators this
module computes).

Every bar is tagged with its US-equities session (pre_market/regular/
closed, see session.py) -- Requirement 3's session-aware buffering:
`indicators.py` uses this tag to reset the ATR baseline at the regular-
session open, and `consumer.py` uses it to keep the 15-min HTF buffer
(the 200-SMA trend gate's source) restricted to regular-hours bars only.

Storage is keyed BY TIMESTAMP (a dict), not a plain append-only deque.
This was a deque originally, but that only de-duplicated against the
LAST entry -- fine when a symbol has exactly one writer feeding it
strictly in wall-clock order, but this buffer now has TWO independent
async writers per symbol that can interleave: consumer.py's live-tick
accumulator (_update_1m_buffer/_update_htf_buffer) and the historical
pre-seed path (preseed.py via _run_1m_preseed/_run_htf_preseed), which
awaits a blocking yfinance call mid-write and can resume after several
more live ticks have already landed. A deque's tail-only check let a
pre-seeded HISTORICAL bar for a timestamp a live tick had already
written land as a SECOND, separate entry instead of updating it in
place -- producing a genuine duplicate timestamp buried mid-buffer, which
crashed pandas_ta downstream ("cannot reindex on an axis with duplicate
labels") the moment get_dataframe() built a DataFrame from it. Keying by
timestamp makes every add_bar() call an upsert regardless of which
writer runs when, which is race-proof by construction.
"""
from __future__ import annotations

import logging
from datetime import datetime

import pandas as pd

from talonx_quant.session import get_session

logger = logging.getLogger("talonx_quant.buffer")


class RollingBarBuffer:
    def __init__(self, max_bars_per_symbol: int):
        self.max_bars_per_symbol = max_bars_per_symbol
        self._bars: dict[str, dict[datetime, dict]] = {}

    def add_bar(
        self,
        symbol: str,
        timestamp: datetime,
        open_: float | None,
        high: float | None,
        low: float | None,
        close: float | None,
        volume: float | None,
        session: str | None = None,
    ) -> None:
        if close is None:
            logger.debug("Dropping bar for %s with no close price", symbol)
            return

        symbol = symbol.upper()
        bars = self._bars.setdefault(symbol, {})
        session = session or get_session(timestamp)

        # Upsert by timestamp -- a caller may re-report the SAME bucket
        # timestamp more than once (e.g. consumer.py's minute/15-min
        # accumulators re-emit the still-forming bucket's running OHLCV
        # on every tick), and a concurrent historical pre-seed write can
        # also legitimately target a timestamp a live tick already wrote.
        # Either way this must REPLACE, never duplicate, that entry.
        bars[timestamp] = {
            "timestamp": timestamp, "open": open_, "high": high,
            "low": low, "close": close, "volume": volume, "session": session,
        }

        # Evict the OLDEST bar BY TIMESTAMP once over capacity -- not
        # insertion order. A pre-seed batch inserts a run of historical
        # (older) timestamps potentially AFTER newer live-tick bars
        # already exist, so insertion order and chronological order can
        # diverge; evicting by insertion order (a plain deque's maxlen
        # behavior) could evict a brand-new live bar while keeping a
        # stale historical one.
        if len(bars) > self.max_bars_per_symbol:
            del bars[min(bars)]

    def bar_count(self, symbol: str) -> int:
        return len(self._bars.get(symbol.upper(), {}))

    def get_dataframe(self, symbol: str) -> pd.DataFrame | None:
        """
        Returns a DataFrame sorted by timestamp with columns
        [open, high, low, close, volume], or None if the symbol has no
        bars yet. Does NOT enforce min_bars_required -- that's the
        indicators module's concern (this is just "give me what's buffered").
        """
        bars = self._bars.get(symbol.upper())
        if not bars:
            return None

        df = pd.DataFrame(list(bars.values()))
        df = df.sort_values("timestamp").reset_index(drop=True)
        df = df.set_index("timestamp")
        return df

    def known_symbols(self) -> list[str]:
        return list(self._bars.keys())

    def get_bars(self, symbol: str) -> list[dict]:
        """Raw bar dicts (timestamp/open/high/low/close/volume/session) in
        chronological order -- no DataFrame round-trip. This is the
        buffer-persistence checkpoint's source (see
        QuantScanner._checkpoint_all_buffers)."""
        bars = self._bars.get(symbol.upper())
        if not bars:
            return []
        return sorted(bars.values(), key=lambda bar: bar["timestamp"])
