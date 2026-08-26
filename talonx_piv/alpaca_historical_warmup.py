"""Task 69Q Part 9 / Task 70S -- Alpaca IEX historical one-minute warmup.

Task 70S wires this module INTO the live warmup path (see warmup.py's
preseed_and_verify), replacing yfinance as the PRIMARY 1-minute pre-session
history source whenever Alpaca credentials are configured and Alpaca
actually has the data -- yfinance remains as an untouched, unmodified
fallback (talonx_quant.consumer.QuantScanner.preseed_symbols, still called
every warmup regardless) for whatever Alpaca could not supply. See
run_alpaca_1m_warmup's own docstring for the causal-cutoff/pagination/retry
contract and warmup.py's module docstring for how the two providers combine
without either silently overriding the other.

fetch_1m_bars (the original Task 69Q prototype) is UNCHANGED in external
behavior -- single page, no retry, fails closed to [] on any non-200 or
transport exception. It is refactored internally to share the same
request/parse helpers run_alpaca_1m_warmup uses, purely to avoid duplicating
the Alpaca bar-schema parsing logic; its own existing tests
(tests/test_task69q_alpaca_historical_warmup.py) are unaffected.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime, timedelta, timezone
from typing import Any, Callable
import time as _time

ALPACA_HISTORICAL_PROVIDER = "ALPACA_HISTORICAL"

# Deterministic per-symbol outcomes -- see module docstring / Task 70S spec.
STATUS_READY = "READY"
STATUS_INSUFFICIENT_HISTORY = "INSUFFICIENT_HISTORY"
STATUS_EMPTY = "EMPTY"
STATUS_TIMEOUT = "TIMEOUT"
STATUS_RATE_LIMITED = "RATE_LIMITED"
STATUS_PROVIDER_ERROR = "PROVIDER_ERROR"
STATUS_INVALID_DATA = "INVALID_DATA"

MAX_PAGES = 20
DEFAULT_MAX_RETRIES = 3
DEFAULT_BACKOFF_SECONDS: tuple[float, ...] = (1.0, 2.0, 4.0)
DEFAULT_LOOKBACK_DAYS = 10


@dataclass(frozen=True)
class HistoricalBar:
    timestamp: datetime
    open: float
    high: float
    low: float
    close: float
    volume: float


@dataclass(frozen=True)
class AlpacaWarmupResult:
    """Evidence-friendly (JSON-serializable via to_dict) summary of one
    symbol's Alpaca 1-minute warmup attempt. Deliberately excludes the raw
    HistoricalBar list -- callers receive that separately alongside this
    result (see run_alpaca_1m_warmup's return value) so this stays cheap to
    persist as an artifact for all 35 symbols."""
    symbol: str
    status: str
    provider: str
    feed: str
    requested_start: str
    requested_end: str
    bar_count: int
    pages_fetched: int
    retries: int
    duplicate_bars_dropped: int
    future_bars_dropped: int
    invalid_rows_dropped: int
    reason: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _iso_z(dt: datetime) -> str:
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _request_page(
    transport: Any, data_endpoint: str, key_id: str, secret_key: str, symbol: str,
    start_iso: str, end_iso: str, feed: str, limit: int, page_token: str | None = None,
) -> Any:
    headers = {"APCA-API-KEY-ID": key_id, "APCA-API-SECRET-KEY": secret_key}
    params: dict[str, Any] = {
        "timeframe": "1Min", "limit": limit, "feed": feed, "start": start_iso, "end": end_iso,
    }
    if page_token:
        params["page_token"] = page_token
    return transport.get(
        f"{data_endpoint}/v2/stocks/{symbol}/bars", headers=headers, params=params, timeout=15,
    )


def _parse_bars_page(body: Any) -> list[HistoricalBar] | None:
    """None means structurally invalid (not a dict, or `bars` present but not
    a list) -- distinct from a legitimately empty/absent `bars` list, which
    returns []. A row missing required fields is silently dropped (same
    fail-closed-per-row posture as talonx_quant.buffer.RollingBarBuffer.add_bar
    dropping a bar with no close), never fabricated."""
    if not isinstance(body, dict):
        return None
    rows = body.get("bars")
    if rows is None:
        return []
    if not isinstance(rows, list):
        return None
    bars: list[HistoricalBar] = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        raw_ts = row.get("t")
        if not raw_ts:
            continue
        try:
            bars.append(HistoricalBar(
                timestamp=datetime.fromisoformat(str(raw_ts).replace("Z", "+00:00")),
                open=float(row["o"]), high=float(row["h"]), low=float(row["l"]),
                close=float(row["c"]), volume=float(row["v"]),
            ))
        except (KeyError, TypeError, ValueError):
            continue
    return bars


def fetch_1m_bars(
    transport: Any, data_endpoint: str, key_id: str, secret_key: str,
    symbol: str, start_iso: str, end_iso: str, feed: str = "iex", limit: int = 1000,
) -> list[HistoricalBar]:
    """Original Task 69Q single-page prototype fetch -- unchanged external
    behavior. Fails closed ([]) on any non-200 response."""
    response = _request_page(transport, data_endpoint, key_id, secret_key, symbol, start_iso, end_iso, feed, limit)
    if response.status_code != 200:
        return []
    parsed = _parse_bars_page(response.json() or {})
    return parsed or []


def _sanitize(raw_bars: list[HistoricalBar], causal_cutoff: datetime) -> tuple[list[HistoricalBar], int, int]:
    """Sorts, de-duplicates (last-seen-wins per timestamp, matching
    RollingBarBuffer.add_bar's own upsert convention), and drops any bar at
    or after `causal_cutoff` -- the hard no-look-ahead boundary. Returns
    (sanitized_bars, duplicate_count, future_dropped_count)."""
    if causal_cutoff.tzinfo is None:
        causal_cutoff = causal_cutoff.replace(tzinfo=timezone.utc)
    future_dropped = 0
    duplicate_dropped = 0
    kept: dict[datetime, HistoricalBar] = {}
    for bar in raw_bars:
        ts = bar.timestamp if bar.timestamp.tzinfo is not None else bar.timestamp.replace(tzinfo=timezone.utc)
        if ts >= causal_cutoff:
            future_dropped += 1
            continue
        if ts in kept:
            duplicate_dropped += 1
        kept[ts] = bar
    sanitized = [kept[ts] for ts in sorted(kept)]
    return sanitized, duplicate_dropped, future_dropped


def _get_with_retry(
    transport: Any, data_endpoint: str, key_id: str, secret_key: str, symbol: str,
    start_iso: str, end_iso: str, feed: str, limit: int, page_token: str | None,
    max_retries: int, backoff_seconds: tuple[float, ...], sleep_fn: Callable[[float], None],
) -> tuple[Any | None, str | None, int]:
    """Returns (response_or_None, failure_status_or_None, attempts_used).
    Retries (bounded, with backoff) on a timeout-shaped exception, HTTP 429,
    or a 5xx PROVIDER error -- any other 4xx fails immediately, no retry
    (an auth/permission/not-found error will not resolve by waiting)."""
    attempts = 0
    while True:
        try:
            response = _request_page(transport, data_endpoint, key_id, secret_key, symbol, start_iso, end_iso, feed, limit, page_token)
        except Exception as exc:  # noqa: BLE001 -- classified below, never raised further
            kind = STATUS_TIMEOUT if "timeout" in type(exc).__name__.lower() else STATUS_PROVIDER_ERROR
            if attempts >= max_retries:
                return None, kind, attempts
            sleep_fn(backoff_seconds[min(attempts, len(backoff_seconds) - 1)])
            attempts += 1
            continue

        if response.status_code == 200:
            return response, None, attempts
        if response.status_code == 429:
            if attempts >= max_retries:
                return None, STATUS_RATE_LIMITED, attempts
            sleep_fn(backoff_seconds[min(attempts, len(backoff_seconds) - 1)])
            attempts += 1
            continue
        if 500 <= response.status_code < 600:
            if attempts >= max_retries:
                return None, STATUS_PROVIDER_ERROR, attempts
            sleep_fn(backoff_seconds[min(attempts, len(backoff_seconds) - 1)])
            attempts += 1
            continue
        return None, STATUS_PROVIDER_ERROR, attempts


def run_alpaca_1m_warmup(
    transport: Any, data_endpoint: str, key_id: str, secret_key: str, symbol: str, *,
    causal_cutoff: datetime, required_bars: int, feed: str = "iex",
    lookback_days: int = DEFAULT_LOOKBACK_DAYS, limit: int = 1000, max_pages: int = MAX_PAGES,
    max_retries: int = DEFAULT_MAX_RETRIES, backoff_seconds: tuple[float, ...] = DEFAULT_BACKOFF_SECONDS,
    sleep_fn: Callable[[float], None] = _time.sleep,
) -> tuple[AlpacaWarmupResult, list[HistoricalBar]]:
    """Causal, paginated, bounded-retry Alpaca 1-minute historical warmup for
    ONE symbol. Never raises -- every failure mode (missing credentials,
    transport exception, non-200, malformed body, insufficient history)
    resolves to a deterministic AlpacaWarmupResult.status plus an empty or
    partial bar list, never a fabricated one.

    causal_cutoff is the single hard no-look-ahead boundary: `end` is set to
    exactly this instant, and every returned bar is additionally re-verified
    (`_sanitize`) to be strictly before it -- defense in depth against the
    provider itself ever echoing back a bar at/after the requested `end`.
    """
    if causal_cutoff.tzinfo is None:
        causal_cutoff = causal_cutoff.replace(tzinfo=timezone.utc)
    requested_start = causal_cutoff - timedelta(days=lookback_days)
    start_iso, end_iso = _iso_z(requested_start), _iso_z(causal_cutoff)

    if not key_id or not secret_key:
        return AlpacaWarmupResult(
            symbol=symbol, status=STATUS_PROVIDER_ERROR, provider=ALPACA_HISTORICAL_PROVIDER, feed=feed,
            requested_start=start_iso, requested_end=end_iso, bar_count=0, pages_fetched=0, retries=0,
            duplicate_bars_dropped=0, future_bars_dropped=0, invalid_rows_dropped=0,
            reason="ALPACA_CREDENTIALS_MISSING",
        ), []

    raw_bars: list[HistoricalBar] = []
    pages_fetched = 0
    retries_used = 0
    page_token: str | None = None
    saw_any_raw_row = False

    while True:
        response, failure, attempts = _get_with_retry(
            transport, data_endpoint, key_id, secret_key, symbol, start_iso, end_iso, feed, limit,
            page_token, max_retries, backoff_seconds, sleep_fn,
        )
        retries_used += attempts

        if failure is not None:
            sanitized_so_far, dup, fut = _sanitize(raw_bars, causal_cutoff)
            if len(sanitized_so_far) >= required_bars:
                break  # already have enough -- ignore the failed extra page
            return AlpacaWarmupResult(
                symbol=symbol, status=failure, provider=ALPACA_HISTORICAL_PROVIDER, feed=feed,
                requested_start=start_iso, requested_end=end_iso, bar_count=len(sanitized_so_far),
                pages_fetched=pages_fetched, retries=retries_used, duplicate_bars_dropped=dup,
                future_bars_dropped=fut, invalid_rows_dropped=0,
                reason=f"{failure}_AFTER_{attempts}_RETRIES_pages_fetched={pages_fetched}",
            ), sanitized_so_far

        body = response.json() if response is not None else None
        parsed = _parse_bars_page(body)
        if parsed is None:
            if pages_fetched == 0:
                return AlpacaWarmupResult(
                    symbol=symbol, status=STATUS_INVALID_DATA, provider=ALPACA_HISTORICAL_PROVIDER, feed=feed,
                    requested_start=start_iso, requested_end=end_iso, bar_count=0, pages_fetched=0,
                    retries=retries_used, duplicate_bars_dropped=0, future_bars_dropped=0, invalid_rows_dropped=0,
                    reason="MALFORMED_RESPONSE_BODY",
                ), []
            break  # keep whatever earlier valid pages already gathered

        pages_fetched += 1
        if parsed:
            saw_any_raw_row = True
        raw_bars.extend(parsed)

        sanitized_preview, _, _ = _sanitize(raw_bars, causal_cutoff)
        next_token = body.get("next_page_token") if isinstance(body, dict) else None
        if not next_token or len(sanitized_preview) >= required_bars or pages_fetched >= max_pages:
            break
        page_token = next_token

    sanitized, dup_dropped, future_dropped = _sanitize(raw_bars, causal_cutoff)
    bar_count = len(sanitized)

    if not saw_any_raw_row and bar_count == 0:
        status, reason = STATUS_EMPTY, "NO_BARS_RETURNED_FOR_REQUESTED_RANGE"
    elif bar_count >= required_bars:
        status, reason = STATUS_READY, f"{bar_count}/{required_bars}_bars"
    else:
        status, reason = STATUS_INSUFFICIENT_HISTORY, f"{bar_count}/{required_bars}_bars"

    return AlpacaWarmupResult(
        symbol=symbol, status=status, provider=ALPACA_HISTORICAL_PROVIDER, feed=feed,
        requested_start=start_iso, requested_end=end_iso, bar_count=bar_count, pages_fetched=pages_fetched,
        retries=retries_used, duplicate_bars_dropped=dup_dropped, future_bars_dropped=future_dropped,
        invalid_rows_dropped=0, reason=reason,
    ), sanitized
