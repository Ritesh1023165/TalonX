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


@dataclass(frozen=True)
class RecoveryStatus:
    symbol: str
    attempts: int
    recovered: bool
    bar_count_1m: int
    required_1m_bars: int

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class RecoveryReport:
    evaluated_at: str
    attempted_symbols: tuple[str, ...]
    statuses: tuple[RecoveryStatus, ...]
    elapsed_seconds: float
    budget_exhausted: bool

    @property
    def recovered_symbols(self) -> list[str]:
        return [s.symbol for s in self.statuses if s.recovered]

    @property
    def still_incomplete_symbols(self) -> list[str]:
        return [s.symbol for s in self.statuses if not s.recovered]

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        d["recovered_symbols"] = self.recovered_symbols
        d["still_incomplete_symbols"] = self.still_incomplete_symbols
        return d


async def run_bounded_recovery_sweep(
    scanner: Any,
    report: InitialPreseedReport,
    *,
    max_attempts: int = 2,
    per_symbol_timeout_s: float = 15.0,
    overall_budget_s: float = 120.0,
    backoff_base_s: float = 2.0,
    sleep_fn=None,
) -> RecoveryReport:
    """Task 118F -- bounded, ONE-SHOT retry of ONLY the symbols the initial
    preseed above left not-ready (a bulk provider failure, a transient
    schema error, etc -- see docs/audits/task118f_resilient_warmup/ for
    the evidenced incident this responds to).

    Must be awaited to completion by the caller in the SAME safety window
    run_initial_preseed already requires: BEFORE any live market-data task
    or quant_scanner.run() task is created. This is a deliberate, load-
    bearing safety choice, not an oversight -- it means this sweep can
    NEVER race a live tick write to the same buffer timestamp, so the
    existing add_bar() upsert-by-timestamp behavior (buffer.py) needs no
    new coordination to stay correct. It also means recovery is naturally
    "restart-safe": each process start gets exactly one sweep, over
    exactly that start's own not-ready set -- there is no persisted
    recovery-worker state to duplicate or leak across a restart.

    Reuses QuantScanner.preseed_symbols() -- the SAME already-proven,
    buffer-only fetch/insert path run_initial_preseed itself uses -- for
    the actual fetch. No new fetch or buffer-write logic exists here.
    QuantScanner.preseed_symbols() is a strict no-op for a symbol already
    marked internally as "preseeded" (by design, for the normal case: a
    warm symbol should never be re-fetched) -- a symbol whose FIRST
    attempt failed would otherwise never get a second one for the rest of
    the process's life. This sweep clears ONLY that internal marker, and
    ONLY for a symbol independently re-verified (from the live buffer
    count, never assumed) to still be below its OWN real threshold right
    now -- never a symbol already ready, never a synthesized bar, never a
    changed threshold.

    Bounded: at most `max_attempts` rounds, `per_symbol_timeout_s` per
    fetch call, one shared `overall_budget_s` wall-clock ceiling across
    the whole sweep (checked before every fetch, never exceeded), and one
    symbol fetched at a time within a round (matches preseed_symbols'
    own existing sequential-per-call contract -- no new concurrency, no
    request storm, no overlapping pollers).

    Emits nothing beyond buffer/indicator state: no alert, no paper
    trade, no Telegram message, no Redis publish -- preseed_symbols()
    already guarantees this (verified: it only ever calls buffer.add_bar
    and store.checkpoint_buffer; it has no signal/dispatch code path at
    all), and this sweep adds no new call site that could change that.
    """
    import asyncio
    import time

    sleep_fn = sleep_fn or asyncio.sleep
    incomplete = [s.symbol for s in report.statuses if not s.ready]
    started = time.monotonic()
    attempts: dict[str, int] = {s: 0 for s in incomplete}
    remaining = list(incomplete)
    budget_exhausted = False

    for attempt_round in range(max_attempts):
        if not remaining:
            break
        if (time.monotonic() - started) >= overall_budget_s:
            budget_exhausted = True
            break
        if attempt_round > 0:
            await sleep_fn(backoff_base_s * (2 ** (attempt_round - 1)))
        next_remaining: list[str] = []
        for symbol in remaining:
            if (time.monotonic() - started) >= overall_budget_s:
                budget_exhausted = True
                next_remaining.append(symbol)
                continue
            # re-verify from the live buffer -- never trust a stale report
            if scanner.buffer.bar_count(symbol) >= scanner.config.min_bars_required:
                continue  # already recovered (e.g. by live accumulation) -- nothing to retry
            attempts[symbol] += 1
            # Clear ONLY this symbol's "already attempted" marker so the
            # existing, unmodified fetch path in preseed_symbols() runs
            # again -- no new fetch code, no bypass of its own logic.
            scanner._preseeded_1m.discard(symbol)
            try:
                await asyncio.wait_for(scanner.preseed_symbols([symbol]), timeout=per_symbol_timeout_s)
            except Exception:  # noqa: BLE001 -- one symbol's failure must never abort the sweep
                pass
            if scanner.buffer.bar_count(symbol) < scanner.config.min_bars_required:
                next_remaining.append(symbol)
        remaining = next_remaining

    statuses = tuple(
        RecoveryStatus(
            symbol=s, attempts=attempts.get(s, 0),
            recovered=scanner.buffer.bar_count(s) >= scanner.config.min_bars_required,
            bar_count_1m=scanner.buffer.bar_count(s), required_1m_bars=scanner.config.min_bars_required,
        )
        for s in incomplete
    )
    return RecoveryReport(
        evaluated_at=datetime.now(timezone.utc).isoformat(),
        attempted_symbols=tuple(incomplete), statuses=statuses,
        elapsed_seconds=time.monotonic() - started, budget_exhausted=budget_exhausted,
    )
