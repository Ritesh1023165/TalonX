"""
tests/test_reddit_client.py
--------------------------------
Tests talonx_ingest.news.reddit_client -- the pure parsing/mapping logic
(_parse_listing, _time_filter_for) plus RedditClient.is_configured and
the "not configured -> return [] with no network call" short-circuit.

Consistent with this project's existing coverage of its OTHER network
clients (EdgarClient, NewsClient, market_data's Polygon/yfinance clients
all have zero direct unit tests either -- they're only exercised via
mocks at the pipeline-integration level, e.g.
test_pipeline_ledger_integration.py): the full async OAuth + HTTP fetch
flow here isn't mocked and tested either, only the synchronous,
network-free logic that can be tested directly and cheaply.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from talonx_ingest.config import RedditConfig
from talonx_ingest.news.reddit_client import RedditClient, _parse_listing, _time_filter_for


def _listing(*posts: dict) -> dict:
    return {"data": {"children": [{"data": post} for post in posts]}}


def _post(
    title: str = "AAPL to the moon",
    permalink: str = "/r/wallstreetbets/comments/abc123/aapl_to_the_moon/",
    created_utc: float | None = None,
    selftext: str = "",
) -> dict:
    return {
        "title": title,
        "permalink": permalink,
        "created_utc": created_utc,
        "selftext": selftext,
    }


@pytest.mark.parametrize(
    "lookback_days,expected",
    [(1, "day"), (7, "week"), (31, "month"), (365, "year"), (1000, "all")],
)
def test_time_filter_for_maps_lookback_to_reddit_window(lookback_days, expected):
    assert _time_filter_for(lookback_days) == expected


def test_parse_listing_maps_basic_fields():
    now = datetime.now(timezone.utc)
    payload = _listing(_post(created_utc=now.timestamp(), selftext="DD inside."))
    cutoff = now - timedelta(days=7)

    articles = _parse_listing("AAPL", "wallstreetbets", payload, cutoff)

    assert len(articles) == 1
    a = articles[0]
    assert a.ticker == "AAPL"
    assert a.title == "AAPL to the moon"
    assert a.url == "https://www.reddit.com/r/wallstreetbets/comments/abc123/aapl_to_the_moon/"
    assert a.source == "reddit:r/wallstreetbets"
    assert a.summary == "DD inside."


def test_parse_listing_falls_back_to_title_for_link_posts():
    now = datetime.now(timezone.utc)
    payload = _listing(_post(created_utc=now.timestamp(), selftext=""))
    cutoff = now - timedelta(days=7)

    articles = _parse_listing("AAPL", "stocks", payload, cutoff)

    assert articles[0].summary == "AAPL to the moon"


def test_parse_listing_skips_posts_older_than_cutoff():
    old = datetime.now(timezone.utc) - timedelta(days=30)
    cutoff = datetime.now(timezone.utc) - timedelta(days=7)
    payload = _listing(_post(created_utc=old.timestamp()))

    assert _parse_listing("AAPL", "stocks", payload, cutoff) == []


def test_parse_listing_skips_malformed_entries():
    now = datetime.now(timezone.utc)
    cutoff = now - timedelta(days=7)
    payload = _listing(
        {"title": "no permalink"},  # missing permalink
        {"permalink": "/r/stocks/comments/xyz/"},  # missing title
    )

    assert _parse_listing("AAPL", "stocks", payload, cutoff) == []


def test_parse_listing_truncates_long_selftext():
    now = datetime.now(timezone.utc)
    cutoff = now - timedelta(days=7)
    payload = _listing(_post(created_utc=now.timestamp(), selftext="x" * 5000))

    articles = _parse_listing("AAPL", "stocks", payload, cutoff)

    assert len(articles[0].summary) == 1000


def test_parse_listing_handles_missing_created_utc():
    cutoff = datetime.now(timezone.utc) - timedelta(days=7)
    payload = _listing(_post(created_utc=None))

    articles = _parse_listing("AAPL", "stocks", payload, cutoff)

    assert len(articles) == 1  # no timestamp -- not filtered out, just unordered
    assert articles[0].published_at is None


def test_is_configured_false_without_credentials():
    client = RedditClient(config=RedditConfig(client_id=None, client_secret=None))
    assert client.is_configured is False


def test_is_configured_true_with_both_credentials():
    client = RedditClient(config=RedditConfig(client_id="id", client_secret="secret"))
    assert client.is_configured is True


def test_is_configured_false_with_only_one_credential():
    client = RedditClient(config=RedditConfig(client_id="id", client_secret=None))
    assert client.is_configured is False


@pytest.mark.asyncio
async def test_fetch_for_ticker_short_circuits_when_not_configured():
    # No mocking needed -- this must return before any network call is made.
    client = RedditClient(config=RedditConfig(client_id=None, client_secret=None))
    assert await client.fetch_for_ticker("AAPL") == []
