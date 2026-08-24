"""Task 65B warmup fix -- causal, pre-market hydration of the real
QuantScanner before live evaluation begins.

Reuses QuantScanner.preseed_symbols() (talonx_quant/consumer.py) completely
unmodified -- the same production mechanism run_talonx.py's
WatchlistDrivenQuantPreseed already uses. No strategy semantics change.

Causality: preseed_symbols() -> talonx_quant.preseed.fetch_1m_history /
fetch_15m_history call `yfinance.Ticker(...).history(period=...)` with a
relative period string, which always ends AT CALL TIME -- calling this once,
before any live bar is fed to the scanner, is inherently causal (no bar
later than this call's timestamp is ever consumed by it). Historical
warmup is context only; every subsequent decision is driven by real-time
Alpaca IEX bars through the normal live path.

Mixed provider, by design: historical warmup context comes from yfinance
(preseed.py's existing, unmodified source); today's LIVE feed remains
Alpaca IEX. This does not change today's classification -- warmup traffic,
like every other event today, is OPERATIONAL_PIV_TEST_TRAFFIC /
alpha_evidence=false. See provider_continuity below.

Fail-closed per symbol, never synthesized: a symbol that cannot be
sufficiently hydrated is marked WARMUP_NOT_READY and excluded from the
decision engine's live symbol set for the rest of the session -- the same
exclusion mechanism SessionReadinessValidator already uses for
DATA_NOT_READY (see session_runner.py's readiness intersection). Nothing
here ever fabricates a bar or a computed value.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from typing import Any

from talonx_quant.indicators import compute_htf_trend

REQUIRED_1M_BARS = 120
REQUIRED_15M_BARS = 200
WARMUP_PROVIDER = "YFINANCE"
LIVE_PROVIDER = "ALPACA_IEX"
PROVIDER_CONTINUITY = "MIXED_PROVIDER_OPERATIONAL_PIV"


@dataclass(frozen=True)
class WarmupCheck:
    symbol: str
    preseed_status: str
    bar_count_1m: int
    required_1m_bars: int
    bar_count_15m_regular: int
    required_15m_bars: int
    htf_sma_200_available: bool
    warmup_provider: str
    live_provider: str
    evaluated_at: str
    reason: str
    ready: bool

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


async def preseed_and_verify(scanner: Any, universe: list[str], htf_sma_period: int) -> list[WarmupCheck]:
    """scanner: a talonx_quant.consumer.QuantScanner instance (typed Any
    here to avoid a hard import-time dependency in callers that only need
    the WarmupCheck dataclass)."""
    evaluated_at = datetime.now(timezone.utc).isoformat()
    try:
        await scanner.preseed_symbols(list(universe))
        preseed_status = "PRESEED_CALLED"
    except Exception as exc:  # noqa: BLE001 -- surfaced per-symbol below via actual bar counts, never raised
        preseed_status = f"PRESEED_RAISED_{type(exc).__name__}"

    results: list[WarmupCheck] = []
    for raw_symbol in universe:
        symbol = raw_symbol.upper()
        bar_count_1m = scanner.buffer.bar_count(symbol)
        df_htf = scanner.buffer_htf.get_dataframe(symbol)
        bar_count_15m = 0 if df_htf is None else len(df_htf)
        htf_sma_200 = compute_htf_trend(df_htf, htf_sma_period)
        ready_1m = bar_count_1m >= REQUIRED_1M_BARS
        ready_htf = htf_sma_200 is not None
        ready = ready_1m and ready_htf
        if ready:
            reason = "SUFFICIENT_1M_AND_HTF_HISTORY"
        elif not ready_1m and not ready_htf:
            reason = "INSUFFICIENT_1M_AND_HTF_HISTORY"
        elif not ready_1m:
            reason = "INSUFFICIENT_1M_HISTORY"
        else:
            reason = "INSUFFICIENT_HTF_HISTORY"
        results.append(WarmupCheck(
            symbol=symbol, preseed_status=preseed_status, bar_count_1m=bar_count_1m,
            required_1m_bars=REQUIRED_1M_BARS, bar_count_15m_regular=bar_count_15m,
            required_15m_bars=REQUIRED_15M_BARS, htf_sma_200_available=ready_htf,
            warmup_provider=WARMUP_PROVIDER, live_provider=LIVE_PROVIDER,
            evaluated_at=evaluated_at, reason=reason, ready=ready,
        ))
    return results
