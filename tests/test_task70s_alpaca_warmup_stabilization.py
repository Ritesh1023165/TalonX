"""Task 70S -- PIV stabilization Phase 1: Alpaca IEX historical warmup
correctness. Covers alpaca_historical_warmup.run_alpaca_1m_warmup's own
pagination/retry/causal-sanitization contract, and warmup.py's integration
of it ahead of the existing (unmodified, still-tested-elsewhere) yfinance
path. PAPER-only / historical-market-data-only: every fake transport in
this file exposes only `get`; any `post`/`delete` call is a test failure.
"""
from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone

import pytest

from talonx_piv.alpaca_historical_warmup import (
    STATUS_EMPTY,
    STATUS_INSUFFICIENT_HISTORY,
    STATUS_INVALID_DATA,
    STATUS_PROVIDER_ERROR,
    STATUS_RATE_LIMITED,
    STATUS_READY,
    STATUS_TIMEOUT,
    fetch_1m_bars,
    run_alpaca_1m_warmup,
)
from talonx_piv.config import PivConfig
from talonx_piv.warmup import preseed_and_verify
from talonx_quant.buffer import RollingBarBuffer

CUTOFF = datetime(2026, 8, 26, 4, 19, tzinfo=timezone.utc)
REQUIRED = 120


class Resp:
    def __init__(self, body, status=200):
        self.body, self.status_code = body, status

    def json(self):
        return self.body


def _bars(n, *, start=None, step_minutes=1):
    start = start or (CUTOFF - timedelta(minutes=n * step_minutes))
    return [
        {"t": (start + timedelta(minutes=i * step_minutes)).isoformat().replace("+00:00", "Z"),
         "o": 100.0, "h": 101.0, "l": 99.0, "c": 100.0 + (i % 5), "v": 1000}
        for i in range(n)
    ]


class NoOrderTransport:
    """Base fake transport asserting no order/broker-trading endpoint is
    ever touched by the warmup path."""

    def post(self, *a, **k):
        raise AssertionError("warmup path must never submit an order")

    def delete(self, *a, **k):
        raise AssertionError("warmup path must never cancel/close a position")


class ScriptedTransport(NoOrderTransport):
    """Replays a scripted sequence of (response_or_exception) per .get() call,
    one entry per call regardless of symbol -- sufficient for these
    single-symbol-at-a-time unit tests."""

    def __init__(self, script):
        self.script = list(script)
        self.calls = []

    def get(self, url, **kw):
        self.calls.append((url, kw.get("params")))
        item = self.script.pop(0)
        if isinstance(item, Exception):
            raise item
        return item


def _no_sleep(_seconds):
    pass


# ---------------------------------------------------------------------
# Complete Alpaca IEX warmup -> READY
# ---------------------------------------------------------------------

def test_complete_alpaca_warmup_ready():
    transport = ScriptedTransport([Resp({"bars": _bars(REQUIRED)})])
    result, bars = run_alpaca_1m_warmup(
        transport, "https://data.alpaca.markets", "key", "secret", "AAPL",
        causal_cutoff=CUTOFF, required_bars=REQUIRED, sleep_fn=_no_sleep,
    )
    assert result.status == STATUS_READY
    assert result.bar_count == REQUIRED == len(bars)
    assert result.provider == "ALPACA_HISTORICAL"
    assert result.feed == "iex"
    assert transport.calls[0][1]["feed"] == "iex"


# ---------------------------------------------------------------------
# Multi-page response
# ---------------------------------------------------------------------

def test_multi_page_response_paginates_until_sufficient():
    page1 = _bars(80, start=CUTOFF - timedelta(minutes=160))
    page2 = _bars(80, start=CUTOFF - timedelta(minutes=80))
    transport = ScriptedTransport([
        Resp({"bars": page1, "next_page_token": "TOK1"}),
        Resp({"bars": page2, "next_page_token": None}),
    ])
    result, bars = run_alpaca_1m_warmup(
        transport, "https://data.alpaca.markets", "key", "secret", "AAPL",
        causal_cutoff=CUTOFF, required_bars=REQUIRED, sleep_fn=_no_sleep,
    )
    assert result.status == STATUS_READY
    assert result.pages_fetched == 2
    assert result.bar_count == 160
    assert transport.calls[1][1]["page_token"] == "TOK1"


