"""
tests/test_brain_cache.py
------------------------------
Tests talonx_brain.cache.BrainCache directly: fresh/stale/miss reads,
the write envelope (embedded expires_at, not relying on Redis's own TTL
for freshness -- see cache.py's module docstring for why), lock acquire/
wait/timeout, invalidate, and the market-boundary next_expiry() math
(the trickiest non-obvious piece -- covered across before-open,
mid-session, after-close, and a DST-crossing pair of dates).

The Redis client is mocked (AsyncMock) -- this is about BrainCache's own
logic, not real Redis I/O, same boundary every other consumer's tests in
this project use for their Redis client.
"""
from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock

import pytest

from talonx_brain.cache import BrainCache
from talonx_brain.config import BrainConfig
from talonx_brain.schemas import QuantSignal, ResearchReport, ResearchVerdict, SignalDirection, SignalType

NOW = datetime(2026, 8, 10, 15, 0, 0, tzinfo=timezone.utc)  # 11am ET, mid-session


def _signal() -> QuantSignal:
    return QuantSignal(
        ticker="NVDA",
        signal_type=SignalType.RSI_OVERSOLD_VOLUME_SURGE,
        direction=SignalDirection.BULLISH,
        message="RSI oversold with volume surge",
        price=131.5,
        bar_timestamp=NOW,
    )


def _report() -> ResearchReport:
    return ResearchReport(
        ticker="NVDA",
        triggering_signal=_signal(),
        verdict=ResearchVerdict.BULLISH,
        confidence=0.8,
        summary="Fundamentals support the surge.",
        model_used="gemini-flash-latest",
    )


@pytest.fixture
def client():
    return AsyncMock()


@pytest.fixture
def cache(client) -> BrainCache:
    return BrainCache(client, BrainConfig())


def _envelope(report: ResearchReport, expires_at: datetime) -> str:
    return json.dumps({"report": json.loads(report.model_dump_json()), "expires_at": expires_at.isoformat()})


# --- get() -----------------------------------------------------------------

@pytest.mark.asyncio
async def test_get_returns_none_on_a_miss(cache, client):
    client.get.return_value = None

    assert await cache.get("NVDA") is None


@pytest.mark.asyncio
async def test_get_returns_fresh_true_when_not_yet_expired(cache, client):
    # get()'s freshness check compares against the REAL current time
    # (datetime.now(timezone.utc), not an injectable clock), so the
    # envelope's expires_at must be relative to it too -- NOW above is a
    # fixed fixture timestamp for report/signal content, unrelated to this.
    client.get.return_value = _envelope(_report(), datetime.now(timezone.utc) + timedelta(hours=1))

    result = await cache.get("NVDA")

    assert result is not None
    report, is_fresh = result
    assert is_fresh is True
    assert report.ticker == "NVDA"


@pytest.mark.asyncio
async def test_get_returns_fresh_false_when_past_expiry(cache, client):
    client.get.return_value = _envelope(_report(), NOW - timedelta(hours=1))

    report, is_fresh = await cache.get("NVDA")

    assert is_fresh is False
    assert report.ticker == "NVDA"


@pytest.mark.asyncio
async def test_get_drops_unparseable_entries(cache, client):
    client.get.return_value = "not json"

    assert await cache.get("NVDA") is None


@pytest.mark.asyncio
async def test_get_treats_redis_error_as_a_miss(cache, client):
    client.get.side_effect = ConnectionError("redis down")

    assert await cache.get("NVDA") is None


# --- set() / invalidate() ----------------------------------------------------

@pytest.mark.asyncio
async def test_set_writes_under_the_safety_ttl_with_an_embedded_expiry(cache, client):
    await cache.set("nvda", _report())

    client.set.assert_awaited_once()
    args, kwargs = client.set.await_args
    assert args[0] == "brain_cache:NVDA"
    assert kwargs["ex"] == int(BrainConfig().cache_safety_ttl_seconds)
    envelope = json.loads(args[1])
    assert "expires_at" in envelope
    assert envelope["report"]["ticker"] == "NVDA"


@pytest.mark.asyncio
async def test_invalidate_deletes_the_cache_key(cache, client):
    await cache.invalidate("nvda")

    client.delete.assert_awaited_once_with("brain_cache:NVDA")


# --- Lock ---------------------------------------------------------------

