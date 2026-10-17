"""Tests for feed health tracking, failure counters, and auto-disabling."""

from __future__ import annotations

import httpx
import pytest
import respx

from src.feeds.fetcher import MAX_CONSECUTIVE_FAILURES, FeedFetcher
from src.state.manager import BotState


@pytest.mark.asyncio
@respx.mock
async def test_feed_auto_disables_after_max_failures():
    """A feed failing repeatedly increments failures and auto-disables at the threshold."""
    fetcher = FeedFetcher()
    state = BotState()
    source_id = "unstable_feed"
    feed_url = "https://example.com/unstable.xml"

    # Mock 500 error
    respx.get(url__startswith=feed_url).respond(status_code=500)

    source = {
        "id": source_id,
        "name": "Unstable Feed",
        "url": feed_url,
        "enabled": True,
    }

    async with httpx.AsyncClient() as client:
        # Fail 4 times — not disabled yet
        for i in range(MAX_CONSECUTIVE_FAILURES - 1):
            items = await fetcher.fetch_feed(source, state, client)
            assert len(items) == 0
            assert state.feed_states[source_id]["consecutive_failures"] == i + 1
            assert state.feed_states[source_id].get("auto_disabled") is not True

        # 5th failure: triggers auto-disable
        items = await fetcher.fetch_feed(source, state, client)
        assert len(items) == 0
        assert state.feed_states[source_id]["consecutive_failures"] == MAX_CONSECUTIVE_FAILURES
        assert state.feed_states[source_id]["auto_disabled"] is True
        assert state.feed_states[source_id]["enabled"] is False

        # 6th attempt: skipped immediately without network request
        respx.reset()
        items = await fetcher.fetch_feed(source, state, client)
        assert len(items) == 0


@pytest.mark.asyncio
@respx.mock
async def test_feed_resets_failures_on_success():
    """A previously failing feed resets its counter and enabled state upon successful fetch."""
    fetcher = FeedFetcher()
    state = BotState()
    source_id = "recovering_feed"
    feed_url = "https://example.com/recovering.xml"

    # Set prior failures
    state.feed_states[source_id] = {
        "consecutive_failures": 3,
        "enabled": True,
        "auto_disabled": False,
    }

    # Mock successful response
    respx.get(url__startswith=feed_url).respond(
        status_code=200,
        text="""<?xml version="1.0"?>
        <rss version="2.0">
          <channel>
            <title>Recovered</title>
            <item><title>Item 1</title><link>https://example.com/1</link></item>
          </channel>
        </rss>""",
    )

    source = {
        "id": source_id,
        "name": "Recovering Feed",
        "url": feed_url,
        "enabled": True,
    }

    async with httpx.AsyncClient() as client:
        items = await fetcher.fetch_feed(source, state, client)
        assert len(items) == 1
        assert state.feed_states[source_id]["consecutive_failures"] == 0
        assert state.feed_states[source_id]["auto_disabled"] is False
        assert state.feed_states[source_id]["enabled"] is True