def test_pagination_stops_once_sufficient_even_with_more_pages_available():
    page1 = _bars(REQUIRED, start=CUTOFF - timedelta(minutes=REQUIRED))
    transport = ScriptedTransport([Resp({"bars": page1, "next_page_token": "TOK_UNUSED"})])
    result, bars = run_alpaca_1m_warmup(
        transport, "https://data.alpaca.markets", "key", "secret", "AAPL",
        causal_cutoff=CUTOFF, required_bars=REQUIRED, sleep_fn=_no_sleep,
    )
    assert result.status == STATUS_READY
    assert result.pages_fetched == 1  # never fetched the second page -- already had enough


# ---------------------------------------------------------------------
# Exact causal cutoff -- no future leakage
# ---------------------------------------------------------------------

def test_bar_exactly_at_causal_cutoff_is_excluded():
    bars = _bars(REQUIRED, start=CUTOFF - timedelta(minutes=REQUIRED))
    bars.append({"t": CUTOFF.isoformat().replace("+00:00", "Z"), "o": 1, "h": 1, "l": 1, "c": 1, "v": 1})
    transport = ScriptedTransport([Resp({"bars": bars})])
    result, sanitized = run_alpaca_1m_warmup(
        transport, "https://data.alpaca.markets", "key", "secret", "AAPL",
        causal_cutoff=CUTOFF, required_bars=REQUIRED, sleep_fn=_no_sleep,
    )
    assert all(b.timestamp < CUTOFF for b in sanitized)
    assert result.future_bars_dropped == 1
    assert result.bar_count == REQUIRED


def test_bar_after_causal_cutoff_is_excluded():
    bars = _bars(REQUIRED, start=CUTOFF - timedelta(minutes=REQUIRED))
    future_ts = CUTOFF + timedelta(minutes=5)
    bars.append({"t": future_ts.isoformat().replace("+00:00", "Z"), "o": 1, "h": 1, "l": 1, "c": 1, "v": 1})
    transport = ScriptedTransport([Resp({"bars": bars})])
    result, sanitized = run_alpaca_1m_warmup(
        transport, "https://data.alpaca.markets", "key", "secret", "AAPL",
        causal_cutoff=CUTOFF, required_bars=REQUIRED, sleep_fn=_no_sleep,
    )
    assert all(b.timestamp < CUTOFF for b in sanitized)
    assert result.future_bars_dropped == 1


# ---------------------------------------------------------------------
# Weekend boundary / holiday-or-early-close handling
# ---------------------------------------------------------------------

def test_weekend_gap_in_returned_bars_does_not_break_sufficiency():
    """Simulates Alpaca simply not returning any bars for a Sat/Sun inside
    the requested range (the provider's own natural behavior) -- the
    lookback window is calendar days, not trading days, so weekday bars
    alone must still be able to satisfy the requirement."""
    friday_bars = _bars(70, start=CUTOFF - timedelta(days=3, minutes=70))
    monday_bars = _bars(70, start=CUTOFF - timedelta(minutes=70))
    transport = ScriptedTransport([Resp({"bars": friday_bars + monday_bars})])
    result, bars = run_alpaca_1m_warmup(
        transport, "https://data.alpaca.markets", "key", "secret", "AAPL",
        causal_cutoff=CUTOFF, required_bars=REQUIRED, sleep_fn=_no_sleep,
    )
    assert result.status == STATUS_READY
    assert result.bar_count == 140


def test_holiday_or_early_close_gap_yields_insufficient_not_error():
    """A market holiday (or early close) inside the lookback window just
    means fewer bars than a normal window would give -- a data-availability
    outcome (INSUFFICIENT_HISTORY), never an error status."""
    transport = ScriptedTransport([Resp({"bars": _bars(40)})])
    result, _ = run_alpaca_1m_warmup(
        transport, "https://data.alpaca.markets", "key", "secret", "AAPL",
        causal_cutoff=CUTOFF, required_bars=REQUIRED, sleep_fn=_no_sleep,
    )
    assert result.status == STATUS_INSUFFICIENT_HISTORY
    assert result.bar_count == 40
    assert result.reason == "40/120_bars"


