"""Tests for feed fetching, conditional GET, and parsing."""

from __future__ import annotations

import httpx
import pytest
import respx

from src.feeds.fetcher import FeedFetcher
from src.state.manager import BotState

SAMPLE_RSS_XML = """<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0">
  <channel>
    <title>Sample News Channel</title>
    <link>https://example.com</link>
    <description>Sample News Channel Description</description>
    <item>
      <title>Markets Rally on Tech Earnings</title>
      <link>https://example.com/markets/tech-rally?utm_source=rss</link>
      <description>Tech stocks gained following strong quarterly results.</description>
      <pubDate>Mon, 17 Oct 2026 10:00:00 GMT</pubDate>
    </item>
  </channel>
</rss>
"""


@pytest.mark.asyncio
@respx.mock
async def test_conditional_get_sends_headers():
    fetcher = FeedFetcher()
    state = BotState()
    source_id = "test_feed"
    feed_url = "https://example.com/feed.xml"

    # Set prior ETag and Last-Modified in state
    state.feed_states[source_id] = {
        "etag": '"etag-12345"',
        "last_modified": "Mon, 17 Oct 2026 09:00:00 GMT",
    }

    # Mock 304 response
    route = respx.get(url__startswith=feed_url).respond(
        status_code=304,
        headers={"ETag": '"etag-12345"'},
    )

    source = {
        "id": source_id,
        "name": "Test Feed",
        "url": feed_url,
        "sector": "business",
        "trust_tier": "official",
        "enabled": True,
    }

    async with httpx.AsyncClient() as client:
        items = await fetcher.fetch_feed(source, state, client)

    assert len(items) == 0
    assert route.called
    req_headers = route.calls.last.request.headers
    assert req_headers.get("if-none-match") == '"etag-12345"'
    assert req_headers.get("if-modified-since") == "Mon, 17 Oct 2026 09:00:00 GMT"
    assert state.feed_states[source_id]["consecutive_failures"] == 0


@pytest.mark.asyncio
@respx.mock
async def test_feed_parse_success():
    fetcher = FeedFetcher()
    state = BotState()
    source_id = "test_feed"
    feed_url = "https://example.com/feed.xml"

    respx.get(url__startswith=feed_url).respond(
        status_code=200,
        text=SAMPLE_RSS_XML,
        headers={"ETag": '"new-etag-999"', "Last-Modified": "Tue, 18 Oct 2026 10:00:00 GMT"},
    )

    source = {
        "id": source_id,
        "name": "Sample News",
        "url": feed_url,
        "sector": "markets",
        "trust_tier": "specialist",
        "enabled": True,
    }

    async with httpx.AsyncClient() as client:
        items = await fetcher.fetch_feed(source, state, client)

    assert len(items) == 1
    item = items[0]
    assert item.title == "Markets Rally on Tech Earnings"
    assert "utm_source" not in item.canonical_url
    assert item.sector == "markets"
    assert item.trust_tier == "specialist"
    assert item.simhash != 0
    # State headers updated
    assert state.feed_states[source_id]["etag"] == '"new-etag-999"'
    assert state.feed_states[source_id]["consecutive_failures"] == 0


@pytest.mark.asyncio
@respx.mock
async def test_feed_http_error_increments_failure():
    fetcher = FeedFetcher()
    state = BotState()
    source_id = "failing_feed"
    feed_url = "https://example.com/failing.xml"

    respx.get(url__startswith=feed_url).respond(status_code=500)

    source = {
        "id": source_id,
        "name": "Failing",
        "url": feed_url,
        "enabled": True,
    }

    async with httpx.AsyncClient() as client:
        items = await fetcher.fetch_feed(source, state, client)

    assert len(items) == 0
    assert state.feed_states[source_id]["consecutive_failures"] == 1