@pytest.mark.asyncio
async def test_acquire_lock_uses_set_nx_ex(cache, client):
    client.set.return_value = True

    acquired = await cache.acquire_lock("nvda")

    assert acquired is True
    args, kwargs = client.set.await_args
    assert args[0] == "lock:brain:NVDA"
    assert kwargs["nx"] is True
    assert kwargs["ex"] == int(BrainConfig().cache_lock_ttl_seconds)


@pytest.mark.asyncio
async def test_acquire_lock_returns_false_when_already_held(cache, client):
    client.set.return_value = None  # NX conflict -- redis-py returns None on failure

    assert await cache.acquire_lock("nvda") is False


@pytest.mark.asyncio
async def test_release_lock_deletes_the_lock_key(cache, client):
    await cache.release_lock("nvda")

    client.delete.assert_awaited_once_with("lock:brain:NVDA")


@pytest.mark.asyncio
async def test_wait_for_cache_returns_as_soon_as_an_entry_appears(cache, client, monkeypatch):
    client.get.side_effect = [None, _envelope(_report(), datetime.now(timezone.utc) + timedelta(hours=1))]
    monkeypatch.setattr("asyncio.sleep", AsyncMock())

    result = await cache.wait_for_cache("nvda")

    assert result is not None
    assert result[1] is True


@pytest.mark.asyncio
async def test_wait_for_cache_times_out_and_returns_none(cache, client, monkeypatch):
    client.get.return_value = None
    cache.config = BrainConfig(cache_lock_wait_seconds=0.01)
    monkeypatch.setattr("asyncio.sleep", AsyncMock())

    result = await cache.wait_for_cache("nvda")

    assert result is None


# --- next_expiry() / market boundary math --------------------------------

def test_next_expiry_before_market_open_lands_on_todays_open():
    cache = BrainCache(AsyncMock(), BrainConfig(cache_base_ttl_seconds=999999))
    # 6am ET on a Monday (winter -- EST, UTC-5): 11:00 UTC.
    now = datetime(2026, 1, 12, 11, 0, 0, tzinfo=timezone.utc)

    expiry = cache.next_expiry(now)

    expected = datetime(2026, 1, 12, 14, 0, 0, tzinfo=timezone.utc)  # 9am EST = 14:00 UTC
    assert expiry == expected


def test_next_expiry_mid_session_lands_on_todays_close():
    cache = BrainCache(AsyncMock(), BrainConfig(cache_base_ttl_seconds=999999))
    # 11am ET on a Monday (winter -- EST): 16:00 UTC.
    now = datetime(2026, 1, 12, 16, 0, 0, tzinfo=timezone.utc)

    expiry = cache.next_expiry(now)

    expected = datetime(2026, 1, 12, 21, 0, 0, tzinfo=timezone.utc)  # 4pm EST = 21:00 UTC
    assert expiry == expected


def test_next_expiry_after_close_lands_on_tomorrows_open():
    cache = BrainCache(AsyncMock(), BrainConfig(cache_base_ttl_seconds=999999))
    # 6pm ET on a Monday (winter -- EST): 23:00 UTC.
    now = datetime(2026, 1, 12, 23, 0, 0, tzinfo=timezone.utc)

    expiry = cache.next_expiry(now)

    expected = datetime(2026, 1, 13, 14, 0, 0, tzinfo=timezone.utc)  # next day 9am EST = 14:00 UTC
    assert expiry == expected


def test_next_expiry_handles_daylight_saving_time_offset():
    cache = BrainCache(AsyncMock(), BrainConfig(cache_base_ttl_seconds=999999))
    # 6am ET on a summer Monday (EDT, UTC-4): 10:00 UTC.
    now = datetime(2026, 7, 13, 10, 0, 0, tzinfo=timezone.utc)

    expiry = cache.next_expiry(now)

    expected = datetime(2026, 7, 13, 13, 0, 0, tzinfo=timezone.utc)  # 9am EDT = 13:00 UTC
    assert expiry == expected


def test_next_expiry_is_the_sooner_of_base_ttl_or_market_boundary():
    # A short base TTL (10 minutes) mid-session should win over the
    # much-later market close boundary.
    cache = BrainCache(AsyncMock(), BrainConfig(cache_base_ttl_seconds=600.0))
    now = datetime(2026, 1, 12, 16, 0, 0, tzinfo=timezone.utc)  # 11am EST

    expiry = cache.next_expiry(now)

    assert expiry == now + timedelta(seconds=600)