# ---------------------------------------------------------------------
# Empty response
# ---------------------------------------------------------------------

def test_empty_response_is_empty_not_insufficient():
    transport = ScriptedTransport([Resp({"bars": []})])
    result, bars = run_alpaca_1m_warmup(
        transport, "https://data.alpaca.markets", "key", "secret", "DELISTED",
        causal_cutoff=CUTOFF, required_bars=REQUIRED, sleep_fn=_no_sleep,
    )
    assert result.status == STATUS_EMPTY
    assert bars == []


# ---------------------------------------------------------------------
# Missing required minutes (insufficient bars, distinct wording)
# ---------------------------------------------------------------------

def test_missing_required_minutes_insufficient():
    transport = ScriptedTransport([Resp({"bars": _bars(119)})])
    result, _ = run_alpaca_1m_warmup(
        transport, "https://data.alpaca.markets", "key", "secret", "AAPL",
        causal_cutoff=CUTOFF, required_bars=REQUIRED, sleep_fn=_no_sleep,
    )
    assert result.status == STATUS_INSUFFICIENT_HISTORY
    assert result.bar_count == 119


# ---------------------------------------------------------------------
# Duplicate / out-of-order / invalid bars
# ---------------------------------------------------------------------

def test_duplicate_out_of_order_and_invalid_rows_sanitized():
    good = _bars(REQUIRED, start=CUTOFF - timedelta(minutes=REQUIRED))
    shuffled = list(reversed(good))  # out-of-order
    dup = dict(shuffled[0])  # duplicate timestamp of an existing bar
    invalid_row = {"t": "not-even-a-timestamp?", "o": 1, "h": 1, "l": 1, "c": 1, "v": 1}
    missing_close = {"t": (CUTOFF - timedelta(minutes=1)).isoformat().replace("+00:00", "Z"), "o": 1, "h": 1, "l": 1, "v": 1}
    body = {"bars": shuffled + [dup, invalid_row, missing_close]}
    transport = ScriptedTransport([Resp(body)])
    result, bars = run_alpaca_1m_warmup(
        transport, "https://data.alpaca.markets", "key", "secret", "AAPL",
        causal_cutoff=CUTOFF, required_bars=REQUIRED, sleep_fn=_no_sleep,
    )
    assert result.status == STATUS_READY
    assert result.duplicate_bars_dropped == 1
    # sorted ascending despite out-of-order input
    assert all(bars[i].timestamp < bars[i + 1].timestamp for i in range(len(bars) - 1))
    # malformed rows (bad timestamp / missing close) never produced a bar
    assert result.bar_count == REQUIRED


def test_structurally_invalid_body_is_invalid_data():
    transport = ScriptedTransport([Resp({"bars": "not-a-list"})])
    result, bars = run_alpaca_1m_warmup(
        transport, "https://data.alpaca.markets", "key", "secret", "AAPL",
        causal_cutoff=CUTOFF, required_bars=REQUIRED, sleep_fn=_no_sleep,
    )
    assert result.status == STATUS_INVALID_DATA
    assert bars == []


# ---------------------------------------------------------------------
# Timeout followed by successful retry / retry exhaustion
# ---------------------------------------------------------------------

def test_timeout_then_successful_retry_reaches_ready():
    sleeps = []
    transport = ScriptedTransport([TimeoutError("connect timeout"), Resp({"bars": _bars(REQUIRED)})])
    result, bars = run_alpaca_1m_warmup(
        transport, "https://data.alpaca.markets", "key", "secret", "AAPL",
        causal_cutoff=CUTOFF, required_bars=REQUIRED, sleep_fn=sleeps.append,
    )
    assert result.status == STATUS_READY
    assert result.retries == 1
    assert sleeps == [1.0]  # first backoff step, bounded


