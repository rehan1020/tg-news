"""Tests for digest slot scheduling, formatting, and delivery under cron jitter."""

from __future__ import annotations

import time
from datetime import datetime
from zoneinfo import ZoneInfo

from src.feeds.models import FeedItem
from src.telegram.digest import (
    check_due_digest_slots,
    format_digest_messages,
    item_to_digest_dict,
)


def test_digest_slot_fires_within_grace_window():
    """A slot fires on the first run at or after its scheduled time within the grace window."""
    tz = ZoneInfo("Asia/Kolkata")
    # Slot is 08:00, current time is 08:12 (within 45 min grace window)
    local_dt = datetime(2026, 10, 17, 8, 12, tzinfo=tz)
    digest_times = ["08:00", "18:00"]
    digest_history = {}

    slot_key = check_due_digest_slots(local_dt, digest_times, digest_history)
    assert slot_key == "2026-10-17_08:00"


def test_digest_slot_fires_once_under_jitter():
    """Slots fire exactly once under simulated cron jitter across consecutive runs."""
    tz = ZoneInfo("UTC")
    digest_times = ["08:00"]
    digest_history = {}

    # Run 1 at 08:07 (jittered +7m after slot)
    run1_dt = datetime(2026, 10, 17, 8, 7, tzinfo=tz)
    slot_key = check_due_digest_slots(run1_dt, digest_times, digest_history)
    assert slot_key == "2026-10-17_08:00"

    # Mark slot as fired
    digest_history[slot_key] = True

    # Run 2 at 08:22 (next cron run, +22m after slot)
    run2_dt = datetime(2026, 10, 17, 8, 22, tzinfo=tz)
    assert check_due_digest_slots(run2_dt, digest_times, digest_history) is None

    # Run 3 at 08:37 (third cron run, +37m after slot)
    run3_dt = datetime(2026, 10, 17, 8, 37, tzinfo=tz)
    assert check_due_digest_slots(run3_dt, digest_times, digest_history) is None


def test_digest_slot_outside_grace_window():
    """A slot does NOT fire if the current run is past the 45-minute grace window."""
    tz = ZoneInfo("UTC")
    # Slot 08:00, current time 08:50 (50 minutes late, outside 45m grace window)
    local_dt = datetime(2026, 10, 17, 8, 50, tzinfo=tz)
    digest_times = ["08:00"]
    assert check_due_digest_slots(local_dt, digest_times, {}) is None


def test_digest_slot_before_time():
    """A slot does not fire before its scheduled time."""
    tz = ZoneInfo("UTC")
    # Slot 08:00, current time 07:55
    local_dt = datetime(2026, 10, 17, 7, 55, tzinfo=tz)
    digest_times = ["08:00"]
    assert check_due_digest_slots(local_dt, digest_times, {}) is None


def test_format_digest_messages():
    """Digest formatter generates valid Telegram HTML with sector badges and links."""
    items = [
        {
            "headline": "Global Market Surge",
            "url": "https://example.com/market-surge",
            "sector": "markets",
            "source_name": "Financial Times",
            "published_at": time.time() - 3600,
            "cluster_size": 3,
            "summary": "• Global equities advanced on central bank policy clarity.\n• Tech led gains.",
        },
        {
            "headline": "Semiconductor Export Policy Update",
            "url": "https://example.com/chips-policy",
            "sector": "world",
            "source_name": "Reuters",
            "published_at": time.time() - 7200,
            "cluster_size": 1,
            "summary": "• New trade guidelines announced for high-bandwidth memory chips.",
        },
    ]

    messages = format_digest_messages(items, slot_label="Evening Digest")
    assert len(messages) >= 1
    msg = messages[0]

    assert "EVENING DIGEST" in msg
    assert "Global Market Surge" in msg
    assert "Financial Times" in msg
    assert "(+2 sources)" in msg
    assert '<a href="https://example.com/market-surge">Read original</a>' in msg
    assert "Semiconductor Export Policy Update" in msg


def test_format_digest_messages_chunking():
    """Very large digests with many items split into chunks smaller than 4096 characters."""
    # Generate 25 large items
    large_items = [
        {
            "headline": f"Major Geopolitical Economic Announcement Event Number {i}",
            "url": f"https://example.com/article-{i}",
            "sector": "world",
            "source_name": f"International Herald Tribune Outlet {i}",
            "published_at": time.time() - i * 60,
            "cluster_size": 2,
            "summary": (
                f"• Key point A describing international policy implications for story {i}.\n"
                f"• Key point B detailing diplomatic negotiations and treaty drafts for story {i}."
            ),
        }
        for i in range(25)
    ]

    messages = format_digest_messages(large_items, slot_label="Morning Digest")
    assert len(messages) > 1
    for msg in messages:
        assert len(msg) <= 4096


def test_item_to_digest_dict():
    """FeedItem properly converts to a dictionary representation."""
    feed_item = FeedItem(
        id="hash123",
        canonical_url="https://www.bbc.com/news/world-12345",
        source_id="bbc_world",
        source_name="BBC News",
        sector="world",
        trust_tier="major",
        title="Diplomatic Accord Signed in Geneva",
        url="https://www.bbc.com/news/world-12345",
        summary_raw="Delegates reached consensus on trade terms.",
        published_at=1700000000.0,
    )

    d = item_to_digest_dict(
        feed_item,
        cluster_size=4,
        score=0.68,
        summary="• Consensus reached on critical bilateral trade agreements.",
    )
    assert d["headline"] == "Diplomatic Accord Signed in Geneva"
    assert d["sector"] == "world"
    assert d["score"] == 0.68
    assert d["cluster_size"] == 4
    assert d["source_name"] == "BBC News"
    assert "Consensus reached" in d["summary"]
