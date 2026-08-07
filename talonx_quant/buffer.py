"""
talonx_quant.buffer
-----------------------
In-memory rolling OHLCV buffer, one per ticker, bounded to
`max_bars_per_symbol` bars (oldest bars drop off as new ones arrive --
a deque, not an ever-growing list, since this process is meant to run
continuously).

Only BAR-type MarketTickEvents feed the buffer. TRADE and QUOTE events
carry price/spread info but not the OHLCV shape pandas_ta needs, so
they're not part of this buffer (a consumer could track them separately
for sub-bar signals, but that's out of scope for the indicators this
module computes).
"""
from __future__ import annotations

import logging
from collections import deque
from datetime import datetime

import pandas as pd

logger = logging.getLogger("talonx_quant.buffer")


class RollingBarBuffer:
    def __init__(self, max_bars_per_symbol: int):
        self.max_bars_per_symbol = max_bars_per_symbol
        self._bars: dict[str, deque] = {}

    def add_bar(
        self,
        symbol: str,
        timestamp: datetime,
        open_: float | None,
        high: float | None,
        low: float | None,
        close: float | None,
        volume: float | None,
    ) -> None:
        if close is None:
            logger.debug("Dropping bar for %s with no close price", symbol)
            return

        symbol = symbol.upper()
        if symbol not in self._bars:
            self._bars[symbol] = deque(maxlen=self.max_bars_per_symbol)

        buf = self._bars[symbol]

        # yfinance polling re-sends a snapshot of the CURRENT bar every poll
        # cycle (it's not a discrete "new bar arrived" push like a real
        # WebSocket aggregate) -- without this check, a 5-second poll
        # interval would flood the buffer with dozens of near-identical
        # rows for what is, price-action-wise, the same bar. Only append if
        # this is a genuinely new timestamp; otherwise update the latest
        # bar's OHLCV in place.
        if buf and buf[-1]["timestamp"] == timestamp:
            buf[-1] = {
                "timestamp": timestamp, "open": open_, "high": high,
                "low": low, "close": close, "volume": volume,
            }
        else:
            buf.append({
                "timestamp": timestamp, "open": open_, "high": high,
                "low": low, "close": close, "volume": volume,
            })

    def bar_count(self, symbol: str) -> int:
        return len(self._bars.get(symbol.upper(), ()))

    def get_dataframe(self, symbol: str) -> pd.DataFrame | None:
        """
        Returns a DataFrame sorted by timestamp with columns
        [open, high, low, close, volume], or None if the symbol has no
        bars yet. Does NOT enforce min_bars_required -- that's the
        indicators module's concern (this is just "give me what's buffered").
        """
        buf = self._bars.get(symbol.upper())
        if not buf:
            return None

        df = pd.DataFrame(list(buf))
        df = df.sort_values("timestamp").reset_index(drop=True)
        df = df.set_index("timestamp")
        return df

    def known_symbols(self) -> list[str]:
        return list(self._bars.keys())