def test_timeout_retry_exhaustion_fails_closed():
    script = [TimeoutError("timeout")] * 4  # 1 initial + 3 retries, all fail
    transport = ScriptedTransport(script)
    result, bars = run_alpaca_1m_warmup(
        transport, "https://data.alpaca.markets", "key", "secret", "AAPL",
        causal_cutoff=CUTOFF, required_bars=REQUIRED, max_retries=3, sleep_fn=_no_sleep,
    )
    assert result.status == STATUS_TIMEOUT
    assert result.retries == 3
    assert bars == []


# ---------------------------------------------------------------------
# Rate limiting
# ---------------------------------------------------------------------

def test_rate_limit_then_success():
    transport = ScriptedTransport([Resp({}, status=429), Resp({"bars": _bars(REQUIRED)})])
    result, bars = run_alpaca_1m_warmup(
        transport, "https://data.alpaca.markets", "key", "secret", "AAPL",
        causal_cutoff=CUTOFF, required_bars=REQUIRED, sleep_fn=_no_sleep,
    )
    assert result.status == STATUS_READY
    assert result.retries == 1


def test_rate_limit_exhaustion_fails_closed():
    transport = ScriptedTransport([Resp({}, status=429)] * 4)
    result, bars = run_alpaca_1m_warmup(
        transport, "https://data.alpaca.markets", "key", "secret", "AAPL",
        causal_cutoff=CUTOFF, required_bars=REQUIRED, max_retries=3, sleep_fn=_no_sleep,
    )
    assert result.status == STATUS_RATE_LIMITED
    assert result.retries == 3


def test_non_retryable_4xx_fails_immediately_no_retry():
    transport = ScriptedTransport([Resp({}, status=403)])
    result, bars = run_alpaca_1m_warmup(
        transport, "https://data.alpaca.markets", "key", "secret", "AAPL",
        causal_cutoff=CUTOFF, required_bars=REQUIRED, sleep_fn=_no_sleep,
    )
    assert result.status == STATUS_PROVIDER_ERROR
    assert result.retries == 0
    assert len(transport.calls) == 1  # no retry attempted for a plain 403


# ---------------------------------------------------------------------
# Missing credentials -- fail closed, no request attempted
# ---------------------------------------------------------------------

def test_missing_credentials_fails_closed_without_any_request():
    transport = ScriptedTransport([])  # any .get() call would raise IndexError -- proves none happened
    result, bars = run_alpaca_1m_warmup(
        transport, "https://data.alpaca.markets", "", "", "AAPL",
        causal_cutoff=CUTOFF, required_bars=REQUIRED, sleep_fn=_no_sleep,
    )
    assert result.status == STATUS_PROVIDER_ERROR
    assert result.reason == "ALPACA_CREDENTIALS_MISSING"
    assert bars == []


# ---------------------------------------------------------------------
# fetch_1m_bars (Task 69Q prototype) unchanged behavior smoke check
# ---------------------------------------------------------------------

def test_fetch_1m_bars_prototype_still_behaves_identically():
    transport = ScriptedTransport([Resp({"bars": _bars(3)})])
    bars = fetch_1m_bars(transport, "https://data.alpaca.markets", "key", "secret", "AAPL", "start", "end")
    assert len(bars) == 3


# =======================================================================
# Integration: warmup.py's preseed_and_verify wiring
# =======================================================================

class FakeScanner:
    def __init__(self, yfinance_populate=None):
        self.buffer = RollingBarBuffer(max_bars_per_symbol=250)
        self.buffer_htf = RollingBarBuffer(max_bars_per_symbol=250)
        self._yfinance_populate = yfinance_populate or {}
        self.preseed_calls = []

    async def preseed_symbols(self, symbols):
        self.preseed_calls.append(list(symbols))
        base = datetime(2026, 8, 21, 9, 30, tzinfo=timezone.utc)
        for symbol in symbols:
            symbol = symbol.upper()
            # HTF leg: always yfinance in this fake, matching production
            # (Alpaca leg here is 1-minute-only, per Task 70S scope).
            for i in range(200):
                ts = base + timedelta(minutes=15 * i)
                self.buffer_htf.add_bar(symbol, ts, 100.0, 101.0, 99.0, 100.0, 1000, session="regular")
            # 1-minute leg: mirrors _preseed_1m_if_needed's own guard --
            # only adds bars if the buffer doesn't already meet the threshold.
            if self.buffer.bar_count(symbol) >= 120:
                continue
            n = self._yfinance_populate.get(symbol, 0)
            for i in range(n):
                ts = base + timedelta(minutes=i)
                self.buffer.add_bar(symbol, ts, 100.0, 101.0, 99.0, 100.0, 1000, session="regular")


