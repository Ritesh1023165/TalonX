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

Task 70S -- Alpaca IEX historical 1-minute warmup, wired in ahead of the
yfinance path: when `piv_config` is supplied (real sessions only; every
existing caller/test that omits it gets EXACTLY the prior yfinance-only
behavior, unchanged), each symbol's 1-minute buffer is first hydrated
directly from run_alpaca_1m_warmup (talonx_piv/alpaca_historical_warmup.py)
via the SAME public RollingBarBuffer.add_bar API consumer.py's own preseed
path uses -- talonx_quant/consumer.py, strategy.py, indicators.py, and
config.py are never imported or modified here. scanner.preseed_symbols()
is then still called unconditionally for every symbol (HTF/60m legs are
untouched by this change) -- for the 1-minute leg specifically, its own
_preseed_1m_if_needed guard (`if self.buffer.bar_count(symbol) >=
self.config.min_bars_required: return`) means yfinance is transparently
skipped for any symbol Alpaca already sufficiently warmed, and runs exactly
as before for any symbol Alpaca could not (or was not configured to)
supply -- a real fallback, never a silent override in either direction.

No cross-date warmup cache exists anywhere in this module: both the Alpaca
and yfinance legs recompute their entire requested range from the CURRENT
causal cutoff on every call, so there is no persisted warmup state that
could ever be reused across a different ET trading date (see readiness.py
for the SEPARATE, already-existing 09:30-09:59 session-readiness state,
which does persist/restore and is unaffected by this change).

Mixed provider, by design: historical warmup context comes from Alpaca IEX
history and/or yfinance (preseed.py's existing, unmodified source); today's
LIVE feed remains Alpaca IEX. This does not change today's classification --
warmup traffic, like every other event today, is OPERATIONAL_PIV_TEST_TRAFFIC
/ alpha_evidence=false. See provider_continuity below.

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
from typing import Any, Callable

from talonx_quant.indicators import compute_htf_trend

from .alpaca_historical_warmup import run_alpaca_1m_warmup

REQUIRED_1M_BARS = 120
REQUIRED_15M_BARS = 200
WARMUP_PROVIDER = "YFINANCE"
LIVE_PROVIDER = "ALPACA_IEX"
PROVIDER_CONTINUITY = "MIXED_PROVIDER_OPERATIONAL_PIV"
ALPACA_WARMUP_NOT_ATTEMPTED = "NOT_ATTEMPTED"


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
    # Task 70S additions -- all default-valued so every pre-existing
    # construction call site (there is exactly one, below) and every
    # pre-existing test (which only ever reads attributes, never
    # constructs WarmupCheck directly) is unaffected.
    alpaca_attempted: bool = False
    alpaca_status: str = ALPACA_WARMUP_NOT_ATTEMPTED
    alpaca_bar_count: int = 0
    alpaca_reason: str = ""
    bar_count_1m_source: str = "NONE"

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


async def preseed_and_verify(
    scanner: Any, universe: list[str], htf_sma_period: int, *,
    piv_config: Any | None = None,
    now: datetime | None = None,
    alpaca_transport: Any = None,
    alpaca_sleep_fn: Callable[[float], None] = lambda _seconds: None,
) -> list[WarmupCheck]:
    """scanner: a talonx_quant.consumer.QuantScanner instance (typed Any
    here to avoid a hard import-time dependency in callers that only need
    the WarmupCheck dataclass).

    piv_config: optional talonx_piv.config.PivConfig (duck-typed here, same
    reason). None (the default -- every pre-Task-70S caller) skips the
    Alpaca leg entirely and reproduces the exact prior yfinance-only
    behavior. When supplied with non-empty key_id/secret_key, each symbol's
    1-minute buffer is hydrated from Alpaca FIRST (see module docstring),
    strictly before scanner.preseed_symbols() runs.

    alpaca_sleep_fn defaults to a no-op (not time.sleep) so this integration
    point never sleeps in a caller/test that doesn't explicitly ask for
    real backoff timing -- see alpaca_historical_warmup.run_alpaca_1m_warmup
    for the retry/backoff contract itself.
    """
    evaluated_at_dt = now or datetime.now(timezone.utc)
    evaluated_at = evaluated_at_dt.isoformat()

    alpaca_by_symbol: dict[str, Any] = {}
    key_id = getattr(piv_config, "key_id", "") if piv_config is not None else ""
    secret_key = getattr(piv_config, "secret_key", "") if piv_config is not None else ""
    if piv_config is not None and key_id and secret_key:
        from .config import FEED_MODE_PARAM  # local import: avoids a hard cycle at module load time

        transport = alpaca_transport
        if transport is None:
            import requests as transport  # lazy import -- same optionality posture as preseed.py's yfinance import
        feed = FEED_MODE_PARAM.get(piv_config.feed_mode, "iex")
        for raw_symbol in universe:
            symbol = raw_symbol.upper()
            try:
                result, bars = run_alpaca_1m_warmup(
                    transport, piv_config.data_endpoint, key_id, secret_key, symbol,
                    causal_cutoff=evaluated_at_dt, required_bars=REQUIRED_1M_BARS, feed=feed,
                    sleep_fn=alpaca_sleep_fn,
                )
            except Exception as exc:  # noqa: BLE001 -- per-symbol isolation: one bad symbol must not abort the batch
                from .alpaca_historical_warmup import ALPACA_HISTORICAL_PROVIDER, AlpacaWarmupResult, STATUS_PROVIDER_ERROR
                result = AlpacaWarmupResult(
                    symbol=symbol, status=STATUS_PROVIDER_ERROR, provider=ALPACA_HISTORICAL_PROVIDER, feed=feed,
                    requested_start="", requested_end="", bar_count=0, pages_fetched=0, retries=0,
                    duplicate_bars_dropped=0, future_bars_dropped=0, invalid_rows_dropped=0,
                    reason=f"UNEXPECTED_{type(exc).__name__}",
                )
                bars = []
            alpaca_by_symbol[symbol] = result
            for bar in bars:
                scanner.buffer.add_bar(
                    symbol=symbol, timestamp=bar.timestamp, open_=bar.open, high=bar.high,
                    low=bar.low, close=bar.close, volume=bar.volume,
                )

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

        alpaca_result = alpaca_by_symbol.get(symbol)
        if alpaca_result is None:
            alpaca_source = "NONE"
        elif alpaca_result.bar_count >= REQUIRED_1M_BARS:
            alpaca_source = "ALPACA"
        elif alpaca_result.bar_count > 0:
            alpaca_source = "ALPACA_PARTIAL_PLUS_YFINANCE"
        else:
            alpaca_source = "YFINANCE_FALLBACK"

        results.append(WarmupCheck(
            symbol=symbol, preseed_status=preseed_status, bar_count_1m=bar_count_1m,
            required_1m_bars=REQUIRED_1M_BARS, bar_count_15m_regular=bar_count_15m,
            required_15m_bars=REQUIRED_15M_BARS, htf_sma_200_available=ready_htf,
            warmup_provider=WARMUP_PROVIDER, live_provider=LIVE_PROVIDER,
            evaluated_at=evaluated_at, reason=reason, ready=ready,
            alpaca_attempted=alpaca_result is not None,
            alpaca_status=alpaca_result.status if alpaca_result is not None else ALPACA_WARMUP_NOT_ATTEMPTED,
            alpaca_bar_count=alpaca_result.bar_count if alpaca_result is not None else 0,
            alpaca_reason=alpaca_result.reason if alpaca_result is not None else "",
            bar_count_1m_source=alpaca_source,
        ))
    return results
