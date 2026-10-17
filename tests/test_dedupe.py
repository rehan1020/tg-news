"""Tests for deduplication engine."""

from __future__ import annotations

import time

from src.feeds.models import FeedItem
from src.pipeline.canonical import canonicalize_url, hash_url
from src.pipeline.dedupe import deduplicate_items
from src.pipeline.simhash import compute_simhash
from src.state.manager import BotState


def _make_item(title: str, url: str) -> FeedItem:
    c_url = canonicalize_url(url)
    return FeedItem(
        id=hash_url(c_url),
        title=title,
        url=url,
        canonical_url=c_url,
        source_id="test_source",
        source_name="Test Source",
        sector="world",
        trust_tier="major",
        published_at=time.time(),
        simhash=compute_simhash(title),
    )


def test_dedupe_filters_seen_urls():
    state = BotState()
    item1 = _make_item("First Story Headline", "https://example.com/story-1")
    item2 = _make_item("Second Story Headline", "https://example.com/story-2")

    # Mark item1 as seen
    state.seen_hashes[item1.id] = time.time()

    unique, dropped = deduplicate_items([item1, item2], state)
    assert len(unique) == 1
    assert unique[0].id == item2.id
    assert dropped == 1


def test_re_run_yields_zero_duplicates():
    state = BotState()
    items = [
        _make_item("Headline 1", "https://example.com/item-1"),
        _make_item("Headline 2", "https://example.com/item-2"),
        _make_item("Headline 3", "https://example.com/item-3"),
    ]

    # First run
    unique_run1, dropped_run1 = deduplicate_items(items, state)
    assert len(unique_run1) == 3
    assert dropped_run1 == 0

    # Re-run with the same batch
    unique_run2, dropped_run2 = deduplicate_items(items, state)
    assert len(unique_run2) == 0
    assert dropped_run2 == 3


def test_intra_batch_deduplication():
    state = BotState()
    # Same canonical URL under different tracking params
    item1 = _make_item("Headline", "https://example.com/story?utm_source=a")
    item2 = _make_item("Headline", "https://example.com/story?utm_source=b")

    unique, dropped = deduplicate_items([item1, item2], state)
    assert len(unique) == 1
    assert dropped == 1