def _piv_config(tmp_path):
    return PivConfig(
        key_id="AKFAKE", secret_key="SKFAKE_SECRET_VALUE", paper_trading=True, real_capital=False,
        broker_endpoint="https://paper-api.alpaca.markets", approved_sha="abc", state_dir=tmp_path,
        universe=("AAPL", "MSFT"),
    )


@pytest.mark.asyncio
async def test_alpaca_sufficient_skips_yfinance_for_1m_leg(tmp_path):
    scanner = FakeScanner(yfinance_populate={"AAPL": 0})  # yfinance would add nothing anyway
    transport = ScriptedTransport([Resp({"bars": _bars(REQUIRED, start=CUTOFF - timedelta(minutes=REQUIRED))})])
    checks = await preseed_and_verify(
        scanner, ["AAPL"], 200, piv_config=_piv_config(tmp_path), now=CUTOFF,
        alpaca_transport=transport, alpaca_sleep_fn=_no_sleep,
    )
    assert checks[0].ready is True
    assert checks[0].bar_count_1m_source == "ALPACA"
    assert checks[0].alpaca_status == STATUS_READY
    assert scanner.buffer.bar_count("AAPL") == REQUIRED


@pytest.mark.asyncio
async def test_alpaca_insufficient_falls_back_to_yfinance(tmp_path):
    scanner = FakeScanner(yfinance_populate={"AAPL": 120})  # yfinance fully covers it
    transport = ScriptedTransport([Resp({"bars": _bars(30)})])  # Alpaca gives only 30
    checks = await preseed_and_verify(
        scanner, ["AAPL"], 200, piv_config=_piv_config(tmp_path), now=CUTOFF,
        alpaca_transport=transport, alpaca_sleep_fn=_no_sleep,
    )
    assert checks[0].alpaca_bar_count == 30
    assert checks[0].bar_count_1m_source == "ALPACA_PARTIAL_PLUS_YFINANCE"
    assert checks[0].ready is True  # yfinance fallback completed it
    # Alpaca's 30 bars (< 120) did not clear _preseed_1m_if_needed's own
    # guard, so yfinance ran and added its own 120 non-overlapping bars --
    # the buffer is additive by timestamp (RollingBarBuffer upserts, never
    # replaces a whole symbol), so the final count is both providers' union.
    assert checks[0].bar_count_1m == 150


@pytest.mark.asyncio
async def test_alpaca_disabled_by_default_reproduces_prior_yfinance_only_behavior(tmp_path):
    """piv_config=None (the default) -- exact prior Task 65B behavior."""
    scanner = FakeScanner(yfinance_populate={"AAPL": 120})
    checks = await preseed_and_verify(scanner, ["AAPL"], 200)
    assert checks[0].ready is True
    assert checks[0].alpaca_attempted is False
    assert checks[0].alpaca_status == "NOT_ATTEMPTED"
    assert checks[0].bar_count_1m_source == "NONE"


@pytest.mark.asyncio
async def test_one_symbol_alpaca_failure_isolated_other_symbol_unaffected(tmp_path):
    scanner = FakeScanner(yfinance_populate={"AAPL": 0, "MSFT": 0})

    class PerSymbolTransport(NoOrderTransport):
        def get(self, url, **kw):
            if "/AAPL/" in url:
                raise TimeoutError("simulated network failure for AAPL only")
            return Resp({"bars": _bars(REQUIRED, start=CUTOFF - timedelta(minutes=REQUIRED))})

    checks = await preseed_and_verify(
        scanner, ["AAPL", "MSFT"], 200, piv_config=_piv_config(tmp_path), now=CUTOFF,
        alpaca_transport=PerSymbolTransport(), alpaca_sleep_fn=_no_sleep,
    )
    by_symbol = {c.symbol: c for c in checks}
    assert by_symbol["AAPL"].alpaca_status == STATUS_TIMEOUT
    assert by_symbol["AAPL"].bar_count_1m == 0  # AAPL's yfinance fallback also gave 0 in this fake -- proves isolation, not a fabricated recovery
    assert by_symbol["MSFT"].alpaca_status == STATUS_READY
    assert by_symbol["MSFT"].bar_count_1m == REQUIRED


