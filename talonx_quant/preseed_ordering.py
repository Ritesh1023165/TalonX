"""Task 66B-PREP: deterministic initial Quant preseed ordering.

Closes a startup race in run_talonx.py: WatchlistDrivenQuantPreseed's own
initial preseed (talonx_quant/consumer.py's preseed_symbols(), driven by
run_talonx.py) previously ran as an asyncio task created in the same
batch as market_data_runner's task and quant_scanner.run()'s own task --
all scheduled via asyncio.create_task() with no ordering guarantee against
preseed's real yfinance network I/O. A live tick could therefore reach
QuantScanner._handle_message before its RollingBarBuffers were hydrated,
depending on scheduling luck.

run_initial_preseed(), below, is awaited directly in run_talonx.py's
main() -- BEFORE any task is created -- so it fully completes (or fails
per-symbol) before market data / QuantScanner.run() can start. Reuses
QuantScanner.preseed_symbols() completely unmodified; never duplicates its
implementation. Verifies per-symbol readiness afterward by reading the
scanner's own real buffer state (never trusts "preseed returned" alone),
using the scanner's own configured thresholds (config.min_bars_required,
config.htf_sma_period) so this can never drift from talonx_quant/config.py's
real values.

Fail-closed per symbol, never synthesized: a symbol that isn't sufficiently
hydrated is simply reported not-ready here -- it still runs normally
afterward via QuantScanner's own existing live-accumulation fallback
(unchanged), same as it already does today. This module never raises or
blocks the caller on a partial or even zero-ready result; that policy
decision belongs to the caller (main(), or a preflight check), not here.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from typing import Any

from talonx_quant.indicators import compute_htf_trend


@dataclass(frozen=True)
class InitialPreseedStatus:
    symbol: str
    bar_count_1m: int
    required_1m_bars: int
    bar_count_15m_htf: int
    required_15m_bars: int
    htf_sma_available: bool
    ready: bool
    reason: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class InitialPreseedReport:
    evaluated_at: str
    requested_symbols: tuple[str, ...]
    statuses: tuple[InitialPreseedStatus, ...]

    @property
    def ready_symbols(self) -> list[str]:
        return [s.symbol for s in self.statuses if s.ready]

    @property
    def is_blocked(self) -> bool:
        """True only when symbols were actually requested and none of them
        came up ready -- an empty watchlist is not a blocked state."""
        return len(self.requested_symbols) > 0 and not self.ready_symbols

    def to_dict(self) -> dict[str, Any]:
        return {
            "evaluated_at": self.evaluated_at,
            "requested_symbols": list(self.requested_symbols),
            "requested_count": len(self.requested_symbols),
            "ready_symbols": self.ready_symbols,
            "ready_count": len(self.ready_symbols),
            "is_blocked": self.is_blocked,
            "statuses": [s.to_dict() for s in self.statuses],
        }


async def run_initial_preseed(scanner: Any, symbols: list[str]) -> InitialPreseedReport:
    """scanner: a talonx_quant.consumer.QuantScanner instance (typed Any to
    avoid a hard import-time dependency for callers that only need the
    dataclasses above, e.g. tests using a lightweight fake).

    Must be awaited to completion by the caller before any live market-data
    task or quant_scanner.run() task is created -- that ordering, not
    anything inside this function, is what makes the whole thing causal."""
    requested = tuple(sorted({s.upper() for s in symbols}))
    evaluated_at = datetime.now(timezone.utc).isoformat()
    if requested:
        try:
            await scanner.preseed_symbols(list(requested))
        except Exception:  # noqa: BLE001 -- QuantScanner.preseed_symbols() already catches
            # per-symbol fetch failures internally and never raises in
            # practice; this is defense-in-depth only, so a genuinely
            # unexpected failure still surfaces per-symbol below as
            # not-ready (real buffer state), never fabricated, and never
            # blocks the rest of startup.
            pass

    min_1m = scanner.config.min_bars_required
    min_htf = scanner.config.htf_sma_period
    statuses: list[InitialPreseedStatus] = []
    for symbol in requested:
        bar_count_1m = scanner.buffer.bar_count(symbol)
        df_htf = scanner.buffer_htf.get_dataframe(symbol)
        bar_count_htf = 0 if df_htf is None else len(df_htf)
        htf_available = compute_htf_trend(df_htf, min_htf) is not None
        ready_1m = bar_count_1m >= min_1m
        ready = ready_1m and htf_available
        if ready:
            reason = "SUFFICIENT_1M_AND_HTF_HISTORY"
        elif not ready_1m and not htf_available:
            reason = "INSUFFICIENT_1M_AND_HTF_HISTORY"
        elif not ready_1m:
            reason = "INSUFFICIENT_1M_HISTORY"
        else:
            reason = "INSUFFICIENT_HTF_HISTORY"
        statuses.append(InitialPreseedStatus(
            symbol=symbol, bar_count_1m=bar_count_1m, required_1m_bars=min_1m,
            bar_count_15m_htf=bar_count_htf, required_15m_bars=min_htf,
            htf_sma_available=htf_available, ready=ready, reason=reason,
        ))
    return InitialPreseedReport(evaluated_at=evaluated_at, requested_symbols=requested, statuses=tuple(statuses))