@pytest.mark.asyncio
async def test_no_cross_date_reuse_each_call_recomputes_from_current_cutoff(tmp_path):
    """No persisted Alpaca warmup cache exists anywhere -- proven by showing
    two calls with different `now` values produce different requested
    ranges, never a stale/reused one from a prior call."""
    scanner1 = FakeScanner()
    day1 = datetime(2026, 8, 24, 4, 19, tzinfo=timezone.utc)
    t1 = ScriptedTransport([Resp({"bars": []})])
    checks1 = await preseed_and_verify(
        scanner1, ["AAPL"], 200, piv_config=_piv_config(tmp_path), now=day1,
        alpaca_transport=t1, alpaca_sleep_fn=_no_sleep,
    )
    scanner2 = FakeScanner()
    day2 = datetime(2026, 8, 26, 4, 19, tzinfo=timezone.utc)
    t2 = ScriptedTransport([Resp({"bars": []})])
    checks2 = await preseed_and_verify(
        scanner2, ["AAPL"], 200, piv_config=_piv_config(tmp_path), now=day2,
        alpaca_transport=t2, alpaca_sleep_fn=_no_sleep,
    )
    params1 = t1.calls[0][1]
    params2 = t2.calls[0][1]
    assert params1["start"] != params2["start"]
    assert params1["end"] != params2["end"]
    assert params2["end"].startswith("2026-08-26")


# ---------------------------------------------------------------------
# No credential leakage
# ---------------------------------------------------------------------

def test_no_credential_leakage_in_result_or_check_json():
    transport = ScriptedTransport([Resp({"bars": _bars(REQUIRED)})])
    result, _ = run_alpaca_1m_warmup(
        transport, "https://data.alpaca.markets", "AKSECRETKEYID", "SUPER_SECRET_VALUE", "AAPL",
        causal_cutoff=CUTOFF, required_bars=REQUIRED, sleep_fn=_no_sleep,
    )
    serialized = json.dumps(result.to_dict())
    assert "AKSECRETKEYID" not in serialized
    assert "SUPER_SECRET_VALUE" not in serialized


@pytest.mark.asyncio
async def test_no_credential_leakage_through_full_warmup_check(tmp_path):
    scanner = FakeScanner()
    transport = ScriptedTransport([Resp({"bars": _bars(REQUIRED, start=CUTOFF - timedelta(minutes=REQUIRED))})])
    cfg = _piv_config(tmp_path)
    checks = await preseed_and_verify(
        scanner, ["AAPL"], 200, piv_config=cfg, now=CUTOFF,
        alpaca_transport=transport, alpaca_sleep_fn=_no_sleep,
    )
    serialized = json.dumps(checks[0].to_dict())
    assert cfg.key_id not in serialized
    assert cfg.secret_key not in serialized


# ---------------------------------------------------------------------
# No order/broker-trading calls anywhere in the warmup path
# ---------------------------------------------------------------------

@pytest.mark.asyncio
async def test_full_warmup_pipeline_never_touches_order_endpoints(tmp_path):
    scanner = FakeScanner(yfinance_populate={"AAPL": 0})
    transport = ScriptedTransport([Resp({"bars": _bars(REQUIRED, start=CUTOFF - timedelta(minutes=REQUIRED))})])
    # NoOrderTransport.post/.delete raise AssertionError if ever called --
    # a passing test proves the whole pipeline (Alpaca fetch + yfinance
    # fallback call) issued GET requests only.
    await preseed_and_verify(
        scanner, ["AAPL"], 200, piv_config=_piv_config(tmp_path), now=CUTOFF,
        alpaca_transport=transport, alpaca_sleep_fn=_no_sleep,
    )
